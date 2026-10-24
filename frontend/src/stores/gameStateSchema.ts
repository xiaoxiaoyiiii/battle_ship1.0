import { ROOM_SYNC_FIELDS, type RoomSyncField } from '../socket/events.gen'

/**
 * Explicit mirror of the server game state (ticket #21).
 *
 * The contract source is `battleship.contracts.events_out.RoomSync` — the
 * widest snapshot a client can receive (room_sync, 45 keys). `game_state` sends
 * subsets of the same fields plus two game-over-only keys (`winner_card`,
 * `loser_cards`). `ROOM_SYNC_FIELDS` is generated into events.gen.ts, and the
 * type-level parity checks below fail `vue-tsc` if a key is added, renamed or
 * dropped on either side.
 *
 * Every field carries an explicit type and an explicit default; the store is
 * built from these defaults so there is no bare global and no implicit
 * `undefined` state (a missing key used to read as `undefined` in the legacy
 * `gameState` object and silently disabled UI branches).
 */

export type GameStateFieldType = 'string' | 'number' | 'boolean' | 'array' | 'object'

export interface GameStateFieldSpec {
  readonly type: GameStateFieldType
  readonly nullable: boolean
  readonly default: unknown
  readonly note: string
}

export interface ShipSnapshot {
  positions: Array<{ x: number; y: number }>
  frozen: boolean
  shield: boolean
  /** 仅本人的舰船快照携带；旧载荷缺省为无陷阱。 */
  trap?: boolean
  alive: boolean
  /** Only `player_ships_updated` carries it; room_sync ships omit the flag. */
  invincible?: boolean
}

export interface CellAttack {
  x: number
  y: number
  hit: boolean
}

export interface GameState {
  room_id: string
  state: string
  current_phase: string | null
  current_attacker: string
  attacks_remaining: number
  round: number
  attack_order: string[]
  player_id: string
  player_seat: string
  player_name: string | null
  opponent_name: string | null
  is_ai_room: boolean
  ranked: boolean
  mode: string
  winner: string
  game_over_reason: string | null
  field_magic: string
  remaining_ships: number
  ships: ShipSnapshot[]
  opponent_shielded_ships: Array<Array<{ x: number; y: number }>>
  hand: Array<Record<string, unknown>>
  attacks: CellAttack[]
  opponent_attacks: CellAttack[]
  opponent_remaining_ships: number
  shenwei_holes: unknown[]
  chain: Record<string, unknown>
  chain_waiting: boolean
  chain_window: string | null
  priority_waiting: Record<string, unknown> | null
  shenji_waiting: Record<string, unknown> | null
  active_effects: string[]
  last_stand_lock: boolean
  last_stand_win: boolean
  effect_badges: { self: Array<Record<string, unknown>>; opponent: Array<Record<string, unknown>> }
  pending_placement: Record<string, unknown> | null
  pending_placement_blocked: Array<Record<string, unknown>>
  pending_placement_allowed: unknown[]
  last_stand_cells: Array<{ x: number; y: number }>
  last_stand_owner: string | null
  frozen_area: Record<string, unknown> | null
  magic_blocked: boolean
  effect_flags: Record<string, unknown>
  pending_sacrifice: Record<string, unknown> | null
  pending_sacrifice_ships: Array<Record<string, unknown>>
  rps_choices: Record<string, string>
  // Ticket #43 additive tail: the server-owned countdown and the waiting-seat
  // visibility. Optional on the wire (standalone game_state subsets may omit
  // them); the store defaults are the "hide the timer / no opponent" state.
  turn_deadline: number | null
  turn_timeout_seconds: number
  opponent_ready: boolean
  opponent_online: boolean
  // 服务端可信：对手席位是已登录账号（游客/AI/无对手均为 false）。
  opponent_registered: boolean
  // 重连恢复：整盘重布所需的布船数量与「本盘作废」；待选魔法项与骰子弃牌
  // 只对发起者本人有值（对手/观战为 null / false）。
  max_ships: number
  needs_reset: boolean
  reset_allowed_cells: Array<{ x: number; y: number }> | null
  interaction_waiting: string | null
  magic_temp: Record<string, unknown> | null
  dice_discard_pending: boolean
  // game_state-only payload keys (never part of room_sync).
  winner_card: Record<string, unknown> | null
  loser_cards: Array<Record<string, unknown> | null>
}

