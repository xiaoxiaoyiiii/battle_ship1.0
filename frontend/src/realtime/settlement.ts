import type { Pinia } from 'pinia'
import { createTypedSocket, type TypedSocket } from '../socket/client'
import { useGameStore } from '../stores/game'
import { useUiStore } from '../stores/ui'
import { rememberSeat, restoreSeat } from './reconnect'
import { useResultStore } from '../stores/result'

/**
 * The settlement wire channel (ticket #22).
 *
 * One typed Socket.IO connection feeds the Pinia stores. It is acquired by the
 * game-over screen (and reused by the future game screen) instead of every
 * component opening its own connection. The listener bodies live in
 * applySettlementEvent so the test build can feed the same handler with a
 * frozen payload without bypassing production logic.
 */
export type SettlementEventName =
  | 'game_over'
  | 'game_state'
  | 'game_message'
  | 'room_sync'
  | 'xp_gained'
  | 'rank_changed'
  | 'achievements_unlocked'
  | 'ships_updated'
  | 'recent_opponent'

// Typed listeners: only the frames that exist in the generated outbound union.
// recent_opponent is absent there (see the raw listener below).
const SETTLEMENT_EVENTS = [
  'game_over',
  'game_state',
  'game_message',
  'room_sync',
  'xp_gained',
  'rank_changed',
  'achievements_unlocked',
  'ships_updated',
] as const

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** Apply one server frame to the stores. The single implementation the wire and the gate share. */
export function applySettlementEvent(
  event: SettlementEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  if (!payload || typeof payload !== 'object') return
  const game = useGameStore(pinia)
  const result = useResultStore(pinia)

  switch (event) {
    case 'game_message': {
      // 重摆结束时仍可能停在布船页，由跨页面的共享连接接收最终效果。
      const message = asString(payload.message).trim()
      if (payload.type === 'magic_effect' && message) {
        useUiStore(pinia).notify({ code: `battle-effect:${message}`, message, tone: 'info', ttl: 2000 })
      }
      break
    }
    case 'game_over': {
      const winner = payload.winner
      game.applyServerState({
        state: 'game_over',
        winner: winner == null ? '' : String(winner),
        game_over_reason: asString(payload.reason) || null,
      })
      result.recordGameOver(payload)
      break
    }
    case 'game_state': {
      game.applyServerState(payload)
      if (payload.state === 'game_over') result.recordGameOver(payload)
      else if (payload.state === 'placing_ships') result.beginMatch()
      break
    }
    case 'room_sync': {
      game.applyServerState(payload)
      if (payload.state === 'game_over') {
        result.recordGameOver({
          winner: payload.winner,
          game_over_reason: payload.game_over_reason,
        })
      }
      break
    }
    case 'xp_gained':
      result.recordXp(payload)
      break
    case 'rank_changed':
      result.recordRank(payload)
      break
    case 'achievements_unlocked':
      result.recordAchievements(payload)
      break
    case 'recent_opponent':
      result.recordRecentOpponent(payload)
      break
    case 'ships_updated':
      game.applyServerState({
        remaining_ships: payload.player_remaining_ships,
        opponent_remaining_ships: payload.opponent_remaining_ships,
      })
      break
  }
}

export function installSettlementListeners(socket: TypedSocket, pinia?: Pinia): () => void {
  const offs = SETTLEMENT_EVENTS.map((event) =>
    socket.on(event, (payload) => {
      applySettlementEvent(event, payload, pinia)
      // Keep a reconnect token warm while the seat is bound to this connection.
      if (event === 'game_state' || event === 'room_sync') void rememberSeat(socket, pinia)
    }),
  )
  // The server has pushed this private frame since the legacy settlement hook
  // (one per seat, only when both seats are accounts), but the frozen outbound
  // registry in events.gen.ts predates it. Listening on the raw client keeps the
  // typed union honest without regenerating (and re-hashing) the contract.
  const onRecent = (payload: Record<string, unknown>) => {
    applySettlementEvent('recent_opponent', payload, pinia)
  }
  const raw = socket.socket as unknown as {
    on: (event: string, listener: (payload: Record<string, unknown>) => void) => void
    off: (event: string, listener: (payload: Record<string, unknown>) => void) => void
  }
  raw.on('recent_opponent', onRecent)
  return () => {
    for (const off of offs) off()
    raw.off('recent_opponent', onRecent)
  }
}

export interface SettlementChannelOptions {
  /**
   * Keep the socket connected when the last screen releases it. Both the
   * home -> placement (#26) and placement -> rps (#23) hand-offs need this: a
   * seat is bound to the connection's sid, so disconnecting between screens
   * would make every seat-bound emit fail the server's identity check (the
   * legacy app kept exactly one socket for the page lifetime for the same
   * reason).
   */
  keepAlive?: boolean
}

interface ActiveChannel {
  socket: TypedSocket
  stop: () => void
  refs: number
  keepAlive: boolean
}

let active: ActiveChannel | null = null

/**
 * Acquire the shared channel. The returned release function disconnects when
 * the last screen using it goes away (unless keepAlive is requested); Pinia
 * state survives, only the socket does not.
 */
export function acquireSettlementChannel(
  pinia?: Pinia,
  options: SettlementChannelOptions = {},
): () => void {
  if (!active) {
    const socket = createTypedSocket()
    const stopListeners = installSettlementListeners(socket, pinia)
    // One connection truth for the whole shell (spec §5, ticket #52): every
    // channel reuses this socket, so it reports here once.
    const ui = useUiStore(pinia)
    const onConnect = (): void => {
      ui.setConnection(true)
      // Ticket #53: a reconnect gives a new socket id; rebind the seat with the
      // frozen get_reconnect_token / rejoin_room pair before anything else.
      void restoreSeat(socket, pinia)
    }
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
      keepAlive: options.keepAlive === true,
    }
  }
  const channel = active
  if (options.keepAlive) channel.keepAlive = true
  channel.refs += 1
  let released = false
  return () => {
    if (released) return
    released = true
    channel.refs -= 1
    if (channel.refs <= 0 && active === channel && !channel.keepAlive) {
      channel.stop()
      active = null
    }
  }
}

export function getSettlementSocket(): TypedSocket | null {
  return active?.socket ?? null
}

export function settlementSocketConnected(): boolean {
  return active?.socket.socket.connected ?? false
}

/** Test-build helper: drop the singleton between browser checks. */
export function resetSettlementChannelForTest(): void {
  if (!active) return
  active.stop()
  active = null
}
