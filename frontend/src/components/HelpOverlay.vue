<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppOverlay from './AppOverlay.vue'

/**
 * 玩法与段位帮助（原 main `#help-modal`）。
 *
 * 段位名、小级、每小级分数、每局加减分表**全部来自 `/api/rank_constants`**，
 * 前端不再写死任何数字（后端注释明确要求「帮助页与结算面板只从这份渲染」）。
 * 接口失败时只显示玩法说明并给出「段位规则暂不可用」，不编造数值。
 */
interface RankRow {
  key?: string
  label?: string
  value?: string
  condition?: string
}

interface RankTier {
  id?: string
  name?: string
  label?: string
  index?: number
}

interface RankConstants {
  sub_points?: number
  subs?: string[]
  tiers?: RankTier[]
  win_points?: number
  lose_points?: number
  min_points?: number
  captain_floor?: number
  start_points_of_tier?: Record<string, number>
  scoring?: { win?: RankRow[]; lose?: RankRow[]; loss_floor?: number; base_win?: number; base_lose?: number } & Record<string, unknown>
}

const emit = defineEmits<{ (event: 'close'): void }>()

const loading = ref(true)
const failed = ref(false)
const rules = ref<RankConstants | null>(null)

const playRules = [
  { title: '目标', body: '先击沉对手全部战舰者获胜。双方轮流开炮，炮弹落在对手海域的格子上。' },
  { title: '开局', body: '猜拳决定出手顺序：先手只抽 1 张魔法卡，后手抽 2 张；猜拳只决定这一大回合的顺序。' },
  { title: '回合', body: '每个大回合分准备阶段与战斗阶段。准备阶段出牌、加盾；进入战斗阶段后才能开炮。' },
  { title: '连锁', body: '对手出牌时可以响应：速阶更高的魔法卡能截住它。响应有时限，超时视为不响应。' },
  { title: '场地魔法', body: '场地魔法一直生效，直到被新的场地魔法替换或被无效化。' },
]

const winRows = computed<RankRow[]>(() => rules.value?.scoring?.win ?? [])
const loseRows = computed<RankRow[]>(() => rules.value?.scoring?.lose ?? [])
const tiers = computed<RankTier[]>(() => rules.value?.tiers ?? [])

function tierName(tier: RankTier): string {
  return tier.name ?? tier.label ?? tier.id ?? '未知段位'
}

