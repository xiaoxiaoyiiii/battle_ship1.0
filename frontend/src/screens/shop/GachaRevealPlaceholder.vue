<script setup lang="ts">
import type { GachaPull } from '../../stores/gachaTypes'

defineProps<{ results: GachaPull[] }>()
const emit = defineEmits<{ done: []; skip: [] }>()

function kindLabel(kind: string): string {
  if (kind === 'limited') return '限定皮肤'
  if (kind === 'legendary') return '传说皮肤'
  return '潮汐碎片'
}
</script>

<template>
  <div class="gacha-reveal" data-testid="gacha-reveal" role="dialog" aria-label="抽卡结果">
    <header>
      <h2>抽卡结果</h2>
      <p>这是占位展示。Codex 动画接入后会替换为翻开演出。</p>
    </header>
    <ol class="gacha-reveal__list">
      <li
        v-for="row in results"
        :key="row.index"
        class="gacha-reveal__item"
        :data-kind="row.kind"
        :data-testid="'gacha-reveal-item-' + row.index"
      >
        <span class="gacha-reveal__kind">{{ kindLabel(row.kind) }}</span>
        <strong>{{ row.cardName || '潮汐碎片 ×' + (row.shardsGained || 1) }}</strong>
        <em v-if="row.isNew" class="gacha-reveal__new">NEW</em>
        <span v-if="row.shardsGained" class="gacha-reveal__shards">+{{ row.shardsGained }} 碎片</span>
      </li>
    </ol>
    <div class="gacha-reveal__actions">
      <button type="button" class="button button--ghost" data-testid="gacha-reveal-skip" @click="emit('skip')">跳过</button>
      <button type="button" class="button button--primary" data-testid="gacha-reveal-done" @click="emit('done')">确定</button>
    </div>
  </div>
</template>

<style scoped>
.gacha-reveal { display: grid; gap: 14px; padding: 16px; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--surface-deck); }
.gacha-reveal h2 { margin: 0 0 4px; color: var(--text-primary); font-size: 18px; }
.gacha-reveal header p { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.gacha-reveal__list { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.gacha-reveal__item { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px; border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--surface-sea); color: var(--text-primary); font-size: 14px; }
.gacha-reveal__kind { color: var(--role-action); font-size: 11px; letter-spacing: 0.08em; }
.gacha-reveal__new { padding: 1px 6px; border-radius: 4px; background: var(--gold-soft, #d7b96333); color: var(--gold-strong); font-size: 10px; font-style: normal; letter-spacing: 0.08em; }
.gacha-reveal__shards { margin-left: auto; color: var(--gold-strong); font-variant-numeric: tabular-nums; font-size: 13px; }
.gacha-reveal__actions { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 390px) {
  .gacha-reveal { padding: 12px; }
  .gacha-reveal__item { font-size: 13px; }
}
</style>
