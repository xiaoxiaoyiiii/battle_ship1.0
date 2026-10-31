import { computed, ref, watch } from 'vue'
import { useGameStore } from '../../stores/game'
import { useCardEffectsStore } from '../../stores/cardEffects'
import { sendBattleEvent } from '../../realtime/battle'
import type { Point } from './view'

const NAMES: Record<string, string> = {
  reinforce: '增援', revive: '死者苏生', last_stand: '绝处逢生',
  lanyu: '滥竽充数', shenji_redeploy: '神机妙算重部署', contract_gain: '恶魔契约',
}

function keys(values: unknown[]): Set<string> {
  const result = new Set<string>()
  for (const value of values) {
    const point = Array.isArray(value) ? { x: value[0], y: value[1] } : value as Point | null
    if (point && Number.isInteger(point.x) && Number.isInteger(point.y)) result.add(`${point.x}-${point.y}`)
  }
  return result
}

/** 局内逐艘部署只消费服务端请求，坐标在主战斗棋盘上选择。 */
export function useMagicPlacement() {
  const game = useGameStore()
  const cardEffects = useCardEffectsStore()
  const request = computed(() => game.state.pending_placement)
  const active = computed(() => Boolean(request.value) && !game.state.dice_discard_pending && !cardEffects.busy)
  const kind = computed(() => String(request.value?.kind ?? ''))
  const title = computed(() => NAMES[kind.value] || '部署战舰')
  const hint = computed(() => String(request.value?.message || (kind.value === 'last_stand'
    ? '在自己的海域选择原本有战舰的位置。'
    : '在自己的海域选择一个合法位置，每次部署一艘。')))
  const selected = ref<Point | null>(null)
  const busy = ref(false)
  const error = ref('')
  const legalKeys = computed(() => {
    if (!active.value) return []
    const blocked = keys(game.state.pending_placement_blocked)
    const allowed = keys(game.state.pending_placement_allowed)
    // 绝处逢生仅限原船位；神机等模式的 allowed 是例外信息，不是通用白名单。
    return Array.from({ length: 36 }, (_, index) => `${index % 6}-${Math.floor(index / 6)}`)
      .filter(key => kind.value === 'last_stand' ? allowed.has(key) : !blocked.has(key))
  })
  const selectedKeys = computed(() => selected.value ? [`${selected.value.x}-${selected.value.y}`] : [])
  watch([
    () => game.state.room_id, () => game.state.magic_temp?.id, kind,
    () => request.value?.remaining, () => request.value?.placed,
  ], () => { selected.value = null; error.value = '' })

  function choose(board: 'self' | 'opponent', x: number, y: number): void {
    if (!active.value || busy.value) return
    if (board !== 'self') { error.value = '请在自己的海域选择部署位置。'; return }
    if (!legalKeys.value.includes(`${x}-${y}`)) { error.value = '这个位置不能部署，请选择合法格。'; return }
    selected.value = { x, y }
    error.value = ''
  }

  async function submit(cancel = false): Promise<void> {
    if (busy.value || !active.value || (!cancel && !selected.value)) return
    if (!cancel && !legalKeys.value.includes(`${selected.value!.x}-${selected.value!.y}`)) {
      error.value = '这个位置不能部署，请重新选择。'
      return
    }
    busy.value = true
    error.value = ''
    try {
      const ack = await sendBattleEvent(cancel ? 'cancel_placement' : 'confirm_reinforcement_position', {
        room_id: game.state.room_id, player_id: game.state.player_id,
        ...(cancel ? {} : { position: { ...selected.value! } }),
      })
      if (ack.status !== 'success') error.value = ack.message || '部署失败，请调整位置后重试。'
      // ACK 不推进进度；placement_request / placement_done / room_sync 是唯一依据。
    } catch { error.value = '连接不稳定，放置请求仍保留，请重试。' }
    finally { busy.value = false }
  }

  return { request, active, kind, title, hint, selected, selectedKeys, legalKeys, busy, error, choose, submit }
}
