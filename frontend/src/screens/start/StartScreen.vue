<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import HomeProgress from './HomeProgress.vue'
import HomeTasks from './HomeTasks.vue'
import MatchFoundOverlay from '../../components/MatchFoundOverlay.vue'
import StateSurface from '../../components/StateSurface.vue'
import { cardArtUrl } from '../../cards/cardArt'
import { CARDS, UNIQUE_CARD_NAMES } from '../../cards/cardData'
import { useAuthStore } from '../../stores/auth'
import { useCollectionStore } from '../../stores/collection'
import { useGameStore } from '../../stores/game'
import { useHomeStore } from '../../stores/home'
import { useUiStore } from '../../stores/ui'
import { AI_DIFFICULTY_KEY, aiDifficulty } from '../game-over/view'
import {
  acquireHomeChannel,
  createAiRoom,
  emitCancelMatch,
  emitFindMatch,
  homeSocket,
} from '../../realtime/home'
import {
  changelogKey,
  DIFFICULTY_OPTIONS,
  numberText,
  playerView,
  queueStatusText,
  statsText,
  waitedSeconds,
} from './view'

/**
 * Ticket #26: the three-column home screen.
 *
 * Reads only the home store; every value there either came from an HTTP read
 * (/api/home_stats, /api/online_count, /api/profile, /api/changelog) or from a
 * server socket frame (match_queued / match_canceled / error). The screen
 * formats those values and never recomputes a rank, level or queue rule.
 *
 * The seat is created here (find_match / create_ai_room), so the screen acquires
 * the shared socket with keepAlive: the route change to /placement must not
 * disconnect the connection the seat is bound to.
 */
const router = useRouter()
const auth = useAuthStore()
const home = useHomeStore()
const game = useGameStore()
const collection = useCollectionStore()
const ui = useUiStore()

const difficulty = ref<string>(aiDifficulty())
const difficultyOptions = DIFFICULTY_OPTIONS
let releaseChannel: (() => void) | null = null
let navigating = false
let waitTimer: number | null = null
/** Ticking queue wait, derived from the store's server-confirmed entry time. */
const queueSeconds = ref(0)

function tickQueue(): void {
  queueSeconds.value = waitedSeconds(home.queueStartedAt, Date.now())
}

function stopQueueTicker(): void {
  if (waitTimer !== null) {
    window.clearInterval(waitTimer)
    waitTimer = null
  }
}

watch(
  () => home.queuePending,
  (pending) => {
    if (pending) {
      tickQueue()
      if (waitTimer === null) waitTimer = window.setInterval(tickQueue, 1000)
      return
    }
    stopQueueTicker()
    queueSeconds.value = 0
  },
  { immediate: true },
)

onMounted(() => {
  releaseChannel = acquireHomeChannel(undefined, {
    onConnect: () => {
      // The online counter includes this very connection once it is up, so the
      // boot snapshot is not enough: refetch the authoritative counters.
      void home.loadStats(true)
    },
  })
  void home.loadStats()
  void home.loadProfile()
  void home.loadChangelog()
  maybeAdvance()
})

onBeforeUnmount(() => {
  releaseChannel?.()
  releaseChannel = null
  stopQueueTicker()
})

const player = computed(() => playerView(home.profile))
/** Identity and profile are separate reads; the guest card follows the session. */
/**
 * One name for the whole session (ticket #44): a logged-in account shows its
 * username, a guest shows the persisted 舰长1234. The same computed is what
 * find_match and create_ai_room submit, so the screen never promises a name the
 * server did not receive (spec story 9).
 */
const playerName = computed(() => (auth.isGuest ? auth.guestName : auth.displayName))
const stats = computed(() => statsText(home.stats))
const queueText = computed(() => queueStatusText(home.queueMode))
const pillText = computed(() => numberText(home.onlinePill))
const latestText = computed(() => {
  return home.changelogLatest
})
const entries = computed(() =>
  home.changelog.map((entry) => ({ ...entry, key: changelogKey(entry) })),
)
/** Async regions share the one StateSurface contract (ticket #42, story 57/90). */
const statsState = computed<'loading' | 'ready' | 'empty' | 'error'>(() => {
  if (home.statsFailed) return 'error'
  if (!home.statsLoaded) return 'loading'
  const counters = home.stats
  const allMissing = [counters.onlineCount, counters.queueCasual, counters.queueRanked, counters.lobbyRooms]
    .every((value) => value === null)
  return allMissing ? 'empty' : 'ready'
})

const profileState = computed<'loading' | 'ready' | 'error'>(() => {
  if (auth.isGuest) return 'ready'
  if (home.profileFailed) return 'error'
  return home.profileLoaded ? 'ready' : 'loading'
})

