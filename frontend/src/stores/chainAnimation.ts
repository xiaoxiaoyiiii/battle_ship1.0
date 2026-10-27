import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ChainTimeline } from '../screens/game/chainAnimation'

/** 与规则状态分离的临时演出队列；不会写回连锁、手牌或计时。 */
export const useChainAnimationStore = defineStore('chain-animation', () => {
  const version = ref(0)
  const timeline = new ChainTimeline()
  let enabled = true
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
  function hydrate(payload: unknown, keepPending = true): void { timeline.hydrate(payload, keepPending); changed() }
  function reset(): void { timeline.clear(); changed() }
  function setEnabled(value: boolean): void { enabled = value; if (!value) reset() }
  return { version, update, resolve, hydrate, reset, setEnabled, at: (now: number) => timeline.at(now), until: () => timeline.until, awaitingResults: () => timeline.awaitingResults }
})
