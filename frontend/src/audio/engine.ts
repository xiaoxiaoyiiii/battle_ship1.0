import { SAMPLE_GAINS, SAMPLE_URLS } from './samples'
import {
  BGM_CROSSFADE_SECONDS,
  loopDistanceSeconds,
  loopOffsetSeconds,
  trimFrameCount,
  type BgmBed,
} from './bgmScene'
import { BGM_TRACK_URLS, type BgmTrackName } from './tracks'

/** 音效统一走可调音量的总线；采样素材缓存解码。背景音乐走另一条总线，不用振荡器垫乐。 */

type SfxName =
  | 'hit' | 'miss' | 'sunk' | 'draw' | 'play_card'
  | 'chain' | 'turn' | 'win' | 'lose'

let context: AudioContext | null = null
let sfxBus: { master: GainNode; limiter: DynamicsCompressorNode } | null = null
let sfxVolume = 0.8
let sfxMuted = false
type SfxScope = 'battle' | 'interface'
const voices = new Map<AudioScheduledSourceNode, SfxScope>()
const buffers = new Map<string, AudioBuffer>()
const loading = new Map<string, Promise<void>>()
type BgmVoiceName = BgmTrackName

interface BgmRamp {
  from: number
  to: number
  start: number
  end: number
}

interface BgmVoice {
  id: number
  source: AudioBufferSourceNode
  startedAt: number
  buffer: AudioBuffer
}

let bgmBus: { master: GainNode; gains: Record<BgmVoiceName, GainNode> } | null = null
let bgmVolume = 0.5
let bgmMuted = false
let bgmEnabled = false
let bgmToken = 0
let bgmRetryTimer: number | null = null
let bgmRetries = 0
let nextVoiceId = 1
const desiredBed: { bed: Exclude<BgmBed, 'hold'>; endgame: boolean } = { bed: 'silent', endgame: false }
const bgmVoices: Record<BgmVoiceName, BgmVoice | null> = { standby: null, match: null, endgame: null }
const bgmRamps: Record<BgmVoiceName, BgmRamp> = {
  standby: { from: 0, to: 0, start: 0, end: 0 },
  match: { from: 0, to: 0, start: 0, end: 0 },
  endgame: { from: 0, to: 0, start: 0, end: 0 },
}
const bgmReleaseTokens: Record<BgmVoiceName, number> = { standby: 0, match: 0, endgame: 0 }
const bgmReleasePending: Record<BgmVoiceName, boolean> = { standby: false, match: false, endgame: false }
const bgmBuffers = new Map<BgmVoiceName, AudioBuffer>()
const bgmLoading = new Map<BgmVoiceName, Promise<AudioBuffer | null>>()

function getContext(): AudioContext | null {
  if (context) {
    return context
  }
  if (typeof window === 'undefined') return null
  const ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!ctor) return null
  try {
    context = new ctor()
  } catch {
    context = null
  }
  return context
}

/** Called from the first user gesture; browsers keep contexts suspended until then. */
export function unlockAudio(): void {
  const ctx = getContext()
  if (ctx && ctx.state === 'suspended' && ctx.resume) {
    void ctx.resume().catch(() => undefined)
  }
  if (bgmBus && ctx) applyBgmLevel()
  void preloadSfx()
}

function getSfxBus(ctx: AudioContext): AudioNode {
  if (!sfxBus) {
    const master = ctx.createGain(), limiter = ctx.createDynamicsCompressor()
    limiter.threshold.value = -1
    limiter.knee.value = 0
    limiter.ratio.value = 20
    limiter.attack.value = 0.002
    limiter.release.value = 0.08
    limiter.connect(master)
    master.connect(ctx.destination)
    master.gain.value = sfxMuted ? 0 : sfxVolume
    sfxBus = { master, limiter }
  }
  return sfxBus.limiter
}

export function stopSfx(scope?: SfxScope): void {
  for (const [source, kind] of [...voices]) {
    if (scope && kind !== scope) continue
    try { source.stop() } catch { /* 已自然结束。 */ }
    voices.delete(source)
  }
}

