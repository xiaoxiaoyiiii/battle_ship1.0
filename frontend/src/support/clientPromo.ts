/** 客户端下载弹窗：平台分流、浏览器本地每日去重与客户端壳识别。 */

export const CLIENT_UA_MARKER = 'BattleshipClient/'

/** 安装包直链（服务端 /static/clients/ 静态托管，部署时同步上传）。 */
export const CLIENT_DOWNLOAD_URLS = {
  android: '/static/clients/battleship.apk',
  windows: '/static/clients/battleship-setup.exe',
} as const

export type PromoPlatform = 'android' | 'windows' | 'ios' | 'other'

type StoragePort = Pick<Storage, 'getItem' | 'setItem'> | null
const memory = new Map<string, string>()

/** 客户端壳内不再弹下载提示（壳自己就是客户端）。 */
export function isBattleshipClient(ua: string = navigator.userAgent): boolean {
  return ua.includes(CLIENT_UA_MARKER)
}

export function promoPlatform(ua: string = navigator.userAgent): PromoPlatform {
  if (/Android/i.test(ua)) return 'android'
  if (/iPhone|iPad|iPod/i.test(ua)) return 'ios'
  if (/Windows/i.test(ua)) return 'windows'
  return 'other'
}

function historyKey(owner: string): string {
  return 'bs.client-promo.' + owner
}

/** 浏览器本地每日去重（北京时间，与支持作者提醒同一套天界算法）。 */
export function drawClientPromo(
  owner: string, storage: StoragePort = safeStorage(), now = Date.now(),
): boolean {
  if (!owner) return false
  const key = historyKey(owner)
  const day = supportDay(now)
  let saved: string | null = null
  try { saved = storage?.getItem(key) || null } catch { saved = null }
  if (saved === day) return false
  if (memory.get(key) === day) return false
  memory.set(key, day)
  try { storage?.setItem(key, day) } catch { /* 本页内存仍保留每日去重。 */ }
  return true
}

/** 服务端判定后未弹（账号维度已弹过）时，把本地今天也标记为已弹。 */
export function markClientPromoShown(owner: string, storage: StoragePort = safeStorage()): void {
  const key = historyKey(owner)
  const day = supportDay()
  memory.set(key, day)
  try { storage?.setItem(key, day) } catch { /* 忽略不可写存储。 */ }
}

function safeStorage(): StoragePort {
  try { return localStorage } catch { return null }
}

/** 北京时间天界（支持作者提醒同款）。 */
function supportDay(now: number = Date.now()): string {
  return new Date(now + 8 * 60 * 60 * 1000).toISOString().slice(0, 10)
}
