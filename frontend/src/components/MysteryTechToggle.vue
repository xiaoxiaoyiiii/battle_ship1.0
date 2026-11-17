<script setup lang="ts">
defineProps<{ modelValue: boolean; disabled?: boolean; testid: string }>()
defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()
</script>

<template>
  <label class="mystery-mode-toggle" :class="{ 'is-on': modelValue }">
    <span class="mystery-mode-toggle__sigil" aria-hidden="true">✧</span>
    <span class="mystery-mode-toggle__copy">
      <b>神秘科技大乱斗</b>
      <small>猜拳前挑科技 · 不启用禁牌和突变</small>
    </span>
    <input type="checkbox" role="switch" :checked="modelValue" :disabled="disabled"
      :data-testid="testid" aria-label="开启神秘科技大乱斗"
      @change="$emit('update:modelValue', ($event.target as HTMLInputElement).checked)">
  </label>
</template>

<style scoped>
.mystery-mode-toggle { display: flex; align-items: center; gap: 12px; min-width: 0; padding: 13px 14px; border: 1px solid var(--panel-line, #426073); border-radius: 10px; cursor: pointer; }
.mystery-mode-toggle.is-on { border-color: #55d7e6; background: color-mix(in srgb, #35a5be 12%, transparent); }
.mystery-mode-toggle__sigil { color: var(--accent, #5bdce8); font-size: 27px; }
.mystery-mode-toggle__copy { display: grid; gap: 4px; flex: 1; min-width: 0; }
.mystery-mode-toggle b { color: var(--text-primary); font-size: 14px; }
.mystery-mode-toggle small { color: var(--text-secondary); font-size: 11px; line-height: 1.5; }
.mystery-mode-toggle input { appearance: none; width: 42px; height: 24px; border: 1px solid var(--panel-line, #496274); border-radius: 20px; background: var(--surface-void, #0b1826); flex-shrink: 0; margin: 0; cursor: pointer; }
.mystery-mode-toggle input::before { content: ''; display: block; width: 16px; height: 16px; border-radius: 50%; margin: 3px; background: var(--text-secondary); }
.mystery-mode-toggle input:checked { background: #227a91; border-color: #65e6ef; }
.mystery-mode-toggle input:checked::before { background: #d7fbff; transform: translateX(17px); }
.mystery-mode-toggle input:focus-visible { outline: 2px solid var(--text-primary); outline-offset: 4px; }
.mystery-mode-toggle input:disabled { opacity: .45; cursor: default; }
</style>
