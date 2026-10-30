import type { Pinia } from 'pinia'
import type { AckResponse } from '../socket/events.gen'
import type { TypedSocket } from '../socket/client'
import { acquireSettlementChannel, getSettlementSocket } from './settlement'
import { useHomeStore } from '../stores/home'

/**
 * The home-screen wire channel (ticket #26).
 *
 * The home screen is where a seat is created (matchmaking queue / AI room), and
 * a seat is bound to the socket id it was created on. It therefore reuses the
 * one shared typed Socket.IO connection (ticket #22/#23) with keepAlive so the
 * hand-off to the placement screen does not drop the connection.
 *
 * Only the four frames the home screen consumes are registered here:
 * match_queued / match_canceled / error. game_state is already applied to the
 * game store by the settlement listeners on the same socket.
 */
export type HomeEventName = 'match_queued' | 'match_canceled' | 'error' | 'game_state'

export const HOME_EVENTS: readonly HomeEventName[] = [
  'match_queued',
  'match_canceled',
  'error',
  'game_state',
]

/** Apply one server frame to the home store; wire and gate share this body. */
export function applyHomeEvent(
  event: HomeEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  if (!payload || typeof payload !== 'object') return
  const home = useHomeStore(pinia)
  switch (event) {
    case 'match_queued':
      home.applyMatchQueued(payload)
      break
    case 'match_canceled':
      home.applyMatchCanceled()
      break
    case 'error':
      home.notifyError(payload)
      break
    case 'game_state':
      // The settlement listeners already mirror the frame into the game store;
      // here we only tick the hand-off signal. Both listeners run in the same
      // dispatch, so the screen's watcher sees the mirrored state.
      if (payload.state === 'placing_ships' && home.awaitingPlacement) {
        // A real pair also opens the 匹配成功 overlay (opponent name is in the
        // matchmaking frame); AI/custom rooms have no queue and skip it.
        home.recordPlacementFrame(payload)
        home.markPlacementFrame()
      }
      break
  }
}

export function installHomeListeners(socket: TypedSocket, pinia?: Pinia): () => void {
  const offs = HOME_EVENTS.map((event) =>
    socket.on(event, (payload) => applyHomeEvent(event, payload, pinia)),
  )
  return () => {
    for (const off of offs) off()
  }
}

export interface HomeChannelOptions {
  /** Called once per connection (initial connect and every reconnect). */
  onConnect?: () => void
}

interface ActiveHomeChannel {
  socket: TypedSocket
  stop: () => void
  refs: number
}

let active: ActiveHomeChannel | null = null

/**
 * Acquire the home listeners on the shared connection. Released on unmount; the
 * connection itself stays alive (keepAlive) because the seat identity must
 * survive the route change.
 */
export function acquireHomeChannel(pinia?: Pinia, options: HomeChannelOptions = {}): () => void {
  if (!active) {
    const releaseSettlement = acquireSettlementChannel(pinia, { keepAlive: true })
    const socket = getSettlementSocket()
    if (!socket) {
      releaseSettlement()
      throw new Error('home channel could not open the shared socket')
    }
    const store = useHomeStore(pinia)
    const stopListeners = installHomeListeners(socket, pinia)
    const raw = socket.socket
    const onConnect = () => {
      store.setSocketConnected(true)
      options.onConnect?.()
    }
    const onDisconnect = () => store.setSocketConnected(false)
    raw.on('connect', onConnect)
    raw.on('disconnect', onDisconnect)
    if (raw.connected) onConnect()
    active = {
      socket,
      stop: () => {
        stopListeners()
        raw.off('connect', onConnect)
        raw.off('disconnect', onDisconnect)
        releaseSettlement()
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

export function homeSocket(): TypedSocket | null {
  return active?.socket ?? null
}

type Ack = AckResponse & Record<string, unknown>

export async function emitFindMatch(
  socket: TypedSocket,
  playerName: string,
  mode: 'casual' | 'ranked',
): Promise<Ack> {
  return (await socket.emitEvent('find_match', {
    player_name: playerName,
    mode,
  })) as Ack
}

export async function emitCancelMatch(socket: TypedSocket): Promise<Ack> {
  return (await socket.emitEvent('cancel_match', {})) as Ack
}

export interface AiRoomResult {
  ok: boolean
  message?: string
  roomId?: string
}

/**
 * Create the AI room and seat ourselves in it (legacy aiMatch: create_ai_room
 * then join_room). create_ai_room alone leaves the room with the AI seat only,
 * so the server would never transition it to placement.
 */
export async function createAiRoom(
  socket: TypedSocket,
  playerName: string,
  difficulty: string,
): Promise<AiRoomResult> {
  const created = (await socket.emitEvent('create_ai_room', {
    player_name: playerName,
    difficulty,
  })) as Ack
  if (created.status !== 'success') {
    return { ok: false, message: created.message || '创建人机房间失败' }
  }
  const roomId = String(created.room_id ?? '')
  if (!roomId) return { ok: false, message: '服务端没有返回房间号' }
  const joined = (await socket.emitEvent('join_room', {
    room_id: roomId,
    player_name: playerName,
  })) as Ack
  if (joined.status !== 'success') {
    return { ok: false, message: joined.message || '进入人机房间失败' }
  }
  return { ok: true, roomId }
}

/** Test helper: drop the singleton between browser checks. */
export function resetHomeChannelForTest(): void {
  if (!active) return
  active.stop()
  active = null
}
