<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppOverlay from './AppOverlay.vue'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import {
  CLIENT_DOWNLOAD_URLS, drawClientPromo, isBattleshipClient,
  markClientPromoShown, promoPlatform, type PromoPlatform,
} from '../support/clientPromo'

const auth = useAuthStore()
const ui = useUiStore()
const visible = ref(false)
const remaining = ref(5)
let alive = true
let delay: ReturnType<typeof setTimeout> | null = null
let timeout: ReturnType<typeof setTimeout> | null = null
let countdown: ReturnType<typeof setInterval> | null = null
let pendingOwner: string | null = null
let ready = false
let requested = false

const platform = computed<PromoPlatform>(() => promoPlatform())
const downloadUrl = computed(() => platform.value === 'android'
  ? CLIENT_DOWNLOAD_URLS.android : CLIENT_DOWNLOAD_URLS.windows)

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
  pendingOwner = null
  visible.value = true
  remaining.value = 5
  countdown = setInterval(() => { remaining.value = Math.max(0, remaining.value - 1) }, 1000)
  timeout = setTimeout(close, 5000)
}

async function tryShow(): Promise<void> {
  if (!ready || !alive || ui.activeDialog || requested) return
  requested = true
  // 客户端壳内不弹（读 UA 标识）。
  if (isBattleshipClient()) return
  const owner = auth.user?.id || 'guest'
  if (!drawClientPromo(owner)) return
  if (auth.user) {
    try {
      const response = await fetch('/api/client/promo/prompt', { method: 'POST', credentials: 'same-origin' })
      if (!response.ok) return
      const body = await response.json() as { show?: boolean }
      if (!alive) return
      if (body.show !== true) {
        markClientPromoShown(owner)
        return
      }
    } catch { return }
  }
  pendingOwner = owner
  showWhenAvailable()
}

watch(() => ui.activeDialog, () => {
  showWhenAvailable()
  void tryShow()
})
onMounted(() => {
  // 让首屏先完成渲染，提示不与其它弹窗抢占。
  delay = setTimeout(() => { ready = true; void tryShow() }, 1400)
})
onBeforeUnmount(() => { alive = false; close() })
</script>

<template>
  <AppOverlay v-if="visible" id="client-promo-prompt" :priority="31" labelledby="client-promo-title" @close="close">
    <section class="client-promo">
      <button type="button" class="client-promo__close" aria-label="关闭下载提示" data-testid="client-promo-close" @click="close">×</button>
      <svg class="client-promo__anchor" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 4v12M8 7h8M5 13a7 7 0 0 0 14 0M5 13H3m2 0a2 2 0 1 0 4 0m10 0a2 2 0 1 0-4 0m4 0h2" />
      </svg>
      <template v-if="platform === 'android' || platform === 'windows'">
        <h2 id="client-promo-title">{{ platform === 'android' ? '战舰棋手机版来啦！' : '战舰棋桌面版来啦！' }}</h2>
        <p>
          {{ platform === 'android' ? '装上手机客户端，随时随地开战。' : '装上桌面客户端，双击就玩，不再开浏览器。' }}<br />
          用账号登录客户端，即可领取：<br />
          <strong class="client-promo__reward">500 潮汐徽记 + 专属头像框「远航之环」</strong>
        </p>
        <a :href="downloadUrl" class="button" data-testid="client-promo-download" @click="close">立即下载</a>
        <button type="button" class="client-promo__later" data-testid="client-promo-later" @click="close">下次再说</button>
      </template>
      <template v-else>
        <h2 id="client-promo-title">想更像一个 App？</h2>
        <p>
          {{ platform === 'ios' ? 'iPhone 版制作中。你可以先用浏览器把战舰棋「添加到主屏幕」，一样是全屏体验。' : '客户端安装包暂未覆盖当前系统。可以先用浏览器创建本站快捷方式，一样方便。' }}
        </p>
        <button type="button" class="button" data-testid="client-promo-ok" @click="close">知道了</button>
      </template>
      <small class="client-promo__countdown" data-testid="client-promo-countdown">{{ remaining }} 秒后自动关闭</small>
    </section>
  </AppOverlay>
</template>

<style scoped>
:global(.app-overlay[data-overlay='client-promo-prompt'] .app-overlay__panel) { width:min(412px, calc(100vw - 32px)); box-sizing:border-box; padding:24px; }
.client-promo { position:relative; width:100%; box-sizing:border-box; padding:12px 14px 6px; text-align:center; }
.client-promo__close { position:absolute; top:-12px; right:-10px; width:32px; height:32px; border:0; border-radius:var(--radius-sm); color:var(--text-secondary); background:transparent; font-size:24px; cursor:pointer; }
.client-promo__close:hover { color:var(--text); background:var(--surface-raised); }
.client-promo__close:focus-visible { outline:2px solid var(--role-action); outline-offset:2px; }
.client-promo__anchor { display:block; width:48px; height:48px; margin:0 auto 14px; color:var(--role-action); }
.client-promo__anchor path { stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; }
.client-promo h2 { margin:0; color:var(--text); font-size:23px; font-weight:700; }
.client-promo p { margin:13px 0 20px; color:var(--text-secondary); font-size:14px; line-height:1.85; }
.client-promo__reward { color:var(--text); }
.client-promo .button { width:100%; box-sizing:border-box; display:inline-block; text-decoration:none; }
.client-promo__later { display:block; width:100%; margin-top:10px; padding:10px; border:0; border-radius:var(--radius-sm); color:var(--text-secondary); background:transparent; font-size:13px; cursor:pointer; }
.client-promo__later:hover { color:var(--text); background:var(--surface-raised); }
.client-promo__countdown { display:block; margin-top:13px; color:var(--text-tertiary); font-size:12px; }
@media(max-width:420px) { .client-promo { padding-inline:0; } .client-promo h2 { font-size:21px; } }
</style>
