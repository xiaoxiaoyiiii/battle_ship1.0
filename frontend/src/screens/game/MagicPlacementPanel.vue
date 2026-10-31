<script setup lang="ts">
import { cardArtUrl } from '../../cards/cardArt'
import type { Point } from './view'

defineProps<{
  request: Record<string, unknown>
  kind: string
  title: string
  hint: string
  selected: Point | null
  busy: boolean
  error: string
  compact: boolean
  tight: boolean
}>()
const emit = defineEmits<{ (event: 'confirm'): void; (event: 'cancel'): void }>()
</script>

<template>
  <section class="game-target game-placement battle-prompt" :class="{ 'is-compact': compact, 'is-tight': tight }" data-testid="game-placement" aria-labelledby="magic-placement-title" role="region">
    <header class="battle-prompt__head">
      <div><p class="battle-prompt__context">部署战舰</p><h2 id="magic-placement-title">{{ title }} · 选择部署位置</h2></div>
      <img v-if="cardArtUrl(title)" class="battle-prompt__card-art" :src="cardArtUrl(title)!" alt="" draggable="false" />
    </header>
    <div class="game-target__main">
      <p class="game-target__hint">{{ hint }}</p>
      <p class="game-target__selected battle-prompt__progress" data-testid="magic-placement-progress" role="status">已放置 {{ request.placed ?? 0 }} / {{ request.total ?? request.remaining }}，剩余 {{ request.remaining }} 艘</p>
      <p v-if="error" class="battle-prompt__error" data-testid="magic-placement-error" role="alert">{{ error }}</p>
      <p class="game-placement__selection" data-testid="magic-placement-selected" role="status">{{ selected ? '已选 ' + String.fromCharCode(65 + selected.x) + (selected.y + 1) + '，确认后部署一艘。' : '请点击自己海域中的合法格。' }}</p>
    </div>
    <footer class="game-target__row game-target__actions">
      <button type="button" class="button button--primary" data-testid="magic-placement-confirm" :disabled="busy || !selected" @click="emit('confirm')">{{ busy ? '正在提交…' : '确认部署' }}</button>
      <button type="button" class="button button--ghost" data-testid="magic-placement-cancel" :disabled="busy" @click="emit('cancel')">{{ kind === 'last_stand' ? '交给系统放置' : '放弃剩余放置' }}</button>
    </footer>
  </section>
</template>

<style scoped>
.game-placement.game-target { left:auto; right:16px; top:104px; width:292px; max-height:calc(100dvh - 120px); padding:16px; gap:12px; border:1px solid var(--prompt-line); }
.game-placement .battle-prompt__head h2 { font-size:18px; }
.game-placement .battle-prompt__card-art { width:40px; height:60px; flex-basis:40px; }
.game-placement .game-target__main { display:flex; flex-direction:column; gap:10px; }
.game-placement__selection { margin:0; color:var(--prompt-gold); font-size:13px; line-height:1.6; }
.game-placement footer { display:grid; grid-template-columns:1fr; gap:8px; width:100%; }
.game-placement.is-compact .battle-prompt__head { margin:0; padding:0 0 5px; gap:8px; }
.game-placement.is-compact .battle-prompt__context { display:none; }
.game-placement.is-compact .battle-prompt__head h2 { margin:0; font-size:15px; line-height:1.3; }
.game-placement.is-compact .battle-prompt__card-art { display:none; }
.game-placement.is-compact .game-target__main { gap:4px; }
.game-placement.is-compact .game-target__hint { font-size:12px; line-height:1.5; }
.game-placement.is-compact .battle-prompt__progress { margin:0; padding:5px 8px; min-height:0; font-size:11px; }
.game-placement.is-compact .game-placement__selection { font-size:12px; }
.game-placement.is-compact footer { grid-template-columns:1fr 1fr; padding-top:4px; }
.game-placement.is-compact .button { min-height:40px; padding:6px 9px; font-size:12px; }
.game-placement.is-compact .battle-prompt__error { font-size:12px; line-height:1.5; }
.game-placement.is-tight footer { grid-template-columns:1fr; }
</style>
