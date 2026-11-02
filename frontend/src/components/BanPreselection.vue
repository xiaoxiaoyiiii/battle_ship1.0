<script setup lang="ts">
import { ref, watch } from 'vue'
import AppOverlay from './AppOverlay.vue'
import BanCardPicker from './BanCardPicker.vue'
import { banSelectionError, useCardBansStore } from '../stores/cardBans'
import { useAuthStore } from '../stores/auth'
const bans = useCardBansStore()
const auth = useAuthStore()
const open = ref(false)
const draft = ref<string[]>([])
const error = ref('')
function show(): void {
  if (auth.isGuest) { auth.open('login', '登录后可以按账号记住 Ban 位预选。'); return }
  draft.value = [...bans.preselection]; error.value = ''; open.value = true
}
function save(): void {
  if (!bans.rules) return
  error.value = banSelectionError(draft.value, bans.rules.pool, bans.rules.own_quota)
  if (!error.value && bans.savePreselection(draft.value)) open.value = false
}
watch(() => bans.accountId, () => { open.value = false })
</script>
<template>
  <button type="button" class="button button--ghost" data-testid="ban-preselect-open" @click="show">Ban 位预选<span v-if="bans.rules"> · {{ bans.preselection.length }}/{{ bans.rules.own_quota }}</span></button>
  <AppOverlay v-if="open" id="ban-preselect-overlay" labelledby="ban-preselect-title" @close="open = false">
    <section class="ban-preselect" data-testid="ban-preselection">
      <h2 id="ban-preselect-title">排位 Ban 位预选</h2>
      <p>按自己当前档位预选；跨档匹配时可能获得更多名额，可在开局补选。</p>
      <template v-if="bans.rules">
        <p v-if="!bans.rules.own_quota" data-testid="ban-preselection-zero">你当前档位没有预选名额；跨档匹配时按双方较高名额执行。</p>
        <BanCardPicker :pool="bans.rules.pool" :selection="draft" :quota="bans.rules.own_quota" @change="draft = $event" />
        <p v-if="error" role="alert">{{ error }}</p>
        <div class="ban-preselect__actions"><button type="button" class="button button--ghost" @click="draft = []">清空</button><button type="button" class="button" data-testid="ban-preselect-save" @click="save">保存预选</button></div>
      </template>
      <p v-else role="status">正在同步本账号的 Ban 名额…</p>
      <p v-if="bans.storageError" role="status">{{ bans.storageError }}</p>
      <button type="button" class="button button--ghost" data-testid="ban-preselect-close" @click="open = false">关闭</button>
    </section>
  </AppOverlay>
</template>
<style scoped>
:global(.app-overlay__panel[data-testid='ban-preselect-overlay']) { width: min(720px,calc(100vw - 24px)); }
.ban-preselect { width: min(680px,100%); box-sizing: border-box; padding: 22px; display: grid; gap: 14px; }
.ban-preselect h2 { margin: 0; color: var(--gold-strong); font-size: 21px; }
.ban-preselect p { margin: 0; color: var(--text-muted); font-size: 13px; line-height: 1.65; }
.ban-preselect__actions { display: flex; justify-content: flex-end; gap: 10px; }
</style>
