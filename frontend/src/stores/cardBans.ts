import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useAuthStore } from './auth'

export interface CardBanState {
  enabled: true
  quota: number
  phase: 'countdown' | 'selecting' | 'revealed'
  countdown_deadline: number | null
  selection_deadline: number | null
  own_selection: string[]
  confirmed: boolean
  opponent_confirmed: boolean
  revealed: Record<string, string[]> | null
  banned_names: string[]
  pool: string[]
  ranked: boolean
}

export interface BanRules {
  pool: string[]
  own_quota: number
  defaults: string[]
  countdown_seconds: number
  selection_seconds: number
}

export function banSelectionError(selection: string[], pool: string[], quota: number): string {
  if (!Number.isInteger(quota) || quota < 0 || selection.length > quota) return '已超过本次可选名额，请先取消多选的卡。'
  if (new Set(selection).size !== selection.length) return '同一张卡只能选择一次。'
  if (selection.some(name => name === '失灵！' || !pool.includes(name))) return '选择包含不可 Ban 的卡，请重新选择。'
  return ''
}

/** 预选只按真实账号保存；房间草稿另由服务器持有。 */
export const useCardBansStore = defineStore('card-bans', () => {
  const auth = useAuthStore()
  const rules = ref<BanRules | null>(null)
  const preselection = ref<string[]>([])
  const storageError = ref('')
  const accountId = computed(() => auth.user?.id || '')
  const selectionError = computed(() => rules.value
    ? banSelectionError(preselection.value, rules.value.pool, rules.value.own_quota)
    : '正在同步本账号的 Ban 名额，请稍候。')

  watch(accountId, id => {
    preselection.value = []
    rules.value = null
    storageError.value = ''
    if (!id) return
    try {
      const saved: unknown = JSON.parse(localStorage.getItem('battleship.ban-preselection:' + id) || '[]')
      if (Array.isArray(saved)) preselection.value = saved.filter((name): name is string => typeof name === 'string')
    } catch { storageError.value = '无法读取本机预选，可重新选择。' }
  }, { immediate: true })

  function recordRules(raw: unknown): void {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return
    const value = raw as Record<string, unknown>
    if (!Array.isArray(value.pool) || !Number.isInteger(value.own_quota) || Number(value.own_quota) < 0) return
    rules.value = {
      pool: value.pool.filter((name): name is string => typeof name === 'string' && name !== '失灵！'),
      own_quota: Number(value.own_quota),
      defaults: Array.isArray(value.defaults) ? value.defaults.filter((name): name is string => typeof name === 'string') : [],
      countdown_seconds: Number(value.countdown_seconds) || 5,
      selection_seconds: Number(value.selection_seconds) || 20,
    }
  }

  function savePreselection(selection: string[]): boolean {
    if (!accountId.value || !rules.value || banSelectionError(selection, rules.value.pool, rules.value.own_quota)) return false
    preselection.value = [...selection]
    storageError.value = ''
    try { localStorage.setItem('battleship.ban-preselection:' + accountId.value, JSON.stringify(selection)) }
    catch { storageError.value = '本机存储不可用，预选仅在当前页面保留。' }
    return true
  }
  return { rules, preselection, selectionError, storageError, accountId, recordRules, savePreselection }
})
