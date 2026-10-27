<script setup lang="ts">
import { computed } from 'vue'
import { useHomeStore } from '../../stores/home'
import { useAuthStore } from '../../stores/auth'
const home = useHomeStore()
const auth = useAuthStore()
interface Badge { id: string; name: string; desc: string; unlocked: boolean; unlocked_at?: number }

const badges = computed(() => ((home.profile?.achievements ?? []) as Badge[]).slice().sort((a,b) => Number(b.unlocked) - Number(a.unlocked) || (b.unlocked_at ?? 0) - (a.unlocked_at ?? 0)).slice(0,4))
const career = computed(() => {
  const p = auth.isGuest ? null : home.profile
  const wins = typeof p?.wins === 'number' ? p.wins : null
  const losses = typeof p?.losses === 'number' ? p.losses : null
  const total = wins !== null && losses !== null ? wins + losses : null
  return [['胜率',total ? Math.round(wins! / total * 100) + '%' : '—'], ['总对局', total ?? '—'], ['当前连胜',p?.current_streak ?? '—'], ['最长连胜',p?.longest_streak ?? '—']]
})
</script>
<template>
  <div class="home-progress">
    <section class="progress-panel progress-panel--career">
      <h2>生涯战绩</h2>
      <dl class="career-grid">
        <div v-for="[label,value] in career" :key="String(label)">
          <dd>{{ value }}</dd>
          <dt>{{ label }}</dt>
        </div>
      </dl>
    </section>
    <section class="progress-panel">
      <h2>最近解锁</h2>
      <p v-if="auth.isGuest">登录后记录你的成就与荣誉。</p>
      <p v-else-if="!badges.length">{{ home.profileFailed ? '成就暂时无法读取' : home.profileLoaded ? '尚未解锁成就，开始第一场对局吧' : '正在读取成就…' }}</p>
      <ul v-else class="badge-list" tabindex="0" aria-label="最近的成就">
        <li v-for="badge in badges" :key="badge.id">
          <span class="badge-icon" aria-hidden="true">⚓</span>
          <div><b>{{ badge.name }}</b><small>{{ badge.desc }}</small><span class="badge-state" :class="{unlocked:badge.unlocked}">{{ badge.unlocked ? '已解锁' : '未解锁' }}</span></div>
        </li>
      </ul>
    </section>
  </div>
</template>
<style scoped>
.home-progress { display:grid; gap:16px; min-width:0; }
.progress-panel { min-width:0; padding:18px 20px; border:1px solid var(--panel-line); border-radius:12px; background:var(--panel); }
h2 { margin:0 0 16px; color:var(--text-primary); font-size:16px; font-weight:650; }
p,small,dt { color:var(--text-secondary); font-size:12px; line-height:1.6; }
p { margin:0; }
ul { list-style:none; padding:0; margin:0; }
.badge-list { max-height:146px; overflow-y:auto; overscroll-behavior:contain; scrollbar-width:thin; }
.badge-list li { display:flex; align-items:flex-start; gap:10px; padding:11px 0; }
.badge-list li:first-child { padding-top:0; }
.badge-list li + li { border-top:1px solid var(--panel-line); }
.badge-list li>div { flex:1; min-width:0; }
.badge-list b,.badge-list small,.badge-state { display:block; }
.badge-list b { color:var(--text-primary); font-size:13px; font-weight:600; }
.badge-list small { margin-top:3px; overflow-wrap:anywhere; }
.badge-icon { display:grid; place-items:center; flex:0 0 36px; width:36px; height:36px; border:1px solid color-mix(in srgb,var(--gold) 40%,var(--panel-line)); border-radius:50%; color:var(--gold-strong); background:color-mix(in srgb,var(--gold) 10%,var(--panel)); font-size:19px; }
.badge-state { margin-top:3px; color:var(--text-secondary); font-size:12px; }
.badge-state.unlocked { color:var(--gold-strong); }
.career-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px 12px; margin:0; }
.career-grid div { min-width:0; }
.career-grid dd { margin:0 0 4px; color:var(--text-primary); font-size:26px; line-height:1.1; font-weight:700; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.career-grid dt { font-size:12px; }
@media(min-width:1024px) and (min-height:700px) {
  .home-progress { flex:1; min-height:0; gap:12px; grid-template-rows:auto minmax(0,1fr); }
  .progress-panel { min-height:0; padding:14px 16px; display:flex; flex-direction:column; }
  h2 { flex-shrink:0; margin-bottom:10px; }
  .career-grid { gap:14px 12px; }
  .career-grid dd { font-size:24px; }
  .badge-list { min-height:0; max-height:none; }
}
@media(min-width:1024px) and (min-height:700px) and (max-height:820px) {
  .home-progress { gap:10px; }
  .progress-panel { padding:10px 14px; }
  h2 { margin-bottom:8px; font-size:15px; }
  .career-grid { gap:8px 10px; }
  .career-grid dd { font-size:21px; }
}
@media(max-width:719px) {
  .progress-panel { padding:18px; }
  .badge-list { max-height:220px; }
}
</style>
