<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppOverlay from './components/AppOverlay.vue'
import AppWallpaper from './components/AppWallpaper.vue'
import AppProfileBackground from './components/AppProfileBackground.vue'
import OceanParticles from './components/OceanParticles.vue'
import AuthOverlay from './components/AuthOverlay.vue'
import AvatarMenu from './components/AvatarMenu.vue'
import CardCollectionOverlay from './components/CardCollectionOverlay.vue'
import AdminOverlay from './components/AdminOverlay.vue'
import AdminConsole from './components/AdminConsole.vue'
import CheckinDialog from './components/CheckinDialog.vue'
import FriendsOverlay from './components/FriendsOverlay.vue'
import HelpOverlay from './components/HelpOverlay.vue'
import ScreenBoundary from './components/ScreenBoundary.vue'
import ToastHost from './components/ToastHost.vue'
import TideAshBadge from './components/TideAshBadge.vue'
import GlobalPointerEffects from './components/GlobalPointerEffects.vue'
import DiceRollOverlay from './screens/game/DiceRollOverlay.vue'
import { routeLoading } from './router'
import { getSettlementSocket } from './realtime/settlement'
import { forgetSeat } from './realtime/reconnect'
import { useAuthStore } from './stores/auth'
import { useDmStore } from './stores/dm'
import { acquireFriendsChannel } from './realtime/friends'
import { useCollectionStore } from './stores/collection'
import { useGameStore } from './stores/game'
import { isInitialBanPlacement } from './stores/cardBans'
import { useUiStore } from './stores/ui'
import { useAudioStore } from './stores/audio'
import { useShopStore } from './stores/shop'
import { useMailboxStore } from './stores/mailbox'
import { readCheckinAutoShown, useCheckinStore, writeCheckinAutoShown } from './stores/checkin'
import { installInteractionAudio } from './audio/interactions'
import SplashScreen from './splash/SplashScreen.vue'
import { ASSEMBLE_MS, decideSplash, hasReconnectSeat, processSplashGate } from './splash/splashPolicy'

/**
 * Application shell (ticket #42).
 *
 * Four destinations (开战 / 大厅 / 图鉴 / 排行) plus the friends icon and the
 * avatar menu close the eleven frozen routes down to one obvious place per
 * intent. Flow screens (placement / rps / game / game-over) switch to the
 * immersive toolbar: the destinations disappear, exit and settings stay, and
 * exit asks for confirmation first. Overlays, the notice queue and the three
 * themes live at this level so every screen inherits them.
 */
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const game = useGameStore()
const collection = useCollectionStore()
const ui = useUiStore()
let exitDestination = '/lobby'
const removeBanLeaveGuard = router.beforeEach(to => {
  if (isInitialBanPlacement(game.state) && !['placement', 'settings'].includes(String(to.name))) {
    exitDestination = to.fullPath
    ui.requestExit()
    return false
  }
  return true
})
onBeforeUnmount(removeBanLeaveGuard)

function cancelExit(): void {
  ui.cancelExit()
  exitDestination = '/lobby'
  if (isInitialBanPlacement(game.state) && route.name === 'settings') void router.push({ name: 'placement' })
}
const audio = useAudioStore()
let releaseInteractionAudio: (() => void) | null = null
onMounted(() => { releaseInteractionAudio = installInteractionAudio(sound => audio.playUi(sound)) })
onBeforeUnmount(() => releaseInteractionAudio?.())
// 消费通知的明确语义与唯一编号，不从文案或战斗日志猜测声音。
let lastNoticeSoundId = 0
watch(() => ui.notices.at(-1), notice => {
  if (!notice || notice.id <= lastNoticeSoundId) return
  lastNoticeSoundId = notice.id
  if (notice?.tone === 'error') audio.playUi('reject')
  else if (notice?.tone === 'success') audio.playUi('ready')
})
watch(() => game.state.room_id, () => audio.resetMatchAudio())
watch(() => route.name, name => {
  audio.setBattleScene(['game', 'placement', 'rps'].includes(String(name)))
}, { immediate: true })
const dm = useDmStore()

