import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { bgmBedForRoute, endgameLayerForBattle } from '../audio/bgmScene'
import {
  isBgmRunning,
  playSfx,
  setBgmScene,
  startBgm,
  stopBgm,
  unlockAudio,
  setSfxPreferences,
  stopSfx,
  preloadSfx,
} from '../audio/engine'
import { cardSound } from '../audio/cardSounds'
import { UI_SOUNDS, UI_SOUND_COOLDOWN, type UiSound } from '../audio/uiSounds'

/**
 * Local audio preferences (ticket #33).
 *
 * These are not account settings and never touch the server: they mirror the
 * legacy `sfx_muted` / `bgm_*` localStorage keys (plus a sound volume the
 * legacy synth never persisted) so a refresh restores the exact controls.
 */

export const AUDIO_STORAGE = {
  sfxMuted: 'sfx_muted',
  sfxVolume: 'sfx_volume',
  interfaceSfx: 'ui_sfx_enabled',
  bgmMuted: 'bgm_muted',
  bgmVolume: 'bgm_volume',
  bgmPlaying: 'bgm_playing',
} as const

function readRaw(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function readBool(key: string, fallback: boolean): boolean {
  const raw = readRaw(key)
  if (raw === null) return fallback
  return raw === 'true'
}

function clampVolume(value: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback
  return Math.max(0, Math.min(1, value))
}

function readVolume(key: string, fallback: number): number {
  const raw = readRaw(key)
  if (raw === null || raw.trim() === '') return fallback
  return clampVolume(Number.parseFloat(raw), fallback)
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Private contexts can reject writes; the in-memory setting still works.
  }
}

