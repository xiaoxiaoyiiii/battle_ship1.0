import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import { useWalletStore, type WalletSource } from './wallet'

/**
 * Tide-ash shop.
 *
 * Live `GET /api/shop` and `POST /api/shop/purchase` win whenever they answer
 * with JSON. The fixture below is only a session stand-in for the same JSON
 * shape while that route is absent (404, or a non-JSON gateway failure).
 *
 * Prices and the opening balance live only in the fixture. They are not a
 * second economy: a live catalog replaces them wholesale.
 */
// Local mock 联调 only. Default false so a live API is required.
// Merging with the fixture enabled risks showing a fake balance and catalog.
// Enable with VITE_ALLOW_TIDE_FIXTURE=true (dev server or build env).
export const ALLOW_TIDE_FIXTURE = import.meta.env.VITE_ALLOW_TIDE_FIXTURE === 'true'

export type ShopStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error' | 'anonymous'
export type ShopReason =
  | 'purchased'
  | 'insufficient_funds'
  | 'already_owned'
  | 'item_unavailable'
  | 'unauthorized'
  | ''

export interface ShopItem {
  id: string
  kind: string
  name: string
  price: number
  owned: boolean
  purchasable: boolean
}

export interface ShopPurchaseResult {
  ok: boolean
  reason: ShopReason
  message: string
}

interface JsonObject { [key: string]: unknown }

interface FixtureItem {
  id: string
  kind: string
  name: string
  price: number
  owned: boolean
  purchasable: boolean
}

interface FixtureClaim {
  level: number
  track: 'free' | 'premium'
  reward_kind: string
  reward_id: string
  claimed_at: number
}

interface FixtureState {
  balance: number
  dailyMatchGranted: number
  items: FixtureItem[]
  claims: FixtureClaim[]
}

/**
 * Display names match `profile_spec` (read-only). Prices sit in the published
 * 300–450 band so the mock can both complete a purchase and refuse a dearer
 * one. `kelp_green` starts owned so the gray state is visible before a click.
 * Opening balance is session-only fixture state, not a grant rule.
 */
const FIXTURE_CATALOG: readonly FixtureItem[] = [
  { id: 'ember_wake', kind: 'frame', name: '余烬尾流', price: 400, owned: false, purchasable: true },
  { id: 'tideglass', kind: 'frame', name: '潮汐玻璃', price: 360, owned: false, purchasable: true },
  { id: 'abyssal_glow', kind: 'frame', name: '深渊冷焰', price: 450, owned: false, purchasable: true },
  { id: 'coral_dawn', kind: 'card_bg', name: '珊瑚晨曦', price: 380, owned: false, purchasable: true },
  { id: 'moonlit', kind: 'card_bg', name: '月下潮痕', price: 340, owned: false, purchasable: true },
  { id: 'kelp_green', kind: 'card_bg', name: '深海藻绿', price: 300, owned: true, purchasable: false },
  { id: 'stardust', kind: 'pointer_effect', name: '星尘航迹', price: 420, owned: false, purchasable: true },
  { id: 'pulse', kind: 'title_effect', name: '潮汐呼吸', price: 320, owned: false, purchasable: true },
  { id: 'aurora_drift', kind: 'profile_bg', name: '极光漂流', price: 350, owned: false, purchasable: true },
  { id: 'nebula_wake', kind: 'profile_bg', name: '星云尾迹', price: 410, owned: false, purchasable: true },
]

const FIXTURE_OPENING_BALANCE = 420
const FIXTURE_DAILY_CAP = 60
/** Contract sample: skip_if_owned converts this cosmetic claim into 20 tide ash. */
const FIXTURE_CONVERT_LEVEL = 6
const FIXTURE_CONVERT_TRACK = 'free' as const
const FIXTURE_CONVERT_AMOUNT = 20

const FIXTURE_LEVEL_REWARDS: Record<number, { free?: [string, string]; premium?: [string, string] }> = {
  2: { free: ['tide_ash', 'tide_ash:15'] },
  3: { free: ['currency', '15'] },
  4: { premium: ['tide_ash', 'tide_ash:15'] },
  5: { free: ['title', 'sailor'] },
  6: { free: ['frame', 'season_tide_ring'] },
  7: { free: ['tide_ash', 'tide_ash:15'] },
  12: { free: ['tide_ash', 'tide_ash:15'] },
}

let fixture: FixtureState | null = null
let shopUsesFixture = false
let passUsesFixture = false

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