/** Flow screens are reached from a match, not from the bar. */
const FLOW_ROUTE_NAMES = new Set(['placement', 'rps', 'game', 'game-over'])
const screenFailed = ref(false)
// A failed flow screen falls back to the normal bar: with the destinations
// hidden the player would have no way to leave the error screen.
const immersive = computed(() => FLOW_ROUTE_NAMES.has(String(route.name)) && !screenFailed.value)

const destinations = [
  { name: 'start', label: '开战' },
  { name: 'lobby', label: '大厅' },
  { name: 'battle-pass', label: '通行证' },
  { name: 'shop', label: '商店' },
  { name: 'leaderboard', label: '排行' },
]
const shop = useShopStore()
const mailbox = useMailboxStore()
const checkin = useCheckinStore()
const checkinOpen = ref(false)
const checkinButton = ref<HTMLButtonElement | null>(null)
let checkinRouterReady = false
let mailPoll: number | null = null
let checkinPoll: number | null = null

/* ---- 开屏：Logo 段（可跳过）→ 开战页模块拼接 ----------------------------
 * 触发策略全在 `src/splash/splashPolicy.ts` 里（有单测）。这里只负责状态与
 * 时序：等路由就绪后决定播不播、播完再放签到弹窗出去。
 */
type SplashPhase = 'pending' | 'logo' | 'assemble' | 'idle'
const splashPhase = ref<SplashPhase>('pending')
const splashReducedMotion = ref(false)
let splashAssembleTimer: number | null = null
let splashFallbackTimer: number | null = null
let splashDecided = false
let splashPendingAssembly = false

/** 开屏（含「等路由就绪」这一段）期间，签到弹窗一律等待。 */
const splashActive = computed(() => splashPhase.value !== 'idle')

// 开屏不播曲。待命页之间不换曲；胜负页不换曲；对局和终局层看路由和双方未沉舰数。
watch(
  () => [
    typeof route.name === 'string' ? route.name : '',
    splashActive.value,
    game.state.state,
    game.state.remaining_ships,
    game.state.opponent_remaining_ships,
  ] as const,
  ([routeName, splash, roomState, selfShips, opponentShips]) => {
    audio.syncBgmScene({
      routeName: routeName || null,
      splashActive: splash,
      roomState,
      selfShips,
      opponentShips,
    })
  },
  { immediate: true },
)

function splashStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage
  } catch {
    return null
  }
}

function startSplashDecision(): void {
  if (splashDecided) return
  splashDecided = true
  if (splashFallbackTimer !== null) {
    window.clearTimeout(splashFallbackTimer)
    splashFallbackTimer = null
  }
  if (splashPhase.value !== 'pending') return
  const decision = decideSplash({
    alreadyPlayed: !processSplashGate.shouldPlay(),
    routeName: router.currentRoute.value.name ? String(router.currentRoute.value.name) : null,
    hasSeat: hasReconnectSeat(splashStorage()),
  })
  splashPendingAssembly = decision.assemble
  if (!decision.logo) {
    finishSplash()
    return
  }
  splashReducedMotion.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  splashPhase.value = 'logo'
}

function onSplashLogoDone(): void {
  // 跳过 Logo 不跳过拼接：只要这次冷启动落在开战页，拼接仍然要看完。
  if (splashPendingAssembly && router.currentRoute.value.name === 'start') {
    splashPhase.value = 'assemble'
    splashAssembleTimer = window.setTimeout(() => finishSplash(), ASSEMBLE_MS + 80)
    return
  }
  finishSplash()
}

function finishSplash(): void {
  if (splashAssembleTimer !== null) {
    window.clearTimeout(splashAssembleTimer)
    splashAssembleTimer = null
  }
  splashPendingAssembly = false
  splashPhase.value = 'idle'
  processSplashGate.markPlayed()
  // 开屏整段结束后，才按既有规则决定要不要弹签到。
  void refreshCheckin()
}

