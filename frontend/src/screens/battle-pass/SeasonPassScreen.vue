<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useBattlePassStore, type BattlePassLevel, type BattlePassTrack } from '../../stores/battlePass'

interface TaskRow { id: string; title: string; description: string; current: number; target: number; completed: boolean }
interface TaskPeriod { tasks: TaskRow[]; next_reset_at?: number; start?: string; end?: string }

const auth = useAuthStore()
const store = useBattlePassStore()
const taskState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const daily = ref<TaskPeriod | null>(null)
const weekly = ref<TaskPeriod | null>(null)
const track = ref<HTMLElement | null>(null)

const season = computed(() => store.season)
const progress = computed(() => store.progress)
const xpPercent = computed(() => {
  const total = season.value?.totalXp || 0
  return total ? Math.min(100, Math.round(progress.value.xp / total * 100)) : 0
})
const claimKeys = computed(() => new Set(store.claims.map((item) => `${item.level}:${item.track}`)))

function isClaimed(level: number, kind: BattlePassTrack): boolean { return claimKeys.value.has(`${level}:${kind}`) }
function canClaim(row: BattlePassLevel, kind: BattlePassTrack): boolean {
  if (progress.value.level < row.level || isClaimed(row.level, kind)) return false
  if (kind === 'premium' && !progress.value.premiumUnlocked) return false
  return kind === 'free' ? Boolean(row.freeRewardId) : Boolean(row.premiumRewardId)
}
function rewardLabel(row: BattlePassLevel, kind: BattlePassTrack): string {
  const type = kind === 'free' ? row.freeKind : row.premiumKind
  const id = kind === 'free' ? row.freeRewardId : row.premiumRewardId
  if (!id) return '—'
  const label = type === 'title' ? '称号' : type === 'frame' ? '头像框' : '名片底色'
  return `${label} · ${id.replaceAll('_', ' ')}`
}
function levelState(row: BattlePassLevel): string {
  if (row.level === progress.value.level) return '当前'
  if (row.level < progress.value.level) return '已达成'
  return `需要 Lv.${row.level}`
}
function claimLabel(row: BattlePassLevel, kind: BattlePassTrack): string {
  if (isClaimed(row.level, kind)) return '已领取'
  if (kind === 'premium' && !progress.value.premiumUnlocked) return '豪华轨'
  if (canClaim(row, kind)) return store.claiming === `${row.level}:${kind}` ? '领取中…' : '领取'
  return '未解锁'
}
function claim(row: BattlePassLevel, kind: BattlePassTrack): void {
  if (canClaim(row, kind)) void store.claim(row.level, kind)
}
function percent(current: number, target: number): number { return Math.min(100, Math.round(current / Math.max(1, target) * 100)) }
function taskCount(period: TaskPeriod | null): string {
  if (!period) return '—'
  return `${period.tasks.filter((task) => task.completed).length}/${period.tasks.length}`
}
async function loadTasks(): Promise<void> {
  taskState.value = 'loading'
  try {
    const response = await fetch('/api/tasks', { credentials: 'same-origin', headers: { accept: 'application/json' }, cache: 'no-store' })
    if (response.status === 401) { taskState.value = 'ready'; return }
    if (!response.ok) throw new Error('任务读取失败')
    const body = await response.json() as { daily?: TaskPeriod; weekly?: TaskPeriod }
    daily.value = body.daily || null
    weekly.value = body.weekly || null
    taskState.value = 'ready'
  } catch { taskState.value = 'error' }
}
async function load(): Promise<void> {
  await Promise.all([store.load(true), loadTasks()])
  await nextTick()
  track.value?.querySelector<HTMLElement>('[data-current="true"]')?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
}

onMounted(() => { void load() })
watch(() => auth.isGuest, () => { store.reset(); void load() })
</script>

