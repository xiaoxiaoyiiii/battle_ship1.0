import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useWalletStore } from './wallet'
import { useShopStore } from './shop'

export interface MailAttachment { kind: string; amount?: number; reward_id?: string; name?: string }
export interface PlayerMail {
  id: string; title: string; body: string; attachments: MailAttachment[]
  created_at: number; expires_at: number; attachment_expires_at: number
  read_at: number | null; claimed_at: number | null; unread: boolean; can_claim: boolean; can_delete: boolean
}

export const useMailboxStore = defineStore('mailbox', () => {
  const items = ref<PlayerMail[]>([])
  const unclaimedCount = ref(0)
  const unreadCount = ref(0)
  const loading = ref(false)
  const busy = ref('')
  const error = ref('')
  let generation = 0

  function reset(): void {
    generation++; items.value = []; unclaimedCount.value = 0; unreadCount.value = 0
    loading.value = false; error.value = ''; busy.value = ''
  }
  async function load(): Promise<void> {
    const token = ++generation
    loading.value = true
    try {
      const response = await fetch('/api/mailbox', { credentials: 'same-origin', cache: 'no-store' })
      if (token !== generation) return
      if (response.status === 401) { reset(); return }
      if (!response.ok) throw new Error('邮箱暂时无法读取，请重试')
      const body = await response.json()
      if (token !== generation) return
      if (!Array.isArray(body.items)) throw new Error('邮件数据异常')
      items.value = body.items
      unclaimedCount.value = Number(body.unclaimed_count) || 0
      unreadCount.value = Number(body.unread_count) || 0
      error.value = ''
    } catch (cause) {
      if (token === generation) error.value = cause instanceof Error ? cause.message : '邮箱读取失败'
    } finally { if (token === generation) loading.value = false }
  }
  async function act(id: string, action: 'read' | 'claim' | 'delete'): Promise<boolean> {
    if (busy.value) return false
    busy.value = id
    error.value = ''
    try {
      const response = await fetch(`/api/mailbox/${encodeURIComponent(id)}/${action}`, { method: 'POST', credentials: 'same-origin' })
      const body = await response.json()
      if (!response.ok || !body.ok) throw new Error(body.reason || '邮件操作失败')
      if (action === 'claim') {
        if (typeof body.balance === 'number') useWalletStore().apply({ balance: body.balance }, 'api')
        void useShopStore().load(true)
      }
      await load()
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '邮件操作失败'
      return false
    } finally { busy.value = '' }
  }
  return { items, unclaimedCount, unreadCount, loading, busy, error, load, act, reset }
})