export function setSfxPreferences(volume: number, muted: boolean): void {
  sfxVolume = Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 0
  sfxMuted = muted
  if (sfxBus) sfxBus.master.gain.value = muted ? 0 : sfxVolume
  if (muted || sfxVolume === 0) stopSfx()
}

function track(source: AudioScheduledSourceNode, nodes: AudioNode[] = [], scope: SfxScope = 'battle'): void {
  if (voices.size >= 12) {
    const oldest = voices.keys().next().value
    try { oldest?.stop() } catch { /* 已结束。 */ }
    if (oldest) voices.delete(oldest)
  }
  voices.set(source, scope)
  source.onended = () => {
    voices.delete(source)
    source.disconnect()
    for (const node of nodes) node.disconnect()
  }
}

/** 只准备后续事件，不在下载或解码完成后补播先前错过的声音。 */
export async function preloadSfx(names?: readonly string[]): Promise<void> {
  const ctx = getContext()
  if (!ctx) return
  await Promise.all(Object.entries(SAMPLE_URLS).filter(([name]) => !names || names.includes(name)).map(([name, url]) => {
    if (buffers.has(name)) return Promise.resolve()
    const pending = loading.get(name)
    if (pending) return pending
    const task = fetch(url).then(response => {
      if (!response.ok) throw new Error(`音效素材加载失败：${name}`)
      return response.arrayBuffer()
    }).then(data => ctx.decodeAudioData(data)).then(buffer => {
      buffers.set(name, buffer)
    }).catch(error => {
      console.warn(`音效暂不可用：${name}`, error)
    }).finally(() => { loading.delete(name) })
    loading.set(name, task)
    return task
  }))
}

function envelope(ctx: AudioContext, start: number, peak: number, duration: number): GainNode {
  const gain = ctx.createGain()
  const attack = Math.min(0.02, duration / 4)
  gain.gain.setValueAtTime(0.0001, start)
  gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), start + attack)
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration)
  gain.connect(getSfxBus(ctx))
  return gain
}

function tone(
  ctx: AudioContext,
  start: number,
  options: { freq: number; to?: number; type?: OscillatorType; duration: number; gain: number },
): void {
  const oscillator = ctx.createOscillator()
  oscillator.type = options.type ?? 'sine'
  oscillator.frequency.setValueAtTime(options.freq, start)
  if (options.to) oscillator.frequency.exponentialRampToValueAtTime(options.to, start + options.duration)
  const gain = envelope(ctx, start, options.gain, options.duration)
  oscillator.connect(gain)
  track(oscillator, [gain])
  oscillator.start(start)
  oscillator.stop(start + options.duration + 0.03)
}

function noise(
  ctx: AudioContext,
  start: number,
  options: { duration: number; gain: number; from?: number; to?: number; filter?: BiquadFilterType },
): void {
  const length = Math.max(1, Math.floor(ctx.sampleRate * options.duration))
  const buffer = ctx.createBuffer(1, length, ctx.sampleRate)
  const data = buffer.getChannelData(0)
  for (let index = 0; index < length; index += 1) data[index] = Math.random() * 2 - 1
  const source = ctx.createBufferSource()
  source.buffer = buffer
  const filter = ctx.createBiquadFilter()
  filter.type = options.filter ?? 'lowpass'
  filter.frequency.setValueAtTime(options.from ?? 1200, start)
  if (options.to) filter.frequency.exponentialRampToValueAtTime(options.to, start + options.duration)
  source.connect(filter)
  const gain = envelope(ctx, start, options.gain, options.duration)
  filter.connect(gain)
  track(source, [filter, gain])
  source.start(start)
  source.stop(start + options.duration + 0.03)
}

