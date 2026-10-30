import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

/**
 * 玩家在本机选择的交互装饰。
 *
 * 服务端 profile_effects 是最终装备状态；localStorage 只在游客或接口尚未
 * 返回时提供本地回退。未知值统一回退到 none，避免旧版本或脏数据让交互层
 * 意外替玩家打开付费特效。
 */
export type PointerEffectId = 'none' | 'ripple' | 'comet' | 'stardust' | 'eclipse'

export const POINTER_EFFECTS: Array<{
  id: PointerEffectId
  name: string
  description: string
  tier: '基础' | '高级' | '豪华'
}> = [
  { id: 'none', name: '关闭', description: '不显示全局交互特效', tier: '基础' },
  { id: 'ripple', name: '潮汐点击', description: '点击与手机轻触泛起一圈潮纹', tier: '基础' },
  { id: 'comet', name: '彗星航迹', description: '鼠标拖动时留下短暂彗尾', tier: '高级' },
  { id: 'stardust', name: '星尘航迹', description: '点击爆发星尘，拖动留下粒子尾迹', tier: '高级' },
  { id: 'eclipse', name: '日蚀脉冲', description: '点击产生日蚀环，拖动形成暗金脉冲', tier: '豪华' },
]

const STORAGE_KEY = 'battleship.cosmetics.pointerEffect'

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function isPointerEffectId(value: unknown): value is PointerEffectId {
  return POINTER_EFFECTS.some(item => item.id === value)
}

function readPointerEffect(): PointerEffectId {
  try {
    const value = storage()?.getItem(STORAGE_KEY)
    return isPointerEffectId(value) ? value : 'none'
  } catch {
    return 'none'
  }
}

export const useCosmeticStore = defineStore('cosmetics', () => {
  const pointerEffect = ref<PointerEffectId>(readPointerEffect())

  function setPointerEffect(next: PointerEffectId): void {
    pointerEffect.value = isPointerEffectId(next) ? next : 'none'
    try {
      storage()?.setItem(STORAGE_KEY, pointerEffect.value)
    } catch {
      // 外观偏好写不进去不影响本次会话。
    }
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('bs:cosmetic-pointer', { detail: pointerEffect.value }))
    }
  }

  /** 登录后用个人资料的服务端装备覆盖本地回退值。 */
  function syncFromProfile(profile: Record<string, unknown> | null | undefined): void {
    const value = profile?.pointer_effect_id
    const next = isPointerEffectId(value) ? value : 'none'
    pointerEffect.value = next
    try { storage()?.setItem(STORAGE_KEY, next) } catch { /* 回退值仍在本次会话生效。 */ }
  }

  const pointerEffectMeta = computed(() => POINTER_EFFECTS.find(item => item.id === pointerEffect.value) || POINTER_EFFECTS[3])

  return { pointerEffect, pointerEffectMeta, setPointerEffect, syncFromProfile }
})
