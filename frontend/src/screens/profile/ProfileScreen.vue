<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProfileStore, type JsonObject } from '../../stores/profile'
import { useUiStore } from '../../stores/ui'

/**
 * Ticket #25: own / other player's profile card.
 *
 * Every number, badge, tier label and history row comes from the server. The
 * privacy flags are rendered, not enforced here: show_history / show_rank /
 * show_guestbook were already applied by the server, while show_stats /
 * show_fav_cards remain legacy frontend-only hides (DECISIONS D13).
 */
const route = useRoute()
const router = useRouter()
const store = useProfileStore()
const ui = useUiStore()

const targetUsername = computed(() => String(route.query.username || '').trim())
const viewed = computed(() => store.viewed)
const stats = computed<JsonObject | null>(() => viewed.value.stats)

const isSelf = computed(() => {
  const row = stats.value
  if (!row) return false
  const name = String(row.username || '')
  return Boolean(name) && name === store.viewerName
})

function readObject(source: JsonObject | null | undefined, key: string): JsonObject | null {
  const value = source ? source[key] : null
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function readArray(source: JsonObject | null | undefined, key: string): unknown[] {
  const value = source ? source[key] : null
  return Array.isArray(value) ? value : []
}

function readString(source: JsonObject | null | undefined, key: string): string {
  const value = source ? source[key] : null
  return typeof value === 'string' ? value : ''
}

function readNumber(source: JsonObject | null | undefined, key: string): number | null {
  const value = Number(source ? source[key] : NaN)
  return Number.isFinite(value) ? value : null
}

function flag(key: string): boolean {
  const value = stats.value ? stats.value[key] : null
  return value === undefined || value === null ? true : Number(value) !== 0
}

const loading = computed(
  () =>
    viewed.value.status === 'loading' ||
    (store.ownStatus === 'loading' && !targetUsername.value),
)
const loginRequired = computed(
  () => !targetUsername.value && store.ownStatus === 'anonymous' && viewed.value.status === 'idle',
)
const empty = computed(() => viewed.value.status === 'empty')
const failed = computed(() => viewed.value.status === 'error')
const ready = computed(() => viewed.value.status === 'ready' && stats.value !== null)

const avatar = computed(() => readString(stats.value, 'avatar'))
const displayName = computed(() => readString(stats.value, 'username') || targetUsername.value || '玩家')
const statusText = computed(() => readString(stats.value, 'status_text'))
const signature = computed(() => readString(stats.value, 'signature'))
const titleName = computed(() => readString(stats.value, 'title_name'))
const nameStyle = computed(() => readString(stats.value, 'name_style'))
const cardBg = computed(() => readString(stats.value, 'card_bg_id') || 'deep')
const frame = computed(() => readString(stats.value, 'frame_id') || 'none')

const tags = computed(() => {
  const names = readArray(stats.value, 'tag_names').map((item) => String(item))
  if (names.length) return names
  return readArray(stats.value, 'tags').map((item) => String(item))
})

const wins = computed(() => readNumber(stats.value, 'wins') ?? 0)
const losses = computed(() => readNumber(stats.value, 'losses') ?? 0)
const totalMatches = computed(() => wins.value + losses.value)
const winRateText = computed(() => {
  const total = totalMatches.value
  // Unknown is shown as 暂无, never as a dash row (spec story 97).
  return total ? Math.round((wins.value / total) * 100) + '%' : '暂无'
})
const streak = computed(() => readNumber(stats.value, 'longest_streak') ?? 0)

const levelInfo = computed(() => readObject(stats.value, 'level_info'))
const levelText = computed(() => 'Lv.' + (readNumber(levelInfo.value, 'level') ?? 1))
const levelCapped = computed(() => levelInfo.value?.capped === true)
const levelFill = computed(() => {
  if (!levelInfo.value) return 0
  if (levelCapped.value) return 100
  const ratio = readNumber(levelInfo.value, 'ratio') ?? 0
  return Math.max(0, Math.min(100, Math.round(ratio * 100)))
})
const levelProgressText = computed(() => {
  if (!levelInfo.value) return ''
  if (levelCapped.value) return '满级 ' + (readNumber(levelInfo.value, 'max_level') ?? 100)
  const into = readNumber(levelInfo.value, 'into') ?? 0
  const need = readNumber(levelInfo.value, 'need') ?? 0
  return into + ' / ' + need + ' 经验'
})

const rankInfo = computed(() => readObject(stats.value, 'rank_info'))
const showRank = computed(() => flag('show_rank'))
const rankFill = computed(() => {
  const row = rankInfo.value
  if (!row) return 0
  const sub = readNumber(row, 'sub_points') ?? 0
  const progress = readNumber(row, 'progress') ?? 0
  if (sub <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((progress / sub) * 100)))
})
const rankNextText = computed(() => {
  const next = rankInfo.value ? readNumber(rankInfo.value, 'to_next') : null
  return next === null ? '' : '还差 ' + next + ' 分'
})

