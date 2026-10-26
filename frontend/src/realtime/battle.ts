import type { Pinia } from 'pinia'
import { ref, watch } from 'vue'
import type { TypedSocket } from '../socket/client'
import {
  acquireSettlementChannel,
  getSettlementSocket,
} from './settlement'
import { useGameStore } from '../stores/game'
import { useMatchStore } from '../stores/match'
import { useUiStore } from '../stores/ui'
import { useAudioStore } from '../stores/audio'
import type { InboundEvent, OutboundEvent } from '../socket/events.gen'
import type { CardLike, Point } from '../screens/game/view'
import { actionWaitReason, WAIT_EXEMPT_EVENTS } from '../screens/game/view'

/**
 * The live battle wire channel (ticket #27).
 *
 * The game screen acquires the *settlement* channel first (ref-counted, one
 * socket), then installs these listeners on that same socket. That order is
 * load-bearing: game_over/game_state are owned by the settlement channel, so an
 * in-game ending lands in the result store while the game screen is still
 * mounted (the #22 deviation, see docs/FRONTEND_GAMEOVER_2026_10_20.md §5).
 *
 * The reducer (`applyBattleEvent`) is the single implementation shared by the
 * wire and by the test build's `battle.feed`, exactly like the settlement
 * sample. It only merges server frames into the stores; it never re-derives a
 * rule.
 */

export const BATTLE_EVENTS = [
  'attack_result',
  'attacks_updated',
  'board_attacks_updated',
  'turn_change',
  'phase_updated',
  'hand_updated',
  'game_log',
  'magic_chain_updated',
  'chain_request',
  'chain_resolved',
  'field_magic_updated',
  'active_effects',
  'player_ships_updated',
  'shield_absorbed',
  'shields_added',
  'revealed_positions',
  'revived_positions',
  'shenwei_hole',
  'shenwei_hole_restored',
  'frozen_area',
  'last_stand_cells',
  'ship_sacrificed',
  'trap_set',
  'trap_triggered',
  'game_message',
  'message',
  'error',
  'quick_chat',
  'chat_message',
  'sacrifice_request',
  'sacrifice_cancelled',
  'placement_request',
  'placement_done',
  'priority_waiting',
  'priority_waiting_end',
  'priority_request',
  'priority_setting_updated',
  'shenji_waiting',
  'shenji_waiting_end',
  'dice_discard_request',
  'dice_discard_complete',
  'opponent_disconnected',
  'opponent_reconnected',
] as const satisfies readonly OutboundEvent[]

export type BattleEventName = (typeof BATTLE_EVENTS)[number]

export type BattleEmitEvent =
  | 'attack'
  | 'enter_battle_phase'
  | 'enter_end_phase'
  | 'end_turn'
  | 'use_magic_card'
  | 'chain_response'
  | 'quick_chat'
  | 'chat_message'
  | 'confirm_sacrifice'
  | 'confirm_reinforcement_position'
  | 'cancel_placement'
  | 'confirm_magic_target'
  | 'cancel_magic_selection'
  | 'request_hand_sync'
  | 'surrender'
  | 'get_discard_pile'
  | 'papal_discard'
  | 'get_magic_temp_data'
  | 'confirm_shenji_declare'
  | 'dice_discard_choose'
  | 'priority_response'
  | 'set_decline_priority'

export const BATTLE_EMIT_EVENTS: readonly BattleEmitEvent[] = [
  'attack',
  'enter_battle_phase',
  'enter_end_phase',
  'end_turn',
  'use_magic_card',
  'chain_response',
  'quick_chat',
  'chat_message',
  'confirm_sacrifice',
  'confirm_reinforcement_position',
  'cancel_placement',
  'confirm_magic_target',
  'cancel_magic_selection',
  'request_hand_sync',
  'surrender',
  'get_discard_pile',
  'papal_discard',
  'get_magic_temp_data',
  'confirm_shenji_declare',
  'dice_discard_choose',
  'priority_response',
  'set_decline_priority',
]

const ALLOWED_EMITS: readonly string[] = BATTLE_EMIT_EVENTS satisfies readonly InboundEvent[]
/** 全部对局面板共用，防止不同按钮在上一请求未完成时重复写入。 */
export const battleActionPending = ref(false)

