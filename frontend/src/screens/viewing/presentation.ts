/** 共用实战演出时长与卡面；观看端只展示录像已给出的结果。 */
import { CHAIN_ENTRY_MS, CHAIN_SUCCESS_MS, CHAIN_RESOLVE_MS, CHAIN_SINGLE_RESOLVE_MS, parseStack, type ChainFrame } from '../game/chainAnimation'
import { cardSound } from '../../audio/cardSounds'
import { commanderSkillVisual } from '../../components/commander/commanderSkillVisuals'
import { object } from './frame'
import type { Json, Point, Side } from './types'

const commanderDurations = { chain_enter: 580, resolve: 820, negated: 620, reveal: 920 }
type CommanderStage = keyof typeof commanderDurations

function commanderStage(value: unknown): CommanderStage | null {
  return typeof value === 'string' && Object.hasOwn(commanderDurations, value) ? value as CommanderStage : null
}

function boardPoint(value: unknown): value is Point {
  return object(value) && typeof value.x === 'number' && typeof value.y === 'number' &&
    Number.isInteger(value.x) && Number.isInteger(value.y) && value.x >= 0 && value.x < 6 && value.y >= 0 && value.y < 6
}

export function commanderPresentation(cue: Json | null) {
  if (cue?.stage !== 'commander_skill' || (cue.seat !== 'p1' && cue.seat !== 'p2')) return null
  const stage = commanderStage(cue.skill_stage)
  const skill = commanderSkillVisual(cue.skill_id)
  if (!stage || !skill || cue.commander_id !== skill.commanderId) return null
  const seat: Side = cue.seat
  const opponent: Side = seat === 'p1' ? 'p2' : 'p1'
  const reveal = skill.id === 'delayed_lock' && stage === 'reveal' && cue.target === opponent
  const sacrifice = skill.id === 'sacrifice_gambit' && stage === 'chain_enter' && cue.target === seat
  // 青瞳只使用正式揭晓后的公开坐标。
  const cells = (reveal || sacrifice) && Array.isArray(cue.cells) ? cue.cells.filter(boardPoint) : []
  const board = reveal && cells.length ? opponent : seat
  const failed = cue.success === false && stage === 'resolve'
  const negatedBy = typeof cue.negated_by === 'string' ? cue.negated_by : ''
  const detail = stage === 'negated' ? (negatedBy ? `被${negatedBy}无效` : '已无效')
    : stage === 'chain_enter' ? '入链'
    : stage === 'reveal' ? '锁定揭晓'
    : failed ? '未生效'
    : skill.id === 'delayed_lock' ? '待揭晓'
    : skill.id === 'sacrifice_gambit' && Number.isInteger(cue.draw_count) ? `抽取 ${cue.draw_count} 张牌`
    : '已生效'
  return { skill, stage, seat, board, cells, failed, detail }
}

export function presentationDuration(cue: Json): number {
  if (cue.stage === 'attack_windup') return 220
  if (cue.stage === 'attack_tail') return 380
  if (cue.stage === 'join') return CHAIN_ENTRY_MS
  if (cue.stage === 'chain_success') return CHAIN_SUCCESS_MS
  if (cue.stage === 'card' || cue.stage === 'card_face') return Array.isArray(cue.chain) && cue.chain.length > 1 ? CHAIN_RESOLVE_MS : CHAIN_SINGLE_RESOLVE_MS
  if (cue.stage === 'commander_skill') {
    const stage = commanderStage(cue.skill_stage)
    return stage ? commanderDurations[stage] : 0
  }
  const effect = cue.effect as Json | undefined
  const total = Number(effect?.duration_ms) || 1250, impact = Number(effect?.impact) || .45
  if (cue.stage === 'effect_windup') return total * impact
  if (cue.stage === 'effect_tail') return total * (1 - impact)
  return 350
}

export function presentationCues(cue: Json): Json[] {
  if (['card', 'card_face'].includes(String(cue.stage)) && cue.first === true && Array.isArray(cue.chain) && cue.chain.length > 1) {
    return [{ ...cue, stage: 'chain_success' }, { ...cue, first: false }]
  }
  return [cue]
}

export function chainFrame(cue: Json, progress: number): ChainFrame | null {
  if (!['join', 'chain_success', 'card', 'card_face'].includes(String(cue.stage))) return null
  const cards = parseStack(cue)
  if (!cards.length) return null
  return { progress, cue: { kind: cue.stage === 'join' ? 'join' : cue.stage === 'chain_success' ? 'success' : 'resolve', cards,
    order: Number(cue.order) || cards.length, start: 0, duration: presentationDuration(cue),
    result: { negated: cue.negated_skip === true, failed: cue.success === false, negatedBy: String(cue.negated_by ?? '') } } }
}

export function cueSounds(cue: Json): string[] {
  if (cue.stage === 'join') return ['play_card']
  if (cue.stage === 'chain_success') return ['chain']
  if (cue.stage === 'attack_tail') {
    const result = cue.result as Json | undefined
    return [result?.shield_blocked || result?.invincible ? 'holy_shield' : result?.sunk ? 'sunk' : result?.hit ? 'hit' : 'miss']
  }
  if (cue.stage === 'card' && cue.negated_skip === true) return [cue.negated_by === '加百列之光' ? 'gabriel' : 'negate']
  // 旧录像只有结算卡名和栈，不补造牌效落点；仍可播放该卡已有的音效。
  const card = cue.stage === 'legacy_result' ? cue.card : cue.stage === 'effect_tail' && cue.success !== false ? (cue.effect as Json)?.card : null
  const sound = typeof card === 'string' ? cardSound(card) : null
  return sound ? [sound] : []
}
