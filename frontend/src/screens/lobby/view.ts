import type {
  LobbyFilter,
  LobbyMatch,
  LobbyPlayer,
  LobbyQueueMode,
  LobbyRoom,
} from '../../stores/lobby'

/**
 * Pure view helpers for the lobby screen (ticket #24).
 *
 * These only format server-authoritative values. "Joinable" compares the
 * server's players/capacity fields; the screen never invents room visibility,
 * queue membership or a match result. Search/filter are local views over the
 * last broadcast and never cause a server request.
 */
export const STATUS_TEXT: Record<string, string> = {
  idle: '空闲',
  matching: '匹配中',
  in_room: '在房间',
  in_game: '对局中',
}

export const FILTERS: ReadonlyArray<{ value: LobbyFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'joinable', label: '可加入' },
  { value: 'watchable', label: '可观战' },
  { value: 'full', label: '已满' },
]

export function statusText(player: LobbyPlayer): string {
  return STATUS_TEXT[player.status] || '空闲'
}

export function levelText(player: LobbyPlayer): string {
  return 'Lv.' + (player.level > 0 ? player.level : 1)
}

export function rankText(player: LobbyPlayer): string {
  return player.rankLabel || ''
}

export function initial(name: string): string {
  const chars = Array.from(String(name || '').trim())
  return chars.length ? chars[0] : '游'
}

export function roomJoinable(room: LobbyRoom): boolean {
  return room.players < room.capacity
}

export function roomSeatsText(room: LobbyRoom): string {
  return room.players + ' / ' + room.capacity
}

/** Ticket #43 fields, shown on the room card so a player can judge the table. */
export function roomModeText(room: LobbyRoom): string {
  if (room.mode === 'ranked') return '排位'
  if (room.mode === 'custom') return '自定义'
  return '休闲'
}

export function roomVisibilityText(room: LobbyRoom): string {
  return room.public ? '公开' : '私密'
}

export function matchNamesText(match: LobbyMatch): string {
  const names = match.names.map((name) => String(name || '玩家'))
  return (names[0] || '玩家') + ' vs ' + (names[1] || '玩家')
}

export function matchSpectateText(match: LobbyMatch): string {
  return '观战 ' + match.spectators + ' / ' + match.spectatorLimit
}

export function queueModeText(mode: LobbyQueueMode): string {
  if (mode === 'ranked') return '排位匹配中'
  if (mode === 'casual') return '休闲匹配中'
  return ''
}

export function timeText(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return '--:--:--'
  try {
    return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return '--:--:--'
  }
}

function hit(parts: Array<string | number>, query: string): boolean {
  if (!query) return true
  return parts.some((part) => String(part ?? '').toLowerCase().includes(query))
}

export function normalizedQuery(query: string): string {
  return String(query || '').trim().toLowerCase()
}

export function filterRooms(
  rooms: LobbyRoom[],
  filter: LobbyFilter,
  query: string,
): LobbyRoom[] {
  if (filter === 'watchable') return []
  const needle = normalizedQuery(query)
  return rooms.filter((room) => {
    if (filter === 'joinable' && !roomJoinable(room)) return false
    if (filter === 'full' && roomJoinable(room)) return false
    return hit([room.name, room.host, room.roomId], needle)
  })
}

export function filterMatches(
  matches: LobbyMatch[],
  filter: LobbyFilter,
  query: string,
): LobbyMatch[] {
  if (filter === 'joinable' || filter === 'full') return []
  const needle = normalizedQuery(query)
  return matches.filter((match) => hit(match.names, needle))
}

export function showsRooms(filter: LobbyFilter): boolean {
  return filter !== 'watchable'
}

export function showsMatches(filter: LobbyFilter): boolean {
  return filter === 'all' || filter === 'watchable'
}

export function roomsEmptyText(
  total: number,
  filter: LobbyFilter,
  query: string,
): string {
  if (!total) return '暂无等待中的房间，点上方的「创建房间」开一桌'
  if (!normalizedQuery(query)) {
    if (filter === 'joinable') return '没有可加入的房间（共 ' + total + ' 间在等，可能都已满）'
    if (filter === 'full') return '没有已满的房间'
    return '没有符合条件的房间（共 ' + total + ' 间在等）'
  }
  return '没有符合条件的房间（共 ' + total + ' 间在等，试着改一下搜索或筛选）'
}

export function matchesEmptyText(total: number, query: string): string {
  if (!total) return '当前没有正在进行的对局'
  if (normalizedQuery(query)) return '没有符合搜索的对局（共 ' + total + ' 局在进行）'
  return '没有符合条件的对局'
}

export function inviteDisabledReason(friend: {
  online: boolean
  inGame: boolean
}): string {
  if (!friend.online) return '对方不在线，暂时不能邀战'
  if (friend.inGame) return '对方正在对局中，暂时不能邀战'
  return ''
}