const RECIPES: Record<SfxName, (ctx: AudioContext, start: number) => void> = {
  hit: (ctx, start) => {
    noise(ctx, start, { duration: 0.22, gain: 0.5, from: 1800, to: 200 })
    tone(ctx, start, { freq: 140, to: 60, type: 'square', duration: 0.18, gain: 0.32 })
  },
  miss: (ctx, start) => {
    noise(ctx, start, { duration: 0.16, gain: 0.22, filter: 'highpass', from: 900, to: 2400 })
    tone(ctx, start, { freq: 900, to: 500, type: 'sine', duration: 0.12, gain: 0.12 })
  },
  sunk: (ctx, start) => {
    noise(ctx, start, { duration: 0.5, gain: 0.5, from: 1200, to: 80 })
    tone(ctx, start, { freq: 220, to: 55, type: 'sawtooth', duration: 0.45, gain: 0.28 })
  },
  draw: (ctx, start) => {
    tone(ctx, start, { freq: 660, to: 990, type: 'triangle', duration: 0.14, gain: 0.16 })
  },
  play_card: (ctx, start) => {
    noise(ctx, start, { duration: 0.28, gain: 0.28, filter: 'bandpass', from: 400, to: 2600 })
    tone(ctx, start, { freq: 520, to: 880, type: 'triangle', duration: 0.2, gain: 0.14 })
  },
  chain: (ctx, start) => {
    tone(ctx, start, { freq: 740, type: 'square', duration: 0.1, gain: 0.15 })
    tone(ctx, start + 0.13, { freq: 990, type: 'square', duration: 0.14, gain: 0.15 })
  },
  turn: (ctx, start) => {
    tone(ctx, start, { freq: 520, type: 'sine', duration: 0.18, gain: 0.15 })
    tone(ctx, start + 0.1, { freq: 780, type: 'sine', duration: 0.22, gain: 0.12 })
  },
  win: (ctx, start) => {
    ;[523, 659, 784, 1047].forEach((freq, index) => {
      tone(ctx, start + index * 0.12, { freq, type: 'triangle', duration: 0.26, gain: 0.17 })
    })
  },
  lose: (ctx, start) => {
    ;[440, 349, 262].forEach((freq, index) => {
      tone(ctx, start + index * 0.16, { freq, type: 'sawtooth', duration: 0.34, gain: 0.13 })
    })
  },
}

export function playSfx(name: string, volume: number, muted: boolean): boolean {
  setSfxPreferences(volume, muted)
  if (sfxMuted || sfxVolume === 0 || (typeof document !== 'undefined' && document.hidden)) return false
  const sample = name === 'win' ? 'victory' : name === 'lose' ? 'defeat' : name
  if (!(sample in SAMPLE_URLS) && !(name in RECIPES)) return false
  const ctx = getContext()
  if (!ctx) return false
  // 首次快速点击时 resume 可能还未完成；仅当前手势内的界面音可同步排入。
  // 素材未解码、后台事件及无手势的战斗事件仍直接略过，不等待以后补播。
  const firstGesture = sample.startsWith('ui_') && ctx.state === 'suspended'
    && typeof navigator !== 'undefined' && navigator.userActivation?.isActive
  if (ctx.state !== 'running' && !firstGesture) return false
  if (firstGesture) void ctx.resume().catch(() => undefined)
  try {
    if (sample in SAMPLE_URLS) {
      const buffer = buffers.get(sample)
      if (!buffer) { void preloadSfx(); return false }
      const source = ctx.createBufferSource()
      const gain = ctx.createGain()
      gain.gain.value = SAMPLE_GAINS[sample] ?? 1
      source.buffer = buffer
      source.connect(gain)
      gain.connect(getSfxBus(ctx))
      track(source, [gain], sample.startsWith('ui_') ? 'interface' : 'battle')
      source.start(ctx.currentTime + 0.001)
      return true
    }
    RECIPES[name as SfxName](ctx, ctx.currentTime + 0.001)
    return true
  } catch {
    return false
  }
}

const BGM_VOICES: readonly BgmVoiceName[] = ['standby', 'match', 'endgame']

function clampUnit(volume: number): number {
  return Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 0
}

