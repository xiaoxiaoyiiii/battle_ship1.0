/** 图鉴只消费本人进度，公开演出只消费服务端随已出牌附带的档位。 */
export interface CollectionSkin {
  skin_id: string
  card_key?: string
  tier?: string
  owned?: boolean
}
export interface CollectionCard {
  name: string; description: string; speed: number; type: string
  lit: boolean; uses: number; wins: number; selected_tier: number; unlocked_tier: number
  next_target: number | null; remaining: number; chain_description: string
  skins?: CollectionSkin[]
  owned_skins?: string[]
  selected_skin?: string
}
export interface CollectionAchievement {
  id: string; name: string; description: string; current: number; target: number
  tide: number; unlocked: boolean; title?: string
}
export interface CollectionData {
  cards: CollectionCard[]; total: number; lit_count: number; balance: number
  milestones: Array<{target: number; tide: number; claimed: boolean}>
  achievements: CollectionAchievement[]; thresholds: number[]
  shards?: number
}
export const MASTERY_NAMES = ['关闭', '潮光', '星曜', '熔金', '虹潮'] as const
export function masteryTier(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 4 ? value : 0
}
export function masteryClass(value: unknown): string {
  const tier = masteryTier(value)
  return tier ? `mastery-glow mastery-glow--${tier}` : ''
}
export interface CollectionFilter { query: string; status: string; speed: string; type: string; sort: string; skin: string }
export function filteredCards(cards: CollectionCard[], filter: CollectionFilter): CollectionCard[] {
  const query = filter.query.trim().toLocaleLowerCase()
  const rows = cards.filter(c => (!query || (c.name + c.description).toLocaleLowerCase().includes(query))
    && (filter.status === 'all' || (filter.status === 'lit' ? c.lit : !c.lit))
    && (filter.skin !== 'owned' || ownedSkinIds(c).length > 0)
    && (filter.speed === 'all' || c.speed === Number(filter.speed))
    && (filter.type === 'all' || c.type === filter.type))
  if (filter.sort === 'uses') rows.sort((a,b) => b.uses-a.uses || a.name.localeCompare(b.name,'zh-CN'))
  if (filter.sort === 'name') rows.sort((a,b) => a.name.localeCompare(b.name,'zh-CN'))
  return rows
}

export function ownedSkinIds(card: CollectionCard | null | undefined): string[] {
  if (!card) return []
  if (Array.isArray(card.owned_skins) && card.owned_skins.length) {
    return card.owned_skins.filter((id): id is string => typeof id === 'string' && id.length > 0 && id !== 'default')
  }
  return (card.skins ?? []).filter((skin) => skin.owned && skin.skin_id).map((skin) => skin.skin_id)
}

export function selectedSkinId(card: CollectionCard | null | undefined): string {
  const value = card?.selected_skin
  return typeof value === 'string' && value ? value : 'default'
}
