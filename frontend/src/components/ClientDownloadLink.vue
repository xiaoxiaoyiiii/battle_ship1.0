<script setup lang="ts">
import { computed } from 'vue'
import { CLIENT_DOWNLOAD_URLS, isBattleshipClient, promoPlatform } from '../support/clientPromo'

const props = withDefaults(defineProps<{ compact?: boolean; testId?: string }>(), {
  compact: false, testId: 'client-download-link',
})

// 客户端壳内不显示下载入口（已经在客户端里了）。
const downloadUrl = computed(() => promoPlatform() === 'android'
  ? CLIENT_DOWNLOAD_URLS.android : CLIENT_DOWNLOAD_URLS.windows)
const platformLabel = computed(() => promoPlatform() === 'android' ? '手机版' : '电脑版')
const inClient = isBattleshipClient()
</script>

<template>
  <a v-if="!inClient" :href="downloadUrl" class="client-download"
    :class="{ 'client-download--compact': props.compact }" :data-testid="testId">
    <svg class="client-download__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 4v12M8 7h8M5 13a7 7 0 0 0 14 0M5 13H3m2 0a2 2 0 1 0 4 0m10 0a2 2 0 1 0-4 0m4 0h2" />
    </svg>
    <span class="client-download__copy"><strong>下载客户端</strong><span>登录领 500 徽记和专属头像框</span></span>
    <span class="client-download__action">{{ platformLabel }}下载</span>
  </a>
</template>

<style scoped>
.client-download { display:flex; align-items:center; gap:12px; padding:16px 18px; color:var(--text); border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface-deck); text-decoration:none; transition:border-color .18s, background .18s; }
.client-download:hover { border-color:var(--role-action); background:var(--surface-raised); }
.client-download:focus-visible { outline:2px solid var(--role-action); outline-offset:4px; }
.client-download__icon { width:26px; height:26px; flex:none; color:var(--role-action); }
.client-download__icon path { stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; }
.client-download__copy { display:flex; flex-direction:column; gap:4px; min-width:0; font-size:12px; line-height:1.5; color:var(--text-secondary); }
.client-download__copy strong { color:var(--text); font-size:14px; font-weight:650; }
.client-download__action { margin-left:auto; flex:none; font-size:12px; color:var(--text-secondary); }
.client-download--compact { padding:12px 14px; }
@media(max-width:420px) { .client-download__action { display:none; } }
@media(prefers-reduced-motion:reduce) { .client-download { transition:none; } }
</style>
