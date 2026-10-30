import type { GameOverRecord, JsonObject } from '../../stores/result'

/**
 * Pure view helpers for the settlement screen (ticket #22).
 *
 * These only format server-authoritative values; no rank/XP rule is
 * recomputed here. Keeping them outside the SFC makes the text rules one
 * implementation (the legacy screen had the reason sentence written twice).
 */
export type Outcome = 'win' | 'lose' | 'draw' | 'unknown' | 'none'

export function outcomeOf(record: GameOverRecord | null, playerId: string): Outcome {
  if (!record) return 'none'
  if (record.winner === null) return 'draw'
  if (!playerId) return 'unknown'
  return record.winner === playerId ? 'win' : 'lose'
}

export function verdictText(outcome: Outcome): string {
  switch (outcome) {
    case 'win':
      return '胜 利'
    case 'lose':
      return '失 败'
    case 'draw':
      return '平 局'
    case 'unknown':
      return '对局结束'
    default:
      return '结算'
  }
}

/** End reason in the current viewpoint; null means no extra sentence. */
export function reasonText(reason: string, won: boolean): string | null {
  const text = String(reason ?? '').trim()
  if (!text) return null
  if (text === 'surrender') return won ? '对方投降' : '我方投降'
  if (text === 'opponent_disconnected') return won ? '对手掉线超时' : '我方掉线超时'
  if (text === 'timeout') return '操作超时'
  return text
}

/** The one-line explanation under the verdict (legacy wording preserved). */
export function summaryText(record: GameOverRecord, outcome: Outcome, round: number): string {
  const won = outcome === 'win'
  const parts: string[] = []
  const why = reasonText(record.reason, won)
  if (outcome === 'draw') {
    if (why) parts.push(why)
    parts.push('双方未分胜负')
  } else if (outcome === 'unknown') {
    if (why) parts.push(why)
    parts.push('已分出胜负')
  } else if (why) {
    parts.push(why)
    parts.push(won ? '你获胜' : '你落败')
  } else {
    parts.push(won ? '击沉对方全部战舰' : '你的舰队被击沉')
  }
  if (round > 0) parts.push(round + ' 回合')
  return parts.join(' · ')
}

export function modeText(ranked: boolean, mode: string): string {
  if (ranked || mode === 'ranked') return '排位赛'
  if (mode === 'ai') return '人机对战'
  if (mode === 'custom') return '自定义房'
  return '休闲赛'
}

export type MatchMode = 'ranked' | 'casual' | 'ai' | 'custom'

/**
 * The mode "再来一局" must replay. The game store already carries the three
 * server-authoritative flags (recorded at match start), so no new protocol
 * field is needed; ranked wins over a stale mode string, AI over custom.
 */
export function matchModeOf(ranked: boolean, mode: string, isAiRoom: boolean): MatchMode {
  if (isAiRoom || mode === 'ai') return 'ai'
  if (ranked || mode === 'ranked') return 'ranked'
  if (mode === 'custom') return 'custom'
  return 'casual'
}

export function matchModeLabel(mode: MatchMode): string {
  switch (mode) {
    case 'ranked':
      return '排位赛'
    case 'ai':
      return '人机对战'
    case 'custom':
      return '自定义房'
    default:
      return '休闲赛'
  }
}

/** The start screen stores the picked AI difficulty here (default normal). */
export const AI_DIFFICULTY_KEY = 'bs.aiDifficulty'
export const AI_DIFFICULTIES = ['easy', 'normal', 'hard', 'master'] as const

export function aiDifficulty(): string {
  try {
    const stored = String(window.localStorage.getItem(AI_DIFFICULTY_KEY) || '').trim()
    if ((AI_DIFFICULTIES as readonly string[]).includes(stored)) return stored
  } catch {
    // Private-mode storage can throw; the default applies.
  }
  return 'normal'
}

export function signed(value: number): string {
  return value > 0 ? '+' + value : String(value)
}

export function readNumber(source: JsonObject | null | undefined, key: string): number | null {
  if (!source) return null
  const value = source[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function readBoolean(source: JsonObject | null | undefined, key: string): boolean {
  return source?.[key] === true
}

export function readString(source: JsonObject | null | undefined, key: string): string {
  if (!source) return ''
  const value = source[key]
  return typeof value === 'string' ? value : ''
}

export function readObject(source: JsonObject | null | undefined, key: string): JsonObject | null {
  if (!source) return null
  const value = source[key]
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : null
}

export function readArray(source: JsonObject | null | undefined, key: string): unknown[] {
  if (!source) return []
  const value = source[key]
  return Array.isArray(value) ? value : []
}

export function toObjects(values: unknown[]): JsonObject[] {
  return values.filter((value): value is JsonObject =>
    Boolean(value) && typeof value === 'object' && !Array.isArray(value),
  )
}

export function progressPercent(progress: number | null, total: number | null): number {
  if (progress === null || total === null || total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((progress / total) * 100)))
}
