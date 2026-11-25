import type { Pinia } from 'pinia'
import router from '../router'
import type { TypedSocket } from '../socket/client'
import type { AckResponse } from '../socket/events.gen'
import { useAudioStore } from '../stores/audio'
import { useCustomRematchStore } from '../stores/customRematch'
import { useGameStore } from '../stores/game'
import { useHomeStore } from '../stores/home'
import { useLobbyStore } from '../stores/lobby'
import { usePlacementStore } from '../stores/placement'
import { useResultStore } from '../stores/result'
import { useUiStore } from '../stores/ui'
import { adoptRememberedSeat, forgetSeatForRoom, readRememberedSeat } from './reconnect'

type RematchAck = AckResponse & { rematch?: unknown }
type RematchAction = 'invite' | 'accept' | 'decline' | 'cancel'

const endMessages = {
  declined: '对方拒绝了再战邀请。',
  canceled: '再战邀请已撤回。',
  expired: '再战邀请已过期。',
  unavailable: '再战邀请已失效。',
} as const

export function isRematchRoute(name: unknown): boolean {
  return name === 'game-over' || name === 'lobby' || name === 'lobby-rooms'
    || name === 'lobby-matches' || name === 'lobby-create'
}

export function applyCustomRematchState(payload: unknown, pinia?: Pinia): boolean {
  const rematch = useCustomRematchStore(pinia)
  const before = rematch.state
  if (!rematch.applyState(payload) || !rematch.state) return false
  const next = rematch.state
  // 这张凭据针对已结算旧局，应走再战恢复而非原局重连。
  forgetSeatForRoom(next.room_id)
  if (before?.status === 'pending' && before.room_id === next.room_id
    && (next.status === 'declined' || next.status === 'canceled'
      || next.status === 'expired' || next.status === 'unavailable')) {
    useUiStore(pinia).notify({
      code: 'custom-rematch-' + next.status,
      message: next.message || endMessages[next.status],
      tone: 'info',
    })
  }
  return true
}

/** 重新连线时用同一席的短期凭据恢复邀请，也可用已保存的原局座位证明。 */
export async function syncCustomRematch(socket: TypedSocket, pinia?: Pinia): Promise<boolean> {
  const rematch = useCustomRematchStore(pinia)
  const oldSeat = readRememberedSeat()
  const credential = rematch.credential ?? (oldSeat ? { room_id: oldSeat.roomId, token: oldSeat.token } : {})
  const revision = rematch.revision
  try {
    const ack = await socket.emitEvent('custom_rematch_sync', { ...credential }) as RematchAck
    if (ack.status !== 'success') return false
    if (ack.rematch === null && rematch.revision === revision) rematch.clear()
    if (ack.rematch && applyCustomRematchState(ack.rematch, pinia)) return true
    return rematch.revision !== revision && rematch.state !== null
  } catch {
    // 不可达时保留凭据，下次连线仍按服务器原截止时间恢复。
    return false
  }
}

export async function sendCustomRematchAction(socket: TypedSocket | null, action: RematchAction, pinia?: Pinia): Promise<void> {
  const rematch = useCustomRematchStore(pinia)
  const current = rematch.state
  if (!current || rematch.submitting) return
  const connectionError = (message: string) => useUiStore(pinia).notify({
    code: 'custom-rematch-action', message, tone: 'error',
  })
  if (!socket?.socket.connected) {
    connectionError('实时连接还没恢复，请稍后再试。')
    return
  }
  rematch.submitting = true
  try {
    const data = { room_id: current.room_id, token: current.token }
    const ack = (action === 'invite'
      ? await socket.emitEvent('custom_rematch_invite', data)
      : await socket.emitEvent('custom_rematch_reply', { ...data, action })) as RematchAck
    if (ack.rematch) applyCustomRematchState(ack.rematch, pinia)
    if (ack.status === 'error') connectionError(ack.message || '再战操作没有完成。')
  } catch {
    connectionError('网络不稳定，正在同步再战状态。')
    if (socket.socket.connected) void syncCustomRematch(socket, pinia)
  } finally {
    rematch.submitting = false
  }
}

export function applyCustomRematchStarted(payload: Record<string, unknown>, pinia?: Pinia): void {
  const source = payload.source_room_id
  const room = payload.room_id
  const token = payload.reconnect_token
  const snapshot = payload.game as Record<string, unknown> | undefined
  if (typeof source !== 'string' || !source || typeof room !== 'string' || !room
    || typeof token !== 'string' || !token || !snapshot || snapshot.room_id !== room
    || typeof snapshot.player_id !== 'string' || !snapshot.player_id) return
  const destination = snapshot.state === 'placing_ships' ? 'placement'
    : snapshot.state === 'rock_paper_scissors' ? 'rps'
      : snapshot.state === 'attacking' || snapshot.state === 'mystery_tech_resolution' ? 'game' : ''
  if (!destination) return

  const game = useGameStore(pinia)
  const currentRoom = game.state.room_id
  // 在另一个进行中的对局时，不用旧房迟到的通知覆盖它。
  if (currentRoom && currentRoom !== room && currentRoom !== source) return
  if (!useCustomRematchStore(pinia).finishHandoff(source)) return
  if (readRememberedSeat()?.roomId !== room) {
    adoptRememberedSeat({ roomId: room, playerId: snapshot.player_id, token })
  }
  useUiStore(pinia).clearConnectionIssue()
  if (currentRoom === room && !isRematchRoute(router.currentRoute.value.name)) return

  useAudioStore(pinia).resetMatchAudio()
  useResultStore(pinia).reset()
  const placement = usePlacementStore(pinia)
  placement.reset()
  placement.adoptOpponentState(snapshot)
  const lobby = useLobbyStore(pinia)
  lobby.clearOwnRoom()
  lobby.clearMatchFound()
  lobby.takeStartedRoom()
  const home = useHomeStore(pinia)
  home.clearMatchFound()
  home.placementHandled()
  game.applyServerState(snapshot)
  void router.replace({ name: destination })
}
