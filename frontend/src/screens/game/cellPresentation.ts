import type { BoardCell } from './view'
export type CellVisual = 'empty' | 'ship' | 'ship-hit' | 'miss' | 'shield-blocked' | 'shielded' | 'trap' | 'hole' | 'revived'
export interface CellHint { title: string; detail: string }
export interface SelectionHint { selectable?: boolean; card?: string; hint?: string }

/** 当前真实状态优先；历史挡炮标记不能覆盖后来命中或新加的护盾。 */
export function cellVisualState(cell: BoardCell): CellVisual {
  if (cell.hole) return 'hole'
  if (cell.hit || cell.sunk) return 'ship-hit'
  if (cell.revived) return 'revived'
  if (cell.shielded) return 'shielded'
  if (cell.shieldBroken) return 'shield-blocked'
  if (cell.trap) return 'trap'
  if (cell.miss) return 'miss'
  return cell.ship ? 'ship' : 'empty'
}

/** 普通舰船、命中与落空不弹提示；只解释特殊状态和当前可选目标。 */
export function cellHints(cell: BoardCell, selection: SelectionHint): CellHint[] {
  const hints: CellHint[] = []
  const visual = cellVisualState(cell)
  if (visual === 'shield-blocked') hints.push({ title: '护盾挡炮', detail: '护盾已挡下此前的攻击并被消耗；此格仍可再次受到攻击，不代表舰船已沉没。' })
  if (visual === 'shielded') hints.push({ title: '护盾保护', detail: '此格战舰仍有护盾。普通炮击命中时先消耗护盾，不直接击沉舰船。' })
  if (cell.trap && !cell.hit && !cell.sunk && !cell.hole) hints.push({ title: '守株待兔陷阱', detail: '己方战舰设有「守株待兔」陷阱，触发时按卡牌效果反制；此标记仅己方可见。' })
  if (selection.selectable) {
    const card = selection.card || '战舰'
    const suffix = ['冻结', '探测雷达', '神威！', '硫磺火焰'].includes(card) ? '区域待选择' : card === '轰炸' ? '行列待选择' : '目标待选择'
    hints.push({ title: card + suffix, detail: selection.hint || '点击此格选择当前效果的目标。' })
  }
  return hints
}
