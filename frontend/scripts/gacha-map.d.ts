export const REQUEST_ID_PATTERN: RegExp
export const DEFAULT_PRICES: { single: number; ten: number }
export const DEFAULT_RATES: { limited: number; legendary: number; shard: number }
export const DEFAULT_EXCHANGE_COST: { legendary: number; limited: number }
export const DEFAULT_DUPLICATE_SHARDS: number
export const DEFAULT_SHARD_PER_DRAW: number
export const GACHA_ERROR_MESSAGES: Record<string, string>
export function isValidRequestId(value: unknown): boolean
export function createRequestId(): string
export function normalizeSkinId(value: unknown): string | null
export function pickEntryUrl(entry: unknown): string | null
export function lookupManifestUrl(manifest: unknown, skinId: unknown): string | null
export function resolveCardArtUrl(
  cardName: string,
  skinId: unknown,
  options?: {
    defaultUrl?: ((name: string) => string | null) | string | null
    manifest?: unknown
  },
): string | null
export function readApiError(body: unknown): { code: string; message: string; field: string | null }
export function gachaErrorMessage(body: unknown, fallback?: string): string
export function mapGachaPull(row: unknown): import('../src/stores/gachaTypes').GachaPull
export function mapProgress(value: unknown): import('../src/stores/gachaTypes').GachaProgress
export function mapPoolSkin(row: unknown): import('../src/stores/gachaTypes').GachaPoolSkin
export function mapRatesDisplay(value: unknown): import('../src/stores/gachaTypes').GachaRateLine[]
export function mapGachaPullResult(body: unknown): import('../src/stores/gachaTypes').GachaPullResult
export function mapGachaPool(body: unknown): import('../src/stores/gachaTypes').GachaPool
export function mapExchangeResult(body: unknown): import('../src/stores/gachaTypes').GachaExchangeResult
export function applyPullToPool(
  pool: import('../src/stores/gachaTypes').GachaPool | null,
  result: import('../src/stores/gachaTypes').GachaPullResult,
): import('../src/stores/gachaTypes').GachaPool | null
export function applyExchangeToPool(
  pool: import('../src/stores/gachaTypes').GachaPool | null,
  exchanged: import('../src/stores/gachaTypes').GachaPoolSkin | null,
  shards: number,
  progress: import('../src/stores/gachaTypes').GachaProgress | null | undefined,
  balance?: number,
): import('../src/stores/gachaTypes').GachaPool | null
