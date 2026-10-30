import type { Pinia } from 'pinia'
import type { TypedSocket } from '../socket/client'
import { useGameStore } from '../stores/game'
import { useUiStore } from '../stores/ui'

/**
 * Seat recovery across a socket reconnect (ticket #53).
 *
 * A reconnect gives the client a new socket id, but every seat is bound to the
 * old one, so the server answers "你不在这个房间" to every action. The frozen
 * pair `get_reconnect_token` / `rejoin_room` exists for exactly this:
 *
 *  1. while the seat is still bound to this connection, ask for a token and
 *     keep it (sessionStorage survives an in-page reconnect);
 *  2. after the socket comes back, `rejoin_room` with that token rebinds the
 *     seat to the new socket and the server re-sends `room_sync`;
 *  3. issue a fresh token for the next reconnect.
 *
 * No new event, no new protocol: both events are in the frozen inbound list.
 */

const STORAGE_KEY = 'battleship.reconnect.seat'

export interface StoredSeat {
  roomId: string
  playerId: string
  token: string
}

let stored: StoredSeat | null = null
let restoreBusy = false

function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage
  } catch {
    return null
  }
}

function load(): StoredSeat | null {
  if (stored) return stored
  try {
    const raw = storage()?.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<StoredSeat>
    if (!parsed || !parsed.roomId || !parsed.playerId || !parsed.token) return null
    stored = { roomId: String(parsed.roomId), playerId: String(parsed.playerId), token: String(parsed.token) }
    return stored
  } catch {
    return null
  }
}

function save(seat: StoredSeat | null): void {
  stored = seat
  try {
    if (seat) storage()?.setItem(STORAGE_KEY, JSON.stringify(seat))
    else storage()?.removeItem(STORAGE_KEY)
  } catch {
    // Storage is best effort; the in-memory copy still covers this visit.
  }
}

function ackToken(ack: unknown): string {
  const record = (ack && typeof ack === 'object' ? ack : {}) as Record<string, unknown>
  return typeof record.token === 'string' ? record.token : ''
}

/** Ask this (seat-bound) connection for a reconnect token and keep it. */
async function captureToken(socket: TypedSocket, roomId: string, playerId: string): Promise<boolean> {
  try {
    const ack = await socket.emitEvent('get_reconnect_token', { room_id: roomId, player_id: playerId })
    const token = ackToken(ack)
    if (ack && ack.status === 'success' && token) {
      save({ roomId, playerId, token })
      return true
    }
  } catch {
    // Not seated on this connection any more: fall through to rejoin.
  }
  return false
}

/**
 * Keep a token for the current seat. Safe to call on every frame: it is a
 * no-op once a token for this room/player is stored.
 */
export async function rememberSeat(socket: TypedSocket | null, pinia?: Pinia): Promise<void> {
  const game = useGameStore(pinia)
  const roomId = game.state.room_id
  const playerId = game.state.player_id
  if (!socket || !roomId || !playerId) return
  const existing = load()
  if (existing && existing.roomId === roomId && existing.playerId === playerId) return
  await captureToken(socket, roomId, playerId)
}

/**
 * Restore the seat after a connection comes up. Returns true when the player is
 * seated again (or was never in a match), false when recovery failed.
 */
export async function restoreSeat(socket: TypedSocket | null, pinia?: Pinia): Promise<boolean> {
  if (!socket || restoreBusy) return true
  const game = useGameStore(pinia)
  const ui = useUiStore(pinia)
  const seat = load()
  const roomId = game.state.room_id || (seat ? seat.roomId : '')
  const playerId = game.state.player_id || (seat ? seat.playerId : '')
  if (!roomId || !playerId) return true
  restoreBusy = true
  try {
    // First connect / still the seated connection: a token can be issued here.
    if (await captureToken(socket, roomId, playerId)) {
      ui.clearConnectionIssue()
      return true
    }
    if (!seat || seat.roomId !== roomId || seat.playerId !== playerId) return false
    const ack = await socket.emitEvent('rejoin_room', {
      room_id: roomId,
      player_id: playerId,
      token: seat.token,
    })
    if (ack && ack.status === 'success') {
      ui.clearConnectionIssue()
      ui.notify({ code: 'connection-seat-restored', message: '已回到原来的座位，可以继续这一局', tone: 'success' })
      // Rotate the token for the next reconnect (the seat is bound again now).
      await captureToken(socket, roomId, playerId)
      return true
    }
    ui.setConnectionIssue('没能恢复原来的座位：' + (ack && ack.message ? ack.message : '服务器拒绝了恢复请求'))
    return false
  } catch {
    ui.setConnectionIssue('没能恢复原来的座位：网络仍然不稳定')
    return false
  } finally {
    restoreBusy = false
  }
}

/** Test/route helper: forget the stored seat (leaving a match on purpose). */
export function forgetSeat(): void {
  save(null)
}