export function shopKindLabel(kind: string): string {
  const key = kind.trim().toLowerCase().replace(/[\s-]+/g, '_')
  const labels: Record<string, string> = {
    frame: '头像框',
    card_bg: '名片底色',
    profile_bg: '资料背景',
    pointer_effect: '指针特效',
    title_effect: '称号特效',
    title: '称号',
  }
  return labels[key] || '外观'
}

export function shopReasonText(reason: string): string {
  switch (reason) {
    case 'purchased': return '购买成功'
    case 'insufficient_funds': return '徽记不足，这件外观还买不了'
    case 'already_owned': return '已经拥有这件外观'
    case 'item_unavailable': return '这件商品暂时不能购买'
    case 'unauthorized': return '请先登录后再购买'
    default: return '购买没有完成，请稍后再试'
  }
}

export async function readResponse(response: Response): Promise<{ json: JsonObject | null }> {
  const raw = await response.text()
  if (!raw) return { json: null }
  try {
    return { json: object(JSON.parse(raw) as unknown) }
  } catch {
    return { json: null }
  }
}

/** 404, or a gateway/proxy failure that never produced JSON. */
export function responseMissing(response: Response, json: JsonObject | null): boolean {
  if (response.status === 404) return true
  if (response.status >= 500 && json === null) return true
  return false
}

function fixtureState(): FixtureState {
  if (!fixture) {
    fixture = {
      balance: FIXTURE_OPENING_BALANCE,
      dailyMatchGranted: 0,
      items: FIXTURE_CATALOG.map((item) => ({ ...item })),
      claims: [],
    }
  }
  return fixture
}

export function resetTideFixture(): void {
  fixture = null
  shopUsesFixture = false
  passUsesFixture = false
}

export function tidePassUsesFixture(): boolean { return passUsesFixture }

function walletSnapshot(state: FixtureState) {
  return {
    balance: state.balance,
    dailyMatchGranted: state.dailyMatchGranted,
    dailyCap: FIXTURE_DAILY_CAP,
  }
}

/** Same integer curve as domain `level_xp` — fixture markers only. */
function fixtureLevelXp(level: number): number {
  const total = 18000
  const cap = 50
  const clamped = Math.min(cap, Math.max(1, level))
  return Math.floor((total * (clamped - 1)) / (cap - 1))
}

function fixtureLevels(): JsonObject[] {
  const rows: JsonObject[] = []
  for (let level = 1; level <= 50; level += 1) {
    const reward = FIXTURE_LEVEL_REWARDS[level]
    rows.push({
      level,
      xp_at: fixtureLevelXp(level),
      free_kind: reward?.free?.[0] || '',
      free_reward_id: reward?.free?.[1] || '',
      premium_kind: reward?.premium?.[0] || '',
      premium_reward_id: reward?.premium?.[1] || '',
    })
  }
  return rows
}

export function tideFixtureBattlePass(): JsonObject {
  const state = fixtureState()
  passUsesFixture = true
  return {
    ok: true,
    authenticated: true,
    wallet: { currency: 'tide_ash', ...walletSnapshot(state) },
    season: {
      id: 'fixture-deep-sea',
      name: '深海远征',
      state: 'active',
      level_cap: 50,
      total_xp: 18000,
    },
    progress: { xp: fixtureLevelXp(8), level: 8, premium_unlocked: false },
    levels: fixtureLevels(),
    challenges: [
      { id: 'fixture:voyage', metric: 'matches', target: 20, current: 4, xp: 800, completed: false, title: '远洋航线', description: '完成 20 场有效排位或休闲真人对局' },
      { id: 'fixture:cards', metric: 'cards', target: 50, current: 10, xp: 800, completed: false, title: '万法试航', description: '在有效真人对局中打出 50 张魔法卡' },
      { id: 'fixture:victories', metric: 'wins', target: 10, current: 3, xp: 1000, completed: false, title: '深海凯旋', description: '赢得 10 场排位或休闲真人对局' },
    ],
    claims: state.claims.map((claim) => ({ ...claim })),
  }
}

function tideAmount(rewardId: string): number {
  const tail = rewardId.includes(':') ? rewardId.slice(rewardId.lastIndexOf(':') + 1) : rewardId
  const amount = number(tail, 0)
  return amount > 0 ? Math.floor(amount) : 0
}

