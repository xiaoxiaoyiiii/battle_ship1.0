import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface DrawFlight {
  id: number
  room: string
  player: string
  index: number
  discard: boolean
}

/** 只记录真实摸牌事件，手牌同步、退款和重连不会凭空触发摸牌。 */
export const useCardDrawStore = defineStore('card-draw', () => {
  const queue = ref<DrawFlight[]>([])
  let sequence = 0
  function enqueue(payload: Record<string, unknown>): void {
    queue.value.push({ id: ++sequence, room: String(payload.room_id ?? ''),
      player: String(payload.player ?? ''), index: Math.max(0, Number(payload.hand_count ?? 1) - 1),
      discard: payload.destination === 'discard' })
  }
  function complete(id: number): void { queue.value = queue.value.filter(item => item.id !== id) }
  function reset(): void { queue.value = [] }
  return { queue, enqueue, complete, reset }
})
