<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useHomeStore } from '../../stores/home'
import { useAuthStore } from '../../stores/auth'
const home = useHomeStore()
const auth = useAuthStore()
interface Badge { id: string; name: string; desc: string; unlocked: boolean; unlocked_at?: number }
interface Tier { id: string; name: string }
const rules = ref<{ tiers?: Tier[]; start_points_of_tier?: Record<string, number> } | null>(null)
const failed = ref(false)
onMounted(async () => {
  try {
    const response = await fetch('/api/rank_constants')
    if (!response.ok) throw new Error('段位暂不可用')
    rules.value = await response.json()
  } catch { failed.value = true }
})
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
    <section class="progress-panel">
      <h2>最近解锁</h2>
      <p v-if="auth.isGuest">登录后记录你的成就与荣誉。</p>
      <p v-else-if="!badges.length">{{ home.profileFailed ? '成就暂时无法读取' : home.profileLoaded ? '尚未解锁成就，开始第一场对局吧' : '正在读取成就…' }}</p>
      <ul v-else class="badge-list"><li v-for="badge in badges" :key="badge.id"><span class="badge-icon">⚓</span><div><b>{{ badge.name }}</b><small>{{ badge.desc }}</small></div><span :class="{unlocked:badge.unlocked}">{{ badge.unlocked ? '已解锁' : '未解锁' }}</span></li></ul>
    </section>
    <section class="progress-panel"><h2>生涯数据</h2><dl class="career-grid"><div v-for="[label,value] in career" :key="String(label)"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl></section>
    <section class="progress-panel"><h2>段位阶梯</h2><p v-if="!rules">{{ failed ? '段位规则暂不可用' : '正在读取段位…' }}</p><ul v-else class="rank-ladder"><li v-for="tier in rules.tiers?.filter(t => typeof rules?.start_points_of_tier?.[t.id] === 'number').slice(0,4).reverse()" :key="tier.id"><span>{{ tier.name }}</span><b>{{ rules.start_points_of_tier?.[tier.id] }}+</b></li></ul></section>
  </div>
</template>
<style scoped>
.home-progress { display:grid; gap:12px; }
.progress-panel { padding:14px; border:1px solid var(--panel-line); border-radius:14px; background:var(--panel); }
h2 { margin:0 0 12px; color:var(--text-tertiary); font-size:12px; letter-spacing:.22em; }
p,small,dt { color:var(--text-tertiary); font-size:12px; line-height:1.6; }
ul { list-style:none; padding:0; margin:0; }
.badge-list li { display:flex; align-items:center; gap:8px; padding:7px 0; border-bottom:1px dashed var(--panel-line); font-size:10px; }
.badge-list li>div { flex:1; min-width:0; }.badge-list b,.badge-list small { display:block; }.badge-list b { font-size:13px; }
.badge-icon { padding:7px; border-radius:8px; background:var(--surface-raised); }.unlocked { color:var(--gold); }
.career-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:0; }.career-grid div { border:1px solid var(--panel-line); border-radius:9px; padding:9px; }dd { margin:4px 0 0; font-weight:700; }
.rank-ladder li { display:flex; justify-content:space-between; border-bottom:1px dashed var(--panel-line); padding:7px 0; color:var(--text-secondary); font-size:12px; }
</style>
