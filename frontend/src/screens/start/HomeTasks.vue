<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
type Period = 'daily' | 'weekly'
interface Task { id: string; metric: string; title: string; description: string; target: number; current: number; completed: boolean }
interface Window { start: string; end: string; next_reset_at: number; tasks: Task[] }
interface TasksResponse { authenticated: boolean; server_time: number; timezone: string; daily: Window; weekly: Window }
const auth = useAuthStore()
const selected = ref<Period>('daily')
const data = ref<TasksResponse | null>(null)
const failed = ref(false)
const loading = ref(true)
const tabs = ref<HTMLButtonElement[]>([])
let request: AbortController | undefined
let refreshTimer: ReturnType<typeof setInterval> | undefined
let resetTimer: ReturnType<typeof setTimeout> | undefined
const current = computed(() => data.value?.[selected.value])
const signedIn = computed(() => !auth.isGuest && data.value?.authenticated === true)
const icons: Record<string, string> = { wins: '⚑', cards: '▧', ranked: '⚔' }
async function load(): Promise<void> {
  request?.abort()
  const controller = new AbortController()
  request = controller
  clearTimeout(resetTimer)
  try {
    const response = await fetch('/api/tasks', { credentials: 'same-origin', signal: controller.signal, cache: 'no-store' })
    if (!response.ok) throw new Error('任务暂时不可用')
    const body: TasksResponse = await response.json()
    if (request !== controller) return
    data.value = body; failed.value = false
    // 按服务端时间差更新，避免本机时钟偏差导致跨日不刷新。
    const seconds = Math.min(body.daily.next_reset_at, body.weekly.next_reset_at) - body.server_time
    resetTimer = setTimeout(() => { if (!document.hidden) void load() }, Math.max(1000, seconds * 1000 + 200))
  } catch {
    if (!controller.signal.aborted && request === controller) failed.value = true
  } finally {
    if (request === controller) loading.value = false
  }
}
function focusTab(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  selected.value = event.key === 'Home' ? 'daily' : event.key === 'End' ? 'weekly' : selected.value === 'daily' ? 'weekly' : 'daily'
  tabs.value[selected.value === 'daily' ? 0 : 1]?.focus()
}
function refreshVisible() { if (!document.hidden) void load() }
watch(() => auth.user?.id, () => { data.value = null; loading.value = true; void load() }, { immediate: true })
onMounted(() => {
  refreshTimer = setInterval(refreshVisible, 30000)
  document.addEventListener('visibilitychange', refreshVisible)
  window.addEventListener('focus', refreshVisible)
})
onBeforeUnmount(() => {
  request?.abort(); clearInterval(refreshTimer); clearTimeout(resetTimer)
  document.removeEventListener('visibilitychange', refreshVisible)
  window.removeEventListener('focus', refreshVisible)
})
</script>
<template>
  <section class="home-card home-tasks" data-testid="home-tasks" aria-labelledby="home-tasks-title">
    <div class="task-tabs" role="tablist" aria-label="任务周期" @keydown="focusTab">
      <button v-for="(period, index) in (['daily', 'weekly'] as const)" :id="`tasks-${period}-tab`" :key="period"
        :ref="el => { if (el) tabs[index] = el as HTMLButtonElement }" type="button" role="tab"
        :aria-selected="selected === period" :tabindex="selected === period ? 0 : -1"
        :aria-controls="`tasks-${period}-panel`" @click="selected = period">{{ period === 'daily' ? '每日任务' : '每周任务' }}</button>
    </div>
    <div class="task-heading"><h2 id="home-tasks-title">航海任务</h2><span v-if="signedIn && current">完成 {{ current.tasks.filter(t => t.completed).length }}/{{ current.tasks.length }}</span></div>
    <p v-if="loading" class="task-note" role="status">正在读取任务…</p>
    <div v-else-if="failed" class="task-note" role="status">任务暂时无法读取。<button type="button" @click="load">重试</button></div>
    <div v-else-if="current" :id="`tasks-${selected}-panel`" role="tabpanel" :aria-labelledby="`tasks-${selected}-tab`">
      <ul class="task-list">
        <li v-for="task in current.tasks" :key="task.id" class="task-row" :class="{ 'is-complete': signedIn && task.completed }" :data-testid="task.id">
          <span class="task-icon" aria-hidden="true">{{ icons[task.metric] }}</span>
          <div class="task-copy">
            <div class="task-title"><b>{{ task.title }}</b><span>{{ signedIn ? `${task.current} / ${task.target}` : `— / ${task.target}` }}</span></div>
            <p>{{ task.description }}<span v-if="signedIn && task.completed" class="task-done"> · 已完成</span></p>
            <progress :value="signedIn ? task.current : 0" :max="task.target" :aria-label="task.title" />
          </div>
        </li>
      </ul>
      <p v-if="!signedIn" class="task-guest"><button type="button" @click="auth.open('login')">登录</button>后记录任务进度</p>
      <p class="task-reset">{{ selected === 'daily' ? '每日 00:00 更新' : '每周一 00:00 更新' }} · 北京时间</p>
      <p v-if="signedIn" class="task-footnote">进度在对局结算后更新</p>
    </div>
  </section>