function applyBgmLevel(): void {
  if (!bgmBus) return
  try {
    bgmBus.master.gain.value = !bgmEnabled || bgmMuted ? 0 : bgmVolume
    if (context && context.state === 'suspended' && context.resume) {
      void context.resume().catch(() => undefined)
    }
  } catch {
    // 上下文已关闭时，下一次播放会重新建立总线。
  }
}

function ensureBgmBus(ctx: AudioContext): void {
  if (bgmBus) return
  const master = ctx.createGain()
  master.gain.value = 0
  master.connect(ctx.destination)
  const gains = {} as Record<BgmVoiceName, GainNode>
  for (const name of BGM_VOICES) {
    const gain = ctx.createGain()
    gain.gain.value = 0
    gain.connect(master)
    gains[name] = gain
  }
  bgmBus = { master, gains }
}

function rampValue(ramp: BgmRamp, time: number): number {
  if (time <= ramp.start || ramp.end <= ramp.start) return time <= ramp.start ? ramp.from : ramp.to
  if (time >= ramp.end) return ramp.to
  const t = (time - ramp.start) / (ramp.end - ramp.start)
  return ramp.from + (ramp.to - ramp.from) * t
}

function fadeBgmGain(ctx: AudioContext, name: BgmVoiceName, target: number): void {
  const ramp = bgmRamps[name]
  if (ramp.to === target) return
  const gain = bgmBus?.gains[name]
  if (!gain) return
  const now = ctx.currentTime
  const from = rampValue(ramp, now)
  gain.gain.cancelScheduledValues(now)
  gain.gain.setValueAtTime(from, now)
  if (Math.abs(target - from) < 0.0001) {
    gain.gain.setValueAtTime(target, now)
    bgmRamps[name] = { from: target, to: target, start: now, end: now }
    return
  }
  const end = now + BGM_CROSSFADE_SECONDS
  gain.gain.linearRampToValueAtTime(target, end)
  bgmRamps[name] = { from, to: target, start: now, end }
}

function keepBgmVoice(name: BgmVoiceName): void {
  bgmReleasePending[name] = false
  bgmReleaseTokens[name] += 1
}

function stopBgmVoice(name: BgmVoiceName): void {
  const voice = bgmVoices[name]
  bgmVoices[name] = null
  if (!voice) return
  try { voice.source.stop() } catch { /* 已经停过。 */ }
  try { voice.source.disconnect() } catch { /* 上下文已关闭。 */ }
}

function releaseBgmVoice(name: BgmVoiceName): void {
  if (!bgmVoices[name] || bgmReleasePending[name] || typeof window === 'undefined') return
  bgmReleasePending[name] = true
  const token = ++bgmReleaseTokens[name]
  window.setTimeout(() => {
    if (bgmReleaseTokens[name] !== token) return
    bgmReleasePending[name] = false
    if (bgmRamps[name].to > 0.001) return
    stopBgmVoice(name)
  }, Math.ceil(BGM_CROSSFADE_SECONDS * 1000) + 80)
}

function stopAllBgmVoices(): void {
  if (bgmRetryTimer !== null && typeof window !== 'undefined') {
    window.clearTimeout(bgmRetryTimer)
    bgmRetryTimer = null
  }
  for (const name of BGM_VOICES) {
    keepBgmVoice(name)
    stopBgmVoice(name)
    const gain = bgmBus?.gains[name]
    if (gain && context) {
      const now = context.currentTime
      try {
        gain.gain.cancelScheduledValues(now)
        gain.gain.setValueAtTime(0, now)
      } catch { /* 上下文已关闭。 */ }
    }
    bgmRamps[name] = { from: 0, to: 0, start: 0, end: 0 }
  }
}

function scheduleBgmRetry(): void {
  if (bgmRetryTimer !== null || typeof window === 'undefined' || bgmRetries >= 4) return
  bgmRetries += 1
  bgmRetryTimer = window.setTimeout(() => {
    bgmRetryTimer = null
    if (bgmEnabled) void runBgmTransport(++bgmToken)
  }, 700)
}

