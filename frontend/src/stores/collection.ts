import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { CollectionCard, CollectionData } from '../screens/collection/model'
import { gachaErrorMessage } from './gachaMap'


function normalizeCard(card: CollectionCard): CollectionCard {
  return {
    ...card,
    skins: Array.isArray(card.skins) ? card.skins : [],
    owned_skins: Array.isArray(card.owned_skins) ? card.owned_skins : [],
    selected_skin: typeof card.selected_skin === 'string' && card.selected_skin ? card.selected_skin : 'default',
  }
}

function normalizeCollection(body: CollectionData): CollectionData {
  return {
    ...body,
    cards: Array.isArray(body.cards) ? body.cards.map(normalizeCard) : [],
    shards: typeof body.shards === 'number' && Number.isFinite(body.shards) ? body.shards : 0,
  }
}

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
      data.value = normalizeCollection(body as CollectionData)
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


  async function selectSkin(cardName: string, skin: string): Promise<boolean> {
    if (saving.value) return false
    const token = generation
    saving.value = cardName; error.value = ''
    try {
      const response = await fetch('/api/collection/skin', {
        method:'PUT', credentials:'same-origin',
        headers:{'Content-Type':'application/json', Accept:'application/json'},
        body:JSON.stringify({card_name:cardName, skin}),
      })
      const body = await response.json()
      if (token !== generation) return false
      if (response.status === 401) { error.value = '登录后即可保存卡面选用。'; return false }
      if (!response.ok || !body.ok) { error.value = gachaErrorMessage(body, '卡面没有保存，请重试。'); return false }
      selectionVersion++
      const card = data.value?.cards.find(c=>c.name===cardName)
      if (card) card.selected_skin = typeof body.selected_skin === 'string' && body.selected_skin ? body.selected_skin : skin
      return true
    } catch { if (token === generation) error.value = '卡面没有保存，请重试。'; return false }
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

  return { isOpen, open, close, toggle, data, loading, error, saving, load, reset, select, selectSkin }
})
