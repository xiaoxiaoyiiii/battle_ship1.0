import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useShopStore } from './shop'
import { useWalletStore } from './wallet'

/**
 * 每日签到（GET/POST /api/checkin）。
 *
 * 能不能签、红点、今天是哪一天，只认服务端字段（today / today_checked /
 * show_red_dot / already_checked）。这里不推算上海日历。
 * `today` 只用来画服务端指定的那一个月，以及给「当天已自动弹出」做本地键。
 */

export const CHECKIN_AUTO_SHOWN_PREFIX = 'battleship.checkin.autoShown'
const DEFAULT_DAILY = 15
const DEFAULT_MILESTONES: Record<number, number> = { 7: 80, 14: 150, 30: 300 }
const MILESTONE_DAYS = [7, 14, 30]

export type CheckinCellState = 'checked' | 'today' | 'unchecked'

export interface CheckinMilestone {
  days: number
  amount: number
  title: string
  reached: boolean
  claimed: boolean
}

export interface CheckinView {
  today: string
  year: number | null
  month: number | null
  day: number | null
  todayChecked: boolean
  monthCount: number
  checkedDays: number[]
  daysInMonth: number
  dailyAmount: number
  milestones: CheckinMilestone[]
  title: string
  balance: number | null
  showRedDot: boolean
}

export interface CheckinClaimResult {
  ok: boolean
  alreadyChecked: boolean
  needsLogin: boolean
  gained: number | null
  titleName: string | null
}

const SERVER_DAY = /^(\d{4})-(\d{1,2})-(\d{1,2})/

export function checkinAutoShownKey(userId: string, today: string): string {
  return `${CHECKIN_AUTO_SHOWN_PREFIX}:${userId}:${today}`
}

export function readCheckinAutoShown(userId: string, today: string): boolean {
  try {
    return localStorage.getItem(checkinAutoShownKey(userId, today)) === '1'
  } catch {
    return false
  }
}

export function writeCheckinAutoShown(userId: string, today: string): void {
  try {
    localStorage.setItem(checkinAutoShownKey(userId, today), '1')
  } catch {
    // 记不住就下次进主屏再提示一次；红点仍由服务端决定。
  }
}

export function parseServerDay(today: string): { year: number; month: number; day: number } | null {
  const match = SERVER_DAY.exec(today.trim())
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  return { year, month, day }
}

/** 周一为一列。只用服务端年月日的公历位置，不读取本机「今天」。 */
export function mondayOffset(year: number, month: number): number {
  const sunday0 = new Date(Date.UTC(year, month - 1, 1)).getUTCDay()
  return (sunday0 + 6) % 7
}

export function daysInCalendarMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

