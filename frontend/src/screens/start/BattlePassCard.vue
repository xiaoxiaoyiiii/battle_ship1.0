<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useBattlePassStore } from '../../stores/battlePass'

const auth = useAuthStore()
const store = useBattlePassStore()
const season = computed(() => store.season)
const progress = computed(() => store.progress)
const xpPercent = computed(() => {
  const total = season.value?.totalXp || 0
  return total ? Math.min(100, Math.round((progress.value.xp / total) * 100)) : 0
})
const nextReward = computed(() => store.levels.find((row) => row.level > progress.value.level && (row.freeRewardId || row.premiumRewardId)))

function rewardText(row: typeof nextReward.value): string {
  if (!row) return '完成任务获得赛季经验'
  const id = row.freeRewardId || row.premiumRewardId
  const kind = row.freeKind || row.premiumKind
  const label = kind === 'title' ? '称号' : kind === 'frame' ? '头像框' : '名片底色'
  return `Lv.${row.level} · ${label} · ${id?.replaceAll('_', ' ') || '奖励'}`
}

onMounted(() => { void store.load() })
watch(() => auth.isGuest, () => { store.reset(); void store.load() })
</script>

<template>
  <section class="home-card battle-pass-mini" data-testid="battle-pass-card" aria-labelledby="battle-pass-title">
    <div class="battle-pass-mini__head">
      <div>
        <p class="battle-pass-mini__eyebrow">航海季</p>
        <h2 id="battle-pass-title" class="home-kicker">赛季通行证</h2>
      </div>
      <router-link class="battle-pass-mini__open" :to="{ name: 'battle-pass' }" data-testid="battle-pass-open">查看全部</router-link>
    </div>

    <p v-if="store.status === 'loading'" class="battle-pass-mini__note" role="status">读取赛季进度…</p>
    <div v-else-if="store.status === 'anonymous' || auth.isGuest" class="battle-pass-mini__guest">
      <span>登录后记录赛季经验</span>
      <button type="button" @click="auth.open('login', '登录后查看赛季通行证')">登录</button>
    </div>
    <p v-else-if="store.status === 'error'" class="battle-pass-mini__note battle-pass-mini__note--error">{{ store.error || '暂时无法读取' }}</p>
    <p v-else-if="!season" class="battle-pass-mini__note">当前没有开放的赛季。</p>
    <template v-else>
      <div class="battle-pass-mini__summary">
        <strong>Lv.{{ progress.level }}</strong>
        <span>{{ progress.xp.toLocaleString() }} / {{ season.totalXp.toLocaleString() }} XP</span>
      </div>
      <div class="battle-pass-mini__bar" role="progressbar" :aria-valuenow="progress.xp" :aria-valuemax="season.totalXp" aria-label="赛季经验进度">
        <i :style="{ width: xpPercent + '%' }"></i>
      </div>
      <div class="battle-pass-mini__foot">
        <span>{{ rewardText(nextReward) }}</span>
        <span>{{ store.challenges.filter((item) => item.completed).length }}/{{ store.challenges.length }} 挑战</span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.battle-pass-mini { min-width:0; padding:16px 18px; }
.battle-pass-mini__head,.battle-pass-mini__summary,.battle-pass-mini__foot { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.battle-pass-mini__eyebrow { margin:0 0 2px; color:var(--role-action); font-size:10px; letter-spacing:.14em; }
.battle-pass-mini__open { color:var(--role-action); font-size:11px; text-decoration:none; }
.battle-pass-mini__open:hover { text-decoration:underline; }
.battle-pass-mini__summary { margin-top:14px; color:var(--text-secondary); font-size:11px; font-variant-numeric:tabular-nums; }
.battle-pass-mini__summary strong { color:var(--text-primary); font-size:22px; line-height:1; }
.battle-pass-mini__bar { height:6px; margin-top:8px; overflow:hidden; border-radius:999px; background:var(--surface-raised); }
.battle-pass-mini__bar i { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,var(--role-action),var(--gold)); }
.battle-pass-mini__foot { margin-top:10px; color:var(--text-secondary); font-size:10px; line-height:1.4; }
.battle-pass-mini__foot span:first-child { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.battle-pass-mini__guest { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-top:13px; color:var(--text-secondary); font-size:12px; }
.battle-pass-mini__guest button { padding:4px 8px; border:1px solid var(--border-strong); border-radius:5px; color:var(--role-action); background:transparent; font:inherit; cursor:pointer; }
.battle-pass-mini__note { margin:13px 0 0; color:var(--text-secondary); font-size:12px; }
.battle-pass-mini__note--error { color:var(--role-warning); }
</style>