<template>
  <section class="screen season-pass" data-screen="battle-pass" data-testid="screen-battle-pass" aria-labelledby="season-pass-title">
    <div class="season-pass__shell">
      <header class="season-pass__hero">
        <div>
          <p class="season-pass__eyebrow">深海远征 · 赛季履历</p>
          <h1 id="season-pass-title">赛季通行证</h1>
          <p class="season-pass__subtitle">完成真人排位与休闲对局，解锁属于这一季的舰队身份。</p>
        </div>
        <div v-if="season" class="season-pass__hero-state">
          <span>{{ season.state === 'claim_only' ? '领取期' : season.state === 'closed' ? '已结束' : '进行中' }}</span>
          <strong>Lv.{{ progress.level }} / {{ season.levelCap }}</strong>
        </div>
      </header>

      <div v-if="store.status === 'anonymous' || auth.isGuest" class="season-pass__login">
        <h2>登录后开始记录赛季进度</h2>
        <p>通行证经验、任务和奖励领取都绑定账号。</p>
        <button type="button" class="button button--primary" @click="auth.open('login', '登录后查看赛季通行证')">登录 / 注册</button>
      </div>
      <div v-else-if="store.status === 'loading'" class="season-pass__state">正在读取赛季目录…</div>
      <div v-else-if="store.status === 'error'" class="season-pass__state season-pass__state--error">{{ store.error || '赛季数据暂时无法读取。' }} <button type="button" class="button button--ghost" @click="load">重试</button></div>
      <div v-else-if="!season" class="season-pass__state">当前没有开放的赛季。</div>
      <template v-else>
        <section class="season-pass__summary" aria-label="赛季进度">
          <div class="season-pass__level-badge"><span>当前等级</span><strong>Lv.{{ progress.level }}</strong></div>
          <div class="season-pass__progress-main">
            <div class="season-pass__progress-copy"><b>{{ progress.xp.toLocaleString() }} XP</b><span>{{ season.totalXp.toLocaleString() }} XP</span></div>
            <div class="season-pass__progress-bar" role="progressbar" :aria-valuenow="progress.xp" :aria-valuemax="season.totalXp" aria-label="赛季经验"><i :style="{ width: xpPercent + '%' }"></i></div>
            <p>经验自动入账；奖励达到等级后手动领取。{{ progress.premiumUnlocked ? '豪华轨道已解锁。' : '豪华轨道由管理员授予。' }}</p>
          </div>
          <div class="season-pass__summary-stat"><span>赛季挑战</span><strong>{{ store.challenges.filter((item) => item.completed).length }} / {{ store.challenges.length }}</strong></div>
        </section>

        <section class="season-pass__panel season-pass__rewards" aria-labelledby="season-pass-rewards-title">
          <div class="season-pass__panel-head"><div><p class="season-pass__eyebrow">REWARD TRACK</p><h2 id="season-pass-rewards-title">等级奖励</h2></div><span>横向滑动查看 50 级</span></div>
          <div ref="track" class="season-pass__track" role="list" aria-label="赛季等级奖励">
            <article v-for="row in store.levels" :key="row.level" class="season-pass__level-card" :class="{ 'is-current': row.level === progress.level, 'is-past': row.level < progress.level }" :data-current="row.level === progress.level ? 'true' : 'false'" role="listitem">
              <div class="season-pass__level-card-head"><strong>Lv.{{ row.level }}</strong><span>{{ levelState(row) }}</span></div>
              <div class="season-pass__reward-row season-pass__reward-row--free"><span class="season-pass__reward-track">免费</span><div><b>{{ rewardLabel(row, 'free') }}</b><small v-if="row.freeRewardId">达到等级即可领取</small></div><button v-if="row.freeRewardId" type="button" class="season-pass__claim" :class="{ 'is-claimed': isClaimed(row.level, 'free') }" :disabled="!canClaim(row, 'free') || store.claiming !== null" @click="claim(row, 'free')">{{ claimLabel(row, 'free') }}</button></div>
              <div class="season-pass__reward-row season-pass__reward-row--premium"><span class="season-pass__reward-track">豪华</span><div><b>{{ rewardLabel(row, 'premium') }}</b><small v-if="row.premiumRewardId">深海主题外观奖励</small></div><button v-if="row.premiumRewardId" type="button" class="season-pass__claim" :class="{ 'is-claimed': isClaimed(row.level, 'premium') }" :disabled="!canClaim(row, 'premium') || store.claiming !== null" @click="claim(row, 'premium')">{{ claimLabel(row, 'premium') }}</button></div>
            </article>
          </div>
        </section>

        <div class="season-pass__columns">
          <section class="season-pass__panel" aria-labelledby="season-pass-tasks-title">
            <div class="season-pass__panel-head"><div><p class="season-pass__eyebrow">ROUTINE</p><h2 id="season-pass-tasks-title">任务进度</h2></div><span v-if="taskState === 'error'">读取失败</span></div>
            <div class="season-pass__task-grid">
              <div class="season-pass__task-period"><header><strong>今日任务</strong><span>{{ taskCount(daily) }}</span></header><ul><li v-for="task in daily?.tasks || []" :key="task.id" :class="{ 'is-complete': task.completed }"><div><b>{{ task.title }}</b><small>{{ task.description }}</small></div><span>{{ task.current }}/{{ task.target }}</span><i><em :style="{ width: percent(task.current, task.target) + '%' }"></em></i></li></ul><p>完成任意 2 个，获得 200 XP</p></div>
              <div class="season-pass__task-period"><header><strong>本周任务</strong><span>{{ taskCount(weekly) }}</span></header><ul><li v-for="task in weekly?.tasks || []" :key="task.id" :class="{ 'is-complete': task.completed }"><div><b>{{ task.title }}</b><small>{{ task.description }}</small></div><span>{{ task.current }}/{{ task.target }}</span><i><em :style="{ width: percent(task.current, task.target) + '%' }"></em></i></li></ul><p>完成任意 2 个，获得 800 XP</p></div>
            </div>
          </section>

          <section class="season-pass__panel" aria-labelledby="season-pass-challenges-title">
            <div class="season-pass__panel-head"><div><p class="season-pass__eyebrow">VOYAGE CHALLENGES</p><h2 id="season-pass-challenges-title">赛季挑战</h2></div><span>额外 XP</span></div>
            <ul class="season-pass__challenge-list"><li v-for="challenge in store.challenges" :key="challenge.id" :class="{ 'is-complete': challenge.completed }"><div class="season-pass__challenge-copy"><b>{{ challenge.title }}</b><span>{{ challenge.current }}/{{ challenge.target }} · +{{ challenge.xp }} XP</span><small>{{ challenge.description }}</small></div><div class="season-pass__challenge-bar"><i :style="{ width: percent(challenge.current, challenge.target) + '%' }"></i></div></li></ul>
          </section>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.season-pass { padding:28px clamp(18px, 5vw, 72px) 42px; align-items:stretch; }
