/**
 * Pure view helpers for the rock-paper-scissors screen (ticket #23).
 *
 * They only format the server result (status / winner / choices). No RPS rule
 * is recomputed here: the winner is whatever rps_result says.
 */

export type RpsRecord = Record<string, unknown>

export interface RpsResultView {
  tie: boolean
  verdict: string
  self: string
  opponent: string
  /** A tie payload carries no choices (RpsOutcome defaults to {}), so there is nothing to reveal. */
  hasChoices: boolean
}

const CHOICE_NAMES: Record<string, string> = {
  rock: '石头',
  paper: '布',
  scissors: '剪刀',
}

export function choiceName(choice: string): string {
  if (!choice) return '—'
  return CHOICE_NAMES[choice] || choice
}

function readString(source: RpsRecord | null | undefined, key: string): string {
  if (!source) return ''
  const value = source[key]
  return typeof value === 'string' ? value : ''
}

function readChoiceMap(source: RpsRecord | null | undefined): RpsRecord {
  if (!source) return {}
  const value = source.choices
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as RpsRecord) : {}
}

export function rpsResultView(
  result: RpsRecord | null,
  playerId: string,
): RpsResultView | null {
  if (!result) return null
  const choices = readChoiceMap(result)
  const selfChoice = playerId ? readString(choices, playerId) : ''
  const opponentId = Object.keys(choices).find((key) => key !== playerId) || ''
  const opponentChoice = opponentId ? readString(choices, opponentId) : ''
  const self = choiceName(selfChoice)
  const opponent = choiceName(opponentChoice)
  const hasChoices = Boolean(selfChoice || opponentChoice)
  const status = readString(result, 'status')

  if (status === 'tie') {
    // The legacy screen dedupes the server's own "平局" prefix
    // (static/game.js:7955-7961): the title already says it.
    const detail = readString(result, 'message')
    const verdict = '平局，请重新选择一种手势' +
      (detail && detail.indexOf('平局') === -1 ? '：' + detail : '')
    return { tie: true, verdict, self, opponent, hasChoices }
  }

  const winner = readString(result, 'winner')
  if (status !== 'win' || !playerId || !winner) {
    return { tie: false, verdict: '猜拳结果已出，等待服务器推进对局。', self, opponent, hasChoices }
  }
  return {
    tie: false,
    verdict: winner === playerId ? '你获胜，先攻击！' : '对手获胜，先攻击！',
    self,
    opponent,
    hasChoices,
  }
}
