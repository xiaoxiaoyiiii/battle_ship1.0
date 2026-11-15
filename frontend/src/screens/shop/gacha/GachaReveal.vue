<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type { ComponentPublicInstance, CSSProperties } from 'vue'
import { getSkin, getSkinForCard } from '../../../cards/skins/skinManifest'
import SkinCardFace from '../../../cards/skins/SkinCardFace.vue'
import '../../../cards/skins/skin-effects.css'
import {
  createGachaRevealFlow,
  getGachaAppearance,
  summarizeGachaResults,
} from './gachaFlow'
import type { GachaPull } from './gachaFlow'
import { createGachaAudio } from './gachaAudio'
import './gacha-reveal.css'

const props = defineProps<{
  results: readonly GachaPull[]
  /** 服务器返回的抽后碎片余额；展示动画不会再次累加这个数字。 */
  shardBalance?: number
  /** 可选的碎片飞入目标，不传时使用组件自己的碎片栏。 */
  shardTarget?: HTMLElement | null
  /** 传 true 额外遵守游戏内的减少动态设置；系统偏好始终生效。 */
  reducedMotion?: boolean
}>()

// skip 只展开所有卡，父组件应继续保留本组件；done 表示用户已点击收下。
const emit = defineEmits<{ done: []; skip: [] }>()
const panel = ref<HTMLElement | null>(null)
const shardAnchor = ref<HTMLElement | null>(null)
const doneButton = ref<HTMLButtonElement | null>(null)
const cardElements: Array<HTMLElement | null> = []
const announcement = ref('')
let media: MediaQueryList | undefined
let motionRootObserver: MutationObserver | undefined
let previousFocus: HTMLElement | null = null
let disposed = false
let batch = 0
let flightId = 0
const uiTimers = new Set<ReturnType<typeof setTimeout>>()
const audio = createGachaAudio()
const chargeSounds = new Map<number, () => void>()
const pointers = new Map<number, { index: number; x: number; y: number; touch: boolean }>()
const keyboardCards = new Set<number>()
let silentReveal = false

