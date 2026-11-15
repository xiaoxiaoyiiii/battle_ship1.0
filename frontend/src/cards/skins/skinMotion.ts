import { getSkin } from './skinManifest'
import type { SkinTier } from './skinManifest'

export type SkinFaceContext = 'reveal' | 'collection' | 'hand' | 'chain' | 'spectate' | 'replay'
export type SkinMotionLevel = 'static' | 'subtle' | 'full'
export interface SkinFaceRect { x: number; y: number; width: number; height: number }
export interface SkinFrameSource {
  readonly skinId: string
  readonly tier: SkinTier
  readonly width: 768
  readonly height: 1152
  readonly staticUrl: string
  readonly ready: Promise<boolean>
  prepareMotion(): Promise<boolean>
  draw(ctx: CanvasRenderingContext2D, rect: SkinFaceRect, timeMs: number, level: SkinMotionLevel): boolean
}

const ART = { x: 28, y: 151, width: 712, height: 637 }
const TAU = Math.PI * 2
// 只保存资源地址；创建静态首屏不会请求任何动态图层。
const layers: Record<string, readonly string[]> = {
  'neon-shiling': [new URL('../../assets/skins/motion/neon-shiling-reactor.webp', import.meta.url).href],
  'neon-emo-qiyue': [
    new URL('../../assets/skins/motion/neon-emo-qiyue-demon.webp', import.meta.url).href,
    new URL('../../assets/skins/motion/neon-emo-qiyue-contract.webp', import.meta.url).href,
  ],
  'neon-juechu-fengsheng': [new URL('../../assets/skins/motion/neon-juechu-fengsheng-ship.webp', import.meta.url).href],
}
const images = new Map<string, { image: HTMLImageElement; ready: Promise<boolean> }>()

function loadImage(url: string) {
  const cached = images.get(url)
  if (cached) return cached
  if (typeof Image === 'undefined') return null
  const image = new Image()
  image.decoding = 'async'
  const ready = new Promise<boolean>((resolve) => {
    image.onload = () => resolve(image.naturalWidth > 0)
    image.onerror = () => resolve(false)
  })
  const entry = { image, ready }
  images.set(url, entry)
  image.src = url
  return entry
}

function glow(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, color: string, alpha: number) {
  const opacity = ctx.globalAlpha
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius)
  gradient.addColorStop(0, color)
  gradient.addColorStop(1, 'transparent')
  ctx.globalAlpha = opacity * alpha
  ctx.fillStyle = gradient
  ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2)
  ctx.globalAlpha = opacity
}

function motes(ctx: CanvasRenderingContext2D, p: number, full: boolean, seed: number) {
  const opacity = ctx.globalAlpha
  const count = full ? 70 : 5
  for (let i = 0; i < count; i += 1) {
    const life = (p * (full ? 2 : 1) + i * .61803398875 + seed) % 1
    const alpha = Math.sin(Math.PI * life) ** 2
    const x = ART.x + 20 + ((i * 137.51 + seed * 677) % 670) + Math.sin(p * TAU + i) * (full ? 20 : 3)
    const y = ART.y + ART.height * (1 - life)
    const size = full ? 1.4 + i % 4 * .65 : 1.5
    ctx.globalAlpha = opacity * alpha * (full ? .85 : .25)
    ctx.fillStyle = full && i % 3 ? '#ffe5af' : '#89f9ed'
    ctx.fillRect(x, y, size, size)
    if (full && i % 3 === 0) {
      ctx.lineWidth = .8
      ctx.strokeStyle = i % 2 ? '#ffaddb' : '#f8f1d2'
      ctx.beginPath()
      ctx.moveTo(x - size * 2.5, y); ctx.lineTo(x + size * 2.5, y)
      ctx.moveTo(x, y - size * 2.5); ctx.lineTo(x, y + size * 2.5)
      ctx.stroke()
    }
    if (full && i % 7 === 0) {
      ctx.save(); ctx.translate(x, y); ctx.rotate(p * TAU + i)
      ctx.beginPath(); ctx.moveTo(-4, -8); ctx.lineTo(6, 0); ctx.lineTo(-2, 9); ctx.closePath()
      ctx.globalAlpha *= .65; ctx.stroke(); ctx.restore()
    }
  }
  ctx.globalAlpha = opacity
}

function ribbon(ctx: CanvasRenderingContext2D, p: number, y: number, color: string, amplitude: number) {
  const opacity = ctx.globalAlpha
  ctx.strokeStyle = color; ctx.lineWidth = 1.4
  for (let band = 0; band < 3; band += 1) {
    ctx.globalAlpha = opacity * (.14 + band * .07)
    ctx.beginPath()
    for (let n = 0; n <= 24; n += 1) {
      const x = ART.x + n / 24 * ART.width
      const wave = Math.sin(n / 24 * TAU * 2 + p * TAU + band * .32) * amplitude
      if (n === 0) ctx.moveTo(x, y + wave + band * 5)
      else ctx.lineTo(x, y + wave + band * 5)
    }
    ctx.stroke()
  }
  ctx.globalAlpha = opacity
}