export const useAudioStore = defineStore('audio', () => {
  const sfxMuted = ref(readBool(AUDIO_STORAGE.sfxMuted, false))
  const sfxVolume = ref(readVolume(AUDIO_STORAGE.sfxVolume, 0.8))
  const interfaceSfx = ref(readBool(AUDIO_STORAGE.interfaceSfx, true))
  const bgmMuted = ref(readBool(AUDIO_STORAGE.bgmMuted, false))
  const bgmVolume = ref(readVolume(AUDIO_STORAGE.bgmVolume, 0.5))
  // 没有本地记录时默认播放。已经保存的 false 保持关闭，这里不回写、也不迁移旧数据。
  const bgmPlaying = ref(readBool(AUDIO_STORAGE.bgmPlaying, true))
  const heardEffects = new Set<string>()
  let resultPlayedFor = ''
  let battleScene = false
  const lastUiSound = new Map<UiSound, number>()
  setSfxPreferences(sfxVolume.value, sfxMuted.value)

  const sfxVolumePercent = computed(() => Math.round(sfxVolume.value * 100))
  const bgmVolumePercent = computed(() => Math.round(bgmVolume.value * 100))
  const bgmStatus = computed(() => {
    if (bgmPlaying.value) return bgmMuted.value ? '播放中 · 已静音' : '播放中'
    return bgmMuted.value ? '已暂停 · 已静音' : '已暂停'
  })

  function setSfxMuted(value: boolean): void {
    sfxMuted.value = Boolean(value)
    write(AUDIO_STORAGE.sfxMuted, sfxMuted.value ? 'true' : 'false')
    setSfxPreferences(sfxVolume.value, sfxMuted.value)
  }

  function toggleSfxMute(): boolean {
    setSfxMuted(!sfxMuted.value)
    return sfxMuted.value
  }

  function setSfxVolume(value: number): void {
    sfxVolume.value = clampVolume(value, sfxVolume.value)
    write(AUDIO_STORAGE.sfxVolume, String(sfxVolume.value))
    setSfxPreferences(sfxVolume.value, sfxMuted.value)
  }

  function previewSfx(): void {
    playSfx('gabriel', sfxVolume.value, sfxMuted.value)
  }

  function applyBgm(): void {
    if (bgmPlaying.value) startBgm(bgmVolume.value, bgmMuted.value)
    else stopBgm()
  }

  /**
   * 页面和舰数决定曲子。签到、好友等浮层不在这里，避免把循环打断。
   * 胜负页是 hold：引擎保持当前曲子和已经叠上的终局层。
   */
  function syncBgmScene(input: {
    routeName: string | null
    splashActive: boolean
    roomState: string
    selfShips: number
    opponentShips: number
  }): void {
    const bed = bgmBedForRoute(input.routeName, input.splashActive)
    const endgame = endgameLayerForBattle(bed, input.roomState, input.selfShips, input.opponentShips)
    setBgmScene(bed, endgame)
  }

  function setBgmPlaying(value: boolean): void {
    bgmPlaying.value = Boolean(value)
    write(AUDIO_STORAGE.bgmPlaying, bgmPlaying.value ? 'true' : 'false')
    applyBgm()
  }

  function toggleBgmPlay(): boolean {
    setBgmPlaying(!bgmPlaying.value)
    return bgmPlaying.value
  }

  function setBgmMuted(value: boolean): void {
    bgmMuted.value = Boolean(value)
    write(AUDIO_STORAGE.bgmMuted, bgmMuted.value ? 'true' : 'false')
    if (bgmPlaying.value) startBgm(bgmVolume.value, bgmMuted.value)
  }

  function toggleBgmMute(): boolean {
    setBgmMuted(!bgmMuted.value)
    return bgmMuted.value
  }

  function setBgmVolume(value: number): void {
    bgmVolume.value = clampVolume(value, bgmVolume.value)
    write(AUDIO_STORAGE.bgmVolume, String(bgmVolume.value))
    if (bgmPlaying.value) startBgm(bgmVolume.value, bgmMuted.value)
  }

  /** Fire one battle sound; the reducer calls this without knowing the engine. */
  function play(name: string): void {
    playSfx(name, sfxVolume.value, sfxMuted.value)
  }

  function setInterfaceSfx(enabled: boolean): void {
    interfaceSfx.value = Boolean(enabled)
    write(AUDIO_STORAGE.interfaceSfx, String(interfaceSfx.value))
    if (!interfaceSfx.value) stopSfx('interface')
  }

  function playUi(name: UiSound): boolean {
    if (!interfaceSfx.value || sfxMuted.value || sfxVolume.value === 0) return false
    const now = Date.now()
    const previous = lastUiSound.get(name)
    if (previous !== undefined && now - previous < UI_SOUND_COOLDOWN[name]) return false
    const played = playSfx(UI_SOUNDS[name], sfxVolume.value, sfxMuted.value)
    if (played) lastUiSound.set(name, now)
    return played
  }

  function playCardEffect(payload: Record<string, unknown>): void {
    const id = typeof payload.effect_id === 'string' ? payload.effect_id : ''
    const name = typeof payload.card === 'string' ? cardSound(payload.card) : null
    if (!id || !name || heardEffects.has(id)) return
    heardEffects.add(id)
    if (heardEffects.size > 256) heardEffects.delete(heardEffects.values().next().value!)
    if (battleScene) play(name)
  }

  function playBattle(name: string): void {
    if (battleScene) play(name)
  }

  function setBattleScene(active: boolean): void {
    battleScene = active
    if (!active) stopSfx('battle')
  }

  function resetMatchAudio(): void {
    stopSfx('battle')
    heardEffects.clear()
    resultPlayedFor = ''
  }

  function playOutcome(room: string, outcome: string): void {
    if (!room || !['win', 'lose'].includes(outcome) || resultPlayedFor === room) return
    resultPlayedFor = room
    stopSfx('battle')
    play(outcome)
  }

  if (typeof window !== 'undefined') {
    // 先解码轻量界面素材，第一次手势只需解锁，避免按完按钮才开始下载。
    void preloadSfx(Object.values(UI_SOUNDS))
    const unlock = (): void => {
      unlockAudio()
      if (bgmPlaying.value) startBgm(bgmVolume.value, bgmMuted.value)
    }
    window.addEventListener('pointerdown', unlock, { once: true })
    window.addEventListener('keydown', unlock, { once: true })
    // Restore the requested BGM state; the context itself may stay suspended
    // until the first gesture (browser autoplay policy), which is expected.
    if (bgmPlaying.value) startBgm(bgmVolume.value, bgmMuted.value)
  }

  return {
    sfxMuted,
    sfxVolume,
    interfaceSfx,
    bgmMuted,
    bgmVolume,
    bgmPlaying,
    sfxVolumePercent,
    bgmVolumePercent,
    bgmStatus,
    setSfxMuted,
    toggleSfxMute,
    setSfxVolume,
    setInterfaceSfx,
    previewSfx,
    setBgmPlaying,
    toggleBgmPlay,
    setBgmMuted,
    toggleBgmMute,
    setBgmVolume,
    syncBgmScene,
    play,
    playUi,
    playCardEffect,
    playBattle,
    setBattleScene,
    playOutcome,
    resetMatchAudio,
    stop: stopSfx,
    isBgmRunning,
  }
})
