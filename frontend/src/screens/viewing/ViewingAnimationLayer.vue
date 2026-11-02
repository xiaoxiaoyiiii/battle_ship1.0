<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { drawChainFrame } from '../game/chainAnimationCanvas'
import { planChainStage } from '../game/chainStageLayout'
import { drawCardEffect, drawCounterEffect, warmCardEffectCaches, clearCardEffectCaches } from '../game/cardEffects/canvas'
import type { CardEffectKind, EffectCell, EffectRect } from '../game/cardEffects/types'
import { chainFrame } from './presentation'
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
  if (cue.stage === 'attack_windup' || cue.stage === 'attack_tail') {
    const point = cue.cell as Json, result = cue.result as Json
    const target = points([point], String(cue.target))[0], source = board(String(cue.attacker))
    if (!target || !source) return
    const x = target.cx, y = target.cy, radius = Math.max(10, target.w * .6)
    const color = result.shield_blocked ? '#f0c36d' : result.hit ? '#ff8a91' : '#83dcea'
    ctx.strokeStyle = color; ctx.fillStyle = color
    if (cue.stage === 'attack_windup') {
      const fromX = source.x + source.w / 2, fromY = source.y + source.h / 2
      ctx.globalAlpha = .8; ctx.lineWidth = 2
      ctx.beginPath(); ctx.moveTo(fromX, fromY); ctx.lineTo(fromX + (x - fromX) * progress, fromY + (y - fromY) * progress); ctx.stroke()
    } else {
      ctx.globalAlpha = 1 - progress; ctx.lineWidth = 2.5
      ctx.beginPath(); ctx.arc(x, y, radius * (.5 + progress), 0, Math.PI * 2); ctx.stroke()
      ctx.font = '600 14px "Microsoft YaHei",sans-serif'; ctx.textAlign = 'center'
      ctx.fillText(result.shield_blocked ? '护盾挡下' : result.invincible ? '无敌保护' : result.sunk ? '击沉' : result.hit ? '命中' : '未命中', x, y - radius - 8)
    }
    return
  }
  const effect = cue.effect as Json | undefined
  if (effect) {
    const one = board('p1'), two = board('p2'); if (!one || !two) return
    const side = String(effect.target), target = side === 'p1' ? one : two
    const union = { x: Math.min(one.x, two.x), y: Math.min(one.y, two.y), w: Math.max(one.x + one.w, two.x + two.w) - Math.min(one.x, two.x), h: Math.max(one.y + one.h, two.y + two.h) - Math.min(one.y, two.y) }
    const impact = Number(effect.impact) || .45, tail = cue.stage === 'effect_tail', success = cue.success !== false
    const p = tail ? success ? impact + (1 - impact) * progress : impact * (1 - progress) : impact * progress
    const origin = points([effect.origin].filter(Boolean), side)[0]
    if (effect.kind === 'negate' || effect.kind === 'gabriel') drawCounterEffect(ctx, effect.kind, p, target)
    else drawCardEffect(ctx, { kind: effect.kind as CardEffectKind, progress: p, privateTargets: Array.isArray(effect._private_cells) },
      { sourceBoard: effect.caster === 'p1' ? one : two, targetBoard: target, boardsUnion: union,
        cells: points(effect.cells, side), privateCells: points(effect._private_cells, side), origin: origin ? [origin.cx, origin.cy] : undefined })
    return
  }
  const frame = chainFrame(cue, progress)
  if (!frame) return
  drawChainFrame(ctx, frame, planChainStage({ width, height, count: frame.cue.cards.length, insets: { top: 0, right: 0, bottom: 0, left: 0 } }), image)
}
watch(() => [props.cue, props.progress], () => void nextTick(draw), { flush: 'post' })
onMounted(warmCardEffectCaches)
onBeforeUnmount(() => { clearCardEffectCaches(); art.clear() })
</script>
<template><Teleport to="body"><div v-if="cue" class="view-animation" data-testid="viewing-animation" :data-stage="cue.stage" :data-order="cue.order" :data-negated="cue.negated_skip === true" aria-hidden="true"><canvas ref="canvas"></canvas></div></Teleport></template>
