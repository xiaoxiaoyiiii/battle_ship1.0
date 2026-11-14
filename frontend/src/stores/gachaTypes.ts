export type GachaKind = 'shard' | 'legendary' | 'limited'
export type GachaTier = 'legendary' | 'limited'
export type GachaStatus = 'idle' | 'loading' | 'ready' | 'error' | 'anonymous'

export interface GachaPull {
  index: number
  kind: GachaKind
  skinId: string | null
  cardKey: string | null
  cardName: string | null
  isNew: boolean
  shardsGained: number
}

export interface GachaProgress {
  owned: number
  total: number
  complete: boolean
}

export interface GachaPullSummary {
  newSkins: string[]
  duplicates: number
  shardsGained: number
}

export interface GachaPullResult {
  requestId: string
  replayed: boolean
  count: 1 | 10
  results: GachaPull[]
  balance: number
  shards: number
  cost?: number
  currency?: string
  summary?: GachaPullSummary
  progress?: GachaProgress | null
}

export interface GachaRateLine {
  kind: string
  label: string
  percent: string
  note: string
}

export interface GachaPoolSkin {
  skinId: string
  cardKey: string
  cardName: string
  tier: GachaTier
  owned: boolean
}

export interface GachaPool {
  ok: boolean
  poolId: string
  currency: string
  balance: number
  shards: number
  prices: { single: number; ten: number }
  rates: { limited: number; legendary: number; shard: number }
  ratesDisplay: GachaRateLine[]
  duplicateShards: number
  shardPerDraw: number
  exchangeCost: { legendary: number; limited: number }
  pity: null | unknown
  skins: GachaPoolSkin[]
  progress: GachaProgress
}

export interface GachaExchangeResult {
  skin: GachaPoolSkin | null
  cost: number
  shards: number
  balance: number
  progress: GachaProgress
}

export interface GachaActionResult {
  ok: boolean
  code: string
  message: string
  replayed?: boolean
  result?: GachaPullResult
  alreadyOwned?: boolean
}
