<script setup lang="ts">
import { computed } from 'vue'

/**
 * 区域目标预览层（A＋D 方案）。
 *
 * A：整片作用范围只画**一条**完整外轮廓 + 很淡的填色，角落一个小尺寸标记（3×3 / 2×2 / 行 / 6 格）；
 * D：轮廓与填色按卡牌主题取色（冻结冰蓝、硫磺火焰与轰炸琥珀、神威紫、雷达青绿），克制不发散。
 *
 * 只做绘制：不进 DOM 交互，`pointer-events: none`，格子照旧由 `BoardPanel` 渲染并接收点击。
 * 几何完全由 CSS 变量推导（`--cell` / `--gap` / `--pad`），与 `.board__grid` 的网格同源，
 * 因此不需要测量 DOM，也不会随窗口缩放错位。
 */
const props = defineProps<{
  /** 参与预览的格子，键形如 `x-y`。 */
  cells: string[]
  /** 主题色档位。 */
  tone?: 'freeze' | 'fire' | 'divine' | 'radar' | 'default'
  /** 角落标记文案，缺省按覆盖范围自动推导。 */
  label?: string
}>()

const cells = computed(() => props.cells ?? [])
const keySet = computed(() => new Set(cells.value))
const coords = computed(() =>
  cells.value.map((key) => {
    const [x, y] = key.split('-').map(Number)
    return { key, x, y }
  }),
)
const has = (x: number, y: number) => keySet.value.has(x + '-' + y)

/** 一片范围才有外轮廓；零散选船（穿帮场景）交给 `BoardPanel` 的轻量圆环，这里不画。 */
const bounds = computed(() => {
  if (!coords.value.length) return null
  const xs = coords.value.map((c) => c.x)
  const ys = coords.value.map((c) => c.y)
  return { x1: Math.min(...xs), x2: Math.max(...xs), y1: Math.min(...ys), y2: Math.max(...ys) }
})

const width = computed(() => (bounds.value ? bounds.value.x2 - bounds.value.x1 + 1 : 0))
const height = computed(() => (bounds.value ? bounds.value.y2 - bounds.value.y1 + 1 : 0))

/** 覆盖范围是否恰好填满包围盒——填满才可能是“整片”，否则只是散点。 */
const filled = computed(() => width.value * height.value === coords.value.length && coords.value.length > 1)

const band = computed(() => filled.value && (width.value === 1 || height.value === 1))

const shape = computed<'rect' | 'band' | 'union' | 'none'>(() => {
  if (!bounds.value || coords.value.length < 2) return 'none'
  if (!filled.value) return 'union'
  return band.value ? 'band' : 'rect'
})

const label = computed(() => {
  if (props.label) return props.label
  if (!bounds.value) return ''
  if (shape.value === 'band') return width.value === 1 ? '列 6 格' : '行 6 格'
  if (shape.value === 'rect') return width.value + '×' + height.value
  return coords.value.length + ' 格'
})

/** 每格的左/上偏移（与 `.board__grid` 的 padding + gap 同步）。 */
function cellLeft(x: number): string {
  return `calc(var(--pad, 10px) + ${x} * (var(--cell, 40px) + var(--gap, 4px)))`
}

function cellTop(y: number): string {
  return `calc(var(--pad, 10px) + ${y} * (var(--cell, 40px) + var(--gap, 4px)))`
}

interface Edge {
  key: string
  side: 'top' | 'right' | 'bottom' | 'left'
  style: Record<string, string>
}

/**
 * 只画“暴露边”：相邻格也在预览里的一侧不画，于是连续矩形得到一条完整外框，
 * 不规则的六连格得到真实并集轮廓，而不会退化成包围矩形（暗示额外作用格）。
 */
