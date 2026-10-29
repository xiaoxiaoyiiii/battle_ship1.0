import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type BattlePassStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error' | 'anonymous'
export type BattlePassTrack = 'free' | 'premium'

export interface BattlePassSeason {
  id: string
  name: string
  startsAt: number | null
  endsAt: number | null
  claimEndsAt: number | null
  state: string
  levelCap: number
  totalXp: number
}

export interface BattlePassLevel {
  level: number
  xpAt: number
  freeKind: string
  freeRewardId: string
  premiumKind: string
  premiumRewardId: string
}

export interface BattlePassProgress {
  xp: number
  level: number
  premiumUnlocked: boolean
  version: number
}

export interface BattlePassChallenge {
  id: string
  title: string
  description: string
  metric: string
  target: number
  current: number
  xp: number
  completed: boolean
}

export interface BattlePassClaim {
  level: number
  track: BattlePassTrack
  rewardKind: string
  rewardId: string
  claimedAt: number | null
}

export interface BattlePassView {
  season: BattlePassSeason | null
  progress: BattlePassProgress
  levels: BattlePassLevel[]
  challenges: BattlePassChallenge[]
  claims: BattlePassClaim[]
  authenticated: boolean
  serverTime: number | null
}

interface JsonObject { [key: string]: unknown }

function object(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : null
}
function string(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}
function number(value: unknown, fallback = 0): number {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : fallback
}
function bool(value: unknown): boolean { return value === true || value === 1 }
function firstObject(body: JsonObject): JsonObject {
  return object(body.battle_pass) || object(body.data) || body
}
function parseSeason(value: unknown): BattlePassSeason | null {
  const row = object(value)
  if (!row || !string(row.id)) return null
  return {
    id: string(row.id),
    name: string(row.name || row.title, '深海远征'),
    startsAt: numberOrNull(row.starts_at ?? row.startsAt),
    endsAt: numberOrNull(row.ends_at ?? row.endsAt),
    claimEndsAt: numberOrNull(row.claim_ends_at ?? row.claimEndsAt),
    state: string(row.state || row.status, 'active'),
    levelCap: Math.max(1, number(row.level_cap ?? row.levelCap, 50)),
    totalXp: Math.max(0, number(row.total_xp ?? row.totalXp, 20000)),
  }
}
function numberOrNull(value: unknown): number | null {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}
function parseProgress(value: unknown, season: BattlePassSeason | null): BattlePassProgress {
  const row = object(value) || {}
  const xp = Math.max(0, number(row.xp ?? row.experience ?? row.current_xp))
  const level = Math.max(1, number(row.level ?? row.current_level, deriveLevel(xp, season)))
  return {
    xp,
    level,
    premiumUnlocked: bool(row.premium_unlocked ?? row.premiumUnlocked ?? row.is_premium),
    version: number(row.version),
  }
}
function deriveLevel(xp: number, season: BattlePassSeason | null): number {
  if (!season || season.totalXp <= 0) return 1
  return Math.max(1, Math.min(season.levelCap, Math.floor((xp / season.totalXp) * (season.levelCap - 1)) + 1))
}
function rewardField(row: JsonObject, nestedKey: string, field: string, nestedField: string): string {
  const nested = object(row[nestedKey])
  return string(row[field]) || string(nested?.[nestedField])
}
function parseLevels(value: unknown): BattlePassLevel[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    const row = object(item) || {}
    return {
      level: Math.max(1, number(row.level, 1)),
      xpAt: Math.max(0, number(row.xp_at ?? row.xpAt)),
      freeKind: rewardField(row, 'free_reward', 'free_kind', 'kind') || string(row.freeKind),
      freeRewardId: rewardField(row, 'free_reward', 'free_reward_id', 'id') || string(row.freeRewardId),
      premiumKind: rewardField(row, 'premium_reward', 'premium_kind', 'kind') || string(row.premiumKind),
      premiumRewardId: rewardField(row, 'premium_reward', 'premium_reward_id', 'id') || string(row.premiumRewardId),
    }
  }).sort((a, b) => a.level - b.level)
}
function parseChallenges(value: unknown): BattlePassChallenge[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    const row = object(item) || {}
    const target = Math.max(1, number(row.target))
    const current = Math.max(0, number(row.current ?? row.progress))
    return {
      id: string(row.id),
      title: string(row.title, '赛季挑战'),
      description: string(row.description, '完成指定对局目标'),
      metric: string(row.metric), target, current,
      xp: Math.max(0, number(row.xp ?? row.reward_xp)),
      completed: bool(row.completed) || current >= target,
    }
  }).filter((row) => row.id)
}
function parseClaims(value: unknown): BattlePassClaim[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    const row = object(item) || {}
    return {
      level: Math.max(1, number(row.level)),
      track: string(row.track) === 'premium' ? 'premium' : 'free',
      rewardKind: string(row.reward_kind ?? row.rewardKind),
      rewardId: string(row.reward_id ?? row.rewardId),
      claimedAt: numberOrNull(row.claimed_at ?? row.claimedAt),
    }
  })
}

