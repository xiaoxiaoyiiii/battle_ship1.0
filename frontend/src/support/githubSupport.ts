/** 所有推广入口使用同一地址；概率与浏览器内去重不依赖结算奖励。 */
export const GITHUB_URL = 'https://github.com/xiaoxiaoyiiii/battle_ship1.0'
export const SUPPORT_PROBABILITY = 0.1

type StoragePort = Pick<Storage, 'getItem' | 'setItem'> | null
interface PromptHistory { day: string; matches: string[]; shown: boolean }
const memory = new Map<string, PromptHistory>()

export function supportDay(now = Date.now()): string {
  return new Date(now + 8 * 60 * 60 * 1000).toISOString().slice(0, 10)
}

export function supportStorage(): StoragePort {
  try { return localStorage } catch { return null }
}

function history(owner: string, storage: StoragePort, now: number): PromptHistory {
  const key = 'bs.support-prompt.' + owner
  let saved = memory.get(key)
  try {
    const raw = JSON.parse(storage?.getItem(key) || 'null')
    if (raw?.day === supportDay(now) && Array.isArray(raw.matches) && typeof raw.shown === 'boolean') {
      const current = saved?.day === raw.day ? saved : null
      saved = {
        day: raw.day,
        matches: [...new Set<string>([...(current?.matches || []), ...raw.matches.filter((value: unknown) => typeof value === 'string')])],
        shown: raw.shown || Boolean(current?.shown),
      }
    }
  } catch { /* 浏览器禁止存储或旧值损坏时，继续使用本页内存。 */ }
  return saved?.day === supportDay(now) ? saved : { day: supportDay(now), matches: [], shown: false }
}

function save(owner: string, value: PromptHistory, storage: StoragePort): void {
  const key = 'bs.support-prompt.' + owner
  memory.set(key, value)
  try { storage?.setItem(key, JSON.stringify(value)) } catch { /* 本页仍保留每日去重。 */ }
}

export function drawSupportPrompt(
  owner: string, matchKey: string, storage = supportStorage(), random = Math.random, now = Date.now(),
): boolean {
  if (!matchKey) return false
  const saved = history(owner, storage, now)
  if (saved.shown || saved.matches.includes(matchKey)) return false
  saved.matches.push(matchKey)
  save(owner, saved, storage)
  return random() < SUPPORT_PROBABILITY
}

export function markSupportPromptShown(owner: string, storage = supportStorage(), now = Date.now()): void {
  const saved = history(owner, storage, now)
  saved.shown = true
  save(owner, saved, storage)
}
