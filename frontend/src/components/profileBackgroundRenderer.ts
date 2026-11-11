/** 大窗口将渐变、遮罩和模糊烘焙一次；逐帧只合成有像素上限的纹理。 */
const PAINT_PROPERTIES = [
  'background-image', 'background-size', 'background-position', 'background-repeat',
  'filter', 'mask-image', 'mask-size', 'mask-position', 'mask-repeat',
]

interface Layer {
  bitmap: HTMLCanvasElement
  element: HTMLElement
  pseudo: string | null
}

function escapeAttribute(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;')
}

async function rasterize(
  element: HTMLElement, pseudo: string | null,
  width: number, height: number, textureWidth: number, textureHeight: number,
): Promise<Layer> {
  const style = getComputedStyle(element, pseudo)
  const paint = PAINT_PROPERTIES.map(name => `${name}:${style.getPropertyValue(name)}`).join(';')
  const css = `width:${width}px;height:${height}px;${paint}`
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${textureWidth}" height="${textureHeight}" viewBox="0 0 ${width} ${height}"><foreignObject width="${width}" height="${height}"><div xmlns="http://www.w3.org/1999/xhtml" style="${escapeAttribute(css)}"></div></foreignObject></svg>`
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    const bitmap = document.createElement('canvas')
    bitmap.width = textureWidth
    bitmap.height = textureHeight
    const context = bitmap.getContext('2d')
    if (!context) throw new Error('背景纹理画布不可用')
    context.drawImage(image, 0, 0)
    return { bitmap, element, pseudo }
  } finally {
    URL.revokeObjectURL(url)
  }
}

export function createProfileBackgroundRenderer(
  host: HTMLElement, canvas: HTMLCanvasElement,
  options: { enabled: () => boolean; reduced: () => boolean },
): { refresh: () => void; syncMotion: () => void; destroy: () => void } {
  const context = canvas.getContext('2d')
  const media = matchMedia('(prefers-reduced-motion: reduce)')
  let layers: Layer[] = []
  let width = 0
  let height = 0
  let generation = 0
  let frame = 0
  let nextFrame = 0
  let signature = ''
  let destroyed = false
  let resizeTimer = 0

  function stop(): void {
    cancelAnimationFrame(frame)
    frame = 0
  }

  function fallback(): void {
    stop()
    host.dataset.renderer = 'css'
    canvas.hidden = true
    layers = []
  }

  function reduced(): boolean { return media.matches || options.reduced() }

  function draw(now: number): void {
    frame = 0
    if (destroyed || !context || !layers.length || document.hidden) return
    if (now >= nextFrame) {
      nextFrame = now + 1000 / 30
      context.setTransform(1, 0, 0, 1, 0, 0)
      context.clearRect(0, 0, canvas.width, canvas.height)
      layers.forEach((layer, index) => {
        const style = getComputedStyle(layer.element, layer.pseudo)
        context.save()
        context.scale(canvas.width / width, canvas.height / height)
        if (index > 0) {
          context.globalAlpha = Number(style.opacity)
          const [x = 0, y = 0] = style.transformOrigin.split(' ').map(parseFloat)
          const matrix = new DOMMatrix(style.transform === 'none' ? undefined : style.transform)
          context.translate(x, y)
          context.transform(matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f)
          context.translate(-x, -y)
        }
        context.drawImage(layer.bitmap, 0, 0, width, height)
        context.restore()
      })
    }
    if (!reduced()) frame = requestAnimationFrame(draw)
  }

  function syncMotion(): void {
    stop()
    nextFrame = 0
    draw(performance.now())
  }

  async function rebuild(): Promise<void> {
    if (destroyed) return
    const bounds = host.getBoundingClientRect()
    const nextWidth = Math.round(bounds.width)
    const nextHeight = Math.round(bounds.height)
    const enabled = options.enabled() && nextWidth >= 1024 && nextHeight > 0 && !!context
    const nextSignature = `${nextWidth}:${nextHeight}:${host.dataset.bg}:${enabled}`
    if (signature === nextSignature) return
    signature = nextSignature
    const version = ++generation
    fallback()
    if (!enabled) return
    const scale = Math.min(1, 1280 / nextWidth, 720 / nextHeight)
    const textureWidth = Math.max(1, Math.round(nextWidth * scale))
    const textureHeight = Math.max(1, Math.round(nextHeight * scale))
    try {
      // 只采集背景节点，避免把画布自身包含进纹理。
      const sources = [host, ...host.querySelectorAll<HTMLElement>(':scope > span')]
      const cached = await Promise.all([
        ...sources.map(element => rasterize(element, null, nextWidth, nextHeight, textureWidth, textureHeight)),
        rasterize(host, '::before', nextWidth, nextHeight, textureWidth, textureHeight),
        rasterize(host, '::after', nextWidth, nextHeight, textureWidth, textureHeight),
      ])
      if (destroyed || version !== generation) return
      width = nextWidth
      height = nextHeight
      canvas.width = textureWidth
      canvas.height = textureHeight
      layers = cached
      host.dataset.renderer = 'cached'
      canvas.hidden = false
      syncMotion()
    } catch {
      // 不支持离屏栅格化的浏览器继续使用原有背景。
      if (!destroyed && version === generation) fallback()
    }
  }

  const refresh = (): void => {
    clearTimeout(resizeTimer)
    void rebuild()
  }
  // 连续拖动窗口时沿用上一帧纹理，尺寸稳定后再烘焙，避免堆积解码任务。
  const observer = new ResizeObserver(() => {
    clearTimeout(resizeTimer)
    resizeTimer = window.setTimeout(refresh, 120)
  })
  observer.observe(host)
  document.addEventListener('visibilitychange', syncMotion)
  media.addEventListener('change', syncMotion)
  refresh()
  return {
    refresh,
    syncMotion,
    destroy(): void {
      destroyed = true
      generation++
      clearTimeout(resizeTimer)
      observer.disconnect()
      document.removeEventListener('visibilitychange', syncMotion)
      media.removeEventListener('change', syncMotion)
      fallback()
      canvas.width = canvas.height = 0
    },
  }
}
