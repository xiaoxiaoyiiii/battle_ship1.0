<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AppOverlay from './AppOverlay.vue'
import { useAuthStore, type AuthTab } from '../stores/auth'

/**
 * App-level login / register overlay (ticket #44, spec section 3).
 *
 * One dialog for both intents: two tabs share the same two fields, because the
 * frozen JSON contract of POST /login and POST /register only needs a username
 * and a password. The component owns the draft fields; the auth store owns the
 * request, the player-facing error mapping and the reload on success.
 *
 * The panel is the shared AppOverlay primitive (#42): real dialog role, focus
 * trap, Esc and backdrop close, focus returned to the trigger. Only this
 * overlay's panel width is narrowed, via the data-overlay selector below.
 */
const emit = defineEmits<{ (event: 'close'): void }>()

const auth = useAuthStore()
const username = ref('')
const password = ref('')
const usernameInput = ref<HTMLInputElement | null>(null)

const isRegister = computed(() => auth.tab === 'register')
const title = computed(() => (isRegister.value ? '创建作战室账号' : '登录作战室'))
const hint = computed(() =>
  isRegister.value
    ? '用户名至少 3 位，密码至少 6 位；注册成功即登录。'
    : '还没有账号？切到「注册」当场创建一个。',
)
const submitLabel = computed(() => {
  if (auth.busy) return isRegister.value ? '注册中…' : '登录中…'
  return isRegister.value ? '注册并登录' : '登录'
})

function close(): void {
  emit('close')
}

function choose(tab: AuthTab): void {
  auth.switchTab(tab)
}

function onSubmit(): void {
  void auth.submit(username.value, password.value)
}

// Switching tabs never carries a stale failure across.
watch(
  () => auth.tab,
  async () => {
    auth.clearError()
    await nextTick()
    usernameInput.value?.focus()
  },
)
</script>

<template>
  <AppOverlay id="auth-overlay" :priority="150" labelledby="auth-title" @close="close">
    <form class="auth-card" novalidate @submit.prevent="onSubmit">
      <header class="auth-card__head">
        <p class="auth-card__eyebrow">身 份 验 证</p>
        <h2 id="auth-title" class="auth-card__title" data-testid="auth-title">{{ title }}</h2>
        <button
          type="button"
          class="auth-card__close"
          data-testid="auth-close"
          aria-label="关闭登录浮层"
          @click="close"
        >
          ✕
        </button>
      </header>

      <p v-if="auth.reason" class="auth-card__reason" data-testid="auth-reason">{{ auth.reason }}</p>

      <div class="auth-tabs" role="tablist" aria-label="登录或注册">
        <button
          id="auth-tab-login"
          type="button"
          class="auth-tab"
          :class="{ 'is-active': !isRegister }"
          role="tab"
          :aria-selected="!isRegister"
          data-testid="auth-tab-login"
          @click="choose('login')"
        >
          登录
        </button>
        <button
          id="auth-tab-register"
          type="button"
          class="auth-tab"
          :class="{ 'is-active': isRegister }"
          role="tab"
          :aria-selected="isRegister"
          data-testid="auth-tab-register"
          @click="choose('register')"
        >
          注册
        </button>
      </div>

      <div class="auth-fields" role="tabpanel" :aria-labelledby="'auth-tab-' + auth.tab">
        <label class="auth-field">
          <span class="auth-field__label">用户名</span>
          <input
            ref="usernameInput"
            v-model="username"
            class="auth-field__input"
            type="text"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            data-testid="auth-username"
            :disabled="auth.busy"
            @input="auth.clearError()"
          />
        </label>
        <label class="auth-field">
          <span class="auth-field__label">密码</span>
          <input
            v-model="password"
            class="auth-field__input"
            type="password"
            :autocomplete="isRegister ? 'new-password' : 'current-password'"
            data-testid="auth-password"
            :disabled="auth.busy"
            @input="auth.clearError()"
          />
        </label>

        <p class="auth-card__hint" data-testid="auth-hint">{{ hint }}</p>
        <p v-if="auth.error" class="auth-card__error" data-testid="auth-error" role="alert">
          {{ auth.error }}
        </p>
      </div>

      <footer class="auth-actions">
        <button
          type="submit"
          class="button auth-submit"
          data-testid="auth-submit"
          :disabled="auth.busy"
        >
          {{ submitLabel }}
        </button>
        <p class="auth-card__guest" data-testid="auth-guest-name">
          游客状态：{{ auth.guestName }} · 登录后保存段位与战绩
        </p>
      </footer>
    </form>
  </AppOverlay>
