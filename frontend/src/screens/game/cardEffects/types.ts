/** 所有坐标均为 Canvas 的 CSS 像素坐标，调用端负责处理设备像素比。 */
export interface EffectRect { x: number; y: number; w: number; h: number }
export interface EffectCell extends EffectRect { cx: number; cy: number; gx?: number; gy?: number }
export type EffectPoint = readonly [number, number]
export type CardEffectKind = 'bomb' | 'vortex' | 'ice' | 'fire' | 'splash' | 'negate' | 'seal' | 'gabriel' | 'revive' | 'heal' | 'last_chance' | 'shield' | 'sanctuary'
export type RecoveryEffectKind = Extract<CardEffectKind, 'revive' | 'heal' | 'last_chance' | 'shield' | 'sanctuary'>
export interface CardEffectFrame {
  kind: CardEffectKind
  /** 从主体动效开始计时，0 到 1；卡面退场由调用端先完成。 */
  progress: number
  seed?: number
  /** 仅施法者可为 true。没有授权时恢复类忽略所有精确落点。 */
  privateTargets?: boolean
}
export interface CardEffectGeometry {
  sourceBoard?: EffectRect
  targetBoard: EffectRect
  /** 无暇圣心必须传双方棋盘的并集。 */
  boardsUnion?: EffectRect
  /** 仅包含本来就公开的施法选择区域，不含隐藏船位。 */
  cells?: readonly EffectCell[]
  /** 来自当前观看者私有视图，且仅在 privateTargets 为 true 时使用。 */
  privateCells?: readonly EffectCell[]
  /** 已公开的效果起点；溅射在边角处不能用四邻格的均值代替命中中心。 */
  origin?: EffectPoint
  avatar?: EffectRect
}
