import type { Pinia } from 'pinia'
import { createTypedSocket, type TypedSocket } from '../socket/client'
import { useSpectateStore } from '../stores/spectate'
import { useUiStore } from '../stores/ui'
import { asObject, asString, type JsonObject } from '../screens/spectate/view'

/**
 * The spectator wire channel (ticket #28).
 *
 * One typed Socket.IO connection per mounted spectate screen, joining only the
 * spectator room (the server puts the connection there; this client never asks
 * for a match room). The listener bodies live in applySpectateEvent so the test
 * build feeds the exact production handler.
 *
 * Only events on the server's spectator allowlist are consumed. There is no
 * branch for a private frame: a screen that could consume one would be the
 * hole the allowlist exists to close.
 */
export type SpectateEventName =
  | 'spectate_sync'
  | 'spectate_you'
  | 'spectate_roster'
  | 'spectate_board'
  | 'spectate_ended'
  | 'spectate_count_changed'
  | 'spectate_chat'
  | 'attack_result'
  | 'turn_change'
  | 'phase_updated'
  | 'attacks_updated'
  | 'game_log'
  | 'magic_chain_updated'
  | 'chain_resolved'
  | 'field_magic_updated'
  | 'chat_message'
  | 'game_over'
  | 'game_canceled'

export const SPECTATE_EVENTS: readonly SpectateEventName[] = [
  'spectate_sync',
  'spectate_you',
  'spectate_roster',
  'spectate_board',
  'spectate_ended',
  'spectate_count_changed',
  'spectate_chat',
  'attack_result',
  'turn_change',
  'phase_updated',
  'attacks_updated',
  'game_log',
  'magic_chain_updated',
  'chain_resolved',
  'field_magic_updated',
  'chat_message',
  'game_over',
  'game_canceled',
]

/** The single implementation the wire and the test hook share. */
export function applySpectateEvent(
  event: SpectateEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  const store = useSpectateStore(pinia)
  if (!payload || typeof payload !== 'object') return
  switch (event) {
    case 'spectate_sync':
      store.applySnapshot(payload)
      break
    case 'spectate_you':
      store.applyYou(payload)
      break
    case 'spectate_roster':
      store.applyRoster(payload)
      break
    case 'spectate_board':
      store.applyBoardFrame(payload)
      break
    case 'spectate_ended':
      store.applyEnded(payload)
      break
    case 'spectate_count_changed':
      store.applyCount(payload)
      break
    case 'spectate_chat':
      store.applyChat(payload)
      break
    case 'attack_result':
      store.applyAttackResult(payload)
      break
    case 'turn_change':
      store.applyTurnChange(payload)
      break
    case 'phase_updated':
      store.applyPhaseUpdated(payload)
      break
    case 'attacks_updated':
      store.applyAttacksUpdated(payload)
      break
    case 'game_log':
      store.applyLog(payload)
      break
    case 'magic_chain_updated':
    case 'chain_resolved':
      store.applyChain(payload)
      break
    case 'field_magic_updated':
      store.applyFieldMagic(payload)
      break
    case 'chat_message':
      store.applyPlayerChat(payload)
      break
    case 'game_over':
      store.applyGameOver(payload)
      break
    case 'game_canceled':
      store.applyEnded({ reason: asString(payload.reason) || asString(payload.message) })
      break
  }
}

export function installSpectateListeners(socket: TypedSocket, pinia?: Pinia): () => void {
  const offs = SPECTATE_EVENTS.map((event) =>
    socket.on(event, (payload) => applySpectateEvent(event, payload, pinia)),
  )
  return () => {
    for (const off of offs) off()
  }
}

interface ActiveChannel {
  socket: TypedSocket
  stop: () => void
  refs: number
}

let active: ActiveChannel | null = null

