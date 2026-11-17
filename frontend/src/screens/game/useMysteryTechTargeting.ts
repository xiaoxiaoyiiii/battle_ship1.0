import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useGameStore } from '../../stores/game'
import { useMysteryTechStore } from '../../stores/mysteryTech'
import { getSettlementSocket } from '../../realtime/settlement'
import { emitMysteryTechTarget } from '../../realtime/mysteryTech'
import type { MysteryTechCell } from '../../stores/mysteryTechTypes'
import {
  EMPTY_TARGET_DRAFT,
  applyMysteryTechTargetClick,
  formatCountdown,
  mysteryTechPreviewKeys,
  mysteryTechSelectedKeys,
  mysteryTechShipLabel,
  mysteryTechTargetBoard,
  mysteryTechTargetFields,
  mysteryTechTargetLegalKeys,
  mysteryTechTargetProgress,
  remainingMsUntil,
  targetKindHint,
  targetKindTitle,
  type MysteryTechBoardSide,
  type MysteryTechTargetDraft,
} from './mysteryTechView'

/**
 * 神秘科技结算瞄准，直接走对局里真实的战斗棋盘（与魔法卡选格同一套 BoardPanel 与点击通路）。
 * 只在 target.player_id 是本人时激活；对手瞄准时本人只看到叠加层的「对方正在结算」横幅。
 * 协议不变：确认时发 mystery_tech_target（request_id + x/y/ship_index），15 秒超时仍由服务器裁决。
 */
export function useMysteryTechTargeting() {
  const game = useGameStore()
  const tech = useMysteryTechStore()

  const now = ref(Date.now())
  const draft = ref<MysteryTechTargetDraft>({ ...EMPTY_TARGET_DRAFT })
  const hover = ref<MysteryTechCell | null>(null)
  const localError = ref('')
  let ticker: number | null = null

  const target = computed(() => {
    const snapshot = tech.state
    if (!(tech.enabled || game.state.mystery_tech === true || snapshot.enabled)) return null
    if (snapshot.stage !== 'targeting') return null
    const current = snapshot.target
    const me = game.state.player_id
    if (!current || !me || current.player_id !== me) return null
    return current
  })
  const active = computed(() => target.value !== null)
  const board = computed<MysteryTechBoardSide | null>(() => (target.value ? mysteryTechTargetBoard(target.value.kind) : null))

  const techName = computed(() => {
    const id = target.value?.tech_id
    if (!id) return ''
    const found = tech.state.selected.find((item) => item.tech_id === id)
    return found?.technology.name || id
  })
  const title = computed(() => (target.value ? targetKindTitle(target.value.kind, techName.value) : ''))
  const hint = computed(() => (target.value ? targetKindHint(target.value.kind, target.value.remaining) : ''))
  const progress = computed(() => mysteryTechTargetProgress(target.value, draft.value))
  const legalKeys = computed(() => mysteryTechTargetLegalKeys(target.value))
  const selectedKeys = computed(() => mysteryTechSelectedKeys(target.value, draft.value))
  const previewKeys = computed(() => mysteryTechPreviewKeys(target.value, draft.value, hover.value))
  const fields = computed(() => mysteryTechTargetFields(target.value, draft.value))
  const submitting = computed(() => tech.pending === 'target')
  const canConfirm = computed(() => fields.value !== null && !submitting.value)
  const error = computed(() => localError.value || tech.error)
  const remainingMs = computed(() => {
    const current = target.value
    if (!current) return 0
    return remainingMsUntil(current.deadline, null, tech.targetReceivedAt || tech.receivedAt, now.value)
  })
  const seconds = computed(() => formatCountdown(remainingMs.value))
  const urgent = computed(() => remainingMs.value <= 5000)
  const selectionKind = computed<'area' | 'ships' | null>(() => {
    const kind = target.value?.kind
    if (kind === 'sonar_pulse') return 'area'
    if (kind === 'revive') return 'ships'
    return null
  })
  const selectionTone = computed<'radar' | 'default'>(() => {
    const kind = target.value?.kind
    if (kind === 'sonar_pulse') return 'radar'
    return 'default'
  })
  const ships = computed(() => {
    const current = target.value
    if (!current || current.kind !== 'revive') return []
    return current.ships.map((ship, index) => ({
      shipIndex: ship.ship_index,
      label: mysteryTechShipLabel(current, ship, index),
      picked: draft.value.shipIndex === ship.ship_index,
    }))
  })

  watch(
    () => target.value?.request_id,
    () => {
      draft.value = { ...EMPTY_TARGET_DRAFT }
      hover.value = null
      localError.value = ''
    },
  )

  watch(
    active,
    (on) => {
      if (on && ticker === null) {
        now.value = Date.now()
        ticker = window.setInterval(() => { now.value = Date.now() }, 250)
      } else if (!on && ticker !== null) {
        window.clearInterval(ticker)
        ticker = null
      }
    },
    { immediate: true },
  )
  onBeforeUnmount(() => {
    if (ticker !== null) window.clearInterval(ticker)
    ticker = null
  })

  /** 返回 true 表示点击已被神秘科技瞄准消费（GameScreen 不再按开炮/魔法处理）。 */
  function onCell(side: MysteryTechBoardSide, x: number, y: number): boolean {
    const current = target.value
    if (!current) return false
    if (submitting.value) return true
    const next = applyMysteryTechTargetClick(current, draft.value, side, x, y)
    draft.value = next.draft
    localError.value = next.error
    if (!next.error) tech.setError('')
    return true
  }

  function onHover(side: MysteryTechBoardSide, point: { x: number; y: number } | null): void {
    hover.value = target.value && side === board.value ? point : null
  }

  function pickShip(shipIndex: number): void {
    const current = target.value
    if (!current || submitting.value) return
    if (!current.ships.some((ship) => ship.ship_index === shipIndex)) return
    draft.value = { ...draft.value, shipIndex }
    localError.value = ''
    tech.setError('')
  }

  function clearDraft(): void {
    draft.value = { ...EMPTY_TARGET_DRAFT }
    localError.value = ''
    tech.setError('')
  }

  async function confirm(): Promise<void> {
    const current = target.value
    const payload = fields.value
    if (!current || submitting.value) return
    if (!payload) {
      localError.value = current.kind === 'revive' && draft.value.shipIndex == null
        ? '请先选择一艘残骸。'
        : '请先在棋盘上点一个高亮目标。'
      return
    }
    const socket = getSettlementSocket()
    if (!socket) {
      localError.value = '还没有连上对局连接'
      return
    }
    localError.value = ''
    await emitMysteryTechTarget(socket, current.request_id, payload)
  }

  return {
    target,
    active,
    board,
    techName,
    title,
    hint,
    progress,
    legalKeys,
    selectedKeys,
    previewKeys,
    selectionKind,
    selectionTone,
    ships,
    canConfirm,
    submitting,
    error,
    seconds,
    urgent,
    onCell,
    onHover,
    pickShip,
    clearDraft,
    confirm,
  }
}