export function checkinCellState(day: number, view: CheckinView): CheckinCellState {
  const isToday = view.day !== null && day === view.day
  if (isToday) return view.todayChecked ? 'checked' : 'today'
  if (view.checkedDays.includes(day)) return 'checked'
  return 'unchecked'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function asInt(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  if (!Number.isFinite(n)) return null
  const whole = Math.trunc(n)
  return whole >= 0 ? whole : null
}

function amountOf(row: Record<string, unknown>): number | null {
  return asInt(row.tide ?? row.amount ?? row.tide_ash ?? row.tideAsh ?? row.reward ?? row.value ?? row.ash)
}

function titleText(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  const row = asRecord(value)
  return typeof row?.name === 'string' ? row.name.trim() : ''
}

function messageFrom(body: unknown): string {
  const row = asRecord(body)
  if (!row) return ''
  if (typeof row.error === 'string' && row.error.trim()) return row.error.trim()
  const nested = asRecord(row.error)
  if (typeof nested?.message === 'string' && nested.message.trim()) return nested.message.trim()
  if (typeof row.message === 'string' && row.message.trim()) return row.message.trim()
  return ''
}

function parseCheckedDays(value: unknown, today: { year: number; month: number } | null, daysInMonth: number): number[] {
  if (!Array.isArray(value)) return []
  const days: number[] = []
  for (const item of value) {
    if (typeof item === 'number' || (typeof item === 'string' && !item.includes('-'))) {
      const n = asInt(item)
      if (n !== null && n >= 1 && n <= daysInMonth) days.push(n)
      continue
    }
    if (typeof item === 'string') {
      const parsed = parseServerDay(item)
      if (!parsed) continue
      if (today && (parsed.year !== today.year || parsed.month !== today.month)) continue
      if (parsed.day >= 1 && parsed.day <= daysInMonth) days.push(parsed.day)
      continue
    }
    const row = asRecord(item)
    if (!row) continue
    const direct = asInt(row.day ?? row.d)
    if (direct !== null && direct >= 1 && direct <= daysInMonth) {
      days.push(direct)
      continue
    }
    if (typeof row.date === 'string') {
      const parsed = parseServerDay(row.date)
      if (!parsed) continue
      if (today && (parsed.year !== today.year || parsed.month !== today.month)) continue
      if (parsed.day >= 1 && parsed.day <= daysInMonth) days.push(parsed.day)
    }
  }
  return [...new Set(days)].sort((a, b) => a - b)
}

interface MilestoneBits {
  amount: number | null
  title: string
  reached: boolean | null
  claimed: boolean | null
}

function parseMilestoneMap(rewards: unknown): Map<number, MilestoneBits> {
  const map = new Map<number, MilestoneBits>()
  const root = asRecord(rewards)
  const raw = root?.milestones ?? root?.milestone
  const absorb = (days: number, row: Record<string, unknown> | null, amount: number | null) => {
    if (days <= 0) return
    map.set(days, {
      amount,
      title: row ? titleText(row.title) : '',
      reached: typeof row?.reached === 'boolean' ? row.reached : null,
      claimed: typeof row?.claimed === 'boolean' ? row.claimed : null,
    })
  }
  if (Array.isArray(raw)) {
    for (const item of raw) {
      const row = asRecord(item)
      if (!row) continue
      const days = asInt(row.days ?? row.day ?? row.count ?? row.threshold ?? row.need ?? row.at)
      if (days === null) continue
      absorb(days, row, amountOf(row))
    }
    return map
  }
  const record = asRecord(raw)
  if (!record) return map
  for (const [key, item] of Object.entries(record)) {
    const days = asInt(key)
    if (days === null) continue
    const row = asRecord(item)
    if (row) absorb(days, row, amountOf(row))
    else absorb(days, null, asInt(item))
  }
  return map
}

function parseDaily(rewards: unknown, previous: number | null): number {
  const root = asRecord(rewards)
  if (!root) return previous ?? DEFAULT_DAILY
  const daily = root.daily ?? root.daily_reward ?? root.dailyReward
  const row = asRecord(daily)
  const amount = asInt(daily) ?? (row ? amountOf(row) : null)
  return amount ?? previous ?? DEFAULT_DAILY
}

function fallbackTitle(parsed: { year: number; month: number } | null, previous: string): string {
  if (!parsed) return previous
  return `潮汐签到·${parsed.year}年${parsed.month}月`
}

function buildMilestones(
  map: Map<number, MilestoneBits>,
  monthCount: number,
  title: string,
): CheckinMilestone[] {
  const days = new Set<number>([...MILESTONE_DAYS, ...map.keys()])
  return [...days].sort((a, b) => a - b).map((day) => {
    const found = map.get(day)
    return {
      days: day,
      amount: found?.amount ?? DEFAULT_MILESTONES[day] ?? 0,
      title: day === 30 ? (title || found?.title || '') : (found?.title || ''),
      reached: found?.reached ?? monthCount >= day,
      claimed: found?.claimed ?? false,
    }
  })
}

export function parseCheckinPayload(body: unknown, previous: CheckinView | null, source: 'get' | 'post'): CheckinView | null {
  const row = asRecord(body)
  if (!row) return source === 'post' ? previous : null
  const today = typeof row.today === 'string' && row.today.trim() ? row.today.trim() : (previous?.today ?? '')
  if (!today) return null
  const parsed = parseServerDay(today)
  const daysInMonthRaw = asInt(row.days_in_month ?? row.daysInMonth)
  const daysInMonth = daysInMonthRaw !== null && daysInMonthRaw >= 28 && daysInMonthRaw <= 31
    ? daysInMonthRaw
    : parsed ? daysInCalendarMonth(parsed.year, parsed.month) : (previous?.daysInMonth ?? 30)
  const todayParts = parsed ? { year: parsed.year, month: parsed.month } : null
  let checkedDays: number[]
  if (Array.isArray(row.checked_days) || Array.isArray(row.checkedDays)) {
    checkedDays = parseCheckedDays(row.checked_days ?? row.checkedDays, todayParts, daysInMonth)
  } else if (previous) {
    checkedDays = previous.checkedDays.filter((day) => day >= 1 && day <= daysInMonth)
  } else {
    checkedDays = []
  }
  let todayChecked: boolean
  if (typeof row.today_checked === 'boolean') todayChecked = row.today_checked
  else if (typeof row.todayChecked === 'boolean') todayChecked = row.todayChecked
  else if (row.already_checked === true || row.alreadyChecked === true) todayChecked = true
  else if (source === 'post') todayChecked = true
  else todayChecked = false
  if (source === 'post' && todayChecked && parsed && !checkedDays.includes(parsed.day) && !Array.isArray(row.checked_days) && !Array.isArray(row.checkedDays)) {
    checkedDays = [...checkedDays, parsed.day].sort((a, b) => a - b)
  }
  const monthRaw = asInt(row.month_count ?? row.monthCount)
  let monthCount = monthRaw
  if (monthCount === null) {
    if (Array.isArray(row.checked_days) || Array.isArray(row.checkedDays)) monthCount = checkedDays.length
    else if (previous && source === 'post' && todayChecked && !previous.todayChecked) monthCount = previous.monthCount + 1
    else monthCount = previous?.monthCount ?? checkedDays.length
  }
  const explicitDot = row.show_red_dot ?? row.showRedDot
  const showRedDot = typeof explicitDot === 'boolean' ? explicitDot : !todayChecked
  const rewardPayload = row.rewards
  const keepRewards = rewardPayload === undefined && previous !== null
  const dailyAmount = keepRewards ? previous.dailyAmount : parseDaily(rewardPayload, previous?.dailyAmount ?? null)
  const rewardMap = keepRewards ? null : parseMilestoneMap(rewardPayload)
  const explicitTitle = titleText(row.title)
  const rewardTitle = rewardMap?.get(30)?.title ?? ''
  const year = asInt(row.year) ?? parsed?.year ?? null
  const serverMonth = asInt(row.month)
  const month = serverMonth !== null && serverMonth >= 1 && serverMonth <= 12 ? serverMonth : (parsed?.month ?? null)
  const day = parsed && (year === null || parsed.year === year) && (month === null || parsed.month === month)
    ? parsed.day
    : null
  const title = explicitTitle || rewardTitle || previous?.title || fallbackTitle(year !== null && month !== null ? { year, month } : null, '')
  const milestones = keepRewards
    ? previous.milestones.map((item) => ({
      ...item,
      reached: monthCount >= item.days,
      title: item.days === 30 ? title : item.title,
    }))
    : buildMilestones(rewardMap ?? new Map(), monthCount, title)
  const balance = typeof row.balance === 'number' && Number.isFinite(row.balance) ? row.balance : (previous?.balance ?? null)
  return {
    today,
    year,
    month,
    day,
    todayChecked,
    monthCount,
    checkedDays,
    daysInMonth,
    dailyAmount,
    milestones,
    title,
    balance,
    showRedDot,
  }
}

function grantSummary(body: Record<string, unknown>): { gained: number | null; titleName: string | null } {
  const granted = asRecord(body.granted)
  if (!granted) return { gained: null, titleName: null }
  const daily = asInt(granted.daily_tide)
  const milestone = asInt(granted.milestone_tide)
  const gained = daily === null && milestone === null ? null : (daily ?? 0) + (milestone ?? 0)
  const titleName = titleText(granted.title)
  return { gained, titleName: titleName || null }
}

async function publishBalance(balance: number | null, stillCurrent: () => boolean): Promise<void> {
  if (!stillCurrent()) return
  const wallet = useWalletStore()
  if (balance !== null) wallet.apply({ balance }, 'api')
  await useShopStore().load(true)
  if (!stillCurrent()) return
  // 商店刷新若带回旧余额，仍以这次签到返回的余额为准。
  if (balance !== null) wallet.apply({ balance }, 'api')
}

export const useCheckinStore = defineStore('checkin', () => {
  const status = ref<CheckinView | null>(null)
  const loading = ref(false)
  const claiming = ref(false)
  const error = ref('')
  let generation = 0
  // 只在 reset（登出 / 换号）时递增。load 的请求序号不能取消同账号正在进行的签到。
  let session = 0

  const today = computed(() => status.value?.today ?? '')
  const todayChecked = computed(() => status.value?.todayChecked === true)
  const showRedDot = computed(() => status.value?.showRedDot === true)

  function reset(): void {
    generation += 1
    session += 1
    status.value = null
    error.value = ''
    loading.value = false
    claiming.value = false
    // 签到之后的商店刷新还在飞。不抬商店的请求序号，旧账号的余额会在换号后写进来。
    useShopStore().reset()
  }

  async function load(): Promise<void> {
    const token = ++generation
    loading.value = true
    try {
      const response = await fetch('/api/checkin', {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { accept: 'application/json' },
      })
      if (token !== generation) return
      if (response.status === 401) {
        reset()
        return
      }
      const body: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(messageFrom(body) || '签到日历暂时读不出来，请稍后再试。')
      const next = parseCheckinPayload(body, null, 'get')
      if (!next) throw new Error('签到数据异常')
      if (token !== generation) return
      status.value = next
      error.value = ''
    } catch (cause) {
      if (token === generation) error.value = cause instanceof Error ? cause.message : '签到日历暂时读不出来，请稍后再试。'
    } finally {
      if (token === generation) loading.value = false
    }
  }

  async function claim(): Promise<CheckinClaimResult> {
    const dropped: CheckinClaimResult = { ok: false, alreadyChecked: false, needsLogin: false, gained: null, titleName: null }
    if (claiming.value) return dropped
    if (status.value?.todayChecked) return { ok: true, alreadyChecked: true, needsLogin: false, gained: null, titleName: null }
    const token = session
    claiming.value = true
    error.value = ''
    try {
      const response = await fetch('/api/checkin', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { accept: 'application/json' },
      })
      const body: unknown = await response.json().catch(() => null)
      if (token !== session) return dropped
      const row = asRecord(body) ?? {}
      if (response.status === 401) {
        reset()
        return { ok: false, alreadyChecked: false, needsLogin: true, gained: null, titleName: null }
      }
      const already = row.already_checked === true || row.alreadyChecked === true
      if (!response.ok && !already) {
        error.value = messageFrom(body) || '签到没有成功，请稍后再试。'
        return { ok: false, alreadyChecked: false, needsLogin: false, gained: null, titleName: null }
      }
      if (token !== session) return dropped
      const next = parseCheckinPayload(body, status.value, 'post')
      if (token !== session) return dropped
      if (next) status.value = next
      const balance = typeof row.balance === 'number' && Number.isFinite(row.balance) ? row.balance : null
      await publishBalance(balance, () => token === session)
      if (token !== session) return dropped
      claiming.value = false
      void load()
      const summary = already ? { gained: null, titleName: null } : grantSummary(row)
      return {
        ok: true,
        alreadyChecked: already,
        needsLogin: false,
        gained: summary.gained,
        titleName: summary.titleName,
      }
    } catch (cause) {
      if (token !== session) return dropped
      error.value = cause instanceof Error ? cause.message : '签到没有成功，请稍后再试。'
      return { ok: false, alreadyChecked: false, needsLogin: false, gained: null, titleName: null }
    } finally {
      if (token === session) claiming.value = false
    }
  }

  return { status, loading, claiming, error, today, todayChecked, showRedDot, load, claim, reset }
})
