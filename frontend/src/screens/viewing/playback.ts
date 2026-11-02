/** 本地观看时钟。状态只来自录像或观战帧，动画完成不发送玩家 ACK。 */
import { copy, frameAt } from './frame'
import type { Json, Recording, ViewFrame, ViewPacket } from './types'

interface Job { step: number; duration: number; cue?: Json; patch?: Partial<ViewFrame>; frame?: ViewFrame }
export interface PlaybackSnapshot { frame: ViewFrame | null; step: number; cue: Json | null; progress: number; playing: boolean }

function duration(cue: Json): number {
  if (cue.stage === 'join') return 800
  if (cue.stage === 'card' || cue.stage === 'card_face') return cue.first ? 1050 : 650
  const effect = cue.effect as Json | undefined
  const total = Number(effect?.duration_ms) || 1250, impact = Number(effect?.impact) || .45
  if (cue.stage === 'effect_windup') return total * impact
  if (cue.stage === 'effect_tail') return total * (1 - impact)
  return 350
}

export class ViewingPlayback {
  snapshot: PlaybackSnapshot = { frame: null, step: 0, cue: null, progress: 0, playing: false }
  private recording: Recording | null = null
  private jobs: Job[] = []
  private cursor = 0
  private elapsed = 0
  private entered = false
  private lastTime: number | null = null
  private speed = 1
  private live = false
  private reduced = false
  get pending(): number { return this.jobs.length - this.cursor }

  load(recording: Recording): void { this.dispose(); this.recording = recording; this.live = false; this.seek(0) }
  play(): void {
    if (!this.live && this.recording && !this.pending) this.seek(0)
    this.snapshot.playing = true; this.lastTime = null
  }
  pause(): void { this.snapshot.playing = false; this.lastTime = null }
  setSpeed(value: number): void { if ([1, 2, 4].includes(value)) this.speed = value }
  setReduced(value: boolean): void { this.reduced = value; if (value) this.snapshot.cue = null }

  seek(step: number): void {
    if (!this.recording) return
    const r = this.recording, index = Math.max(0, Math.min(r.steps.length - 1, Math.trunc(step)))
    this.snapshot.frame = frameAt(r, index); this.snapshot.step = index; this.snapshot.cue = null; this.snapshot.progress = 0
    this.jobs = []; this.cursor = 0; this.elapsed = 0; this.entered = false; this.lastTime = null
    for (let i = index + 1; i < r.steps.length; i++) {
      const events = r.events.filter(e => e.step === r.steps[i].i)
      if (r.version === 1) {
        this.jobs.push({ step: i, frame: frameAt(r, i), duration: 600 })
      } else {
        for (const e of events) {
          if (e.type === 'state') this.jobs.push({ step: i, patch: e.patch, duration: 0 })
          else if (e.cue) this.jobs.push({ step: i, cue: e.cue, duration: duration(e.cue) })
        }
        this.jobs.push({ step: i, duration: events.some(e => e.type === 'presentation') ? 150 : 450 })
      }
    }
  }

  enqueue(packet: ViewPacket): void {
    if (!this.live) { this.dispose(); this.live = true; this.snapshot.frame = copy(packet.frame); this.snapshot.playing = true }
    if (this.cursor > 0) { this.jobs = this.jobs.slice(this.cursor); this.cursor = 0 }
    this.jobs.push({ step: 0, frame: copy(packet.frame), duration: 0 })
    for (const cue of packet.cues) this.jobs.push({ step: 0, cue: copy(cue), duration: duration(cue) })
    if (this.pending > 32 || this.jobs.reduce((n, j) => n + j.duration, 0) > 8000) {
      this.jobs = []; this.cursor = 0; this.elapsed = 0; this.entered = false
      this.snapshot.frame = copy(packet.frame); this.snapshot.cue = null; this.snapshot.progress = 0
    }
  }

  advance(now: number): PlaybackSnapshot {
    if (!this.snapshot.playing) { this.lastTime = null; return this.snapshot }
    let delta = this.lastTime === null ? 0 : Math.max(0, now - this.lastTime) * this.speed
    this.lastTime = now
    while (this.cursor < this.jobs.length) {
      const job = this.jobs[this.cursor]
      if (!this.entered) {
        this.snapshot.step = job.step
        if (job.frame) this.snapshot.frame = copy(job.frame)
        if (job.patch && this.snapshot.frame) this.snapshot.frame = { ...this.snapshot.frame, ...copy(job.patch) }
        this.snapshot.cue = this.reduced ? null : job.cue ?? null
        this.snapshot.progress = 0; this.entered = true
      }
      const length = this.reduced && job.cue ? 0 : job.duration
      const left = Math.max(0, length - this.elapsed)
      if (delta < left) { this.elapsed += delta; this.snapshot.progress = length ? this.elapsed / length : 1; break }
      delta -= left; this.cursor += 1; this.elapsed = 0; this.entered = false
      this.snapshot.cue = null; this.snapshot.progress = 0
    }
    if (!this.live && this.cursor >= this.jobs.length) this.snapshot.playing = false
    return this.snapshot
  }

  dispose(): void {
    this.recording = null; this.jobs = []; this.cursor = 0; this.elapsed = 0; this.entered = false
    this.lastTime = null; this.live = false
    this.snapshot = { frame: null, step: 0, cue: null, progress: 0, playing: false }
  }
}
