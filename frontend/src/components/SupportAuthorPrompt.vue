<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppOverlay from './AppOverlay.vue'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { drawSupportPrompt, GITHUB_URL, markSupportPromptShown } from '../support/githubSupport'

const props = defineProps<{ matchKey: string }>()
const auth = useAuthStore()
const ui = useUiStore()
const visible = ref(false)
const remaining = ref(5)
let alive = true
let delay: ReturnType<typeof setTimeout> | null = null
let timeout: ReturnType<typeof setTimeout> | null = null
let countdown: ReturnType<typeof setInterval> | null = null
let pendingOwner: string | null = null

function close(): void {
  visible.value = false
  pendingOwner = null
  if (delay !== null) clearTimeout(delay)
  if (timeout !== null) clearTimeout(timeout)
  if (countdown !== null) clearInterval(countdown)
  delay = timeout = countdown = null
}

function showWhenAvailable(): void {
  if (!alive || ui.activeDialog || pendingOwner === null) return
  markSupportPromptShown(pendingOwner)
  pendingOwner = null
  visible.value = true
  remaining.value = 5
  countdown = setInterval(() => { remaining.value = Math.max(0, remaining.value - 1) }, 1000)
  timeout = setTimeout(close, 5000)
}

async function tryShow(): Promise<void> {
  if (!alive || ui.activeDialog) return
  const owner = auth.user?.id || 'guest'
  if (!drawSupportPrompt(owner, props.matchKey)) return
  if (auth.user) {
    try {
      const response = await fetch('/api/support/prompt', { method: 'POST', credentials: 'same-origin' })
      if (!response.ok) return
      const body = await response.json() as { show?: boolean }
      if (!alive) return
      if (body.show !== true) {
        markSupportPromptShown(owner)
        return
      }
    } catch { return }
  }
  pendingOwner = owner
  showWhenAvailable()
}

watch(() => ui.activeDialog, showWhenAvailable)
onMounted(() => {
  // 先让结算结果与奖励动画呈现，提醒不抢占其它弹窗。
  delay = setTimeout(() => { void tryShow() }, 1100)
})
onBeforeUnmount(() => { alive = false; close() })
</script>

<template>
  <AppOverlay v-if="visible" id="support-author-prompt" :priority="30" labelledby="support-author-title" @close="close">
    <section class="support-prompt">
      <button type="button" class="support-prompt__close" aria-label="关闭支持作者提醒" data-testid="support-prompt-close" @click="close">×</button>
      <svg class="support-prompt__star" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="m12 3 2.8 5.7 6.3.9-4.5 4.4 1.1 6.2-5.7-3-5.7 3 1.1-6.2-4.5-4.4 6.3-.9L12 3Z" />
      </svg>
      <h2 id="support-author-title">喜欢这片海域？</h2>
      <p>如果战舰棋让你玩得开心，欢迎去 GitHub 为作者点一颗星。谢谢你的支持！</p>
      <a :href="GITHUB_URL" target="_blank" rel="noopener noreferrer" class="button" data-testid="support-prompt-github" @click="close">前往 GitHub</a>
      <small class="support-prompt__countdown" data-testid="support-prompt-countdown">{{ remaining }} 秒后自动关闭</small>
    </section>
  </AppOverlay>
</template>

<style scoped>
:global(.app-overlay[data-overlay='support-author-prompt'] .app-overlay__panel) { width:min(412px, calc(100vw - 32px)); box-sizing:border-box; padding:24px; }
.support-prompt { position:relative; width:100%; box-sizing:border-box; padding:12px 14px 6px; text-align:center; }
.support-prompt__close { position:absolute; top:-12px; right:-10px; width:32px; height:32px; border:0; border-radius:var(--radius-sm); color:var(--text-secondary); background:transparent; font-size:24px; cursor:pointer; }
.support-prompt__close:hover { color:var(--text); background:var(--surface-raised); }
.support-prompt__close:focus-visible { outline:2px solid var(--role-action); outline-offset:2px; }
.support-prompt__star { display:block; width:48px; height:48px; margin:0 auto 14px; color:var(--gold); }
.support-prompt__star path { stroke:currentColor; stroke-width:1.25; stroke-linejoin:round; fill:var(--gold-soft); }
.support-prompt h2 { margin:0; color:var(--text); font-size:23px; font-weight:700; }
.support-prompt p { margin:13px 0 22px; color:var(--text-secondary); font-size:14px; line-height:1.85; }
.support-prompt .button { width:100%; box-sizing:border-box; }
.support-prompt__countdown { display:block; margin-top:13px; color:var(--text-tertiary); font-size:12px; }
@media(max-width:420px) { .support-prompt { padding-inline:0; } .support-prompt h2 { font-size:21px; } }
</style>
