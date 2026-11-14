/** Pure gacha mappers and helpers (snake_case wire → camelCase). No I/O. */

export const REQUEST_ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/

export const DEFAULT_PRICES = { single: 80, ten: 800 }
export const DEFAULT_RATES = { limited: 0.01, legendary: 0.09, shard: 0.90 }
export const DEFAULT_EXCHANGE_COST = { legendary: 20, limited: 60 }
export const DEFAULT_DUPLICATE_SHARDS = 5
export const DEFAULT_SHARD_PER_DRAW = 1

export const GACHA_ERROR_MESSAGES = {
  unauthorized: '请先登录后再抽卡',
  invalid_payload: '请求格式不正确',
  invalid_count: '抽卡次数无效',
  invalid_request_id: '请求无效，请重试',
  unknown_skin: '未知皮肤',
  unknown_card: '未知卡牌',
  skin_card_mismatch: '这张皮肤不属于该卡',
  insufficient_tide_ash: '潮汐徽记不足',
  insufficient_shards: '碎片不足',
  skin_already_owned: '已经拥有这张皮肤',
  skin_not_owned: '尚未拥有这张皮肤',
  request_id_conflict: '请求冲突，请重试',
}

export function isValidRequestId(value) {
  return typeof value === 'string' && REQUEST_ID_PATTERN.test(value)
}

export function createRequestId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'
  let id = ''
  for (let i = 0; i < 32; i += 1) id += alphabet[Math.floor(Math.random() * alphabet.length)]
  return id
}

export function normalizeSkinId(value) {
  if (value == null) return null
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed || trimmed.toLowerCase() === 'default') return null
  return trimmed
}

