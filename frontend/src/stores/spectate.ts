import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  asArray,
  asInt,
  asObject,
  asString,
  attackCells,
  displayName,
  isObject,
  normalizeCell,
  seatName,
  seatOf,
  type ChatKind,
  type SpectateCell,
  type SpectateChatLine,
  type SpectateLog,
  type SpectateRosterRow,
  type SpectateSide,
} from '../screens/spectate/view'

/**
 * Spectator session state (ticket #28).
 *
 * The spectator channel is the only source: the store copies whitelisted fields
 * from spectate_sync / spectate_board / the mirrored match events. It has no
 * field that could hold a ship position or a hand's contents; the boards are
 * rebuilt from "cells this seat shot at" (one transpose at render time).
 *
 * Chat lines get a monotonic sequence id: it is stable across re-renders and
 * unique, which array indices are not (and the selector contract forbids them).
 */
export type SpectatePhaseState = 'idle' | 'joining' | 'joined' | 'error' | 'ended'

const LOG_LIMIT = 200
const CHAT_LIMIT = 200

export const useSpectateStore = defineStore('spectate', () => {
  const phase = ref<SpectatePhaseState>('idle')
  const error = ref('')
  const roomId = ref('')
  const endedReason = ref('')
  const winnerLabel = ref('')

  const stateValue = ref('')
  const currentPhase = ref('')
  const currentAttacker = ref('')
  const attacksRemaining = ref(0)
  const round = ref(0)
  const fieldMagic = ref('')
  const ranked = ref(false)

  const seatLabels = ref<Record<string, string>>({})
  const sides = ref<{ p1: SpectateSide | null; p2: SpectateSide | null }>({ p1: null, p2: null })
  const attacks = ref<{ p1: SpectateCell[]; p2: SpectateCell[] }>({ p1: [], p2: [] })
  const logs = ref<SpectateLog[]>([])
  const chain = ref<Record<string, unknown> | null>(null)
  const roster = ref<SpectateRosterRow[]>([])
  const count = ref(0)
  const limit = ref(0)
  const me = ref('')
  const chat = ref<SpectateChatLine[]>([])

  let chatSeq = 0

  function pushChat(kind: ChatKind, name: string, text: string): void {
    const value = String(text ?? '').trim()
    if (!value) return
    chatSeq += 1
    chat.value.push({ seq: chatSeq, kind, name, text: value })
    if (chat.value.length > CHAT_LIMIT) chat.value = chat.value.slice(-CHAT_LIMIT)
  }

  function beginJoin(id: string): void {
    phase.value = 'joining'
    error.value = ''
    roomId.value = id
    endedReason.value = ''
    winnerLabel.value = ''
    stateValue.value = ''
    currentPhase.value = ''
    currentAttacker.value = ''
    attacksRemaining.value = 0
    round.value = 0
    fieldMagic.value = ''
    ranked.value = false
    seatLabels.value = {}
    sides.value = { p1: null, p2: null }
    attacks.value = { p1: [], p2: [] }
    logs.value = []
    chain.value = null
    roster.value = []
    count.value = 0
    limit.value = 0
    me.value = ''
    chat.value = []
  }

  function markJoined(payload: Record<string, unknown> | null | undefined): void {
    if (payload) {
      roomId.value = asString(payload.room_id) || roomId.value
      const reported = asInt(payload.count, -1)
      if (reported >= 0) count.value = reported
      const cap = asInt(payload.limit, -1)
      if (cap >= 0) limit.value = cap
    }
    if (phase.value !== 'ended') phase.value = 'joined'
  }

  function failJoin(message: string): void {
    phase.value = 'error'
    error.value = message || '进入观战失败'
  }

  function applySide(label: 'p1' | 'p2', raw: unknown): SpectateSide | null {
    if (!isObject(raw)) return null
    return {
      seatId: asString(raw.seat_id),
      name: asString(raw.name),
      remainingShips: asInt(raw.remaining_ships, 0),
      handCount: asInt(raw.hand_count, 0),
    }
  }

  function applySnapshot(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    roomId.value = asString(payload.room_id) || roomId.value
    stateValue.value = asString(payload.state)
    currentPhase.value = asString(payload.current_phase)
    currentAttacker.value = asString(payload.current_attacker)
    attacksRemaining.value = asInt(payload.attacks_remaining, 0)
    round.value = asInt(payload.round, 0)
    ranked.value = payload.ranked === true
    fieldMagic.value = asString(payload.field_magic)

    const labels: Record<string, string> = {}
    const rawLabels = asObject(payload.seat_labels)
    if (rawLabels) {
      for (const [key, value] of Object.entries(rawLabels)) {
        const label = asString(value)
        if (label === 'p1' || label === 'p2') labels[key] = label
      }
    }
    seatLabels.value = labels

    const rawSides = asObject(payload.sides) ?? {}
    sides.value = {
      p1: applySide('p1', rawSides.p1),
      p2: applySide('p2', rawSides.p2),
    }
    attacks.value = {
      p1: attackCells(isObject(rawSides.p1) ? rawSides.p1.attacks : null),
      p2: attackCells(isObject(rawSides.p2) ? rawSides.p2.attacks : null),
    }

    logs.value = []
    for (const entry of asArray(payload.game_logs)) {
      if (!isObject(entry)) continue
      logs.value.push({
        ts: asInt(entry.ts, 0),
        type: asString(entry.type),
        text: asString(entry.text),
      })
    }
    if (logs.value.length > LOG_LIMIT) logs.value = logs.value.slice(-LOG_LIMIT)

    chain.value = isObject(payload.chain) ? payload.chain : null
    roster.value = []
    for (const entry of asArray(payload.spectators)) {
      if (!isObject(entry)) continue
      roster.value.push({
        name: displayName(entry.name),
        joinedAt: asInt(entry.joined_at, 0),
      })
    }
    count.value = asInt(payload.spectator_count, count.value)
    limit.value = asInt(payload.spectator_limit, limit.value)

    const winnerKey = asString(payload.winner)
    if (winnerKey) {
      const label = seatOf(seatLabels.value, winnerKey)
      winnerLabel.value = label ? seatName(sides.value, label) : ''
    }
    if (stateValue.value === 'game_over') {
      phase.value = 'ended'
    } else if (phase.value !== 'ended') {
      phase.value = 'joined'
    }
  }

  function applyBoardFrame(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    const rawSides = asObject(payload.sides)
    if (!rawSides) return
    let applied = false
    for (const label of ['p1', 'p2'] as const) {
      const raw = rawSides[label]
      if (!isObject(raw) || !Array.isArray(raw.attacks)) continue
      attacks.value[label] = attackCells(raw.attacks)
      const current = sides.value[label]
      if (current) {
        const remaining = asInt(raw.remaining_ships, current.remainingShips)
        const hand = asInt(raw.hand_count, current.handCount)
        current.remainingShips = remaining
        current.handCount = hand
        if (raw.name !== undefined && raw.name !== null) current.name = asString(raw.name)
      } else {
        sides.value[label] = applySide(label, raw)
      }
      applied = true
    }
    if (!applied) return
    const labels = asObject(payload.seat_labels)
    if (labels) {
      const next: Record<string, string> = {}
      for (const [key, value] of Object.entries(labels)) {
        const label = asString(value)
        if (label === 'p1' || label === 'p2') next[key] = label
      }
      seatLabels.value = next
    }
  }

  function applyAttackResult(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    const label = seatOf(seatLabels.value, payload.attacker)
    if (!label) return
    if (payload.shield_blocked !== true) {
      const cell = normalizeCell({
        x: payload.x,
        y: payload.y,
        hit: payload.hit,
        ship_sunk: payload.ship_sunk,
      })
      if (cell) {
        const list = attacks.value[label]
        const index = list.findIndex((item) => item.x === cell.x && item.y === cell.y)
        if (index >= 0) list[index] = cell
        else list.push(cell)
      }
    }
    const other = label === 'p1' ? 'p2' : 'p1'
    const attackerSide = sides.value[label]
    if (attackerSide) {
      attackerSide.remainingShips = asInt(payload.attacker_remaining_ships, attackerSide.remainingShips)
    }
    const defenderSide = sides.value[other]
    if (defenderSide) {
      defenderSide.remainingShips = asInt(payload.defender_remaining_ships, defenderSide.remainingShips)
    }
    attacksRemaining.value = asInt(payload.remaining_attacks, attacksRemaining.value)
  }

  function applyTurnChange(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    currentAttacker.value = asString(payload.current_attacker) || currentAttacker.value
    attacksRemaining.value = asInt(payload.attacks_remaining, attacksRemaining.value)
    const step = asString(payload.phase)
    if (step) currentPhase.value = step
  }

  function applyPhaseUpdated(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    const phaseValue = asString(payload.current_phase) || asString(payload.phase)
    if (phaseValue) currentPhase.value = phaseValue
    if (payload.current_attacker !== undefined) currentAttacker.value = asString(payload.current_attacker)
    if (payload.attacks_remaining !== undefined) {
      attacksRemaining.value = asInt(payload.attacks_remaining, attacksRemaining.value)
    }
    if (payload.round !== undefined) round.value = asInt(payload.round, round.value)
    if (payload.field_magic !== undefined) fieldMagic.value = asString(payload.field_magic)
  }

  function applyAttacksUpdated(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    if (payload.current_attacker !== undefined) currentAttacker.value = asString(payload.current_attacker)
    attacksRemaining.value = asInt(payload.attacks_remaining, attacksRemaining.value)
  }

  function applyLog(entry: unknown): void {
    if (!isObject(entry)) return
    if (!asString(entry.text)) return
    logs.value.push({
      ts: asInt(entry.ts, 0),
      type: asString(entry.type),
      text: asString(entry.text),
    })
    if (logs.value.length > LOG_LIMIT) logs.value = logs.value.slice(-LOG_LIMIT)
  }

  function applyChain(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    chain.value = payload
  }

  function applyFieldMagic(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    const card = asObject(payload.card)
    fieldMagic.value = card ? asString(card.name) : asString(payload.name)
  }

  function applyRoster(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    const rows = asArray(payload.spectators)
    roster.value = []
    for (const entry of rows) {
      if (!isObject(entry)) continue
      roster.value.push({
        name: displayName(entry.name),
        joinedAt: asInt(entry.joined_at, 0),
      })
    }
    count.value = asInt(payload.count, roster.value.length)
    limit.value = asInt(payload.limit, limit.value)
  }

  function applyCount(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    const next = asInt(payload.count, -1)
    if (next >= 0) count.value = next
  }

  function applyYou(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    me.value = asString(payload.name)
  }

  function applyChat(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    pushChat('msg', displayName(payload.name), asString(payload.message))
  }

  function applyPlayerChat(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    pushChat('player', displayName(payload.username), asString(payload.message))
  }

  function applyGameOver(payload: Record<string, unknown> | null | undefined): void {
    if (!isObject(payload)) return
    const winnerKey = asString(payload.winner)
    const label = seatOf(seatLabels.value, winnerKey)
    winnerLabel.value = label ? seatName(sides.value, label) : ''
    phase.value = 'ended'
  }

  function applyEnded(payload: Record<string, unknown> | null | undefined): void {
    if (isObject(payload)) endedReason.value = asString(payload.reason)
    phase.value = 'ended'
  }

  function chatNotice(text: string, kind: ChatKind = 'notice'): void {
    pushChat(kind, '', text)
  }

  function reset(): void {
    phase.value = 'idle'
    error.value = ''
    roomId.value = ''
    endedReason.value = ''
    winnerLabel.value = ''
    stateValue.value = ''
    currentPhase.value = ''
    currentAttacker.value = ''
    attacksRemaining.value = 0
    round.value = 0
    fieldMagic.value = ''
    ranked.value = false
    seatLabels.value = {}
    sides.value = { p1: null, p2: null }
    attacks.value = { p1: [], p2: [] }
    logs.value = []
    chain.value = null
    roster.value = []
    count.value = 0
    limit.value = 0
    me.value = ''
    chat.value = []
    chatSeq = 0
  }

  return {
    phase,
    error,
    roomId,
    endedReason,
    winnerLabel,
    stateValue,
    currentPhase,
    currentAttacker,
    attacksRemaining,
    round,
    fieldMagic,
    ranked,
    seatLabels,
    sides,
    attacks,
    logs,
    chain,
    roster,
    count,
    limit,
    me,
    chat,
    beginJoin,
    markJoined,
    failJoin,
    applySnapshot,
    applyBoardFrame,
    applyAttackResult,
    applyTurnChange,
    applyPhaseUpdated,
    applyAttacksUpdated,
    applyLog,
    applyChain,
    applyFieldMagic,
    applyRoster,
    applyCount,
    applyYou,
    applyChat,
    applyPlayerChat,
    applyGameOver,
    applyEnded,
    chatNotice,
    reset,
  }
})