const edges = computed<Edge[]>(() => {
  if (shape.value === 'none' || shape.value === 'union') {
    if (shape.value !== 'union') return []
  }
  const out: Edge[] = []
  const thickness = '2px'
  for (const cell of coords.value) {
    const left = cellLeft(cell.x)
    const top = cellTop(cell.y)
    const base = { left, top, width: 'var(--cell, 40px)', height: 'var(--cell, 40px)' }
    if (!has(cell.x, cell.y - 1)) {
      out.push({ key: cell.key + '-t', side: 'top', style: { ...base, transform: 'translate(0, -1px)', height: thickness } })
    }
    if (!has(cell.x, cell.y + 1)) {
      out.push({ key: cell.key + '-b', side: 'bottom', style: { ...base, transform: 'translate(0, 1px)', height: thickness } })
    }
    if (!has(cell.x - 1, cell.y)) {
      out.push({ key: cell.key + '-l', side: 'left', style: { ...base, transform: 'translate(-1px, 0)', width: thickness } })
    }
    if (!has(cell.x + 1, cell.y)) {
      out.push({ key: cell.key + '-r', side: 'right', style: { ...base, transform: 'translate(1px, 0)', width: thickness } })
    }
  }
  return out
})

const badgeStyle = computed<Record<string, string>>(() => {
  if (!bounds.value) return { left: '0px', top: '0px' }
  // 标记贴在并集包围盒的左上角内侧：永远在棋盘内，不会被容器裁掉。
  return { left: cellLeft(bounds.value.x1), top: cellTop(bounds.value.y1) }
})
</script>

<template>
  <div
    v-if="shape !== 'none'"
    class="sel-preview"
    :class="['sel-preview--' + shape, 'sel-tone--' + (tone ?? 'default')]"
    :data-shape="shape"
    :data-tone="tone ?? 'default'"
    data-testid="board-selection-preview"
    aria-hidden="true"
  >
    <span
      v-for="cell in coords"
      :key="cell.key + '-fill'"
      class="sel-preview__fill"
      :style="{ left: cellLeft(cell.x), top: cellTop(cell.y) }"
    ></span>
    <span
      v-for="edge in edges"
      :key="edge.key"
      class="sel-preview__edge"
      :class="'sel-preview__edge--' + edge.side"
      :style="edge.style"
    ></span>
    <span v-if="label" class="sel-preview__tag" :style="badgeStyle">{{ label }}</span>
  </div>
</template>

<style scoped>
.sel-preview {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  --sel-hue: var(--role-action);
  --sel-border: color-mix(in srgb, var(--sel-hue) 72%, white);
  /* 填色 10%、纹理约 5%：够看出“整片”，又不盖住命中 / 战舰 / 盾牌图标。 */
  --sel-fill: color-mix(in srgb, var(--sel-hue) 10%, transparent);
  --sel-tex: color-mix(in srgb, var(--sel-hue) 14%, transparent);
}

/* D 档主题色：使用现有主题变量作基底，三主题下都成立。 */
.sel-tone--freeze {
  --sel-hue: var(--role-self, #4ec8e0);
}
.sel-tone--fire {
  --sel-hue: var(--gold, #c9a24c);
}
.sel-tone--divine {
  --sel-hue: #8b6cf0;
}
.sel-tone--radar {
  --sel-hue: #3fd6a8;
}

.sel-preview__fill {
  position: absolute;
  width: var(--cell, 40px);
  height: var(--cell, 40px);
  border-radius: 4px;
  background:
    repeating-linear-gradient(
      135deg,
      var(--sel-tex) 0 1px,
      transparent 1px 10px
    ),
    var(--sel-fill);
}

.sel-preview__edge {
  position: absolute;
  border-radius: 2px;
  background: var(--sel-border);
  box-shadow: 0 0 5px color-mix(in srgb, var(--sel-hue) 30%, transparent);
}

.sel-preview__tag {
  position: absolute;
  z-index: 1;
  transform: translate(4px, 4px);
  padding: 1px 5px;
  border: 1px solid color-mix(in srgb, var(--sel-hue) 62%, transparent);
  border-radius: 4px;
  background: color-mix(in srgb, var(--surface-chamber, #151a30) 82%, transparent);
  color: var(--sel-border);
  font-size: 10px;
  line-height: 1.35;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

@media (max-width: 719px) {
  .sel-preview__tag {
    font-size: 9px;
    padding: 0 4px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sel-preview__edge {
    box-shadow: none;
  }
}
</style>
