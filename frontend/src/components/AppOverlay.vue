<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useUiStore } from '../stores/ui'

/**
 * The one dialog primitive (ticket #42).
 *
 * Every overlay teleports to <body>, renders as a real modal dialog, claims the
 * single overlay slot in the ui store and returns focus to its trigger on close.
 * The layer prop picks the z-index token: the match-found result is token-above
 * the generic overlay, so a card archive opened during matchmaking can never
 * cover it.
 */
const props = withDefaults(
  defineProps<{
    /** Stable id used by the single-overlay guard and for data-overlay. */
    id: string
    /** Focus/stacking priority; a dialog only replaces a strictly lower one. */
    priority?: number
    layer?: 'overlay' | 'match-found'
    /** The element the dialog points at with aria-labelledby. */
    labelledby?: string
    /** Fallback accessible name when there is no visible heading id. */
    label?: string
    closeOnBackdrop?: boolean
    /** 可控显示时保留组件，让离场动画播放完。 */
    open?: boolean
    transitionName?: string
    /** Where focus goes on close; defaults to whatever was focused on mount. */
    returnFocus?: () => HTMLElement | null
  }>(),
  {
    priority: 100,
    layer: 'overlay',
    labelledby: undefined,
    label: undefined,
    closeOnBackdrop: true,
    open: true,
    transitionName: undefined,
    returnFocus: undefined,
  },
)

const emit = defineEmits<{ (event: 'close'): void }>()
const ui = useUiStore()

const panel = ref<HTMLElement | null>(null)
const shown = ref(false)
let opener: HTMLElement | null = null
let claimed = false

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function items(): HTMLElement[] {
  const root = panel.value
  if (!root) return []
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => element.offsetParent !== null || element === root,
  )
}

function close(): void {
  emit('close')
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    close()
    return
  }
  if (event.key !== 'Tab') return
  const focusable = items()
  if (!focusable.length) {
    event.preventDefault()
    panel.value?.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement as HTMLElement | null
  if (!event.shiftKey && (active === last || !panel.value?.contains(active))) {
    event.preventDefault()
    first.focus()
  } else if (event.shiftKey && (active === first || !panel.value?.contains(active))) {
    event.preventDefault()
    last.focus()
  }
}

function onBackdrop(event: MouseEvent): void {
  if (props.closeOnBackdrop && event.target === event.currentTarget) close()
}

/** Pull focus back if a stray Tab reaches the page behind the dialog. */
function onFocusIn(event: FocusEvent): void {
  const root = panel.value
  if (!root) return
  const target = event.target as Node | null
  if (target && !root.contains(target)) items()[0]?.focus()
}

async function activate(): Promise<void> {
  if (!claimed) opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  claimed = claimed || ui.claimDialog(props.id, props.priority)
  if (!claimed) {
    // A higher-priority layer owns the screen: this dialog never shows.
    emit('close')
    return
  }
  ui.registerDialogClose(props.id, close)
  document.addEventListener('focusin', onFocusIn)
  shown.value = true
  await nextTick()
  if (!shown.value) return
  const focusable = items()
  ;(focusable[0] ?? panel.value)?.focus()
}

function release(): void {
  if (shown.value && props.open) return
  document.removeEventListener('focusin', onFocusIn)
  if (claimed) {
    ui.unregisterDialogClose(props.id)
    ui.releaseDialog(props.id)
  }
  claimed = false
  const target = props.returnFocus ? props.returnFocus() : opener
  if (target && document.contains(target)) target.focus()
  opener = null
}

onMounted(() => { if (props.open) void activate() })
watch(() => props.open, (open) => {
  if (open) void activate()
  else {
    shown.value = false
    // 立即交还对话槽，后续的目标或连锁窗口不必等待动画结束。
    release()
  }
})
onBeforeUnmount(() => {
  shown.value = false
  release()
})

watch(
  () => props.priority,
  (priority) => {
    if (claimed) ui.claimDialog(props.id, priority)
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition :name="transitionName" :css="Boolean(transitionName)" :appear="Boolean(transitionName)" @after-leave="release">
    <div
      v-if="shown"
      class="app-overlay"
      :class="'app-overlay--' + layer"
      :data-overlay="id"
      :style="{ zIndex: layer === 'match-found' ? 'var(--z-match-found)' : 'var(--z-overlay)' }"
      @click="onBackdrop"
    >
      <div
        ref="panel"
        class="app-overlay__panel"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="labelledby"
        :aria-label="labelledby ? undefined : label"
        :data-testid="id"
        tabindex="-1"
        @keydown="onKeydown"
      >
        <slot />
      </div>
    </div>
    </Transition>
  </Teleport>
</template>
