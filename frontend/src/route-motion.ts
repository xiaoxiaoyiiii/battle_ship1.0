import { nextTick } from 'vue'
import type { Router } from 'vue-router'

// 用画面快照过渡，避免两份对局组件同时挂载，也不改变浮窗的定位容器。
export function installRouteMotion(router: Router): void {
  const flow = ['placement', 'rps', 'game', 'game-over']
  let active: ViewTransition | undefined
  router.beforeResolve((to, from) => {
    active?.skipTransition()
    if (!from.name || to.path === from.path || !document.startViewTransition ||
        matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const a = flow.indexOf(String(from.name)), b = flow.indexOf(String(to.name))
    document.documentElement.dataset.routeMotion = a >= 0 && b >= 0 ? (b > a ? 'forward' : 'back') : 'fade'
    return new Promise<boolean>((allow) => {
      let release: (() => void) | undefined
      const rendered = new Promise<void>((resolve) => { release = resolve })
      const stop = router.afterEach(async () => { stop(); await nextTick(); release?.() })
      active = document.startViewTransition(() => { allow(true); return rendered })
      // 快速导航取消过渡时仍然允许导航，错误不变成未处理的拒绝。
      void active.ready.catch(() => {})
      void active.finished.catch(() => {}).finally(() => { stop(); release?.(); allow(true) })
    })
  })
}
