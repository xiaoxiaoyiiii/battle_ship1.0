import type { Pinia } from 'pinia'
import type { AckResponse } from '../socket/events.gen'
import type { TypedSocket } from '../socket/client'
import { acquireSettlementChannel, getSettlementSocket } from './settlement'
import { usePlacementStore } from '../stores/placement'
import { useRpsStore } from '../stores/rps'
import { useGameStore } from '../stores/game'

/**
 * Ticket #23: the wire channel shared by the placement and rps screens.
 *
 * It reuses the one typed Socket.IO connection installed by the settlement
 * channel (ticket #22) with keepAlive, because a guest seat is bound to that
 * connection's sid: the placement submit and the rps choice must come from the
 * same connection the room was created on. The two extra events below are the
 * only ones this ticket consumes; command acks are handled by the screens.
 */
export type MatchEventName = 'rps_result' | 'reset_gameboard'

export const MATCH_EVENTS: readonly MatchEventName[] = ['rps_result', 'reset_gameboard']

/** Apply one server frame to the stores; the single implementation for wire and gate. */
export function applyMatchEvent(
  event: MatchEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  if (!payload || typeof payload !== 'object') return
  switch (event) {
    case 'rps_result':
      useRpsStore(pinia).applyResult(payload)
      break
    case 'reset_gameboard':
      usePlacementStore(pinia).applyReset(payload)
      useGameStore(pinia).applyServerState({ state: 'placing_ships', needs_reset: true, max_ships: Number(payload.new_max_ships) || 6, ships: [] })
      break
  }
}

export function installMatchListeners(socket: TypedSocket, pinia?: Pinia): () => void {
  const offs = MATCH_EVENTS.map((event) =>
    socket.on(event, (payload) => applyMatchEvent(event, payload, pinia)),
  )
  return () => {
    for (const off of offs) off()
  }
}

/**
 * Ack interceptor used by the external browser gate to simulate a lost frame
 * (the message really never reaches the server, which is what a timeout state
 * is for). Production never installs one.
 */
type AckInterceptor = (event: string, data: Record<string, unknown>) => boolean

let ackInterceptor: AckInterceptor | null = null

export function setMatchAckInterceptor(interceptor: AckInterceptor | null): void {
  ackInterceptor = interceptor
}

export function emitMatchEvent(
  socket: TypedSocket,
  event: 'place_ships' | 'rps_choice',
  data: Record<string, unknown>,
): Promise<AckResponse> {
  if (ackInterceptor && ackInterceptor(event, data)) {
    return new Promise<AckResponse>(() => {
      /* never settles: the frame was dropped */
    })
  }
  return socket.emitEvent(event, data)
}

interface ActiveMatchChannel {
  socket: TypedSocket
  stop: () => void
  refs: number
}

let active: ActiveMatchChannel | null = null

/**
 * Acquire the match channel. The connection is kept alive across screens
 * (seat identity), so release only drops the listeners when the last screen
 * using them goes away.
 */
export function acquireMatchChannel(pinia?: Pinia): () => void {
  if (!active) {
    const releaseSettlement = acquireSettlementChannel(pinia, { keepAlive: true })
    const socket = getSettlementSocket()
    if (!socket) {
      releaseSettlement()
      throw new Error('match channel could not open the shared socket')
    }
    const stopListeners = installMatchListeners(socket, pinia)
    active = {
      socket,
      stop: () => {
        stopListeners()
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

export function matchSocket(): TypedSocket | null {
  return active?.socket ?? null
}

export function resetMatchChannelForTest(): void {
  if (!active) return
  active.stop()
  active = null
  ackInterceptor = null
}