/** Acquire the shared channel; the last screen to release closes the socket. */
export function acquireSpectateChannel(pinia?: Pinia): () => void {
  if (!active) {
    const socket = createTypedSocket()
    const stopListeners = installSpectateListeners(socket, pinia)
    // Spectating owns its own socket, so it reports the shell connection too.
    const ui = useUiStore(pinia)
    const onConnect = (): void => ui.setConnection(true)
    const onDisconnect = (): void => ui.setConnection(false)
    socket.socket.on('connect', onConnect)
    socket.socket.on('disconnect', onDisconnect)
    socket.connect()
    active = {
      socket,
      stop: () => {
        socket.socket.off('connect', onConnect)
        socket.socket.off('disconnect', onDisconnect)
        stopListeners()
        socket.disconnect()
      },
      refs: 0,
    }
  }
  const channel = active
  channel.refs += 1
  let released = false
  return () => {
    if (released) return
    released = true
    channel.refs -= 1
    if (channel.refs <= 0 && active === channel) {
      channel.stop()
      active = null
    }
  }
}

export function getSpectateSocket(): TypedSocket | null {
  return active?.socket ?? null
}

export function spectateSocketConnected(): boolean {
  return active?.socket.socket.connected ?? false
}

export interface SpectateActionResult {
  ok: boolean
  message: string
}

function ackRecord(ack: unknown): JsonObject {
  return asObject(ack) ?? {}
}

/** Join the spectator channel; every failure keeps a readable reason. */
export async function joinSpectate(roomId: string, pinia?: Pinia): Promise<SpectateActionResult> {
  const store = useSpectateStore(pinia)
  if (!roomId) {
    const message = '缺少房间号，请从大厅的进行中对局进入观战。'
    store.failJoin(message)
    return { ok: false, message }
  }
  const socket = getSpectateSocket()
  if (!socket) {
    const message = '观战通道还没有连接好，请稍后重试。'
    store.failJoin(message)
    return { ok: false, message }
  }
  store.beginJoin(roomId)
  try {
    const ack = await socket.emitEvent('spectate_join', { room_id: roomId })
    const record = ackRecord(ack)
    if (record.status !== 'success') {
      const message = asString(record.message) || '进入观战失败'
      store.failJoin(message)
      return { ok: false, message }
    }
    store.markJoined(record)
    return { ok: true, message: '' }
  } catch (error) {
    const message = '进入观战失败（网络），请稍后重试。'
    store.failJoin(message)
    return { ok: false, message }
  }
}

/** Leave the spectator seat (idempotent: a refusal is not an error here). */
export async function leaveSpectate(pinia?: Pinia): Promise<void> {
  const store = useSpectateStore(pinia)
  const socket = getSpectateSocket()
  const roomId = store.roomId
  const seated = store.phase === 'joined' || store.phase === 'ended'
  store.reset()
  if (!socket || !roomId || !seated) return
  try {
    await socket.emitEvent('spectate_leave', { room_id: roomId })
  } catch {
    // Leaving is best effort: the socket is closed right after this anyway.
  }
}

/** Send one spectator-chat line; a refusal is surfaced, never swallowed. */
export async function sendSpectateChat(message: string, pinia?: Pinia): Promise<SpectateActionResult> {
  const store = useSpectateStore(pinia)
  const text = String(message ?? '').trim()
  if (!text) {
    store.chatNotice('说点什么再发送吧')
    return { ok: false, message: '说点什么再发送吧' }
  }
  if (store.phase !== 'joined' && store.phase !== 'ended') {
    store.chatNotice('你不在观战席上，发送失败', 'error')
    return { ok: false, message: '你不在观战席上，发送失败' }
  }
  const socket = getSpectateSocket()
  if (!socket) {
    store.chatNotice('观战通道还没有连接好，发送失败', 'error')
    return { ok: false, message: '观战通道还没有连接好，发送失败' }
  }
  try {
    const ack = await socket.emitEvent('spectate_chat_send', {
      room_id: store.roomId,
      message: text,
    })
    const record = ackRecord(ack)
    if (record.status !== 'success') {
      const why = asString(record.message) || '发送失败，请稍后再试'
      store.chatNotice(why, 'error')
      return { ok: false, message: why }
    }
    return { ok: true, message: '' }
  } catch {
    const why = '发送失败（网络），请稍后再试'
    store.chatNotice(why, 'error')
    return { ok: false, message: why }
  }
}

/** Test-build helper: drop the singleton between browser checks. */
export function resetSpectateChannelForTest(): void {
  if (!active) return
  active.stop()
  active = null
}