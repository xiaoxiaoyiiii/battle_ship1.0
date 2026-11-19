<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { drawChainFrame } from '../game/chainAnimationCanvas'
import { planChainStage } from '../game/chainStageLayout'
import { drawCardEffect, drawCounterEffect, warmCardEffectCaches, clearCardEffectCaches } from '../game/cardEffects/canvas'
import type { CardEffectKind, EffectCell, EffectRect } from '../game/cardEffects/types'
import { chainFrame, commanderPresentation } from './presentation'
import { resolveCardArtUrl } from '../../cards/skinArt'
import { createChainSkinFaces } from '../game/chainSkinFaces'
import type { Json } from './types'

const props = withDefaults(defineProps<{ cue: Json | null; progress: number; context?: 'spectate' | 'replay' }>(), { context: 'spectate' })
const canvas = ref<HTMLCanvasElement | null>(null), art = new Map<string, HTMLImageElement>()
const commander = computed(() => commanderPresentation(props.cue))
function image(name: string, skinId?: string | null): HTMLImageElement | null {
  const key = name + '::' + (skinId || 'default')
  let img = art.get(key)
  if (!img) { const url = resolveCardArtUrl(name, skinId); if (!url) return null; img = new Image(); img.src = url; art.set(key, img) }
  return img.complete && img.naturalWidth ? img : null
}
// 公开连锁牌的动态皮肤（只认 cue 里的 skin_id）。播放进度驱动重绘；暂停时由皮肤时钟合并请求一次重绘。
let pendingDraw = 0
function requestDraw(): void {
  if (pendingDraw || typeof requestAnimationFrame === 'undefined') return
  pendingDraw = requestAnimationFrame(() => { pendingDraw = 0; draw() })
}
function redrawViewport(): void {
  if (props.cue) requestDraw()
}
const skinFaces = createChainSkinFaces(props.context, requestDraw)
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
function paintCommander(ctx: CanvasRenderingContext2D, cast: NonNullable<typeof commander.value>, progress: number): void {
  const region = board(cast.board)
  if (!region) return
  const { x, y, w, h } = region
  const canceled = cast.stage === 'negated' || cast.failed
  const intensity = Math.min(1, .24 + progress * 5, (1 - progress) * 4)
  const color = canceled ? '#fa9199' : cast.skill.accent
  const size = Math.min(w, h)
  ctx.save()
  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.shadowColor = color
  ctx.shadowBlur = 10
  ctx.lineWidth = 2
  ctx.globalAlpha = intensity * .9
  ctx.beginPath()
  ctx.roundRect(x - 2, y - 2, w + 4, h + 4, 7)
  ctx.stroke()
  ctx.clip()
  ctx.globalAlpha = intensity * .065
  ctx.fillRect(x, y, w, h)
  ctx.globalAlpha = intensity * .8
  const cx = x + w / 2, cy = y + h / 2
  ctx.beginPath()
  if (canceled) {
    const reach = size * .10
    ctx.moveTo(cx - reach, cy - reach); ctx.lineTo(cx + reach, cy + reach)
    ctx.moveTo(cx + reach, cy - reach); ctx.lineTo(cx - reach, cy + reach)
  } else if (cast.skill.id === 'firepower_control') {
    const offset = progress * w * .5
    for (let i = 0; i < 3; i++) {
      ctx.moveTo(x - w * .5 + offset, y + h * (.45 + .14 * i))
      ctx.lineTo(x + w * .6 + offset, y + h * (.22 + .14 * i))
    }
  } else if (cast.skill.id === 'dauntless_fleet') {
    const reach = size * .19 * (1 + progress * .3)
    const gap = reach * .42
    ctx.moveTo(cx - gap, cy - reach); ctx.lineTo(cx - reach, cy - reach * .55)
    ctx.lineTo(cx - reach, cy + reach * .32); ctx.lineTo(cx - gap, cy + reach)
    ctx.moveTo(cx + gap, cy - reach); ctx.lineTo(cx + reach, cy - reach * .55)
    ctx.lineTo(cx + reach, cy + reach * .32); ctx.lineTo(cx + gap, cy + reach)
  } else if (cast.skill.id === 'sacrifice_gambit') {
    const cardWidth = size * .14, cardHeight = size * .22
    const spread = size * (.035 + progress * .06)
    for (const direction of [-1, 1]) {
      ctx.save()
      ctx.translate(cx + direction * spread, cy - direction * cardHeight * .14)
      ctx.rotate(direction * .24)
      ctx.roundRect(-cardWidth / 2, -cardHeight / 2, cardWidth, cardHeight, 3)
      ctx.restore()
    }
  } else {
    const radius = size * (.08 + progress * .39)
    ctx.arc(cx, cy, radius, 0, Math.PI * 2)
    ctx.moveTo(cx + radius * .66, cy)
    ctx.arc(cx, cy, radius * .66, 0, Math.PI * 2)
  }
  ctx.stroke()
  for (const cell of points(cast.cells, cast.board)) {
    const inset = Math.max(2, cell.w * .1)
    ctx.strokeRect(cell.x + inset, cell.y + inset, cell.w - 2 * inset, cell.h - 2 * inset)
  }
  ctx.restore()
}
function draw(): void {
  const c = canvas.value, cue = props.cue
  if (!c || !cue) { skinFaces.clear(); return }
  skinFaces.beginFrame()
  try { paint(c, cue) } finally { skinFaces.endFrame() }
}
function paint(c: HTMLCanvasElement, cue: Json): void {
  const ratio = Math.min(2, devicePixelRatio || 1), width = innerWidth, height = innerHeight
  c.width = width * ratio; c.height = height * ratio
  const ctx = c.getContext('2d'); if (!ctx) return
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
  const progress = props.progress
  if (commander.value) {
    paintCommander(ctx, commander.value, progress)
    return
  }
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
  drawChainFrame(ctx, frame, planChainStage({ width, height, count: frame.cue.cards.length, insets: { top: 0, right: 0, bottom: 0, left: 0 } }), image, skinFaces.lookup)
}
watch(() => [props.cue, props.progress], () => void nextTick(draw), { flush: 'post' })
onMounted(() => {
  warmCardEffectCaches()
  redrawViewport()
  window.addEventListener('resize', redrawViewport)
  window.addEventListener('scroll', redrawViewport, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', redrawViewport)
  window.removeEventListener('scroll', redrawViewport, true)
  clearCardEffectCaches(); art.clear(); skinFaces.dispose()
  if (pendingDraw) cancelAnimationFrame(pendingDraw)
})
</script>
<template>
  <Teleport to="body">
    <div v-if="cue" class="view-animation" data-testid="viewing-animation" :data-stage="cue.stage"
      :data-order="cue.order" :data-negated="cue.negated_skip === true || commander?.stage === 'negated'" aria-hidden="true">
      <canvas ref="canvas" :data-testid="commander ? 'viewing-commander-effect' : undefined"
        :data-board="commander?.board" :data-skill-stage="commander?.stage"></canvas>
    </div>
  </Teleport>
</template>