function systemReducedMotion() {
  return (typeof document !== 'undefined' && document.documentElement?.dataset.motion === 'reduced')
    || typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const flow = createGachaRevealFlow(props.results, {
  reducedMotion: props.reducedMotion === true || systemReducedMotion(),
  onChange: (snapshot) => { state.value = snapshot },
  onDone: () => emit('done'),
  onSkip: () => emit('skip'),
})
const state = shallowRef(flow.snapshot)

const cards = computed(() => state.value.cards.map((card, index) => {
  const result = props.results[index]
  const appearance = getGachaAppearance(result, card.exposed)
  // 卡面在翻到中点之后才进入 DOM，卡背期间不查询或预加载具体皮肤。
  const skin = card.exposed && result.kind !== 'shard'
    ? (result.skinId ? getSkin(result.skinId) : undefined)
      ?? (result.cardKey ? getSkinForCard(result.cardKey) : undefined)
    : undefined
  const name = card.exposed ? result.cardName ?? skin?.cardName ?? '霓虹赛博皮肤' : ''
  const isNew = card.exposed && result.kind !== 'shard' && result.isNew
  const duplicate = card.exposed && result.kind !== 'shard' && !result.isNew
  const gained = card.exposed ? result.shardsGained : 0
  const resultLabel = result.kind === 'shard'
    ? `潮汐碎片，获得 ${gained} 个`
    : `${appearance.label}，${name}，${isNew ? '首次获得' : `已拥有，获得 ${gained} 个潮汐碎片`}`
  return {
    index,
    phase: card.phase,
    exposed: card.exposed,
    tone: appearance.tone,
    label: appearance.label,
    name,
    imageUrl: skin?.imageUrl,
    skinId: skin?.skinId,
    effectClass: skin?.effectClass,
    isNew,
    duplicate,
    gained,
    particles: card.exposed && card.phase === 'turning' && !state.value.reducedMotion
      ? (result.kind === 'shard' ? 5 : result.kind === 'limited' ? 42 : 18) : 0,
    ariaLabel: card.exposed
      ? `第 ${index + 1} 张，${resultLabel}`
      : `第 ${index + 1} 张卡，${appearance.label}，${card.phase === 'charging' ? '正在蓄力，松开翻牌' : card.phase === 'turning' ? '正在翻开' : '点击或按住翻开'}`,
  }
}))

const summary = computed(() => summarizeGachaResults(props.results))
const exposedCount = computed(() => state.value.cards.filter((card) => card.exposed).length)
const visibleShards = computed(() => props.results.reduce((total, result, index) =>
  total + (state.value.cards[index]?.exposed ? result.shardsGained : 0), 0))
const balanceLabel = computed(() => props.shardBalance === undefined ? '本次碎片' : '潮汐碎片')
const displayBalance = computed(() => props.shardBalance ?? visibleShards.value)
const title = computed(() => {
  switch (state.value.stage) {
    case 'scanning': return '聆听深海回响'
    case 'rising': return '回响正在凝聚'
    case 'ready': return '翻开你的回响'
    case 'summary': return props.results.length ? '回响已抵达' : '暂无抽取结果'
  }
})

interface ShardFlight { id: number; style: CSSProperties }
const flights = shallowRef<ShardFlight[]>([])

function clearUiTimers() {
  batch += 1
  uiTimers.forEach((timer) => clearTimeout(timer))
  uiTimers.clear()
  flights.value = []
}

async function flyShards(index: number) {
  const result = props.results[index]
  if (state.value.reducedMotion || result.kind === 'shard' || result.isNew || result.shardsGained <= 0) return
  const currentBatch = batch
  await nextTick()
  if (disposed || batch !== currentBatch) return
  const origin = cardElements[index]?.getBoundingClientRect()
  const target = (props.shardTarget?.isConnected ? props.shardTarget : shardAnchor.value)?.getBoundingClientRect()
  if (!origin || !target) return
  const created: ShardFlight[] = []
  const count = Math.min(12, result.shardsGained)
  for (let particle = 0; particle < count; particle += 1) {
    const x = origin.left + origin.width * (0.35 + particle / Math.max(count, 1) * 0.3)
    const y = origin.top + origin.height * 0.75
    created.push({
      id: ++flightId,
      style: {
        left: `${x}px`,
        top: `${y}px`,
        '--gacha-flight-x': `${target.left + target.width / 2 - x}px`,
        '--gacha-flight-y': `${target.top + target.height / 2 - y}px`,
        animationDelay: `${particle * 55}ms`,
      },
    })
  }
  flights.value = [...flights.value, ...created]
  const ids = new Set(created.map((flight) => flight.id))
  const timer = setTimeout(() => {
    uiTimers.delete(timer)
    if (!disposed && batch === currentBatch) flights.value = flights.value.filter((flight) => !ids.has(flight.id))
  }, 900 + count * 55)
  uiTimers.add(timer)
}

function setCardElement(index: number, element: Element | ComponentPublicInstance | null) {
  cardElements[index] = element instanceof HTMLElement ? element : null
}

function particleStyle(particle: number, count: number): CSSProperties {
  const angle = particle / count * Math.PI * 2
  const reach = 52 + (particle % 5) * 14
  return {
    '--gacha-particle-x': `${Math.cos(angle) * reach}px`,
    '--gacha-particle-y': `${Math.sin(angle) * reach}px`,
    '--gacha-particle-angle': `${particle * 47}deg`,
    animationDelay: `${particle % 4 * 18}ms`,
  }
}

function clearInteraction() {
  pointers.clear()
  keyboardCards.clear()
  chargeSounds.forEach((stop) => stop())
  chargeSounds.clear()
  audio.stopAll()
}

function skip() {
  clearInteraction()
  silentReveal = true
  flow.skip()
  silentReveal = false
}

function onCardClick(index: number, event?: MouseEvent) {
  // pointer 手势已在 down/up 处理；原生 click 只作为读屏/程序激活入口。
  if (!event || event.detail === 0) flow.reveal(index)
}

function onPointerDown(index: number, event: PointerEvent) {
  if (event.button !== 0 || !flow.press(index)) return
  pointers.set(event.pointerId, { index, x: event.clientX, y: event.clientY, touch: event.pointerType === 'touch' })
  ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
}

function onPointerCancel(event: PointerEvent) {
  const pointer = pointers.get(event.pointerId)
  if (!pointer) return
  pointers.delete(event.pointerId)
  flow.cancel(pointer.index)
}

function onPointerMove(event: PointerEvent) {
  const pointer = pointers.get(event.pointerId)
  if (pointer?.touch && Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 12) onPointerCancel(event)
}

function onPointerUp(event: PointerEvent) {
  const pointer = pointers.get(event.pointerId)
  if (!pointer) return
  pointers.delete(event.pointerId)
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const inside = event.clientX >= rect.left && event.clientX <= rect.left + rect.width
    && event.clientY >= rect.top && event.clientY <= rect.top + rect.height
  if (inside) flow.release(pointer.index)
  else flow.cancel(pointer.index)
}

function onCardKeyDown(index: number, event: KeyboardEvent) {
  if (event.key !== ' ' && event.key !== 'Enter') return
  event.preventDefault()
  if (!event.repeat && flow.press(index)) keyboardCards.add(index)
}

function onCardKeyUp(index: number, event: KeyboardEvent) {
  if (event.key !== ' ' && event.key !== 'Enter') return
  event.preventDefault()
  if (keyboardCards.delete(index)) flow.release(index)
}

function onCardBlur(index: number) {
  if (keyboardCards.delete(index)) flow.cancel(index)
}

watch(() => state.value.cards, (next, previous) => {
  next.forEach((card, index) => {
    const before = previous[index]
    if (card.phase !== 'charging') {
      chargeSounds.get(index)?.()
      chargeSounds.delete(index)
    }
    if (silentReveal) return
    const shard = props.results[index]?.kind === 'shard'
    if (card.phase === 'charging' && before?.phase !== 'charging') {
      chargeSounds.set(index, audio.play('charge', { loop: true, level: shard ? 0.2 : 0.52, rate: shard ? 1.5 : 1 }))
    }
    if ((card.phase === 'turning' || card.phase === 'open') && before?.phase === 'charging') {
      audio.play('flip', { level: shard ? 0.23 : 0.72 })
    }
    if (card.exposed && !before?.exposed && !shard) {
      audio.play(props.results[index].kind === 'limited' ? 'limited' : 'legendary', { level: 0.85 })
    }
  })
}, { flush: 'sync' })

watch(() => state.value.cards, (next, previous) => {
  next.forEach((card, index) => {
    if (card.exposed && !previous[index]?.exposed) announcement.value = cards.value[index].ariaLabel
    if (card.phase === 'open' && previous[index]?.phase !== 'open') void flyShards(index)
  })
})

watch(() => state.value.stage, async (stage) => {
  const currentBatch = batch
  await nextTick()
  if (disposed || currentBatch !== batch) return
  if (stage === 'summary') {
    announcement.value = props.results.length
      ? `全部回响已揭示，首次获得 ${summary.value.newSkinCount} 款皮肤，获得 ${summary.value.shardsGained} 个潮汐碎片。点击收下完成。`
      : '暂无抽取结果，可以点击完成返回。'
    doneButton.value?.focus()
  } else if (stage === 'ready' && document.activeElement === panel.value) {
    cardElements.find((element, index) => element && state.value.cards[index].phase === 'hidden')?.focus()
  }
})

watch(() => props.results, () => {
  clearInteraction()
  clearUiTimers()
  announcement.value = ''
  flow.reset(props.results)
  void nextTick(() => panel.value?.focus())
}, { deep: true, flush: 'sync' })

function updateMotion() {
  flow.setReducedMotion(props.reducedMotion === true || systemReducedMotion())
  if (flow.snapshot.reducedMotion) clearUiTimers()
}
watch(() => props.reducedMotion, updateMotion)

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    if (state.value.stage === 'summary') { audio.stopAll(); flow.finish() }
    else skip()
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const controls = Array.from(panel.value.querySelectorAll<HTMLElement>('button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])'))
    .filter((element) => element.tabIndex >= 0 && element.getClientRects().length > 0)
  const first = controls[0]
  const last = controls[controls.length - 1]
  if (!first) {
    event.preventDefault()
    panel.value.focus()
  } else if (!controls.includes(document.activeElement as HTMLElement)) {
    // 翻牌后卡仍持焦点，但已经退出 Tab 顺序；此时接管浏览器的默认跳转。
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus()
  } else if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.value)) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  media = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-reduced-motion: reduce)') : undefined
  media?.addEventListener('change', updateMotion)
  if (typeof MutationObserver !== 'undefined' && document.documentElement) {
    motionRootObserver = new MutationObserver(updateMotion)
    motionRootObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] })
  }
  if (state.value.stage === 'summary') doneButton.value?.focus()
  else panel.value?.focus()
})

