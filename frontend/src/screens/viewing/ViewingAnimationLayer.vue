<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { drawChainFrame } from '../game/chainAnimationCanvas'
import { planChainStage } from '../game/chainStageLayout'
import { drawCardEffect, drawCounterEffect, warmCardEffectCaches, clearCardEffectCaches } from '../game/cardEffects/canvas'
import type { CardEffectKind, EffectCell, EffectRect } from '../game/cardEffects/types'
import type { ChainFrame } from '../game/chainAnimation'
import { cardArtUrl } from '../../cards/cardArt'
import type { Json } from './types'

const props = defineProps<{ cue: Json | null; progress: number }>()
const canvas = ref<HTMLCanvasElement | null>(null), art = new Map<string, HTMLImageElement>()
function image(name: string): HTMLImageElement | null {
  let img = art.get(name)
  if (!img) { const url = cardArtUrl(name); if (!url) return null; img = new Image(); img.src = url; art.set(name, img) }
  return img.complete && img.naturalWidth ? img : null
}
function rect(selector: string): EffectRect | null {
  const r = document.querySelector(selector)?.getBoundingClientRect()
  return r && r.width && r.height ? { x: r.x, y: r.y, w: r.width, h: r.height } : null
}
function board(side: string): EffectRect | null { return rect(`.view-battle [data-owner="${side}"] .board__grid`) }
function points(values: unknown, side: string): EffectCell[] {
  if (!Array.isArray(values)) return []
  return values.flatMap(p => {
    const r = rect(`.view-battle [data-owner="${side}"] [data-x="${p.x}"][data-y="${p.y}"]`)
    return r ? [{ ...r, cx: r.x + r.w / 2, cy: r.y + r.h / 2, gx: p.x, gy: p.y }] : []
  })
}
function draw(): void {
  const c = canvas.value, cue = props.cue
  if (!c || !cue) return
  const ratio = Math.min(2, devicePixelRatio || 1), width = innerWidth, height = innerHeight
  c.width = width * ratio; c.height = height * ratio
  const ctx = c.getContext('2d'); if (!ctx) return
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
  const progress = props.progress
  const effect = cue.effect as Json | undefined
  if (effect) {
    const one = board('p1'), two = board('p2'); if (!one || !two) return
    const side = String(effect.target), target = side === 'p1' ? one : two
    const union = { x: Math.min(one.x, two.x), y: Math.min(one.y, two.y), w: Math.max(one.x + one.w, two.x + two.w) - Math.min(one.x, two.x), h: Math.max(one.y + one.h, two.y + two.h) - Math.min(one.y, two.y) }
    const impact = Number(effect.impact) || .45, tail = cue.stage === 'effect_tail', success = cue.success !== false
    const p = tail ? success ? impact + (1 - impact) * progress : impact * (1 - progress) : impact * progress
    if (effect.kind === 'negate' || effect.kind === 'gabriel') drawCounterEffect(ctx, effect.kind, p, target)
    else drawCardEffect(ctx, { kind: effect.kind as CardEffectKind, progress: p, privateTargets: Array.isArray(effect._private_cells) },
      { sourceBoard: effect.caster === 'p1' ? one : two, targetBoard: target, boardsUnion: union,
        cells: points(effect.cells, side), privateCells: points(effect._private_cells, side) })
    return
  }
  const source = Array.isArray(cue.chain) ? cue.chain as Json[] : []
  const cards = source.map((row, i) => ({ name: typeof row.card === 'string' ? row.card : String((row.card as Json)?.name ?? ''), caster: String(row.seat ?? ''), order: i + 1, id: '' }))
  if (!cards.length) return
  const frame: ChainFrame = { progress, cue: { kind: cue.stage === 'join' ? 'join' : 'resolve', cards, order: Number(cue.order) || cards.length,
    result: { negated: cue.negated_skip === true, failed: cue.success === false }, start: 0, duration: 1 } }
  drawChainFrame(ctx, frame, planChainStage({ width, height, count: cards.length, insets: { top: 0, right: 0, bottom: 0, left: 0 } }), image)
}
watch(() => [props.cue, props.progress], () => void nextTick(draw), { flush: 'post' })
onMounted(warmCardEffectCaches)
onBeforeUnmount(() => { clearCardEffectCaches(); art.clear() })
</script>
<template><Teleport to="body"><div v-if="cue" class="view-animation" data-testid="viewing-animation" :data-stage="cue.stage" aria-hidden="true"><canvas ref="canvas"></canvas></div></Teleport></template>
