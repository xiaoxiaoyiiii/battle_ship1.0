/** 只消费服务器结果；本模块不抽取皮肤、不扣费，也不发放碎片。 */
export interface GachaPull {
  readonly index: number
  readonly kind: 'shard' | 'legendary' | 'limited'
  readonly skinId: string | null
  readonly cardKey: string | null
  readonly cardName: string | null
  readonly isNew: boolean
  readonly shardsGained: number
}

export type GachaResult = GachaPull

export type GachaStage = 'scanning' | 'rising' | 'ready' | 'summary'
export type GachaCardPhase = 'hidden' | 'turning' | 'open'

export interface GachaCardState {
  readonly phase: GachaCardPhase
  readonly exposed: boolean
}

export interface GachaRevealSnapshot {
  readonly stage: GachaStage
  readonly cards: readonly GachaCardState[]
  readonly flash: boolean
  readonly reducedMotion: boolean
  readonly completed: boolean
}

export interface GachaRevealOptions {
  readonly reducedMotion?: boolean
  readonly onChange?: (snapshot: GachaRevealSnapshot) => void
  readonly onSkip?: () => void
  readonly onDone?: () => void
}

export interface GachaRevealFlow {
  readonly snapshot: GachaRevealSnapshot
  reveal(index: number): boolean
  skip(): boolean
  finish(): boolean
  reset(results: readonly GachaResult[]): void
  setReducedMotion(reduced: boolean): void
  dispose(): void
}

/** 未揭示时不返回 skinId、卡名、限定档位或 NEW 标记。 */
export function getGachaAppearance(result: GachaResult, exposed: boolean) {
  if (!exposed) {
    return result.kind === 'shard'
      ? { tone: 'shard', label: '灰蓝回响' } as const
      : { tone: 'charged', label: '青紫回响' } as const
  }
  switch (result.kind) {
    case 'shard': return { tone: 'shard', label: '潮汐碎片' } as const
    case 'legendary': return { tone: 'legendary', label: '传说皮肤' } as const
    case 'limited': return { tone: 'limited', label: '限定皮肤' } as const
  }
}

export function summarizeGachaResults(results: readonly GachaResult[]) {
  return {
    totalCount: results.length,
    skinCount: results.filter((result) => result.kind !== 'shard').length,
    newSkinCount: results.filter((result) => result.kind !== 'shard' && result.isNew === true).length,
    duplicateSkinCount: results.filter((result) => result.kind !== 'shard' && result.isNew === false).length,
    shardsGained: results.reduce((total, result) => total + result.shardsGained, 0),
  }
}

/** 每次 reset 开始一轮；skip 只揭示，finish 才通知父级可以关闭。 */
export function createGachaRevealFlow(
  initialResults: readonly GachaResult[],
  options: GachaRevealOptions = {},
): GachaRevealFlow {
  let results = initialResults.map((result) => ({ ...result }))
  let reducedMotion = options.reducedMotion === true
  let disposed = false
  let flashSeen = false
  let skipped = false
  let generation = 0
  const timers = new Set<ReturnType<typeof setTimeout>>()

  function initialSnapshot(): GachaRevealSnapshot {
    return {
      stage: results.length === 0 ? 'summary' : reducedMotion ? 'ready' : 'scanning',
      cards: results.map(() => ({ phase: 'hidden', exposed: false })),
      flash: false,
      reducedMotion,
      completed: false,
    }
  }

  let snapshot = initialSnapshot()

  function publish(update: Partial<GachaRevealSnapshot>) {
    if (disposed) return
    snapshot = { ...snapshot, ...update }
    options.onChange?.(snapshot)
  }

  function clearTimers() {
    generation += 1
    timers.forEach((timer) => clearTimeout(timer))
    timers.clear()
  }

  function after(delay: number, callback: () => void) {
    const scheduledGeneration = generation
    const timer = setTimeout(() => {
      timers.delete(timer)
      if (!disposed && scheduledGeneration === generation) callback()
    }, delay)
    timers.add(timer)
  }

  function begin() {
    if (snapshot.stage !== 'scanning') return
    after(1000, () => publish({ stage: 'rising' }))
    after(1600, () => publish({ stage: 'ready' }))
  }

  function changeCard(index: number, state: GachaCardState) {
    const cards = snapshot.cards.map((card, current) => current === index ? state : card)
    publish({ cards, stage: cards.every((card) => card.phase === 'open') ? 'summary' : 'ready' })
  }

  begin()

  return {
    get snapshot() { return snapshot },

    reveal(index) {
      if (disposed || snapshot.completed || snapshot.stage !== 'ready' || !Number.isInteger(index)) return false
      if (snapshot.cards[index]?.phase !== 'hidden') return false
      if (reducedMotion) {
        changeCard(index, { phase: 'open', exposed: true })
        return true
      }
      changeCard(index, { phase: 'turning', exposed: false })
      after(450, () => {
        changeCard(index, { phase: 'turning', exposed: true })
        if (results[index].kind === 'limited' && !flashSeen) {
          flashSeen = true
          publish({ flash: true })
          after(260, () => publish({ flash: false }))
        }
      })
      after(900, () => changeCard(index, { phase: 'open', exposed: true }))
      return true
    },

    skip() {
      if (disposed || skipped || snapshot.completed || snapshot.stage === 'summary') return false
      clearTimers()
      skipped = true
      flashSeen = true
      publish({
        cards: results.map(() => ({ phase: 'open', exposed: true })),
        stage: 'summary',
        flash: false,
      })
      options.onSkip?.()
      return true
    },

    finish() {
      if (disposed || snapshot.completed || snapshot.stage !== 'summary') return false
      clearTimers()
      publish({ completed: true, flash: false })
      options.onDone?.()
      return true
    },

    reset(nextResults) {
      if (disposed) return
      clearTimers()
      results = nextResults.map((result) => ({ ...result }))
      skipped = false
      flashSeen = false
      snapshot = initialSnapshot()
      options.onChange?.(snapshot)
      begin()
    },

    setReducedMotion(reduced) {
      if (disposed || reduced === reducedMotion) return
      reducedMotion = reduced
      if (!reduced) {
        publish({ reducedMotion: false })
        return
      }
      clearTimers()
      const cards = snapshot.cards.map((card) => card.phase === 'turning'
        ? { phase: 'open', exposed: true } as const
        : card)
      publish({
        reducedMotion: true,
        flash: false,
        cards,
        stage: cards.every((card) => card.phase === 'open') ? 'summary' : 'ready',
      })
    },

    dispose() {
      disposed = true
      clearTimers()
    },
  }
}