function refreshMailbox(): void {
  if (!auth.isGuest && !immersive.value && !document.hidden) void mailbox.load()
}
function rememberCheckinPrompt(): void {
  const today = checkin.today
  const userId = auth.user?.id
  if (!today || !userId) return
  writeCheckinAutoShown(userId, today)
}
function closeCheckin(): void {
  checkinOpen.value = false
}
async function noteCheckinShown(): Promise<void> {
  await nextTick()
  // 导航收尾若已把弹层关掉，这里不能记成「今天提示过」。
  if (!checkinRouterReady || !checkinOpen.value || immersive.value || auth.isGuest) return
  rememberCheckinPrompt()
}
function openCheckin(): void {
  if (auth.isGuest) {
    ui.requestLogin('login', '登录后即可每日签到。')
    return
  }
  checkinOpen.value = true
}
function maybeAutoOpenCheckin(): void {
  // 首屏导航结束前不要打开：afterEach 会立刻关掉弹层。
  // 「已提示」只在弹层真正留在屏幕上之后再记，不能记在这次被关掉的瞬间。
  if (!checkinRouterReady) return
  // 开屏（Logo / 拼接）还在进行时先让路：两层不能叠在一起。
  if (splashActive.value) return
  if (auth.isGuest || immersive.value || checkinOpen.value || document.hidden) return
  if (ui.activeDialog) return
  if (!checkin.showRedDot || checkin.todayChecked) return
  const today = checkin.today
  const userId = auth.user?.id
  if (!today || !userId) return
  if (readCheckinAutoShown(userId, today)) return
  checkinOpen.value = true
}
async function refreshCheckin(): Promise<void> {
  if (auth.isGuest) {
    checkin.reset()
    checkinOpen.value = false
    return
  }
  if (immersive.value || document.hidden) return
  await checkin.load()
  maybeAutoOpenCheckin()
}
function onCheckinVisibility(): void {
  void refreshCheckin()
}
onMounted(() => {
  refreshMailbox()
  // 路由就绪后再决定开屏：邀请链接这类 beforeEach 重定向已经落定，
  // 否则会把「目标是大厅」误判成「目标是开战」。
  splashFallbackTimer = window.setTimeout(() => {
    splashFallbackTimer = null
    if (splashPhase.value === 'pending') finishSplash()
  }, 2000)
  void router.isReady().then(() => {
    checkinRouterReady = true
    startSplashDecision()
    if (checkinOpen.value) void noteCheckinShown()
    // 开屏期间先不拉签到；finishSplash() 会补一次。
    if (splashActive.value) return
    return refreshCheckin()
  })
  mailPoll = window.setInterval(refreshMailbox, 60000)
  checkinPoll = window.setInterval(onCheckinVisibility, 60000)
  document.addEventListener('visibilitychange', refreshMailbox)
  document.addEventListener('visibilitychange', onCheckinVisibility)
})
onBeforeUnmount(() => {
  if (mailPoll !== null) window.clearInterval(mailPoll)
  if (checkinPoll !== null) window.clearInterval(checkinPoll)
  if (splashAssembleTimer !== null) window.clearTimeout(splashAssembleTimer)
  if (splashFallbackTimer !== null) window.clearTimeout(splashFallbackTimer)
  document.removeEventListener('visibilitychange', refreshMailbox)
  document.removeEventListener('visibilitychange', onCheckinVisibility)
})
watch(() => auth.isGuest, guest => { if (guest) mailbox.reset(); else refreshMailbox() })
watch(checkinOpen, (open) => { if (open) void noteCheckinShown() })
watch(() => auth.user?.id ?? '', (id, previous) => {
  if (id === previous) return
  checkin.reset()
  checkinOpen.value = false
  if (!id) return
  void refreshCheckin()
  void shop.load(true)
})
watch(immersive, (value, previous) => {
  if (value && checkinOpen.value) closeCheckin()
  if (previous && !value) void refreshCheckin()
})
watch(() => checkin.todayChecked, (checked) => { if (checked) rememberCheckinPrompt() })
watch(() => ui.activeDialog?.id ?? null, (id, previous) => {
  if (previous && !id) maybeAutoOpenCheckin()
})
watch(() => auth.isGuest, (guest) => {
  if (guest) shop.reset()
  else void shop.load(true)
}, { immediate: true })
watch(() => route.fullPath, async () => {
  await nextTick()
  const link = document.querySelector<HTMLElement>('.app-nav__link[aria-current="page"]')
  const scroller = link?.parentElement
  if (!link || !scroller || scroller.scrollWidth <= scroller.clientWidth + 1) return
  link.scrollIntoView({ inline: 'nearest', block: 'nearest' })
})

