/** 观看帧按棋盘所有者编号；展示端不重新计算规则。 */
export type Side = 'p1' | 'p2'
export type Json = Record<string, unknown>
export interface Point { x: number; y: number }
export interface Shot extends Point { hit?: boolean; sunk?: boolean; area?: boolean; fog_miss?: boolean }
export interface FleetCell extends Shot { shielded?: boolean; frozen?: boolean; invincible?: boolean; trap?: boolean }
export interface Area { x1: number; y1: number; x2: number; y2: number }
export interface ViewCard { name: string; speed?: number; type?: string; description?: string }
export interface ViewPlayer { name: string; remaining_ships: number; hand_count: number; cards: ViewCard[] | null; effects: Json[] }
export interface ViewBoard { fleet: FleetCell[]; marks: Shot[]; shots: Shot[]; reveals: Point[]; holes: Area[]; frozen_area: Area | null; last_stand: Point[] }
export interface ViewFrame {
  version: 2; audience: 'replay' | 'spectator'
  context: Json; rules: Json; players: Record<Side, ViewPlayer>; boards: Record<Side, ViewBoard>; chain: Json
}
export interface ViewPacket { version: 2; room_id: string; seq: number; frame: ViewFrame; cues: Json[]; baseline?: boolean }
export interface ViewEvent { seq: number; step: number; type: 'state' | 'presentation'; patch?: Partial<ViewFrame>; cue?: Json }
export interface RecordingStep { i: number; kind: string; actor?: string | null; text: string; detail?: Json }
export interface Recording {
  version: number; steps: RecordingStep[]; initial: ViewFrame; events: ViewEvent[]
  checkpoints: Array<{ seq: number; step: number; frame: ViewFrame }>
  nodes: Array<{ step: number; kind: string; label: string }>; truncated: string; legacy?: unknown
}