function sceneEnergy(ctx: CanvasRenderingContext2D, skinId: string, p: number) {
  const opacity = ctx.globalAlpha
  const phase = p * TAU
  if (skinId === 'neon-shiling') {
    const x = 390, y = 402
    ctx.save(); ctx.translate(x, y); ctx.rotate(phase)
    for (let ring = 0; ring < 3; ring += 1) {
      ctx.strokeStyle = ring % 2 ? '#de8dff' : '#79fff1'
      ctx.globalAlpha = opacity * (.3 + .16 * Math.sin(phase + ring))
      ctx.lineWidth = ring === 0 ? 2.5 : 1.2
      ctx.setLineDash([17 + ring * 7, 13])
      ctx.beginPath(); ctx.arc(0, 0, 84 + ring * 44, 0, TAU); ctx.stroke()
    }
    ctx.restore()
    glow(ctx, x, y, 150, '#61f4e8', .12 + .07 * Math.sin(phase))
    ribbon(ctx, p, 438, '#c79bff', 34)
  } else if (skinId === 'neon-emo-qiyue') {
    glow(ctx, 384, 404, 178, '#ff489f', .14 + .07 * Math.sin(phase))
    for (let i = 0; i < 4; i += 1) ribbon(ctx, p + i * .25, 390 + i * 14, i % 2 ? '#fb8ad6' : '#ff4f9b', 18)
    ctx.save(); ctx.translate(384, 592); ctx.rotate(-phase)
    ctx.setLineDash([9, 17]); ctx.strokeStyle = '#edb6ff'; ctx.lineWidth = 2; ctx.globalAlpha = opacity * .55
    ctx.beginPath(); ctx.arc(0, 0, 49, 0, TAU); ctx.stroke(); ctx.restore()
  } else {
    glow(ctx, 392, 231, 178, '#ffa6f2', .15 + .06 * Math.sin(phase))
    ribbon(ctx, p, 680, '#ac81ff', 18)
    ribbon(ctx, p + .25, 720, '#72f3f0', 13)
    ctx.save(); ctx.translate(390, 225)
    for (const direction of [-1, 1]) {
      ctx.save(); ctx.scale(direction, 1); ctx.rotate(Math.sin(phase) * .07)
      for (let feather = 0; feather < 7; feather += 1) {
        ctx.globalAlpha = opacity * (.13 + .1 * Math.sin(phase + feather * .45) ** 2)
        ctx.strokeStyle = feather % 2 ? '#ffcefc' : '#81f6ff'; ctx.lineWidth = 2
        ctx.beginPath(); ctx.moveTo(0, 30); ctx.quadraticCurveTo(55 + feather * 12, -80, 140 + feather * 20, -60 + feather * 14); ctx.stroke()
      }
      ctx.restore()
    }
    ctx.restore()
  }
  ctx.globalAlpha = opacity
}

function sweep(ctx: CanvasRenderingContext2D, p: number) {
  for (let i = 0; i < 2; i += 1) {
    const progress = (p * 2 + i * .5) % 1
    const x = -280 + progress * 1450
    ctx.save(); ctx.translate(x, ART.y); ctx.transform(1, 0, -.38, 1, 0, 0)
    const gradient = ctx.createLinearGradient(-65, 0, 65, 0)
    gradient.addColorStop(0, 'transparent'); gradient.addColorStop(.45, '#ffe5c4'); gradient.addColorStop(.5, '#fff7dd'); gradient.addColorStop(.56, '#ffa5e3'); gradient.addColorStop(1, 'transparent')
    ctx.globalAlpha *= Math.sin(progress * Math.PI) ** 2 * .17
    ctx.fillStyle = gradient; ctx.fillRect(-65, -100, 130, ART.height + 200); ctx.restore()
  }
}

/** 传说的双束流光只穿过插画，沿六秒周期绕回，文字区保持静止。 */
function legendaryFlow(ctx: CanvasRenderingContext2D, p: number) {
  const opacity = ctx.globalAlpha
  for (let beam = 0; beam < 2; beam += 1) {
    const travel = (p + beam * .5) % 1
    const x = ART.x - 280 + travel * (ART.width + 560)
    const gradient = ctx.createLinearGradient(x - 100, ART.y, x + 130, ART.y + ART.height)
    gradient.addColorStop(0, 'transparent')
    gradient.addColorStop(.35, beam ? '#aa82ff00' : '#76fff000')
    gradient.addColorStop(.48, beam ? '#c4a2ff' : '#a4fff1')
    gradient.addColorStop(.52, '#ffffff')
    gradient.addColorStop(.65, beam ? '#aa82ff00' : '#76fff000')
    gradient.addColorStop(1, 'transparent')
    ctx.globalAlpha = opacity * Math.sin(Math.PI * travel) ** 2 * .23
    ctx.fillStyle = gradient
    ctx.fillRect(ART.x, ART.y, ART.width, ART.height)
  }
  ctx.globalAlpha = opacity
}

