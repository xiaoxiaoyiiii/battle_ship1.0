<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useBattlePassStore, type BattlePassLevel, type BattlePassTrack } from '../../stores/battlePass'

const auth = useAuthStore()
const store = useBattlePassStore()

const signedIn = computed(() => !auth.isGuest && store.status !== 'anonymous')
const season = computed(() => store.season)
const progress = computed(() => store.progress)
const currentLevel = computed(() => progress.value.level || 1)
const levelCap = computed(() => season.value?.levelCap || 50)
const xpPercent = computed(() => {
  const total = season.value?.totalXp || 0
  return total ? Math.max(0, Math.min(100, Math.round((progress.value.xp / total) * 100))) : 0
})
const displayLevels = computed(() => {
  const levels = store.levels
  if (!levels.length) return []
  const start = Math.max(1, Math.min(currentLevel.value - 1, levels.length - 5))
  return levels.slice(start, start + 5)
})
const nextLevel = computed(() => displayLevels.value.find((row) => row.level > currentLevel.value) || null)
const compactChallenges = computed(() => store.challenges.slice(0, 3))

function rewardLabel(row: BattlePassLevel, track: BattlePassTrack): string {
  const kind = track === 'free' ? row.freeKind : row.premiumKind
  const id = track === 'free' ? row.freeRewardId : row.premiumRewardId
  if (!id) return '—'
  const clean = id.includes(':') ? id.split(':').slice(1).join(':') : id
  const labels: Record<string, string> = {
    title: '称号', frame: '头像框', avatar_frame: '头像框', card_bg: '名片底色', badge: '徽章',
  }
  return `${labels[kind] || kind || '奖励'} · ${clean.replaceAll('_', ' ')}`
}
function claimText(row: BattlePassLevel, track: BattlePassTrack): string {
  if (store.isClaimed(row.level, track)) return '已领取'
  if (track === 'premium' && !progress.value.premiumUnlocked) return '豪华'
  if (!store.canClaim(row.level, track)) return '未解锁'
  return store.claiming === `${row.level}:${track}` ? '领取中…' : '领取'
}
function claim(row: BattlePassLevel, track: BattlePassTrack): void {
  void store.claim(row.level, track)
}
function stateLabel(state: string): string {
  return ({ active: '进行中', claim_only: '领取期', upcoming: '即将开始', closed: '已结束' } as Record<string, string>)[state] || '进行中'
}
function progressWidth(challenge: { current: number; target: number }): number {
  return Math.max(0, Math.min(100, Math.round((challenge.current / challenge.target) * 100)))
}

onMounted(() => { void store.load() })
watch(() => auth.isGuest, () => { store.reset(); void store.load() })
</script>

