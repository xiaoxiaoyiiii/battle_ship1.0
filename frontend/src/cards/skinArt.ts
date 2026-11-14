/**
 * Resolve a card face, preferring a owned skin when the Codex manifest has art.
 * The manifest file is owned by Codex and may be absent; never statically import it.
 */
import { cardArtUrl } from './cardArt'
import {
  lookupManifestUrl,
  normalizeSkinId,
  resolveCardArtUrl as resolveWithLookups,
} from '../../scripts/gacha-map.mjs'

// Precise glob so a missing Codex file yields an empty record instead of a build error.
const MANIFEST_MODULES = import.meta.glob('./skins/skinManifest.ts', { eager: true })

function manifestModule(): unknown {
  const modules = Object.values(MANIFEST_MODULES)
  return modules.length ? modules[0] : null
}

export { normalizeSkinId }

/** Skin image if `skinId` is present and the manifest has a usable url; otherwise the default face. */
export function resolveCardArtUrl(cardName: string, skinId?: string | null): string | null {
  return resolveWithLookups(cardName, skinId, {
    defaultUrl: cardArtUrl,
    manifest: manifestModule(),
  })
}

/** Direct manifest url lookup (empty / unknown → null). */
export function skinArtUrl(skinId?: string | null): string | null {
  const id = normalizeSkinId(skinId)
  if (!id) return null
  return lookupManifestUrl(manifestModule(), id)
}
