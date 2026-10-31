<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useChainAnimationStore } from '../../stores/chainAnimation'
import { useGameStore } from '../../stores/game'
import { useUiStore } from '../../stores/ui'
import { useAudioStore } from '../../stores/audio'
import { cardArtUrl } from '../../cards/cardArt'
import { drawChainFrame } from './chainAnimationCanvas'
import { planChainStage, type ChainStageInsets } from './chainStageLayout'
import type { ChainFrame } from './chainAnimation'

const props = defineProps<{ suspended?: boolean }>()
const animation = useChainAnimationStore(), game = useGameStore(), ui = useUiStore(), audio = useAudioStore()
const canvas = ref<HTMLCanvasElement | null>(null)
const frame = shallowRef<ChainFrame | null>(null)
const art = new Map<string, HTMLImageElement>()
let raf = 0, mounted = false
let motion: MediaQueryList | null = null
let cachedInsets: ChainStageInsets = { top: 0, right: 0, bottom: 0, left: 0 }
let cachedViewport = ''

/** 安全区由壳层暴露的 CSS 变量提供（刘海/手势区），无则按 0 处理。 */
function readInsets(): ChainStageInsets {
  const key = `${window.innerWidth}x${window.innerHeight}`
  if (key === cachedViewport) return cachedInsets
  const shell = document.querySelector('.app-shell')
  const style = shell ? getComputedStyle(shell) : null
  const read = (name: string): number => {
    const raw = style?.getPropertyValue(name) ?? ''
    const value = Number.parseFloat(raw)
    return Number.isFinite(value) ? Math.max(0, value) : 0
  }
  cachedViewport = key
  cachedInsets = {
    top: read('--app-safe-top'),
    right: read('--app-safe-right'),
    bottom: read('--app-safe-bottom'),
    left: read('--app-safe-left'),
  }
  return cachedInsets
}

function lookup(name: string): HTMLImageElement | null {
  if (art.has(name)) return art.get(name) ?? null
  const url = cardArtUrl(name)
  if (!url) return null
  const image = new Image(); image.src = url; art.set(name, image)
  return image
}
function tick(): void {
  raf = 0
  if (!mounted) return
  const next = props.suspended ? null : animation.at(Date.now())
  if (frame.value?.cue !== next?.cue) {
    frame.value = next
    if (next?.cue.kind === 'join') audio.play('play_card')
    else if (next?.cue.kind === 'success') audio.play('chain')
  }
  if (next && canvas.value) {
    const width = window.innerWidth, height = window.innerHeight, ratio = Math.min(2, window.devicePixelRatio || 1)
    if (canvas.value.width !== Math.round(width * ratio) || canvas.value.height !== Math.round(height * ratio)) {
      canvas.value.width = Math.round(width * ratio); canvas.value.height = Math.round(height * ratio)
    }
    const ctx = canvas.value.getContext('2d')
    if (ctx) {
      // 构图按可用宽高 + 安全区实时计算：旋转只影响下一帧的布局，不重挂载、不重置时间轴。
      const plan = planChainStage({ width, height, count: next.cue.cards.length, insets: readInsets() })
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      drawChainFrame(ctx, next, plan, lookup)
    }
  }
  // 绘制可能跨过截止时刻；已有画面时仍需下一帧负责移除叠层。
  if (next || Date.now() < animation.until()) raf = window.requestAnimationFrame(tick)
  else void nextTick(() => animation.finish())
}
function start(): void { if (mounted && !raf) raf = window.requestAnimationFrame(tick) }
function syncMotion(): void {
  const enabled = !document.hidden && ui.motion !== 'reduced' && !motion?.matches && ui.connection === 'online'
  animation.setEnabled(enabled)
  if (!enabled) frame.value = null
}
watch(() => animation.version, start)
watch(() => [ui.motion, ui.connection], syncMotion)
watch(() => props.suspended, () => { if (props.suspended) frame.value = null; start() })
onMounted(() => {
  mounted = true; motion = window.matchMedia('(prefers-reduced-motion: reduce)')
  animation.hydrate(game.state.chain, false); syncMotion()
  document.addEventListener('visibilitychange', syncMotion); motion.addEventListener('change', syncMotion)
  start()
})
onBeforeUnmount(() => {
  mounted = false; window.cancelAnimationFrame(raf); animation.reset()
  document.removeEventListener('visibilitychange', syncMotion); motion?.removeEventListener('change', syncMotion)
  art.clear()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="frame" class="chain-animation" data-testid="chain-animation" :data-kind="frame.cue.kind" :data-order="frame.cue.order" :data-cards="frame.cue.cards.map(card => card.name).join('|')" aria-hidden="true">
      <canvas ref="canvas" class="chain-animation__canvas"></canvas>
    </div>
  </Teleport>
</template>

<style scoped>
/* 演出高于手牌与详情浮窗，仍允许操作层和系统提示显示在上方。 */
.chain-animation { position:fixed; inset:0; z-index:var(--z-chain,90); pointer-events:none; overflow:hidden; contain:strict; }
.chain-animation__canvas { display:block; width:100%; height:100%; pointer-events:none; }
</style>