onBeforeUnmount(() => {
  const shouldRestoreFocus = panel.value?.contains(document.activeElement) || document.activeElement === document.body
  disposed = true
  clearInteraction()
  audio.dispose()
  flow.dispose()
  clearUiTimers()
  media?.removeEventListener('change', updateMotion)
  motionRootObserver?.disconnect()
  if (shouldRestoreFocus && previousFocus?.isConnected) previousFocus.focus()
})
</script>

<template>
  <Teleport to="body">
  <section
    ref="panel"
    class="gacha-reveal"
    :class="[`gacha-reveal--${state.stage}`, { 'gacha-reveal--single': results.length === 1, 'gacha-reveal--reduced': state.reducedMotion }]"
    role="dialog"
    aria-modal="true"
    aria-label="潮汐回响"
    tabindex="-1"
    @keydown="onKeydown"
  >
    <div class="gacha-reveal__depth" aria-hidden="true"></div>
    <div class="gacha-reveal__sonar" aria-hidden="true"><span></span></div>
    <div v-if="state.flash" class="gacha-reveal__flash" aria-hidden="true"></div>

    <header class="gacha-reveal__header">
      <div ref="shardAnchor" class="gacha-reveal__wallet" :aria-label="`${balanceLabel} ${displayBalance}`">
        <span class="gacha-reveal__shard-symbol" aria-hidden="true"></span>
        <span>{{ balanceLabel }}<strong>{{ displayBalance }}</strong></span>
      </div>
      <button v-if="state.stage !== 'summary'" class="gacha-reveal__skip" type="button" @click="skip()">跳过动画<kbd>Esc</kbd></button>
      <button v-else class="gacha-reveal__skip" type="button" @click="audio.stopAll(); flow.finish()">关闭结果<kbd>Esc</kbd></button>
    </header>

    <main class="gacha-reveal__content">
      <div class="gacha-reveal__heading">
        <span class="gacha-reveal__heading-line" aria-hidden="true"></span>
        <h1>{{ title }}</h1>
        <p v-if="state.stage === 'ready'">{{ exposedCount }} / {{ results.length }}<span>任选一张 · 点击或按住蓄力</span></p>
        <p v-else-if="state.stage === 'summary' && results.length">霓虹赛博<span>{{ summary.totalCount }} 次回响</span></p>
        <p v-else-if="results.length">潮汐深处，光正在靠近</p>
        <p v-else>返回卡池后再次抽取。</p>
      </div>

      <ol v-if="cards.length" class="gacha-reveal__cards" aria-label="本次抽取的卡牌">
        <li v-for="card in cards" :key="card.index" class="gacha-reveal__slot">
          <button
            :ref="(element) => setCardElement(card.index, element)"
            class="gacha-card"
            :class="[`gacha-card--${card.tone}`, `gacha-card--${card.phase}`, { 'gacha-card--exposed': card.exposed }]"
            :style="{ '--gacha-card-order': card.index }"
            type="button"
            :disabled="state.stage === 'scanning' || state.stage === 'rising' || state.completed"
            :aria-disabled="state.stage !== 'ready' || card.phase !== 'hidden'"
            :tabindex="state.stage === 'ready' && card.phase === 'hidden' ? 0 : -1"
            :aria-label="card.ariaLabel"
            @click="onCardClick(card.index, $event)"
            @pointerdown="onPointerDown(card.index, $event)"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerCancel"
            @lostpointercapture="onPointerCancel"
            @keydown="onCardKeyDown(card.index, $event)"
            @keyup="onCardKeyUp(card.index, $event)"
            @blur="onCardBlur(card.index)"
          >
            <span class="gacha-card__edge" aria-hidden="true"></span>
            <span v-if="card.particles" class="gacha-card__burst" :class="`gacha-card__burst--${card.tone}`" aria-hidden="true">
              <i class="gacha-card__burst-core"></i>
              <i v-for="ring in (card.tone === 'limited' ? 3 : 1)" :key="`ring-${ring}`" class="gacha-card__burst-ring" :style="{ '--gacha-ring-order': ring - 1 }"></i>
              <i v-for="particle in card.particles" :key="particle" class="gacha-card__particle" :style="particleStyle(particle, card.particles)"></i>
            </span>
            <span class="gacha-card__turn" aria-hidden="true">
              <span class="gacha-card__face gacha-card__back">
                <span class="gacha-card__back-orbit"></span>
                <span class="gacha-card__back-mark"><i></i><i></i><i></i></span>
                <span class="gacha-card__back-name">潮汐回响</span>
                <span class="gacha-card__back-tide"></span>
              </span>
              <span v-if="card.exposed" class="gacha-card__face gacha-card__front">
                <SkinCardFace v-if="card.skinId" class="gacha-card__art" :skin-id="card.skinId" context="reveal" :reduced-motion="state.reducedMotion" alt="" />
                <span v-else-if="card.tone === 'shard'" class="gacha-card__shard-art"><i></i><b>×{{ card.gained }}</b></span>
                <span v-else class="gacha-card__missing-art"><i></i></span>
                <span v-if="card.tone === 'shard'" class="gacha-card__shard-label">潮汐碎片</span>
              </span>
            </span>
          </button>
          <div class="gacha-card__caption" :class="{ 'gacha-card__caption--visible': card.exposed }" aria-hidden="true">
            <span v-if="card.isNew" class="gacha-card__new">NEW</span>
            <small>{{ card.exposed ? card.label : '\u00a0' }}</small>
            <em v-if="card.duplicate">已拥有 · 碎片 +{{ card.gained }}</em>
            <em v-else-if="card.isNew">首次获得</em>
            <em v-else-if="card.exposed">碎片 +{{ card.gained }}</em>
          </div>
        </li>
      </ol>

      <footer class="gacha-reveal__footer">
        <template v-if="state.stage === 'summary'">
          <p v-if="results.length" class="gacha-reveal__summary">
            <span v-if="summary.newSkinCount">新皮肤 <strong>{{ summary.newSkinCount }}</strong></span>
            <span v-if="summary.duplicateSkinCount">重复皮肤 <strong>{{ summary.duplicateSkinCount }}</strong></span>
            <span>潮汐碎片 <strong>+{{ summary.shardsGained }}</strong></span>
          </p>
          <button ref="doneButton" class="gacha-reveal__done" type="button" :disabled="state.completed" @click="audio.stopAll(); flow.finish()">{{ results.length ? '收下回响' : '完成' }}</button>
        </template>
        <p v-else class="gacha-reveal__hint">{{ state.stage === 'ready' ? '每一道回响，都由你亲手唤醒。' : '正在寻找属于你的回响…' }}</p>
      </footer>
    </main>
    <p class="gacha-reveal__sr-only" role="status" aria-live="polite" aria-atomic="true">{{ announcement }}</p>
    <Teleport to="body">
      <div v-if="flights.length" class="gacha-shard-flight-layer" aria-hidden="true">
        <span v-for="flight in flights" :key="flight.id" class="gacha-shard-flight" :style="flight.style"></span>
      </div>
    </Teleport>
  </section>
  </Teleport>
</template>
