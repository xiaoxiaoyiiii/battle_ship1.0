<script setup lang="ts">
import { computed, ref } from 'vue'
const props = withDefaults(defineProps<{ pool: string[]; selection: string[]; quota: number; disabled?: boolean }>(), { disabled: false })
const emit = defineEmits<{ (event: 'change', selection: string[]): void }>()
const query = ref('')
const visible = computed(() => props.pool.filter(name => name !== '失灵！' && name.includes(query.value.trim())))
function toggle(name: string): void {
  if (props.disabled || !props.pool.includes(name) || name === '失灵！') return
  const selected = props.selection.includes(name)
  if (!selected && props.selection.length >= props.quota) return
  emit('change', selected ? props.selection.filter(value => value !== name) : [...props.selection, name])
}
</script>
<template>
  <div class="ban-picker">
    <p class="ban-picker__count" data-testid="ban-selected-count">已选 {{ selection.length }} / {{ quota }} <span>·「失灵！」不可 Ban</span></p>
    <input v-model="query" type="search" class="ban-picker__search" placeholder="搜索卡名" aria-label="搜索可 Ban 卡牌" />
    <div class="ban-picker__grid" data-testid="ban-card-pool" aria-label="可 Ban 卡牌">
      <button v-for="name in visible" :key="name" type="button" class="ban-picker__card" :class="{ 'is-selected': selection.includes(name) }" :data-testid="'ban-card-' + name" :aria-pressed="selection.includes(name)" :disabled="disabled || (!selection.includes(name) && selection.length >= quota)" @click="toggle(name)"><span>{{ name }}</span><b aria-hidden="true">{{ selection.includes(name) ? '✓' : '+' }}</b></button>
    </div>
    <p v-if="!visible.length" role="status">没有符合搜索的卡牌。</p>
  </div>
</template>
<style scoped>
.ban-picker { display: grid; gap: 12px; min-width: 0; }
.ban-picker__count { margin: 0; color: var(--gold-strong); font-size: 14px; }
.ban-picker__count span { color: var(--text-muted); font-size: 12px; }
.ban-picker__search { width: 100%; min-width: 0; padding: 10px 12px; box-sizing: border-box; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface-deck); color: var(--text); }
.ban-picker__grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; max-height: min(42dvh,340px); overflow-y: auto; padding: 2px; }
.ban-picker__card { display: flex; align-items: center; justify-content: space-between; gap: 6px; min-height: 44px; padding: 9px 10px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface-deck); color: var(--text); cursor: pointer; font-size: 13px; text-align: left; overflow-wrap: anywhere; }
.ban-picker__card b { color: var(--text-muted); }
.ban-picker__card.is-selected { border-color: var(--gold-strong); background: var(--gold-soft); color: var(--gold-strong); }
.ban-picker__card:disabled:not(.is-selected) { opacity: .45; cursor: not-allowed; }
@media(max-width:600px) { .ban-picker__grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
</style>
