import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useWalletStore } from './wallet'

const GUEST_COMMANDER_KEY = 'battleship.commander.selected'

export interface CommanderSkillSpec {
  id: string
  name: string
  commander_id: string
  kind: 'limited' | 'cooldown' | 'per_chain'
  enters_chain: boolean
  speed: number | null
  max_uses: number | null
  cooldown_rounds: number
  requires_own_ship: boolean
  timing_label: string
  limit_label: string
  description: string
}

export interface CommanderProgress {
  xp: number
  max_xp: number
  level: number
  max_level: number
  is_max_level: boolean
  xp_in_level: number
  xp_needed: number
  progress_pct: number
}

export interface CommanderEquipped {
  portrait: string
  intro: string
  skill_vfx: string
  victory_motion: string
  avatar: string
  emoji_slot: string
}

export interface CommanderRewardTrackEntry {
  level: number
  label: string
  category: string
  milestone_tier?: number
  summary: string
  items: Array<{ kind: string; id: string; name: string }>
  unlocked: boolean
  claimed: boolean
  claimable: boolean
}

export interface CommanderSpecView {
  id: string
  name: string
  gender: string
  title_tagline: string
  outfit: string
  personality: string
  palette: { primary: string; secondary: string; accent: string; glow: string }
  skill: CommanderSkillSpec
  profile_cosmetics: Record<string, string>
  assets: {
    portraits: Record<string, string>
    avatar: string
    emojis: Record<string, string>
  }
  owned: boolean
  selected: boolean
  unlock_source: string | null
  cost_paid: number
  unlock_cost: number
  progress: CommanderProgress
  equipped: CommanderEquipped
  unlocked_options: {
    portraits: string[]
    intros: string[]
    skill_vfx: string[]
    victory_motions: string[]
    avatars: string[]
    emojis: string[]
  }
  claimed_levels: number[]
  claimable_levels: number[]
  reward_track: CommanderRewardTrackEntry[]
}

export interface CommanderViewResponse {
  ok: boolean
  authenticated: boolean
  tide_ash_balance: number
  unlock_cost: number
  free_initial_available: boolean
  selected_commander_id: string | null
  ai_daily_xp_used: number
  ai_daily_xp_cap: number
  day_cst: string
  commanders: CommanderSpecView[]
}

export interface CommanderSkillCastEvent {
  id: string
  player_id: string
  commander_id: string
  commander_name: string
  commander_level: number
  skill_id: string
  skill_name: string
  stage: 'resolve' | 'chain_enter' | 'negated' | 'reveal'
  negated?: boolean
  negated_by?: string | null
  success?: boolean
  draw_count?: number
  cells?: Array<{ x: number; y: number }>
  target_player_id?: string | null
  ts: number
}

export interface CommanderXpSettledPayload {
  player_id: string
  commander_id: string
  commander_name: string
  mode: string
  is_ai: boolean
  raw_xp: number
  delta: number
  reason: string
  before_xp: number
  after_xp: number
  before_level: number
  after_level: number
  leveled_up: boolean
  new_claimable_levels: number[]
  ai_daily_xp_used: number | null
  ai_daily_xp_cap: number | null
}

