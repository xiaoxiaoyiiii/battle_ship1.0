<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useCardDrawStore, type DrawFlight } from '../../stores/cardDraw'
import { useGameStore } from '../../stores/game'
import { useUiStore } from '../../stores/ui'
import { cardArtUrl } from '../../cards/cardArt'

const draws = useCardDrawStore(), game = useGameStore(), ui = useUiStore()
const deck = ref<HTMLElement | null>(null)
const active = ref<DrawFlight | null>(null)
const style = ref<Record<string, string>>({})
const face = computed(() => {
  const flight = active.value
  if (!flight || flight.discard || flight.player !== game.state.player_id) return null
  return cardArtUrl(String(game.state.hand[flight.index]?.name ?? ''))
})
let raf = 0, mounted = false
let media: MediaQueryList | null = null
function enabled(): boolean { return !document.hidden && ui.motion !== 'reduced' && !media?.matches }
function play(): void {
  if (!mounted || active.value) return
  const next = draws.queue.find(item => item.room === game.state.room_id)
  if (!next) return
  if (!enabled()) { draws.reset(); return }
  active.value = next
  const source = deck.value?.getBoundingClientRect()
  const mine = next.player === game.state.player_id
  const target = document.querySelector(next.discard ? '[data-testid="game-discard"]' : mine ? '[data-testid="game-hand"]' : '[data-testid="game-opponent-avatar"]')?.getBoundingClientRect()
  const fromX = (source?.left ?? 30) + (source?.width ?? 44) / 2, fromY = (source?.top ?? 200) + (source?.height ?? 60) / 2
  const toX = target ? target.left + target.width / 2 : window.innerWidth / 2
  const toY = target ? target.top + Math.min(85, target.height / 2) : window.innerHeight - 100
  const started = performance.now()
  const tick = (now: number): void => {
    const progress = Math.min(1, (now - started) / 650), ease = 1 - Math.pow(1 - progress, 3)
    const x = fromX + (toX - fromX) * ease, y = fromY + (toY - fromY) * ease - Math.sin(progress * Math.PI) * 95
    const scale = mine ? 0.65 + 0.65 * Math.sin(progress * Math.PI / 2) : 0.85 - 0.55 * progress
    style.value = { transform: `translate(${x - 36}px, ${y - 51}px) rotate(${(1 - progress) * (mine ? -16 : 20)}deg) scale(${scale})`, opacity: String(progress > .88 ? (1 - progress) / .12 : 1) }
    if (progress < 1) raf = requestAnimationFrame(tick)
    else { draws.complete(next.id); active.value = null; play() }
  }
  raf = requestAnimationFrame(tick)
}
function resetMotion(): void {
  if (!enabled()) { cancelAnimationFrame(raf); active.value = null; draws.reset() }
  else play()
}
watch(() => draws.queue.length, play)
watch(() => ui.motion, resetMotion)
onMounted(() => {
  mounted = true; media = matchMedia('(prefers-reduced-motion: reduce)')
  document.addEventListener('visibilitychange', resetMotion); media.addEventListener('change', resetMotion)
  play()
})
onBeforeUnmount(() => {
  mounted = false; cancelAnimationFrame(raf); draws.reset()
  document.removeEventListener('visibilitychange', resetMotion); media?.removeEventListener('change', resetMotion)
})
</script>

<template>
  <div class="draw-deck" data-testid="game-deck" :aria-label="'共享牌堆，剩余 ' + game.state.deck_count + ' 张'">
    <div ref="deck" class="draw-deck__back"><span>⚓</span></div>
    <span>共享牌堆 <b data-testid="game-deck-count">{{ game.state.deck_count }}</b></span>
  </div>
  <Teleport to="body">
    <div v-if="active" class="draw-flight" data-testid="draw-animation" :data-flight="active.id" :data-owner="active.player === game.state.player_id ? 'self' : 'opponent'" :style="style" aria-hidden="true">
      <img v-if="face" :src="face" alt="" />
      <span v-else>⚓</span>
    </div>
  </Teleport>
</template>

<style scoped>
.draw-deck { display:flex; align-items:center; gap:12px; color:var(--muted); font-size:13px; }
.draw-deck b { color:var(--text); font-size:17px; margin-left:5px; font-variant-numeric:tabular-nums; }
.draw-deck__back,.draw-flight { display:grid; place-items:center; color:#95d9e8; border:1px solid #8bafbf; border-radius:5px; background:repeating-linear-gradient(45deg,#102c42 0 5px,#15364d 5px 6px); box-shadow:inset 0 0 0 3px #0b1b2c,inset 0 0 0 4px #536c7b; }
.draw-deck__back { width:32px; height:44px; margin:3px 0 5px; box-shadow:3px 3px 0 #1c3448,5px 5px 0 #5a7280,inset 0 0 0 3px #0b1b2c; }
.draw-flight { position:fixed; left:0; top:0; width:72px; height:102px; z-index:9100; pointer-events:none; will-change:transform,opacity; font-size:32px; box-shadow:0 0 22px #69d6ed55; }
.draw-flight img { width:100%; height:100%; object-fit:fill; border-radius:4px; }
@media(max-width:600px) { .draw-deck { gap:8px; font-size:11px; } .draw-deck__back { width:25px; height:35px; } }
</style>
