import { CHAIN_FLIGHT_MS, CHAIN_ENTRY_MS, type ChainArtCard, type ChainFrame } from './chainAnimation'
import { drawCounterEffect } from './cardEffects/canvas'
import type { ChainStageCard, ChainStagePlan } from './chainStageLayout'
import { masteryTier } from '../collection/model'

type ArtLookup = (name: string) => HTMLImageElement | null
const clamp = (n: number): number => Math.max(0, Math.min(1, n))
const ease = (n: number): number => 1 - (1 - clamp(n)) ** 3
const mix = (a: number, b: number, p: number): number => a + (b - a) * p

function number(ctx: CanvasRenderingContext2D, order: number, x: number, y: number, size: number): void {
  ctx.save(); ctx.font = `italic 700 ${size}px Georgia`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.shadowColor = '#030810'; ctx.shadowBlur = 12; ctx.lineWidth = 3; ctx.strokeStyle = '#3d3522'
  ctx.strokeText(String(order), x, y)
  const gold = ctx.createLinearGradient(0, y - size / 2, 0, y + size / 2)
  gold.addColorStop(0, '#fff5d5'); gold.addColorStop(.45, '#d1b576'); gold.addColorStop(.6, '#fff4bd'); gold.addColorStop(1, '#aa8542')
  ctx.fillStyle = gold; ctx.fillText(String(order), x, y); ctx.restore()
}

function chain(ctx: CanvasRenderingContext2D, x: number, y: number, endX: number, endY: number, scale = 1, progress = 1): void {
  const length = Math.hypot(endX - x, endY - y)
  ctx.save(); ctx.translate(x, y); ctx.rotate(Math.atan2(endY - y, endX - x))
  const step = 17 * Math.max(.6, scale)
  for (let i = 0; i < Math.floor(length / step) * clamp(progress); i++) {
    ctx.save(); ctx.translate(i * step, 0); ctx.rotate(i % 2 ? -.12 : .12)
    ctx.beginPath(); ctx.ellipse(0, 0, 14 * scale, i % 2 ? 3.5 * scale : 7.5 * scale, 0, 0, Math.PI * 2)
    ctx.shadowColor = '#000'; ctx.shadowBlur = 4; ctx.strokeStyle = '#304858'; ctx.lineWidth = 7 * scale; ctx.stroke()
    ctx.shadowBlur = 0; ctx.strokeStyle = i % 2 ? '#88a5b9' : '#d1e5ed'; ctx.lineWidth = 4 * scale; ctx.stroke()
    ctx.strokeStyle = '#f7ffffaa'; ctx.lineWidth = 1; ctx.stroke(); ctx.restore()
  }
  ctx.restore()
}

