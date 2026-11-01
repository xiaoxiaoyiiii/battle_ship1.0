/** 词条文案、目录和互斥关系均以服务端本周快照为准。 */
export interface MutationEntry {
  id: string
  group: string
  name: string
  description: string
}

export interface MutationState {
  ids: string[]
  entries: MutationEntry[]
  week_id: string
  confirmation_required: boolean
  confirmed: boolean
  waiting_for: number
  ack_token: string
  starting_ship_cap: number
  dice_rolls: Record<string, number>
  storm_active: boolean
  preparation_cast: boolean
  round_casts: number
  extra_discard_required: boolean
}

export interface WeeklyMutations {
  week_id: string
  pack_id: string
  name: string
  entries: MutationEntry[]
  catalog: MutationEntry[]
  pair_blacklist: string[][]
}

export function normalizeWeeklyMutations(value: unknown): WeeklyMutations | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  const entries = (items: unknown): MutationEntry[] => Array.isArray(items) ? items.flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const entry = item as Record<string, unknown>
    if (typeof entry.id !== 'string' || typeof entry.group !== 'string' || typeof entry.name !== 'string' || typeof entry.description !== 'string') return []
    return [{ id: entry.id, group: entry.group, name: entry.name, description: entry.description }]
  }) : []
  return {
    week_id: String(raw.week_id ?? ''), pack_id: String(raw.pack_id ?? ''), name: String(raw.name ?? ''),
    entries: entries(raw.entries), catalog: entries(raw.catalog),
    pair_blacklist: Array.isArray(raw.pair_blacklist) ? raw.pair_blacklist.filter((pair): pair is string[] => Array.isArray(pair) && pair.length === 2 && pair.every(id => typeof id === 'string')) : [],
  }
}

export function mutationSelectionError(ids: string[], weekly: WeeklyMutations | null): string {
  if (!ids.length) return ''
  if (!weekly) return '词条目录尚未载入，请刷新大厅后重试。'
  const chosen: MutationEntry[] = []
  for (const id of ids) {
    const entry = weekly.catalog.find(item => item.id === id)
    if (!entry) return '词条目录已更新，请重新选择。'
    const conflict = chosen.find(item => item.group === entry.group)
    if (conflict) return `「${entry.name}」与「${conflict.name}」属于同一互斥组。`
    const blocked = chosen.find(item => weekly.pair_blacklist.some(pair => pair.includes(item.id) && pair.includes(id)))
    if (blocked) return `「${entry.name}」与「${blocked.name}」不能在同一局生效。`
    chosen.push(entry)
  }
  return ''
}
