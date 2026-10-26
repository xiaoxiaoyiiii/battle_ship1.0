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
    <div class="task-heading"><h2 id="home-tasks-title">航海任务</h2><span v-if="signedIn && current">完成 {{ current.tasks.filter(t => t.completed).length }}/{{ current.tasks.length }}</span></div>
    <div class="task-tabs" role="tablist" aria-label="任务周期" @keydown="focusTab">
      <button v-for="(period, index) in (['daily', 'weekly'] as const)" :id="`tasks-${period}-tab`" :key="period"
        :ref="el => { if (el) tabs[index] = el as HTMLButtonElement }" type="button" role="tab"
        :aria-selected="selected === period" :tabindex="selected === period ? 0 : -1"
        :aria-controls="`tasks-${period}-panel`" @click="selected = period">{{ period === 'daily' ? '每日任务' : '每周任务' }}</button>
    </div>
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
.home-tasks { flex:0 0 auto; min-width:0; padding:18px 20px; border:1px solid var(--panel-line); border-radius:12px; background:var(--panel); }
.task-tabs { display:grid; grid-template-columns:1fr 1fr; padding:3px; gap:3px; border:1px solid var(--panel-line); border-radius:7px; background:var(--surface-sea); }
.task-tabs button { min-height:34px; border:0; border-radius:4px; background:transparent; color:var(--text-secondary); font:inherit; font-size:12px; cursor:pointer; }
.task-tabs button[aria-selected='true'] { background:var(--surface-raised); color:var(--text-primary); }
.task-tabs button:focus-visible,.task-note button:focus-visible,.task-guest button:focus-visible { outline:2px solid var(--role-action); outline-offset:2px; }
.task-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; margin:0 0 14px; }
.task-heading h2 { margin:0; font-size:16px; color:var(--text-primary); font-weight:650; }
.task-heading>span,.task-reset,.task-footnote { color:var(--text-secondary); font-size:12px; }
.task-list { list-style:none; padding:0; margin:4px 0 0; display:grid; }
.task-row { display:flex; align-items:flex-start; gap:9px; padding:16px 0; }
.task-row + .task-row { border-top:1px solid var(--panel-line); }
.task-icon { flex:0 0 18px; width:18px; padding-top:1px; color:var(--gold-strong); font-size:16px; }
.task-copy { min-width:0; flex:1; }
.task-title { display:flex; flex-wrap:wrap; gap:6px; justify-content:space-between; color:var(--text-primary); font-size:13px; line-height:1.4; }
.task-title b { font-weight:600; }
.task-title span { color:var(--role-self); white-space:nowrap; font-variant-numeric:tabular-nums; font-size:12px; }
.task-copy p { color:var(--text-secondary); margin:5px 0 10px; font-size:12px; line-height:1.55; }
.task-copy progress { appearance:none; display:block; width:100%; height:3px; border:0; border-radius:3px; overflow:hidden; background:var(--surface-raised); accent-color:var(--role-action); }
.task-copy progress::-webkit-progress-bar { background:var(--surface-raised); }
.task-copy progress::-webkit-progress-value { background:var(--role-action); border-radius:3px; }
.task-copy progress::-moz-progress-bar { background:var(--role-action); }
.task-done { color:var(--role-success,#58c9a0); }
.is-complete .task-copy progress { accent-color:var(--role-success); }
.is-complete .task-copy progress::-webkit-progress-value { background:var(--role-success); }
.is-complete .task-copy progress::-moz-progress-bar { background:var(--role-success); }
.task-reset { margin:2px 0 0; line-height:1.5; }
.task-footnote { margin:5px 0 0; line-height:1.5; }
.task-note,.task-guest { font-size:13px; color:var(--text-secondary); line-height:1.6; }
.task-guest { text-align:center; margin:10px 0 0; }
.task-note button,.task-guest button { color:var(--role-action); border:0; background:none; padding:0 3px; font:inherit; cursor:pointer; text-decoration:underline; }
@media(max-width:719px) { .home-tasks { padding:18px; } }
</style>
