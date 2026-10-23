<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useCollectionStore } from '../stores/collection'
import { THEME_LABELS, useUiStore, type ThemeName } from '../stores/ui'

/**
 * Avatar menu: the only home of settings, appearance, help and login (spec
 * story 13-15, ticket #42). Three intent groups, no new routes.
 */
const emit = defineEmits<{ (event: 'close'): void }>()

const ui = useUiStore()
const collection = useCollectionStore()
const auth = useAuthStore()
const panel = ref<HTMLElement | null>(null)

const themes: ThemeName[] = ['chart', 'journal', 'night']

onMounted(() => {
  panel.value?.querySelector<HTMLElement>('a, button')?.focus()
})

function chooseTheme(theme: ThemeName): void {
  ui.setTheme(theme)
  ui.notify({ code: 'theme-' + theme, tone: 'success', message: '已切换到「' + THEME_LABELS[theme] + '」主题' })
}

function toggleMotion(): void {
  const next = ui.motion === 'reduced' ? 'auto' : 'reduced'
  ui.setMotion(next)
  ui.notify({
    code: 'motion-' + next,
    tone: 'success',
    message: next === 'reduced' ? '已减少动效，只保留状态变化' : '已恢复完整动效',
  })
}

function openCollection(): void {
  collection.open()
  emit('close')
}

function openHelp(): void {
  close()
  ui.openHelp()
}

function close(): void {
  emit('close')
}

/** Guest first item: open the app-level overlay instead of the dead /login page. */
function openLogin(): void {
  emit('close')
  auth.open('login')
}

/** Logged-in exit: the existing frozen /logout redirect (spec section 3). */
function logout(): void {
  emit('close')
  auth.requestLogout()
}
</script>

<template>
  <div class="app-menu-scrim" data-testid="avatar-menu-scrim" @click="close"></div>
  <section
    ref="panel"
    class="app-menu"
    data-testid="avatar-menu"
    role="menu"
    aria-label="账号与设置"
    @keydown.esc.stop.prevent="close"
  >
    <section class="app-menu__group" data-testid="avatar-group-mine" aria-labelledby="avatar-group-mine-title">
      <h2 id="avatar-group-mine-title" class="app-menu__title">我的</h2>
      <button
        v-if="auth.isGuest"
        type="button"
        class="app-menu__item app-menu__item--auth"
        data-testid="avatar-item-login"
        @click="openLogin"
      >
        登录 / 注册
      </button>
      <router-link class="app-menu__item" :to="{ name: 'profile' }" data-testid="avatar-item-profile" @click="close">
        名片与战绩
      </router-link>
      <button type="button" class="app-menu__item" data-testid="avatar-item-collection" @click="openCollection">
        收藏（图鉴）
      </button>
    </section>

    <section class="app-menu__group" data-testid="avatar-group-appearance" aria-labelledby="avatar-group-appearance-title">
      <h2 id="avatar-group-appearance-title" class="app-menu__title">外观与声音</h2>
      <div class="app-menu__themes" role="group" aria-label="主题">
        <button
          v-for="theme in themes"
          :key="theme"
          type="button"
          class="app-menu__theme"
          :class="{ 'is-active': ui.theme === theme }"
          :data-testid="'theme-' + theme"
          :aria-pressed="ui.theme === theme"
          @click="chooseTheme(theme)"
        >
          {{ THEME_LABELS[theme] }}
        </button>
      </div>
      <button
        type="button"
        class="app-menu__item app-menu__item--toggle"
        data-testid="avatar-item-motion"
        :aria-pressed="ui.motion === 'reduced'"
        @click="toggleMotion"
      >
        减少动效
      </button>
      <router-link class="app-menu__item" :to="{ name: 'settings' }" data-testid="avatar-item-settings" @click="close">
        声音与设置
      </router-link>
    </section>

    <section class="app-menu__group" data-testid="avatar-group-about" aria-labelledby="avatar-group-about-title">
      <h2 id="avatar-group-about-title" class="app-menu__title">帮助与关于</h2>
      <button
        type="button"
        class="app-menu__item"
        data-testid="avatar-item-help"
        @click="openHelp"
      >
        玩法与帮助
      </button>
      <button
        v-if="!auth.isGuest"
        type="button"
        class="app-menu__item"
        data-testid="avatar-item-logout"
        @click="logout"
      >
        退出登录
      </button>
      <p class="app-menu__version" data-testid="avatar-version">深海作战室 · 基础版</p>
    </section>

    <p v-if="auth.isGuest" class="app-menu__identity" data-testid="avatar-guest-name">
      游客 · {{ auth.guestName }} · 登录后保存段位与战绩
    </p>
    <p v-else class="app-menu__identity" data-testid="avatar-user-name">已登录 · {{ auth.displayName }}</p>
  </section>
</template>

<style scoped>
/* Identity line under the three groups: the one place the guest name and the
   logged-in name are stated without competing with the menu items. */
.app-menu__identity {
  margin: 0;
  padding: 8px 10px 2px;
  border-top: 1px solid var(--border-subtle);
  color: var(--text-tertiary);
  font-size: 11px;
  line-height: 1.5;
}

.app-menu__item--auth {
  border-color: var(--role-action);
  background: var(--role-action-soft);
  font-weight: 600;
}
</style>
