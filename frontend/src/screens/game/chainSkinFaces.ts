/**
 * 共享 Canvas（连锁 / 观战 / 录像）的动态皮肤卡面。
 *
 * 只认公开载荷里已经给出的 skin_id，且皮肤必须与这张牌的卡名匹配；不从卡名或对手手牌推断。
 * 每张皮肤牌一个帧源 + 一个 registerSkinAnimation 句柄：回调只记录时间/档位并请求一次舞台重绘，
 * 真正的绘制在宿主原有绘制顺序里调用 drawSkinFace。每帧没画到的牌标记 visible:false，
 * 久未出现或场景结束时 dispose()。
 */
import { getSkin } from '../../cards/skins/skinManifest'
import { createSkinFrameSource, drawSkinFace } from '../../cards/skins/skinMotion'
import type { SkinFaceContext, SkinFaceRect, SkinFrameSource, SkinMotionLevel } from '../../cards/skins/skinMotion'
import { registerSkinAnimation } from '../../cards/skins/skinAnimationRuntime'
import { normalizeSkinId } from '../../cards/skinArt'

/** 在当前变换下的局部矩形里画动态卡面；false 表示未就绪，宿主沿用旧静态绘制。 */
export type SkinFacePainter = (ctx: CanvasRenderingContext2D, rect: SkinFaceRect) => boolean
export type SkinFaceLookup = (name: string, skinId?: string | null) => SkinFacePainter | null

interface Face {
  source: SkinFrameSource
  ready: boolean
  elapsed: number
  level: SkinMotionLevel
  motionRequested: boolean
  animation?: ReturnType<typeof registerSkinAnimation>
  element?: HTMLElement
  seen: number
  last?: number
  visible: boolean
  painter: SkinFacePainter
}

const IDLE_DISPOSE_MS = 1500

export function createChainSkinFaces(context: SkinFaceContext, requestRender: () => void) {
  const faces = new Map<string, Face>()
  let frame = 0
  let disposed = false

  function register(face: Face, element: HTMLElement) {
    face.animation?.dispose()
    face.element = element
    face.animation = registerSkinAnimation({
      element, tier: face.source.tier, context, visible: true,
      onLevelChange(level) { face.level = level },
      onFrame(time, level) {
        face.elapsed = time; face.level = level
        if (level === 'full' && !face.motionRequested) {
          face.motionRequested = true
          void face.source.prepareMotion()
        }
        requestRender()
      },
    })
  }

  const lookup: SkinFaceLookup = (name, skinId) => {
    if (disposed) return null
    const id = normalizeSkinId(skinId)
    const skin = getSkin(id)
    if (!skin || skin.cardName !== name) return null
    let face = faces.get(skin.skinId)
    if (!face) {
      const source = createSkinFrameSource(skin.skinId)
      if (!source) return null
      const created: Face = {
        source, ready: false, elapsed: 0, level: 'static', motionRequested: false, seen: frame, visible: true,
        painter(ctx, rect) {
          created.seen = frame
          if (!created.ready) return false
          const element = ctx.canvas as HTMLCanvasElement | undefined
          if (element && element !== created.element && typeof HTMLElement !== 'undefined' && element instanceof HTMLElement) register(created, element)
          if (!created.visible) { created.visible = true; created.animation?.update({ visible: true }) }
          return drawSkinFace(ctx, source, rect, created.elapsed, created.level)
        },
      }
      face = created
      faces.set(skin.skinId, created)
      void source.ready.then((ready) => {
        if (disposed || faces.get(skin.skinId) !== created) return
        created.ready = ready
        if (ready) requestRender()
      })
    }
    return face.painter
  }

  return {
    lookup,
    /** 每次舞台重绘前调用。 */
    beginFrame() { frame += 1 },
    /** 每次舞台重绘后调用：本帧没画到的牌停掉调度，久未出现的释放。 */
    endFrame(now = Date.now()) {
      faces.forEach((face, key) => {
        if (face.seen === frame) { face.last = now; return }
        if (face.visible) { face.visible = false; face.animation?.update({ visible: false }) }
        face.last ??= now
        if (now - face.last > IDLE_DISPOSE_MS) { face.animation?.dispose(); faces.delete(key) }
      })
    },
    /** 场景结束 / 卸载：全部释放。 */
    clear() {
      faces.forEach((face) => face.animation?.dispose())
      faces.clear()
    },
    dispose() { disposed = true; faces.forEach((face) => face.animation?.dispose()); faces.clear() },
  }
}