const showStats = computed(() => flag('show_stats'))
const showFavCards = computed(() => flag('show_fav_cards'))
const favCards = computed(() =>
  readArray(stats.value, 'fav_cards')
    .filter((item): item is JsonObject => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    .filter((item) => Boolean(item.name)),
)

const badges = computed(() => {
  // Owner view: the full catalogue comes from /api/achievements.
  if (store.achievements.length) return store.achievements
  return readArray(stats.value, 'achievements').filter(
    (item): item is JsonObject => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
})
const badgeCount = computed(() => store.achievementCount ?? readObject(stats.value, 'badge_count'))
const badgeUnlocked = computed(() => {
  const count = badgeCount.value ? readNumber(badgeCount.value, 'unlocked') : null
  return count ?? badges.value.filter((item) => item.unlocked === true).length
})
const badgeTotal = computed(() => {
  const count = badgeCount.value ? readNumber(badgeCount.value, 'total') : null
  return count ?? badges.value.length
})

const showHistory = computed(() => isSelf.value || flag('show_history'))
const history = computed(() => viewed.value.history)
const historyEmptyText = computed(() => {
  if (!showHistory.value) return '该玩家未公开对局历史'
  return isSelf.value ? '还没有对局记录' : '暂无历史战绩'
})

const winsRank = computed(() => readNumber(stats.value, 'rank'))
const createdAt = computed(() => {
  const seconds = readNumber(stats.value, 'created_at')
  if (!seconds) return ''
  const date = new Date(seconds * 1000)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')
})

function modeLabel(mode: unknown): string {
  switch (String(mode || '')) {
    case 'ranked':
      return '排位'
    case 'casual':
      return '休闲'
    case 'ai':
      return '人机'
    case 'custom':
      return '自定义'
    default:
      return ''
  }
}

function historyTime(row: JsonObject): string {
  const seconds = Number(row.timestamp)
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  const date = new Date(seconds * 1000)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN')
}

function historyOpponent(row: JsonObject): string {
  const selfId = stats.value ? String(stats.value.id || '') : ''
  const winnerId = String(row.winner_id || '')
  const name = winnerId === selfId ? row.loser_name : row.winner_name
  return String(name || '未知玩家')
}

function historyResult(row: JsonObject): string {
  const selfId = stats.value ? String(stats.value.id || '') : ''
  return String(row.winner_id || '') === selfId ? '胜' : '负'
}

function openReplay(matchId: string): void {
  if (!matchId) return
  void router.push({ name: 'replay', query: { match_id: matchId } })
}

function openSettings(): void {
  void router.push({ name: 'settings' })
}

/** Where 返回 goes: the query the caller sent, then browser history, then the board. */
const FROM_ROUTES: Record<string, { name: string }> = {
  start: { name: 'start' },
  home: { name: 'start' },
  leaderboard: { name: 'leaderboard' },
  lobby: { name: 'lobby' },
  'game-over': { name: 'game-over' },
  replay: { name: 'replay' },
  spectate: { name: 'spectate' },
}

function back(): void {
  const from = String(route.query.from || '')
  const target = FROM_ROUTES[from]
  if (target) {
    void router.push(target)
    return
  }
  const historyBack = router.options.history.state.back
  if (typeof historyBack === 'string' && historyBack && historyBack !== route.fullPath) {
    router.back()
    return
  }
  void router.push({ name: 'leaderboard' })
}

// ------------------------------------------------------- recent entries ----
// The three entries (badges / record / replay) are ordered by most recent use
// and the order is remembered, so a returning player's habitual entry is first.
type QuickKey = 'badges' | 'record' | 'replay'
const QUICK_KEY = 'battleship.profile.recent'
const QUICK_DEFAULT: QuickKey[] = ['badges', 'record', 'replay']
const QUICK_LABELS: Record<QuickKey, string> = { badges: '徽章', record: '战绩', replay: '回放' }
const QUICK_TARGETS: Record<QuickKey, string> = {
  badges: 'profile-badges',
  record: 'profile-history',
  replay: 'profile-history',
}

function readQuickOrder(): QuickKey[] {
  try {
    const raw = localStorage.getItem(QUICK_KEY)
    if (!raw) return [...QUICK_DEFAULT]
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return [...QUICK_DEFAULT]
    const valid = parsed.filter((item): item is QuickKey => QUICK_DEFAULT.includes(item as QuickKey))
    return [...valid, ...QUICK_DEFAULT.filter((item) => !valid.includes(item))]
  } catch {
    return [...QUICK_DEFAULT]
  }
}

const quickOrder = ref<QuickKey[]>(readQuickOrder())

function useQuick(key: QuickKey): void {
  quickOrder.value = [key, ...quickOrder.value.filter((item) => item !== key)]
  try {
    localStorage.setItem(QUICK_KEY, JSON.stringify(quickOrder.value))
  } catch {
    // Best effort: the order still changes for this visit.
  }
  document
    .querySelector('[data-testid="' + QUICK_TARGETS[key] + '"]')
    ?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

async function refresh(): Promise<void> {
  if (targetUsername.value) {
    await store.loadPublic(targetUsername.value)
    return
  }
  if (store.viewerName) {
    await store.loadPublic(store.viewerName)
  } else {
    store.clearViewed()
  }
}

onMounted(async () => {
  await store.loadOwn()
  await refresh()
})

watch(targetUsername, () => {
  void refresh()
})
</script>

<template>
  <section
    class="screen profile"
    data-screen="profile"
    data-testid="screen-profile"
    :data-self="isSelf ? 'true' : 'false'"
    aria-labelledby="screen-profile-title"
  >
    <header class="profile__head">
      <p class="profile__eyebrow">竞技场 · 名片</p>
      <h1 id="screen-profile-title" class="profile__title" data-testid="profile-heading">名片</h1>
      <p class="profile__viewing" data-testid="profile-viewing">
        {{ ready ? (isSelf ? '我的名片' : displayName + ' 的名片') : '玩家名片' }}
      </p>
    </header>

    <p v-if="loading" class="profile__state" data-testid="profile-loading" role="status">正在加载名片…</p>

    <section v-else-if="loginRequired" class="profile__login" data-testid="profile-login-required">
      <h2>需要先登录</h2>
      <p>自己的名片、徽章与隐私设置都在登录后显示。</p>
      <button
        type="button"
        class="button"
        data-testid="profile-login-required-action"
        @click="ui.requestLogin('login', '登录后查看完整名片')"
      >
        登录 / 注册
      </button>
    </section>

    <p v-else-if="empty" class="profile__state" data-testid="profile-empty">
      没有找到这位玩家 —— 用户名可能拼错了，或账号已经不存在。
    </p>

    <p v-else-if="failed" class="profile__state profile__state--error" data-testid="profile-error" role="alert">
      无法加载名片：{{ viewed.error }}
    </p>

    <template v-else-if="ready">
      <!-- Most-recently-used first (spec story 120, ticket #49). -->
      <nav class="profile__quick" data-testid="profile-quick" aria-label="常用入口">
        <button
          v-for="key in quickOrder"
          :key="key"
          type="button"
          class="profile__quick-item"
          :data-testid="'profile-quick-' + key"
          @click="useQuick(key)"
        >
          {{ QUICK_LABELS[key] }}
        </button>
      </nav>

      <article class="profile__card" :data-bg="cardBg">
        <header class="profile__hero">
          <div class="profile__avatar-wrap">
            <img v-if="avatar" class="profile__avatar" data-testid="profile-avatar"
                 :src="avatar" :data-frame="frame" alt="" />
            <span v-else class="profile__avatar profile__avatar--empty" data-testid="profile-avatar"
                  :data-frame="frame" aria-hidden="true">⚓</span>
            <span class="profile__level" data-testid="profile-level">{{ levelText }}</span>
          </div>
          <div class="profile__who">
            <h2 class="profile__name">
              <span :class="{ 'is-rainbow': nameStyle === 'rainbow' }" data-testid="profile-name">{{ displayName }}</span>
              <span v-if="titleName" class="profile__title-chip" data-testid="profile-title">{{ titleName }}</span>
            </h2>
            <p v-if="statusText" class="profile__status" data-testid="profile-status">{{ statusText }}</p>
            <p v-if="signature" class="profile__signature" data-testid="profile-signature">
              {{ signature }}
            </p>
            <div v-if="tags.length" class="profile__tags" data-testid="profile-tags">
              <span v-for="tag in tags" :key="tag" class="profile__tag">{{ tag }}</span>
            </div>
          </div>
        </header>

        <div v-if="levelInfo" class="profile__bar-row">
          <div class="profile__bar" role="img" :aria-label="'等级进度 ' + levelFill + '%'">
            <div class="profile__bar-fill" data-testid="profile-level-fill" :style="{ width: levelFill + '%' }"></div>
          </div>
          <span class="profile__bar-text" data-testid="profile-level-text">{{ levelProgressText }}</span>
        </div>

        <section v-if="rankInfo" class="profile__rank" data-testid="profile-rank">
          <span class="profile__rank-label" data-testid="profile-rank-label">{{ readString(rankInfo, 'label') }}</span>
          <div class="profile__bar profile__bar--rank" role="img" :aria-label="'段位进度 ' + rankFill + '%'">
            <div class="profile__bar-fill profile__bar-fill--rank"
                 data-testid="profile-rank-fill" :style="{ width: rankFill + '%' }"></div>
          </div>
          <span v-if="rankNextText" class="profile__bar-text" data-testid="profile-rank-note">{{ rankNextText }}</span>
        </section>
        <p v-else-if="!isSelf && !showRank" class="profile__private" data-testid="profile-rank-private">
          该玩家未公开段位信息。
        </p>

        <section v-if="showStats" class="profile__stats" data-testid="profile-stats" aria-label="战绩">
          <div class="profile__stat"><b data-testid="profile-stat-streak">{{ streak }}</b><span>最高连胜</span></div>
          <div class="profile__stat"><b data-testid="profile-stat-rate">{{ winRateText }}</b><span>胜率</span></div>
          <div class="profile__stat"><b data-testid="profile-stat-total">{{ totalMatches }}</b><span>总场次</span></div>
        </section>
        <p v-else class="profile__private" data-testid="profile-stats-private">该玩家未公开战绩亮点。</p>

        <section v-if="badges.length" class="profile__block" data-testid="profile-badges" aria-label="徽章墙">
          <h3 class="profile__block-title">
            徽章墙
            <span class="profile__badge-count" data-testid="profile-badge-count">
              已解锁 {{ badgeUnlocked }} / {{ badgeTotal }}
            </span>
          </h3>
          <ul class="profile__badge-list">
            <li
              v-for="badge in badges"
              :key="readString(badge, 'id')"
              class="profile__badge"
              :class="{ 'is-locked': badge.unlocked !== true }"
              :data-testid="'profile-badge-' + readString(badge, 'id')"
              :title="readString(badge, 'requirement')"
            >
              <b>{{ readString(badge, 'name') }}</b>
              <span>{{ badge.unlocked === true ? readString(badge, 'desc') : readString(badge, 'requirement') }}</span>
            </li>
          </ul>
        </section>

        <section v-if="showFavCards" class="profile__block" data-testid="profile-favcards" aria-label="最爱用的卡">
          <h3 class="profile__block-title">最爱用的卡</h3>
          <ul v-if="favCards.length" class="profile__fav-list">
            <li v-for="card in favCards" :key="readString(card, 'name')"
                class="profile__fav" :data-testid="'profile-favcard-' + readString(card, 'name')">
              <span>{{ readString(card, 'name') }}</span>
              <small>{{ readNumber(card, 'uses') ?? 0 }} 次</small>
            </li>
          </ul>
          <p v-else class="profile__private">还没有常用的卡牌记录。</p>
        </section>
        <p v-else class="profile__private" data-testid="profile-favcards-private">该玩家未公开最爱用的卡。</p>

        <section v-if="showHistory" class="profile__block" data-testid="profile-history" aria-label="历史战绩">
          <h3 class="profile__block-title">历史战绩</h3>
          <ul v-if="history.length" class="profile__history">
            <li v-for="row in history" :key="readString(row, 'match_id')"
                class="profile__history-row"
                :data-testid="'profile-history-row-' + readString(row, 'match_id')">
              <span class="profile__history-time">{{ historyTime(row) }}</span>
              <span class="profile__history-opp">
                vs {{ historyOpponent(row) }}
                <small v-if="modeLabel(row.mode)">· {{ modeLabel(row.mode) }}</small>
              </span>
              <b :class="historyResult(row) === '胜' ? 'is-win' : 'is-lose'">{{ historyResult(row) }}</b>
              <button
                v-if="row.has_replay === true"
                type="button"
                class="button button--small"
                :data-testid="'profile-history-replay-' + readString(row, 'match_id')"
                @click="openReplay(readString(row, 'match_id'))"
              >
                回放
              </button>
            </li>
          </ul>
          <p v-else class="profile__private" data-testid="profile-history-empty">{{ historyEmptyText }}</p>
        </section>
        <p v-else class="profile__private" data-testid="profile-history-private">该玩家未公开对局历史。</p>

        <footer class="profile__meta" data-testid="profile-meta">
          <span v-if="createdAt" data-testid="profile-meta-joined">加入于 {{ createdAt }}</span>
          <span v-if="winsRank" data-testid="profile-meta-rank">战绩榜第 {{ winsRank }} 名</span>
          <span data-testid="profile-meta-record">{{ wins }} 胜 {{ losses }} 负</span>
        </footer>
      </article>

      <div class="profile__actions">
        <button v-if="isSelf" type="button" class="button" data-testid="profile-settings-link" @click="openSettings">
          隐私与设置
        </button>
        <button type="button" class="button button--ghost" data-testid="profile-back" @click="back">
          返回排行榜
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
/* C+ profile: one 800px modal column with a violet hero band, then the
   information blocks stacked inside the same card. */
.profile {
  align-items: center;
  gap: 0;
  padding: 0 24px 40px;
}

.profile__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 14px;
  width: 800px;
  max-width: 100%;
  padding: 14px 26px 10px;
  border: 1px solid var(--panel-line);
  border-bottom: 0;
  border-radius: var(--radius) var(--radius) 0 0;
  background: var(--panel);
}

.profile__eyebrow {
  margin: 0;
  color: var(--text-secondary);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.profile__title {
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
}

.profile__viewing {
  margin: 0 0 0 auto;
  color: var(--text-muted);
  font-size: 12px;
}

.profile__state,
.profile__login {
  width: 800px;
  max-width: 100%;
  margin: 0;
  padding: 14px 26px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  color: var(--text-muted);
  font-size: 13px;
}

.profile__state--error {
  border-color: var(--danger);
  color: var(--danger);
}

.profile__login h2 {
  margin: 0 0 6px;
  color: var(--text);
  font-size: 18px;
}

.profile__login p {
  margin: 0 0 10px;
}

.profile__card {
  display: grid;
  gap: 12px;
  width: 800px;
  max-width: 100%;
  padding: 0 0 18px;
  overflow: hidden;
  border: 1px solid var(--panel-line);
  border-radius: 0 0 var(--radius) var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.profile__card[data-bg='graphite'] {
  background: linear-gradient(160deg, #232a30, #10151a 70%);
}

.profile__card[data-bg='cyber'] {
  background: linear-gradient(160deg, #2a1840, #0f1a2c 70%);
}

.profile__card[data-bg='lava'] {
  background: linear-gradient(160deg, #3a1a12, #1a0f0c 70%);
}

.profile__hero {
  position: relative;
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 4px;
  padding: 124px 26px 10px;
}

.profile__hero::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 152px;
  border-bottom: 1px solid color-mix(in srgb, var(--role-action) 40%, transparent);
  background:
    repeating-linear-gradient(115deg, rgba(255, 255, 255, 0.06) 0 2px, transparent 2px 12px),
    radial-gradient(300px 120px at 22% 0%, rgba(255, 255, 255, 0.24), transparent 72%),
    linear-gradient(120deg, #7a5af0, #4029a4 70%);
}

.profile__avatar-wrap {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.profile__avatar {
  width: 88px;
  height: 88px;
  border: 3px solid rgba(11, 13, 24, 0.65);
  border-radius: 50%;
  object-fit: cover;
  background: #151a30;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.4);
}

.profile__avatar[data-frame='gold'] {
  border-color: var(--gold-strong);
}

.profile__avatar[data-frame='silver'] {
  border-color: #c6d3dd;
}

.profile__avatar[data-frame='aurora'] {
  border-color: var(--success);
}

.profile__avatar--empty {
  display: grid;
  place-items: center;
  color: var(--role-action);
  font-size: 34px;
}

.profile__level {
  padding: 1px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: rgba(11, 13, 24, 0.72);
  color: var(--gold-strong);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.profile__who {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding-bottom: 4px;
}

.profile__name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 22px;
}

.profile__name .is-rainbow {
  background: linear-gradient(90deg, var(--role-enemy), var(--gold-strong), #6fe0a0, #4ec8e0);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.profile__title-chip {
  padding: 2px 8px;
  border: 1px solid color-mix(in srgb, var(--gold) 50%, transparent);
  border-radius: 999px;
  background: var(--gold-soft);
  color: var(--gold-strong);
  font-size: 11px;
}

.profile__status {
  margin: 0;
  color: var(--text);
  font-size: 13px;
}

.profile__signature {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.profile__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.profile__tag {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 11px;
}

.profile__bar-row,
.profile__rank,
.profile__stats,
.profile__block,
.profile__meta,
.profile__actions {
  margin-left: 26px;
  margin-right: 26px;
}

.profile__bar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.profile__bar {
  flex: 1 1 160px;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-sunken);
}

.profile__bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--role-success), var(--success));
}

.profile__bar-fill--rank {
  background: linear-gradient(90deg, var(--gold), var(--gold-strong));
}

.profile__bar-text {
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.profile__rank {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius-sm);
  background: var(--surface-deck);
}

.profile__rank-label {
  color: var(--gold-strong);
  font-size: 14px;
}

.profile__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.profile__stat {
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid rgba(42, 51, 88, 0.6);
  border-radius: var(--radius-sm);
  background: var(--surface-deck);
}

.profile__stat b {
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.profile__stat span {
  color: var(--text-muted);
  font-size: 11px;
}

.profile__block {
  padding: 12px 14px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius-sm);
  background: var(--surface-deck);
}

.profile__block-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 10px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 12px;
  letter-spacing: 0.06em;
}

.profile__badge-count {
  color: var(--accent-strong);
  letter-spacing: 0;
}

.profile__badge-list {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.profile__badge {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 9px 8px;
  border: 1px dashed var(--line-dash);
  border-radius: 8px;
  background: rgba(124, 92, 240, 0.06);
  text-align: center;
}

.profile__badge b {
  color: var(--gold-strong);
  font-size: 12px;
}

.profile__badge span {
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.35;
}

.profile__badge.is-locked {
  opacity: 0.6;
}

.profile__badge.is-locked b {
  color: var(--text-muted);
}

.profile__fav-list,
.profile__history {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.profile__fav {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid rgba(124, 92, 240, 0.45);
  border-radius: 8px;
  background: var(--accent-soft);
  font-size: 12px;
}

.profile__fav small {
  color: var(--text-muted);
}

.profile__history {
  flex-direction: column;
  gap: 4px;
}

.profile__history-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--surface-deck);
  font-size: 12px;
}

.profile__history-time {
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

.profile__history-opp {
  flex: 1;
  min-width: 0;
}

.profile__history-row .is-win {
  color: var(--success);
}

.profile__history-row .is-lose {
  color: var(--role-enemy);
}

.profile__private {
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
}

.profile__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  padding-top: 10px;
  border-top: 1px dashed var(--line-dash);
  color: var(--text-muted);
  font-size: 11px;
}

.profile__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.profile__actions .button {
  min-height: 40px;
  padding: 8px 18px;
}

.profile__actions [data-testid='profile-settings-link'] {
  border-color: var(--accent-strong);
  background: var(--hero-grad);
  color: #fff;
}

.button--ghost {
  border-color: var(--border-strong);
  background: var(--surface-deck);
  color: var(--text-muted);
}

.profile__quick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 800px;
  max-width: 100%;
  padding: 0 0 10px;
}

.profile__quick-item {
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: var(--surface-chamber);
  color: var(--text-secondary);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.profile__quick-item:hover {
  border-color: var(--role-self);
  color: var(--text-primary);
  background: var(--role-self-soft);
}

@media (max-width: 719px) {
  .profile__quick-item,
  .profile__actions .button,
  .profile__actions button,
  .profile__history-row button {
    min-height: 44px;
    min-width: 44px;
  }
}

@media (max-width: 760px) {
  .profile {
    padding: 0 12px 30px;
  }

  .profile__head {
    padding: 12px 16px 8px;
  }

  .profile__hero {
    padding: 104px 16px 8px;
  }

  .profile__hero::before {
    height: 128px;
  }

  .profile__avatar {
    width: 68px;
    height: 68px;
  }

  .profile__bar-row,
  .profile__rank,
  .profile__stats,
  .profile__block,
  .profile__meta,
  .profile__actions {
    margin-left: 16px;
    margin-right: 16px;
  }

  .profile__badge-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .profile__stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
  }
}
</style>