export function claimTideFixture(level: number, track: 'free' | 'premium'): { ok: boolean; body: JsonObject } {
  const state = fixtureState()
  const reward = FIXTURE_LEVEL_REWARDS[level]
  const pair = track === 'premium' ? reward?.premium : reward?.free
  if (!pair) return { ok: false, body: { ok: false, reason: 'reward_unavailable' } }
  if (state.claims.some((claim) => claim.level === level && claim.track === track)) {
    return { ok: true, body: { ...tideFixtureBattlePass(), ok: true, reason: 'already_claimed', converted_to_tide_ash: 0 } }
  }
  const [kind, rewardId] = pair
  let converted = 0
  if (level === FIXTURE_CONVERT_LEVEL && track === FIXTURE_CONVERT_TRACK) {
    converted = FIXTURE_CONVERT_AMOUNT
    state.balance += converted
  } else if (kind === 'tide_ash' || kind === 'currency') {
    state.balance += tideAmount(rewardId)
  }
  state.claims.push({
    level,
    track,
    reward_kind: kind,
    reward_id: rewardId,
    claimed_at: Date.now(),
  })
  return {
    ok: true,
    body: { ...tideFixtureBattlePass(), ok: true, reason: 'claimed', converted_to_tide_ash: converted },
  }
}

function purchaseTideFixture(itemId: string): { status: number; body: JsonObject } {
  const state = fixtureState()
  const item = state.items.find((row) => row.id === itemId)
  if (!item) {
    return { status: 404, body: { ok: false, reason: 'item_unavailable', balance: state.balance } }
  }
  if (item.owned || !item.purchasable) {
    return {
      status: 409,
      body: { ok: false, reason: 'already_owned', balance: state.balance, item: { id: item.id, kind: item.kind, owned: true } },
    }
  }
  if (state.balance < item.price) {
    return {
      status: 409,
      body: { ok: false, reason: 'insufficient_funds', balance: state.balance, item: { id: item.id, kind: item.kind, owned: false } },
    }
  }
  state.balance -= item.price
  item.owned = true
  item.purchasable = false
  return {
    status: 200,
    body: { ok: true, reason: 'purchased', balance: state.balance, item: { id: item.id, kind: item.kind, owned: true } },
  }
}

function parseItem(value: unknown): ShopItem | null {
  const row = object(value)
  if (!row) return null
  const id = string(row.id)
  if (!id) return null
  const owned = bool(row.owned)
  const purchasable = row.purchasable === undefined ? !owned : bool(row.purchasable) && !owned
  return {
    id,
    kind: string(row.kind),
    name: string(row.name, id),
    price: Math.max(0, number(row.price)),
    owned,
    purchasable,
  }
}

function parseReason(value: unknown): ShopReason {
  const reason = string(value)
  if (reason === 'purchased' || reason === 'insufficient_funds' || reason === 'already_owned' || reason === 'item_unavailable' || reason === 'unauthorized') {
    return reason
  }
  return ''
}