<template>
  <section class="home-card battle-pass" data-testid="battle-pass-card" aria-labelledby="battle-pass-title">
    <div class="battle-pass__head">
      <div>
        <p class="battle-pass__eyebrow">航海季 · 进度</p>
        <h2 id="battle-pass-title" class="home-kicker">赛季通行证</h2>
      </div>
      <span v-if="season" class="battle-pass__state">{{ stateLabel(season.state) }}</span>
    </div>

    <p v-if="store.status === 'loading'" class="battle-pass__note" role="status">正在读取赛季进度…</p>
    <div v-else-if="store.status === 'anonymous' || (auth.isGuest && !season)" class="battle-pass__guest">
      <p>登录后记录赛季经验，领取航海奖励。</p>
      <button type="button" class="battle-pass__action" @click="auth.open('login', '登录后查看赛季通行证')">登录查看</button>
    </div>
    <p v-else-if="store.status === 'error'" class="battle-pass__note battle-pass__note--error" role="alert">
      {{ store.error || '赛季进度暂时无法读取。' }}
      <button type="button" class="battle-pass__retry" @click="store.load(true)">重试</button>
    </p>
    <p v-else-if="store.status === 'empty' || !season" class="battle-pass__note">当前没有开放的赛季。</p>

    <template v-else>
      <div class="battle-pass__summary">
        <div class="battle-pass__level"><strong>Lv.{{ currentLevel }}</strong><span>/ {{ levelCap }}</span></div>
        <div class="battle-pass__xp"><span>{{ progress.xp.toLocaleString() }} XP</span><span>{{ season.totalXp.toLocaleString() }} XP</span></div>
        <div class="battle-pass__bar" role="progressbar" :aria-valuenow="progress.xp" :aria-valuemax="season.totalXp" aria-label="赛季经验进度">
          <i :style="{ width: xpPercent + '%' }"></i>
        </div>
      </div>

      <div class="battle-pass__section">
        <div class="battle-pass__section-head"><h3>奖励轨道</h3><span>当前等级附近</span></div>
        <div class="battle-pass__tracks" role="list" aria-label="赛季奖励轨道">
          <div v-for="row in displayLevels" :key="row.level" class="battle-pass__level-row" :class="{ 'is-current': row.level === currentLevel, 'is-past': row.level < currentLevel }" role="listitem">
            <span class="battle-pass__level-no">{{ row.level }}</span>
            <div class="battle-pass__reward battle-pass__reward--free">
              <span class="battle-pass__reward-label">免费</span>
              <span class="battle-pass__reward-name">{{ rewardLabel(row, 'free') }}</span>
              <button v-if="row.freeRewardId" type="button" class="battle-pass__claim" :disabled="!store.canClaim(row.level, 'free') || store.claiming !== null" :data-claimed="store.isClaimed(row.level, 'free')" @click="claim(row, 'free')">{{ claimText(row, 'free') }}</button>
            </div>
            <div class="battle-pass__reward battle-pass__reward--premium">
              <span class="battle-pass__reward-label">豪华</span>
              <span class="battle-pass__reward-name">{{ rewardLabel(row, 'premium') }}</span>
              <button v-if="row.premiumRewardId" type="button" class="battle-pass__claim" :disabled="!store.canClaim(row.level, 'premium') || store.claiming !== null" :data-claimed="store.isClaimed(row.level, 'premium')" @click="claim(row, 'premium')">{{ claimText(row, 'premium') }}</button>
            </div>
          </div>
          <p v-if="!displayLevels.length" class="battle-pass__note">奖励目录准备中。</p>
        </div>
      </div>

      <div v-if="compactChallenges.length" class="battle-pass__section battle-pass__challenges">
        <div class="battle-pass__section-head"><h3>赛季挑战</h3><span>完成可得额外 XP</span></div>
        <ul>
          <li v-for="challenge in compactChallenges" :key="challenge.id" :class="{ 'is-complete': challenge.completed }">
            <div class="battle-pass__challenge-copy"><strong>{{ challenge.title }}</strong><span>{{ challenge.current }} / {{ challenge.target }}</span><small>{{ challenge.description }} · +{{ challenge.xp }} XP</small></div>
            <div class="battle-pass__challenge-bar"><i :style="{ width: progressWidth(challenge) + '%' }"></i></div>
          </li>
        </ul>
      </div>

      <div class="battle-pass__foot">
        <span>{{ progress.premiumUnlocked ? '豪华轨道已解锁' : '免费轨道 · 豪华轨道由管理员发放' }}</span>
        <span v-if="nextLevel">下一奖励 Lv.{{ nextLevel.level }}</span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.battle-pass { min-width:0; padding:18px 20px; }
