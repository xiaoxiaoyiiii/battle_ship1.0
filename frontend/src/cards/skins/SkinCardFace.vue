<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getSkin } from './skinManifest'
import { createSkinFrameSource } from './skinMotion'
import type { SkinFaceContext, SkinFrameSource, SkinMotionLevel } from './skinMotion'
import { registerSkinAnimation } from './skinAnimationRuntime'
import './skin-card-face.css'

const props = withDefaults(defineProps<{
  skinId: string | null
  context?: SkinFaceContext
  width?: number
  motion?: boolean
  reducedMotion?: boolean
  alt?: string
}>(), { context: 'collection', motion: true, reducedMotion: false })

const host = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const skin = computed(() => getSkin(props.skinId))
const level = ref<SkinMotionLevel>('static')
const painted = ref(false)
const label = computed(() => props.alt ?? skin.value?.cardName ?? '未选择皮肤')
const sizeStyle = computed(() => props.width && props.width > 0 ? { width: `${props.width}px` } : undefined)
let mounted = false
let generation = 0
let animation: ReturnType<typeof registerSkinAnimation> | undefined
let resize: ResizeObserver | undefined
let source: SkinFrameSource | null = null
let sourceReady = false
let motionRequested = false
let pixelRatio = 0

function resizeCanvas() {
  if (!canvas.value || !host.value) return
  // 翻牌侧面挂载时投影宽度接近零；使用不受祖先 3D 旋转影响的布局尺寸。
  const style = window.getComputedStyle(host.value)
  pixelRatio = window.devicePixelRatio || 1
  const width = Math.max(1, Math.ceil((style.width?.endsWith('px') ? parseFloat(style.width) : host.value.clientWidth) * pixelRatio))
  const height = Math.max(1, Math.ceil((style.height?.endsWith('px') ? parseFloat(style.height) : host.value.clientHeight) * pixelRatio))
  if (canvas.value.width !== width || canvas.value.height !== height) {
    canvas.value.width = width; canvas.value.height = height
    painted.value = false
  }
}

function start() {
  generation += 1
  const current = generation
  animation?.dispose(); animation = undefined
  source = null; sourceReady = false; motionRequested = false; painted.value = false; level.value = 'static'
  if (!mounted || !host.value || !skin.value) return
  resizeCanvas()
  animation = registerSkinAnimation({
    element: host.value, tier: skin.value.tier, context: props.context,
    reducedMotion: !props.motion || props.reducedMotion,
    onLevelChange(next) {
      level.value = next
      if (next === 'static') painted.value = false
      else resizeCanvas()
    },
    onFrame(time, quality) {
      if (current !== generation || quality === 'static' || !canvas.value) return
      // 切到不同像素密度的屏幕时，布局可能不变，ResizeObserver 不一定触发。
      if (pixelRatio !== (window.devicePixelRatio || 1)) resizeCanvas()
      if (!source) {
        source = createSkinFrameSource(props.skinId)
        const loading = source
        void loading?.ready.then((ready) => { if (generation === current) sourceReady = ready })
      }
      if (!source || !sourceReady) return
      if (quality === 'full' && !motionRequested) {
        motionRequested = true
        void source.prepareMotion()
      }
      const ctx = canvas.value.getContext('2d', { alpha: false })
      if (!ctx) return
      painted.value = source.draw(ctx, { x: 0, y: 0, width: canvas.value.width, height: canvas.value.height }, time, quality)
    },
  })
}

watch(() => props.skinId, start, { flush: 'post' })
watch(() => [props.context, props.motion, props.reducedMotion], () => {
  animation?.update({ context: props.context, reducedMotion: !props.motion || props.reducedMotion })
})
watch(() => props.width, resizeCanvas, { flush: 'post' })
onMounted(() => {
  mounted = true
  if (typeof ResizeObserver !== 'undefined' && host.value) {
    resize = new ResizeObserver(resizeCanvas); resize.observe(host.value)
  }
  start()
})
onBeforeUnmount(() => {
  mounted = false; generation += 1
  animation?.dispose(); resize?.disconnect(); source = null
})
</script>

<template>
  <span ref="host" class="skin-card-face" :style="sizeStyle" :data-motion-level="level" :data-skin-id="skin?.skinId" :data-context="context">
    <img v-if="skin" class="skin-card-face__static" :src="skin.imageUrl" :alt="label" loading="lazy" decoding="async" draggable="false" />
    <span v-else class="skin-card-face__empty" role="img" :aria-label="label"></span>
    <canvas v-if="skin" ref="canvas" class="skin-card-face__motion" :class="{ 'skin-card-face__motion--ready': painted && level !== 'static' }" aria-hidden="true"></canvas>
  </span>
</template>
