import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { CollectionData } from '../screens/collection/model'

/** 独立图鉴页的数据与请求代次。旧入口的打开信号由壳层统一转成路由导航。 */
export const useCollectionStore = defineStore('collection', () => {
  const isOpen = ref(false)
  const data = ref<CollectionData | null>(null)
  const loading = ref(false), error = ref(''), saving = ref('')
  let generation = 0, loadVersion = 0, selectionVersion = 0

  function reset(): void { generation++; data.value = null; loading.value = false; error.value = ''; saving.value = '' }
  async function load(): Promise<void> {
    const token = generation, request = ++loadVersion, selection = selectionVersion
    loading.value = true; error.value = ''
    try {
      const response = await fetch('/api/collection', { credentials:'same-origin', headers:{Accept:'application/json'} })
      const body = await response.json()
      if (token !== generation || request !== loadVersion || selection !== selectionVersion) return
      if (!response.ok || !body || !Array.isArray(body.cards) || !Array.isArray(body.achievements)) {
        error.value = response.status === 401 ? '登录后即可记录点亮、熟练和成就。' : '图鉴暂时读取失败，请重试。'
        return
      }
      data.value = body as CollectionData
    } catch { if (token === generation && request === loadVersion) error.value = '图鉴暂时读取失败，请重试。' }
    finally { if (token === generation && request === loadVersion) loading.value = false }
  }
  async function select(name: string, tier: number): Promise<boolean> {
    if (saving.value) return false
    const token = generation
    saving.value = name; error.value = ''
    try {
      const response = await fetch('/api/collection/mastery', {method:'POST', credentials:'same-origin',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({card_name:name,tier})})
      const body = await response.json()
      if (token !== generation) return false
      if (!response.ok || !body.ok) { error.value = body.error || '光效没有保存，请重试。'; return false }
      selectionVersion++
      const card = data.value?.cards.find(c=>c.name===name)
      if (card) card.selected_tier = body.selected_tier
      return true
    } catch { if (token === generation) error.value = '光效没有保存，请重试。'; return false }
    finally { if (token === generation) saving.value = '' }
  }

  function open(): void {
    isOpen.value = true
  }

  function close(): void {
    isOpen.value = false
  }

  function toggle(): void {
    isOpen.value = !isOpen.value
  }

  return { isOpen, open, close, toggle, data, loading, error, saving, load, reset, select }
})