const loading = computed(() => routeLoading.value)

const menuOpen = ref(false)
const consoleOpen = ref(false)
async function consoleHotkey(event: KeyboardEvent): Promise<void> {
  if (event.key !== 'F8' || event.repeat || auth.isGuest) return
  event.preventDefault()
  if (consoleOpen.value) { consoleOpen.value = false; return }
  try {
    const response = await fetch('/api/admin/me')
    if (response.ok && (await response.json()).is_admin === true) consoleOpen.value = true
  } catch { /* 网络中断时保持关闭；服务端仍独立校验权限。 */ }
}
onMounted(() => window.addEventListener('keydown', consoleHotkey))
onBeforeUnmount(() => window.removeEventListener('keydown', consoleHotkey))
watch(() => auth.isGuest, guest => { if (guest) consoleOpen.value = false })
const avatarButton = ref<HTMLButtonElement | null>(null)
const collectionButton = ref<HTMLButtonElement | null>(null)

function toggleMenu(): void {
  menuOpen.value = !menuOpen.value
}

function closeMenu(): void {
  const wasOpen = menuOpen.value
  menuOpen.value = false
  // Keyboard users land back on the trigger, never on a detached node.
  if (wasOpen) avatarButton.value?.focus()
}

function openCollection(): void {
  menuOpen.value = false
  collection.open()
}

/** What leaving costs, in the same words the settlement would use. */
const immersivePenalty = computed(() => {
  if (isInitialBanPlacement(game.state)) {
    if (game.state.mode === 'custom') return '退出自定义房不算逃跑，不会扣排位分。'
    return game.state.card_bans?.phase === 'revealed'
      ? '双方已亮牌，整个布船阶段退出均按逃跑判负扣分；对手无结算收益并返回排位队列。'
      : '尚未亮牌，退出不会触发亮牌后的排位逃跑处罚。'
  }
  return game.state.ranked ? '本局按判负结算并扣段位分。' : '本局按判负结算（休闲/人机不计段位分）。'
})

function retryConnection(): void {
  window.location.reload()
}

/** The reconnect could not restore the seat: the player can still leave. */
function exitToHome(): void {
  ui.clearConnectionIssue()
  void router.push({ name: 'start' })
}

const exitPending = ref(false)
async function exitMatch(): Promise<void> {
  if (exitPending.value) return
  if (game.state.card_bans && game.state.state === 'placing_ships') {
    const socket = getSettlementSocket()
    if (!socket?.socket.connected || !game.state.room_id || !game.state.player_id) {
      ui.notify({ code: 'card-ban-exit-disconnected', message: '连接未就绪，请重连后再退出。', tone: 'error' })
      return
    }
    exitPending.value = true
    try {
      const ack = await socket.emitEvent('surrender', { room_id: game.state.room_id, player_id: game.state.player_id })
      if (ack.status !== 'success') {
        ui.notify({ code: 'card-ban-exit-rejected', message: ack.message || '退出未成功，请重试。', tone: 'error' })
        return
      }
      forgetSeat()
      game.reset()
    } catch {
      ui.notify({ code: 'card-ban-exit-failed', message: '退出未确认，请检查连接后重试。', tone: 'error' })
      return
    } finally { exitPending.value = false }
  }
  ui.cancelExit()
  const destination = exitDestination
  exitDestination = '/lobby'
  void router.push(destination)
}

/**
 * Cross-ticket login entry (ticket #44): any screen may ask for the overlay by
 * dispatching a bs:auth-required CustomEvent instead of linking to /login
 * (the server keeps 302-ing that route to the home screen). Ticket #48 uses it
 * for the spectate / replay guest call to action.
 */
