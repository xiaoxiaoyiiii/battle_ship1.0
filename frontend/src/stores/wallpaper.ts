import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Applied dynamic wallpaper (spec user story 2 / legacy wallpaper.js).
 *
 * The legacy page applied a wallpaper by pointing a background <video>/<img> at
 * the frozen media URL and remembering the choice in localStorage. This store is
 * the same behaviour inside the SPA:
 *
 * * GET /api/wallpapers lists playable local wallpapers (localhost only);
 * * the chosen row carries media_url (/api/wallpaper/media/<id>?v=<mtime>) and
 *   preview_url (/api/wallpaper/preview/<id>?v=<mtime>) from the server;
 * * the choice is persisted under one storage key and survives reloads, exactly
 *   like the legacy key the old settings screen wrote.
 *
 * Nothing is re-derived here: the media URL always comes from the server, so a
 * replaced file (same id, new mtime) changes the URL and busts the cache.
 */
export interface WallpaperChoice {
  id: string
  title: string
  kind: 'video' | 'image'
  mediaUrl: string
  previewUrl: string
}

export const WALLPAPER_STORAGE_KEY = 'battleship.wallpaper.v1'

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function readStored(): WallpaperChoice | null {
  const store = storage()
  if (!store) return null
  try {
    const raw = store.getItem(WALLPAPER_STORAGE_KEY)
    if (!raw) return null
    const data: unknown = JSON.parse(raw)
    if (!isObject(data)) return null
    const kind = data.kind === 'video' ? 'video' : data.kind === 'image' ? 'image' : null
    const mediaUrl = typeof data.mediaUrl === 'string' ? data.mediaUrl : ''
    if (!kind || !mediaUrl) return null
    return {
      id: typeof data.id === 'string' ? data.id : '',
      title: typeof data.title === 'string' && data.title ? data.title : '壁纸',
      kind,
      mediaUrl,
      previewUrl: typeof data.previewUrl === 'string' ? data.previewUrl : '',
    }
  } catch {
    return null
  }
}

export const useWallpaperStore = defineStore('wallpaper', () => {
  const applied = ref<WallpaperChoice | null>(readStored())
  const playing = ref(true)

  const hasWallpaper = computed(() => applied.value !== null)

  function write(choice: WallpaperChoice | null): void {
    const store = storage()
    if (!store) return
    try {
      if (choice) store.setItem(WALLPAPER_STORAGE_KEY, JSON.stringify(choice))
      else store.removeItem(WALLPAPER_STORAGE_KEY)
    } catch {
      // Private-mode storage failures must not break the settings screen.
    }
  }

  function apply(choice: WallpaperChoice): void {
    applied.value = {
      id: String(choice.id || ''),
      title: String(choice.title || '壁纸'),
      kind: choice.kind === 'video' ? 'video' : 'image',
      mediaUrl: String(choice.mediaUrl || ''),
      previewUrl: String(choice.previewUrl || ''),
    }
    playing.value = true
    write(applied.value)
  }

  function clear(): void {
    applied.value = null
    playing.value = true
    write(null)
  }

  function setPlaying(value: boolean): void {
    playing.value = value
  }

  function togglePlay(): void {
    playing.value = !playing.value
  }

  return { applied, playing, hasWallpaper, apply, clear, setPlaying, togglePlay }
})