</template>

<style>
/* The shared AppOverlay panel is sized for full-screen screens; the auth dialog
   is a narrow card. Scoped to this overlay id so no other dialog changes. */
.app-overlay[data-overlay='auth-overlay'] .app-overlay__panel {
  width: min(460px, 100%);
  max-height: calc(100dvh - 24px);
  border: 0;
  background: transparent;
  box-shadow: none;
  overflow: visible;
}
</style>

<style scoped>
.auth-card {
  display: flex;
  flex-direction: column;
  max-height: calc(100dvh - 24px);
  overflow-y: auto;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  background: var(--surface-deck);
  box-shadow: var(--shadow-panel);
  color: var(--text-primary);
}

.auth-card__head {
  position: relative;
  display: grid;
  gap: 2px;
  padding: 18px 20px 10px;
}

.auth-card__eyebrow {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 10px;
  letter-spacing: 0.24em;
}

.auth-card__title {
  margin: 0;
  padding-right: 44px;
  font-size: 21px;
  font-weight: 700;
}

.auth-card__close {
  position: absolute;
  top: 14px;
  right: 14px;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 15px;
  cursor: pointer;
}

.auth-card__close:hover {
  border-color: var(--role-self);
  color: var(--text-primary);
  background: var(--role-self-soft);
}

.auth-card__reason {
  margin: 0 20px 8px;
  padding: 8px 10px;
  border: 1px dashed var(--role-action);
  border-radius: var(--radius-sm);
  background: var(--role-action-soft);
  color: var(--text-primary);
  font-size: 12px;
}

.auth-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  margin: 4px 20px 0;
  padding: 4px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-chamber);
}

.auth-tab {
  min-height: 40px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease), background var(--duration-fast) var(--ease);
}

.auth-tab:hover {
  color: var(--text-primary);
  background: var(--role-self-soft);
}

.auth-tab.is-active {
  border-color: var(--border-strong);
  background: var(--role-action-soft);
  color: var(--text-primary);
  font-weight: 600;
}

.auth-fields {
  display: grid;
  gap: 12px;
  padding: 16px 20px 4px;
}

.auth-field {
  display: grid;
  gap: 5px;
}

.auth-field__label {
  color: var(--text-secondary);
  font-size: 12px;
}

.auth-field__input {
  min-height: 44px;
  padding: 8px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-sea);
  color: var(--text-primary);
  font: inherit;
  font-size: 16px;
}

.auth-field__input:focus {
  border-color: var(--role-self);
  outline: 2px solid var(--role-self);
  outline-offset: 1px;
}

.auth-card__hint {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.5;
}

.auth-card__error {
  margin: 0;
  padding: 8px 10px;
  border: 1px solid var(--role-enemy);
  border-radius: var(--radius-sm);
  background: var(--role-enemy-soft);
  color: var(--text-primary);
  font-size: 13px;
}

/* The submit row sticks to the bottom of the scrolling card, so a phone
   keyboard can never hide the one action the dialog exists for. */
.auth-actions {
  position: sticky;
  bottom: 0;
  display: grid;
  gap: 8px;
  padding: 12px 20px max(14px, env(safe-area-inset-bottom));
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-deck);
}

.auth-submit {
  min-height: 46px;
  border-color: var(--role-action);
  background: var(--role-action);
  color: var(--surface-sea);
  font-weight: 700;
}

.auth-submit:hover:not(:disabled) {
  border-color: var(--role-action);
  background: var(--accent-strong);
}

.auth-card__guest {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 11px;
  text-align: center;
}

@media (max-width: 479px) {
  .auth-card__head {
    padding: 16px 16px 8px;
  }

  .auth-tabs {
    margin: 4px 16px 0;
  }

  .auth-fields {
    padding: 14px 16px 4px;
  }

  .auth-actions {
    padding: 10px 16px max(12px, env(safe-area-inset-bottom));
  }
}
</style>