export const useShopStore = defineStore('shop', () => {
  const status = ref<ShopStatus>('idle')
  const error = ref('')
  const items = ref<ShopItem[]>([])
  const purchasing = ref<string | null>(null)
  const usingFixture = ref(false)
  let requestToken = 0

  const balance = computed(() => useWalletStore().balance)

  function publishFixture(): void {
    const state = fixtureState()
    shopUsesFixture = true
    usingFixture.value = true
    items.value = state.items.map((item) => ({ ...item }))
    useWalletStore().apply(walletSnapshot(state), 'fixture')
  }

  function publishApi(body: JsonObject): void {
    shopUsesFixture = false
    usingFixture.value = false
    const parsed = (Array.isArray(body.items) ? body.items : []).map(parseItem).filter((item): item is ShopItem => item !== null)
    items.value = parsed
    if (body.balance !== undefined) {
      const wallet = useWalletStore()
      const dailyGranted = body.daily_match_granted ?? body.dailyMatchGranted
      const dailyCap = body.daily_cap ?? body.dailyCap
      wallet.apply({
        balance: number(body.balance),
        dailyMatchGranted: dailyGranted === undefined ? wallet.dailyMatchGranted : number(dailyGranted),
        dailyCap: dailyCap === undefined ? wallet.dailyCap : number(dailyCap),
      }, 'api' satisfies WalletSource)
    }
  }

  function applyPurchase(body: JsonObject): void {
    const wallet = useWalletStore()
    if (body.balance !== undefined) {
      wallet.apply({
        balance: number(body.balance),
        dailyMatchGranted: wallet.dailyMatchGranted,
        dailyCap: wallet.dailyCap,
      }, usingFixture.value ? 'fixture' : 'api')
    }
    const patch = object(body.item)
    const id = string(patch?.id)
    if (!id) return
    const owned = patch?.owned === undefined ? parseReason(body.reason) === 'purchased' || parseReason(body.reason) === 'already_owned' : bool(patch.owned)
    items.value = items.value.map((item) => {
      if (item.id !== id) return item
      const nextOwned = owned || item.owned
      return {
        ...item,
        kind: string(patch?.kind, item.kind),
        owned: nextOwned,
        purchasable: nextOwned ? false : item.purchasable,
      }
    })
    if (usingFixture.value) {
      const state = fixtureState()
      const row = state.items.find((item) => item.id === id)
      if (row && owned) {
        row.owned = true
        row.purchasable = false
      }
    }
  }

  async function load(force = false): Promise<void> {
    const auth = useAuthStore()
    if (auth.isGuest) {
      requestToken += 1
      items.value = []
      error.value = ''
      usingFixture.value = false
      status.value = 'anonymous'
      useWalletStore().markAnonymous()
      return
    }
    if (!force && (status.value === 'loading' || status.value === 'ready' || status.value === 'anonymous')) return
    const token = ++requestToken
    status.value = 'loading'
    error.value = ''
    useWalletStore().markLoading()
    try {
      const response = await fetch('/api/shop', { credentials: 'same-origin', headers: { accept: 'application/json' }, cache: 'no-store' })
      const parsed = await readResponse(response)
      if (token !== requestToken) return
      if (response.status === 401) {
        items.value = []
        usingFixture.value = false
        status.value = 'anonymous'
        useWalletStore().markAnonymous()
        return
      }
      if (ALLOW_TIDE_FIXTURE && (responseMissing(response, parsed.json) || (parsed.json === null && !response.ok))) {
        publishFixture()
        status.value = items.value.length ? 'ready' : 'empty'
        return
      }
      if (!response.ok || !parsed.json || parsed.json.ok === false) throw new Error('商店暂时无法读取')
      publishApi(parsed.json)
      status.value = items.value.length ? 'ready' : 'empty'
    } catch (cause) {
      if (token !== requestToken) return
      if (ALLOW_TIDE_FIXTURE && cause instanceof TypeError) {
        publishFixture()
        status.value = items.value.length ? 'ready' : 'empty'
        return
      }
      status.value = 'error'
      error.value = cause instanceof Error ? cause.message : '商店暂时无法读取'
    }
  }

  async function purchase(itemId: string): Promise<ShopPurchaseResult> {
    const auth = useAuthStore()
    const fail = (reason: ShopReason): ShopPurchaseResult => ({ ok: false, reason, message: shopReasonText(reason) })
    if (auth.isGuest || status.value === 'anonymous') return fail('unauthorized')
    const current = items.value.find((item) => item.id === itemId)
    if (!current) return fail('item_unavailable')
    if (current.owned || !current.purchasable) return fail('already_owned')
    if (purchasing.value) return fail('')
    purchasing.value = itemId
    error.value = ''
    try {
      if (usingFixture.value || shopUsesFixture) {
        const result = purchaseTideFixture(itemId)
        applyPurchase(result.body)
        const reason = parseReason(result.body.reason)
        if (result.body.ok === true && reason === 'purchased') return { ok: true, reason: 'purchased', message: shopReasonText('purchased') }
        const resolved = reason || 'item_unavailable'
        error.value = shopReasonText(resolved)
        return { ok: false, reason: resolved, message: error.value }
      }
      const response = await fetch('/api/shop/purchase', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { accept: 'application/json', 'content-type': 'application/json' },
        body: JSON.stringify({ item_id: itemId }),
      })
      const parsed = await readResponse(response)
      if (response.status === 401) {
        status.value = 'anonymous'
        useWalletStore().markAnonymous()
        return fail('unauthorized')
      }
      const body = parsed.json || {}
      const reason = parseReason(body.reason) || (response.ok ? 'purchased' : '')
      if (body.balance !== undefined || body.item) applyPurchase(body)
      if (body.ok === true && reason === 'purchased') {
        if (!object(body.item)) {
          items.value = items.value.map((item) => item.id === itemId ? { ...item, owned: true, purchasable: false } : item)
        }
        return { ok: true, reason: 'purchased', message: shopReasonText('purchased') }
      }
      if (reason === 'already_owned') {
        items.value = items.value.map((item) => item.id === itemId ? { ...item, owned: true, purchasable: false } : item)
      }
      const resolved = reason || (response.status === 401 ? 'unauthorized' : 'item_unavailable')
      error.value = shopReasonText(resolved)
      return { ok: false, reason: resolved, message: error.value }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '购买没有完成，请稍后再试'
      return { ok: false, reason: '', message: error.value }
    } finally {
      purchasing.value = null
    }
  }

  function reset(): void {
    requestToken += 1
    status.value = 'idle'
    error.value = ''
    items.value = []
    purchasing.value = null
    usingFixture.value = false
    resetTideFixture()
    useWalletStore().reset()
  }

  return { status, error, items, purchasing, usingFixture, balance, load, purchase, reset }
})
