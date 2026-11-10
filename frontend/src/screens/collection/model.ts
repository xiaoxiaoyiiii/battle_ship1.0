/** 图鉴只消费本人进度，公开演出只消费服务端随已出牌附带的档位。 */
export interface CollectionCard {
  name: string; description: string; speed: number; type: string
  lit: boolean; uses: number; wins: number; selected_tier: number; unlocked_tier: number
  next_target: number | null; remaining: number; chain_description: string
}
export interface CollectionAchievement {
  id: string; name: string; description: string; current: number; target: number
  tide: number; unlocked: boolean; title?: string
}
export interface CollectionData {
  cards: CollectionCard[]; total: number; lit_count: number; balance: number
  milestones: Array<{target: number; tide: number; claimed: boolean}>
  achievements: CollectionAchievement[]; thresholds: number[]
}
export const MASTERY_NAMES = ['关闭', '潮光', '星曜', '熔金', '虹潮'] as const
export function masteryTier(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 4 ? value : 0
}
export function masteryClass(value: unknown): string {
  const tier = masteryTier(value)
  return tier ? `mastery-glow mastery-glow--${tier}` : ''
}
export interface CollectionFilter { query: string; status: string; speed: string; type: string; sort: string }
export function filteredCards(cards: CollectionCard[], filter: CollectionFilter): CollectionCard[] {
  const query = filter.query.trim().toLocaleLowerCase()
  const rows = cards.filter(c => (!query || (c.name + c.description).toLocaleLowerCase().includes(query))
    && (filter.status === 'all' || (filter.status === 'lit' ? c.lit : !c.lit))
    && (filter.speed === 'all' || c.speed === Number(filter.speed))
    && (filter.type === 'all' || c.type === filter.type))
  if (filter.sort === 'uses') rows.sort((a,b) => b.uses-a.uses || a.name.localeCompare(b.name,'zh-CN'))
  if (filter.sort === 'name') rows.sort((a,b) => a.name.localeCompare(b.name,'zh-CN'))
  return rows
}