function startPoints(tier: RankTier): string {
  const table = rules.value?.start_points_of_tier
  if (!table || !tier.id) return '—'
  const points = table[tier.id]
  return typeof points === 'number' ? String(points) : '—'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const response = await fetch('/api/rank_constants', { headers: { accept: 'application/json' } })
    const data = (await response.json()) as RankConstants
    if (!response.ok || !Array.isArray(data.tiers) || !data.tiers.length) throw new Error('bad payload')
    rules.value = data
    failed.value = false
  } catch {
    rules.value = null
    failed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppOverlay id="help-overlay" labelledby="help-title" @close="emit('close')">
    <div class="help">
      <header class="help__head">
        <div>
          <p class="help__eyebrow">帮助 · 玩法与段位</p>
          <h2 id="help-title" class="help__title">怎么打，怎么升级</h2>
        </div>
        <button type="button" class="button button--ghost" data-testid="help-close" @click="emit('close')">关闭</button>
      </header>

      <div class="help__cols">
        <section class="help__panel" aria-label="玩法说明">
          <h3 class="help__panel-title">玩法</h3>
          <dl class="help__list">
            <template v-for="rule in playRules" :key="rule.title">
              <dt>{{ rule.title }}</dt>
              <dd>{{ rule.body }}</dd>
            </template>
          </dl>
        </section>

        <section class="help__panel" aria-label="段位阶梯">
          <h3 class="help__panel-title">段位阶梯</h3>
          <p v-if="loading" class="help__hint" data-testid="help-loading">正在读取段位规则…</p>
          <p v-else-if="failed" class="help__hint help__hint--warn" data-testid="help-unavailable">
            段位规则暂不可用，稍后再看；玩法说明不受影响。
          </p>
          <ol v-else class="help__tiers" data-testid="help-tiers">
            <li v-for="tier in tiers" :key="tier.id ?? tierName(tier)" class="help__tier">
              <span class="help__tier-name">{{ tierName(tier) }}</span>
              <span class="help__tier-sub">{{ rules?.subs?.join(' / ') }}</span>
              <span class="help__tier-points">{{ startPoints(tier) }} 分起</span>
            </li>
          </ol>
          <p v-if="rules" class="help__foot">
            每个小级 {{ rules.sub_points }} 分；最低 {{ rules.min_points }} 分；胜利 {{ rules.win_points }} 分、失败
            {{ rules.lose_points }} 分起，具体加成为下表的组合。
          </p>
        </section>
      </div>

      <section v-if="rules && (winRows.length || loseRows.length)" class="help__panel help__panel--wide" aria-label="计分规则">
        <h3 class="help__panel-title">每局加减分</h3>
        <div class="help__score-grid">
          <div>
            <h4 class="help__score-title">胜利</h4>
            <ul class="help__score-list" data-testid="help-scoring-win">
              <li v-for="row in winRows" :key="row.key ?? row.label">
                <span class="help__score-label">{{ row.label }}</span>
                <b class="help__score-value">{{ row.value }}</b>
                <span v-if="row.condition" class="help__score-cond">{{ row.condition }}</span>
              </li>
            </ul>
          </div>
          <div>
            <h4 class="help__score-title">失败</h4>
            <ul class="help__score-list" data-testid="help-scoring-lose">
              <li v-for="row in loseRows" :key="row.key ?? row.label">
                <span class="help__score-label">{{ row.label }}</span>
                <b class="help__score-value">{{ row.value }}</b>
                <span v-if="row.condition" class="help__score-cond">{{ row.condition }}</span>
              </li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  </AppOverlay>
</template>

<style scoped>
.help {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: min(1000px, calc(100vw - 48px));
  max-height: calc(100dvh - 96px);
  overflow: auto;
  padding: 18px 20px 20px;
}

.help__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.help__eyebrow {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.help__title {
  margin: 0;
  font-size: 20px;
  color: var(--text-primary);
}

.help__cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}

.help__panel {
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-chamber);
}

.help__panel--wide {
  grid-column: 1 / -1;
}

.help__panel-title {
  margin: 0 0 10px;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
}

.help__list {
  margin: 0;
  display: grid;
  gap: 8px;
}

.help__list dt {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.help__list dd {
  margin: 2px 0 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-secondary);
}

.help__tiers {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 4px;
}

.help__tier {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: baseline;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--role-action) 6%, transparent);
}

.help__tier-name {
  font-size: 13px;
  color: var(--text-primary);
}

.help__tier-sub {
  font-size: 11px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.help__tier-points {
  font-size: 11.5px;
  color: var(--gold-strong, var(--role-action));
  font-variant-numeric: tabular-nums;
}

.help__hint {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.help__hint--warn {
  color: var(--role-warning);
}

.help__foot {
  margin: 10px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}

.help__score-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}

.help__score-title {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.help__score-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 4px;
}

.help__score-list li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  padding: 5px 8px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-raised) 70%, transparent);
}

.help__score-label {
  font-size: 12.5px;
  color: var(--text-primary);
}

.help__score-value {
  font-size: 12.5px;
  color: var(--gold-strong, var(--role-action));
  font-variant-numeric: tabular-nums;
}

.help__score-cond {
  grid-column: 1 / -1;
  font-size: 11px;
  color: var(--text-tertiary);
}

@media (max-width: 860px) {
  .help {
    width: min(100%, calc(100vw - 24px));
    padding: 14px 14px 16px;
  }

  .help__cols,
  .help__score-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
