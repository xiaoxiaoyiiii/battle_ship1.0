import type { ReplayPayload } from '../replay/model'
import { frameAt, object, sides } from './frame'
import type { Json, Recording } from './types'

/** 只用旧录像明确记录的坐标、阵营、结果及连锁快照恢复基础演出。 */
export function legacyPresentation(recording: Recording, index: number): { before: Json[]; after: Json[] } {
  const step = recording.steps[index], detail = step.detail ?? {}, legacy = recording.legacy as ReplayPayload
  const previous = frameAt(recording, index - 1), next = frameAt(recording, index)
  if (step.kind === 'attack' && object(detail.target)) {
    const { x, y } = detail.target
    const row = legacy.attacks.find(row => row.step === step.i)
    const attacker = sides.find(side => Array.isArray(row?.[side]) && (row![side] as Json[]).some(p => p.x === x && p.y === y))
    if (attacker && Number.isInteger(x) && Number.isInteger(y)) {
      const cue = { attacker, target: attacker === 'p1' ? 'p2' : 'p1', cell: { x, y },
        result: { hit: detail.hit === true, sunk: detail.ship_sunk === true, shield_blocked: detail.shield_blocked === true, invincible: detail.invincible === true } }
      return { before: [{ ...cue, stage: 'attack_windup' }], after: [{ ...cue, stage: 'attack_tail' }] }
    }
  }
  const stack = previous.chain.chain as Json[], incoming = next.chain.chain as Json[]
  if (step.kind === 'magic' && detail.played === true && incoming.length) return { before: [], after: [{ stage: 'join', chain: incoming }] }
  if (step.kind === 'magic' && typeof detail.card === 'string' && stack.length && incoming.length < stack.length) {
    let full = stack
    for (let k = index - 2; k >= 0; k--) {
      const candidate = frameAt(recording, k).chain.chain as Json[]
      if (!candidate.length) break
      if (candidate.length > full.length) full = candidate
    }
    const current = stack.at(-1)!
    if (current.card === detail.card) {
      return { before: [{ stage: 'card', card: detail.card, chain: full, order: stack.length,
        first: stack.length === full.length, negated_skip: current.negated === true }],
        after: current.negated === true ? [] : [{ stage: 'legacy_result', card: detail.card }] }
    }
  }
  return { before: [], after: [] }
}