function card(ctx: CanvasRenderingContext2D, item: ChainArtCard, art: ArtLookup, x: number, y: number, width: number, angle = 0, grey = false): void {
  const height = width * 1.5
  const radius = Math.max(5, width * 0.05)
  ctx.save(); ctx.translate(x, y); ctx.rotate(angle)
  const tier = masteryTier(item.masteryTier)
  if (tier) {
    const colors = ['','#6de0ec','#ba96ff','#f3c467','#9beff7']
    ctx.save(); ctx.shadowColor=colors[tier]; ctx.shadowBlur=12+tier*8
    ctx.strokeStyle=colors[tier]; ctx.lineWidth=1+tier
    if (tier===4) {
      const rainbow=ctx.createLinearGradient(-width/2,-height/2,width/2,height/2)
      ;['#72e5e7','#bb98ff','#f6ce7a','#89f0df'].forEach((c,i)=>rainbow.addColorStop(i/3,c))
      ctx.strokeStyle=rainbow
    }
    ctx.beginPath();ctx.roundRect(-width/2-6,-height/2-6,width+12,height+12,radius+4);ctx.stroke()
    if (tier>=2) {ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(-width/2-10,-height/2-10,width+20,height+20,radius+6);ctx.stroke()}
    if (tier>=3) {
      ctx.fillStyle=colors[tier]
      for (const sx of [-1,1]) for (const sy of [-1,1]) {
        const px=sx*(width/2+8),py=sy*(height/2+8)
        ctx.beginPath();ctx.moveTo(px,py-6);ctx.lineTo(px+3,py);ctx.lineTo(px,py+6);ctx.lineTo(px-3,py);ctx.closePath();ctx.fill()
      }
    }
    ctx.restore()
  }
  ctx.shadowColor = '#82c9e877'; ctx.shadowBlur = 19; ctx.fillStyle = '#122033'
  ctx.beginPath(); ctx.roundRect(-width / 2 - 3, -height / 2 - 3, width + 6, height + 6, radius + 2); ctx.fill(); ctx.shadowBlur = 0
  ctx.save(); ctx.beginPath(); ctx.roundRect(-width / 2, -height / 2, width, height, radius); ctx.clip()
  const image = art(item.name)
  if (image?.complete && image.naturalWidth) {
    if (grey) ctx.filter = 'grayscale(1) brightness(.65)'
    ctx.drawImage(image, -width / 2, -height / 2, width, height)
  } else {
    ctx.fillStyle = '#142b3e'; ctx.fillRect(-width / 2, -height / 2, width, height)
    ctx.fillStyle = '#f2dda2'; ctx.textAlign = 'center'; ctx.font = `700 ${Math.max(12, width / 10)}px "Microsoft YaHei",sans-serif`
    ctx.fillText(item.name, 0, 0, width - 14)
  }
  ctx.restore(); ctx.strokeStyle = grey ? '#8b8790' : '#f0cf83'; ctx.lineWidth = 1.3
  ctx.beginPath(); ctx.roundRect(-width / 2 - 2, -height / 2 - 2, width + 4, height + 4, radius + 1); ctx.stroke(); ctx.restore()
}

function success(ctx: CanvasRenderingContext2D, x: number, y: number, progress: number, fontSize: number): void {
  ctx.save(); ctx.globalAlpha *= Math.min(1, progress * 6, (1 - progress) * 5)
  ctx.translate(x, y); ctx.transform(1, 0, -.1, 1, 0, 0)
  const zoom = mix(1.1, 1, ease(progress * 3)); ctx.scale(zoom, zoom)
  ctx.font = `italic 800 ${fontSize}px Arial`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.lineJoin = 'round'; ctx.lineWidth = 4; ctx.strokeStyle = '#183149'; ctx.shadowColor = '#83eaff'; ctx.shadowBlur = 22
  ctx.strokeText('Successful Chain', 0, 0)
  const silver = ctx.createLinearGradient(0, -fontSize * .6, 0, fontSize * .6)
  silver.addColorStop(0, '#fff'); silver.addColorStop(.42, '#f3fdff'); silver.addColorStop(.54, '#88b9cf'); silver.addColorStop(.64, '#e9fbff'); silver.addColorStop(1, '#8bd8ee')
  ctx.fillStyle = silver; ctx.fillText('Successful Chain', 0, 0); ctx.restore()
}

/** 把一张卡从入场起点飞到构图落点。 */
function placed(pos: ChainStageCard, item: ChainArtCard, plan: ChainStagePlan, flight: number): { x: number; y: number; angle: number } {
  const from = item.caster === 'p2' ? plan.entry.p2 : plan.entry.p1
  return {
    x: mix(from.x, pos.x, flight),
    y: mix(from.y, pos.y, flight),
    angle: mix(from.angle, pos.angle, flight),
  }
}

