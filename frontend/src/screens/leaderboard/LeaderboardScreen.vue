<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useLeaderboardStore, type JsonObject } from '../../stores/leaderboard'
import { useProfileStore } from '../../stores/profile'

/**
 * Ticket #25: the leaderboard screen.
 *
 * Two independent server-sorted sources (wins board / ranked board). This screen
 * never re-sorts or recomputes a tier: every label, position and points value is
 * rendered exactly as the endpoint returned it.
 */
const router = useRouter()
const board = useLeaderboardStore()
const profile = useProfileStore()

onMounted(async () => {
  await profile.loadOwn()
  // The wins-board position lives on /user_stats, not on /api/profile; fetch it
  // for the pinned 我的名次 row instead of guessing from the rendered page.
  if (profile.viewerName) await profile.loadPublic(profile.viewerName)
  if (board.record.status === 'idle') await board.loadRecord()
})

const meName = computed(() => profile.viewerName)

function text(row: JsonObject | null | undefined, key: string): string {
  const value = row ? row[key] : ''
  return value === null || value === undefined ? '' : String(value)
}

function numberText(row: JsonObject | null | undefined, key: string): string {
  const value = Number(row ? row[key] : 0)
  return Number.isFinite(value) ? String(value) : '0'
}

function winRate(row: JsonObject): string {
  const wins = Number(row.wins) || 0
  const losses = Number(row.losses) || 0
  const total = wins + losses
  return total ? Math.round((wins / total) * 100) + '%' : '—'
}

const activeTab = computed(() => board.activeTab)
const activeBoard = computed(() => board.active)

/** Server-position of the viewer on the board that is currently shown. */
const myRankPosition = computed(() => {
  if (activeTab.value === 'ranked') {
    const rank = board.ranked.myRank
    return typeof rank === 'number' && rank > 0 ? String(rank) : '暂无'
  }
  const stats = profile.viewed.stats
  const rank = Number(stats ? stats.rank : NaN)
  return Number.isFinite(rank) && rank > 0 ? String(rank) : '暂无'
})
const myRankNote = computed(() =>
  activeTab.value === 'ranked' ? '全服排位名次' : '全服战绩名次',
)
const podiumRows = computed(() => {
  const rows = activeBoard.value.rows.slice(0, 3)
  if (rows.length < 3) return rows.map((row, index) => ({ row, place: index + 1 }))
  return [
    { row: rows[1], place: 2 },
    { row: rows[0], place: 1 },
    { row: rows[2], place: 3 },
  ]
})

function podiumValue(row: JsonObject): string {
  return activeTab.value === 'ranked' ? numberText(row, 'points') : numberText(row, 'wins')
}

function podiumLabel(): string {
  return activeTab.value === 'ranked' ? '排位分' : '胜场'
}

function isMe(row: JsonObject): boolean {
  const name = text(row, 'username')
  return Boolean(name) && name === meName.value
}

function openTab(tab: 'record' | 'ranked'): void {
  if (tab === activeTab.value) return
  board.setTab(tab)
}

function openUser(username: string): void {
  if (!username) return
  // from=… lets the profile card return to the board the player came from.
  void router.push({ name: 'profile', query: { username, from: 'leaderboard' } })
}

function backHome(): void {
  void router.push({ name: 'start' })
}
</script>

