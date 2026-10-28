import { SAMPLE_GAINS, SAMPLE_URLS } from './samples'

/** 音效统一走可调音量的总线；采样素材缓存解码，BGM 保持独立。 */

type SfxName =
  | 'hit' | 'miss' | 'sunk' | 'draw' | 'play_card'
  | 'chain' | 'turn' | 'win' | 'lose'

let context: AudioContext | null = null
let sfxBus: { master: GainNode; limiter: DynamicsCompressorNode } | null = null
let sfxVolume = 0.8
let sfxMuted = false
const voices = new Set<AudioScheduledSourceNode>()
const buffers = new Map<string, AudioBuffer>()
const loading = new Map<string, Promise<void>>()
let bgm: {
  master: GainNode
  filter: BiquadFilterNode
  oscillators: OscillatorNode[]
  lfo: OscillatorNode
} | null = null
let bgmVolume = 0.5
let bgmMuted = false

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
  if (bgm && ctx) applyBgm(bgmVolume, bgmMuted)
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

export function stopSfx(): void {
  for (const source of [...voices]) {
    try { source.stop() } catch { /* 已自然结束。 */ }
  }
  voices.clear()
}

export function setSfxPreferences(volume: number, muted: boolean): void {
  sfxVolume = Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 0
  sfxMuted = muted
  if (sfxBus) sfxBus.master.gain.value = muted ? 0 : sfxVolume
  if (muted || sfxVolume === 0) stopSfx()
}

function track(source: AudioScheduledSourceNode, nodes: AudioNode[] = []): void {
  if (voices.size >= 12) {
    const oldest = voices.values().next().value
    try { oldest?.stop() } catch { /* 已结束。 */ }
    if (oldest) voices.delete(oldest)
  }
  voices.add(source)
  source.onended = () => {
    voices.delete(source)
    source.disconnect()
    for (const node of nodes) node.disconnect()
  }
}

/** 只准备后续事件，不在下载或解码完成后补播先前错过的声音。 */
export async function preloadSfx(): Promise<void> {
  const ctx = getContext()
  if (!ctx) return
  await Promise.all(Object.entries(SAMPLE_URLS).map(([name, url]) => {
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
  if (!ctx || ctx.state !== 'running') return false
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
      track(source, [gain])
      source.start(ctx.currentTime + 0.001)
      return true
    }
    RECIPES[name as SfxName](ctx, ctx.currentTime + 0.001)
    return true
  } catch {
    return false
  }
}

function applyBgm(volume: number, muted: boolean): void {
  bgmVolume = volume
  bgmMuted = muted
  if (!bgm) return
  try {
    bgm.master.gain.value = muted ? 0 : Math.max(0, Math.min(1, volume)) * 0.2
    if (context && context.state === 'suspended' && context.resume) {
      void context.resume().catch(() => undefined)
    }
  } catch {
    // A closed context is not a user-visible failure; the next start recreates it.
  }
}

export function startBgm(volume: number, muted: boolean): boolean {
  if (bgm) {
    applyBgm(volume, muted)
    return true
  }
  const ctx = getContext()
  if (!ctx) return false
  try {
    const master = ctx.createGain()
    master.gain.value = muted ? 0 : Math.max(0, Math.min(1, volume)) * 0.2
    master.connect(ctx.destination)

    const filter = ctx.createBiquadFilter()
    filter.type = 'lowpass'
    filter.frequency.value = 800
    filter.connect(master)

    const oscillators = [110, 164.81, 220].map((freq, index) => {
      const oscillator = ctx.createOscillator()
      oscillator.type = index === 2 ? 'triangle' : 'sine'
      oscillator.frequency.value = freq
      const gain = ctx.createGain()
      gain.gain.value = 0.3
      oscillator.connect(gain)
      gain.connect(filter)
      oscillator.start()
      return oscillator
    })

    const lfo = ctx.createOscillator()
    lfo.frequency.value = 0.06
    const lfoGain = ctx.createGain()
    lfoGain.gain.value = 200
    lfo.connect(lfoGain)
    lfoGain.connect(filter.frequency)
    lfo.start()

    bgm = { master, filter, oscillators, lfo }
    applyBgm(volume, muted)
    return true
  } catch {
    bgm = null
    return false
  }
}

export function stopBgm(): void {
  if (!bgm) return
  try {
    for (const oscillator of bgm.oscillators) oscillator.stop()
    bgm.lfo.stop()
    bgm.master.disconnect()
  } catch {
    // Already stopped/closed.
  }
  bgm = null
}

export function isBgmRunning(): boolean {
  return bgm !== null
}
