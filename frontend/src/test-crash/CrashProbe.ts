import { defineComponent } from 'vue'

/**
 * Test-build-only crash injector: rendering it throws, which the screen
 * boundary must absorb. `import.meta`-style gating lives in App.vue so the
 * whole module is tree-shaken from production builds (the gate asserts the
 * name below is absent from dist/assets/*.js).
 */
export const CrashProbe = defineComponent({
  name: 'bs-test-crash',
  render() {
    throw new Error('injected per-screen crash (test build only)')
  },
})
