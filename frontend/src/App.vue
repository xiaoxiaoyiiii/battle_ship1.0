<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppOverlay from './components/AppOverlay.vue'
import AppWallpaper from './components/AppWallpaper.vue'
import OceanParticles from './components/OceanParticles.vue'
import AuthOverlay from './components/AuthOverlay.vue'
import AvatarMenu from './components/AvatarMenu.vue'
import CardCollectionOverlay from './components/CardCollectionOverlay.vue'
import AdminOverlay from './components/AdminOverlay.vue'
import FriendsOverlay from './components/FriendsOverlay.vue'
import HelpOverlay from './components/HelpOverlay.vue'
import ScreenBoundary from './components/ScreenBoundary.vue'
import ToastHost from './components/ToastHost.vue'
import DiceRollOverlay from './screens/game/DiceRollOverlay.vue'
import { routeLoading } from './router'
import { useAuthStore } from './stores/auth'
import { useDmStore } from './stores/dm'
import { acquireFriendsChannel } from './realtime/friends'
import { useCollectionStore } from './stores/collection'
import { useGameStore } from './stores/game'
import { useUiStore } from './stores/ui'
import { useAudioStore } from './stores/audio'

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
const audio = useAudioStore()
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
  { name: 'leaderboard', label: '排行' },
]

const loading = computed(() => routeLoading.value)

const menuOpen = ref(false)
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
const immersivePenalty = computed(() =>
  game.state.ranked ? '本局按判负结算并扣段位分。' : '本局按判负结算（休闲/人机不计段位分）。',
)

function retryConnection(): void {
  window.location.reload()
}

/** The reconnect could not restore the seat: the player can still leave. */
function exitToHome(): void {
  ui.clearConnectionIssue()
  void router.push({ name: 'start' })
}

function exitMatch(): void {
  ui.cancelExit()
  void router.push({ name: 'lobby' })
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
  <!-- Applied wallpaper layer (spec story 2); renders nothing until applied. -->
  <AppWallpaper />
  <OceanParticles />

  <!-- Single-overlay root: the card archive opens above the shell. -->
  <CardCollectionOverlay
    v-if="collection.isOpen"
    :return-focus="() => collectionButton"
    @close="collection.close()"
  />

  <HelpOverlay v-if="ui.helpOpen" @close="ui.closeHelp()" />
  <FriendsOverlay v-if="ui.friendsOpen" @close="ui.closeFriends()" />
  <AdminOverlay v-if="ui.adminOpen" @close="ui.closeAdmin()" />

  <div class="app-shell" data-testid="app-shell" :data-route-loading="loading ? 'true' : 'false'" :data-immersive="immersive ? 'true' : 'false'">
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
        <component :is="Component" v-if="Component" :key="viewRoute.path" />
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
    @close="ui.cancelExit()"
  >
    <div class="confirm">
      <h2 id="exit-confirm-title" class="confirm__title">退出这一局？</h2>
      <p class="confirm__text">退出会中断当前对局，已经打出的进度不会保留；{{ immersivePenalty }}</p>
      <div class="confirm__actions">
        <button type="button" class="button" data-testid="exit-confirm-cancel" @click="ui.cancelExit()">继续对局</button>
        <button type="button" class="button button--danger" data-testid="exit-confirm-ok" @click="exitMatch">确认退出</button>
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
