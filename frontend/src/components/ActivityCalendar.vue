<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppOverlay from './AppOverlay.vue'
interface Season { id: string; starts_at: number; ends_at: number; claim_ends_at: number }
const emit = defineEmits<{ close: [] }>()
const seasons = ref<Season[]>([])
const recurring = ref<{ name: string; schedule: string }[]>([])
const error = ref('')
const loading = ref(true)
function date(n: number): string { return new Date(n * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }
onMounted(async () => {
  try {
    const response = await fetch('/api/activity-calendar')
    if (!response.ok) throw new Error('暂时无法读取日历，请稍后重试')
    const body = await response.json()
    seasons.value = body.seasons
    recurring.value = body.recurring
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '日历读取失败' }
  finally { loading.value = false }
})
</script>
<template>
  <AppOverlay id="activity-calendar" label="活动日历" @close="emit('close')"><section class="activity-calendar" data-testid="activity-calendar-content"><header><h2>海域日历</h2><button class="button button--ghost" data-testid="activity-calendar-close" @click="emit('close')">关闭</button></header><p>所有时间均为沪时；排位季与通行证季同步。</p><p v-if="loading" role="status">正在读取…</p><p v-if="error" role="alert">{{ error }}</p><p v-else-if="!loading && !seasons.length">正式开服后公布首季日期，当前暂无赛季安排。</p><ol><li v-for="season in seasons" :key="season.id"><h3>{{ season.id }}</h3><p>开季：{{ date(season.starts_at) }}<br>结季锁榜：{{ date(season.ends_at) }}<br>通行证领奖截止：{{ date(season.claim_ends_at) }}</p></li></ol><div v-for="item in recurring" :key="item.name" class="activity-calendar__event"><b>{{ item.name }}</b><span>{{ item.schedule }}</span></div><p class="activity-calendar__hint">排位季末奖励在新季开始后投递到邮箱，附件领取期为新季起 14 天。</p></section></AppOverlay>
</template>
<style scoped>
.activity-calendar { --text-strong:var(--text-primary); }
.activity-calendar { box-sizing:border-box; width:min(620px,calc(100vw - 32px)); max-height:85dvh; overflow:auto; padding:clamp(20px,4vw,32px); background:var(--surface-sea); color:var(--text-strong); border:1px solid var(--border-subtle); border-radius:14px; }.activity-calendar header { display:flex; justify-content:space-between; align-items:center; gap:16px; }.activity-calendar h2 { margin:0; }.activity-calendar p { color:var(--text-muted); line-height:1.8; font-size:14px; }.activity-calendar ol { padding-left:20px; }.activity-calendar li { padding-left:8px; }.activity-calendar h3 { font-size:16px; }.activity-calendar__event { display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; padding:16px 0; border-top:1px solid var(--border-subtle); font-size:14px; }.activity-calendar__event span { color:var(--text-muted); }.activity-calendar__hint { border-top:1px solid var(--border-subtle); padding-top:14px; }
</style>