function onAuthRequired(event: Event): void {
  const detail = event instanceof CustomEvent ? (event.detail as { mode?: string; reason?: string } | null) : null
  const mode = detail?.mode === 'register' ? 'register' : 'login'
  auth.open(mode, typeof detail?.reason === 'string' ? detail.reason : '')
}

onMounted(() => window.addEventListener('bs:auth-required', onAuthRequired))
onBeforeUnmount(() => window.removeEventListener('bs:auth-required', onAuthRequired))

/**
 * 好友事件的生命周期挂在**登录状态**上，而不是面板挂载（审查 P2-3）：
 * 面板关着的时候也要收私聊与申请，否则关掉面板就再也收不到推送。
 * 面板可见性单独交给 dm.setVisible，标读只发生在玩家正看着的会话里。
 */
let releaseFriends: (() => void) | null = null

function syncFriendsChannel(guest: boolean): void {
  if (!guest && !releaseFriends) {
    try {
      releaseFriends = acquireFriendsChannel()
    } catch {
      // 还没有共享 socket（未进过对局/大厅）时先跳过，后续登录态变化会再试
      releaseFriends = null
    }
    return
  }
  if (guest && releaseFriends) {
    releaseFriends()
    releaseFriends = null
    dm.reset()
  }
}

watch(() => auth.isGuest, (guest) => syncFriendsChannel(Boolean(guest)), { immediate: true })
watch(() => ui.friendsOpen, (open) => dm.setVisible(open), { immediate: true })

onBeforeUnmount(() => {
  releaseFriends?.()
  releaseFriends = null
})
</script>

