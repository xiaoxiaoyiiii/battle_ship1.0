<script setup lang="ts">
import { computed, ref, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import BoardAreaPreview from './BoardAreaPreview.vue'
import BoardCellIcon from './BoardCellIcon.vue'
import { cellVisualState, cellHints } from './cellPresentation'
import type { BoardCell } from './view'

/**
 * One 6x6 sea (ticket #27, keyboard + legal-range pass in #47).
 *
 * Pure rendering: every flag comes from the view model, which itself only
 * formats store values. The panel never decides a game rule; `attackable` and
 * `legal` are computed from the server snapshot by the screen.
 *
 * #47 adds two presentation-only behaviours: a roving cursor so arrow keys +
 * Enter can fire (the grid keeps one tab stop, cells stay programmatic
 * buttons for the gates) and a `legal` highlight set for the target banner.
 */
const props = defineProps<{
  board: 'self' | 'opponent'
  boardTestid: string
  titleTestid: string
  title: string
  subtitle?: string
  cells: BoardCell[]
  selected?: string[]
  preview?: string[]
  legal?: string[]
  hidden?: boolean
  selectionBoard?: 'self' | 'opponent' | null
  /** 区域类卡牌的目标形状；'ships' 表示点船选择，不画整片轮廓。 */
  selectionKind?: 'area' | 'line' | 'continuous' | 'ships' | null
  /** A＋D 预览层的主题色档位。 */
  selectionTone?: 'freeze' | 'fire' | 'divine' | 'radar' | 'default'
  /** 预览层角落标记（缺省由覆盖范围推导）。 */
  selectionBadge?: string
  selectionLabel?: string
  selectionHint?: string
  picking?: boolean
  interactive?: boolean
}>()

const emit = defineEmits<{ (event: 'cell', x: number, y: number): void; (event: 'hover', point: { x: number; y: number } | null): void }>()

const selectedSet = computed(() => new Set(props.selected ?? []))
const previewSet = computed(() => new Set(props.preview ?? []))
const legalSet = computed(() => new Set(
  props.picking && (!props.selectionBoard || props.selectionBoard === props.board) ? props.legal ?? [] : [],
))
/**
 * A＋D 区域预览：只有「成片」的目标（区域 / 行列 / 连续格）才画整片轮廓与填色；
 * 点船类目标保持逐格轻量标记，不会把几艘独立的船连成假的整片范围。
 */
const areaPreviewCells = computed<string[]>(() => {
  const kind = props.selectionKind
  if (kind !== 'area' && kind !== 'line' && kind !== 'continuous') return []
  if (props.hidden) return []
  const merged = new Set<string>([...(props.preview ?? []), ...(props.selected ?? [])])
  return [...merged]
})
const areaPreviewActive = computed(() => areaPreviewCells.value.length > 0)

const cursor = ref(0)
const grid = ref<HTMLElement | null>(null)

// 提示传送到根节点，避免被棋盘或手机对局容器裁切；不拦截点击。
const hintedKey = ref<string | null>(null)
const tooltip = ref<HTMLElement | null>(null)
const hintPosition = ref({ left: '0px', top: '0px', visibility: 'hidden' as 'hidden' | 'visible' })
const hintId = computed(() => props.boardTestid + '-cell-hint')
const hintedCell = computed(() => props.cells.find(cell => cell.key === hintedKey.value))
function hintsFor(cell: BoardCell) {
  return cellHints(cell, { selectable: legalSet.value.has(cell.key), card: props.selectionLabel, hint: props.selectionHint })
}
const hints = computed(() => hintedCell.value && !props.hidden ? hintsFor(hintedCell.value) : [])
function hideHint() { hintedKey.value = null }
async function showHint(cell: BoardCell, event: Event) {
  if (!hintsFor(cell).length) { hideHint(); return }
  const anchor = (event.currentTarget as HTMLElement).getBoundingClientRect()
  hintedKey.value = cell.key
  hintPosition.value.visibility = 'hidden'
  await nextTick()
  if (hintedKey.value !== cell.key || !tooltip.value) return
  const bounds = tooltip.value.getBoundingClientRect()
  const left = Math.max(12, Math.min(innerWidth - bounds.width - 12, anchor.left + anchor.width / 2 - bounds.width / 2))
  const preferred = anchor.top >= bounds.height + 18 ? anchor.top - bounds.height - 10 : anchor.bottom + 10
  const top = Math.max(12, Math.min(innerHeight - bounds.height - 12, preferred))
  hintPosition.value = { left: left + 'px', top: top + 'px', visibility: 'visible' }
}
watch(() => props.hidden, hideHint)
onMounted(() => {
  window.addEventListener('resize', hideHint)
  window.addEventListener('scroll', hideHint, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', hideHint)
  window.removeEventListener('scroll', hideHint, true)
})

function cellState(cell: BoardCell): string {
  if (cell.hit && cell.ship) return 'ship-hit'
  if (cell.sunk) return 'ship-sunk'
  if (cell.hit) return 'hit'
  if (cell.miss) return 'miss'
  if (cell.shielded) return 'ship-shielded'
  if (cell.ship) return 'ship'
  return 'empty'
}

function cellLabel(cell: BoardCell): string {
  const parts = ['第 ' + (cell.x + 1) + ' 列 第 ' + (cell.y + 1) + ' 行']
  if (cell.ship) parts.push(cell.sunk ? '已沉没的战舰' : '你的战舰')
  if (cell.frozen) parts.push('被冻结')
  if (cell.shielded) parts.push('带护盾')
  if (cell.invincible) parts.push('无敌')
  if (cell.trap) parts.push('守株待兔陷阱')
  if (cell.hit) parts.push('命中')
  if (cell.miss) parts.push('未命中')
  if (cell.shieldBroken) parts.push('护盾挡下这一炮')
  if (cell.revealed) parts.push('已探明敌舰位置')
  if (cell.hole) parts.push('被神威扣掉，无法攻击')
  if (cell.frozenArea) parts.push('冻结区域')
  if (cell.lastStand) parts.push('绝处逢生候选格')
  if (cell.attackable) parts.push('可攻击')
  if (legalSet.value.has(cell.key)) parts.push('可选择')
  return parts.join('，')
}

function onCell(cell: BoardCell): void {
  emit('cell', cell.x, cell.y)
}

function focusIndex(index: number): void {
  cursor.value = Math.min(Math.max(index, 0), props.cells.length - 1)
  const node = grid.value?.querySelectorAll<HTMLElement>('[role="gridcell"]')[cursor.value]
  node?.focus()
}

/** Arrow keys move the cursor; Enter/Space fires the focused cell (#47). */
function onKeydown(event: KeyboardEvent): void {
  const current = props.cells[cursor.value]
  if (!current) return
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -6, ArrowDown: 6 }[event.key]
  if (step !== undefined) {
    event.preventDefault()
    const next = cursor.value + step
    if (next >= 0 && next < props.cells.length) focusIndex(next)
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('cell', current.x, current.y)
  }
}

function onCellFocus(index: number): void {
  cursor.value = index
}
</script>

<template>
  <section
    v-show="!hidden"
    class="board"
    :class="['board--' + board, { 'board--picking': picking, 'board--area': areaPreviewActive }]"
    :data-testid="boardTestid"
    :data-board="board"
    :aria-label="title"
  >
    <header class="board__head">
      <h2 class="board__title" :data-testid="titleTestid">{{ title }}</h2>
      <p v-if="subtitle" class="board__subtitle">{{ subtitle }}</p>
    </header>
    <div
      ref="grid"
      class="board__grid"
      role="grid"
      tabindex="0"
      :aria-label="title + '，方向键移动，Enter 开炮'"
      @keydown="onKeydown"
    >
      <BoardAreaPreview
        v-if="areaPreviewActive"
        :cells="areaPreviewCells"
        :tone="selectionTone ?? 'default'"
        :label="selectionBadge"
      />
      <button
        v-for="(cell, index) in cells"
        :key="cell.key"
        type="button"
        role="gridcell"
        tabindex="-1"
        class="cell"
        :class="[
          'cell--' + cellState(cell),
          {
            'cell--ship': cell.ship,
            'cell--sunk': cell.sunk,
            'cell--frozen': cell.frozen,
            'cell--shielded': cell.shielded,
            'cell--invincible': cell.invincible,
            'cell--hit': cell.hit,
            'cell--miss': cell.miss,
            'cell--shield-broken': cell.shieldBroken,
            'cell--revealed': cell.revealed,
            'cell--hole': cell.hole,
            'cell--frozen-area': cell.frozenArea,
            'cell--last-stand': cell.lastStand,
            'cell--attackable': cell.attackable,
            'cell--legal': legalSet.has(cell.key),
            'cell--selected': selectedSet.has(cell.key) || previewSet.has(cell.key),
            'cell--trap': cell.trap,
            'cell--preview': previewSet.has(cell.key),
            'cell--cursor': cursor === index,
          },
        ]"
        :data-testid="'game-cell-' + board + '-' + cell.x + '-' + cell.y"
        :data-cell="cellState(cell)"
        :data-visual-state="cellVisualState(cell)"
        :aria-describedby="hintedKey === cell.key && hints.length ? hintId : undefined"
        :data-attackable="cell.attackable ? 'true' : 'false'"
        :data-legal="legalSet.has(cell.key) ? 'true' : 'false'"
        :aria-label="cellLabel(cell)"
        :aria-disabled="picking ? !legalSet.has(cell.key) : board === 'opponent' && !cell.attackable"
        @focus="onCellFocus(index); showHint(cell, $event)"
        @mouseenter="showHint(cell, $event); emit('hover', { x: cell.x, y: cell.y })"
        @mouseleave="hideHint(); emit('hover', null)"
        @blur="hideHint(); emit('hover', null)"
        @keydown.esc="hideHint"
        @click="onCell(cell)"
      >
        <BoardCellIcon v-if="!['empty', 'hole'].includes(cellVisualState(cell))" :kind="cellVisualState(cell)" />
        <span v-if="cell.trap && cellVisualState(cell) !== 'trap' && !cell.sunk" class="cell__badge cell__badge--trap" aria-hidden="true">△</span>
        <span v-if="cell.frozen" class="cell__badge cell__badge--frozen" aria-hidden="true">冻</span>
      </button>
    </div>
    <Teleport to="body">
      <div v-if="hints.length && hintedCell" :id="hintId" ref="tooltip" role="tooltip" class="board-cell-hint" :style="hintPosition">
        <small>第 {{ hintedCell.x + 1 }} 列 · 第 {{ hintedCell.y + 1 }} 行</small>
        <div v-for="hint in hints" :key="hint.title" class="board-cell-hint__item"><b>{{ hint.title }}</b><p>{{ hint.detail }}</p></div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.board {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.board__head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
  padding: 0 2px;
}

