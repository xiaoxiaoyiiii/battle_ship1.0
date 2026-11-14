import { getActivePinia } from 'pinia'
import { getCurrentInstance, watch } from 'vue'
import { useAudioStore } from '../../../stores/audio'

const samples = {
  charge: new URL('./sfx/charge.wav', import.meta.url).href,
  flip: new URL('./sfx/flip.wav', import.meta.url).href,
  legendary: new URL('./sfx/legendary.wav', import.meta.url).href,
  limited: new URL('./sfx/limited.wav', import.meta.url).href,
} as const

type Sample = keyof typeof samples
interface Preferences { muted: boolean; volume: number; enabled: boolean }

/** 只读取已经存在的音频 store；演示页不能因为抽卡而启动整套 BGM。 */
function readPreferences(pinia: ReturnType<typeof getActivePinia>): Preferences {
  const stores = (pinia as typeof pinia & { _s?: Map<string, unknown> })?._s
  if (pinia && stores?.has(useAudioStore.$id)) {
    const audio = useAudioStore(pinia)
    return { muted: audio.sfxMuted, volume: audio.sfxVolume, enabled: audio.interfaceSfx }
  }
  function read(key: string) {
    try { return localStorage.getItem(key) } catch { return null }
  }
  const rawVolume = read('sfx_volume')
  const volume = rawVolume === null || rawVolume.trim() === '' ? 0.8 : Number.parseFloat(rawVolume)
  return {
    muted: read('sfx_muted') === 'true',
    volume: Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 0.8,
    enabled: read('ui_sfx_enabled') === null || read('ui_sfx_enabled') === 'true',
  }
}

/** 独立媒体通道；不注册全局音效映射，不修改设置或 localStorage。 */
export function createGachaAudio() {
  const instance = getCurrentInstance()
  // Pinia 2 的 getActivePinia 在无注入的 setup 中会警告，先检查该应用是否装有 Pinia。
  const pinia = !instance || instance.appContext.config.globalProperties.$pinia ? getActivePinia() : undefined
  const preferences = () => readPreferences(pinia)
  const active = new Map<HTMLAudioElement, number>()
  let disposed = false

  function stop(audio: HTMLAudioElement) {
    if (!active.delete(audio)) return
    audio.pause()
    audio.removeAttribute('src')
    audio.load()
  }

  function stopAll() { [...active.keys()].forEach(stop) }

  function synchronize() {
    const current = preferences()
    if (current.muted || !current.enabled || current.volume <= 0) stopAll()
    else active.forEach((level, audio) => { audio.volume = current.volume * level })
  }

  const stopWatch = watch(preferences, synchronize, { flush: 'sync' })
  // 无 Pinia 的独立演示页也要响应同页写入的 localStorage（storage 事件只跨页触发）。
  const preferencePoll = setInterval(synchronize, 120)
  if (typeof window !== 'undefined') window.addEventListener('storage', synchronize)

  return {
    play(sample: Sample, options: { loop?: boolean; level?: number; rate?: number } = {}) {
      const current = preferences()
      if (disposed || current.muted || !current.enabled || current.volume <= 0 || typeof Audio === 'undefined') return () => {}
      const level = Math.max(0, Math.min(1, options.level ?? 1))
      const audio = new Audio(samples[sample])
      audio.volume = current.volume * level
      audio.loop = options.loop === true
      audio.playbackRate = options.rate ?? 1
      active.set(audio, level)
      audio.addEventListener('ended', () => stop(audio), { once: true })
      audio.addEventListener('error', () => stop(audio), { once: true })
      void audio.play().catch(() => stop(audio))
      return () => stop(audio)
    },
    stopAll,
    dispose() {
      disposed = true
      stopAll()
      stopWatch()
      clearInterval(preferencePoll)
      if (typeof window !== 'undefined') window.removeEventListener('storage', synchronize)
    },
  }
}
