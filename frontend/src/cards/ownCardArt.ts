/** Own-hand / own-card art uses the player's selected_skin from /api/collection. */
import { useCollectionStore } from '../stores/collection'
import { normalizeSkinId, resolveCardArtUrl, skinEffectClass } from './skinArt'

export function ownSkinId(cardName: string): string | null {
  const selected = useCollectionStore().data?.cards.find((card) => card.name === cardName)?.selected_skin
  return normalizeSkinId(selected)
}

export function ownCardArtUrl(cardName: string): string | null {
  return resolveCardArtUrl(cardName, ownSkinId(cardName))
}

export function ownSkinEffectClass(cardName: string): string {
  return skinEffectClass(cardName, ownSkinId(cardName))
}
