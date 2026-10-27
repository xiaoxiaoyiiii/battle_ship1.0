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
        <h1 id="screen-start-title" class="home-head__title" data-testid="start-heading">准备出航</h1>
        <p class="home-head__subtitle">一片海域，一手魔法。下一场胜负由你决定。</p>
      </div>
      <div class="home-head__meta">
        <span class="home-pill" title="在线玩家">
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
        <h2 id="home-player-title" class="home-kicker home-player__kicker">指挥官</h2>
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
          <p class="home-bar-label">段位进度</p>
          <div class="home-bar" role="img" :aria-label="'段位进度 ' + player.rankFill + '%'">
            <div class="home-bar__fill" data-testid="start-player-rank-fill" :style="{ width: player.rankFill + '%' }"></div>
          </div>
          <p class="home-bar-label">等级经验 <span>{{ player.levelText }}</span></p>
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
        <section class="home-launch">
        <div class="home-launch__art" aria-hidden="true">
          <img v-for="card in showcase.slice(0, 3)" :key="card" :src="cardArtUrl(card) || ''" alt="" />
        </div>
        <div class="home-main__head">
          <h2 id="home-actions-title" class="home-main__title">选择你的下一场海战</h2>
          <p class="home-main__lead">落子、施法，在连锁中扭转战局。</p>
        </div>
        <div class="home-launch__actions">
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
        </button>

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
        </button>
        </div>
        <p class="home-launch__note">休闲不计段位分 · 排位对战影响段位</p>
        <div v-if="home.queuePending" class="home-queue" role="status">
          <p class="home-queue__text" data-testid="start-queue-status">
            {{ queueText }} · 已等待 <b data-testid="start-queue-waited">{{ queueSeconds }}</b> 秒
          </p>
          <button type="button" class="button home-queue__cancel" data-testid="start-queue-cancel" @click="cancelQueue">
            取消匹配
          </button>
        </div>
        </section>

        <div class="home-ai home-card" data-testid="start-ai-difficulty" role="radiogroup" aria-label="电脑难度">
          <div class="home-ai__head">
            <span class="home-ai__title">人机对战</span>
            <span class="home-ai__hint">练习规则与连锁，不结算段位分。</span>
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
          <div class="home-ai__foot">
          <p class="home-ai__current">{{ difficultyOptions.find((o) => o.value === difficulty)?.label }} · {{ difficultyOptions.find((o) => o.value === difficulty)?.hint }}</p>
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
            <h2 id="home-changelog-title" class="home-kicker">最近公告</h2>
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
/* 三栏出航台：身份、对局入口和实时信息各有稳定层级。 */
.home-screen { width:100%; max-width:1480px; margin:0 auto; padding:24px 24px 28px; display:flex; flex-direction:column; gap:22px; }
.home-head { display:flex; align-items:center; justify-content:space-between; gap:20px; }
.home-head__main { min-width:0; }
.home-head__title { margin:0; color:var(--text-primary); font-size:30px; font-weight:750; letter-spacing:.02em; line-height:1.3; }
.home-head__subtitle { margin:5px 0 0; color:var(--text-secondary); font-size:14px; }
.home-head__meta { display:flex; align-items:center; flex-wrap:wrap; justify-content:flex-end; gap:12px; }
.home-pill { display:inline-flex; align-items:center; gap:5px; padding:5px 10px; border:1px solid color-mix(in srgb,var(--role-success) 30%,transparent); border-radius:5px; background:color-mix(in srgb,var(--role-success) 10%,var(--panel)); color:var(--role-success); font-size:13px; white-space:nowrap; }
.home-pill__dot { width:6px; height:6px; background:currentColor; border-radius:50%; }
.home-pill__value { font-variant-numeric:tabular-nums; }
.home-conn { display:flex; align-items:center; gap:6px; color:var(--text-secondary); font-size:12px; }
.home-conn::before { content:''; width:5px; height:5px; border-radius:50%; background:var(--role-success); }
.home-conn[data-connected='false']::before { background:var(--role-warning); }
.home-grid { display:grid; grid-template-columns:226px minmax(0,1fr) 286px; gap:22px; align-items:start; }
.home-left,.home-main,.home-side { min-width:0; display:flex; flex-direction:column; gap:16px; }
.home-card { min-width:0; padding:18px 20px; border:1px solid var(--panel-line); border-radius:12px; background:var(--panel); }
.home-card__head { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:14px; }
.home-kicker { margin:0; color:var(--text-primary); font-size:16px; font-weight:650; letter-spacing:0; }
.home-card__dot { width:6px; height:6px; border-radius:50%; background:var(--role-success); }
.home-card__note { color:var(--text-secondary); font-size:13px; line-height:1.6; }
.home-player { display:grid; grid-template-columns:56px minmax(0,1fr); gap:4px 12px; padding:20px; }
.home-player__crest { grid-row:1 / 3; display:flex; align-items:center; }
.home-player__emblem { display:grid; place-items:center; width:54px; height:54px; border:1px solid color-mix(in srgb,var(--role-self) 60%,var(--panel-line)); border-radius:50%; background:color-mix(in srgb,var(--role-self) 12%,var(--panel)); color:var(--role-self); font-size:24px; font-weight:700; }
.home-player__kicker { align-self:end; font-size:12px; color:var(--text-secondary); }
.home-player__name { align-self:start; min-width:0; overflow-wrap:anywhere; color:var(--text-primary); font-size:17px; line-height:1.4; font-weight:700; margin:0; }
.home-player__body,.home-player__note,.home-player__links { grid-column:1 / -1; }
.home-player__body { margin-top:12px; gap:0; }
.home-player__note { margin:12px 0 0; color:var(--text-secondary); font-size:13px; line-height:1.6; }
.home-player__rankrow { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:6px; margin-bottom:16px; font-size:12px; }
.home-player__rank { color:var(--gold-strong); }
.home-player__level { color:var(--text-secondary); }
.home-player__level-text { display:none; }
.home-bar-label { display:flex; justify-content:space-between; flex-wrap:wrap; gap:3px; margin:10px 0 5px; color:var(--text-secondary); font-size:12px; }
.home-bar-label span { color:var(--text-primary); font-variant-numeric:tabular-nums; }
.home-bar { height:4px; overflow:hidden; border-radius:4px; background:var(--surface-raised); }
.home-bar__fill { height:100%; border-radius:inherit; background:var(--gold); }
.home-bar__fill--xp { background:var(--role-self); }
.home-player__kv { display:grid; gap:7px; margin:16px 0; }
.home-player__kv-row { display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:4px; font-size:12px; }
.home-player__kv-row dt { color:var(--text-secondary); }
.home-player__kv-row dd { margin:0; color:var(--text-primary); font-variant-numeric:tabular-nums; }
.home-player__links { display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px; margin-top:14px; }
.home-link { color:var(--role-self); font:inherit; font-size:13px; text-decoration:none; }
.home-link--button { border:0; background:none; cursor:pointer; }
.home-link--wide { display:flex; align-items:center; justify-content:center; min-height:38px; border:1px solid var(--border-strong); border-radius:6px; color:var(--text-primary); }
.home-link--wide:hover { background:var(--surface-raised); }
.home-launch { position:relative; isolation:isolate; overflow:hidden; min-height:202px; padding:24px 26px 20px; border:1px solid color-mix(in srgb,var(--role-action) 25%,var(--panel-line)); border-radius:14px; background:linear-gradient(110deg,color-mix(in srgb,var(--role-action) 12%,var(--panel)),var(--panel)); }
.home-main__head { position:relative; z-index:1; max-width:75%; }
.home-main__title { margin:0; color:var(--text-primary); font-size:25px; font-weight:700; line-height:1.35; }
.home-main__lead { margin:9px 0 0; color:var(--text-secondary); font-size:13px; line-height:1.6; }
.home-launch__art { position:absolute; inset:20px 8px 0 auto; width:196px; pointer-events:none; z-index:-1; opacity:.65; mask-image:linear-gradient(to right,transparent,#000 25%); }
.home-launch__art img { position:absolute; top:12px; width:100px; aspect-ratio:3 / 4; object-fit:contain; border-radius:6px; box-shadow:0 8px 18px #0004; }
.home-launch__art img:nth-child(1) { left:1px; transform:rotate(-16deg); }
.home-launch__art img:nth-child(2) { left:53px; top:0; transform:rotate(3deg); }
.home-launch__art img:nth-child(3) { left:104px; top:24px; transform:rotate(16deg); }
.home-launch__actions { position:relative; z-index:1; display:flex; gap:10px; flex-wrap:wrap; margin-top:23px; max-width:80%; }
.home-play { display:flex; align-items:center; justify-content:center; gap:9px; position:relative; min-height:42px; padding:10px 15px; border:1px solid transparent; border-radius:7px; font:inherit; cursor:pointer; text-align:left; transition:background .16s,border-color .16s; }
.home-play--casual { color:var(--on-accent,#fff); background:var(--hero-grad); border-color:var(--hero-border); }
.home-play--ranked { color:var(--gold-strong); background:color-mix(in srgb,var(--gold) 12%,var(--surface-sea)); border-color:color-mix(in srgb,var(--gold) 45%,var(--panel-line)); }
.home-play:hover:not(:disabled) { filter:brightness(1.08); }
.home-play__icon { display:flex; }
.home-play__copy { display:flex; flex-direction:column; min-width:0; }
.home-play__title { font-weight:650; font-size:14px; }
.home-play__desc { position:absolute; overflow:hidden; width:1px; height:1px; clip-path:inset(50%); white-space:nowrap; }
.home-launch__note { position:relative; margin:12px 0 0; color:var(--text-secondary); font-size:12px; }
.home-play:disabled,.home-ai__cap:disabled,.home-ai__action:disabled { opacity:.55; cursor:not-allowed; }
.home-queue { position:relative; z-index:1; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin-top:16px; padding-top:12px; border-top:1px solid var(--panel-line); }
.home-queue__text { margin:0; color:var(--text-primary); font-size:13px; }
.home-queue__text b { color:var(--role-self); font-variant-numeric:tabular-nums; }
.home-queue__cancel { min-height:36px; font-size:12px; }
.home-ai { display:flex; flex-direction:column; gap:14px; }
.home-ai__head { display:flex; flex-direction:column; gap:4px; }
.home-ai__title { color:var(--text-primary); font-size:17px; font-weight:650; }
.home-ai__hint,.home-ai__current { color:var(--text-secondary); font-size:12px; line-height:1.5; }
.home-ai__caps { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; }
.home-ai__cap { min-width:0; min-height:36px; padding:6px 8px; border:1px solid var(--border-strong); border-radius:5px; background:var(--surface-sea); color:var(--text-secondary); font:inherit; cursor:pointer; }
.home-ai__cap b { font-size:13px; font-weight:500; }
.home-ai__cap small { display:none; }
.home-ai__cap.is-active { color:var(--text-primary); border-color:color-mix(in srgb,var(--role-action) 70%,var(--panel-line)); background:color-mix(in srgb,var(--role-action) 22%,var(--panel)); }
.home-ai__foot { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.home-ai__current { margin:0; }
.home-ai__action { flex-shrink:0; min-height:36px; padding:7px 12px; color:var(--text-primary); border:1px solid var(--border-strong); border-radius:6px; background:var(--surface-raised); font:inherit; font-size:13px; font-weight:600; cursor:pointer; }
.home-notice { margin:0; padding:10px 14px; border-left:2px solid var(--role-warning); color:var(--role-warning); background:var(--panel); font-size:13px; }
.home-links { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
.home-link--tile { display:flex; flex-direction:column; align-items:flex-start; justify-content:center; min-width:0; min-height:70px; padding:12px 14px; border:1px solid var(--panel-line); border-radius:8px; background:var(--panel); text-align:left; }
.home-link--tile:hover { border-color:var(--role-self); background:var(--surface-raised); }
.home-link--tile b { color:var(--text-primary); font-size:13px; font-weight:650; }
.home-link--tile small { margin-top:4px; color:var(--text-secondary); font-size:12px; line-height:1.35; }
.home-showcase { padding:18px 20px 14px; }
.home-showcase__meta { color:var(--text-secondary); font-size:12px; }
.home-showcase__row { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:14px; margin:0; padding:0; list-style:none; }
.home-showcase__row li { min-width:0; }
.home-cardface { display:flex; flex-direction:column; align-items:center; width:100%; gap:7px; border:0; padding:0; color:var(--text-primary); background:none; font:inherit; cursor:pointer; }
.home-cardface__art { display:block; width:100%; aspect-ratio:2 / 3; object-fit:contain; border-radius:5px; background:var(--surface-chamber); box-shadow:0 5px 12px #0003; transition:transform .16s; }
.home-cardface:hover .home-cardface__art { transform:translateY(-4px); }
.home-cardface__art--none { display:grid; place-items:center; color:var(--gold); font-size:24px; }
.home-cardface__name { max-width:100%; color:var(--text-secondary); font-size:12px; line-height:1.5; overflow-wrap:anywhere; }
.home-stats { display:grid; gap:10px; margin:0; }
.home-stat { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.home-stat dt { color:var(--text-secondary); font-size:13px; }
.home-stat dd { margin:0; color:var(--text-primary); font-size:14px; font-variant-numeric:tabular-nums; }
.home-stat dd b { font-weight:500; }
.home-stat__unit { margin-left:4px; font-size:12px; }
.home-changelog { min-height:0; }
.home-changelog__latest { color:var(--text-secondary); font-size:12px; white-space:nowrap; }
.home-changelog__list { max-height:210px; overflow-y:auto; overscroll-behavior:contain; margin:0; padding:0 5px 0 0; list-style:none; scrollbar-width:thin; }
.home-changelog__entry + .home-changelog__entry { margin-top:16px; padding-top:14px; border-top:1px solid var(--panel-line); }
.home-changelog__date { margin:0 0 7px; color:var(--role-self); font-size:12px; font-variant-numeric:tabular-nums; }
.home-changelog__items { display:grid; gap:7px; margin:0; padding:0; list-style:none; color:var(--text-secondary); font-size:13px; line-height:1.65; }
.home-screen :is(button,a):focus-visible { outline:2px solid var(--focus-ring); outline-offset:3px; }
@media (max-width:1240px) and (min-width:1024px) {
  .home-grid { grid-template-columns:210px minmax(0,1fr) 262px; gap:16px; }
  .home-launch { padding:22px; }
  .home-launch__art { width:120px; opacity:.32; }
  .home-main__head,.home-launch__actions { max-width:100%; }
  .home-main__title { font-size:23px; }
  .home-links { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .home-link--tile { min-height:58px; padding:10px 12px; }
  .home-showcase__row { gap:7px; }
}
@media (max-width:1023px) {
  .home-screen { padding:22px 20px 30px; }
  .home-grid { grid-template-columns:minmax(0,1fr) 280px; gap:18px; }
  .home-main { grid-column:1; grid-row:1; }
  .home-side { grid-column:2; grid-row:1 / 3; }
  .home-left { grid-column:1; grid-row:2; }
  .home-launch__art { width:135px; opacity:.35; }
  .home-main__head,.home-launch__actions { max-width:100%; }
  .home-main__title { font-size:23px; }
  .home-links { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .home-player { grid-template-columns:56px minmax(0,1fr); }
  .home-player__rankrow { margin-bottom:12px; }
  .home-changelog__list { max-height:260px; }
}
@media (max-width:719px) {
  .home-screen { padding:20px 16px 26px; gap:18px; }
  .home-head { align-items:flex-start; gap:12px; }
  .home-head__title { font-size:27px; }
  .home-head__subtitle { font-size:13px; }
  .home-head__meta { gap:7px; }
  .home-conn { max-width:90px; font-size:12px; }
  .home-grid { display:flex; flex-direction:column; gap:18px; }
  .home-main,.home-left,.home-side { width:100%; }
  .home-main { order:0; }
  .home-left { order:1; }
  .home-side { order:2; }
  .home-launch { min-height:208px; padding:22px 20px; }
  .home-launch__art { right:-12px; opacity:.26; }
  .home-launch__actions { gap:8px; }
  .home-play { flex:1; padding:10px; }
  .home-main__title { font-size:23px; }
  .home-ai__foot { flex-wrap:wrap; }
  .home-ai__current { flex:1 1 140px; }
  .home-card { padding:18px; }
  .home-showcase { padding:18px 14px; }
  .home-showcase__row { gap:10px; overflow-x:auto; grid-template-columns:repeat(5,minmax(78px,1fr)); padding-bottom:5px; scrollbar-width:thin; }
  .home-showcase__meta { font-size:12px; }
  .home-card__head { gap:8px; align-items:baseline; }
  .home-card__head .home-kicker { font-size:15px; }
  .home-stat { min-height:24px; }
}
/* 桌面三栏共用可用高度，长公告与成就只在各自面板内滚动。 */
@media (min-width:1024px) and (min-height:700px) {
  .home-screen { flex:0 0 auto; height:calc(100dvh - 64px); min-height:0; padding:14px 24px 16px; gap:14px; }
  .home-head { flex-shrink:0; }
  .home-head__title { font-size:26px; }
  .home-grid { flex:1; min-height:0; align-items:stretch; gap:18px; }
  .home-left,.home-main,.home-side { min-height:0; gap:12px; }
  .home-card { padding:14px 16px; }
  .home-card__head { margin-bottom:10px; }
  .home-player { flex-shrink:0; }
  .home-player__body { margin-top:8px; }
  .home-player__rankrow { margin-bottom:10px; }
  .home-bar-label { margin-top:6px; }
  .home-player__kv { margin:12px 0; }
  .home-launch,.home-ai,.home-links { flex-shrink:0; }
  .home-launch { min-height:180px; padding:20px 22px 16px; }
  .home-launch__actions { margin-top:18px; }
  .home-ai { gap:10px; }
  .home-link--tile { min-height:58px; padding:9px 12px; }
  .home-showcase { flex:1; min-height:0; display:flex; flex-direction:column; }
  .home-showcase__row { flex:1; min-height:0; }
  .home-showcase__row li { min-height:0; }
  .home-cardface { height:100%; min-height:0; }
  .home-cardface__art { flex:1; min-height:0; height:0; aspect-ratio:auto; }
  .home-cardface__name { flex-shrink:0; }
  .home-side > [data-testid='start-online'] { flex-shrink:0; }
  .home-changelog { flex:1; display:flex; flex-direction:column; }
  .home-changelog > .state-surface { flex:1; min-height:0; }
  .home-changelog__list { max-height:none; min-height:0; }
}
@media (min-width:1024px) and (min-height:700px) and (max-height:820px) {
  .home-screen { padding-top:10px; padding-bottom:12px; gap:10px; }
  .home-head__title { font-size:22px; }
  .home-head__subtitle { font-size:12px; }
  .home-left,.home-main,.home-side { gap:10px; }
  .home-card { padding:10px 14px; }
  .home-player__emblem { width:44px; height:44px; font-size:21px; }
  .home-player { grid-template-columns:44px minmax(0,1fr); }
  .home-player__body { margin-top:4px; }
  .home-player__rankrow { margin-bottom:6px; }
  .home-player__kv { margin:8px 0; gap:5px; }
  .home-link--wide { min-height:32px; }
  .home-launch { min-height:140px; padding:12px 18px; }
  .home-main__title { font-size:20px; }
  .home-main__lead { margin-top:3px; font-size:12px; }
  .home-launch__actions { margin-top:10px; }
  .home-play { min-height:36px; padding:7px 12px; }
  .home-launch__note { margin-top:6px; }
  .home-ai { gap:6px; }
  .home-ai__head { flex-direction:row; align-items:baseline; flex-wrap:wrap; gap:4px 10px; }
  .home-ai__cap { min-height:32px; padding:4px 8px; }
  .home-ai__action { min-height:32px; padding:5px 10px; }
  .home-link--tile { min-height:44px; padding:5px 10px; }
  .home-link--tile small { margin-top:2px; }
  .home-stat { min-height:16px; }
  .home-stat dt { font-size:12px; line-height:1.3; }
  .home-stat dd { font-size:13px; line-height:1.3; }
  .home-stats { gap:4px; }
}
@media (prefers-reduced-motion:reduce) {
  .home-play,.home-cardface__art { transition:none; }
  .home-cardface:hover .home-cardface__art { transform:none; }
}
</style>
