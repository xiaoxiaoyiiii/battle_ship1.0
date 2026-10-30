import type { ChangelogEntry, HomeMode, HomeStats, JsonObject } from '../../stores/home'

/**
 * Formatting helpers for the home screen (ticket #26).
 *
 * The screen renders only server values: `rank_info.label`, `level_info`,
 * `wins`/`losses` and the counters. The two percentages below are the only
 * arithmetic the view performs, and they are pure formatting (the server does
 * not send a percentage for the rank sub-tier or the win rate).
 */
export function readString(source: JsonObject | null | undefined, key: string): string {
  if (!source) return ''
  const value = source[key]
  return typeof value === 'string' ? value : ''
}

export function readNumber(source: JsonObject | null | undefined, key: string): number | null {
  if (!source) return null
  const value = source[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function readObject(source: JsonObject | null | undefined, key: string): JsonObject | null {
  if (!source) return null
  const value = source[key]
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

/** Unknown server numbers render nothing; zero is a real value (story 64). */
export function numberText(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
}

export function percentOf(value: number | null, total: number | null): string {
  if (value === null || total === null || total <= 0) return ''
  return Math.round((value / total) * 100) + '%'
}

/** Bar width in percent; 0 when the server omitted the numbers. */
export function percentWidth(value: number | null, total: number | null): number {
  if (value === null || total === null || total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((value / total) * 100)))
}

/** `ratio` is already 0..1 from `leveling.level_view`, so no curve lives here. */
export function ratioWidth(ratio: number | null): number {
  if (ratio === null) return 0
  return Math.max(0, Math.min(100, Math.round(ratio * 100)))
}

export interface PlayerView {
  guest: boolean
  name: string
  rankLabel: string
  rankFill: number
  level: string
  levelText: string
  levelFill: number
  record: string
  winRate: string
  streak: string
}

export function playerView(profile: JsonObject | null): PlayerView {
  if (!profile) {
    return {
      guest: true,
      name: '游客',
      rankLabel: '',
      rankFill: 0,
      level: '',
      levelText: '',
      levelFill: 0,
      record: '',
      winRate: '',
      streak: '',
    }
  }
  const rank = readObject(profile, 'rank_info')
  const level = readObject(profile, 'level_info')
  const wins = readNumber(profile, 'wins')
  const losses = readNumber(profile, 'losses')
  const into = readNumber(level, 'into')
  const need = readNumber(level, 'need')
  const levelValue = readNumber(level, 'level')
  const matches = wins !== null && losses !== null ? wins + losses : null
  return {
    guest: false,
    name: readString(profile, 'username') || '指挥官',
    rankLabel: readString(rank, 'label'),
    rankFill: percentWidth(readNumber(rank, 'progress'), readNumber(rank, 'sub_points')),
    level: levelValue === null ? '' : 'Lv.' + levelValue,
    levelText:
      need === null ? '' : need > 0 ? numberText(into) + ' / ' + numberText(need) : '满级',
    levelFill: ratioWidth(readNumber(level, 'ratio')),
    record: wins === null || losses === null ? '' : wins + ' 胜 / ' + losses + ' 负',
    winRate: percentOf(wins, matches),
    streak: numberText(readNumber(profile, 'longest_streak')),
  }
}

export function queueStatusText(mode: HomeMode | null): string {
  if (mode === 'ranked') return '正在寻找排位对手…'
  if (mode === 'casual') return '正在寻找休闲对手…'
  return ''
}

/** Seconds waited since the server confirmed the queue entry (story 21). */
export function waitedSeconds(startedAt: number, now: number): number {
  if (!startedAt) return 0
  return Math.max(0, Math.floor((now - startedAt) / 1000))
}

/** AI difficulty options: four directly clickable pills (story 17). */
export const DIFFICULTY_OPTIONS: ReadonlyArray<{ value: string; label: string; hint: string }> = [
  { value: 'easy', label: '简单', hint: '只会炮击' },
  { value: 'normal', label: '普通', hint: '每回合一张安全卡' },
  { value: 'hard', label: '困难', hint: '会用失灵响应连锁' },
  { value: 'master', label: '大师', hint: '试算选牌 · 读情报开炮' },
]

/**
 * Stable list key for one announcement: the server contract says the date is
 * unique (changelog.py), and whitespace is folded so the value can sit inside a
 * data-testid.
 */
export function changelogKey(entry: ChangelogEntry): string {
  return entry.date.trim().replace(/\s+/g, '-')
}

export interface StatsText {
  online: string
  casual: string
  ranked: string
  rooms: string
}

export function statsText(stats: HomeStats): StatsText {
  return {
    online: numberText(stats.onlineCount),
    casual: numberText(stats.queueCasual),
    ranked: numberText(stats.queueRanked),
    rooms: numberText(stats.lobbyRooms),
  }
}
