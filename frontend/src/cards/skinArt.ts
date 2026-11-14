/**
 * Resolve a card face from the Codex skin manifest, falling back to the default art.
 */
import { cardArtUrl } from './cardArt'
import { normalizeSkinId } from '../../scripts/gacha-map.mjs'
import {
  getSkin,
  skinArtForCard as manifestArtForCard,
  skinArtUrl as manifestArtUrl,
} from './skins/skinManifest'
import './skins/skin-effects.css'

export { normalizeSkinId }
export { getSkin } from './skins/skinManifest'

/** Skin image if it matches this card; otherwise the default face. */
export function resolveCardArtUrl(cardName: string, skinId?: string | null): string | null {
  return manifestArtForCard(cardName, normalizeSkinId(skinId)) ?? cardArtUrl(cardName)
}

/** Direct manifest url lookup (missing / default / unknown → null). */
export function skinArtUrl(skinId?: string | null): string | null {
  return manifestArtUrl(normalizeSkinId(skinId))
}

/**
 * Neon edge classes when the skin matches this card; otherwise empty.
 * Put this on the art container, never on a face-down opponent hand.
 */
export function skinEffectClass(cardName: string, skinId?: string | null): string {
  const entry = getSkin(normalizeSkinId(skinId))
  return entry && entry.cardName === cardName ? entry.effectClass : ''
}
