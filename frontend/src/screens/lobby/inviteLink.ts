/**
 * 房间邀请链接的纯逻辑（不碰 DOM、不碰 socket，便于回归）。
 *
 * 设计边界（任务约定）：
 * - URL 只携带房间标识 room=XXXX，不带 token / 密码 / 用户名等隐私字段；
 * - 房间号只允许字母数字与下划线，长度 <= 32，避免把任意输入塞进既有的 join_room；
 * - 文案集中在这里，复制成功/失败两条反馈与手动复制兜底提示保持一对一。
 */

export const INVITE_PARAM = 'room'

const ROOM_ID_PATTERN = /^[A-Za-z0-9_]{1,32}$/

/** 生成 `<origin><pathname>?room=<id>`；origin/path 的末尾斜杠只保留一个。 */
export function buildInviteUrl(origin: string, pathname: string, roomId: string): string {
  const base = String(origin || '').replace(/\/+$/, '')
  const path = String(pathname || '/').startsWith('/') ? String(pathname || '/') : '/' + String(pathname)
  return `${base}${path}?${INVITE_PARAM}=${encodeURIComponent(String(roomId).trim())}`
}

/** 从路由 query 里取出房间号；非法或缺省一律返回空串（调用方据此不做任何动作）。 */
export function readInviteRoomId(query: unknown): string {
  if (!query || typeof query !== 'object') return ''
  const raw = (query as Record<string, unknown>)[INVITE_PARAM]
  const first = Array.isArray(raw) ? raw[0] : raw
  if (typeof first !== 'string' && typeof first !== 'number') return ''
  const trimmed = String(first).trim()
  return ROOM_ID_PATTERN.test(trimmed) ? trimmed : ''
}

/** 复制结果的可读反馈。 */
export function inviteFeedback(copied: boolean): string {
  return copied ? '邀请链接已复制，发给好友即可直接进房' : '复制失败，请手动复制链接发给好友'
}

/** 手动复制兜底：提示文案里带完整链接，玩家可自行复制。 */
export function inviteManualPrompt(url: string): string {
  return `复制下面的邀请链接发给好友：\n${url}`
}