const COMMANDER_SVG_MODULES = import.meta.glob('/public/commanders/*/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

const COMMANDER_ART_MODULES = import.meta.glob('/public/commanders/*/art_*.webp', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

const COMMANDER_RIG_MODULES = import.meta.glob('/public/commanders/*/rig_*.png', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

export function commanderPortraitUrl(commanderId: string, variant = 'base'): string {
  const safeId = commanderId || 'chichao'
  const safeVar = ['base', 'ascended', 'alt', 'ultimate'].includes(variant) ? variant : 'base'
  const key = `/public/commanders/${safeId}/portrait_${safeVar}.svg`
  return COMMANDER_SVG_MODULES[key] ?? `/commanders/${safeId}/portrait_${safeVar}.svg`
}

export function commanderArtUrl(commanderId: string, variant = 'base'): string {
  const safeId = commanderId || 'chichao'
  const safeVar = ['base', 'ascended', 'alt', 'ultimate'].includes(variant) ? variant : 'base'
  const key = `/public/commanders/${safeId}/art_${safeVar}.webp`
  return COMMANDER_ART_MODULES[key] ?? `/commanders/${safeId}/art_${safeVar}.webp`
}

export function commanderRigUrl(commanderId: string, variant = 'base'): string {
  const safeId = commanderId || 'chichao'
  const safeVar = ['base', 'ascended', 'alt', 'ultimate'].includes(variant) ? variant : 'base'
  const key = `/public/commanders/${safeId}/rig_${safeVar}.png`
  return COMMANDER_RIG_MODULES[key] ?? `/commanders/${safeId}/rig_${safeVar}.png`
}

export function commanderAvatarUrl(commanderId: string): string {
  const safeId = commanderId || 'chichao'
  const key = `/public/commanders/${safeId}/avatar.svg`
  return COMMANDER_SVG_MODULES[key] ?? `/commanders/${safeId}/avatar.svg`
}

export function commanderEmojiUrl(commanderId: string, key = 'emoji_1'): string {
  const safeId = commanderId || 'chichao'
  const safeKey = key || 'emoji_1'
  const path = `/public/commanders/${safeId}/${safeKey}.svg`
  return COMMANDER_SVG_MODULES[path] ?? `/commanders/${safeId}/${safeKey}.svg`
}

export type CommanderPortraitVariant = 'base' | 'ascended' | 'alt' | 'ultimate'
export type CommanderIntroTier = 'base' | 'enhanced' | 'ultimate'
export type CommanderSkillVfxTier = 'base' | 'exclusive'
export type CommanderVictoryMotionTier = 'base' | 'exclusive'
export type CommanderEquippedLike = CommanderEquipped | Record<string, unknown>

export interface CommanderPalette {
  primary: string
  secondary: string
  accent: string
  glow: string
}

const COMMANDER_PALETTES: Record<string, CommanderPalette> = {
  chichao: {
    primary: '#e84855',
    secondary: '#1d141b',
    accent: '#ff9e7d',
    glow: 'rgba(232, 72, 85, 0.42)',
  },
  qingtong: {
    primary: '#4ea8de',
    secondary: '#14202e',
    accent: '#9be7ff',
    glow: 'rgba(78, 168, 222, 0.42)',
  },
  tieanchor: {
    primary: '#3b76f6',
    secondary: '#0f172a',
    accent: '#7dd3fc',
    glow: 'rgba(59, 118, 246, 0.42)',
  },
  guihang: {
    primary: '#eab354',
    secondary: '#191f2c',
    accent: '#fef08a',
    glow: 'rgba(234, 179, 84, 0.42)',
  },
}

const COMMANDER_FACE_FOCUS: Record<string, Record<CommanderPortraitVariant, string>> = {
  chichao: { base: '50% 29%', ascended: '50% 29%', alt: '50% 29%', ultimate: '50% 49%' },
  qingtong: { base: '50% 25%', ascended: '50% 25%', alt: '50% 25%', ultimate: '50% 25%' },
  tieanchor: { base: '50% 35%', ascended: '50% 35%', alt: '50% 35%', ultimate: '50% 35%' },
  guihang: { base: '50% 28%', ascended: '50% 28%', alt: '50% 28%', ultimate: '50% 27%' },
}

export function commanderPalette(commanderId: string): CommanderPalette {
  return COMMANDER_PALETTES[commanderId] ?? COMMANDER_PALETTES.chichao
}

export function commanderTierOf(level: number): 0 | 1 | 2 | 3 | 4 {
  if (level >= 20) return 4
  if (level >= 15) return 3
  if (level >= 10) return 2
  if (level >= 5) return 1
  return 0
}

export function commanderTierLabel(tier: number): string {
  return ['初任列舰', '伍级校尉', '拾级王牌', '拾伍统帅', '满阶海皇'][Math.max(0, Math.min(4, tier))] ?? '初任列舰'
}

export function portraitVariantFor(
  level: number,
  equipped?: { portrait?: string } | Record<string, unknown> | null,
): CommanderPortraitVariant {
  const chosen = typeof equipped?.portrait === 'string' ? equipped.portrait : ''
  if (chosen === 'base' || chosen === 'ascended' || chosen === 'alt' || chosen === 'ultimate') {
    return chosen
  }
  if (level >= 20) return 'ultimate'
  if (level >= 10) return 'ascended'
  return 'base'
}

export function portraitForLevelAndEquipped(
  commanderId: string,
  level: number,
  equipped?: { portrait?: string } | Record<string, unknown> | null,
): string {
  return commanderPortraitUrl(commanderId, portraitVariantFor(level, equipped))
}

export function commanderFaceFocus(
  commanderId: string,
  levelOrVariant: number | CommanderPortraitVariant = 'base',
  equipped?: { portrait?: string } | Record<string, unknown> | null,
): string {
  const variant =
    typeof levelOrVariant === 'string'
      ? levelOrVariant
      : portraitVariantFor(levelOrVariant, equipped)
  const map = COMMANDER_FACE_FOCUS[commanderId] ?? COMMANDER_FACE_FOCUS.chichao
  return map[variant] ?? map.base
}

export function commanderIntroForEquipped(
  level: number,
  equipped?: { intro?: string } | Record<string, unknown> | null,
): CommanderIntroTier {
  const chosen = typeof equipped?.intro === 'string' ? equipped.intro : ''
  if (chosen === 'base' || chosen === 'enhanced' || chosen === 'ultimate') {
    return chosen
  }
  if (level >= 20) return 'ultimate'
  if (level >= 15) return 'enhanced'
  return 'base'
}

export function commanderSkillVfxForEquipped(
  level: number,
  equipped?: { skill_vfx?: string } | Record<string, unknown> | null,
): CommanderSkillVfxTier {
  const chosen = typeof equipped?.skill_vfx === 'string' ? equipped.skill_vfx : ''
  if (chosen === 'base' || chosen === 'exclusive') {
    return chosen
  }
  return level >= 15 ? 'exclusive' : 'base'
}

export function commanderVictoryMotionForEquipped(
  level: number,
  equipped?: { victory_motion?: string } | Record<string, unknown> | null,
): CommanderVictoryMotionTier {
  const chosen = typeof equipped?.victory_motion === 'string' ? equipped.victory_motion : ''
  if (chosen === 'base' || chosen === 'exclusive') {
    return chosen
  }
  return level >= 13 ? 'exclusive' : 'base'
}

function readGuestSelected(): string {
  try {
    const raw = window.localStorage.getItem(GUEST_COMMANDER_KEY)
    return raw && ['chichao', 'qingtong', 'tieanchor', 'guihang'].includes(raw) ? raw : 'chichao'
  } catch {
    return 'chichao'
  }
}

function writeGuestSelected(id: string): void {
  try {
    window.localStorage.setItem(GUEST_COMMANDER_KEY, id)
  } catch {
    // 隐私模式下忽略写入失败
  }
}

export const useCommandersStore = defineStore('commanders', () => {
  const view = ref<CommanderViewResponse | null>(null)
  const loading = ref(false)
  const loaded = ref(false)
  const busy = ref(false)
  const error = ref('')
  const guestSelectedId = ref<string>(readGuestSelected())
  const lastSkillEvent = ref<CommanderSkillCastEvent | null>(null)
  const lastXpSettled = ref<CommanderXpSettledPayload | null>(null)
  const consumedSkillEventIds = new Set<string>()
  let currentAudio: HTMLAudioElement | null = null

  const commanders = computed(() => view.value?.commanders ?? [])
  const selectedCommanderId = computed(() => {
    const data = view.value
    if (data?.authenticated) {
      if (data.selected_commander_id) return data.selected_commander_id
      const firstOwned = data.commanders.find((c) => c.owned)
      if (firstOwned) return firstOwned.id
      return guestSelectedId.value
    }
    return guestSelectedId.value
  })
  const selectedCommander = computed(
    () => commanders.value.find((c) => c.id === selectedCommanderId.value) ?? commanders.value[0] ?? null,
  )
  const freeInitialAvailable = computed(() => Boolean(view.value?.authenticated && view.value?.free_initial_available))
  const totalClaimableCount = computed(() =>
    commanders.value.reduce((acc, item) => acc + (item.owned ? item.claimable_levels.length : 0), 0),
  )

  async function load(force = false): Promise<void> {
    if (loading.value || (loaded.value && !force)) return
    loading.value = true
    error.value = ''
    try {
      const response = await fetch('/api/commanders', {
        headers: { accept: 'application/json' },
        credentials: 'same-origin',
      })
      const body = (await response.json().catch(() => null)) as CommanderViewResponse | null
      if (!response.ok || !body?.ok) {
        error.value = '暂时未能加载指挥官档案'
        return
      }
      view.value = body
      loaded.value = true
      if (body.authenticated && typeof body.tide_ash_balance === 'number') {
        useWalletStore().apply({ balance: body.tide_ash_balance }, 'api')
      }
      if (body.authenticated && body.selected_commander_id) {
        guestSelectedId.value = body.selected_commander_id
      }
    } catch {
      error.value = '网络繁忙，加载指挥官数据失败'
    } finally {
      loading.value = false
    }
  }

  async function postAction(
    path: string,
    payload: Record<string, unknown>,
  ): Promise<{ ok: boolean; message?: string }> {
    busy.value = true
    error.value = ''
    try {
      const response = await fetch(path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', accept: 'application/json' },
        body: JSON.stringify(payload),
      })
      const body = (await response.json().catch(() => ({}))) as CommanderViewResponse & {
        ok?: boolean
        message?: string
      }
      if (!response.ok || !body?.ok) {
        const msg = body?.message || '操作未能生效'
        error.value = msg
        return { ok: false, message: msg }
      }
      if (Array.isArray(body.commanders)) {
        view.value = body
        loaded.value = true
        if (body.authenticated && typeof body.tide_ash_balance === 'number') {
          useWalletStore().apply({ balance: body.tide_ash_balance }, 'api')
        }
      }
      return { ok: true, message: body.message }
    } catch {
      const msg = '网络不稳定，请稍后重试'
      error.value = msg
      return { ok: false, message: msg }
    } finally {
      busy.value = false
    }
  }

  async function unlock(commanderId: string): Promise<{ ok: boolean; message?: string }> {
    const res = await postAction('/api/commanders/unlock', { commander_id: commanderId })
    if (res.ok) {
      guestSelectedId.value = commanderId
      writeGuestSelected(commanderId)
    }
    return res
  }

  async function select(commanderId: string): Promise<{ ok: boolean; message?: string }> {
    if (!view.value?.authenticated) {
      guestSelectedId.value = commanderId
      writeGuestSelected(commanderId)
      return { ok: true, message: '已切换出战指挥官' }
    }
    const target = commanders.value.find((c) => c.id === commanderId)
    if (!target?.owned) {
      return { ok: false, message: '请先解锁该指挥官' }
    }
    const res = await postAction('/api/commanders/select', { commander_id: commanderId })
    if (res.ok) {
      guestSelectedId.value = commanderId
      writeGuestSelected(commanderId)
    }
    return res
  }

  async function claim(
    commanderId: string,
    level?: number,
    claimAll = false,
  ): Promise<{ ok: boolean; message?: string }> {
    return postAction('/api/commanders/claim', {
      commander_id: commanderId,
      ...(typeof level === 'number' ? { level } : {}),
      ...(claimAll ? { claim_all: true } : {}),
    })
  }

  async function equip(
    commanderId: string,
    patch: Record<string, string>,
  ): Promise<{ ok: boolean; message?: string }> {
    return postAction('/api/commanders/equip', {
      commander_id: commanderId,
      equipped: patch,
    })
  }

  function recordSkillUsed(payload: Record<string, unknown>): void {
    const stage = String(payload.stage || 'resolve') as CommanderSkillCastEvent['stage']
    const ev: CommanderSkillCastEvent = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      player_id: String(payload.player_id || ''),
      commander_id: String(payload.commander_id || 'chichao'),
      commander_name: String(payload.commander_name || ''),
      commander_level: Number(payload.commander_level || 1),
      skill_id: String(payload.skill_id || ''),
      skill_name: String(payload.skill_name || ''),
      stage,
      negated: Boolean(payload.negated),
      negated_by: typeof payload.negated_by === 'string' ? payload.negated_by : null,
      success: typeof payload.success === 'boolean' ? payload.success : undefined,
      draw_count: typeof payload.draw_count === 'number' && payload.draw_count > 0 ? payload.draw_count : undefined,
      cells: Array.isArray(payload.cells) ? (payload.cells as Array<{ x: number; y: number }>) : undefined,
      target_player_id: typeof payload.target_player_id === 'string' ? payload.target_player_id : null,
      ts: Date.now(),
    }
    lastSkillEvent.value = ev
  }

  function recordXpSettled(payload: Record<string, unknown>): void {
    lastXpSettled.value = {
      player_id: String(payload.player_id || ''),
      commander_id: String(payload.commander_id || ''),
      commander_name: String(payload.commander_name || ''),
      mode: String(payload.mode || ''),
      is_ai: Boolean(payload.is_ai),
      raw_xp: Number(payload.raw_xp || 0),
      delta: Number(payload.delta || 0),
      reason: String(payload.reason || ''),
      before_xp: Number(payload.before_xp || 0),
      after_xp: Number(payload.after_xp || 0),
      before_level: Number(payload.before_level || 1),
      after_level: Number(payload.after_level || 1),
      leveled_up: Boolean(payload.leveled_up),
      new_claimable_levels: Array.isArray(payload.new_claimable_levels)
        ? payload.new_claimable_levels.map((n) => Number(n))
        : [],
      ai_daily_xp_used: payload.ai_daily_xp_used == null ? null : Number(payload.ai_daily_xp_used),
      ai_daily_xp_cap: payload.ai_daily_xp_cap == null ? null : Number(payload.ai_daily_xp_cap),
    }
    void load(true)
  }

  function isSkillEventFresh(ev: CommanderSkillCastEvent | null, maxAgeMs = 1500): boolean {
    if (!ev) return false
    if (consumedSkillEventIds.has(ev.id)) return false
    return Date.now() - ev.ts <= maxAgeMs
  }

  function consumeSkillEvent(id: string): boolean {
    if (!id || consumedSkillEventIds.has(id)) return false
    consumedSkillEventIds.add(id)
    if (consumedSkillEventIds.size > 80) {
      const first = consumedSkillEventIds.values().next().value
      if (first) consumedSkillEventIds.delete(first)
    }
    return true
  }

  function clearSkillEvents(): void {
    if (lastSkillEvent.value?.id) consumedSkillEventIds.add(lastSkillEvent.value.id)
    lastSkillEvent.value = null
  }

  function clearMatchSettlement(): void {
    lastXpSettled.value = null
    clearSkillEvents()
  }

  return {
    view,
    loading,
    loaded,
    busy,
    error,
    commanders,
    selectedCommanderId,
    selectedCommander,
    freeInitialAvailable,
    totalClaimableCount,
    lastSkillEvent,
    lastXpSettled,
    load,
    unlock,
    select,
    claim,
    equip,
    recordSkillUsed,
    recordXpSettled,
    isSkillEventFresh,
    consumeSkillEvent,
    clearSkillEvents,
    clearMatchSettlement,
  }
})