/** Ranked entry: the current tier and the "this changes rank" warning (story 16). */
const rankedDesc = computed(() => {
  if (auth.isGuest) return '登录后显示段位 · 结算会改变段位'
  return player.value.rankLabel
    ? '当前段位：' + player.value.rankLabel + ' · 结算会改变段位'
    : '结算会改变段位'
})

/** Loading / empty / error / ready for the announcement panel (ticket #42). */
const changelogState = computed<'loading' | 'ready' | 'empty' | 'error'>(() => {
  if (home.changelogFailed) return 'error'
  if (!home.changelogLoaded) return 'loading'
  return entries.value.length ? 'ready' : 'empty'
})

// The screen still renders its own notice line; the shell toast makes the same
// result visible from anywhere (one queue, same wording).
watch(
  () => home.notice,
  (message) => {
    if (message) ui.notify({ code: 'home-notice', tone: 'error', message })
  },
)
const actionsDisabled = computed(() => home.busy || home.awaitingPlacement)
/** 展示原 main 首页的五张完整卡面，计数仍取真实卡表。 */
const showcase = ref(['余音绕梁', '溅射', '失灵！', '禁忌果实', '雷达子弹'])
const hasUsage = ref(false)
onMounted(async () => {
  try {
    const response = await fetch('/api/card_usage')
    if (!response.ok) return
    const body = await response.json() as { usage?: Record<string, number> }
    const ranked = Object.entries(body.usage ?? {}).filter(([name,count]) => UNIQUE_CARD_NAMES.includes(name) && count > 0).sort((a,b) => b[1]-a[1]).map(([name])=>name)
    if (ranked.length) { showcase.value = [...new Set([...ranked,...showcase.value])].slice(0,5); hasUsage.value = true }
  } catch { /* 暂无使用统计时展示原版精选卡面。 */ }
})
const cardCount = UNIQUE_CARD_NAMES.length
const fieldCount = CARDS.filter((card) => card.type === '场地').length

/**
 * Hand-off to placement. A real matchmaking pair first shows the 匹配成功
 * overlay (five-second countdown, legacy screen) and navigates when it emits
 * done; 人机创建成功后也播放演出，自定义房仍按房间流程推进。
 */
function advanceToPlacement(): void {
  if (navigating) return
  navigating = true
  home.placementHandled()
  home.clearMatchFound()
  void router.push({ name: 'placement' })
}

function onMatchFoundDone(): void {
  if (home.awaitingPlacement) advanceToPlacement()
}

function maybeAdvance(): void {
  if (navigating || !home.awaitingPlacement) return
  if (game.state.state !== 'placing_ships') return
  if (home.matchFound) return
  advanceToPlacement()
}

watch(() => game.state.state, maybeAdvance)
// A second match starts from an already-placing_ships store, so the state
// watcher alone would never fire: each placing frame ticks this counter.
watch(() => home.placementSignal, maybeAdvance)

function currentSocket() {
  const socket = homeSocket()
  if (!socket) {
    home.notifyMessage('实时连接还没就绪，请稍后再试')
    return null
  }
  return socket
}

async function startMatch(mode: 'casual' | 'ranked'): Promise<void> {
  // A guest cannot rank (server refuses it); open the login overlay instead of
  // spending the click on a refusal the player cannot act on (spec story 31).
  if (mode === 'ranked' && auth.isGuest) {
    home.notifyMessage('排位对战需要先登录')
    auth.open('login', '排位对战需要先登录，登录后会回到这里继续。')
    return
  }
  const socket = currentSocket()
  if (!socket) return
  home.clearNotice()
  home.beginAction(mode)
  try {
    const ack = await emitFindMatch(socket, playerName.value, mode)
    if (ack.status === 'error') home.notifyMessage(ack.message || '匹配请求被拒绝')
  } catch {
    home.notifyMessage('网络不稳定，请再试一次')
  } finally {
    home.endAction()
  }
}

async function cancelQueue(): Promise<void> {
  home.clearNotice()
  try {
    const socket = currentSocket()
    if (!socket) return
    const ack = await emitCancelMatch(socket)
    home.applyMatchCanceled()
    ui.notify({
      code: 'match-canceled',
      tone: ack.status === 'success' ? 'info' : 'warning',
      message: ack.status === 'success' ? '已取消匹配' : ack.message || '取消匹配没有送达',
      next: ack.status === 'success' ? '' : '检查网络后再试一次。',
    })
  } catch {
    home.notifyMessage('取消匹配失败，请再试一次')
  }
}