function emptyView(): BattlePassView {
  return { season: null, progress: { xp: 0, level: 1, premiumUnlocked: false, version: 0 }, levels: [], challenges: [], claims: [], authenticated: false, serverTime: null }
}

export const useBattlePassStore = defineStore('battle-pass', () => {
  const status = ref<BattlePassStatus>('idle')
  const error = ref('')
  const view = ref<BattlePassView>(emptyView())
  const claiming = ref<string | null>(null)
  let requestToken = 0

  const season = computed(() => view.value.season)
  const progress = computed(() => view.value.progress)
  const levels = computed(() => view.value.levels)
  const challenges = computed(() => view.value.challenges)
  const claims = computed(() => view.value.claims)
  const claimKeys = computed(() => new Set(claims.value.map((claim) => `${claim.level}:${claim.track}`)))

  function isClaimed(level: number, track: BattlePassTrack): boolean { return claimKeys.value.has(`${level}:${track}`) }
  function canClaim(level: number, track: BattlePassTrack): boolean {
    if (!season.value || progress.value.level < level || isClaimed(level, track)) return false
    if (track === 'premium' && !progress.value.premiumUnlocked) return false
    const row = levels.value.find((item) => item.level === level)
    return Boolean(row && (track === 'free' ? row.freeRewardId : row.premiumRewardId))
  }

  function apply(body: unknown): void {
    const data = object(body)
    if (!data) throw new Error('通行证数据格式无效')
    const payload = firstObject(data)
    const nextSeason = parseSeason(payload.season)
    view.value = {
      season: nextSeason,
      progress: parseProgress(payload.progress, nextSeason),
      levels: parseLevels(payload.levels ?? payload.rewards),
      challenges: parseChallenges(payload.challenges),
      claims: parseClaims(payload.claims),
      authenticated: payload.authenticated === undefined ? true : bool(payload.authenticated),
      serverTime: numberOrNull(payload.server_time ?? payload.serverTime),
    }
  }

  async function load(force = false): Promise<void> {
    if (!force && (status.value === 'loading' || status.value === 'ready' || status.value === 'anonymous')) return
    const token = ++requestToken
    status.value = 'loading'; error.value = ''
    try {
      const response = await fetch('/api/battle-pass', { credentials: 'same-origin', headers: { accept: 'application/json' }, cache: 'no-store' })
      if (token !== requestToken) return
      if (response.status === 401) {
        view.value = emptyView(); status.value = 'anonymous'; return
      }
      if (!response.ok) throw new Error('通行证暂时无法读取')
      const body = await response.json()
      apply(body)
      status.value = view.value.season ? 'ready' : 'empty'
    } catch (cause) {
      if (token !== requestToken) return
      status.value = 'error'; error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function claim(level: number, track: BattlePassTrack): Promise<boolean> {
    if (!canClaim(level, track) || claiming.value) return false
    const key = `${level}:${track}`
    claiming.value = key; error.value = ''
    try {
      const response = await fetch('/api/battle-pass/claim', {
        method: 'POST', credentials: 'same-origin', headers: { accept: 'application/json', 'content-type': 'application/json' },
        body: JSON.stringify({ season_id: season.value?.id || undefined, level, track }),
      })
      if (!response.ok) throw new Error(response.status === 409 ? '奖励尚未达到领取条件' : '领取失败，请稍后再试')
      const body = await response.json().catch(() => null)
      const bodyObject = object(body)
      if (bodyObject && (bodyObject.season || bodyObject.progress || bodyObject.battle_pass || bodyObject.data)) apply(bodyObject)
      else await load(true)
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally { claiming.value = null }
  }

  function reset(): void { status.value = 'idle'; error.value = ''; view.value = emptyView(); claiming.value = null; requestToken += 1 }

  return { status, error, view, season, progress, levels, challenges, claims, claiming, load, claim, isClaimed, canClaim, reset }
})
