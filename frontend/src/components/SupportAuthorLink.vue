<script setup lang="ts">
import { GITHUB_URL } from '../support/githubSupport'

withDefaults(defineProps<{ compact?: boolean; testId?: string }>(), {
  compact: false, testId: 'support-author-link',
})
</script>

<template>
  <a :href="GITHUB_URL" target="_blank" rel="noopener noreferrer" class="support-author"
    :class="{ 'support-author--compact': compact }" :data-testid="testId">
    <svg class="support-author__star" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="m12 3 2.8 5.7 6.3.9-4.5 4.4 1.1 6.2-5.7-3-5.7 3 1.1-6.2-4.5-4.4 6.3-.9L12 3Z" />
    </svg>
    <span class="support-author__copy"><strong>喜欢战舰棋？</strong><span>去 GitHub 为作者点一颗星</span></span>
    <span class="support-author__action">支持作者</span>
  </a>
</template>

<style scoped>
.support-author { display:flex; align-items:center; gap:12px; padding:16px 18px; color:var(--text); border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface-deck); text-decoration:none; transition:border-color .18s, background .18s; }
.support-author:hover { border-color:var(--gold); background:var(--surface-raised); }
.support-author:focus-visible { outline:2px solid var(--role-action); outline-offset:4px; }
.support-author__star { width:26px; height:26px; flex:none; color:var(--gold); }
.support-author__star path { stroke:currentColor; stroke-width:1.6; stroke-linejoin:round; fill:var(--gold-soft); }
.support-author__copy { display:flex; flex-direction:column; gap:4px; min-width:0; font-size:12px; line-height:1.5; color:var(--text-secondary); }
.support-author__copy strong { color:var(--text); font-size:14px; font-weight:650; }
.support-author__action { margin-left:auto; flex:none; font-size:12px; color:var(--text-secondary); }
.support-author--compact { padding:12px 14px; }
@media(max-width:420px) { .support-author__action { display:none; } }
@media(prefers-reduced-motion:reduce) { .support-author { transition:none; } }
</style>