function trimBgmBuffer(ctx: AudioContext, buffer: AudioBuffer): AudioBuffer {
  const frames = trimFrameCount(buffer.length, buffer.sampleRate)
  if (frames <= 0 || frames === buffer.length) return buffer
  const trimmed = ctx.createBuffer(buffer.numberOfChannels, frames, buffer.sampleRate)
  for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
    trimmed.copyToChannel(buffer.getChannelData(channel).subarray(0, frames), channel)
  }
  return trimmed
}

function loadBgmTrack(name: BgmVoiceName): Promise<AudioBuffer | null> {
  const cached = bgmBuffers.get(name)
  if (cached) return Promise.resolve(cached)
  const pending = bgmLoading.get(name)
  if (pending) return pending
  const task = (async () => {
    const ctx = getContext()
    if (!ctx) return null
    const response = await fetch(BGM_TRACK_URLS[name])
    if (!response.ok) throw new Error(`背景音乐加载失败：${name}`)
    const encoded = await response.arrayBuffer()
    const decoded = await ctx.decodeAudioData(encoded.slice(0))
    const trimmed = trimBgmBuffer(ctx, decoded)
    bgmBuffers.set(name, trimmed)
    bgmRetries = 0
    return trimmed
  })().catch(error => {
    console.warn(`背景音乐暂不可用：${name}`, error)
    return null
  }).finally(() => { bgmLoading.delete(name) })
  bgmLoading.set(name, task)
  return task
}

function preloadBgm(): void {
  for (const name of BGM_VOICES) void loadBgmTrack(name)
}

function ensureBgmVoice(name: BgmVoiceName, buffer: AudioBuffer, offset: number, when: number): BgmVoice {
  const existing = bgmVoices[name]
  if (existing) return existing
  const ctx = getContext()
  if (!ctx || !bgmBus) throw new Error('背景音乐总线还没建立')
  const source = ctx.createBufferSource()
  source.buffer = buffer
  source.loop = true
  source.connect(bgmBus.gains[name])
  const startOffset = loopOffsetSeconds(offset, buffer.duration)
  source.start(when, startOffset)
  const voice = { id: nextVoiceId, source, startedAt: when - startOffset, buffer }
  nextVoiceId += 1
  bgmVoices[name] = voice
  return voice
}

function desiredMix(): Record<BgmVoiceName, number> {
  if (!bgmEnabled || desiredBed.bed === 'silent') return { standby: 0, match: 0, endgame: 0 }
  if (desiredBed.bed === 'standby') return { standby: 1, match: 0, endgame: 0 }
  return { standby: 0, match: 1, endgame: desiredBed.endgame ? 1 : 0 }
}

function applyBgmMix(ctx: AudioContext): void {
  const mix = desiredMix()
  for (const name of BGM_VOICES) {
    if (mix[name] > 0 && !bgmVoices[name]) mix[name] = 0
    if (mix[name] > 0) keepBgmVoice(name)
    fadeBgmGain(ctx, name, mix[name])
    if (mix[name] <= 0) releaseBgmVoice(name)
  }
}

function freshBgm(token: number): boolean {
  return bgmEnabled && token === bgmToken
}

async function runBgmTransport(token: number): Promise<void> {
  if (!freshBgm(token)) return
  const ctx = getContext()
  if (!ctx) return
  try {
    ensureBgmBus(ctx)
  } catch {
    return
  }
  if (desiredBed.bed === 'standby') {
    const buffer = await loadBgmTrack('standby')
    if (!freshBgm(token) || desiredBed.bed !== 'standby') return
    if (!buffer) { scheduleBgmRetry(); return }
    ensureBgmVoice('standby', buffer, 0, ctx.currentTime)
  } else if (desiredBed.bed === 'match') {
    const matchBuffer = await loadBgmTrack('match')
    if (!freshBgm(token) || desiredBed.bed !== 'match') return
    if (!matchBuffer) { scheduleBgmRetry(); return }
    const matchVoice = ensureBgmVoice('match', matchBuffer, 0, ctx.currentTime)
    if (desiredBed.endgame) {
      const endBuffer = await loadBgmTrack('endgame')
      if (!freshBgm(token) || desiredBed.bed !== 'match') return
      if (endBuffer && desiredBed.endgame) {
        const startAt = ctx.currentTime
        const offset = loopOffsetSeconds(startAt - matchVoice.startedAt, matchVoice.buffer.duration)
        ensureBgmVoice('endgame', endBuffer, offset, startAt)
      } else if (!endBuffer) {
        scheduleBgmRetry()
      }
    }
  }
  if (!freshBgm(token)) return
  applyBgmMix(ctx)
}