.season-pass__shell { width:min(1480px,100%); margin:0 auto; }
.season-pass__hero { display:flex; align-items:end; justify-content:space-between; gap:24px; padding-bottom:24px; }
.season-pass__hero h1 { margin:0 0 8px; color:var(--text-primary); font-size:32px; letter-spacing:-.03em; }
.season-pass__eyebrow { margin:0 0 5px; color:var(--role-action); font-size:10px; letter-spacing:.16em; }
.season-pass__subtitle,.season-pass__state,.season-pass__login p { margin:0; color:var(--text-secondary); font-size:13px; line-height:1.7; }
.season-pass__hero-state { display:grid; gap:5px; min-width:150px; padding:14px 16px; border:1px solid var(--border-subtle); border-radius:10px; background:var(--surface-deck); color:var(--text-secondary); text-align:right; }
.season-pass__hero-state strong { color:var(--text-primary); font-size:22px; }
.season-pass__summary { display:grid; grid-template-columns:140px minmax(0,1fr) 150px; align-items:center; gap:22px; margin-bottom:22px; padding:18px 20px; border:1px solid var(--border-strong); border-radius:12px; background:linear-gradient(135deg,var(--surface-deck),color-mix(in srgb,var(--surface-sea) 70%,var(--surface-deck))); }
.season-pass__level-badge,.season-pass__summary-stat { display:grid; gap:5px; color:var(--text-secondary); font-size:12px; }
.season-pass__level-badge strong,.season-pass__summary-stat strong { color:var(--text-primary); font-size:25px; }
.season-pass__summary-stat { text-align:right; }
.season-pass__progress-copy { display:flex; justify-content:space-between; color:var(--text-secondary); font-size:12px; font-variant-numeric:tabular-nums; }
.season-pass__progress-copy b { color:var(--text-primary); }
.season-pass__progress-bar { height:8px; margin-top:8px; overflow:hidden; border-radius:999px; background:var(--surface-raised); }
.season-pass__progress-bar i,.season-pass__challenge-bar i,.season-pass__task-period li i em { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,var(--role-action),var(--gold)); }
.season-pass__progress-main p { margin:8px 0 0; color:var(--text-secondary); font-size:11px; }
.season-pass__panel { min-width:0; padding:20px; border:1px solid var(--border-subtle); border-radius:12px; background:color-mix(in srgb,var(--surface-deck) 90%,transparent); }
.season-pass__panel-head { display:flex; align-items:end; justify-content:space-between; gap:16px; margin-bottom:16px; }
.season-pass__panel-head h2 { margin:0; color:var(--text-primary); font-size:20px; }
.season-pass__panel-head > span { color:var(--text-secondary); font-size:11px; }
.season-pass__track { display:grid; grid-auto-flow:column; grid-auto-columns:minmax(248px,248px); gap:10px; overflow-x:auto; padding:4px 4px 12px; scroll-snap-type:x proximity; scrollbar-width:thin; }
.season-pass__level-card { display:grid; gap:9px; min-height:196px; padding:12px; border:1px solid var(--border-subtle); border-radius:9px; background:var(--surface-sea); scroll-snap-align:center; transition:border-color var(--duration-fast) var(--ease),transform var(--duration-fast) var(--ease); }
.season-pass__level-card:hover { transform:translateY(-2px); border-color:var(--border-strong); }
.season-pass__level-card.is-current { border-color:var(--role-action); box-shadow:0 0 0 2px var(--role-action-soft); }
.season-pass__level-card.is-past { opacity:.66; }
.season-pass__level-card-head { display:flex; align-items:center; justify-content:space-between; color:var(--text-secondary); font-size:11px; }
.season-pass__level-card-head strong { color:var(--text-primary); font-size:18px; }
.season-pass__reward-row { display:grid; grid-template-columns:34px minmax(0,1fr) auto; align-items:center; gap:8px; min-width:0; padding:9px; border:1px solid var(--border-subtle); border-radius:7px; }
.season-pass__reward-row--free { background:color-mix(in srgb,var(--surface-raised) 70%,transparent); }
.season-pass__reward-row--premium { border-color:color-mix(in srgb,var(--gold) 35%,var(--border-subtle)); background:color-mix(in srgb,var(--gold) 7%,var(--surface-sea)); }
.season-pass__reward-track { color:var(--text-secondary); font-size:10px; writing-mode:vertical-rl; }
.season-pass__reward-row--premium .season-pass__reward-track { color:var(--gold-strong); }
.season-pass__reward-row b,.season-pass__reward-row small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.season-pass__reward-row b { color:var(--text-primary); font-size:11px; }
.season-pass__reward-row small { margin-top:3px; color:var(--text-secondary); font-size:10px; }
.season-pass__claim { padding:4px 6px; border:1px solid var(--border-strong); border-radius:4px; color:var(--role-action); background:transparent; font:inherit; font-size:10px; white-space:nowrap; cursor:pointer; }
.season-pass__claim:disabled { color:var(--text-muted); opacity:.72; cursor:default; }
.season-pass__claim.is-claimed { border-color:color-mix(in srgb,var(--role-success) 38%,var(--border-subtle)); color:var(--role-success); }
.season-pass__columns { display:grid; grid-template-columns:minmax(0,1.18fr) minmax(320px,.82fr); gap:22px; margin-top:22px; }
.season-pass__task-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
.season-pass__task-period { padding:13px; border:1px solid var(--border-subtle); border-radius:9px; background:var(--surface-sea); }
.season-pass__task-period header { display:flex; justify-content:space-between; color:var(--text-primary); font-size:13px; }
.season-pass__task-period header span { color:var(--role-action); font-variant-numeric:tabular-nums; }
.season-pass__task-period ul,.season-pass__challenge-list { display:grid; gap:11px; margin:14px 0 0; padding:0; list-style:none; }
.season-pass__task-period li { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:3px 8px; align-items:center; }
.season-pass__task-period li div { min-width:0; }
.season-pass__task-period li b,.season-pass__task-period li small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.season-pass__task-period li b { color:var(--text-primary); font-size:11px; }
.season-pass__task-period li small { color:var(--text-secondary); font-size:10px; }
.season-pass__task-period li > span { color:var(--role-action); font-size:11px; }
.season-pass__task-period li i { grid-column:1/-1; height:4px; overflow:hidden; border-radius:999px; background:var(--surface-raised); }
.season-pass__task-period li i em { width:0; }
.season-pass__task-period li.is-complete b { color:var(--role-success); }
.season-pass__task-period > p { margin:14px 0 0; color:var(--text-secondary); font-size:10px; }
.season-pass__challenge-list li { padding:11px; border:1px solid var(--border-subtle); border-radius:8px; background:var(--surface-sea); }
.season-pass__challenge-copy { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:3px 10px; }
.season-pass__challenge-copy b { color:var(--text-primary); font-size:12px; }
.season-pass__challenge-copy span { color:var(--role-action); font-size:11px; font-variant-numeric:tabular-nums; }
.season-pass__challenge-copy small { grid-column:1/-1; color:var(--text-secondary); font-size:10px; }
.season-pass__challenge-bar { height:4px; margin-top:8px; overflow:hidden; border-radius:999px; background:var(--surface-raised); }
.season-pass__challenge-list li.is-complete { border-color:color-mix(in srgb,var(--role-success) 38%,var(--border-subtle)); }
.season-pass__challenge-list li.is-complete .season-pass__challenge-bar i { background:var(--role-success); }
.season-pass__login,.season-pass__state { padding:24px; border:1px solid var(--border-strong); border-radius:12px; background:var(--surface-deck); }
.season-pass__login h2 { margin:0 0 8px; color:var(--text-primary); font-size:19px; }
.season-pass__login .button { margin-top:16px; }
.season-pass__state--error { color:var(--role-warning); }
@media(max-width:900px) { .season-pass__summary { grid-template-columns:120px minmax(0,1fr); }.season-pass__summary-stat { grid-column:1/-1; text-align:left; }.season-pass__columns { grid-template-columns:1fr; } }
@media(max-width:620px) { .season-pass { padding:18px 14px 28px; }.season-pass__hero { align-items:flex-start; flex-direction:column; }.season-pass__hero h1 { font-size:27px; }.season-pass__hero-state { width:100%; text-align:left; }.season-pass__summary { grid-template-columns:1fr; gap:13px; }.season-pass__summary-stat { grid-column:auto; }.season-pass__task-grid { grid-template-columns:1fr; }.season-pass__panel { padding:15px; } }
@media(prefers-reduced-motion:reduce) { .season-pass__level-card { transition:none; } }
</style>