/** 绘制通用连锁演出，绝不在棋盘上模拟某张卡的攻击或冻结效果。 */
export function drawChainFrame(ctx: CanvasRenderingContext2D, frame: ChainFrame, plan: ChainStagePlan, art: ArtLookup): void {
  const { cue, progress } = frame
  const fade = Math.min(1, progress * 12, (1 - progress) * 9)
  const scale = Math.max(.55, plan.scale)
  ctx.clearRect(0, 0, plan.width, plan.height)
  ctx.save(); ctx.fillStyle = `rgba(3,9,18,${.57 * fade})`; ctx.fillRect(0, 0, plan.width, plan.height); ctx.globalAlpha = fade

  const current = plan.current
  if (cue.kind === 'resolve') {
    const active = cue.cards.find(item => item.order === cue.order)
    const neighbours = cue.cards.filter(item => Math.abs(item.order - cue.order) === 1)
    if (active) {
      // 相邻卡压暗排两侧，保持「这一张正在结算」的视觉焦点。
      neighbours.forEach((item, index) => {
        const companion = plan.companions[index] ?? plan.companions[0]
        if (!companion) return
        ctx.save(); ctx.globalAlpha *= .25
        card(ctx, item, art, companion.x, companion.y, companion.w)
        ctx.restore()
      })
      const counter = cue.result?.negatedBy === '失灵！' ? 'negate' : cue.result?.negatedBy === '加百列之光' ? 'gabriel' : null
      const grey = Boolean(cue.result?.failed || (cue.result?.negated && (!counter || progress >= (counter === 'gabriel' ? .50 : .33))))
      card(ctx, active, art, current.x, current.y, current.w, current.angle, grey)
      number(ctx, active.order, plan.number.x, plan.number.y, plan.number.size)
      if (grey) {
        const w = current.w * .58
        ctx.save(); ctx.translate(current.x, current.y); ctx.rotate(-.12)
        ctx.fillStyle = '#421d2ae8'; ctx.fillRect(-w, -current.w * .13, w * 2, current.w * .26)
        ctx.strokeStyle = '#f1a4a9'; ctx.lineWidth = 1; ctx.strokeRect(-w, -current.w * .13, w * 2, current.w * .26)
        ctx.fillStyle = '#ffdad6'; ctx.font = `700 ${Math.max(16, current.w * .15)}px "Microsoft YaHei",sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
        ctx.fillText(cue.result?.negated ? '无 效' : '未生效', 0, 0); ctx.restore()
      } else {
        ctx.save(); ctx.globalAlpha *= .5 * Math.sin(progress * Math.PI)
        const radius = current.w * 1.05
        const light = ctx.createRadialGradient(current.x, current.y, current.w * .3, current.x, current.y, radius)
        light.addColorStop(0, '#d6c78655'); light.addColorStop(1, 'transparent'); ctx.fillStyle = light
        ctx.fillRect(current.x - radius, current.y - radius, radius * 2, radius * 2); ctx.restore()
      }
      if (cue.result?.negated && counter) {
        drawCounterEffect(ctx, counter, progress, {
          x: current.x - current.w / 2,
          y: current.y - current.w * .75,
          w: current.w,
          h: current.w * 1.5,
        })
      }
    }
  } else {
    // 入链/成功：陪衬卡沿「斜向（竖屏）或横向（横屏）」排开，当前卡最后落位。
    const positions: Array<{ pos: ChainStageCard; item: ChainArtCard }> = []
    cue.cards.slice(-(1 + plan.companions.length)).forEach((item, index, list) => {
      const isLast = index === list.length - 1
      const slot = isLast ? current : plan.companions[index]
      if (slot) positions.push({ pos: slot, item })
    })
    for (let i = 1; i < positions.length; i += 1) {
      const prev = positions[i - 1].pos
      const next = positions[i].pos
      chain(ctx, prev.x + prev.w * .26, prev.y + prev.w * .5, next.x - next.w * .26, next.y - next.w * .5, scale)
    }
    for (const { pos, item } of positions) {
      const incoming = cue.kind === 'join' && item.order === cue.order
      const flight = incoming ? ease(progress * CHAIN_ENTRY_MS / CHAIN_FLIGHT_MS) : 1
      const at = placed(pos, item, plan, flight)
      card(ctx, item, art, at.x, at.y, pos.w, at.angle)
      if (flight > .96) {
        chain(ctx, pos.x - pos.w * .2, pos.y - pos.w * .78, pos.x - pos.w * .56, pos.y - pos.w * .40, scale)
        chain(ctx, pos.x + pos.w * .20, pos.y + pos.w * .78, pos.x + pos.w * .56, pos.y + pos.w * .41, scale)
        number(ctx, item.order, pos.x + pos.w * .5, pos.y + pos.w * .63, Math.max(20, pos.w * .34))
      }
    }
    if (cue.kind === 'success') success(ctx, plan.title.x, plan.title.y, progress, Math.max(22, plan.title.size))
  }
  ctx.restore()
}