function frameGlow(ctx: CanvasRenderingContext2D, p: number, full: boolean) {
  const opacity = ctx.globalAlpha
  ctx.globalAlpha = opacity * (full ? .65 : .12 + Math.sin(p * TAU) * .06)
  const gradient = ctx.createLinearGradient(0, 0, 768, 1152)
  gradient.addColorStop(0, '#76f7ef'); gradient.addColorStop(.4, full ? '#ffe4a4' : '#a58aff'); gradient.addColorStop(1, full ? '#ff93c9' : '#76f7ef')
  ctx.strokeStyle = gradient; ctx.lineWidth = full ? 2.5 : 1
  ctx.setLineDash(full ? [44, 19, 6, 19] : [])
  ctx.lineDashOffset = -p * 88 * 8
  ctx.beginPath(); ctx.roundRect(13, 13, 742, 1126, 16); ctx.stroke()
  ctx.setLineDash([]); ctx.globalAlpha = opacity
}

/** 与DOM共用的逐帧入口。文字、速阶、类型、规则区永远直接取静态整卡。 */
export function drawSkinFace(ctx: CanvasRenderingContext2D, source: SkinFrameSource, rect: SkinFaceRect, timeMs: number, level: SkinMotionLevel): boolean {
  return source.draw(ctx, rect, timeMs, level)
}

/** 只接受调用方已获授权的skinId，不从卡名或对手手牌推断皮肤。 */
export function createSkinFrameSource(skinId: string | null | undefined): SkinFrameSource | null {
  const skin = getSkin(skinId)
  if (!skin) return null
  const base = loadImage(skin.imageUrl)
  let sprites: HTMLImageElement[] = []
  let motionPromise: Promise<boolean> | undefined
  const source: SkinFrameSource = {
    skinId: skin.skinId, tier: skin.tier, width: 768, height: 1152, staticUrl: skin.imageUrl,
    ready: base?.ready ?? Promise.resolve(false),
    prepareMotion() {
      if (!motionPromise) {
        const pending = (layers[skin.skinId] ?? []).map(loadImage)
        motionPromise = Promise.all(pending.map((entry) => entry?.ready ?? false)).then((ready) => {
          if (!ready.every(Boolean)) return false
          sprites = pending.flatMap((entry) => entry ? [entry.image] : [])
          return true
        })
      }
      return motionPromise
    },
    draw(ctx, rect, timeMs, level) {
      if (!base?.image.complete || !base.image.naturalWidth || rect.width <= 0 || rect.height <= 0) return false
      const full = level === 'full' && skin.tier === 'limited' && sprites.length > 0
      const seconds = full ? 8000 : 6000
      const p = ((Number.isFinite(timeMs) ? timeMs : 0) % seconds + seconds) % seconds / seconds
      const phase = p * TAU
      const seed = skin.cardKey.length * .071
      ctx.save(); ctx.translate(rect.x, rect.y); ctx.scale(rect.width / 768, rect.height / 1152)
      ctx.drawImage(base.image, 0, 0, 768, 1152)
      if (level !== 'static') {
        ctx.save(); ctx.beginPath(); ctx.rect(ART.x, ART.y, ART.width, ART.height); ctx.clip()
        if (full) {
          const scale = 1.035 + Math.sin(phase) * .006
          const dx = Math.sin(phase) * 4, dy = Math.cos(phase) * 3
          ctx.drawImage(base.image, ART.x, ART.y, ART.width, ART.height,
            ART.x - ART.width * (scale - 1) / 2 + dx, ART.y - ART.height * (scale - 1) / 2 + dy, ART.width * scale, ART.height * scale)
          sprites.forEach((sprite, index) => {
            ctx.save(); ctx.translate(ART.x + ART.width / 2, ART.y + ART.height / 2)
            ctx.translate(Math.sin(phase + index * Math.PI) * 10, Math.sin(phase + index * 1.5) * (skin.cardKey === 'juechu-fengsheng' ? 12 : 9))
            ctx.rotate(Math.sin(phase + index) * .009); ctx.scale(1.06, 1.06)
            ctx.drawImage(sprite, -ART.width / 2, -ART.height / 2, ART.width, ART.height); ctx.restore()
          })
          ctx.save(); ctx.globalCompositeOperation = 'screen'
          sceneEnergy(ctx, skin.skinId, p); sweep(ctx, p); motes(ctx, p, true, seed); ctx.restore()
        } else {
          ctx.save(); ctx.globalCompositeOperation = 'screen'
          glow(ctx, 384, 440, 300, '#7b64d5', .025 + .015 * Math.sin(phase))
          if (skin.tier === 'legendary') legendaryFlow(ctx, p)
          motes(ctx, p, false, seed); ctx.restore()
        }
        ctx.restore(); frameGlow(ctx, p, full)
      }
      ctx.restore()
      return true
    },
  }
  return source
}
