<script setup lang="ts">
import AppOverlay from '../../components/AppOverlay.vue'
import { cardArtUrl } from '../../cards/cardArt'
import type { CardLike } from './view'
withDefaults(defineProps<{ card: CardLike; reason: string; canDiscard: boolean; discardReason?: string; pending?: boolean }>(), { discardReason: '', pending: false })
const emit = defineEmits<{ close: []; use: []; discard: [] }>()
</script>

<template>
  <AppOverlay id="mobile-card-reader" :priority="150" labelledby="mobile-card-name" @close="emit('close')">
    <section class="mobile-card-reader" data-testid="game-card-detail">
      <header>
        <div><small>魔法卡 · 速阶 {{ card.speed }}</small><h2 id="mobile-card-name">{{ card.name }}</h2></div>
        <button type="button" class="button button--ghost" data-testid="game-card-detail-close" aria-label="关闭卡牌阅读" @click="emit('close')">×</button>
      </header>
      <div class="mobile-card-reader__body">
      <div class="mobile-card-reader__content">
        <img v-if="cardArtUrl(card.name)" :src="cardArtUrl(card.name)!" :alt="card.name + '完整卡面'" />
        <article><span class="mobile-card-reader__type">{{ card.type }}</span><h3>效果说明</h3><p>{{ card.description || '暂无效果说明' }}</p></article>
      </div>
      <p v-if="reason" class="mobile-card-reader__reason" data-testid="game-card-detail-reason">{{ reason }}</p>
      <p v-if="canDiscard" class="mobile-card-reader__discard-hint">无需发动这张牌，确认弃置即可获得 2 次攻击。</p>
      </div>
      <footer>
        <button v-if="canDiscard" type="button" class="button button--ghost" data-testid="game-papal-discard" :disabled="pending || Boolean(discardReason)" @click="emit('discard')">弃置此卡 · 攻击 +2</button>
        <button type="button" class="button button--primary" data-testid="game-card-detail-use" :disabled="Boolean(reason) || pending" @click="emit('use')">使用此卡</button>
      </footer>
    </section>
  </AppOverlay>
</template>

<style scoped>
:global(.app-overlay[data-overlay='mobile-card-reader'] .app-overlay__panel) { width:min(620px,calc(100vw - 24px)); padding:0; max-height:calc(100dvh - 24px - env(safe-area-inset-top) - env(safe-area-inset-bottom)); overflow:hidden; }
.mobile-card-reader { display:flex; flex-direction:column; max-height:calc(100dvh - 24px - env(safe-area-inset-top) - env(safe-area-inset-bottom)); padding:14px; color:#e4ecf6; background:linear-gradient(150deg,#17243a,#0c1526); }
header { display:flex; flex:0 0 auto; align-items:center; justify-content:space-between; gap:12px; }
header small,.mobile-card-reader__type { color:#a89bda; font-size:13px; }
header h2 { margin:4px 0 0; font-size:25px; }
header button { width:44px; height:44px; font-size:24px; }
.mobile-card-reader__body { flex:1 1 auto; min-height:0; overflow-y:auto; overscroll-behavior:contain; }
.mobile-card-reader__content { display:grid; grid-template-columns:1fr; gap:18px; margin-top:16px; }
.mobile-card-reader__content img { display:block; width:min(62vw,240px); max-height:36dvh; object-fit:contain; margin:auto; filter:drop-shadow(0 12px 18px #0008); }
article { padding:14px; border:1px solid #b49bec30; border-radius:12px; background:#080e1a66; }
article h3 { margin:8px 0; font-size:14px; color:#a9c7df; }
article p { margin:0; white-space:pre-line; line-height:1.75; font-size:16px; }
.mobile-card-reader__reason { padding:10px 12px; border-left:2px solid #d3b878; background:#d3b8780d; color:#e4ca91; font-size:14px; line-height:1.5; }
.mobile-card-reader__discard-hint { color:#e4ca91; font-size:13px; line-height:1.5; }
footer { display:flex; flex:0 0 auto; gap:10px; padding-top:10px; background:#0c1526; margin-top:8px; }
footer .button { flex:1; min-width:0; min-height:46px; padding:8px; font-size:14px; }
@media(orientation:landscape) { .mobile-card-reader__content { grid-template-columns:minmax(120px,180px) 1fr; align-items:start; }.mobile-card-reader__content img { width:100%; max-height:54dvh; } }
</style>
