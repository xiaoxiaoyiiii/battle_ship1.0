import type { Pinia } from 'pinia'
import type { TypedSocket } from '../socket/client'
import { acquireSettlementChannel, getSettlementSocket } from './settlement'
import { useDmStore } from '../stores/dm'
import { useUiStore } from '../stores/ui'

/**
 * 好友事件通道（原 main 的 `friend_message` / `friend_request` 处理）。
 *
 * 复用共享 socket（`acquireSettlementChannel` 打开的连接），不新开连接、
 * 不轮询。事件名是后端 `services/friends.py` 的 `_push_friend_event` 发出的
 * 参数化 outbound，未进 events.gen.ts，所以这里的 on 做一次局部 cast
 * （与 realtime/lobby.ts 里 friend_invite 的处理同一先例，DECISIONS D21）。
 */
export type FriendsEventName = 'friend_message' | 'friend_request'

const FRIENDS_EVENTS: readonly FriendsEventName[] = ['friend_message', 'friend_request']

export interface FriendsEventHandlers {
  /** 收到好友申请时让面板刷新列表/计数。 */
  onRequest?: (payload: Record<string, unknown>) => void
}

/** 单帧 → store。测试构建与真线共用这一份实现。 */
export function applyFriendsEvent(
  event: FriendsEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
  handlers: FriendsEventHandlers = {},
): void {
  if (!payload || typeof payload !== 'object') return
  const dm = useDmStore(pinia)
  const ui = useUiStore(pinia)

  if (event === 'friend_message') {
    const result = dm.receivePush(payload)
    if (result.unread > 0) {
      ui.notify({
        code: 'dm-' + result.name,
        tone: 'info',
        message: `${result.name} 发来一条私聊`,
      })
    }
    return
  }

  const from = String(payload.from_username ?? '玩家')
  ui.notify({ code: 'friend-request-' + String(payload.from_user_id ?? from), tone: 'info', message: `${from} 想加你为好友` })
  handlers.onRequest?.(payload)
}

export function installFriendsListeners(
  socket: TypedSocket,
  pinia?: Pinia,
  handlers: FriendsEventHandlers = {},
): () => void {
  type Listener = (payload: Record<string, unknown>) => void
  const listen = socket.on as unknown as (event: string, handler: Listener) => () => void
  const offs = FRIENDS_EVENTS.map((event) =>
    listen(event, (payload) => applyFriendsEvent(event, payload, pinia, handlers)),
  )
  return () => {
    for (const off of offs) off()
  }
}

interface ActiveFriendsChannel {
  socket: TypedSocket
  releaseSettlement: () => void
  stop: () => void
  refs: number
}

let activeChannel: ActiveFriendsChannel | null = null

/** 打开（或复用）好友事件通道；返回释放函数，引用计数归零时断开监听。 */
export function acquireFriendsChannel(pinia?: Pinia, handlers: FriendsEventHandlers = {}): () => void {
  if (!activeChannel) {
    const releaseSettlement = acquireSettlementChannel(pinia)
    const socket = getSettlementSocket()
    if (!socket) {
      releaseSettlement()
      throw new Error('friends channel did not open a socket')
    }
    const stop = installFriendsListeners(socket, pinia, handlers)
    activeChannel = { socket, releaseSettlement, stop, refs: 0 }
  }
  const channel = activeChannel
  channel.refs += 1
  let released = false
  return () => {
    if (released) return
    released = true
    channel.refs -= 1
    if (channel.refs <= 0 && activeChannel === channel) {
      channel.stop()
      channel.releaseSettlement()
      activeChannel = null
    }
  }
}

export function friendsChannelSocket(): TypedSocket | null {
  return activeChannel?.socket ?? null
}