async function startAi(): Promise<void> {
  const socket = currentSocket()
  if (!socket) return
  home.clearNotice()
  // #48 reads this back for "再来一局" of an AI match; persist before the seat
  // is created so a failed request still remembers the choice (issue #45).
  try {
    window.localStorage.setItem(AI_DIFFICULTY_KEY, difficulty.value)
  } catch {
    // Private mode: the launch still works with the in-memory choice.
  }
  home.beginAction('ai')
  try {
    const result = await createAiRoom(socket, playerName.value, difficulty.value)
    if (!result.ok) {
      home.notifyMessage(result.message || '人机对战暂时不可用')
      return
    }
    home.expectPlacement()
    home.matchFound = { playerName: playerName.value, opponentName: game.state.opponent_name || 'AI', mode: 'casual', roomId: game.state.room_id }
    maybeAdvance()
  } catch {
    home.notifyMessage('网络不稳定，请再试一次')
  } finally {
    home.endAction()
  }
}
</script>

<template>
  <MatchFoundOverlay
    v-if="home.matchFound"
    :self-name="home.matchFound.playerName"
    :opponent-name="home.matchFound.opponentName"
    :mode="home.matchFound.mode"
    @done="onMatchFoundDone"
  />

  <section
    class="screen home-screen"
    data-screen="start"
    data-testid="screen-start"
    aria-labelledby="screen-start-title"
  >
    <header class="home-head">
      <div class="home-head__main">
        <p class="home-kicker">竞技场 · 出 海</p>
        <h1 id="screen-start-title" class="home-head__title" data-testid="start-heading">首页</h1>
      </div>
      <div class="home-head__meta">
        <span class="home-pill" title="在线玩家（/api/online_count）">
          <i class="home-pill__dot" aria-hidden="true"></i>
          <span class="home-pill__label">在线</span>
          <b class="home-pill__value" data-testid="start-online-pill">{{ pillText }}</b>
          <span class="home-pill__unit">人</span>
        </span>
        <span
          class="home-conn"
          data-testid="start-connection-status"
          :data-connected="home.socketConnected ? 'true' : 'false'"
          role="status"
        >
          {{ home.socketConnected ? '实时连接已就绪' : '正在连接实时服务…' }}
        </span>
      </div>
    </header>

    <div class="home-grid">
      <!-- 玩家信息：/api/profile 的服务端字段，前端只排版。 -->
      <div class="home-left">
      <aside class="home-card home-player" data-testid="start-player" aria-labelledby="home-player-title">
        <div class="home-player__crest">
          <span class="home-player__emblem" aria-hidden="true"><span>舰</span></span>
        </div>
        <h2 id="home-player-title" class="home-kicker home-player__kicker">指 挥 官</h2>
        <p class="home-player__name" data-testid="start-player-name">{{ playerName }}</p>

        <template v-if="auth.isGuest">
          <p v-if="home.profileFailed" class="home-player__note" data-testid="start-player-error">
            名片暂时取不到，刷新后再试。
          </p>
          <p v-else-if="home.profileLoaded" class="home-player__note" data-testid="start-player-guest">
            游客状态：登录后显示段位、等级与战绩。
          </p>
          <p v-else class="home-player__note" data-testid="start-player-loading">正在读取名片…</p>
          <div class="home-player__links">
            <button
              type="button"
              class="home-link home-link--button"
              data-testid="start-login-link"
              @click="auth.open('login')"
            >
              去登录
            </button>
            <router-link class="home-link" :to="{ name: 'profile' }" data-testid="start-profile-link">查看名片</router-link>
          </div>
        </template>

        <StateSurface
          v-else
          class="home-player__body"
          data-testid="start-profile-surface"
          :state="profileState"
          loading-text="名片载入中…"
          error-text="名片暂时取不到。"
          @retry="home.loadProfile()"
        >
          <div class="home-player__rankrow">
            <span v-if="player.rankLabel" class="home-player__rank" data-testid="start-player-rank">{{ player.rankLabel }}</span>
            <span class="home-player__level">
              <span data-testid="start-player-level">{{ player.level }}</span>
              <span class="home-player__level-text" data-testid="start-player-level-text">{{ player.levelText }}</span>
            </span>
          </div>
          <div class="home-bar" role="img" :aria-label="'段位进度 ' + player.rankFill + '%'">
            <div class="home-bar__fill" data-testid="start-player-rank-fill" :style="{ width: player.rankFill + '%' }"></div>
          </div>
          <div class="home-bar home-bar--xp" role="img" :aria-label="'等级经验 ' + player.levelFill + '%'">
            <div class="home-bar__fill home-bar__fill--xp" data-testid="start-player-level-fill" :style="{ width: player.levelFill + '%' }"></div>
          </div>
          <dl class="home-player__kv">
            <div class="home-player__kv-row">
              <dt>战绩</dt>
              <dd data-testid="start-player-record">{{ player.record || '暂无' }}</dd>
            </div>
            <div class="home-player__kv-row">
              <dt>胜率</dt>
              <dd data-testid="start-player-winrate">{{ player.winRate || '暂无' }}</dd>
            </div>
            <div class="home-player__kv-row">
              <dt>最长连胜</dt>
              <dd data-testid="start-player-streak">{{ player.streak || '暂无' }}</dd>
            </div>
          </dl>
          <router-link class="home-link home-link--wide" :to="{ name: 'profile' }" data-testid="start-profile-link">
            查看我的名片
          </router-link>
        </StateSurface>
      </aside>
      <HomeProgress />
      </div>

      <!-- 主行动入口：DOM 中先于右栏，窄屏收成单列时“先能开一局”。 -->
      <section class="home-main" data-testid="start-actions" aria-labelledby="home-actions-title">
        <div class="home-main__head">
          <h2 id="home-actions-title" class="home-kicker">选 择 一 种 打 法</h2>
          <p class="home-main__lead">休闲与排位共用一个匹配队列；人机随时开局，不结算段位分。</p>
        </div>

        <button
          type="button"
          class="home-play home-play--casual"
          data-testid="start-primary-action"
          data-primary-action
          :disabled="actionsDisabled"
          @click="startMatch('casual')"
        >
          <span class="home-play__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M4 12a8 8 0 1 0 8-8" />
              <path d="M4 4v4h4" />
              <path d="M12 8v4l3 2" />
            </svg>
          </span>
          <span class="home-play__copy">
            <span class="home-play__title">休闲匹配</span>
            <span class="home-play__desc">随机匹配一位在线玩家 · 不计段位分 · 随时开一局</span>
          </span>
          <span class="home-play__cta" aria-hidden="true">ENTER</span>
        </button>

        <div v-if="home.queuePending" class="home-queue" role="status">
          <p class="home-queue__text" data-testid="start-queue-status">
            {{ queueText }} · 已等待 <b data-testid="start-queue-waited">{{ queueSeconds }}</b> 秒
          </p>
          <button type="button" class="button home-queue__cancel" data-testid="start-queue-cancel" @click="cancelQueue">
            取消匹配
          </button>
        </div>

        <button
          type="button"
          class="home-play home-play--ranked"
          data-testid="start-ranked-action"
          :disabled="actionsDisabled"
          @click="startMatch('ranked')"
        >
          <span class="home-play__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z" />
              <path d="M9 12l2 2 4-4" />
            </svg>
          </span>
          <span class="home-play__copy">
            <span class="home-play__title">排位对战</span>
            <span class="home-play__desc" data-testid="start-ranked-desc">{{ rankedDesc }}</span>
          </span>
          <span class="home-play__cta" aria-hidden="true">RANKED</span>
        </button>

        <div class="home-ai home-card" data-testid="start-ai-difficulty" role="radiogroup" aria-label="电脑难度">
          <div class="home-ai__head">
            <span class="home-ai__title">人机对战</span>
            <span class="home-ai__hint">练习规则与连锁 · 当前难度：{{ difficultyOptions.find((o) => o.value === difficulty)?.label }}</span>
          </div>
          <div class="home-ai__caps">
            <button
              v-for="option in difficultyOptions"
              :key="option.value"
              type="button"
              role="radio"
              class="home-ai__cap"
              :class="{ 'is-active': difficulty === option.value }"
              :aria-checked="difficulty === option.value"
              :title="option.hint"
              :data-testid="'start-ai-difficulty-' + option.value"
              :disabled="actionsDisabled"
              @click="difficulty = option.value"
            >
              <b>{{ option.label }}</b>
              <small>{{ option.hint }}</small>
            </button>
          </div>
          <button
            type="button"
            class="home-ai__action"
            data-testid="start-ai-action"
            :disabled="actionsDisabled"
            @click="startAi"
          >
            开始人机对战
          </button>
        </div>

        <p v-if="home.notice" class="home-notice" role="alert" data-testid="start-notice">
          {{ home.notice }}
        </p>

        <nav class="home-links" aria-label="更多入口">
          <router-link class="home-link home-link--tile" :to="{ name: 'lobby' }" data-testid="start-lobby-link">
            <b>游戏大厅</b><small>房间列表 · 公屏</small>
          </router-link>
          <router-link class="home-link home-link--tile" :to="{ name: 'leaderboard' }" data-testid="start-leaderboard-link">
            <b>排行榜</b><small>段位与胜场</small>
          </router-link>
          <router-link class="home-link home-link--tile" :to="{ name: 'settings' }" data-testid="start-settings-link">
            <b>设置</b><small>主题 · 音效 · 账号</small>
          </router-link>
          <button type="button" class="home-link home-link--tile home-link--button" data-testid="start-collection-link" @click="collection.open()">
            <b>图鉴 / 卡库</b><small>48 张魔法卡</small>
          </button>
        </nav>

        <!-- 卡牌展示条：main 首页中间栏底部那排卡面（图鉴入口的展示，不宣称热度数据）。 -->
        <section class="home-card home-showcase" aria-labelledby="home-showcase-title">
        <div class="home-card__head">
          <h2 id="home-showcase-title" class="home-kicker">{{ hasUsage ? '全服热门卡' : '魔法卡精选' }}</h2>
          <span class="home-showcase__meta">{{ cardCount }} 张魔法卡 · 场地 {{ fieldCount }} 张</span>
        </div>
        <ul class="home-showcase__row">
          <li v-for="card in showcase" :key="card">
            <button type="button" class="home-cardface" :title="card" @click="collection.open()">
              <img v-if="cardArtUrl(card)" class="home-cardface__art" :src="cardArtUrl(card) || ''" :alt="card" loading="lazy" />
              <span v-else class="home-cardface__art home-cardface__art--none" aria-hidden="true">舰</span>
              <span class="home-cardface__name">{{ card }}</span>
            </button>
          </li>
        </ul>
      </section>
      </section>

      <!-- 在线与公告。 -->
      <aside class="home-side">
        <HomeTasks />
        <section class="home-card" data-testid="start-online" aria-labelledby="home-online-title">
          <div class="home-card__head">
            <h2 id="home-online-title" class="home-kicker">实时战况</h2>
            <i class="home-card__dot" aria-hidden="true"></i>
          </div>
          <StateSurface
            data-testid="start-stats-surface"
            :state="statsState"
            loading-text="在线数据载入中…"
            empty-text="暂无在线数据"
            error-text="在线数据暂时取不到。"
            @retry="home.loadStats(true)"
          >
            <dl class="home-stats">
              <div class="home-stat">
                <dt>在线玩家</dt>
                <dd><b data-testid="start-online-count">{{ stats.online }}</b><span class="home-stat__unit">人</span></dd>
              </div>
              <div class="home-stat">
                <dt>休闲队列</dt>
                <dd><b data-testid="start-queue-casual">{{ stats.casual }}</b><span class="home-stat__unit">人</span></dd>
              </div>
              <div class="home-stat">
                <dt>排位队列</dt>
                <dd><b data-testid="start-queue-ranked">{{ stats.ranked }}</b><span class="home-stat__unit">人</span></dd>
              </div>
              <div class="home-stat">
                <dt>大厅房间</dt>
                <dd><b data-testid="start-lobby-rooms">{{ stats.rooms }}</b><span class="home-stat__unit">间</span></dd>
              </div>
            </dl>
          </StateSurface>
        </section>

        <section class="home-card home-changelog" data-testid="start-changelog" aria-labelledby="home-changelog-title">
          <div class="home-card__head">
            <h2 id="home-changelog-title" class="home-kicker">最 近 公 告</h2>
            <span class="home-changelog__latest" data-testid="start-changelog-latest">{{ latestText }}</span>
          </div>
          <StateSurface
            :state="changelogState"
            loading-text="公告载入中…"
            @retry="home.loadChangelog()"
          >
            <ul class="home-changelog__list">
              <li
                v-for="entry in entries"
                :key="entry.key"
                class="home-changelog__entry"
                :data-testid="'start-changelog-entry-' + entry.key"
              >
                <p class="home-changelog__date">{{ entry.date }}</p>
                <ul class="home-changelog__items">
                  <li v-for="(item, index) in entry.items" :key="index">{{ item }}</li>
                </ul>
              </li>
            </ul>
            <template #empty>
              <p class="home-card__note" data-testid="start-changelog-empty">暂时没有公告。</p>
            </template>
            <template #error>
              <p class="home-card__note" data-testid="start-changelog-empty">
                暂时没有公告（载入失败），可以重试。
              </p>
            </template>
          </StateSurface>
        </section>
      </aside>

    </div>
  </section>
