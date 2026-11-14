/**
 * Thin typed wrapper around the shared ESM mapper in scripts/gacha-map.mjs.
 * The check-gacha script imports the same module so there is one source of truth.
 */
import * as map from '../../scripts/gacha-map.mjs'
import type {
  GachaExchangeResult,
  GachaPool,
  GachaPoolSkin,
  GachaProgress,
  GachaPull,
  GachaPullResult,
  GachaRateLine,
} from './gachaTypes'

export {
  REQUEST_ID_PATTERN,
  DEFAULT_PRICES,
  DEFAULT_RATES,
  DEFAULT_EXCHANGE_COST,
  DEFAULT_DUPLICATE_SHARDS,
  DEFAULT_SHARD_PER_DRAW,
  GACHA_ERROR_MESSAGES,
  isValidRequestId,
  createRequestId,
  normalizeSkinId,
  pickEntryUrl,
  lookupManifestUrl,
  readApiError,
  gachaErrorMessage,
} from '../../scripts/gacha-map.mjs'

export type {
  GachaKind,
  GachaTier,
  GachaStatus,
  GachaPull,
  GachaProgress,
  GachaPullSummary,
  GachaPullResult,
  GachaRateLine,
  GachaPoolSkin,
  GachaPool,
  GachaExchangeResult,
  GachaActionResult,
} from './gachaTypes'

export function resolveCardArtUrlWithLookups(
  cardName: string,
  skinId: unknown,
  options?: {
    defaultUrl?: ((name: string) => string | null) | string | null
    manifest?: unknown
  },
): string | null {
  return map.resolveCardArtUrl(cardName, skinId, options)
}

export function mapGachaPull(row: unknown): GachaPull {
  return map.mapGachaPull(row) as GachaPull
}

export function mapProgress(value: unknown): GachaProgress {
  return map.mapProgress(value) as GachaProgress
}

export function mapPoolSkin(row: unknown): GachaPoolSkin {
  return map.mapPoolSkin(row) as GachaPoolSkin
}

export function mapRatesDisplay(value: unknown): GachaRateLine[] {
  return map.mapRatesDisplay(value) as GachaRateLine[]
}

export function mapGachaPullResult(body: unknown): GachaPullResult {
  return map.mapGachaPullResult(body) as GachaPullResult
}

export function mapGachaPool(body: unknown): GachaPool {
  return map.mapGachaPool(body) as GachaPool
}

export function mapExchangeResult(body: unknown): GachaExchangeResult {
  return map.mapExchangeResult(body) as GachaExchangeResult
}

export function applyPullToPool(pool: GachaPool | null, result: GachaPullResult): GachaPool | null {
  return map.applyPullToPool(pool, result) as GachaPool | null
}

export function applyExchangeToPool(
  pool: GachaPool | null,
  exchanged: GachaPoolSkin | null,
  shards: number,
  progress: GachaProgress | null | undefined,
  balance?: number,
): GachaPool | null {
  return map.applyExchangeToPool(pool, exchanged, shards, progress, balance) as GachaPool | null
}
