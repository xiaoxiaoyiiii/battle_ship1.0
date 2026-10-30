import rawCards from './card_data.json'

/**
 * The frozen card table, copied from the backend at build time.
 *
 * Source of truth: backend/src/battleship/domain/magic/data/magic_card.json
 * (the same file the server loads). scripts/sync-card-data.mjs regenerates
 * card_data.json before every build and validates the frozen 50/48 counts; the
 * generated file is committed so a fresh checkout can typecheck.
 *
 * The collection overlay groups by speed/type and renders the real card faces
 * through cardArt.ts, exactly like the in-game hand.
 */
export interface CardInfo {
  name: string
  speed: number
  type: string
  description: string
}

export const CARDS: readonly CardInfo[] = (rawCards as CardInfo[]).slice()

export const CARD_SPEEDS: readonly number[] = [1, 2, 3]
export const CARD_TYPES: readonly string[] = ['普通', '场地', '判定']

export const CARD_COUNT = CARDS.length
export const UNIQUE_CARD_NAMES: readonly string[] = Array.from(new Set(CARDS.map((card) => card.name)))

/** Rows grouped by speed, in speed order; a missing speed is an empty group. */
export function cardsBySpeed(): Array<{ speed: number; label: string; cards: CardInfo[] }> {
  return CARD_SPEEDS.map((speed) => ({
    speed,
    label: '速阶 ' + speed,
    cards: CARDS.filter((card) => card.speed === speed),
  }))
}

/** Rows grouped by card type, in the frozen type order. */
export function cardsByType(): Array<{ type: string; cards: CardInfo[] }> {
  const order = CARD_TYPES.slice()
  for (const card of CARDS) {
    if (!order.includes(card.type)) order.push(card.type)
  }
  return order.map((type) => ({
    type,
    cards: CARDS.filter((card) => card.type === type),
  }))
}
