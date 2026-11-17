/** 神秘科技大乱斗前端类型，字段与 CONTRACT-codex.md 对齐。 */

export type MysteryTechTier = 'quality' | 'legendary' | 'mythic'
export type MysteryTechTiming = 'instant' | 'persistent'
export type MysteryTechStage =
  | 'idle'
  | 'selecting'
  | 'locked'
  | 'resolving'
  | 'targeting'
  | 'effect_waiting'
  | 'ended'

export type MysteryTechTargetKind = 'revive' | 'fleet_rebirth' | 'sonar_pulse'

export interface MysteryTechInfo {
  id: string
  name: string
  tier: MysteryTechTier
  timing: MysteryTechTiming
  description: string
}

export interface MysteryTechOption {
  tech_id: string
  refresh_used: boolean
  technology: MysteryTechInfo
}

export interface MysteryTechSelected {
  player_id: string
  seat: string
  tech_id: string
  round: number
  technology: MysteryTechInfo
}

export interface MysteryTechCell {
  x: number
  y: number
}

export interface MysteryTechTargetShip {
  ship_index: number
  positions: MysteryTechCell[]
}

export interface MysteryTechTarget {
  request_id: string
  player_id: string
  tech_id: string
  kind: MysteryTechTargetKind
  deadline: number | null
  remaining: number
  legal_cells: MysteryTechCell[]
  ship_indices: number[]
  ships: MysteryTechTargetShip[]
}

export interface MysteryTechState {
  room_id?: string
  enabled: boolean
  stage: MysteryTechStage
  selection_round: number
  deadline: number | null
  remaining_ms: number
  options: MysteryTechOption[]
  locked_tech_id: string | null
  target: MysteryTechTarget | null
  selected: MysteryTechSelected[]
  locked_players: string[]
  resolving_player: string | null
  pending_extra_attacks: Record<string, number>
}

export const EMPTY_MYSTERY_TECH_STATE: MysteryTechState = {
  enabled: false,
  stage: 'idle',
  selection_round: 0,
  deadline: null,
  remaining_ms: 0,
  options: [],
  locked_tech_id: null,
  target: null,
  selected: [],
  locked_players: [],
  resolving_player: null,
  pending_extra_attacks: {},
}
