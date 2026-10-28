import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  isBgmRunning,
  playSfx,
  startBgm,
  stopBgm,
  unlockAudio,
  setSfxPreferences,
  stopSfx,
} from '../audio/engine'
import { cardSound } from '../audio/cardSounds'

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
  const bgmMuted = ref(readBool(AUDIO_STORAGE.bgmMuted, false))
  const bgmVolume = ref(readVolume(AUDIO_STORAGE.bgmVolume, 0.5))
  const bgmPlaying = ref(readBool(AUDIO_STORAGE.bgmPlaying, false))
  const heardEffects = new Set<string>()
  let resultPlayedFor = ''
  let battleScene = false
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
    if (!active) stopSfx()
  }

  function resetMatchAudio(): void {
    stopSfx()
    heardEffects.clear()
    resultPlayedFor = ''
  }

  function playOutcome(room: string, outcome: string): void {
    if (!room || !['win', 'lose'].includes(outcome) || resultPlayedFor === room) return
    resultPlayedFor = room
    stopSfx()
    play(outcome)
  }

  if (typeof window !== 'undefined') {
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
    bgmMuted,
    bgmVolume,
    bgmPlaying,
    sfxVolumePercent,
    bgmVolumePercent,
    bgmStatus,
    setSfxMuted,
    toggleSfxMute,
    setSfxVolume,
    previewSfx,
    setBgmPlaying,
    toggleBgmPlay,
    setBgmMuted,
    toggleBgmMute,
    setBgmVolume,
    play,
    playCardEffect,
    playBattle,
    setBattleScene,
    playOutcome,
    resetMatchAudio,
    stop: stopSfx,
    isBgmRunning,
  }
})
