import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ChainTimeline } from '../screens/game/chainAnimation'

/** 与规则状态分离的临时演出队列；不会写回连锁、手牌或计时。 */
export const useChainAnimationStore = defineStore('chain-animation', () => {
  const version = ref(0)
  const timeline = new ChainTimeline()
  let enabled = true
  let completions: Array<() => void> = []
  function finish(): void { const callbacks = completions; completions = []; callbacks.forEach(callback => callback()) }
  function whenFinished(callback: () => void): void {
    if (!enabled || Date.now() >= timeline.until) callback()
    else completions.push(callback)
  }
  const changed = (): void => { version.value += 1 }
  function update(payload: unknown): boolean {
    const stackChanged = timeline.update(payload, Date.now(), enabled)
    changed()
    return stackChanged
  }
  function resolve(payload: unknown): void {
    if (enabled) timeline.resolve(payload, Date.now())
    else timeline.clear()
    changed()
  }
  function present(payload: unknown): void {
    if (enabled) timeline.present(payload, Date.now())
    changed()
  }
  function hydrate(payload: unknown, keepPending = true): void { timeline.hydrate(payload, keepPending); changed() }
  function reset(): void { timeline.clear(); finish(); changed() }
  function setEnabled(value: boolean): void { enabled = value; if (!value) reset() }
  return { version, update, resolve, present, hydrate, reset, setEnabled, whenFinished, finish, at: (now: number) => timeline.at(now), until: () => timeline.until, awaitingResults: () => timeline.awaitingResults }
})
