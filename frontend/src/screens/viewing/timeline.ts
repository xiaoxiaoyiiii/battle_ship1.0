import type { Recording } from './types'
export type TimelineNode = Recording['nodes'][number]

/** 关键节点等距排列；节点之间的拖动仍能定位每个真实步骤。 */
export function timelineNodes(source: readonly TimelineNode[], count: number): TimelineNode[] {
  if (count < 1) return []
  const grouped = new Map<number, TimelineNode>()
  grouped.set(0, { step: 0, kind: 'start', label: '对局开始' })
  for (const node of source) {
    if (!Number.isInteger(node.step) || node.step < 0 || node.step >= count) continue
    const known = grouped.get(node.step)
    grouped.set(node.step, { ...node, label: known ? known.label + ' · ' + node.label : node.label })
  }
  if (count > 1) {
    const last = grouped.get(count - 1)
    grouped.set(count - 1, { step: count - 1, kind: 'end', label: last?.label ?? '录像结束' })
  }
  return [...grouped.values()].sort((a, b) => a.step - b.step)
}

export function positionAt(step: number, nodes: readonly TimelineNode[]): number {
  if (nodes.length < 2) return 0
  const index = nodes.findIndex(node => node.step >= step)
  if (index < 0) return 1000
  if (index === 0) return 0
  const previous = nodes[index - 1], next = nodes[index]
  return (index - 1 + (step - previous.step) / (next.step - previous.step)) * 1000 / (nodes.length - 1)
}

export function stepAt(position: number, nodes: readonly TimelineNode[]): number {
  if (nodes.length < 2) return nodes[0]?.step ?? 0
  const value = Math.max(0, Math.min(1000, position)) / 1000 * (nodes.length - 1)
  const index = Math.min(nodes.length - 2, Math.floor(value))
  return Math.round(nodes[index].step + (nodes[index + 1].step - nodes[index].step) * (value - index))
}
