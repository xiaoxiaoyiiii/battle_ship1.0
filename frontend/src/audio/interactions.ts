import { unlockAudio } from './engine'
import { UI_SOUNDS, type UiSound } from './uiSounds'

/** 原生鼠标、触摸与键盘激活统一走 click，避免 pointerdown/keyup 重复响。 */
export function interactionSound(target: EventTarget | null): UiSound | null {
  if (!(target instanceof Element)) return null
  if (!target.closest('#app, .app-overlay, [data-testid="toast-host"]')) return null
  const control = target.closest<HTMLElement>('button, a[href], [role="button"], [role="tab"], [role="radio"], [role="switch"], input')
  if (!control || control.closest('[data-ui-sound="none"]')) return null
  if (control.matches(':disabled, [aria-disabled="true"], [aria-busy="true"]')) return null
  // 棋盘用实际选中/部署的结果发声，不能点错格子也播放成功音。
  if (control.getAttribute('role') === 'gridcell') return null
  if (control.matches('input:not([type="checkbox"]):not([type="radio"])')) return null
  const explicit = control.dataset.uiSound
  if (explicit && explicit in UI_SOUNDS) return explicit as UiSound
  if (control.matches('[role="tab"], [role="radio"], [role="switch"], input[type="checkbox"], input[type="radio"]')) return 'select'
  if (control.hasAttribute('aria-expanded')) return control.getAttribute('aria-expanded') === 'true' ? 'back' : 'press'
  const label = (control.getAttribute('aria-label') || control.textContent || '').trim()
  if (/^(返回|取消|关闭|收起|撤销|上一步|离开)/.test(label)) return 'back'
  if (control.matches('[data-primary-action], .button--primary, .home-play, .home-ai__action')) return 'confirm'
  return 'press'
}

export function installInteractionAudio(play: (sound: UiSound) => boolean, root: Document = document): () => void {
  const activate = (event: Event): void => {
    const sound = interactionSound(event.target)
    if (sound) play(sound)
  }
  const change = (event: Event): void => {
    const target = event.target
    if (!(target instanceof Element) || target.closest('[data-ui-sound="none"]')) return
    if (!target.closest('#app, .app-overlay, [data-testid="toast-host"]')) return
    if (target.matches('select:not(:disabled), input[type="range"]:not(:disabled)')) play('select')
  }
  const unlock = (): void => unlockAudio()
  root.addEventListener('click', activate, true)
  root.addEventListener('change', change, true)
  root.addEventListener('pointerdown', unlock, { capture: true, once: true })
  root.addEventListener('keydown', unlock, { capture: true, once: true })
  return () => {
    root.removeEventListener('click', activate, true)
    root.removeEventListener('change', change, true)
    root.removeEventListener('pointerdown', unlock, true)
    root.removeEventListener('keydown', unlock, true)
  }
}