function isObject(value) {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function asString(value, fallback = '') {
  return typeof value === 'string' ? value : fallback
}

function asNumber(value, fallback = 0) {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : fallback
}

function asBool(value) {
  return value === true || value === 1
}

export function pickEntryUrl(entry) {
  if (entry == null) return null
  if (typeof entry === 'string') {
    const text = entry.trim()
    return text || null
  }
  if (!isObject(entry)) return null
  for (const key of ['url', 'src', 'image', 'artUrl', 'href']) {
    const value = entry[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (value && typeof value === 'object') {
      if (typeof value.default === 'string' && value.default.trim()) return value.default.trim()
      if (typeof value.url === 'string' && value.url.trim()) return value.url.trim()
    }
  }
  return null
}

export function lookupManifestUrl(manifest, skinId) {
  const id = normalizeSkinId(skinId)
  if (!id || manifest == null || typeof manifest !== 'object') return null
  const seen = new Set()
  const queue = [manifest]
  while (queue.length) {
    const current = queue.shift()
    if (!current || typeof current !== 'object' || seen.has(current)) continue
    seen.add(current)
    if (Object.prototype.hasOwnProperty.call(current, id)) {
      const url = pickEntryUrl(current[id])
      if (url) return url
    }
    for (const value of Object.values(current)) {
      if (value && typeof value === 'object') queue.push(value)
    }
  }
  return null
}

/**
 * Resolve card art, falling back to the default face when skinId is missing,
 * "default", unknown, or the manifest has no usable url.
 *
 * @param {string} cardName
 * @param {unknown} skinId
 * @param {{ defaultUrl?: ((name: string) => string | null) | string | null, manifest?: unknown }} [options]
 */
export function resolveCardArtUrl(cardName, skinId, options = {}) {
  const lookup = options.defaultUrl
  const fallback = typeof lookup === 'function' ? lookup(cardName) : (lookup ?? null)
  const id = normalizeSkinId(skinId)
  if (!id) return fallback ?? null
  const url = lookupManifestUrl(options.manifest, id)
  return url || fallback || null
}

export function readApiError(body) {
  const root = isObject(body) ? body : null
  const err = root && isObject(root.error) ? root.error : null
  const code = asString(err?.code || (typeof root?.code === 'string' ? root.code : ''))
  const message = asString(err?.message)
  const field = asString(err?.field) || null
  return { code, message, field }
}

export function gachaErrorMessage(body, fallback = '操作没有完成，请稍后再试') {
  const { code, message } = readApiError(body)
  if (message) return message
  if (code && GACHA_ERROR_MESSAGES[code]) return GACHA_ERROR_MESSAGES[code]
  return fallback
}

const KINDS = new Set(['shard', 'legendary', 'limited'])

export function mapGachaPull(row) {
  const item = isObject(row) ? row : {}
  const kind = KINDS.has(item.kind) ? item.kind : 'shard'
  const skinRaw = item.skin_id
  const keyRaw = item.card_key
  const nameRaw = item.card_name
  return {
    index: asNumber(item.index, 0),
    kind,
    skinId: skinRaw == null || skinRaw === '' ? null : asString(skinRaw) || null,
    cardKey: keyRaw == null || keyRaw === '' ? null : asString(keyRaw) || null,
    cardName: nameRaw == null || nameRaw === '' ? null : asString(nameRaw) || null,
    isNew: asBool(item.is_new),
    shardsGained: asNumber(item.shards_gained, 0),
  }
}

export function mapProgress(value) {
  const row = isObject(value) ? value : {}
  const owned = asNumber(row.owned, 0)
  const total = asNumber(row.total, 12)
  return {
    owned,
    total: total || 12,
    complete: row.complete === true || (total > 0 && owned >= total),
  }
}

export function mapPoolSkin(row) {
  const item = isObject(row) ? row : {}
  return {
    skinId: asString(item.skin_id),
    cardKey: asString(item.card_key),
    cardName: asString(item.card_name),
    tier: item.tier === 'limited' ? 'limited' : 'legendary',
    owned: asBool(item.owned),
  }
}

export function mapRatesDisplay(value) {
  if (!Array.isArray(value)) return []
  return value.map((row) => {
    const item = isObject(row) ? row : {}
    return {
      kind: asString(item.kind),
      label: asString(item.label),
      percent: asString(item.percent),
      note: asString(item.note),
    }
  }).filter((row) => row.kind || row.label || row.percent)
}

export function mapGachaPullResult(body) {
  const row = isObject(body) ? body : {}
  const count = asNumber(row.count, 0) === 10 ? 10 : 1
  const results = Array.isArray(row.results) ? row.results.map(mapGachaPull) : []
  const summaryRow = isObject(row.summary) ? row.summary : null
  const rawProgress = row.progress
  return {
    requestId: asString(row.request_id),
    replayed: asBool(row.replayed),
    count,
    cost: asNumber(row.cost, count === 10 ? DEFAULT_PRICES.ten : DEFAULT_PRICES.single),
    currency: asString(row.currency, 'tide_ash'),
    results,
    summary: summaryRow ? {
      newSkins: Array.isArray(summaryRow.new_skins) ? summaryRow.new_skins.filter((id) => typeof id === 'string') : [],
      duplicates: asNumber(summaryRow.duplicates, 0),
      shardsGained: asNumber(summaryRow.shards_gained, 0),
    } : {
      newSkins: results.filter((item) => item.isNew && item.skinId).map((item) => item.skinId),
      duplicates: results.filter((item) => item.kind !== 'shard' && !item.isNew).length,
      shardsGained: results.reduce((sum, item) => sum + item.shardsGained, 0),
    },
    balance: asNumber(row.balance, 0),
    shards: asNumber(row.shards, 0),
    progress: rawProgress != null ? mapProgress(rawProgress) : null,
  }
}

export function mapGachaPool(body) {
  const row = isObject(body) ? body : {}
  const prices = isObject(row.prices) ? row.prices : {}
  const rates = isObject(row.rates) ? row.rates : {}
  const exchange = isObject(row.exchange_cost) ? row.exchange_cost : {}
  const skins = Array.isArray(row.skins) ? row.skins.map(mapPoolSkin).filter((skin) => skin.skinId) : []
  return {
    ok: row.ok !== false,
    poolId: asString(row.pool_id, 'neon-v1'),
    currency: asString(row.currency, 'tide_ash'),
    balance: asNumber(row.balance, 0),
    shards: asNumber(row.shards, 0),
    prices: {
      single: asNumber(prices.single, DEFAULT_PRICES.single),
      ten: asNumber(prices.ten, DEFAULT_PRICES.ten),
    },
    rates: {
      limited: asNumber(rates.limited, DEFAULT_RATES.limited),
      legendary: asNumber(rates.legendary, DEFAULT_RATES.legendary),
      shard: asNumber(rates.shard, DEFAULT_RATES.shard),
    },
    ratesDisplay: mapRatesDisplay(row.rates_display),
    duplicateShards: asNumber(row.duplicate_shards, DEFAULT_DUPLICATE_SHARDS),
    shardPerDraw: asNumber(row.shard_per_draw, DEFAULT_SHARD_PER_DRAW),
    exchangeCost: {
      legendary: asNumber(exchange.legendary, DEFAULT_EXCHANGE_COST.legendary),
      limited: asNumber(exchange.limited, DEFAULT_EXCHANGE_COST.limited),
    },
    pity: row.pity == null ? null : row.pity,
    skins,
    progress: mapProgress(row.progress),
  }
}

export function mapExchangeResult(body) {
  const row = isObject(body) ? body : {}
  return {
    skin: row.skin ? mapPoolSkin(row.skin) : null,
    cost: asNumber(row.cost, 0),
    shards: asNumber(row.shards, 0),
    balance: asNumber(row.balance, 0),
    progress: mapProgress(row.progress),
  }
}

export function applyPullToPool(pool, result) {
  if (!pool || !result) return pool
  const gained = new Set(
    (result.results || []).filter((item) => item.isNew && item.skinId).map((item) => item.skinId),
  )
  return {
    ...pool,
    balance: result.balance,
    shards: result.shards,
    progress: result.progress || pool.progress,
    skins: (pool.skins || []).map((skin) => (
      gained.has(skin.skinId) ? { ...skin, owned: true } : skin
    )),
  }
}

export function applyExchangeToPool(pool, exchanged, shards, progress, balance) {
  if (!pool) return pool
  const skinId = exchanged && exchanged.skinId
  return {
    ...pool,
    shards,
    balance: balance == null ? pool.balance : balance,
    progress: progress || pool.progress,
    skins: (pool.skins || []).map((skin) => (
      skin.skinId === skinId ? { ...skin, owned: true } : skin
    )),
  }
}
