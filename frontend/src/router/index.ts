import { ref } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { INVITE_PARAM, INVITE_TOKEN_PARAM, readInviteRoomId, readInviteToken } from '../screens/lobby/inviteLink'
import { hasReconnectSeat, shouldRedirectLobbyToStart } from '../splash/splashPolicy'

/**
 * The eleven screens of ticket #21. Names are frozen: they are the route
 * contract used by the port map (notes/14) and by the external browser gate.
 * Business screens land in #22–#28; these are placeholders only.
 */
const routes: RouteRecordRaw[] = [
  { path: '/', name: 'start', component: () => import('../screens/start/StartScreen.vue') },
  { path: '/placement', name: 'placement', component: () => import('../screens/placement/PlacementScreen.vue') },
  { path: '/rps', name: 'rps', component: () => import('../screens/rps/RpsScreen.vue') },
  { path: '/game', name: 'game', component: () => import('../screens/game/GameScreen.vue') },
  { path: '/lobby', component: () => import('../screens/lobby/LobbyLayout.vue'), children: [
    { path: '', name: 'lobby', component: () => import('../screens/lobby/LobbyScreen.vue') },
    { path: 'rooms', name: 'lobby-rooms', component: () => import('../screens/lobby/LobbyDirectoryScreen.vue'), props: { kind: 'rooms' } },
    { path: 'matches', name: 'lobby-matches', component: () => import('../screens/lobby/LobbyDirectoryScreen.vue'), props: { kind: 'matches' } },
    { path: 'create', name: 'lobby-create', component: () => import('../screens/lobby/RoomCreateScreen.vue') },
    { path: 'room', name: 'lobby-room', component: () => import('../screens/lobby/RoomWaitingScreen.vue') },
  ] },
  { path: '/leaderboard', name: 'leaderboard', component: () => import('../screens/leaderboard/LeaderboardScreen.vue') },
  { path: '/profile', name: 'profile', component: () => import('../screens/profile/ProfileScreen.vue') },
  { path: '/settings', name: 'settings', component: () => import('../screens/settings/SettingsScreen.vue') },
  { path: '/mailbox', name: 'mailbox', component: () => import('../screens/mailbox/MailboxScreen.vue') },
  { path: '/admin/mailbox', name: 'admin-mailbox', component: () => import('../screens/mailbox/AdminMailScreen.vue') },
  { path: '/welcome', name: 'welcome', component: () => import('../screens/start/WelcomeScreen.vue') },
  { path: '/terms', name: 'terms', component: () => import('../screens/legal/LegalScreen.vue'), props: { kind: 'terms' } },
  { path: '/privacy', name: 'privacy', component: () => import('../screens/legal/LegalScreen.vue'), props: { kind: 'privacy' } },
  { path: '/battle-pass', name: 'battle-pass', component: () => import('../screens/battle-pass/SeasonPassScreen.vue') },
  { path: '/shop', name: 'shop', component: () => import('../screens/shop/ShopScreen.vue') },
  { path: '/collection', name: 'collection', component: () => import('../screens/collection/CollectionScreen.vue') },
  { path: '/replay', name: 'replay', component: () => import('../screens/replay/ReplayScreen.vue') },
  { path: '/spectate', name: 'spectate', component: () => import('../screens/spectate/SpectateScreen.vue') },
  { path: '/game-over', name: 'game-over', component: () => import('../screens/game-over/GameOverScreen.vue') },
  // No new route name: unknown deep links return to the start screen.
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const routeLoading = ref(false)

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

// 冷启动只看第一次导航：之后用户点「大厅」不能被弹回开战页。
let initialNavigationDone = false

function splashSessionStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage
  } catch {
    return null
  }
}

// Loading state for both initial navigation and in-app switches. The shell
// renders [data-testid="route-loading"] while this is true and records the
// transitions for the external gate.
router.beforeEach((to) => {
  routeLoading.value = true
  const isInitialNavigation = !initialNavigationDone
  initialNavigationDone = true
  // 邀请链接可能被贴到首页：房间号合法时转到大厅，由大厅统一走既有 join_room。
  if (to.name === 'start' && readInviteRoomId(to.query)) {
    return { name: 'lobby', query: { [INVITE_PARAM]: readInviteRoomId(to.query),
      ...(readInviteToken(to.query) ? { [INVITE_TOKEN_PARAM]: readInviteToken(to.query) } : {}) } }
  }
  // 桌面壳 1.0.1 写死打开 /lobby：首次冷启动且没有邀请、没有可重连座位时改回开战页，
  // 这样开屏决策看到的落点就是 start，Logo 之后的拼接段才会播。必须用 replace，
  // 否则用户按返回会回到大厅又触发一次重定向。
  if (shouldRedirectLobbyToStart({
    routeName: typeof to.name === 'string' ? to.name : null,
    hasInvite: Boolean(readInviteRoomId(to.query)),
    hasSeat: hasReconnectSeat(splashSessionStorage()),
    isInitialNavigation,
  })) {
    return { name: 'start', replace: true }
  }
  return true
})
router.afterEach(() => {
  routeLoading.value = false
})
router.onError(() => {
  routeLoading.value = false
})

export default router