.board__title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.16em;
  color: var(--text-tertiary);
}

.board__subtitle {
  margin: 0;
  font-size: 11.5px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.board__grid {
  --gap: 4px;
  --pad: 10px;
  position: relative;
  display: grid;
  grid-template-columns: repeat(6, var(--cell, 40px));
  gap: var(--gap);
  padding: var(--pad);
  border: 1px solid var(--board-border);
  border-radius: 14px;
  background: var(--board-bg);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--role-action) 12%, transparent),
    inset 0 0 42px rgba(0, 0, 0, 0.45),
    0 16px 40px rgba(0, 0, 0, 0.35);
  width: fit-content;
  outline: none;
}

.board__grid:focus-visible {
  box-shadow: 0 0 0 2px var(--focus-ring);
}

.board--opponent .board__grid {
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--role-enemy) 22%, transparent),
    inset 0 0 42px rgba(0, 0, 0, 0.45),
    0 16px 40px rgba(0, 0, 0, 0.35);
}

.board--picking .board__grid {
  border-color: var(--role-action);
  box-shadow: 0 0 0 2px var(--role-action-soft), 0 16px 40px rgba(0, 0, 0, 0.35);
}

.cell {
  position: relative;
  width: var(--cell, 40px);
  height: var(--cell, 40px);
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--board-border) 70%, transparent);
  border-radius: 8px;
  background: var(--cell-bg);
  color: var(--text-tertiary);
  font: inherit;
  font-size: 15px;
  line-height: 1;
  cursor: default;
  transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
}

