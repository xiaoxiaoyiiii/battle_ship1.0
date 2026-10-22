<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useWallpaperStore } from '../stores/wallpaper'

/**
 * The applied wallpaper layer plus its one play/pause control.
 *
 * Rendered once by the shell so every screen has the same background. Without an
 * applied choice the component renders nothing, which keeps the screenshot
 * baselines of the shipped screens untouched.
 */
const wallpaper = useWallpaperStore()
const video = ref<HTMLVideoElement | null>(null)

const choice = computed(() => wallpaper.applied)
const isVideo = computed(() => choice.value?.kind === 'video')

watch(
  [() => wallpaper.applied?.id, () => wallpaper.playing],
  async () => {
    await nextTick()
    const element = video.value
    if (!element) return
    if (wallpaper.playing) {
      try {
        await element.play()
      } catch {
        // Autoplay can be refused before a user gesture; the control below lets
        // the player start it explicitly instead of showing a frozen frame.
      }
    } else {
      element.pause()
    }
  },
)
</script>

<template>
  <div v-if="choice" class="app-wallpaper" data-testid="wallpaper-layer" aria-hidden="true">
    <video
      v-if="isVideo"
      ref="video"
      class="app-wallpaper__media"
      data-testid="wallpaper-media"
      :src="choice.mediaUrl"
      :poster="choice.previewUrl || undefined"
      muted
      loop
      playsinline
      autoplay
    ></video>
    <img
      v-else
      class="app-wallpaper__media"
      data-testid="wallpaper-media"
      :src="choice.mediaUrl"
      alt=""
      decoding="async"
    />
    <div class="app-wallpaper__scrim"></div>
  </div>

  <div v-if="choice" class="app-wallpaper__controls" data-testid="wallpaper-controls">
    <span class="app-wallpaper__title" data-testid="wallpaper-title">{{ choice.title }}</span>
    <button
      type="button"
      class="app-wallpaper__button"
      data-testid="wallpaper-toggle"
      :aria-pressed="wallpaper.playing"
      :title="wallpaper.playing ? '暂停壁纸' : '播放壁纸'"
      @click="wallpaper.togglePlay()"
    >
      {{ wallpaper.playing ? '暂停' : '播放' }}
    </button>
    <button
      type="button"
      class="app-wallpaper__button"
      data-testid="wallpaper-clear"
      title="关闭壁纸"
      @click="wallpaper.clear()"
    >
      关闭
    </button>
  </div>
</template>

<style scoped>
.app-wallpaper {
  position: fixed;
  inset: 0;
  z-index: var(--z-wallpaper);
  overflow: hidden;
  background: #05070f;
}

.app-wallpaper__media {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.app-wallpaper__scrim {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(5, 7, 18, 0.35), rgba(5, 7, 18, 0.65));
}

.app-wallpaper__controls {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 40;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid var(--border-strong, color-mix(in srgb, var(--role-action) 40%, transparent));
  border-radius: 999px;
  background: rgba(8, 11, 24, 0.78);
  backdrop-filter: blur(4px);
}

.app-wallpaper__title {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted, var(--text-tertiary));
  font-size: 12px;
}

.app-wallpaper__button {
  padding: 4px 10px;
  border: 1px solid color-mix(in srgb, var(--role-action) 40%, transparent);
  border-radius: 999px;
  background: transparent;
  color: var(--text, var(--text-primary));
  font-size: 11px;
  cursor: pointer;
}

.app-wallpaper__button:hover {
  border-color: color-mix(in srgb, var(--gold) 70%, transparent);
}
</style>