</template>
<style scoped>
.home-tasks { flex:0 0 auto; min-width:0; }
.task-tabs { display:grid; grid-template-columns:1fr 1fr; padding:3px; gap:3px; border:1px solid var(--panel-line); border-radius:9px; background:var(--surface-sea); }
.task-tabs button { min-height:34px; border:0; border-radius:6px; background:transparent; color:var(--text-tertiary); font:inherit; font-size:12px; cursor:pointer; }
.task-tabs button[aria-selected='true'] { background:var(--role-action); color:var(--on-accent,#fff); box-shadow:0 2px 10px color-mix(in srgb,var(--role-action) 25%,transparent); }
.task-tabs button:focus-visible,.task-note button:focus-visible,.task-guest button:focus-visible { outline:2px solid var(--role-action); outline-offset:2px; }
.task-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; margin:10px 0 6px; }
.task-heading h2 { margin:0; font-size:13px; color:var(--text-primary); }
.task-heading>span,.task-reset,.task-footnote { color:var(--text-tertiary); font-size:10px; }
.task-list { list-style:none; padding:0; margin:0; display:grid; gap:7px; }
.task-row { display:flex; align-items:center; gap:10px; padding:8px; border:1px solid var(--border-subtle); border-radius:9px; background:color-mix(in srgb,var(--surface-sea) 50%,transparent); }
.task-icon { flex:0 0 29px; width:29px; height:29px; display:grid; place-items:center; border:1px solid color-mix(in srgb,var(--gold,#c9a24c) 40%,transparent); color:var(--gold,#c9a24c); border-radius:50%; background:color-mix(in srgb,var(--gold,#c9a24c) 10%,transparent); font-size:19px; }
.task-copy { min-width:0; flex:1; }
.task-title { display:flex; gap:6px; justify-content:space-between; color:var(--text-primary); font-size:12px; line-height:1.25; }
.task-title span { white-space:nowrap; font-variant-numeric:tabular-nums; }
.task-copy p { color:var(--text-tertiary); margin:4px 0 6px; font-size:10px; line-height:1.2; }
.task-copy progress { appearance:none; display:block; width:100%; height:5px; border:0; border-radius:9px; overflow:hidden; background:var(--surface-sea); accent-color:var(--role-action); }
.task-copy progress::-webkit-progress-bar { background:var(--surface-sea); }
.task-copy progress::-webkit-progress-value { background:var(--role-action); border-radius:9px; }
.task-copy progress::-moz-progress-bar { background:var(--role-action); }
.task-done { color:var(--role-success,#58c9a0); }
.is-complete { border-color:color-mix(in srgb,var(--role-success,#58c9a0) 35%,var(--border-subtle)); }
.task-reset { text-align:center; margin:10px 0 0; }
.task-footnote { margin:5px 0 0; text-align:center; }
.task-note,.task-guest { font-size:12px; color:var(--text-tertiary); }
.task-guest { text-align:center; margin:10px 0 0; }
.task-note button,.task-guest button { color:var(--role-action); border:0; background:none; padding:0 3px; font:inherit; cursor:pointer; text-decoration:underline; }
</style>
