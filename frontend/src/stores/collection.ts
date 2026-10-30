import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * Overlay state for the card collection (spec story 14).
 *
 * The frozen route table has no collection entry, so the archive is an overlay
 * mounted once by the shell (App.vue) and opened from the home/settings screens.
 * Keeping the flag in a store means both entry points share one overlay instead
 * of each screen rendering its own copy.
 */
export const useCollectionStore = defineStore('collection', () => {
  const isOpen = ref(false)

  function open(): void {
    isOpen.value = true
  }

  function close(): void {
    isOpen.value = false
  }

  function toggle(): void {
    isOpen.value = !isOpen.value
  }

  return { isOpen, open, close, toggle }
})
