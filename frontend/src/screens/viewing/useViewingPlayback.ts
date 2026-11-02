import { onBeforeUnmount, onMounted, shallowRef } from 'vue'
import { ViewingPlayback, type PlaybackSnapshot } from './playback'
import { useUiStore } from '../../stores/ui'
import { useAudioStore } from '../../stores/audio'
import { cueSounds } from './presentation'

/** 页面只驱动本地时钟，不连接玩家状态或网络 ACK。 */
export function useViewingPlayback(onFrame?: (snapshot: PlaybackSnapshot) => void) {
  const player = new ViewingPlayback(), snapshot = shallowRef<PlaybackSnapshot>({ ...player.snapshot })
  const ui = useUiStore()
  const audio = useAudioStore()
  let raf = 0, mounted = false
  function tick(now: number): void {
    if (!mounted) return
    player.setReduced(ui.motion === 'reduced' || matchMedia('(prefers-reduced-motion: reduce)').matches)
    const next = player.advance(now)
    for (const cue of player.drainCues()) for (const sound of cueSounds(cue)) audio.play(sound)
    const old = snapshot.value
    if (next.frame !== old.frame || next.step !== old.step || next.cue !== old.cue || next.progress !== old.progress || next.playing !== old.playing) {
      snapshot.value = { ...next }; onFrame?.(next)
    }
    raf = requestAnimationFrame(tick)
  }
  function sync(cancelAudio = true): void { if (cancelAudio) audio.stop('battle'); snapshot.value = { ...player.snapshot } }
  onMounted(() => { mounted = true; raf = requestAnimationFrame(tick) })
  onBeforeUnmount(() => { mounted = false; cancelAnimationFrame(raf); player.dispose(); audio.stop('battle') })
  return { player, snapshot, sync }
}