.battle-pass__head,.battle-pass__section-head,.battle-pass__xp,.battle-pass__foot { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.battle-pass__eyebrow { margin:0 0 3px; color:var(--role-action); font-size:11px; letter-spacing:.12em; }
.battle-pass__state { padding:3px 8px; border:1px solid color-mix(in srgb,var(--role-success) 34%,var(--panel-line)); border-radius:999px; color:var(--role-success); font-size:11px; white-space:nowrap; }
.battle-pass__summary { margin-top:14px; }
.battle-pass__level { display:flex; align-items:baseline; gap:5px; color:var(--text-primary); }
.battle-pass__level strong { font-size:23px; line-height:1; }
.battle-pass__level span { color:var(--text-secondary); font-size:12px; }
.battle-pass__xp { margin-top:7px; color:var(--text-secondary); font-size:11px; font-variant-numeric:tabular-nums; }
.battle-pass__bar,.battle-pass__challenge-bar { height:5px; overflow:hidden; border-radius:999px; background:var(--surface-raised); }
.battle-pass__bar { margin-top:7px; }
.battle-pass__bar i,.battle-pass__challenge-bar i { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,var(--role-action),var(--gold)); }
.battle-pass__section { margin-top:15px; }
.battle-pass__section-head h3 { margin:0; color:var(--text-primary); font-size:13px; font-weight:650; }
.battle-pass__section-head span { color:var(--text-secondary); font-size:11px; }
.battle-pass__tracks { display:grid; gap:6px; margin-top:8px; max-height:235px; overflow:auto; padding-right:3px; scrollbar-width:thin; }
.battle-pass__level-row { display:grid; grid-template-columns:25px minmax(0,1fr) minmax(0,1fr); gap:6px; align-items:stretch; }
.battle-pass__level-row.is-current .battle-pass__level-no { border-color:var(--role-action); color:var(--text-primary); background:color-mix(in srgb,var(--role-action) 17%,var(--panel)); }
.battle-pass__level-row.is-past { opacity:.62; }
.battle-pass__level-no { display:grid; place-items:center; min-height:42px; border:1px solid var(--panel-line); border-radius:5px; color:var(--text-secondary); font-size:12px; font-weight:650; }
.battle-pass__reward { min-width:0; position:relative; display:grid; grid-template-columns:auto minmax(0,1fr); align-content:center; gap:0 6px; padding:6px 7px; border:1px solid var(--panel-line); border-radius:5px; background:var(--surface-sea); }
.battle-pass__reward--premium { border-color:color-mix(in srgb,var(--gold) 25%,var(--panel-line)); }
.battle-pass__reward-label { grid-row:1 / 3; align-self:center; color:var(--text-secondary); font-size:10px; writing-mode:vertical-rl; }
.battle-pass__reward--premium .battle-pass__reward-label { color:var(--gold-strong); }
.battle-pass__reward-name { min-width:0; overflow:hidden; color:var(--text-primary); font-size:11px; line-height:1.25; text-overflow:ellipsis; white-space:nowrap; }
.battle-pass__claim { justify-self:start; margin-top:4px; padding:1px 5px; border:1px solid var(--border-strong); border-radius:3px; color:var(--role-action); background:transparent; font:inherit; font-size:10px; cursor:pointer; }
.battle-pass__claim:not(:disabled):hover { background:color-mix(in srgb,var(--role-action) 14%,transparent); }
.battle-pass__claim:disabled { color:var(--text-muted); cursor:default; opacity:.75; }
.battle-pass__claim[data-claimed='true'] { color:var(--role-success); border-color:color-mix(in srgb,var(--role-success) 35%,var(--panel-line)); }
.battle-pass__challenges ul { display:grid; gap:8px; margin:8px 0 0; padding:0; list-style:none; }
.battle-pass__challenges li { min-width:0; }
.battle-pass__challenge-copy { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:2px 8px; align-items:baseline; }
.battle-pass__challenge-copy strong { overflow:hidden; color:var(--text-primary); font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
.battle-pass__challenge-copy > span { color:var(--role-action); font-size:11px; font-variant-numeric:tabular-nums; }
.battle-pass__challenge-copy small { grid-column:1 / -1; overflow:hidden; color:var(--text-secondary); font-size:10px; line-height:1.4; text-overflow:ellipsis; white-space:nowrap; }
.battle-pass__challenge-bar { height:3px; margin-top:4px; }
.battle-pass__challenges li.is-complete .battle-pass__challenge-bar i { background:var(--role-success); }
.battle-pass__foot { margin-top:13px; padding-top:10px; border-top:1px solid var(--panel-line); color:var(--text-secondary); font-size:10px; line-height:1.4; }
.battle-pass__note { margin:14px 0 0; color:var(--text-secondary); font-size:12px; line-height:1.55; }
.battle-pass__note--error { color:var(--role-warning); }
.battle-pass__retry,.battle-pass__guest button { color:var(--role-action); border:0; background:none; font:inherit; cursor:pointer; text-decoration:underline; }
.battle-pass__guest { margin-top:14px; padding:11px 12px; border:1px solid var(--panel-line); border-radius:7px; background:var(--surface-sea); }
.battle-pass__guest p { margin:0; color:var(--text-secondary); font-size:12px; line-height:1.5; }
.battle-pass__action { margin-top:8px; padding:6px 10px; border:1px solid var(--border-strong); border-radius:5px; color:var(--text-primary); background:var(--surface-raised); font:inherit; font-size:12px; cursor:pointer; }
@media(min-width:1024px) and (min-height:700px) { .battle-pass { padding:14px 16px; } .battle-pass__tracks { max-height:190px; } .battle-pass__section { margin-top:11px; } .battle-pass__summary { margin-top:10px; } }
@media(max-width:719px) { .battle-pass { padding:18px; } .battle-pass__tracks { max-height:none; } }
</style>\n