</template>

<style scoped>
/* 首页 —— 按 main（BattleShip Arena）的三栏布局重画。
   左 288px 指挥官卡 / 中 1fr 打法列表 / 右 300px 在线与公告；卡片全部落在
   --panel 面层上，层级靠 12px 圆角 + --panel-line 描边 + --shadow-panel 区分，
   不再使用旧版的虚线标题下划线和 12px 全小写标题。 */
.home-screen {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
  max-width: 1440px;
  margin: 0 auto;
  padding: 20px 24px 36px;
}

/* ------------------------------------------------------------- 页头 --- */
.home-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.home-head__main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.home-kicker {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.14em;
}

.home-head__title {
  margin: 0;
  color: var(--text-primary);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.home-head__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.home-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 3px 12px;
  border: 1px solid var(--chip-line);
  border-radius: var(--radius-pill);
  background: rgba(124, 92, 240, 0.08);
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}

.home-pill__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--role-success);
}

.home-pill__label,
.home-pill__unit {
  color: var(--text-tertiary);
}

.home-pill__value {
  color: var(--text-primary);
  font-weight: 600;
}

.home-conn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.home-conn::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--role-success);
}

.home-conn[data-connected='false']::before {
  background: var(--role-warning);
}

/* ------------------------------------------------------------- 栅格 --- */
.home-grid {
  display: grid;
  grid-template-columns: 288px minmax(0, 1fr) 300px;
  gap: 16px;
  align-items: start;
}

