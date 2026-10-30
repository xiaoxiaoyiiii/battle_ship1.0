<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { PlayerCard } from './usePlayerCards'
import AvatarStack from '../../components/AvatarStack.vue'
import TitleBadge from '../../components/TitleBadge.vue'

/**
 * 局内查看某一方的公开名片（原 main 的 #opponent-stats-modal）。
 * 数据是 /user_stats 已按隐私开关过滤后的结果：服务端没给的字段这里一律不显示。
 */
const props = defineProps<{
  side: 'self' | 'opponent'
  name: string
  card: PlayerCard
  isAi: boolean
}>()
const emit = defineEmits<{ (event: 'close'): void }>()
const router = useRouter()

function str(key: string): string {
  const value = props.card.stats?.[key]
  return typeof value === 'string' ? value : ''
}
function num(key: string): number | null {
  const raw = props.card.stats?.[key]
  if (raw === undefined || raw === null || raw === '') return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}
function obj(key: string): Record<string, unknown> | null {
  const value = props.card.stats?.[key]
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}
function flag(key: string): boolean {
  const value = props.card.stats?.[key]
  return value === undefined || value === null ? true : Number(value) !== 0
}

const title = computed(() => (props.side === 'opponent' ? '对手个人信息' : '我的个人信息'))
const ready = computed(() => props.card.status === 'ready' && props.card.stats !== null)
const wins = computed(() => num('wins'))
const losses = computed(() => num('losses'))
const total = computed(() => (wins.value ?? 0) + (losses.value ?? 0))
const winRate = computed(() => (total.value ? Math.round(((wins.value ?? 0) / total.value) * 100) + '%' : '暂无'))
const rankLabel = computed(() => {
  const label = obj('rank_info')?.label
  return flag('show_rank') && typeof label === 'string' ? label : ''
})
const level = computed(() => {
  const value = obj('level_info')?.level
  return typeof value === 'number' ? 'Lv.' + value : ''
})
const showStats = computed(() => flag('show_stats') && (wins.value !== null || losses.value !== null))
const emptyText = computed(() => {
  if (props.card.status === 'loading') return '正在读取资料…'
  if (props.isAi && props.side === 'opponent') return '这是人机对手，没有公开战绩。'
  if (props.card.status === 'error') return '资料没读出来，稍后再试。'
  return props.side === 'opponent' ? '对手是游客或未注册账号，没有公开战绩。' : '游客没有账号资料，登录后才会记录战绩。'
})

/**
 * 局内名片只负责展示公开资料；进入完整主页交给现有 profile 路由。
 * AI 没有账号资料，避免把它导航到一个无意义的 username=AI 页面。
 */
const canOpenProfile = computed(() => Boolean(props.name.trim()) && !(props.side === 'opponent' && props.isAi))
function openProfile(): void {
  if (!canOpenProfile.value) return
  emit('close')
  void router.push({
    name: 'profile',
    query: props.side === 'opponent' ? { username: props.name.trim(), from: 'game' } : { from: 'game' },
  })
}
</script>

<template>
  <div class="player-card-scrim" data-testid="game-player-card-scrim" @click.self="emit('close')">
    <section
      class="player-card"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      :data-testid="side === 'opponent' ? 'game-opponent-stats' : 'game-self-stats'"
    >
      <header class="player-card__head">
        <h2 class="player-card__title">{{ title }}</h2>
        <button type="button" class="game-close" data-testid="game-player-card-close" aria-label="关闭" @click="emit('close')">×</button>
      </header>
      <div class="player-card__who">
        <AvatarStack
          class="player-card__avatar"
          :src="ready ? str('avatar') : ''"
          :frame="ready ? str('frame_id') : 'none'"
          :fallback="(name || '?').slice(0, 1)"
          testid="game-player-card-avatar"
          size="md"
        />
        <div>
          <b class="player-card__name" data-testid="game-player-card-name">{{ name }}</b>
          <TitleBadge
            v-if="ready && str('title_name')"
            :name="str('title_name')"
            :title-id="str('title_id')"
            :title-fx-id="str('title_effect_id') || str('title_fx_id')"
            compact
          />
        </div>
      </div>
      <template v-if="ready">
        <p v-if="str('signature')" class="player-card__line">{{ str('signature') }}</p>
        <dl class="player-card__grid" data-testid="game-player-card-stats">
          <template v-if="level">
            <dt>等级</dt>
            <dd>{{ level }}</dd>
          </template>
          <template v-if="rankLabel">
            <dt>段位</dt>
            <dd>{{ rankLabel }}</dd>
          </template>
          <template v-if="showStats">
            <dt>胜 / 负</dt>
            <dd>{{ wins ?? 0 }} / {{ losses ?? 0 }}</dd>
            <dt>胜率</dt>
            <dd>{{ winRate }}</dd>
            <template v-if="num('longest_streak') !== null">
              <dt>最长连胜</dt>
              <dd>{{ num('longest_streak') }}</dd>
            </template>
          </template>
        </dl>
        <p v-if="!level && !rankLabel && !showStats" class="player-card__line">这位玩家没有公开战绩。</p>
      </template>
      <p v-else class="player-card__line" data-testid="game-player-card-empty">{{ emptyText }}</p>
      <footer v-if="canOpenProfile" class="player-card__actions">
        <button
          type="button"
          class="button button--primary"
          data-testid="game-player-card-profile"
          @click="openProfile"
        >进入个人主页</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.player-card-scrim {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: grid;
  place-items: center;
  padding: 14px;
  background: rgba(4, 8, 14, 0.6);
}

.player-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(380px, 100%);
  max-height: 100%;
  overflow-y: auto;
  padding: 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  background: var(--surface-chamber);
  box-shadow: var(--shadow-panel);
}

.player-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.player-card__title {
  margin: 0;
  font-size: 15px;
}

.player-card__who {
  display: flex;
  align-items: center;
  gap: 10px;
}

.player-card__avatar {
  width: 56px;
  height: 56px;
  flex: 0 0 56px;
}

.player-card__name {
  font-size: 16px;
  overflow-wrap: anywhere;
}

.player-card__line {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}

.player-card__grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 14px;
  margin: 0;
  font-size: 13px;
}

.player-card__grid dt {
  color: var(--text-secondary);
}

.player-card__grid dd {
  margin: 0;
  font-weight: 700;
}

.player-card__actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 2px;
  border-top: 1px solid var(--border-subtle);
}

.player-card__actions .button {
  min-height: 34px;
  padding-inline: 14px;
}
</style>
