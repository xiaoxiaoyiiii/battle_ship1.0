import type { Pinia } from 'pinia'
import type { AckResponse } from '../socket/events.gen'
import type { TypedSocket } from '../socket/client'
import { useGameStore } from '../stores/game'
import { useMysteryTechStore } from '../stores/mysteryTech'

export const MYSTERY_TECH_EVENTS = ['mystery_tech_state', 'mystery_tech_public'] as const
export type MysteryTechEventName = (typeof MYSTERY_TECH_EVENTS)[number]

export function applyMysteryTechEvent(
  event: MysteryTechEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  if (!payload || typeof payload !== 'object') return
  const store = useMysteryTechStore(pinia)
  if (event === 'mystery_tech_state') store.applyPrivate(payload)
  else store.applyPublic(payload)
}

export function hydrateMysteryTechFromSync(
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  if (!payload || typeof payload !== 'object') return
  useMysteryTechStore(pinia).hydrateFromSync(payload.mystery_tech_state, payload.mystery_tech)
}

type Ack = AckResponse & Record<string, unknown>

function identity(pinia?: Pinia): { room_id: string; player_id: string } {
  const game = useGameStore(pinia)
  return { room_id: game.state.room_id, player_id: game.state.player_id }
}

function asAck(value: unknown): Ack {
  return (value && typeof value === 'object' ? value : { status: 'error', message: '没有响应' }) as Ack
}

export async function emitMysteryTechRefresh(
  socket: TypedSocket,
  slot: number,
  pinia?: Pinia,
): Promise<Ack> {
  const store = useMysteryTechStore(pinia)
  store.setPending('refresh')
  store.setError('')
  try {
    const ack = asAck(await socket.emitEvent('mystery_tech_refresh', { ...identity(pinia), slot }))
    if (ack.status !== 'success') store.setError(ack.message || '刷新失败')
    return ack
  } catch (error) {
    const message = error instanceof Error ? error.message : '刷新失败'
    store.setError(message)
    return { status: 'error', message, data: null } as Ack
  } finally {
    store.setPending(null)
  }
}

export async function emitMysteryTechChoose(
  socket: TypedSocket,
  techId: string,
  pinia?: Pinia,
): Promise<Ack> {
  const store = useMysteryTechStore(pinia)
  store.setPending('choose')
  store.setError('')
  try {
    const ack = asAck(await socket.emitEvent('mystery_tech_choose', { ...identity(pinia), tech_id: techId }))
    if (ack.status !== 'success') store.setError(ack.message || '锁定失败')
    return ack
  } catch (error) {
    const message = error instanceof Error ? error.message : '锁定失败'
    store.setError(message)
    return { status: 'error', message, data: null } as Ack
  } finally {
    store.setPending(null)
  }
}

export async function emitMysteryTechTarget(
  socket: TypedSocket,
  requestId: string,
  fields: Record<string, unknown>,
  pinia?: Pinia,
): Promise<Ack> {
  const store = useMysteryTechStore(pinia)
  store.setPending('target')
  store.setError('')
  try {
    const ack = asAck(await socket.emitEvent('mystery_tech_target', {
      ...identity(pinia),
      request_id: requestId,
      ...fields,
    }))
    if (ack.status !== 'success') store.setError(ack.message || '瞄准提交失败')
    return ack
  } catch (error) {
    const message = error instanceof Error ? error.message : '瞄准提交失败'
    store.setError(message)
    return { status: 'error', message, data: null } as Ack
  } finally {
    store.setPending(null)
  }
}