<template>
  <!-- 全局交互装饰：覆盖首页、对局与所有弹层，但永远不拦截点击。 -->
  <GlobalPointerEffects />
  <!-- 个人资料背景是应用级装饰，跟随已装备的 profile_bg_id 覆盖所有主界面。 -->
  <AppProfileBackground />
  <!-- Applied wallpaper layer (spec story 2); renders nothing until applied. -->
  <AppWallpaper />
  <OceanParticles />
  <div class="app-theme-scrim" aria-hidden="true"></div>

  <!-- 冷启动的 Logo 亮相层：只在本次进程第一次打开、且不是回到对局时出现。 -->
  <SplashScreen
    v-if="splashPhase === 'logo'"
    :reduced-motion="splashReducedMotion"
    @done="onSplashLogoDone"
  />

  <!-- Single-overlay root: the card archive opens above the shell. -->
  <CardCollectionOverlay
    v-if="collection.isOpen"
    :return-focus="() => collectionButton"
    @close="collection.close()"
  />

  <HelpOverlay v-if="ui.helpOpen" @close="ui.closeHelp()" />
  <FriendsOverlay v-if="ui.friendsOpen" @close="ui.closeFriends()" />
  <CheckinDialog v-if="checkinOpen && !immersive" :return-focus="() => checkinButton" @close="closeCheckin" />
  <AdminOverlay v-if="ui.adminOpen" @close="ui.closeAdmin()" />
  <AdminConsole v-if="consoleOpen" @close="consoleOpen = false" />
  <div v-if="game.state.admin_test && game.state.room_id" class="admin-test-banner" role="status">管理员测试局 · 不计战绩与奖励</div>

  <div class="app-shell" data-testid="app-shell" :data-route-loading="loading ? 'true' : 'false'" :data-immersive="immersive ? 'true' : 'false'" :data-splash-phase="splashPhase">
    <!-- 连接提示走覆盖层：多提示堆叠在导航下方，不把舞台往下推。 -->
    <div class="app-connection-stack" data-testid="connection-stack">
    <div
      v-if="ui.connection === 'offline'"
      class="app-connection"
      data-testid="connection-banner"
      role="alert"
      aria-live="assertive"
    >
      <span class="app-connection__text">连接中断，正在重连…</span>
      <button type="button" class="app-connection__retry" data-testid="app-connection-retry" @click="retryConnection">
        重新连接
      </button>
      <button type="button" class="app-connection__retry" data-testid="app-connection-exit" @click="exitToHome">
        回首页
      </button>
    </div>

    <div
      v-if="ui.connectionIssue"
      class="app-connection app-connection--issue"
      data-testid="connection-issue"
      role="alert"
      aria-live="assertive"
    >
      <span class="app-connection__text">{{ ui.connectionIssue }}</span>
      <button type="button" class="app-connection__retry" data-testid="connection-issue-retry" @click="retryConnection">
        重新连接
      </button>
      <button type="button" class="app-connection__retry" data-testid="connection-issue-exit" @click="exitToHome">
        回首页
      </button>
    </div>
    </div>

    <nav class="app-nav" :class="{ 'app-nav--flow': immersive }" data-testid="app-nav" aria-label="主屏导航">
      <component
        :is="immersive ? 'div' : 'router-link'"
        class="app-brand"
        :to="immersive ? undefined : '/'"
        :aria-label="immersive ? undefined : '回到首页'"
      >
        <span class="app-brand__mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
            <path d="M12 3v18M5 8l7-4 7 4M4 14h16l-3 6H7z" />
          </svg>
        </span>
        <span class="app-brand__text">
          <b class="app-brand__title">战舰棋 · 作战室</b>
          <small class="app-brand__sub">深海作战室</small>
        </span>
      </component>

      <div v-if="immersive" class="app-nav__links app-nav__links--flow">
        <button type="button" class="app-nav__flow" data-testid="nav-exit" @click="ui.requestExit()">
          退出对局
        </button>
        <router-link class="app-nav__flow" :to="{ name: 'settings' }" data-testid="nav-settings">设置</router-link>
      </div>

      <template v-else>
        <div class="app-nav__links">
          <router-link
            v-for="item in destinations.filter((entry) => entry.name !== 'leaderboard')"
            :key="item.name"
            :to="{ name: item.name }"
            class="app-nav__link"
            :class="{ 'is-active': item.name === 'lobby' && String(route.name).startsWith('lobby') }"
            :data-testid="'nav-' + item.name"
          >
            {{ item.label }}
          </router-link>
          <button
            ref="collectionButton"
            type="button"
            class="app-nav__link"
            :class="{ 'is-active': collection.isOpen }"
            :aria-pressed="collection.isOpen"
            data-testid="nav-collection"
            @click="openCollection"
          >
            图鉴
          </button>
          <router-link
            v-for="item in destinations.filter((entry) => entry.name === 'leaderboard')"
            :key="item.name"
            :to="{ name: item.name }"
            class="app-nav__link"
            :data-testid="'nav-' + item.name"
          >
            {{ item.label }}
          </router-link>
        </div>

        <div class="app-nav__meta">
          <TideAshBadge />
          <button
            ref="checkinButton"
            type="button"
            class="app-nav__icon"
            data-testid="nav-checkin"
            :aria-expanded="checkinOpen"
            aria-haspopup="dialog"
            :aria-label="!auth.isGuest && checkin.showRedDot ? '每日签到（今日未签）' : '每日签到'"
            title="每日签到"
            @click="openCheckin"
          >
            <span
              v-if="!auth.isGuest && checkin.showRedDot"
              class="app-nav__badge app-nav__badge--dot"
              data-testid="nav-checkin-dot"
              aria-hidden="true"
            ></span>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <rect x="4" y="5" width="16" height="15" rx="2" />
              <path d="M8 3.5v3M16 3.5v3M4 9.5h16" />
              <path d="m8.5 14.2 2.1 2.1 4.6-4.8" />
            </svg>
          </button>
          <router-link class="app-nav__icon" :to="{ name: 'mailbox' }" data-testid="nav-mailbox" :aria-label="mailbox.unclaimedCount ? `邮箱（${mailbox.unclaimedCount} 封待领附件）` : '邮箱'" title="邮箱">
            <span v-if="mailbox.unclaimedCount" class="app-nav__badge" data-testid="nav-mailbox-badge">{{ mailbox.unclaimedCount }}</span>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></svg>
          </router-link>
          <button
            type="button"
            class="app-nav__icon"
            data-testid="nav-friends"
            :aria-pressed="ui.friendsOpen"
            :aria-label="dm.totalUnread ? `好友（${dm.totalUnread} 条未读）` : '好友'"
            @click="ui.openFriends()"
          >
            <span v-if="dm.totalUnread" class="app-nav__badge" data-testid="nav-friends-unread">{{ dm.totalUnread }}</span>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <circle cx="9" cy="8" r="3.2" />
              <path d="M3.5 20c.6-3.4 2.9-5 5.5-5s4.9 1.6 5.5 5" />
              <path d="M16 5.5a3 3 0 0 1 0 5.6M17.5 15.4c1.8.6 2.9 2.1 3.2 4.6" />
            </svg>
          </button>

          <div class="app-avatar">
            <button
              ref="avatarButton"
              type="button"
              class="app-nav__icon app-avatar__trigger"
              :aria-expanded="menuOpen"
              aria-haspopup="menu"
              data-testid="nav-avatar"
              @click="toggleMenu"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                <circle cx="12" cy="9" r="3.6" />
                <path d="M4.5 20c.9-3.9 3.9-5.6 7.5-5.6s6.6 1.7 7.5 5.6" />
              </svg>
            </button>
            <AvatarMenu v-if="menuOpen" @close="closeMenu" />
          </div>
          <router-link
            class="app-nav__icon"
            :to="{ name: 'settings' }"
            data-testid="nav-settings"
            aria-label="设置"
            title="设置"
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true">
              <path d="m9.5 3-.6 2.3-1.7 1-2.3-.6-2.5 4.3 1.7 1.7v2l-1.7 1.7 2.5 4.3 2.3-.6 1.7 1 .6 2.3h5l.6-2.3 1.7-1 2.3.6 2.5-4.3-1.7-1.7v-2l1.7-1.7-2.5-4.3-2.3.6-1.7-1-.6-2.3z" />
              <circle cx="12" cy="12.7" r="3" />
            </svg>
          </router-link>
        </div>
      </template>
    </nav>

    <!-- A thin progress line instead of an in-flow notice: switching screens
         no longer pushes the content down and back. -->
    <div v-if="loading" class="route-loading" data-testid="route-loading" role="status" aria-live="polite">
      <span class="route-loading__bar" aria-hidden="true"></span>
      <span class="sr-only">正在切换界面…</span>
    </div>

    <ScreenBoundary @error="screenFailed = true" @recovered="screenFailed = false">
      <router-view v-slot="{ Component, route: viewRoute }">
        <component :is="Component" v-if="Component" :key="viewRoute.matched[0]?.path || viewRoute.path" />
      </router-view>
      <slot name="screen-extra" />
    </ScreenBoundary>
  </div>

  <AuthOverlay v-if="auth.overlayOpen" @close="auth.close()" />

  <AppOverlay
    v-if="ui.exitConfirmOpen"
    id="exit-confirm"
    :priority="250"
    labelledby="exit-confirm-title"
    @close="cancelExit()"
  >
    <div class="confirm">
      <h2 id="exit-confirm-title" class="confirm__title">退出这一局？</h2>
      <p class="confirm__text">退出会中断当前对局，已经打出的进度不会保留；{{ immersivePenalty }}</p>
      <div class="confirm__actions">
        <button type="button" class="button" data-testid="exit-confirm-cancel" @click="cancelExit()">继续对局</button>
        <button type="button" class="button button--danger" data-testid="exit-confirm-ok" :disabled="exitPending" @click="exitMatch">{{ exitPending ? '正在退出…' : '确认退出' }}</button>
      </div>
    </div>
  </AppOverlay>

  <ToastHost />
  <DiceRollOverlay
    :self-id="game.state.player_id"
    :self-name="game.state.player_name || '你'"
    :opponent-name="game.state.opponent_name || '对手'"
  />
</template>

<style>
/* 手机壳层（导航高度契约、单行工具栏、覆盖式连接提示、安全区）。 */
@import './styles/mobile-shell.css';
/* 开屏：Logo 层与开战页模块拼接（状态由 data-splash-phase 驱动）。 */
@import './styles/splash.css';
</style>
