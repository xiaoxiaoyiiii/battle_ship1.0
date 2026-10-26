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

function playerInitial(row: JsonObject): string {
  return Array.from(text(row, 'username').trim())[0] || '舰'
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
      <div>
      <h1 id="screen-leaderboard-title" class="leaderboard__title" data-testid="leaderboard-heading">排行榜</h1>
      <p class="leaderboard__hint">
        每一场对局，都留下你的航迹。
      </p>
      </div>

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
    </header>

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

    <div class="leaderboard__highlights">
    <section
      class="leaderboard__my-rank"
      data-testid="leaderboard-my-rank"
      :data-board="activeTab"
      aria-label="我的名次"
    >
      <h2 class="leaderboard__my-rank-label">我的名次</h2>
      <div class="leaderboard__my-rank-number">
        <b class="leaderboard__my-rank-value" data-testid="leaderboard-my-rank-position">{{ myRankPosition }}</b>
        <span v-if="myRankPosition !== '暂无'">名</span>
      </div>
      <span class="leaderboard__my-rank-note" data-testid="leaderboard-my-rank-note">{{ myRankNote }}</span>
      <p class="leaderboard__my-rank-help">{{ meName ? '点击榜单中的玩家，查看名片与战绩。' : '登录后可在这里查看自己的名次。' }}</p>
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
        <span class="leaderboard__podium-place">{{ activeTab === 'ranked' ? numberText(item.row, 'position') : item.place }}</span>
        <span class="leaderboard__podium-avatar">
          <img v-if="text(item.row, 'avatar')" :src="text(item.row, 'avatar')" alt="" />
          <span v-else>{{ playerInitial(item.row) }}</span>
        </span>
        <span class="leaderboard__podium-name">{{ text(item.row, 'username') || '未知玩家' }}</span>
        <span v-if="activeTab === 'ranked'" class="leaderboard__podium-tier">{{ text(item.row, 'label') || text(item.row, 'tier_name') || '—' }}</span>
        <span class="leaderboard__podium-result">
          <b class="leaderboard__podium-score">{{ podiumValue(item.row) }}</b>
          <small class="leaderboard__podium-label">{{ podiumLabel() }}</small>
        </span>
        <span v-if="item.place === 1" class="leaderboard__podium-leader">榜首舰长</span>
      </button>
    </div>
    </div>

    <p class="leaderboard__scroll-hint">左右滑动榜单，可查看完整战绩。</p>
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
            <td class="leaderboard__position" :data-top="index < 3 ? String(index + 1) : undefined">{{ index + 1 }}</td>
            <td class="leaderboard__player">
              <button
                type="button"
                class="leaderboard__user"
                :data-testid="'leaderboard-open-' + text(row, 'username')"
                :title="'查看 ' + (text(row, 'username') || '玩家') + ' 的名片'"
                @click.stop="openUser(text(row, 'username'))"
              >
                <img
                  v-if="text(row, 'avatar')"
                  class="leaderboard__avatar"
                  :src="text(row, 'avatar')"
                  alt=""
                />
                <span v-else class="leaderboard__avatar leaderboard__avatar--initial" aria-hidden="true">{{ playerInitial(row) }}</span>
                <span :class="['leaderboard__name', { 'is-rainbow': text(row, 'name_style') === 'rainbow' }]">
                  {{ text(row, 'username') || '未知玩家' }}
                </span>
                <span v-if="isMe(row)" class="leaderboard__me-tag">我</span>
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
            <td class="leaderboard__position" :data-top="Number(row.position) <= 3 ? numberText(row, 'position') : undefined">{{ numberText(row, 'position') }}</td>
            <td class="leaderboard__player">
              <button
                type="button"
                class="leaderboard__user"
                :data-testid="'leaderboard-ranked-open-' + text(row, 'username')"
                :title="'查看 ' + (text(row, 'username') || '玩家') + ' 的名片'"
                @click.stop="openUser(text(row, 'username'))"
              >
                <img
                  v-if="text(row, 'avatar')"
                  class="leaderboard__avatar"
                  :src="text(row, 'avatar')"
                  alt=""
                />
                <span v-else class="leaderboard__avatar leaderboard__avatar--initial" aria-hidden="true">{{ playerInitial(row) }}</span>
                <span :class="['leaderboard__name', { 'is-rainbow': text(row, 'name_style') === 'rainbow' }]">
                  {{ text(row, 'username') || '未知玩家' }}
                </span>
                <span v-if="isMe(row)" class="leaderboard__me-tag">我</span>
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
      <p>战绩榜按胜场排序，段位榜按排位分排序。点击玩家查看名片。</p>
      <button type="button" class="button button--ghost" data-testid="leaderboard-back-home" @click="backHome">
        返回首页
      </button>
    </footer>
  </section>
</template>

<style scoped>
.leaderboard { width: min(1490px, 100%); margin: 0 auto; gap: 20px; padding: 24px 28px 28px; }
.leaderboard__head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 18px 24px; }
.leaderboard__title { margin: 0; color: var(--text-primary); font-size: 30px; line-height: 1.25; }
.leaderboard__hint { margin: 6px 0 0; color: var(--text-secondary); font-size: 14px; }
.leaderboard__tabs { display: flex; align-self: center; padding: 4px; gap: 3px; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--surface-deck); }
.leaderboard__tab { min-height: 36px; padding: 7px 16px; border: 1px solid transparent; border-radius: 4px; background: transparent; color: var(--text-secondary); font: inherit; font-size: 13px; cursor: pointer; transition: background var(--duration-fast) var(--ease), color var(--duration-fast) var(--ease); }
.leaderboard__tab:hover { color: var(--text-primary); background: var(--role-self-soft); }
.leaderboard__tab.is-active { border-color: var(--border-subtle); background: var(--surface-raised); color: var(--text-primary); }
.leaderboard__state, .leaderboard__error { margin: 0; padding: 15px 18px; border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--panel); color: var(--text-secondary); font-size: 14px; line-height: 1.7; overflow-wrap: anywhere; }
.leaderboard__error { border-color: color-mix(in srgb, var(--role-enemy) 40%, transparent); background: var(--role-enemy-soft); color: var(--role-enemy); }
.leaderboard__highlights { display: grid; grid-template-columns: minmax(0, 1fr) minmax(230px, 280px); align-items: stretch; gap: 24px; padding-top: 6px; }
.leaderboard__podium { display: grid; grid-column: 1; grid-row: 1; grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: end; gap: 16px; min-width: 0; padding: 16px 12px 0; }
.leaderboard__podium-card { --podium-color: var(--text-secondary); position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-width: 0; min-height: 182px; height: 100%; padding: 20px 18px; border: 1px solid var(--border-subtle); border-radius: 11px; background: var(--panel); color: var(--text-primary); font: inherit; text-align: center; cursor: pointer; transition: border-color var(--duration-fast) var(--ease), background var(--duration-fast) var(--ease); }
.leaderboard__podium-card:hover { border-color: var(--podium-color); background: var(--surface-raised); }
.leaderboard__podium-card[data-place='1'] { --podium-color: var(--gold-strong); margin-top: -16px; height: calc(100% + 16px); border-color: color-mix(in srgb, var(--gold) 60%, transparent); background: linear-gradient(155deg, color-mix(in srgb, var(--gold) 7%, var(--surface-chamber)), var(--surface-deck)); }
.leaderboard__podium-card[data-place='2'] { --podium-color: color-mix(in srgb, var(--role-self) 30%, var(--text-secondary)); }
.leaderboard__podium-card[data-place='3'] { --podium-color: color-mix(in srgb, var(--gold) 60%, var(--text-secondary)); }
.leaderboard__podium-card.is-me { box-shadow: inset 0 0 0 1px var(--role-self); }
.leaderboard__podium-place { position: absolute; top: 16px; left: 18px; color: var(--podium-color); font-size: 25px; font-variant-numeric: tabular-nums; font-style: italic; font-weight: 400; }
.leaderboard__podium-avatar { display: grid; flex: 0 0 48px; place-items: center; width: 48px; height: 48px; overflow: hidden; border: 1px solid color-mix(in srgb, var(--podium-color) 65%, transparent); border-radius: 50%; background: color-mix(in srgb, var(--podium-color) 12%, transparent); color: var(--podium-color); font-size: 23px; font-weight: 650; }
.leaderboard__podium-avatar img { width: 100%; height: 100%; object-fit: cover; }
.leaderboard__podium-name { max-width: 100%; color: var(--text-primary); font-size: 15px; font-weight: 650; line-height: 1.4; overflow-wrap: anywhere; }
.leaderboard__podium-tier { color: var(--text-secondary); font-size: 12px; line-height: 1.4; }
.leaderboard__podium-result { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: center; gap: 6px; }
.leaderboard__podium-score { color: var(--text-primary); font-size: 30px; line-height: 1.2; font-variant-numeric: tabular-nums; }
.leaderboard__podium-label { color: var(--text-secondary); font-size: 12px; }
.leaderboard__podium-leader { color: var(--gold-strong); font-size: 12px; }
.leaderboard__my-rank { display: flex; grid-column: 2; grid-row: 1; flex-direction: column; align-items: flex-start; min-width: 0; gap: 10px; padding: 22px; border: 1px solid var(--border-subtle); border-radius: 11px; background: var(--panel); }
.leaderboard__my-rank-label { margin: 0; color: var(--text-primary); font-size: 17px; font-weight: 650; }
.leaderboard__my-rank-number { display: flex; align-items: baseline; gap: 9px; color: var(--text-secondary); font-size: 13px; }
.leaderboard__my-rank-value { color: var(--role-self); font-size: 40px; line-height: 1.2; font-variant-numeric: tabular-nums; }
.leaderboard__my-rank-note { color: var(--text-secondary); font-size: 12px; }
.leaderboard__my-rank-help { margin: auto 0 0; padding-top: 14px; border-top: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 12px; line-height: 1.65; }
.leaderboard__table-wrap { width: 100%; min-width: 0; max-height: 530px; overflow: auto; overscroll-behavior: contain; border: 1px solid var(--border-subtle); border-radius: 11px; background: var(--panel); }
.leaderboard__table { width: 100%; min-width: 680px; border-collapse: separate; border-spacing: 0; color: var(--text-primary); font-size: 14px; }
.leaderboard__table th, .leaderboard__table td { padding: 13px 22px; text-align: right; vertical-align: middle; border-bottom: 1px solid var(--border-subtle); white-space: nowrap; font-variant-numeric: tabular-nums; }
.leaderboard__table th:first-child, .leaderboard__table td:first-child { width: 82px; text-align: left; }
.leaderboard__table th:nth-child(2), .leaderboard__table td:nth-child(2) { width: 38%; text-align: left; }
.leaderboard__table thead th { position: sticky; z-index: 1; top: 0; background: var(--surface-raised); color: var(--text-secondary); font-size: 12px; font-weight: 500; }
.leaderboard__table tbody tr { cursor: pointer; transition: background var(--duration-fast) var(--ease); }
.leaderboard__table tbody tr:hover { background: var(--role-self-soft); }
.leaderboard__table tbody tr:last-child td { border-bottom: 0; }
.leaderboard__table tbody tr.is-me { background: var(--role-self-soft); }
.leaderboard__table tbody tr.is-me td:first-child { box-shadow: inset 3px 0 var(--role-self); }
.leaderboard__position { color: var(--text-tertiary); }
.leaderboard__position[data-top='1'], .leaderboard__position[data-top='2'], .leaderboard__position[data-top='3'] { color: var(--gold-strong); }
.leaderboard__user { display: inline-flex; align-items: center; gap: 11px; max-width: 100%; min-height: 32px; padding: 0; border: 0; background: transparent; color: var(--text-primary); font: inherit; text-align: left; cursor: pointer; }
.leaderboard__avatar { flex: 0 0 30px; width: 30px; height: 30px; border: 1px solid color-mix(in srgb, var(--role-self) 55%, transparent); border-radius: 50%; object-fit: cover; background: var(--role-self-soft); }
.leaderboard__avatar--initial { display: inline-grid; place-items: center; color: var(--role-self); font-size: 14px; }
.leaderboard__name { max-width: 32ch; white-space: normal; overflow-wrap: anywhere; }
.leaderboard__name.is-rainbow { background: linear-gradient(90deg, var(--role-enemy), var(--gold-strong), var(--role-success), var(--role-self)); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.leaderboard__me-tag { flex-shrink: 0; padding: 1px 6px; border: 1px solid var(--border-strong); border-radius: 4px; color: var(--text-secondary); font-size: 11px; }
.leaderboard__num { color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.leaderboard__table td:nth-child(3).leaderboard__num { color: var(--text-primary); font-weight: 650; }
.leaderboard__tier { display: inline-block; padding: 3px 8px; border: 1px solid var(--border-strong); border-radius: 4px; color: var(--gold-strong); font-size: 12px; }
.leaderboard__actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding-top: 0; }
.leaderboard__actions p { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.7; }
.leaderboard__actions .button { min-height: 38px; border-color: var(--border-strong); background: transparent; color: var(--text-secondary); font-size: 13px; }
.leaderboard__scroll-hint { display: none; }
@media (max-width: 1099px) {
  .leaderboard__highlights { grid-template-columns: minmax(0, 1fr) 220px; gap: 14px; }
  .leaderboard__podium { gap: 10px; padding-right: 0; padding-left: 0; }
  .leaderboard__podium-card { padding: 18px 12px; }
  .leaderboard__podium-place { left: 12px; font-size: 22px; }
  .leaderboard__my-rank { padding: 18px; }
}
@media (max-width: 799px) {
  .leaderboard { padding: 20px 18px 24px; }
  .leaderboard__highlights { display: flex; flex-direction: column-reverse; gap: 16px; }
  .leaderboard__my-rank { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 6px 16px; padding: 16px 18px; }
  .leaderboard__my-rank-label { grid-column: 1; grid-row: 1; font-size: 15px; }
  .leaderboard__my-rank-number { grid-column: 1; grid-row: 2; }
  .leaderboard__my-rank-value { font-size: 30px; }
  .leaderboard__my-rank-note { grid-column: 2; grid-row: 1; text-align: right; }
  .leaderboard__my-rank-help { grid-column: 2; grid-row: 2; margin: 0; padding: 0; border: 0; text-align: right; }
  .leaderboard__podium-card { min-height: 168px; }
  .leaderboard__table-wrap { max-height: 520px; }
  .leaderboard__scroll-hint { display: block; margin: 0 0 -12px; color: var(--text-secondary); font-size: 12px; }
}
@media (max-width: 479px) {
  .leaderboard { gap: 16px; padding: 18px 12px 24px; }
  .leaderboard__head { gap: 14px; }
  .leaderboard__title { font-size: 26px; }
  .leaderboard__tabs { width: 100%; }
  .leaderboard__tab { flex: 1; min-height: 44px; }
  .leaderboard__podium { gap: 8px; padding-top: 10px; }
  .leaderboard__podium-card { min-height: 166px; padding: 15px 8px 12px; gap: 7px; }
  .leaderboard__podium-card[data-place='1'] { margin-top: -10px; height: calc(100% + 10px); }
  .leaderboard__podium-place { top: 8px; left: 9px; font-size: 17px; }
  .leaderboard__podium-avatar { flex-basis: 36px; width: 36px; height: 36px; font-size: 18px; }
  .leaderboard__podium-name { font-size: 13px; }
  .leaderboard__podium-score { font-size: 24px; }
  .leaderboard__podium-result { gap: 4px; }
  .leaderboard__podium-label, .leaderboard__podium-tier, .leaderboard__podium-leader { font-size: 11px; }
  .leaderboard__my-rank { padding: 14px; gap: 7px 10px; }
  .leaderboard__my-rank-help { font-size: 11px; }
  .leaderboard__table { min-width: 640px; font-size: 13px; }
  .leaderboard__table th, .leaderboard__table td { padding: 9px 14px; }
  .leaderboard__table th:first-child, .leaderboard__table td:first-child { width: 60px; }
  .leaderboard__user { min-height: 44px; gap: 8px; }
  .leaderboard__table-wrap { max-height: 500px; }
  .leaderboard__actions { flex-direction: column; align-items: stretch; text-align: center; }
  .leaderboard__actions .button { min-height: 44px; }
}
</style>
