import { onBeforeUnmount, onMounted, shallowRef } from 'vue'
import { ViewingPlayback, type PlaybackSnapshot } from './playback'
import { useUiStore } from '../../stores/ui'

/** 页面只驱动本地时钟，不连接玩家状态或网络 ACK。 */
export function useViewingPlayback(onFrame?: (snapshot: PlaybackSnapshot) => void) {
  const player = new ViewingPlayback(), snapshot = shallowRef<PlaybackSnapshot>({ ...player.snapshot })
  const ui = useUiStore()
  let raf = 0, mounted = false
  function tick(now: number): void {
    if (!mounted) return
    player.setReduced(ui.motion === 'reduced' || matchMedia('(prefers-reduced-motion: reduce)').matches)
    const next = player.advance(now)
    snapshot.value = { ...next }
    onFrame?.(next)
    raf = requestAnimationFrame(tick)
  }
  function sync(): void { snapshot.value = { ...player.snapshot } }
  onMounted(() => { mounted = true; raf = requestAnimationFrame(tick) })
  onBeforeUnmount(() => { mounted = false; cancelAnimationFrame(raf); player.dispose() })
  return { player, snapshot, sync }
}