/**
 * 胜负页传入 hold：不改床，也不改终局层。
 * endgame 为 null 时保留当前层的开关（开屏同样如此）。
 */
export function setBgmScene(bed: BgmBed, endgame: boolean | null): void {
  if (bed === 'hold') return
  const nextEndgame = endgame === null ? desiredBed.endgame : endgame
  if (bed === desiredBed.bed && nextEndgame === desiredBed.endgame) return
  desiredBed.bed = bed
  desiredBed.endgame = nextEndgame
  if (bgmEnabled) void runBgmTransport(++bgmToken)
}

export function startBgm(volume: number, muted: boolean): boolean {
  bgmVolume = clampUnit(volume)
  bgmMuted = muted
  const ctx = getContext()
  if (!ctx) return false
  try {
    ensureBgmBus(ctx)
    const cold = !bgmEnabled
    bgmEnabled = true
    applyBgmLevel()
    if (cold) {
      bgmRetries = 0
      preloadBgm()
      void runBgmTransport(++bgmToken)
    }
    return true
  } catch {
    return false
  }
}

export function stopBgm(): void {
  bgmEnabled = false
  bgmToken += 1
  // 先把总线拉到 0，再停源，避免停掉时还挂着振荡器垫乐或尾巴。
  applyBgmLevel()
  stopAllBgmVoices()
}

export function isBgmRunning(): boolean {
  return bgmEnabled && BGM_VOICES.some(name => bgmVoices[name] !== null)
}

export interface BgmInspection {
  enabled: boolean
  bed: Exclude<BgmBed, 'hold'>
  endgameWanted: boolean
  voiceIds: Record<BgmVoiceName, number | null>
  positions: Record<BgmVoiceName, number | null>
  matchEndgameDistance: number | null
  bufferSeconds: Record<BgmVoiceName, number | null>
  rampTargets: Record<BgmVoiceName, number>
  masterGain: number
}

/** 给自测读取传输状态。不会启动振荡器，也不会改播放。 */
export function inspectBgm(): BgmInspection {
  const now = context?.currentTime ?? 0
  const positions = { standby: null, match: null, endgame: null } as Record<BgmVoiceName, number | null>
  const voiceIds = { standby: null, match: null, endgame: null } as Record<BgmVoiceName, number | null>
  const bufferSeconds = { standby: null, match: null, endgame: null } as Record<BgmVoiceName, number | null>
  for (const name of BGM_VOICES) {
    const voice = bgmVoices[name]
    voiceIds[name] = voice?.id ?? null
    bufferSeconds[name] = voice?.buffer.duration ?? bgmBuffers.get(name)?.duration ?? null
    positions[name] = voice ? loopOffsetSeconds(now - voice.startedAt, voice.buffer.duration) : null
  }
  const matchEndgameDistance = positions.match !== null && positions.endgame !== null
    ? loopDistanceSeconds(positions.match, positions.endgame, bgmVoices.match?.buffer.duration ?? BGM_CROSSFADE_SECONDS)
    : null
  return {
    enabled: bgmEnabled,
    bed: desiredBed.bed,
    endgameWanted: desiredBed.endgame,
    voiceIds,
    positions,
    matchEndgameDistance,
    bufferSeconds,
    rampTargets: { standby: bgmRamps.standby.to, match: bgmRamps.match.to, endgame: bgmRamps.endgame.to },
    masterGain: bgmBus?.master.gain.value ?? 0,
  }
}
