import { onBeforeUnmount, onMounted, shallowRef } from 'vue'
import { ViewingPlayback, type PlaybackSnapshot } from './playback'
import { useUiStore } from '../../stores/ui'
import { useAudioStore } from '../../stores/audio'
import { cardSound } from '../../audio/cardSounds'
import type { Json } from './types'

/** 页面只驱动本地时钟，不连接玩家状态或网络 ACK。 */
export function useViewingPlayback(onFrame?: (snapshot: PlaybackSnapshot) => void) {
  const player = new ViewingPlayback(), snapshot = shallowRef<PlaybackSnapshot>({ ...player.snapshot })
  const ui = useUiStore()
  const audio = useAudioStore()
  let previousCue: Json | null = null
  let raf = 0, mounted = false
  function tick(now: number): void {
    if (!mounted) return
    player.setReduced(ui.motion === 'reduced' || matchMedia('(prefers-reduced-motion: reduce)').matches)
    const next = player.advance(now)
    if (next.cue !== previousCue) {
      previousCue = next.cue
      if (next.cue?.stage === 'join') audio.play('play_card')
      else if (next.cue?.stage === 'card' && next.cue.first === true && Array.isArray(next.cue.chain) && next.cue.chain.length > 1) audio.play('chain')
      else if (next.cue?.stage === 'attack_tail') {
        const result = next.cue.result as Json
        audio.play(result.sunk ? 'sunk' : result.hit ? 'hit' : 'miss')
      } else if (next.cue?.stage === 'effect_tail' && next.cue.success !== false) {
        const name = cardSound(String((next.cue.effect as Json)?.card ?? ''))
        if (name) audio.play(name)
      }
    }
    const old = snapshot.value
    if (next.frame !== old.frame || next.step !== old.step || next.cue !== old.cue || next.progress !== old.progress || next.playing !== old.playing) {
      snapshot.value = { ...next }; onFrame?.(next)
    }
    raf = requestAnimationFrame(tick)
  }
  function sync(cancelAudio = true): void { if (cancelAudio) audio.stop('battle'); snapshot.value = { ...player.snapshot }; previousCue = player.snapshot.cue }
  onMounted(() => { mounted = true; raf = requestAnimationFrame(tick) })
  onBeforeUnmount(() => { mounted = false; cancelAnimationFrame(raf); player.dispose(); audio.stop('battle') })
  return { player, snapshot, sync }
}
