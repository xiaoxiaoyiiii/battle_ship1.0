<script setup lang="ts">
/**
 * 已授权皮肤用 Codex 的 SkinCardFace 动态卡面，否则回退默认卡图 <img>。
 * skinId 只能来自己方图鉴 selected_skin 或公开载荷 skin_id；对手未出的牌不要挂本组件。
 * 无皮肤时根元素就是原来的 <img>，class/style/aria 等原样透传，既有布局不变。
 */
import { computed } from 'vue'
import SkinCardFace from './skins/SkinCardFace.vue'
import type { SkinFaceContext } from './skins/skinMotion'
import { getSkin, normalizeSkinId, resolveCardArtUrl } from './skinArt'
import './card-face-art.css'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  name: string
  skinId?: string | null
  context?: SkinFaceContext
  alt?: string
  /** 与原 <img> 的 object-fit 对齐；皮肤卡面固定 2:3。 */
  fit?: 'contain' | 'cover'
  motion?: boolean
}>(), { skinId: null, context: 'hand', alt: '', fit: 'contain', motion: true })

const skin = computed(() => {
  const entry = getSkin(normalizeSkinId(props.skinId))
  return entry && entry.cardName === props.name ? entry : undefined
})
const fallback = computed(() => resolveCardArtUrl(props.name, null))
</script>

<template>
  <span
    v-if="skin"
    v-bind="$attrs"
    class="card-face-art card-face-art--skin"
    :class="`card-face-art--${fit}`"
    :data-skin-id="skin.skinId"
    :data-skin-tier="skin.tier"
  ><SkinCardFace :skin-id="skin.skinId" :context="context" :motion="motion" :alt="alt" /></span>
  <img v-else-if="fallback" v-bind="$attrs" :src="fallback" :alt="alt" />
</template>
