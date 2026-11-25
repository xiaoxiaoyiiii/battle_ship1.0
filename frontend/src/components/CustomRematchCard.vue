<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { sendCustomRematchAction } from '../realtime/customRematch'
import { getSettlementSocket } from '../realtime/settlement'
import { useCustomRematchStore } from '../stores/customRematch'
import { useUiStore } from '../stores/ui'

const rematch = useCustomRematchStore()
const ui = useUiStore()
const now = ref(Date.now())
const countdown = computed(() => rematch.remainingAt(Math.max(now.value, Date.now())))
const incoming = computed(() => rematch.state?.role === 'recipient')
const opponent = computed(() => rematch.state?.opponent_name || '上局对手')
const canReply = computed(() => !rematch.submitting && ui.connection === 'online' && countdown.value > 0)
let clock: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  clock = setInterval(() => { now.value = Date.now() }, 250)
})
onBeforeUnmount(() => {
  if (clock !== null) clearInterval(clock)
})

function reply(action: 'accept' | 'decline' | 'cancel'): void {
  void sendCustomRematchAction(getSettlementSocket(), action)
}
</script>

<template>
  <Teleport to="body">
    <aside class="rematch-card" data-testid="custom-rematch-card" aria-labelledby="custom-rematch-title">
      <div class="rematch-card__header">
        <p id="custom-rematch-title" class="rematch-card__title" role="status">
          {{ incoming ? opponent + ' 邀请你再战' : '已邀请 ' + opponent + ' 再战' }}
        </p>
        <span class="rematch-card__timer"><b data-testid="custom-rematch-countdown">{{ countdown }}</b> 秒</span>
      </div>
      <p class="rematch-card__detail">
        {{ countdown === 0 ? '邀请已超时。' : ui.connection === 'offline'
          ? '连接正在恢复，邀请截止时间不变。' : incoming && !rematch.state?.can_accept
            ? rematch.state?.message || '等双方都在线空闲后即可接受。' : incoming
              ? '接受后按上局规则直接开战。' : '等待对方接受，双方空闲时会直接开战。' }}
      </p>
      <div class="rematch-card__actions">
        <template v-if="incoming">
          <button type="button" class="button button--primary" data-testid="custom-rematch-accept"
            :disabled="!canReply || !rematch.state?.can_accept" @click="reply('accept')">接受</button>
          <button type="button" class="button button--ghost" data-testid="custom-rematch-decline"
            :disabled="!canReply" @click="reply('decline')">拒绝</button>
        </template>
        <button v-else type="button" class="button button--ghost" data-testid="custom-rematch-cancel"
          :disabled="!canReply" @click="reply('cancel')">撤回</button>
      </div>
    </aside>
  </Teleport>
</template>

<style scoped>
.rematch-card {
  position: fixed;
  z-index: calc(var(--z-overlay) - 1);
  inset: auto max(18px, env(safe-area-inset-right, 0px)) max(18px, env(safe-area-inset-bottom, 0px)) auto;
  box-sizing: border-box;
  width: min(342px, calc(100vw - 36px));
  padding: 12px 14px;
  color: var(--text-primary);
  background: var(--panel-strong, var(--panel));
  border: 1px solid color-mix(in srgb, var(--gold) 58%, var(--border-subtle));
  border-radius: var(--radius);
  box-shadow: 0 14px 34px rgb(0 0 0 / 30%);
}
.rematch-card__header, .rematch-card__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.rematch-card__header { justify-content: space-between; }
.rematch-card__title { flex: 1; min-width: 0; margin: 0; font-weight: 700; overflow-wrap: anywhere; }
.rematch-card__timer { color: var(--gold); font-variant-numeric: tabular-nums; white-space: nowrap; }
.rematch-card__detail { color: var(--text-muted); margin: 7px 0 9px; font-size: .85rem; }
.rematch-card__actions { justify-content: end; }
.rematch-card__actions .button { min-height: 36px; padding: 5px 13px; }
@media (max-width: 700px) {
  .rematch-card {
    inset: calc(var(--app-nav-h, 64px) + env(safe-area-inset-top, 0px) + 8px)
      max(8px, env(safe-area-inset-right, 0px)) auto auto;
    width: min(310px, calc(100vw - 16px));
  }
  .rematch-card__actions .button { min-height: 42px; }
}
</style>
