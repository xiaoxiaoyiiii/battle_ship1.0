<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
const canvas = ref<HTMLCanvasElement | null>(null)
let cleanup = () => {}
onMounted(() => {
  const element = canvas.value!
  const ctx = element.getContext('2d')
  if (!ctx) return
  const reduced = matchMedia('(prefers-reduced-motion: reduce)')
  let frame = 0, previous = 0, width = 0, height = 0
  // 沿用旧 main 的空心气泡、缓慢上浮和左右摇摆；按屏幕面积控制密度。
  let particles: { x: number; y: number; radius: number; speed: number; sway: number; alpha: number }[] = []
  function resize() {
    width = innerWidth; height = innerHeight
    const ratio = Math.min(devicePixelRatio || 1, 2)
    element.width = width * ratio; element.height = height * ratio
    ctx!.setTransform(ratio, 0, 0, ratio, 0, 0)
    particles = Array.from({ length: Math.min(60, Math.max(16, Math.round(width * height / 26000))) }, () => ({
      x: Math.random() * width, y: Math.random() * height, radius: 1 + Math.random() * 3,
      speed: 12 + Math.random() * 36, sway: Math.random() * Math.PI * 2, alpha: .08 + Math.random() * .25,
    }))
  }
  function draw(now: number) {
    const elapsed = Math.min((now - previous) / 1000 || 0, .05)
    previous = now
    ctx!.clearRect(0, 0, width, height)
    for (const p of particles) {
      p.y -= p.speed * elapsed; p.sway += elapsed; p.x += Math.sin(p.sway) * 18 * elapsed
      if (p.y < -10) { p.y = height + 10; p.x = Math.random() * width }
      const edge = Math.min(1, Math.max(0, p.y / 60), Math.max(0, (height - p.y) / 60))
      ctx!.beginPath(); ctx!.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
      ctx!.strokeStyle = `rgba(120, 174, 224, ${p.alpha * edge})`
      ctx!.stroke()
    }
    frame = requestAnimationFrame(draw)
  }
  function resume() {
    cancelAnimationFrame(frame); previous = 0
    if (!document.hidden && !reduced.matches) frame = requestAnimationFrame(draw)
  }
  resize(); resume()
  window.addEventListener('resize', resize)
  document.addEventListener('visibilitychange', resume)
  reduced.addEventListener('change', resume)
  cleanup = () => {
    cancelAnimationFrame(frame)
    window.removeEventListener('resize', resize)
    document.removeEventListener('visibilitychange', resume)
    reduced.removeEventListener('change', resume)
  }
})
onBeforeUnmount(() => cleanup())
</script>
<template><canvas ref="canvas" class="ocean-particles" aria-hidden="true"></canvas></template>
<style scoped>
.ocean-particles { position: fixed; inset: 0; width: 100vw; height: 100vh; pointer-events: none; z-index: 0; }
@media (prefers-reduced-motion: reduce) { .ocean-particles { display: none; } }
</style>