/* 通用卡片面层。 */
.home-card {
  min-width: 0;
  padding: 16px 18px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius-lg);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.home-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.home-card__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--role-success);
}

.home-card__note {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 12.5px;
}

/* --------------------------------------------------------- 指挥官卡 --- */
.home-player {
  display: flex;
  flex-direction: column;
  gap: 10px;
  text-align: center;
}

.home-player__crest {
  display: grid;
  place-items: center;
  padding: 6px 0 2px;
}

.home-player__emblem {
  display: grid;
  place-items: center;
  width: 88px;
  height: 88px;
  border: 1px solid var(--gold);
  border-radius: 50%;
  background:
    radial-gradient(circle at 50% 30%, rgba(201, 162, 76, 0.24), transparent 70%),
    var(--surface-chamber);
  box-shadow:
    inset 0 0 0 6px color-mix(in srgb, var(--surface-chamber) 80%, transparent),
    0 0 22px rgba(201, 162, 76, 0.22);
}

.home-player__emblem > span {
  color: var(--gold-strong);
  font-size: 26px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.home-player__kicker {
  margin-top: 2px;
}

.home-player__name {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.home-player__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  text-align: left;
}

.home-player__note {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 12.5px;
  line-height: 1.6;
  text-align: left;
}

.home-player__rankrow {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.home-player__rank {
  color: var(--gold-strong);
  font-size: 13.5px;
  font-weight: 600;
}

.home-player__level {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  color: var(--text-primary);
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}

.home-player__level-text {
  color: var(--text-tertiary);
  font-size: 11.5px;
}

.home-bar {
  height: 5px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--surface-sea) 70%, transparent);
}

