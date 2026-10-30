/** 界面反馈与战斗声音共用总音量；语义名称不依赖按钮文案。 */
export const UI_SOUNDS = {
  press: 'ui_press', select: 'ui_select', back: 'ui_back', confirm: 'ui_confirm',
  reject: 'ui_reject', place: 'ui_place', remove: 'ui_remove', ready: 'ui_ready',
  match: 'ui_match', countdown: 'ui_countdown',
} as const

export type UiSound = keyof typeof UI_SOUNDS

/** 高频选格轻且短，拒绝/完成提示采用更长的去重窗口。 */
export const UI_SOUND_COOLDOWN: Record<UiSound, number> = {
  press: 65, select: 55, back: 100, confirm: 100, reject: 240,
  place: 55, remove: 55, ready: 250, match: 1000, countdown: 300,
}