/** game_state sends these two on top of the room_sync fields. */
export const GAME_STATE_ONLY_FIELDS = ['winner_card', 'loser_cards'] as const
export type GameStateOnlyField = (typeof GAME_STATE_ONLY_FIELDS)[number]

type ContractField = RoomSyncField
type SchemaField = keyof GameState
type MissingContractField = Exclude<ContractField, SchemaField>
type UnexpectedExtraField = Exclude<SchemaField, ContractField | GameStateOnlyField>
// Compile-time parity guard: both sides must be `never` for this to type-check.
const parity: [MissingContractField, UnexpectedExtraField] extends [never, never] ? true : never = true
void parity

const FIELD_SPECS = {
  room_id: { type: 'string', nullable: false, default: '', note: '当前房间号；首页为空串' },
  state: { type: 'string', nullable: false, default: 'waiting', note: 'waiting/placing_ships/rock_paper_scissors/attacking/game_over' },
  current_phase: { type: 'string', nullable: true, default: null, note: 'preparation/battle/end' },
  current_attacker: { type: 'string', nullable: false, default: '', note: '服务端下发的 player_id，不是客户端 sid' },
  attacks_remaining: { type: 'number', nullable: false, default: 0, note: '本回合剩余攻击次数' },
  round: { type: 'number', nullable: false, default: 0, note: '大回合数' },
  attack_order: { type: 'array', nullable: false, default: [], note: '本大回合出手顺序（player_id）' },
  player_id: { type: 'string', nullable: false, default: '', note: '本座位 id；匹配房是入队 sid' },
  player_seat: { type: 'string', nullable: false, default: '', note: '座位标签 p1/p2 的展示文案' },
  player_name: { type: 'string', nullable: true, default: null, note: '自己的昵称' },
  opponent_name: { type: 'string', nullable: true, default: null, note: '对手昵称' },
  is_ai_room: { type: 'boolean', nullable: false, default: false, note: '人机房' },
  ranked: { type: 'boolean', nullable: false, default: false, note: '是否计排位分' },
  mode: { type: 'string', nullable: false, default: 'casual', note: 'ranked/casual/ai/custom' },
  winner: { type: 'string', nullable: false, default: '', note: '胜者 player_id；未结束为空串' },
  game_over_reason: { type: 'string', nullable: true, default: null, note: '结束原因文案' },
  field_magic: { type: 'string', nullable: false, default: '', note: '当前场地魔法名' },
  remaining_ships: { type: 'number', nullable: false, default: 0, note: '自己存活舰数' },
  ships: { type: 'array', nullable: false, default: [], note: '自己的舰位/冻结/护盾/存活' },
  opponent_shielded_ships: { type: 'array', nullable: false, default: [], note: '对手护盾舰的格子列表（不含未命中信息）' },
  hand: { type: 'array', nullable: false, default: [], note: '手牌卡面快照 name/speed/type/description' },
  attacks: { type: 'array', nullable: false, default: [], note: '自己已开火格 x/y/hit' },
  opponent_attacks: { type: 'array', nullable: false, default: [], note: '对手已开火格 x/y/hit' },
  opponent_remaining_ships: { type: 'number', nullable: false, default: 0, note: '对手存活舰数（公开信息）' },
  shenwei_holes: { type: 'array', nullable: false, default: [], note: '神威空洞格' },
  chain: { type: 'object', nullable: false, default: {}, note: '公开连锁栈（已按观众口径净化）' },
  chain_waiting: { type: 'boolean', nullable: false, default: false, note: '是否等待连锁响应' },
  chain_window: { type: 'string', nullable: true, default: null, note: '连锁窗口标识' },
  priority_waiting: { type: 'object', nullable: true, default: null, note: '等待阶段转换优先权询问' },
  shenji_waiting: { type: 'object', nullable: true, default: null, note: '等待对方神机妙算宣言' },
  active_effects: { type: 'array', nullable: false, default: [], note: '公开效果标记名（排序后）' },
  last_stand_lock: { type: 'boolean', nullable: false, default: false, note: '绝处逢生锁卡' },
  last_stand_win: { type: 'boolean', nullable: false, default: false, note: '绝处逢生击杀即胜' },
  effect_badges: { type: 'object', nullable: false, default: { self: [], opponent: [] }, note: '效果角标（含卡面文案）' },
  pending_placement: { type: 'object', nullable: true, default: null, note: '局内重摆待放置面板' },
  pending_placement_blocked: { type: 'array', nullable: false, default: [], note: '重摆禁用格' },
  pending_placement_allowed: { type: 'array', nullable: false, default: [], note: '重摆白名单格；空=无白名单' },
  last_stand_cells: { type: 'array', nullable: false, default: [], note: '绝处逢生区域格' },
  last_stand_owner: { type: 'string', nullable: true, default: null, note: '绝处逢生归属' },
  frozen_area: { type: 'object', nullable: true, default: null, note: '冻结区域' },
  magic_blocked: { type: 'boolean', nullable: false, default: false, note: '手牌被封' },
  effect_flags: { type: 'object', nullable: false, default: {}, note: '自己的效果标记原始表' },
  pending_sacrifice: { type: 'object', nullable: true, default: null, note: '待牺牲的展示信息' },
  pending_sacrifice_ships: { type: 'array', nullable: false, default: [], note: '待牺牲可选舰' },
  rps_choices: { type: 'object', nullable: false, default: {}, note: '猜拳已出拳的座位（仅猜拳阶段）' },
  turn_deadline: { type: 'number', nullable: true, default: null, note: '回合截止时间（epoch 毫秒）；null=没有计时中的回合计时' },
  turn_timeout_seconds: { type: 'number', nullable: false, default: 0, note: '服务端回合超时秒数（0=关闭）；客户端只渲染不裁决' },
  opponent_ready: { type: 'boolean', nullable: false, default: false, note: '对手是否已摆好战舰（布船/猜拳等待）' },
  opponent_online: { type: 'boolean', nullable: false, default: false, note: '对手是否在线（布船/猜拳等待）' },
  opponent_registered: { type: 'boolean', nullable: false, default: false, note: '对手是否为已登录账号（服务端可信；缺省=false，游客/AI/无对手都不查公开资料）' },
  max_ships: { type: 'number', nullable: false, default: 6, note: '本盘允许的布船数量（灵气复苏/败者食尘会改）' },
  needs_reset: { type: 'boolean', nullable: false, default: false, note: '本方棋盘已作废、需要按 max_ships 重布' },
  reset_allowed_cells: { type: 'array', nullable: true, default: null, note: '整盘重布允许格；null 不限制，空数组表示没有合法格' },
  interaction_waiting: { type: 'string', nullable: true, default: null, note: '服务端当前未完成互动的等待提示，不含私有目标' },
  magic_temp: { type: 'object', nullable: true, default: null, note: '只回给发起者的待选魔法项；对手/观战为 null' },
  dice_discard_pending: { type: 'boolean', nullable: false, default: false, note: '自己是否正被要求弃牌（命运骰子）' },
  winner_card: { type: 'object', nullable: true, default: null, note: '猜拳胜者抽到的卡' },
  loser_cards: { type: 'array', nullable: false, default: [], note: '猜拳败者抽到的卡' },
} as const satisfies Record<SchemaField, GameStateFieldSpec>

export const GAME_STATE_SCHEMA = {
  $id: 'https://battleship.local/schemas/game-state.json',
  title: 'gameState',
  source: 'battleship.contracts.events_out.RoomSync',
  type: 'object',
  additionalProperties: true,
  required: [...ROOM_SYNC_FIELDS, ...GAME_STATE_ONLY_FIELDS],
  fields: FIELD_SPECS,
} as const

export type GameStateSchema = typeof GAME_STATE_SCHEMA

function cloneDefault(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(cloneDefault)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, cloneDefault(item)]))
  }
  return value
}

/** Build a fresh state object from the schema defaults (never shared refs). */
export function defaultGameState(): GameState {
  const state = {} as Record<string, unknown>
  for (const key of GAME_STATE_SCHEMA.required) {
    state[key] = cloneDefault(FIELD_SPECS[key].default)
  }
  return state as unknown as GameState
}

export function isKnownGameStateField(key: string): key is SchemaField {
  return Object.prototype.hasOwnProperty.call(FIELD_SPECS, key)
}