.home-bar__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--gold), var(--gold-strong));
}

.home-bar--xp {
  height: 4px;
}

.home-bar__fill--xp {
  background: linear-gradient(90deg, var(--role-action), var(--accent-strong));
}

.home-player__kv {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin: 4px 0 0;
}

.home-player__kv-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 0;
  border-top: 1px solid var(--border-subtle);
  font-size: 12.5px;
}

.home-player__kv-row dt {
  color: var(--text-tertiary);
}

.home-player__kv-row dd {
  margin: 0;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.home-player__links {
  display: flex;
  gap: 8px;
}

.home-player__links > * {
  flex: 1 1 0;
}

/* ------------------------------------------------------------ 打法区 --- */
.home-main {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.home-main__head {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 0 2px;
}

.home-main__lead {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 12.5px;
  line-height: 1.6;
}

.home-play {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  width: 100%;
  min-height: 84px;
  padding: 16px 18px;
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  text-align: left;
  cursor: pointer;
  transition:
    transform var(--duration-fast) var(--ease),
    filter var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease);
}

.home-play:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.06);
}

.home-play:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.home-play__icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.16);
  color: currentColor;
}

.home-play__copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.home-play__title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.home-play__desc {
  font-size: 12.5px;
  line-height: 1.5;
  opacity: 0.82;
}

.home-play__cta {
  padding: 5px 14px;
  border: 1px solid currentColor;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
  opacity: 0.8;
}

/* 休闲：main 的紫色主 hero。 */
.home-play--casual {
  border-color: var(--hero-border);
  background: var(--hero-grad);
  color: #ffffff;
  box-shadow: var(--shadow-accent);
}

/* 排位：金色主权行（main 的琥珀底 + RANKED）。 */
.home-play--ranked {
  border-color: color-mix(in srgb, var(--gold) 55%, transparent);
  background: color-mix(in srgb, var(--gold) 16%, var(--surface-deck));
  color: var(--text-primary);
}

.home-play--ranked .home-play__icon {
  background: color-mix(in srgb, var(--gold) 26%, transparent);
  color: var(--gold-strong);
}

.home-play--ranked .home-play__cta {
  color: var(--gold-strong);
}

/* 组队等待条。 */
.home-queue {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border: 1px dashed var(--chip-line);
  border-radius: var(--radius);
  background: var(--role-action-soft);
}

