<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { logoDurationMs } from './splashPolicy'

/**
 * 冷启动的 Logo 亮相层。
 *
 * 只做一件事：深色底上淡入现有的舰锚标记与游戏名，约 3 秒后交还控制权；
 * 期间点击（或按键）可以提前跳过。跳过的是 Logo 段——如果需要拼接，
 * 后续仍然会播（由 `App.vue` 决定）。
 *
 * 这里刻意不引入音效、副标题、粒子或额外的品牌元素：品牌标记与文案
 * 直接复用壳层 `App.vue` 里的 SVG 路径与 `.app-brand__title` 的现行文案。
 */
const props = defineProps<{
  /** `prefers-reduced-motion: reduce` 时为 true：时长缩短，改成静态淡入。 */
  reducedMotion?: boolean
}>()

const emit = defineEmits<{ (event: 'done', reason: 'auto' | 'skip'): void }>()

let timer = 0
let finished = false

function finish(reason: 'auto' | 'skip'): void {
  if (finished) return
  finished = true
  if (timer) window.clearTimeout(timer)
  emit('done', reason)
}

function onKeydown(): void {
  finish('skip')
}

onMounted(() => {
  timer = window.setTimeout(() => finish('auto'), logoDurationMs(Boolean(props.reducedMotion)))
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  if (timer) window.clearTimeout(timer)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div
    class="splash"
    :class="{ 'splash--still': reducedMotion }"
    data-testid="splash-logo"
    role="presentation"
    aria-hidden="true"
    @click="finish('skip')"
  >
    <div class="splash__inner">
      <span class="splash__mark">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M12 3v18M5 8l7-4 7 4M4 14h16l-3 6H7z" />
        </svg>
      </span>
      <p class="splash__title">战舰棋 · 作战室</p>
    </div>
    <p class="splash__hint">点击任意处跳过</p>
  </div>
</template>