.cell--attackable {
  cursor: crosshair;
  border-color: color-mix(in srgb, var(--role-enemy) 42%, transparent);
}

.cell--attackable:hover,
.board__grid:focus-visible .cell--cursor,
.cell--cursor:focus-visible {
  background: color-mix(in srgb, var(--role-enemy) 26%, var(--cell-bg));
  border-color: var(--role-enemy);
}

.cell { display:grid; place-items:center; isolation:isolate; }
.cell__art { position:absolute; width:75%; height:75%; max-width:62px; max-height:62px; pointer-events:none; }
.cell[data-visual-state='ship'] { background:linear-gradient(150deg,#607089,#2a3854); border-color:#8f9fb9; color:#eef4ff; }
.cell[data-visual-state='miss'] { background:linear-gradient(150deg,#213656,#17233d); border-color:#527dac; color:#8ddbf7; }
.cell[data-visual-state='ship-hit'] { background:radial-gradient(circle at 50% 42%,#9d2335,#4c1422); border-color:#f05e6f; color:#fff4f3; box-shadow:inset 0 0 12px #cf26322b; }
.cell[data-visual-state='shielded'] { background:linear-gradient(150deg,#123b50,#0b2237); border-color:#49dced; color:#65ebf4; }
.cell[data-visual-state='shield-blocked'] { background:linear-gradient(150deg,#513714,#251c16); border-color:#efb64b; color:#f4c45e; }
.cell[data-visual-state='trap'] { background:linear-gradient(150deg,#382051,#1d1939); border-color:#b77df2; color:#cf9aff; }
.cell[data-visual-state='trap']::before { content:''; position:absolute; inset:2px; background:repeating-linear-gradient(135deg,#bb78f1 0 3px,transparent 3px 7px); clip-path:polygon(0 0,28% 0,0 28%,0 100%,28% 100%,0 72%,100% 0,72% 0,100% 28%,100% 100%,72% 100%,100% 72%); opacity:.7; pointer-events:none; }
.cell--frozen { box-shadow:inset 0 0 0 1px var(--role-self); }
.cell[data-visual-state='empty'].cell--revealed { background:color-mix(in srgb,var(--gold) 32%,var(--cell-bg)); border-color:var(--gold); }
.cell--hole { background:repeating-linear-gradient(45deg,#0a141d,#0a141d 4px,#05101a 4px,#05101a 8px); border-style:dashed; }
.cell--frozen-area { outline:1px dashed var(--role-self); outline-offset:-2px; }
.cell--last-stand { outline:1px dashed var(--role-action); outline-offset:-2px; }
/* 可选格：只给光标的轻微暗示，不刷虚线框；区域模式整片由预览层表达。 */
.cell--legal { cursor:crosshair; }
.cell--legal:hover { background:color-mix(in srgb,var(--role-action) 18%,var(--cell-bg)); }
.board--area .cell--legal::after,.board--area .cell--preview::after,.board--area .cell--selected::after { content:none; }
/* 点船类目标：保留一格一条轻量实线轮廓，几艘船各自独立，不合成整片范围。 */
.cell--preview::after,.cell--selected::after { content:''; position:absolute; z-index:3; inset:2px; border:1.5px solid #9ef0cf; border-radius:5px; pointer-events:none; }
.cell--preview::after { border-style:dashed; border-color:#c8f5e3; }
.cell__badge { position:absolute; left:2px; top:2px; z-index:2; padding:1px 2px; border-radius:3px; font-size:9px; line-height:1; background:#122333; color:#9ee6fa; pointer-events:none; }
.cell__badge--trap { top:auto; bottom:2px; color:#d1a1ff; background:#2a1840; font-size:12px; }
.board-cell-hint { position:fixed; z-index:260; width:270px; max-width:calc(100vw - 24px); max-height:calc(100dvh - 24px); overflow:hidden; box-sizing:border-box; padding:12px 14px; border:1px solid var(--panel-line,#666189); border-radius:10px; background:var(--panel,#151a30); box-shadow:0 10px 32px #0008; color:var(--text-primary,#eef0ff); pointer-events:none; }
.board-cell-hint small { color:var(--text-tertiary); font-size:10px; }
.board-cell-hint__item { margin-top:6px; }
.board-cell-hint__item b { font-size:13px; }
.board-cell-hint__item p { margin:4px 0 0; font-size:12px; line-height:1.6; color:var(--text-secondary,var(--text-primary)); }
@media(prefers-reduced-motion:reduce) { .cell { transition:none; } }

@media (max-width: 719px) {
  .board__grid {
    --gap: 2px;
    --pad: 5px;
  }
}
@media (max-width: 719px) {
  .board {
    gap: 4px;
  }

  .board__head {
    gap: 6px;
  }

  .board__title {
    font-size: 11px;
    letter-spacing: 0.1em;
  }

  .board__subtitle {
    font-size: 10.5px;
  }
}
</style>
