<script setup lang="ts">
import { computed } from 'vue'
import type { DailyChallengeView } from './dailyChallenge'
const props = defineProps<{ view: DailyChallengeView | null; busy: boolean; error: string }>()
defineEmits<{ start: []; refresh: [] }>()
const labels = { available: '可挑战', in_progress: '挑战进行中', completed: '今日已完成', failed: '今日已失败', unavailable: '今日暂无', unauthorized: '登录后可参与' }
const label = computed(() => props.view ? labels[props.view.status] : '正在读取今日挑战…')
const canStart = computed(() => ['available', 'in_progress'].includes(props.view?.status || ''))
</script>

<template>
  <section class="daily-challenge-panel" data-testid="daily-challenge-panel" aria-labelledby="daily-challenge-title">
    <header><span>每日挑战 · {{ view?.date || '战术残局' }}</span><button class="lp-link" :disabled="busy" @click="$emit('refresh')">刷新</button></header>
    <h2 id="daily-challenge-title">{{ view?.puzzle?.name || '战术残局' }}</h2>
    <p class="daily-challenge-meta">高难 · 大师 AI <span>无突变 · 无 Ban</span></p>
    <p class="daily-challenge-status" data-testid="daily-challenge-status" role="status">{{ label }}</p>
    <p v-if="view?.status === 'unavailable'" class="daily-challenge-note">今日暂未安排关卡，稍后再来看看。</p>
    <p v-else-if="view?.status === 'completed'" class="daily-challenge-note">本日挑战已完成，明日再来迎战。</p>
    <p v-else-if="view?.status === 'failed'" class="daily-challenge-note">今天的机会已用完，明日再来挑战。</p>
    <div class="daily-challenge-rewards"><span>通关奖励</span><b>潮汐徽记 +{{ view?.rewards.tide ?? 30 }}</b><b>通行证 XP +{{ view?.rewards.xp ?? 40 }}</b></div>
    <p class="daily-challenge-note">每天仅 1 次，失败不可重开。北京时间 0 点换关，当日未结束的挑战随之截止。</p>
    <p v-if="error" class="daily-challenge-error" role="alert">{{ error }}</p>
    <button v-if="canStart" class="button lp-primary" data-testid="daily-challenge-start" :disabled="busy" @click="$emit('start')">{{ busy ? '正在进入…' : view?.status === 'in_progress' ? '继续挑战' : '开始挑战' }}</button>
    <p v-else-if="view?.status === 'unauthorized'" class="daily-challenge-note">请先登录账号，挑战次数和奖励会保存在你的账号中。</p>
  </section>
</template>

<style scoped>
:global(.app-overlay__panel[data-testid='daily-challenge-dialog']) { width:fit-content; max-width:calc(100vw - 24px); padding:0; }
.daily-challenge-panel { width:min(500px,calc(100vw - 48px)); max-width:100%; min-width:0; padding:26px; display:grid; gap:16px; color:var(--text-primary); box-sizing:border-box; }
header { display:flex; align-items:center; justify-content:space-between; gap:16px; color:var(--role-action); font-size:12px; }
h2 { margin:0; font-size:26px; line-height:1.3; overflow-wrap:anywhere; }
p { margin:0; }
.daily-challenge-meta { font-size:12px; color:var(--gold); display:flex; gap:12px; flex-wrap:wrap; }
.daily-challenge-meta span { color:var(--text-secondary); }
.daily-challenge-status { padding:18px 0; border-block:1px solid var(--border-subtle); color:var(--role-action); font-size:20px; font-weight:700; }
.daily-challenge-rewards { display:flex; flex-wrap:wrap; gap:8px 16px; font-size:13px; }
.daily-challenge-rewards span { flex-basis:100%; color:var(--text-secondary); }
.daily-challenge-rewards b { color:var(--gold); }
.daily-challenge-note { color:var(--text-secondary); font-size:12px; line-height:1.8; }
.daily-challenge-error { color:var(--role-danger); font-size:13px; line-height:1.6; }
.button { justify-content:center; }
@media(max-width:480px) { .daily-challenge-panel { padding:18px; gap:12px; } h2 { font-size:22px; } }
@media(max-height:480px) { .daily-challenge-panel { width:min(640px,calc(100vw - 48px)); padding:14px; gap:8px; } h2 { font-size:21px; } .daily-challenge-status { padding:10px 0; font-size:18px; } .daily-challenge-note { font-size:11px; line-height:1.5; } }
</style>