.home-queue__text {
  margin: 0;
  color: var(--text-primary);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.home-queue__cancel {
  min-height: 32px;
  padding: 4px 12px;
  font-size: 12.5px;
}

/* 人机：难度分段 + 主按钮。 */
.home-ai {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
}

.home-ai__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.home-ai__title {
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 600;
}

.home-ai__hint {
  color: var(--text-tertiary);
  font-size: 11.5px;
}

.home-ai__caps {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.home-ai__cap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
  min-height: 54px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--surface-sea) 55%, transparent);
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  transition:
    border-color var(--duration-fast) var(--ease),
    background var(--duration-fast) var(--ease);
}

.home-ai__cap b {
  color: var(--text-primary);
  font-size: 13.5px;
  font-weight: 600;
}

.home-ai__cap small {
  color: var(--text-secondary);
  font-size: 10.5px;
  line-height: 1.35;
}

.home-ai__cap:hover:not(:disabled) {
  border-color: var(--chip-line);
}

.home-ai__cap.is-active {
  border-color: var(--role-action);
  background: var(--role-action-soft);
  box-shadow: inset 0 0 0 1px var(--role-action);
}

.home-ai__action {
  width: 100%;
  min-height: 40px;
  border: 1px solid var(--role-action);
  border-radius: var(--radius-sm);
  background: var(--role-action-soft);
  color: var(--role-action);
  font: inherit;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease);
}

.home-ai__action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--role-action) 26%, transparent);
}

.home-ai__action:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

/* 提示行。 */
.home-notice {
  margin: 0;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--role-enemy) 45%, transparent);
  border-radius: var(--radius);
  background: var(--role-enemy-soft);
  color: var(--role-enemy);
  font-size: 12.5px;
}

/* 更多入口：2×2 磁贴。 */
.home-links {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.home-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 38px;
  padding: 6px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-chamber);
  color: var(--text-primary);
  font-size: 13px;
  text-decoration: none;
  cursor: pointer;
  transition:
    border-color var(--duration-fast) var(--ease),
    background var(--duration-fast) var(--ease);
}

.home-link:hover {
  border-color: var(--chip-line);
  background: var(--surface-raised);
}

.home-link--button {
  font-family: inherit;
}

.home-link--wide {
  width: 100%;
}

.home-link--tile {
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
  min-height: 56px;
  padding: 10px 14px;
  border-color: var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
}

.home-link--tile b {
  font-size: 13.5px;
  font-weight: 600;
}

.home-link--tile small {
  color: var(--text-tertiary);
  font-size: 11px;
}

/* --------------------------------------------------------- 右栏 --- */
.home-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.home-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.home-stat {
  padding: 9px 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--surface-sea) 50%, transparent);
}

.home-stat--wide {
  grid-column: span 2;
}

.home-stat dt {
  color: var(--text-tertiary);
  font-size: 11.5px;
}

.home-stat dd {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin: 2px 0 0;
  color: var(--text-primary);
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.home-stat--wide dd {
  font-size: 24px;
}

.home-stat__unit {
  color: var(--text-tertiary);
  font-size: 11.5px;
  font-weight: 400;
}

/* 公告：右栏里可滚动的一段。 */
.home-changelog {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
}

.home-changelog__latest {
  color: var(--text-tertiary);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.home-changelog__list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 0;
  padding: 0;
  max-height: 320px;
  overflow-y: auto;
  list-style: none;
}

.home-changelog__entry {
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
}

.home-changelog__entry:first-child {
  padding-top: 0;
  border-top: 0;
}

.home-changelog__date {
  margin: 0 0 4px;
  color: var(--text-tertiary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.home-changelog__items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding-left: 14px;
  color: var(--text-secondary);
  font-size: 12.5px;
  line-height: 1.55;
}

/* 卡牌展示条（main 首页中间栏底部那排卡面）。 */
.home-showcase {
  margin-top: 4px;
}

.home-showcase__meta {
  color: var(--text-tertiary);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.home-showcase__row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.home-cardface {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 112px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

.home-cardface__art {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-chamber);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--gold) 22%, transparent);
  transition:
    transform var(--duration-fast) var(--ease),
    border-color var(--duration-fast) var(--ease),
    box-shadow var(--duration-fast) var(--ease);
}

.home-cardface__art--none {
  display: grid;
  place-items: center;
  color: var(--gold-strong);
  font-size: 22px;
}

.home-cardface:hover .home-cardface__art {
  transform: translateY(-3px);
  border-color: var(--chip-line);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--gold) 35%, transparent),
    0 12px 22px rgba(0, 0, 0, 0.45);
}

