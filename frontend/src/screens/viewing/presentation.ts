/** 共用实战演出时长与卡面；观看端只展示录像已给出的结果。 */
import { CHAIN_ENTRY_MS, CHAIN_SUCCESS_MS, CHAIN_RESOLVE_MS, CHAIN_SINGLE_RESOLVE_MS, type ChainFrame } from '../game/chainAnimation'
import { cardSound } from '../../audio/cardSounds'
import type { Json } from './types'

export function presentationDuration(cue: Json): number {
  if (cue.stage === 'attack_windup') return 220
  if (cue.stage === 'attack_tail') return 380
  if (cue.stage === 'join') return CHAIN_ENTRY_MS
  if (cue.stage === 'chain_success') return CHAIN_SUCCESS_MS
  if (cue.stage === 'card' || cue.stage === 'card_face') return Array.isArray(cue.chain) && cue.chain.length > 1 ? CHAIN_RESOLVE_MS : CHAIN_SINGLE_RESOLVE_MS
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
  const source = Array.isArray(cue.chain) ? cue.chain as Json[] : []
  const cards = source.map((row, i) => ({ name: typeof row.card === 'string' ? row.card : String((row.card as Json)?.name ?? ''), caster: String(row.seat ?? ''), order: i + 1, id: '' }))
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
