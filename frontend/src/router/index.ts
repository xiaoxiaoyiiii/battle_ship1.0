import { ref } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { INVITE_PARAM, readInviteRoomId } from '../screens/lobby/inviteLink'

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
  { path: '/lobby', name: 'lobby', component: () => import('../screens/lobby/LobbyScreen.vue') },
  { path: '/leaderboard', name: 'leaderboard', component: () => import('../screens/leaderboard/LeaderboardScreen.vue') },
  { path: '/profile', name: 'profile', component: () => import('../screens/profile/ProfileScreen.vue') },
  { path: '/settings', name: 'settings', component: () => import('../screens/settings/SettingsScreen.vue') },
  { path: '/battle-pass', name: 'battle-pass', component: () => import('../screens/battle-pass/SeasonPassScreen.vue') },
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

// Loading state for both initial navigation and in-app switches. The shell
// renders [data-testid="route-loading"] while this is true and records the
// transitions for the external gate.
router.beforeEach((to) => {
  routeLoading.value = true
  // 邀请链接可能被贴到首页：房间号合法时转到大厅，由大厅统一走既有 join_room。
  if (to.name === 'start' && readInviteRoomId(to.query)) {
    return { name: 'lobby', query: { [INVITE_PARAM]: readInviteRoomId(to.query) } }
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
