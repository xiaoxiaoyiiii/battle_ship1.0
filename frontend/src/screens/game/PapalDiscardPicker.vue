<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { cardArtUrl } from '../../cards/cardArt'
import type { CardLike } from './view'

const props = defineProps<{ cards: CardLike[]; attacks: number; pending: boolean; error: string }>()
const emit = defineEmits<{ confirm: [indices: number[]]; close: [] }>()
const selected = ref<number[]>([]), changed = ref(false)
const gained = computed(() => selected.value.length * 2)
function toggle(index: number): void {
  if (props.pending) return
  selected.value = selected.value.includes(index) ? selected.value.filter(value => value !== index) : [...selected.value, index]
}
watch(() => props.cards.map(card => card.name).join('\0'), () => {
  if (!props.pending && selected.value.length) { selected.value = []; changed.value = true }
})
</script>
<template>
  <section class="game-papal-picker battle-prompt">
    <header><h2 id="game-papal-title">弃牌换攻击</h2><button type="button" class="button button--ghost" data-testid="game-papal-cancel" :disabled="pending" @click="emit('close')">取消</button></header>
    <p>可多选手牌，每弃置 1 张获得 2 次攻击。选好后一次确认。</p>
    <div class="game-papal-picker__tools"><span>手牌 {{ cards.length }} 张</span><button type="button" class="button button--ghost" :disabled="pending || !cards.length" @click="selected = selected.length === cards.length ? [] : cards.map((_,i) => i)">{{ selected.length === cards.length && cards.length ? '取消全选' : '全选' }}</button></div>
    <div class="game-papal-cards">
      <button v-for="(card,index) in cards" :key="index" type="button" :data-testid="'game-papal-card-' + index" :disabled="pending" :aria-pressed="selected.includes(index)" :class="{ 'is-selected': selected.includes(index) }" @click="toggle(index)">
        <img v-if="cardArtUrl(card.name)" :src="cardArtUrl(card.name)!" alt="" /><span><strong>{{ card.name }}</strong><small>速阶 {{ card.speed }} · {{ card.type }}</small><small>{{ selected.includes(index) ? '已选择 · 攻击 +2' : '点击选择' }}</small></span><b class="game-papal-check" aria-hidden="true">{{ selected.includes(index) ? '✓' : '+' }}</b>
      </button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p><p v-else-if="changed" role="status">手牌已更新，请重新选择。</p>
    <footer class="game-papal-picker__footer">
      <p aria-live="polite" data-testid="game-papal-summary">已选 <b>{{ selected.length }}</b> 张 · 攻击 <b>{{ attacks }} → {{ attacks + gained }}</b></p>
      <button type="button" class="button" data-testid="game-papal-confirm" :disabled="pending || !selected.length" @click="emit('confirm',[...selected].sort((a,b) => a-b))">{{ pending ? '正在弃牌…' : '弃置 ' + selected.length + ' 张 · 攻击 +' + gained }}</button>
    </footer>
  </section>
</template>
<style scoped>
.game-papal-picker { display:flex; flex-direction:column; padding:16px; max-height:78dvh; color:var(--prompt-text); }
header,.game-papal-picker__tools { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-shrink:0; }
h2 { margin:0; font-size:18px; }
p { margin:10px 0; font-size:13px; line-height:1.5; }
.game-papal-picker__tools { margin-bottom:10px; font-size:12px; }
.game-papal-picker__tools .button { min-height:32px; padding:4px 10px; font-size:12px; }
.game-papal-cards { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); min-height:0; gap:8px; overflow-y:auto; padding:2px; }
.game-papal-cards>button { position:relative; display:flex; align-items:center; gap:8px; min-width:0; padding:8px; border:1px solid var(--prompt-line); border-radius:8px; background:var(--prompt-deck); color:var(--prompt-text); text-align:left; cursor:pointer; }
.game-papal-cards>button:hover,.game-papal-cards>button:focus-visible { border-color:var(--prompt-cyan); }
.game-papal-cards>button.is-selected { border-color:var(--prompt-cyan); box-shadow:inset 0 0 0 1px var(--prompt-cyan); background:color-mix(in srgb,var(--prompt-cyan) 12%,var(--prompt-deck)); }
.game-papal-cards img { flex:0 0 40px; width:40px; height:60px; object-fit:contain; }
.game-papal-cards span { display:grid; flex:1; gap:4px; min-width:0; }
.game-papal-cards strong { font-size:14px; overflow-wrap:anywhere; }
.game-papal-cards small { font-size:11px; color:var(--prompt-gold); }
.game-papal-check { flex:0 0 16px; color:var(--prompt-cyan); text-align:center; }
.game-papal-picker__footer { flex-shrink:0; margin-top:12px; padding-top:4px; border-top:1px solid var(--prompt-line); }
.game-papal-picker__footer b { color:var(--prompt-cyan); }
.game-papal-picker__footer .button { width:100%; min-height:44px; }
@media(max-width:430px) { .game-papal-picker { padding:12px; max-height:82dvh; }.game-papal-cards>button { gap:6px; padding:6px; }.game-papal-cards img { flex-basis:32px; width:32px; height:48px; }.game-papal-cards strong { font-size:13px; }.game-papal-cards small { font-size:10px; } }
</style>