function numberOrNull(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function asCardList(value: unknown): CardLike[] {
  if (!Array.isArray(value)) return []
  const cards: CardLike[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    if (typeof record.name !== 'string' || !record.name) continue
    cards.push({
      name: record.name,
      speed: (record.speed as number | string) ?? 0,
      type: String(record.type ?? ''),
      description: String(record.description ?? ''),
    })
  }
  return cards
}

function pointList(value: unknown): Point[] {
  if (!Array.isArray(value)) return []
  const points: Point[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const x = numberOrNull(record.x)
    const y = numberOrNull(record.y)
    if (x !== null && y !== null) points.push({ x, y })
  }
  return points
}

function appendCell(list: unknown, point: Point, hit: boolean): Array<{ x: number; y: number; hit: boolean }> {
  const cells = Array.isArray(list) ? (list as Array<{ x: number; y: number; hit: boolean }>) : []
  if (cells.some((cell) => cell && cell.x === point.x && cell.y === point.y)) return cells.slice()
  return [...cells, { x: point.x, y: point.y, hit }]
}

/**
 * The 90s watchdog frames say what the server did for the player ("思考超时：已
 * 自动开火 (2,3)"). Ticket #47 shows them as a HUD banner instead of a toast
 * that can vanish before the player looks back at the screen.
 */
function noteTimeoutIfAny(match: ReturnType<typeof useMatchStore>, text: string): void {
  if (text.includes('超时')) match.setTimeoutNote(text)
}

/** Apply one battle frame to the stores. Shared by the wire and the test build. */
export function applyBattleEvent(
  event: BattleEventName,
  payload: Record<string, unknown> | null | undefined,
  pinia?: Pinia,
): void {
  if (!payload || typeof payload !== 'object') return
  const game = useGameStore(pinia)
  const match = useMatchStore(pinia)
  const audio = useAudioStore(pinia)
  const state = game.state
  const me = state.player_id

  // 消费护盾的事件立即更新本地船状态，不等待下一份完整快照。
  function breakOwnShield(points: Point[]) {
    const keys = new Set(points.map(p => `${p.x}-${p.y}`))
    game.applyServerState({ ships: state.ships.map(ship => ship.positions.some(p => keys.has(`${p.x}-${p.y}`)) ? { ...ship, shield: false } : ship) })
  }

  switch (event) {
    case 'attack_result': {
      const x = numberOrNull(payload.x)
      const y = numberOrNull(payload.y)
      if (x === null || y === null) return
      const hit = Boolean(payload.hit)
      const attacker = String(payload.attacker ?? '')
      const shipSunk = Boolean(payload.ship_sunk)
      const shieldBlocked = Boolean(payload.shield_blocked)
      game.applyServerState({ last_attack: { attacker, x, y, hit, ship_sunk: shipSunk } })
      audio.play(shipSunk ? 'sunk' : hit ? 'hit' : 'miss')
      const mine = attacker === me
      if (hit && !shieldBlocked) match.clearRevived(!mine, [{ x, y }])
      if (mine) {
        // A shield-absorbed shot spends the attack but does not mark the cell
        // (legacy), so the same cell stays attackable.
        if (!shieldBlocked) game.applyServerState({ attacks: appendCell(state.attacks, { x, y }, hit) })
        else match.markShieldBroken(false, [{ x, y }])
      } else if (!shieldBlocked) {
        game.applyServerState({ opponent_attacks: appendCell(state.opponent_attacks, { x, y }, hit) })
      } else {
        match.markShieldBroken(true, [{ x, y }])
        breakOwnShield([{ x, y }])
      }
      const remaining = numberOrNull(payload.remaining_attacks)
      if (remaining !== null) game.applyServerState({ attacks_remaining: remaining })
      const attackerShips = numberOrNull(payload.attacker_remaining_ships)
      const defenderShips = numberOrNull(payload.defender_remaining_ships)
      if (attackerShips !== null || defenderShips !== null) {
        game.applyServerState(
          mine
            ? { remaining_ships: attackerShips, opponent_remaining_ships: defenderShips }
            : { remaining_ships: defenderShips, opponent_remaining_ships: attackerShips },
        )
      }
      break
    }
    case 'attacks_updated': {
      const remaining = numberOrNull(payload.attacks_remaining)
      game.applyServerState({
        current_attacker: String(payload.current_attacker ?? state.current_attacker),
        ...(remaining !== null ? { attacks_remaining: remaining } : {}),
      })
      break
    }
    case 'turn_change': {
      audio.play('turn')
      const remaining = numberOrNull(payload.attacks_remaining)
      game.applyServerState({
        current_attacker: String(payload.current_attacker ?? state.current_attacker),
        ...(payload.phase ? { current_phase: String(payload.phase) } : {}),
        ...(remaining !== null ? { attacks_remaining: remaining } : {}),
      })
      break
    }
    case 'phase_updated': {
      game.applyServerState({
        ...(payload.current_phase ? { current_phase: String(payload.current_phase) } : {}),
        current_attacker: String(payload.current_attacker ?? state.current_attacker),
      })
      break
    }
    case 'hand_updated': {
      const hand = asCardList(payload.hand)
      if (Array.isArray(payload.hand)) {
        if (hand.length > (Array.isArray(state.hand) ? state.hand.length : 0)) audio.play('draw')
        game.applyServerState({ hand })
      }
      break
    }
    case 'game_log': {
      match.appendLog({
        ts: Number(payload.ts ?? 0) || 0,
        type: String(payload.type ?? 'info'),
        text: String(payload.text ?? ''),
        detail: payload.detail ?? null,
      })
      break
    }
    case 'magic_chain_updated': {
      game.applyServerState({ chain: payload })
      break
    }
    case 'chain_request': {
      audio.play('chain')
      match.openChainWindow(payload)
      break
    }
    case 'chain_resolved': {
      game.applyServerState({ chain: { chain: [], chain_len: 0, targets_dropped: 0 } })
      match.closeChainWindow()
      match.chainResolvedAt = Date.now()
      const results = Array.isArray(payload.results) ? payload.results : []
      for (const raw of results) {
        if (!raw || typeof raw !== 'object') continue
        const result = raw as Record<string, unknown>
        const card = result.card && typeof result.card === 'object' ? (result.card as Record<string, unknown>) : null
        const name = card ? String(card.name ?? '') : ''
        if (result.negated_skip) {
          match.pushNotice(`「${name}」被「${String(result.negated_by ?? '失灵！')}」无效化`, 'warning')
        } else if (String(result.message ?? '').trim() && (result.success === false || (!result.temp_data_id && !['回光返照', '败者食尘'].includes(name)))) {
          match.pushNotice(String(result.message), result.success === false ? 'warning' : 'info')
        }
        if (String(result.temp_data_id ?? '') === 'shield_choice'
          && String(result.caster ?? '') === me
          && result.success !== false) {
          match.openShieldChoice({
            message: String(result.message ?? '仁王之盾：请选择要保护的战舰（至多 3 艘）'),
            caster: me,
          })
        }
        if (result.success !== false && !result.negated_skip) audio.play('play_card')
      }
      void refreshMagicState(pinia)
      break
    }
    case 'field_magic_updated': {
      const card = payload.card && typeof payload.card === 'object' ? (payload.card as Record<string, unknown>) : null
      game.applyServerState({ field_magic: card ? String(card.name ?? '') : '' })
      break
    }
    case 'active_effects': {
      game.applyServerState({
        effect_badges: {
          self: Array.isArray(payload.self) ? (payload.self as Array<Record<string, unknown>>) : [],
          opponent: Array.isArray(payload.opponent) ? (payload.opponent as Array<Record<string, unknown>>) : [],
          field:
            payload.field && typeof payload.field === 'object'
              ? (payload.field as Record<string, unknown>)
              : null,
          field_owner: typeof payload.field_owner === 'string' ? payload.field_owner : null,
        },
      })
      break
    }
    case 'player_ships_updated': {
      if (Array.isArray(payload.ships)) game.applyServerState({ ships: payload.ships })
      match.clearRevived(true, state.ships.filter(ship => ship.alive === false).flatMap(ship => ship.positions))
      break
    }
    case 'board_attacks_updated': {
      game.applyServerState({
        ...(Array.isArray(payload.my_attacks) ? { attacks: payload.my_attacks } : {}),
        ...(Array.isArray(payload.opponent_attacks) ? { opponent_attacks: payload.opponent_attacks } : {}),
      })
      match.clearRevived(false, state.attacks.filter(cell => cell.hit))
      match.clearRevived(true, state.opponent_attacks.filter(cell => cell.hit))
      break
    }
    case 'shield_absorbed': {
      const owner = String(payload.player ?? '')
      const mine = owner === me
      const positions = pointList(payload.positions)
      match.markShieldBroken(mine, positions)
      if (mine) breakOwnShield(positions)
      if (mine) match.pushNotice('你的护盾挡下了这一炮：该格本回合还能被再次攻击', 'warning')
      break
    }
    case 'shields_added': {
      const count = numberOrNull(payload.count) ?? 0
      const owner = String(payload.player ?? '')
      match.pushNotice(owner === me ? `${count} 艘战舰获得了护盾` : `对手 ${count} 艘战舰获得了护盾`)
      break
    }
    case 'revealed_positions': {
      match.markRevealed(pointList(payload.positions))
      game.applyServerState({ revealed_positions: match.revealed.map(point => ({ ...point })) })
      break
    }
    case 'revived_positions': {
      const owner = String(payload.player ?? '')
      if (!owner) break
      match.markRevived(owner === me, pointList(payload.positions))
      break
    }
    case 'shenwei_hole': {
      const area = payload.area && typeof payload.area === 'object' ? (payload.area as Record<string, unknown>) : null
      if (!area) break
      const hole = {
        player: String(payload.player ?? ''),
        x1: Number(area.x1),
        y1: Number(area.y1),
        x2: Number(area.x2),
        y2: Number(area.y2),
        return_turn: Number(payload.return_turn ?? 0),
      }
      const holes = Array.isArray(state.shenwei_holes) ? state.shenwei_holes.slice() : []
      holes.push(hole)
      game.applyServerState({ shenwei_holes: holes })
      match.pushNotice(
        hole.player === me ? '神威！：你的这片 3×3 区域被暂时扣掉，无法攻击' : '神威！：对方一片 3×3 区域被暂时扣掉',
        'warning',
      )
      break
    }
    case 'shenwei_hole_restored': {
      const owner = String(payload.player ?? '')
      const holes = (Array.isArray(state.shenwei_holes) ? state.shenwei_holes : []).filter(
        (hole) => !(hole && typeof hole === 'object' && (hole as Record<string, unknown>).player === owner),
      )
      game.applyServerState({ shenwei_holes: holes })
      match.pushNotice('神威！：被扣掉的战舰已回到棋盘')
      break
    }
    case 'frozen_area': {
      if (payload.cleared) {
        game.applyServerState({ frozen_area: null })
        break
      }
      game.applyServerState({ frozen_area: { ...payload } })
      const count = numberOrNull(payload.frozen) ?? 0
      match.pushNotice(
        String(payload.owner ?? '') === me
          ? `对方冻结了你的 3×3 区域${count ? `（${count} 艘被冻）` : ''}`
          : `你冻结了对方 3×3 区域${count ? `（${count} 艘被冻）` : ''}`,
        'warning',
      )
      break
    }
    case 'last_stand_cells': {
      game.applyServerState({
        last_stand_cells: Array.isArray(payload.cells) ? payload.cells : [],
        last_stand_owner: payload.owner ? String(payload.owner) : null,
      })
      break
    }
    case 'ship_sacrificed': {
      const owner = String(payload.player ?? '')
      match.pushNotice(owner === me ? '你的一艘战舰被牺牲了' : '对方的一艘战舰被牺牲了', 'warning')
      break
    }
    case 'trap_set': {
      match.pushNotice(
        String(payload.player ?? '') === me ? '你为一艘战舰设置了陷阱' : '对手为一艘战舰设置了陷阱',
      )
      break
    }
    case 'trap_triggered': {
      match.pushNotice('陷阱触发', 'warning')
      break
    }
    case 'game_message': {
      const text = String(payload.message ?? '')
      noteTimeoutIfAny(match, text)
      break
    }
    case 'message': {
      const text = String(payload.text ?? payload.message ?? '')
      noteTimeoutIfAny(match, text)
      break
    }
    case 'error': {
      break
    }
    case 'quick_chat': {
      match.recordQuickChat(payload)
      break
    }
    case 'chat_message': {
      match.recordChatMessage(payload)
      break
    }
    case 'sacrifice_request': {
      match.setPickRequest(payload)
      break
    }
    case 'sacrifice_cancelled': {
      match.clearPickRequest()
      break
    }
    case 'placement_request': {
      game.applyServerState({
        pending_placement: { ...payload, caster: state.player_id },
        pending_placement_blocked: Array.isArray(payload.blocked) ? payload.blocked : [],
        pending_placement_allowed: Array.isArray(payload.allowed) ? payload.allowed : [],
      })
      break
    }
    case 'placement_done': {
      game.applyServerState({ pending_placement: null, pending_placement_blocked: [], pending_placement_allowed: [] })
      break
    }
    case 'priority_request':
    case 'priority_waiting': {
      game.applyServerState({
        priority_waiting: {
          ...payload,
          role: event === 'priority_request' ? 'responder' : 'actor',
          action: String(payload.action ?? ''),
          action_text: String(payload.action_text ?? '阶段转换'),
        },
      })
      break
    }
    case 'priority_waiting_end': {
      if (!payload.token || game.state.priority_waiting?.token === payload.token) {
        game.applyServerState({ priority_waiting: null })
      }
      break
    }
    case 'priority_setting_updated': {
      useUiStore(pinia).setPhasePrompts(payload.decline !== true)
      break
    }
    case 'shenji_waiting': {
      game.applyServerState({ shenji_waiting: { text: String(payload.text ?? '等待对方神机妙算宣言中') } })
      break
    }
    case 'shenji_waiting_end': {
      game.applyServerState({ shenji_waiting: null })
      break
    }
    case 'dice_discard_request': {
      game.applyServerState({ dice_discard_pending: true, dice_discard_card: String(payload.card ?? '魔法效果') })
      match.diceDiscardMessage = String(payload.message ?? '')
      break
    }
    case 'dice_discard_complete': {
      match.diceDiscardMessage = ''
      game.applyServerState({ dice_discard_pending: false, dice_discard_card: null })
      break
    }
    case 'opponent_disconnected': {
      match.pushNotice('对手已掉线，等待重连中', 'warning')
      break
    }
    case 'opponent_reconnected': {
      match.pushNotice('对手已重新连接')
      break
    }
  }
}

const isBattleEvent = (event: string): event is BattleEventName =>
  (BATTLE_EVENTS as readonly string[]).includes(event)

export function installBattleListeners(socket: TypedSocket, pinia?: Pinia): () => void {
  const offs = (BATTLE_EVENTS as readonly string[]).map((event) =>
    socket.on(event as OutboundEvent, (payload) => {
      if (isBattleEvent(event)) applyBattleEvent(event, payload, pinia)
    }),
  )
  return () => {
    for (const off of offs) off()
  }
}

interface ActiveChannel {
  socket: TypedSocket
  releaseSettlement: () => void
  stop: () => void
  refs: number
}

let active: ActiveChannel | null = null

/** Acquire the battle channel (opens the shared settlement socket first). */
export function acquireBattleChannel(pinia?: Pinia): () => void {
  if (!active) {
    const releaseSettlement = acquireSettlementChannel(pinia)
    const socket = getSettlementSocket()
    if (!socket) {
      releaseSettlement()
      throw new Error('settlement channel did not open a socket')
    }
    const stopListeners = installBattleListeners(socket, pinia)
    // Connection state is a HUD fact (spec §5), so it is mirrored into the game
    // store here — the only place that owns this socket. No second flag.
    const ui = useUiStore(pinia)
    const game = useGameStore(pinia)
    const syncPhasePreference = (): void => {
      if (!socket.socket.connected || !game.state.room_id || !game.state.player_id) return
      void socket.emitEvent('set_decline_priority', {
        room_id: game.state.room_id, player_id: game.state.player_id, decline: !ui.phasePrompts,
      }).catch(() => { /* 重连时再次同步。 */ })
    }
    const stopPhasePreference = watch(
      () => [game.state.room_id, game.state.player_id, ui.phasePrompts],
      syncPhasePreference, { immediate: true },
    )
    const onConnect = (): void => {
      ui.setConnection(true)
      syncPhasePreference()
      // Ticket #53: the RPS draw is emitted before this channel exists. Pull the
      // authoritative hand once we are connected so the game screen never opens
      // with 0 cards (frozen event, no new protocol).
      void syncHand(socket, pinia)
    }
    const onDisconnect = (): void => ui.setConnection(false)
    socket.socket.on('connect', onConnect)
    socket.socket.on('disconnect', onDisconnect)
    ui.setConnection(socket.socket.connected)
    active = {
      socket,
      releaseSettlement,
      stop: () => {
        socket.socket.off('connect', onConnect)
        socket.socket.off('disconnect', onDisconnect)
        stopPhasePreference()
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

/** Ask the server for the authoritative hand of the current seat. */
export async function syncHand(socket: TypedSocket | null, pinia?: Pinia): Promise<void> {
  if (!socket || !socket.socket.connected) return
  const game = useGameStore(pinia)
  const roomId = game.state.room_id
  const playerId = game.state.player_id
  if (!roomId || !playerId) return
  try {
    await socket.emitEvent('request_hand_sync', { room_id: roomId, player_id: playerId })
  } catch {
    // The screen keeps the hand it already has; the next frame self-heals it.
  }
}

export function getBattleSocket(): TypedSocket | null {
  return active?.socket ?? null
}

let magicReadSeq = 0
/** 当前激活待项由服务端选定，结算结果里排队的后续项不能抢先打开。 */
export async function refreshMagicState(pinia?: Pinia): Promise<void> {
  const socket = getBattleSocket()
  const game = useGameStore(pinia)
  const roomId = game.state.room_id, playerId = game.state.player_id
  if (!socket || !roomId || !playerId) return
  const seq = ++magicReadSeq, previous = game.state.magic_temp
  try {
    const ack = await socket.emitEvent('get_magic_temp_data', { room_id: roomId, player_id: playerId })
    if (seq !== magicReadSeq || game.state.room_id !== roomId || game.state.player_id !== playerId || game.state.magic_temp !== previous) return
    game.applyServerState({ magic_temp: ack.status === 'success' ? ack.data ?? null : null })
  } catch { /* 请求失败不清掉尚未完成的选择；重连快照会恢复。 */ }
}

export function battleSocketConnected(): boolean {
  return active?.socket.socket.connected ?? false
}

/** Send one battle action through the shared typed socket. */
export function sendBattleEvent(
  event: BattleEmitEvent,
  data: Record<string, unknown>,
): Promise<{ status: string; message?: string | null; data?: Record<string, unknown> | null }> {
  const socket = active?.socket ?? null
  if (!socket) return Promise.reject(new Error('battle channel is not connected'))
  if (!ALLOWED_EMITS.includes(event)) return Promise.reject(new Error(`event not allowed: ${event}`))
  const match = useMatchStore()
  const waiting = actionWaitReason(useGameStore().state, event, {
    pending: battleActionPending.value,
    chainBusy: Boolean(match.chainWindow),
    interactionReason: match.pickRequest?.message || (match.shieldChoice ? '请先完成仁王之盾的选船' : ''),
  })
  if (waiting) return Promise.resolve({ status: 'error', message: waiting })
  if (WAIT_EXEMPT_EVENTS.includes(event)) return socket.emitEvent(event, data)
  battleActionPending.value = true
  return socket.emitEvent(event, data).finally(() => { battleActionPending.value = false })
}

/** Test-build helper: drop the singleton between browser checks. */
export function resetBattleChannelForTest(): void {
  if (!active) return
  active.stop()
  active = null
}
