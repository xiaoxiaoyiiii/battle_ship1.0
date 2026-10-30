import type { Pinia } from 'pinia'
import type { TypedSocket } from '../socket/client'
import { acquireSettlementChannel, getSettlementSocket } from './settlement'
import { useGameStore } from '../stores/game'
import { lobbyPlayerName, useLobbyStore } from '../stores/lobby'

/**
 * The lobby wire channel (ticket #24).
 *
 * One typed Socket.IO connection feeds the lobby store while /lobby is mounted.
 * lobby_state is a broadcast, so the store compares lobby_hello.key with the
 * player/chat keys to decide "me"; nothing here invents an is_me flag.
 *
 * The listener bodies live in applyLobbyEvent so the test build can feed the
 * exact production handler with a frozen payload (same seam as #22).
 */
export type LobbyEventName =
  | 'lobby_hello'
  | 'lobby_state'
  | 'lobby_chat_history'
  | 'lobby_chat'
  | 'match_queued'
  | 'match_canceled'
  | 'friend_invite'
  | 'game_state'
  | 'room_sync'
  | 'error'

const LOBBY_EVENTS: readonly LobbyEventName[] = [
  'lobby_hello',
  'lobby_state',
  'lobby_chat_history',
  'lobby_chat',
  'match_queued',
  'match_canceled',
  'friend_invite',
  'game_state',
  'room_sync',
  'error',
]

function readMessage(payload: Record<string, unknown> | null | undefined): string {
  if (!payload) return ''
  const value = payload.message ?? payload.error
  return typeof value === 'string' ? value : ''
}

/** Apply one server frame to the stores. The single implementation the wire and the gate share. */
export function applyLobbyEvent(
  event: LobbyEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  if (!payload || typeof payload !== 'object') return
  const lobby = useLobbyStore(pinia)
  const game = useGameStore(pinia)

  switch (event) {
    case 'lobby_hello':
      lobby.recordHello(payload)
      break
    case 'lobby_state':
      lobby.recordSnapshot(payload)
      break
    case 'lobby_chat_history':
      lobby.recordChatHistory(payload)
      break
    case 'lobby_chat':
      lobby.recordChat(payload)
      break
    case 'match_queued':
      lobby.recordQueued(payload)
      break
    case 'match_canceled':
      lobby.recordCanceled(payload)
      break
    case 'friend_invite':
      lobby.recordFriendInvite(payload)
      break
    case 'game_state':
    case 'room_sync':
      game.applyServerState(payload)
      lobby.recordGameFrame(payload)
      break
    case 'error':
      lobby.setError(readMessage(payload) || '操作失败')
      break
  }
}

export function installLobbyListeners(socket: TypedSocket, pinia?: Pinia): () => void {
  // friend_invite is a parameterised outbound event: the backend sends it
  // through the _push_friend_event helper, so it is not a literal in
  // events.gen.ts (DECISIONS D21). The wire name is frozen; the cast stays
  // local to this listener install instead of widening the typed client.
  type Listener = (payload: Record<string, unknown>) => void
  const listen = socket.on as unknown as (event: string, handler: Listener) => () => void
  const offs = LOBBY_EVENTS.map((event) =>
    listen(event, (payload) => applyLobbyEvent(event, payload, pinia)),
  )
  return () => {
    for (const off of offs) off()
  }
}

function subscribe(socket: TypedSocket, pinia?: Pinia): void {
  const lobby = useLobbyStore(pinia)
  void socket
    .emitEvent('lobby_subscribe', { player_name: lobbyPlayerName() })
    .then((ack) => {
      if (ack.status === 'error') {
        lobby.setError(ack.message || '进入大厅失败')
      }
    })
    .catch((error: unknown) => {
      if (!lobby.connected) return
      lobby.setError(error instanceof Error ? error.message : String(error))
    })
}

interface ActiveChannel {
  socket: TypedSocket
  stop: () => void
  refs: number
}

let active: ActiveChannel | null = null

/**
 * Acquire the shared lobby channel. The returned release function disconnects
 * when the last screen using it goes away; Pinia state survives, only the
 * socket does not.
 */
export function acquireLobbyChannel(pinia?: Pinia): () => void {
  const lobby = useLobbyStore(pinia)
  if (!active) {
    // Ticket #33: the home screen already keeps the one shared socket alive
    // (a seat is bound to its sid). Opening a second connection here made the
    // same account appear twice in presence. Reuse it when present; a direct
    // /lobby visit still owns a socket and closes it on release.
    const reuse = getSettlementSocket() !== null
    const releaseSettlement = acquireSettlementChannel(pinia, reuse ? { keepAlive: true } : {})
    const socket = getSettlementSocket()
    if (!socket) {
      releaseSettlement()
      throw new Error('lobby channel could not open the shared socket')
    }
    const stopListeners = installLobbyListeners(socket, pinia)
    let subscribed = false
    const subscribeOnce = () => {
      if (subscribed) return
      subscribed = true
      subscribe(socket, pinia)
    }
    const onConnect = () => {
      subscribed = false
      lobby.markConnected(true)
      lobby.clearError()
      subscribeOnce()
    }
    const onDisconnect = () => {
      subscribed = false
      lobby.markConnected(false)
    }
    socket.socket.on('connect', onConnect)
    socket.socket.on('disconnect', onDisconnect)
    if (socket.socket.connected) onConnect()
    active = {
      socket,
      stop: () => {
        stopListeners()
        socket.socket.off('connect', onConnect)
        socket.socket.off('disconnect', onDisconnect)
        // The server also drops membership on disconnect; this is the polite
        // path for a route change while the connection is still open.
        if (socket.socket.connected) socket.socket.emit('lobby_unsubscribe', {})
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
      lobby.markConnected(false)
    }
  }
}

export function getLobbySocket(): TypedSocket | null {
  return active?.socket ?? null
}

export function lobbySocketConnected(): boolean {
  return active?.socket.socket.connected ?? false
}

/** Test-build helper: drop the singleton between browser checks. */
export function resetLobbyChannelForTest(): void {
  if (!active) return
  active.stop()
  active = null
}
