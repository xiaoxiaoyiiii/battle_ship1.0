/** 连锁演出的纯时间轴；只消费公开卡面和服务端结果，不计算牌效。 */
export const CHAIN_ENTRY_MS = 800
export const CHAIN_FLIGHT_MS = 620
export const CHAIN_SUCCESS_MS = 550
export const CHAIN_RESOLVE_MS = 1000

export interface ChainArtCard {
  name: string
  caster: string
  order: number
  id: string
}
export interface ChainOutcome {
  negated: boolean
  failed: boolean
  negatedBy?: string
}
export interface ChainCue {
  kind: 'join' | 'success' | 'resolve'
  cards: ChainArtCard[]
  order: number
  result?: ChainOutcome
  animationId?: string
  start: number
  duration: number
}
export interface ChainFrame { cue: ChainCue; progress: number }

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}
function nameOf(value: unknown): string {
  return typeof value === 'string' ? value : String(record(value).name ?? '')
}
function parseStack(value: unknown): ChainArtCard[] {
  const source = record(value).chain
  if (!Array.isArray(source)) return []
  return source.flatMap((raw, index) => {
    const item = record(raw), name = nameOf(item.card)
    return name ? [{ name, caster: String(item.seat ?? item.player_id ?? ''), order: index + 1, id: String(item.id ?? '') }] : []
  })
}
function same(a: ChainArtCard, b: ChainArtCard): boolean {
  return a.name === b.name && a.caster === b.caster && (!a.id || !b.id || a.id === b.id)
}

export class ChainTimeline {
  private stack: ChainArtCard[] = []
  private cues: ChainCue[] = []
  private closed = true
  private lastResolution = ''

  get awaitingResults(): boolean { return !this.closed && this.stack.length > 0 }

  get until(): number {
    const last = this.cues.at(-1)
    return last ? last.start + last.duration : 0
  }

  at(now: number): ChainFrame | null {
    const cue = this.cues.find(item => now >= item.start && now < item.start + item.duration)
    return cue ? { cue, progress: (now - cue.start) / cue.duration } : null
  }

  clear(): void {
    this.stack = []; this.cues = []; this.closed = true; this.lastResolution = ''
  }

  /** 快照恢复只记录基线；同一栈的普通同步不打断正在播放的演出。 */
  hydrate(value: unknown, keepPending = false): void {
    const incoming = parseStack(value)
    // 终局快照可能先带来空栈，chain_resolved仍在同一连接后续事件里。
    if (keepPending && !incoming.length && this.awaitingResults) return
    if (incoming.length === this.stack.length && incoming.every((card, i) => same(card, this.stack[i]))) return
    this.stack = incoming; this.cues = []; this.closed = incoming.length === 0; this.lastResolution = ''
  }

  update(value: unknown, now: number, animate = true): boolean {
    const incoming = parseStack(value)
    if (!incoming.length) {
      const changed = !this.closed
      if (changed) this.clear()
      return changed
    }
    const prefix = !this.closed && this.stack.every((card, i) => incoming[i] && same(card, incoming[i]))
    const previousLength = prefix ? this.stack.length : 0
    if (!prefix) this.cues = []
    this.stack = incoming; this.closed = false; this.lastResolution = ''
    if (!animate) this.cues = []
    for (let i = previousLength; animate && i < incoming.length; i++) {
      this.append({ kind: 'join', cards: incoming.slice(0, i + 1), order: i + 1 }, now, CHAIN_ENTRY_MS)
    }
    return previousLength !== incoming.length
  }

  resolve(value: unknown, now: number): void {
    if (record(value).presented === true) { this.clear(); return }
    const source = record(value).results
    const results = Array.isArray(source) ? source.map(record).filter(item => nameOf(item.card)) : []
    if (!results.length) { this.clear(); return }
    const signature = JSON.stringify(results)
    if (this.closed && signature === this.lastResolution) return
    // 结果按服务端已确定的顺序展示；缺少接链事件时从结果恢复卡面，不推断效果。
    const known = this.stack.length === results.length && results.every((item, i) => this.stack[results.length - i - 1]?.name === nameOf(item.card))
    const cards = known ? this.stack.slice() : results.slice().reverse().map((item, i) => ({ name: nameOf(item.card), caster: String(item.caster ?? ''), order: i + 1, id: '' }))
    this.append({ kind: 'success', cards, order: cards.length }, now, CHAIN_SUCCESS_MS)
    results.forEach((item, i) => this.append({
      kind: 'resolve', cards, order: cards.length - i,
      result: { negated: Boolean(item.negated_skip), failed: item.success === false, negatedBy: String(item.negated_by ?? '') },
    }, now, CHAIN_RESOLVE_MS))
    this.stack = []; this.closed = true; this.lastResolution = signature
  }

  /** 服务端在执行牌效前请求单张展示；是否无效只采用当前项的真实标记。 */
  present(value: unknown, now: number): void {
    const payload = record(value), cards = parseStack(payload)
    if (!cards.length) return
    this.stack = cards; this.closed = false
    if (payload.first) this.append({ kind: 'success', cards, order: cards.length }, now, CHAIN_SUCCESS_MS)
    this.append({ kind: 'resolve', cards, order: Number(payload.order),
      animationId: String(payload.animation_id ?? ''),
      result: { negated: payload.negated_skip === true, failed: false, negatedBy: String(payload.negated_by ?? '') },
    }, now, CHAIN_RESOLVE_MS)
  }

  private append(cue: Omit<ChainCue, 'start' | 'duration'>, now: number, duration: number): void {
    this.cues = this.cues.filter(item => item.start + item.duration > now)
    this.cues.push({ ...cue, start: Math.max(now, this.until), duration })
  }
}