.home-cardface__name {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-cardface:hover .home-cardface__name {
  color: var(--text-primary);
}

/* ----------------------------------------------------------- 断点 --- */
@media (max-width: 1180px) {
  .home-grid {
    grid-template-columns: 260px minmax(0, 1fr) 268px;
  }

  .home-ai__caps {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

}

@media (max-width: 1023px) {
  .home-screen {
    padding: 16px 16px 28px;
  }

  /* One column on tablets/phones: plain flex so the order below is exact
     (grid-template-areas from the desktop layout cannot collapse to 1 column). */
  .home-grid {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .home-main {
    order: 1;
  }

  .home-player {
    order: 2;
  }

  .home-side {
    order: 3;
  }

  /* 单列时卡牌条跟在中栏内容之后（已是中栏子块，无需 order）。 */

  .home-ai__caps {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 719px) {
  .home-screen {
    padding: 12px 12px 24px;
  }

  .home-cardface {
    width: 88px;
  }

  .home-head__title {
    font-size: 19px;
  }

  .home-play {
    grid-template-columns: 38px minmax(0, 1fr);
    min-height: 72px;
    padding: 12px 14px;
  }

  .home-play__icon {
    width: 38px;
    height: 38px;
  }

  .home-play__title {
    font-size: 16px;
  }

  .home-play__cta {
    display: none;
  }

  .home-ai__caps,
  .home-links,
  .home-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }


  .home-player__links {
    flex-direction: column;
  }
}

@media (max-width: 519px) {
  .home-ai__caps {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .home-links {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* 矮一些的桌面窗口（<=940px 高）收紧间距，让首页尽量一屏放下。 */
@media (max-height: 940px) and (min-width: 1024px) {
  .home-screen {
    padding-top: 10px;
  }

  .home-card {
    padding: 14px 16px;
  }

  .home-play--casual {
    min-height: 74px;
  }

  .home-ai__cap {
    min-height: 52px;
  }

  .home-link--tile {
    padding: 10px 12px;
  }

  .home-cardface {
    width: 84px;
  }

  .home-showcase__row {
    gap: 8px;
  }
}

/* 原版首页的完整大卡展示，左栏继续承接成长信息。 */
.home-left { display:grid; gap:12px; align-content:start; min-width:0; }
.home-showcase__row { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; overflow:visible; }
.home-showcase__row li { min-width:0; }
.home-cardface { width:100%; padding:0 0 8px; border:1px solid var(--panel-line); border-radius:10px; overflow:hidden; background:var(--surface-deck); }
.home-cardface__art { width:100%; height:auto; aspect-ratio:2/3; object-fit:cover; }
.home-showcase { padding:16px; }
@media(max-width:700px) { .home-showcase__row { grid-template-columns:repeat(5, minmax(90px,1fr)); overflow-x:auto; }.home-left { order:2; } }

@media(min-width:1024px) and (max-height:1200px) {
  .home-head { margin-bottom:10px; }.home-head__main>.home-kicker { display:none; }.home-head__title { font-size:19px; }
  .home-main { gap:8px; }.home-main__head { gap:2px; }.home-main__lead { margin:0; font-size:11px; }
  .home-play { min-height:64px; padding:12px 18px; }.home-play--casual { min-height:76px; }
  .home-ai { padding:10px 14px; gap:6px; }.home-ai__cap { min-height:40px; padding:6px 8px; }
  .home-link--tile { min-height:48px; padding:6px 12px; }.home-links { gap:8px; }
  .home-player__emblem { width:48px; height:48px; }.home-player__emblem>span { font-size:18px; }
  .home-player { gap:6px; padding:12px 16px; }.home-player__crest { padding:0; }.home-player__kicker { display:none; }
  .home-left { gap:8px; }.home-screen { padding:12px 24px 12px; gap:10px; }
  .home-showcase { padding:12px 14px; }.home-card { padding:12px 16px; }
}
@media(min-width:1024px) and (max-height:940px) {
  .home-player__links { margin-top:0; }
  .home-player { gap:4px; padding-top:8px; padding-bottom:8px; }
  .home-head { margin-bottom:4px; }
  .home-play { padding-top:8px; padding-bottom:8px; }
  .home-ai { gap:4px; padding-top:8px; padding-bottom:8px; }
}
/* 右栏为任务留出空间，在线信息收成紧凑四格，公告内部滚动。 */
.home-side { gap:8px; align-self:start; }
.home-side > [data-testid='start-online'] { flex:0 0 auto; }
.home-stat { display:flex; align-items:center; justify-content:space-between; gap:5px; min-height:36px; padding:6px 8px; }
.home-stat dt { font-size:10.5px; line-height:1.2; }
.home-stat dd { margin:0; font-size:16px; line-height:1.2; }
.home-stats { gap:6px; }
.home-side .home-changelog__list { max-height:clamp(100px,calc(100dvh - 620px),240px); }
@media(min-width:1024px) {
  .home-side { max-height:calc(100dvh - 144px); }
  .home-side .home-changelog { overflow:hidden; }
}
@media(max-width:1023px) {
  .home-grid { align-items:stretch; }
  .home-side { align-self:stretch; }
  .home-side .home-changelog__list { max-height:240px; }
}
</style>