<template>
  <section
    class="screen leaderboard"
    data-screen="leaderboard"
    data-testid="screen-leaderboard"
    :data-tab="activeTab"
    aria-labelledby="screen-leaderboard-title"
  >
    <header class="leaderboard__head">
      <p class="leaderboard__eyebrow">竞技场 · 排行</p>
      <h1 id="screen-leaderboard-title" class="leaderboard__title" data-testid="leaderboard-heading">排行榜</h1>
      <p class="leaderboard__hint">
        战绩榜按胜场排序，段位榜按排位分排序；两张榜都是服务端排好的名次。
      </p>
    </header>

    <div class="leaderboard__tabs" data-testid="leaderboard-tabs" role="tablist" aria-label="榜单">
      <button
        type="button"
        class="leaderboard__tab"
        data-testid="leaderboard-tab-record"
        role="tab"
        :aria-selected="activeTab === 'record' ? 'true' : 'false'"
        :class="{ 'is-active': activeTab === 'record' }"
        @click="openTab('record')"
      >
        战绩榜
      </button>
      <button
        type="button"
        class="leaderboard__tab"
        data-testid="leaderboard-tab-ranked"
        role="tab"
        :aria-selected="activeTab === 'ranked' ? 'true' : 'false'"
        :class="{ 'is-active': activeTab === 'ranked' }"
        @click="openTab('ranked')"
      >
        段位榜
      </button>
    </div>

    <p v-if="activeTab === 'ranked' && activeBoard.status === 'loading' && activeBoard.rows.length === 0"
       class="leaderboard__state" data-testid="leaderboard-ranked-loading" role="status">
      正在加载段位榜…
    </p>
    <p v-if="activeTab === 'record' && activeBoard.status === 'loading' && activeBoard.rows.length === 0"
       class="leaderboard__state" data-testid="leaderboard-loading" role="status">
      正在加载战绩榜…
    </p>

    <p v-if="activeTab === 'record' && activeBoard.status === 'error'"
       class="leaderboard__error" data-testid="leaderboard-error" role="alert">
      无法加载排行榜：{{ activeBoard.error }}
    </p>
    <p v-if="activeTab === 'ranked' && activeBoard.status === 'error'"
       class="leaderboard__error" data-testid="leaderboard-ranked-error" role="alert">
      无法加载段位榜：{{ activeBoard.error }}
    </p>

    <p v-if="activeTab === 'record' && activeBoard.status === 'ready' && activeBoard.rows.length === 0"
       class="leaderboard__state" data-testid="leaderboard-empty">
      榜单还空着 —— 打完第一局并产生胜负记录后就会出现在这里。
    </p>
    <p v-if="activeTab === 'ranked' && activeBoard.status === 'ready' && activeBoard.rows.length === 0"
       class="leaderboard__state" data-testid="leaderboard-ranked-empty">
      还没有人打过排位 —— 打一场排位赛就会出现在这里。
    </p>

    <section
      class="leaderboard__my-rank"
      data-testid="leaderboard-my-rank"
      :data-board="activeTab"
      aria-label="我的名次"
    >
      <span class="leaderboard__my-rank-label">我的名次</span>
      <b class="leaderboard__my-rank-value" data-testid="leaderboard-my-rank-position">{{ myRankPosition }}</b>
      <span class="leaderboard__my-rank-note" data-testid="leaderboard-my-rank-note">{{ myRankNote }}</span>
    </section>

    <div v-if="podiumRows.length" class="leaderboard__podium" data-testid="leaderboard-podium" aria-label="前三名">
      <button
        v-for="item in podiumRows"
        :key="'podium-' + text(item.row, 'username')"
        type="button"
        class="leaderboard__podium-card"
        :class="{ 'is-me': isMe(item.row) }"
        :data-testid="'leaderboard-podium-' + text(item.row, 'username')"
        :data-place="activeTab === 'ranked' ? numberText(item.row, 'position') : String(item.place)"
        @click="openUser(text(item.row, 'username'))"
      >
        <span class="leaderboard__podium-name">{{ text(item.row, 'username') || '未知玩家' }}</span>
        <b class="leaderboard__podium-score">{{ podiumValue(item.row) }}</b>
        <small class="leaderboard__podium-label">{{ podiumLabel() }}</small>
      </button>
    </div>

    <div v-if="activeTab === 'record'" class="leaderboard__table-wrap" data-testid="leaderboard-scroll">
      <table class="leaderboard__table" data-testid="leaderboard-table">
        <thead>
          <tr>
            <th scope="col">排名</th>
            <th scope="col">玩家</th>
            <th scope="col">胜</th>
            <th scope="col">负</th>
            <th scope="col">胜率</th>
            <th scope="col">最长连胜</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, index) in activeBoard.rows"
            :key="'record-' + text(row, 'username')"
            :data-testid="'leaderboard-row-' + text(row, 'username')"
            :data-me="isMe(row) ? 'true' : 'false'"
            :class="{ 'is-me': isMe(row) }"
            @click="openUser(text(row, 'username'))"
          >
            <td>{{ index + 1 }}</td>
            <td class="leaderboard__player">
              <button
                type="button"
                class="leaderboard__user"
                :data-testid="'leaderboard-open-' + text(row, 'username')"
                :title="'查看 ' + (text(row, 'username') || '玩家') + ' 的名片'"
                @click="openUser(text(row, 'username'))"
              >
                <img
                  v-if="text(row, 'avatar')"
                  class="leaderboard__avatar"
                  :src="text(row, 'avatar')"
                  alt=""
                />
                <span :class="['leaderboard__name', { 'is-rainbow': text(row, 'name_style') === 'rainbow' }]">
                  {{ text(row, 'username') || '未知玩家' }}
                </span>
                <span class="leaderboard__open-hint" aria-hidden="true">名片 ↗</span>
              </button>
            </td>
            <td class="leaderboard__num">{{ numberText(row, 'wins') }}</td>
            <td class="leaderboard__num">{{ numberText(row, 'losses') }}</td>
            <td class="leaderboard__num">{{ winRate(row) }}</td>
            <td class="leaderboard__num">{{ numberText(row, 'longest_streak') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else class="leaderboard__table-wrap" data-testid="leaderboard-scroll">
      <table class="leaderboard__table" data-testid="leaderboard-ranked-table">
        <thead>
          <tr>
            <th scope="col">名次</th>
            <th scope="col">玩家</th>
            <th scope="col">段位</th>
            <th scope="col">排位分</th>
            <th scope="col">战绩</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in activeBoard.rows"
            :key="'ranked-' + text(row, 'username')"
            :data-testid="'leaderboard-ranked-row-' + text(row, 'username')"
            :data-me="isMe(row) ? 'true' : 'false'"
            :class="{ 'is-me': isMe(row) }"
            @click="openUser(text(row, 'username'))"
          >
            <td>{{ numberText(row, 'position') }}</td>
            <td class="leaderboard__player">
              <button
                type="button"
                class="leaderboard__user"
                :data-testid="'leaderboard-ranked-open-' + text(row, 'username')"
                :title="'查看 ' + (text(row, 'username') || '玩家') + ' 的名片'"
                @click="openUser(text(row, 'username'))"
              >
                <img
                  v-if="text(row, 'avatar')"
                  class="leaderboard__avatar"
                  :src="text(row, 'avatar')"
                  alt=""
                />
                <span :class="['leaderboard__name', { 'is-rainbow': text(row, 'name_style') === 'rainbow' }]">
                  {{ text(row, 'username') || '未知玩家' }}
                </span>
                <span class="leaderboard__open-hint" aria-hidden="true">名片 ↗</span>
              </button>
            </td>
            <td>
              <span class="leaderboard__tier" :data-tier="text(row, 'tier_id')">
                {{ text(row, 'label') || text(row, 'tier_name') || '—' }}
              </span>
            </td>
            <td class="leaderboard__num">{{ numberText(row, 'points') }}</td>
            <td class="leaderboard__num">
              {{ numberText(row, 'ranked_wins') }} 胜 {{ numberText(row, 'ranked_losses') }} 负
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="leaderboard__actions">
      <button type="button" class="button button--ghost" data-testid="leaderboard-back-home" @click="backHome">
        返回首页
      </button>
    </footer>
  </section>
</template>

<style scoped>
.leaderboard {
  gap: 14px;
  padding-top: 8px;
}

.leaderboard__eyebrow {
  margin: 0 0 2px;
  color: var(--text-secondary);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.leaderboard__title {
  margin: 0;
  font-size: 30px;
  line-height: 1.2;
}

.leaderboard__hint {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

/* Tabs are a full-width rail with the two labels centred, as in C+. */
.leaderboard__tabs {
  display: flex;
  justify-content: center;
  gap: 2px;
  padding: 4px;
  border: 1px solid var(--panel-line);
  border-radius: 8px;
  background: var(--panel);
  align-self: stretch;
}

.leaderboard__tab {
  padding: 7px 20px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.leaderboard__tab:hover {
  color: var(--text);
}

.leaderboard__tab.is-active {
  border-color: color-mix(in srgb, var(--role-action) 60%, transparent);
  background: var(--accent-soft);
  color: var(--text);
}

.leaderboard__state,
.leaderboard__error {
  width: min(1040px, 100%);
  margin: 0 auto;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  color: var(--text-muted);
  font-size: 13px;
}

.leaderboard__error {
  border-color: var(--danger);
  color: var(--danger);
}

/* Podium + table share one 1040px column centred under the full-width rail. */
.leaderboard__podium {
  display: grid;
  grid-template-columns: repeat(3, 335px);
  gap: 20px;
  justify-content: start;
  width: 100%;
  max-width: 1040px;
  margin: 4px auto 0;
}

.leaderboard__podium-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 202px;
  padding: 16px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: linear-gradient(160deg, var(--surface-elevated), #12172e);
  color: var(--text);
  font: inherit;
  text-align: center;
  cursor: pointer;
  box-shadow: var(--shadow-panel);
}

.leaderboard__podium-card::before {
  content: '';
  width: 72px;
  height: 72px;
  border: 2px solid color-mix(in srgb, var(--role-action) 40%, transparent);
  border-radius: 50%;
  background: radial-gradient(circle at 50% 38%, #e8ecff 0 30%, var(--text-tertiary) 31% 46%, #6d7aa8 47% 100%);
  box-shadow: inset 0 0 0 4px rgba(11, 13, 24, 0.55);
}

.leaderboard__podium-card::after {
  content: attr(data-place);
  position: absolute;
  top: 10px;
  left: 14px;
  color: var(--text-muted);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.leaderboard__podium-card[data-place='1'] {
  border-color: rgba(201, 162, 76, 0.65);
  box-shadow: 0 0 24px rgba(201, 162, 76, 0.16), var(--shadow-panel);
}

.leaderboard__podium-card[data-place='1']::before {
  border-color: rgba(201, 162, 76, 0.8);
}

.leaderboard__podium-card[data-place='1']::after {
  color: var(--gold-strong);
}

.leaderboard__podium-card.is-me {
  outline: 1px solid var(--accent);
  outline-offset: -1px;
}

.leaderboard__podium-name {
  max-width: 100%;
  overflow: hidden;
  color: var(--text);
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.leaderboard__podium-score {
  color: var(--gold-strong);
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}

.leaderboard__podium-label {
  color: var(--text-muted);
  font-size: 11px;
}

.leaderboard__table-wrap {
  width: 100%;
  max-width: 1040px;
  margin: 0 auto;
  overflow-x: auto;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.leaderboard__table {
  width: 100%;
  min-width: 640px;
  border-collapse: collapse;
  font-size: 13px;
}

.leaderboard__table th,
.leaderboard__table td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px dashed var(--surface-elevated);
  white-space: nowrap;
}

.leaderboard__table thead th {
  color: var(--text-muted);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.08em;
}

.leaderboard__table tbody tr:last-child td {
  border-bottom: 0;
}

.leaderboard__table tbody tr.is-me {
  background: var(--accent-soft);
}

.leaderboard__user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  cursor: pointer;
}

.leaderboard__avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  object-fit: cover;
  background: var(--surface-deck);
}

.leaderboard__name.is-rainbow {
  background: linear-gradient(90deg, var(--role-enemy), var(--gold-strong), #6fe0a0, #4ec8e0);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.leaderboard__open-hint {
  color: var(--text-dim);
  font-size: 11px;
}

.leaderboard__num {
  font-variant-numeric: tabular-nums;
}

.leaderboard__tier {
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--gold-strong);
  font-size: 12px;
}

.leaderboard__actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: auto;
  padding-top: 6px;
}

.button--ghost {
  border-color: var(--border-strong);
  background: var(--surface-deck);
  color: var(--text-muted);
}

/* Pinned "my rank" row: outside the scrolling area so it stays visible while
   the board scrolls sideways on narrow screens (ticket #49). */
.leaderboard__my-rank {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 12px;
  width: 100%;
  max-width: 1040px;
  margin: 0 auto;
  padding: 10px 16px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--role-action-soft);
}

.leaderboard__my-rank-label {
  color: var(--text-secondary);
  font-size: 12px;
}

.leaderboard__my-rank-value {
  color: var(--role-action);
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.leaderboard__my-rank-note {
  margin-left: auto;
  color: var(--text-tertiary);
  font-size: 11px;
}

.leaderboard__table tbody tr {
  cursor: pointer;
}

.leaderboard__table tbody tr:hover {
  background: var(--role-self-soft);
}

@media (max-width: 719px) {
  button[data-testid],
  a[data-testid] {
    min-height: 44px;
    min-width: 44px;
  }

  .leaderboard__tab,
  .leaderboard__actions .button,
  .leaderboard__actions [data-testid='leaderboard-back-home'] {
    min-height: 44px;
    min-width: 44px;
  }
}

@media (max-width: 1100px) {
  .leaderboard__podium {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
  }

  .leaderboard__podium-card {
    height: 180px;
  }
}

@media (max-width: 640px) {
  .leaderboard__podium {
    grid-template-columns: 1fr;
  }

  .leaderboard__podium-card {
    height: auto;
    min-height: 140px;
    padding: 12px;
  }

  .leaderboard__podium-card::before {
    width: 56px;
    height: 56px;
  }
}
</style>
