import { CHAIN_FLIGHT_MS, CHAIN_ENTRY_MS, type ChainArtCard, type ChainFrame } from './chainAnimation'
import { drawCounterEffect } from './cardEffects/canvas'

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

function chain(ctx: CanvasRenderingContext2D, x: number, y: number, endX: number, endY: number, progress = 1): void {
  const length = Math.hypot(endX - x, endY - y)
  ctx.save(); ctx.translate(x, y); ctx.rotate(Math.atan2(endY - y, endX - x))
  for (let i = 0; i < Math.floor(length / 17) * clamp(progress); i++) {
    ctx.save(); ctx.translate(i * 17, 0); ctx.rotate(i % 2 ? -.12 : .12)
    ctx.beginPath(); ctx.ellipse(0, 0, 14, i % 2 ? 3.5 : 7.5, 0, 0, Math.PI * 2)
    ctx.shadowColor = '#000'; ctx.shadowBlur = 4; ctx.strokeStyle = '#304858'; ctx.lineWidth = 7; ctx.stroke()
    ctx.shadowBlur = 0; ctx.strokeStyle = i % 2 ? '#88a5b9' : '#d1e5ed'; ctx.lineWidth = 4; ctx.stroke()
    ctx.strokeStyle = '#f7ffffaa'; ctx.lineWidth = 1; ctx.stroke(); ctx.restore()
  }
  ctx.restore()
}

function card(ctx: CanvasRenderingContext2D, item: ChainArtCard, art: ArtLookup, x: number, y: number, width: number, angle = 0, grey = false): void {
  const height = width * 1.5
  ctx.save(); ctx.translate(x, y); ctx.rotate(angle)
  ctx.shadowColor = '#82c9e877'; ctx.shadowBlur = 19; ctx.fillStyle = '#122033'
  ctx.beginPath(); ctx.roundRect(-width / 2 - 3, -height / 2 - 3, width + 6, height + 6, 9); ctx.fill(); ctx.shadowBlur = 0
  ctx.save(); ctx.beginPath(); ctx.roundRect(-width / 2, -height / 2, width, height, 7); ctx.clip()
  const image = art(item.name)
  if (image?.complete && image.naturalWidth) {
    if (grey) ctx.filter = 'grayscale(1) brightness(.65)'
    ctx.drawImage(image, -width / 2, -height / 2, width, height)
  } else {
    ctx.fillStyle = '#142b3e'; ctx.fillRect(-width / 2, -height / 2, width, height)
    ctx.fillStyle = '#f2dda2'; ctx.textAlign = 'center'; ctx.font = `700 ${Math.max(14, width / 10)}px "Microsoft YaHei",sans-serif`
    ctx.fillText(item.name, 0, 0, width - 14)
  }
  ctx.restore(); ctx.strokeStyle = grey ? '#8b8790' : '#f0cf83'; ctx.lineWidth = 1.3
  ctx.beginPath(); ctx.roundRect(-width / 2 - 2, -height / 2 - 2, width + 4, height + 4, 8); ctx.stroke(); ctx.restore()
}

function success(ctx: CanvasRenderingContext2D, x: number, y: number, progress: number, compact: boolean): void {
  ctx.save(); ctx.globalAlpha *= Math.min(1, progress * 6, (1 - progress) * 5)
  ctx.translate(x, y); ctx.transform(1, 0, -.1, 1, 0, 0)
  const zoom = mix(1.1, 1, ease(progress * 3)); ctx.scale(zoom, zoom)
  ctx.font = `italic 800 ${compact ? 53 : 70}px Arial`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.lineJoin = 'round'; ctx.lineWidth = 4; ctx.strokeStyle = '#183149'; ctx.shadowColor = '#83eaff'; ctx.shadowBlur = 22
  ctx.strokeText('Successful Chain', 0, 0)
  const silver = ctx.createLinearGradient(0, -40, 0, 40)
  silver.addColorStop(0, '#fff'); silver.addColorStop(.42, '#f3fdff'); silver.addColorStop(.54, '#88b9cf'); silver.addColorStop(.64, '#e9fbff'); silver.addColorStop(1, '#8bd8ee')
  ctx.fillStyle = silver; ctx.fillText('Successful Chain', 0, 0); ctx.restore()
}

