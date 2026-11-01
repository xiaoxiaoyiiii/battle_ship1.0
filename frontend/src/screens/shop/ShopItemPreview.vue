<script setup lang="ts">
import { computed } from 'vue'
import AppProfileBackground from '../../components/AppProfileBackground.vue'
import AvatarStack from '../../components/AvatarStack.vue'
import TitleBadge from '../../components/TitleBadge.vue'
import { POINTER_EFFECTS } from '../../stores/cosmetics'
import type { ShopItem } from '../../stores/shop'
import { useUiStore } from '../../stores/ui'

/**
 * 商店效果预览只消费商品自己的 kind + id，复用已经在名片和全局装饰里
 * 用过的组件。没有对应渲染器时留一句「暂无预览」，不猜测效果。
 */
const props = defineProps<{ item: ShopItem }>()

const ui = useUiStore()

type PreviewKind = 'frame' | 'card_bg' | 'profile_bg' | 'pointer_effect' | 'title_effect' | 'unsupported'

const POINTER_PREVIEW = new Set<string>(
  POINTER_EFFECTS.map((entry) => entry.id).filter((id) => id !== 'none'),
)
const TITLE_FX = new Set(['none', 'glint', 'pulse', 'orbit', 'spark', 'prism'])

/** 与名片编辑器里 data-bg 色板一致，商店只拿来做一小张名片。 */
const CARD_BG_PAINT: Record<string, string> = {
  deep: 'linear-gradient(150deg, #1d466e, #091521 80%)',
  graphite: 'linear-gradient(150deg, #37414d, #101720 80%)',
  cyber: 'linear-gradient(150deg, #5b2f90, #102d4b 80%)',
  lava: 'linear-gradient(150deg, #8b3d29, #241113 80%)',
  dusk: 'linear-gradient(150deg, #6b477b, #171529 80%)',
  aurora: 'linear-gradient(150deg, #226d67, #0b2230 80%)',
  shoal: 'linear-gradient(150deg, #8d7553, #201a18 80%)',
  storm: 'linear-gradient(150deg, #3d4c5d, #111722 80%)',
  abyss: 'linear-gradient(150deg, #1d283d, #02050b 80%)',
  molten_gold: 'linear-gradient(150deg, #6b4b21, #18100b 80%)',
  starfield: 'radial-gradient(circle at 70% 24%, rgb(238 201 111 / 25%), transparent 4%), radial-gradient(circle at 24% 64%, rgb(111 224 244 / 22%), transparent 5%), linear-gradient(150deg, #182b5e, #060a18 80%)',
  season_deep_1: 'linear-gradient(150deg, #1d7691, #071522 80%)',
  kelp_green: 'linear-gradient(150deg, #205c55, #102b2f 80%)',
  moonlit: 'linear-gradient(150deg, #2b4c83, #091329 80%)',
  coral_dawn: 'linear-gradient(150deg, #925067, #241321 80%)',
  abyssal_grid: 'linear-gradient(rgb(201 162 76 / 8%) 1px, transparent 1px), linear-gradient(90deg, rgb(201 162 76 / 8%) 1px, transparent 1px), linear-gradient(150deg, #16131c, #060a12 80%)',
}

const POINTER_SPOTS = [
  { kind: 'trail', left: '24%', top: '70%', angle: '-16deg', delay: '0s' },
  { kind: 'trail', left: '42%', top: '56%', angle: '-10deg', delay: '0.18s' },
  { kind: 'trail', left: '58%', top: '44%', angle: '-6deg', delay: '0.36s' },
  { kind: 'burst', left: '74%', top: '34%', angle: '0deg', delay: '0.12s' },
]

function normalizeKind(kind: string): string {
  return kind.trim().toLowerCase().replace(/[\s-]+/g, '_')
}

function resolveKind(kind: string): PreviewKind {
  switch (normalizeKind(kind)) {
    case 'frame':
    case 'avatar_frame':
      return 'frame'
    case 'card_bg':
    case 'card_background':
      return 'card_bg'
    case 'profile_bg':
    case 'background':
    case 'profile_background':
      return 'profile_bg'
    case 'pointer':
    case 'pointer_effect':
    case 'pointer_fx':
      return 'pointer_effect'
    case 'title_effect':
    case 'title_fx':
      return 'title_effect'
    default:
      return 'unsupported'
  }
}

const itemId = computed(() => props.item.id.trim())
const kind = computed(() => (itemId.value ? resolveKind(props.item.kind) : 'unsupported'))
const pointerKnown = computed(() => POINTER_PREVIEW.has(itemId.value))
const titleKnown = computed(() => TITLE_FX.has(itemId.value))

const motionReduced = computed(() => {
  if (ui.motion === 'reduced') return true
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
})

const cardStyle = computed(() => {
  const paint = CARD_BG_PAINT[itemId.value] || 'linear-gradient(150deg, #1d466e, #091521 80%)'
  if (itemId.value === 'abyssal_grid') {
    return { background: paint, backgroundSize: '24px 24px, 24px 24px, auto' }
  }
  return { background: paint }
})

</script>

