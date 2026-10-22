import './styles/tokens.css'
import './styles/base.css'
// Loaded last so it wins over base.css at equal specificity (shell, buttons,
// toasts, overlay chrome).
import './styles/main-ui.css'
import { createApp, type Component } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { createTestRoot, installTestHooks } from './test-hooks'
import { applyStoredTheme, useUiStore } from './stores/ui'

// Apply the persisted theme before the first paint so a switch never flashes
// the default palette on reload.
applyStoredTheme()

const app = createApp((__BS_TEST_HOOKS__ ? createTestRoot(App as Component) : App) as Component)
const pinia = createPinia()

app.use(pinia)
app.use(router)

app.config.errorHandler = (error, _instance, info) => {
  // Last resort: log without tearing the page down. Screen-local failures are
  // already contained by ScreenBoundary.
  console.error('[app] unhandled error', info, error)
}

// A route switch closes every overlay: nothing is left stacked on the next
// screen (spec story 21, ticket #42).
const ui = useUiStore(pinia)
router.afterEach(() => {
  ui.closeAllDialogs()
  ui.cancelExit()
})

// Compile-time constant: the call (and the test-hook module) disappears from
// production bundles.
if (__BS_TEST_HOOKS__) {
  installTestHooks(router, pinia)
}

app.mount('#app')