/** 绘制通用连锁演出，绝不在棋盘上模拟某张卡的攻击或冻结效果。 */
export function drawChainFrame(ctx: CanvasRenderingContext2D, frame: ChainFrame, width: number, height: number, art: ArtLookup): void {
  const { cue, progress } = frame
  const compact = width < 600, base = compact ? 650 : 1100
  const scale = Math.min(width / base, height / 720, 1.25)
  const fade = Math.min(1, progress * 12, (1 - progress) * 9)
  ctx.clearRect(0, 0, width, height)
  ctx.save(); ctx.fillStyle = `rgba(3,9,18,${.57 * fade})`; ctx.fillRect(0, 0, width, height)
  ctx.translate((width - base * scale) / 2, (height - 640 * scale) / 2); ctx.scale(scale, scale); ctx.globalAlpha = fade
  const center = base / 2
  const shown = cue.cards.slice(-(compact ? 3 : 5))
  const gap = compact ? 135 : shown.length > 3 ? 173 : 230
  const positions = shown.map((item, i) => ({ item, x: center + (i - (shown.length - 1) / 2) * gap, y: 335 - i * 23, angle: (i - (shown.length - 1) / 2) * .105 }))
  if (cue.kind === 'resolve') {
    const active = cue.cards.find(item => item.order === cue.order)
    if (active) {
      for (const item of cue.cards.filter(item => Math.abs(item.order - cue.order) === 1)) {
        ctx.save(); ctx.globalAlpha *= .25
        card(ctx, item, art, center + (item.order < cue.order ? -1 : 1) * (compact ? 218 : 280), 340, compact ? 110 : 125)
        ctx.restore()
      }
      const counter = cue.result?.negatedBy === '失灵！' ? 'negate' : cue.result?.negatedBy === '加百列之光' ? 'gabriel' : null
      const grey = Boolean(cue.result?.failed || (cue.result?.negated && (!counter || progress >= (counter === 'gabriel' ? .50 : .33))))
      card(ctx, active, art, center, 330, compact ? 245 : 260, 0, grey)
      number(ctx, active.order, center + 137, 490, 106)
      if (grey) {
        ctx.save(); ctx.translate(center, 330); ctx.rotate(-.12)
        ctx.fillStyle = '#421d2ae8'; ctx.fillRect(-145, -32, 290, 64)
        ctx.strokeStyle = '#f1a4a9'; ctx.lineWidth = 1; ctx.strokeRect(-145, -32, 290, 64)
        ctx.fillStyle = '#ffdad6'; ctx.font = '700 36px "Microsoft YaHei",sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
        ctx.fillText(cue.result?.negated ? '无 效' : '未生效', 0, 0); ctx.restore()
      } else {
        ctx.save(); ctx.globalAlpha *= .5 * Math.sin(progress * Math.PI)
        const light = ctx.createRadialGradient(center, 330, 80, center, 330, 275)
        light.addColorStop(0, '#d6c78655'); light.addColorStop(1, 'transparent'); ctx.fillStyle = light; ctx.fillRect(center - 275, 55, 550, 550); ctx.restore()
      }
      if(cue.result?.negated && counter)drawCounterEffect(ctx,counter,progress,{x:center-(compact?245:260)/2,y:330-(compact?245:260)*.75,w:compact?245:260,h:(compact?245:260)*1.5})
    }
  } else {
    for (let i = 1; i < positions.length; i++) chain(ctx, positions[i - 1].x + 45, positions[i - 1].y, positions[i].x - 45, positions[i].y)
    for (const pos of positions) {
      const incoming = cue.kind === 'join' && pos.item.order === cue.order
      const flight = incoming ? ease(progress * CHAIN_ENTRY_MS / CHAIN_FLIGHT_MS) : 1
      const fromTop = pos.item.caster === 'p2'
      const x = mix(center + (fromTop ? 290 : -220), pos.x, flight)
      const y = mix(fromTop ? -260 : 980, pos.y, flight)
      const angle = mix(fromTop ? -.5 : .45, pos.angle, flight)
      const w = compact ? 185 : shown.length > 3 ? 175 : 210
      card(ctx, pos.item, art, x, y, w, angle)
      if (flight > .96) {
        chain(ctx, pos.x - w * .2, pos.y - w * .78, pos.x - w * .56, pos.y - w * .40)
        chain(ctx, pos.x + w * .20, pos.y + w * .78, pos.x + w * .56, pos.y + w * .41)
        number(ctx, pos.item.order, pos.x + w * .5, pos.y + w * .63, 86)
      }
    }
    if (cue.kind === 'success') success(ctx, center, 340, progress, compact)
  }
  ctx.restore()
}