<template>
  <div class="shop-item-preview" :data-preview-kind="kind" data-testid="shop-item-preview">
    <div v-if="kind === 'frame'" class="shop-item-preview__stage shop-item-preview__stage--frame" data-testid="shop-preview-frame">
      <AvatarStack :frame="itemId" size="lg" fallback="⚓" alt="" />
    </div>

    <div
      v-else-if="kind === 'card_bg'"
      class="shop-item-preview__card"
      :data-bg="itemId"
      :style="cardStyle"
      data-testid="shop-preview-card-bg"
    >
      <div class="shop-item-preview__card-cover"></div>
      <div class="shop-item-preview__card-row">
        <AvatarStack frame="none" size="sm" fallback="⚓" alt="" />
        <div>
          <strong>名片</strong>
          <span>{{ item.name }}</span>
        </div>
      </div>
    </div>

    <div v-else-if="kind === 'profile_bg'" class="shop-item-preview__stage shop-item-preview__stage--scene" data-testid="shop-preview-profile-bg">
      <AppProfileBackground :preview-id="itemId" />
      <span class="shop-item-preview__scene-label">{{ item.name }}</span>
    </div>

    <div
      v-else-if="kind === 'pointer_effect' && pointerKnown"
      class="shop-item-preview__stage shop-item-preview__stage--pointer"
      :class="{ 'is-still': motionReduced }"
      data-testid="shop-preview-pointer"
      aria-hidden="true"
    >
      <span
        v-for="spot in POINTER_SPOTS"
        :key="spot.kind + spot.left"
        class="shop-item-preview__spot"
        :style="{ left: spot.left, top: spot.top }"
      >
        <span
          class="global-pointer-effects__fx"
          :class="[`global-pointer-effects__fx--${spot.kind}`, `global-pointer-effects__fx--${itemId}`]"
          :style="{ left: '0px', top: '0px', '--pointer-angle': spot.angle, animationDelay: spot.delay }"
        ></span>
      </span>
    </div>
    <p v-else-if="kind === 'pointer_effect' && itemId === 'none'" class="shop-item-preview__note" data-testid="shop-preview-pointer">这件特效不会留下指针轨迹。</p>

    <div v-else-if="kind === 'title_effect' && titleKnown" class="shop-item-preview__stage shop-item-preview__stage--title" data-testid="shop-preview-title">
      <TitleBadge name="领航员" :title-fx-id="itemId" />
    </div>

    <p v-else class="shop-item-preview__missing" data-testid="shop-preview-unsupported">暂无预览</p>
  </div>
</template>

<style scoped>
.shop-item-preview { min-width: 0; }
.shop-item-preview__stage {
  display: grid;
  place-items: center;
  min-height: 148px;
  overflow: hidden;
  border-radius: 10px;
  background: rgb(5 12 24 / 55%);
}
.shop-item-preview__stage--scene {
  position: relative;
  height: 168px;
  isolation: isolate;
}
.shop-item-preview__scene-label {
  position: absolute;
  z-index: 6;
  left: 12px;
  bottom: 10px;
  color: #f4fbff;
  font-size: 13px;
  font-weight: 700;
  text-shadow: 0 1px 8px rgb(0 0 0 / 55%);
}
.shop-item-preview__stage--pointer { position: relative; }
.shop-item-preview__spot {
  position: absolute;
  width: 0;
  height: 0;
  transform: scale(2.4);
  transform-origin: center;
}
.shop-item-preview__card {
  position: relative;
  display: grid;
  align-content: end;
  min-height: 148px;
  overflow: hidden;
  padding: 12px;
  border-radius: 10px;
  color: #f4fbff;
}
.shop-item-preview__card-cover {
  position: absolute;
  inset: 0 0 auto;
  height: 46%;
  background: linear-gradient(120deg, rgb(255 255 255 / 16%), rgb(0 0 0 / 18%));
}
.shop-item-preview__card-row {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}
.shop-item-preview__card-row strong,
.shop-item-preview__card-row span { display: block; }
.shop-item-preview__card-row strong { font-size: 14px; }
.shop-item-preview__card-row span { color: rgb(244 251 255 / 78%); font-size: 12px; }
.shop-item-preview__note,
.shop-item-preview__missing {
  margin: 0;
  padding: 28px 12px;
  border: 1px dashed var(--border-strong);
  border-radius: 10px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
  text-align: center;
}
.shop-item-preview__stage--pointer:not(.is-still) :deep(.global-pointer-effects__fx),
.shop-item-preview__stage--pointer:not(.is-still) :deep(.global-pointer-effects__fx::before),
.shop-item-preview__stage--pointer:not(.is-still) :deep(.global-pointer-effects__fx::after) {
  animation-iteration-count: infinite;
}
.shop-item-preview__stage--pointer.is-still :deep(.global-pointer-effects__fx),
.shop-item-preview__stage--pointer.is-still :deep(.global-pointer-effects__fx::before),
.shop-item-preview__stage--pointer.is-still :deep(.global-pointer-effects__fx::after) {
  animation: none;
  opacity: 0.92;
}
@media (prefers-reduced-motion: reduce) {
  .shop-item-preview__stage--pointer :deep(.global-pointer-effects__fx),
  .shop-item-preview__stage--pointer :deep(.global-pointer-effects__fx::before),
  .shop-item-preview__stage--pointer :deep(.global-pointer-effects__fx::after) {
    animation: none;
    opacity: 0.92;
  }
}
</style>
