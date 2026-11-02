<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { mutationSelectionError, type WeeklyMutations } from '../../stores/mutations'

const props = defineProps<{ open: boolean; selected: string[]; weekly: WeeklyMutations | null }>()
const emit = defineEmits<{ (event: 'close'): void; (event: 'confirm', ids: string[]): void }>()
const draft = ref<string[]>([])
const group = ref('')
const labels: Record<string, string> = { ATK: '战斗火力', SPEED: '魔法节奏', HAND: '手牌补给', TEMPO: '舰队与回合', FOG: '情报与迷雾' }
const groups = computed(() => [...new Set(props.weekly?.catalog.map(e => e.group) ?? [])])
const entries = computed(() => props.weekly?.catalog.filter(e => e.group === group.value) ?? [])
const error = computed(() => mutationSelectionError(draft.value, props.weekly))
watch(() => props.open, open => { if (open) { draft.value = [...props.selected]; group.value = groups.value[0] ?? '' } }, { immediate: true })
function disabledReason(id: string): string {
  return draft.value.includes(id) ? '' : mutationSelectionError([...draft.value, id], props.weekly)
}
function confirm(): void { if (!error.value) emit('confirm', [...draft.value]) }
</script>
<template>
  <AppOverlay id="room-mutation-picker" :open="open" transition-name="lp-picker" labelledby="room-mutations-title" @close="emit('close')">
    <section class="lp-picker">
      <header class="lp-picker__head"><div><h2 id="room-mutations-title">选择本局突变</h2><p>按玩法分组选择，同组及冲突词条不可同时启用。</p></div><button class="lp-link" aria-label="关闭突变选择" @click="emit('close')">关闭</button></header>
      <nav class="lp-picker__groups" aria-label="突变分组"><button v-for="name in groups" :key="name" :class="{ 'is-selected': group === name }" :data-testid="'room-mutations-group-' + name" :aria-pressed="group === name" @click="group = name">{{ labels[name] || name }}</button></nav>
      <div class="lp-picker__options"><label v-for="entry in entries" :key="entry.id" class="lp-mutation" :class="{ 'is-disabled': !!disabledReason(entry.id) }"><input v-model="draft" :value="entry.id" type="checkbox" :data-testid="'room-mutation-' + entry.id" :disabled="!!disabledReason(entry.id)"><span><b>{{ entry.name }}</b><small>{{ entry.description }}</small><small v-if="disabledReason(entry.id)" class="lp-conflict">{{ disabledReason(entry.id) }}</small></span></label><p v-if="!entries.length" class="lp-empty">词条尚未载入，请关闭后刷新大厅重试。</p></div>
      <footer class="lp-picker__foot"><div class="lp-picker__selection"><b>已选 {{ draft.length }} 条</b><span v-if="!draft.length">不选则使用普通规则。</span><button v-for="id in draft" :key="id" class="lp-chip" @click="draft = draft.filter(item => item !== id)">{{ weekly?.catalog.find(e => e.id === id)?.name || id }} ×</button></div><p v-if="error" class="lp-conflict" role="alert">{{ error }}</p><div class="lp-dialog-actions"><button class="button button--ghost" data-testid="room-mutations-cancel" @click="emit('close')">取消</button><button class="button lp-primary" data-testid="room-mutations-confirm" :disabled="!!error" @click="confirm">确认选择</button></div></footer>
    </section>
  </AppOverlay>
</template>
