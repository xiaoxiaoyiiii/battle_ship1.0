import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 创建页草稿跨大厅子页面保留；不写账号或浏览器持久存储。 */
export const useRoomDraftStore = defineStore('room-draft', () => {
  const name = ref('')
  const isPublic = ref(true)
  const banEnabled = ref(false)
  const banQuota = ref(1)
  const mutationIds = ref<string[]>([])
  function reset(): void {
    name.value = ''
    isPublic.value = true
    banEnabled.value = false
    banQuota.value = 1
    mutationIds.value = []
  }
  return { name, isPublic, banEnabled, banQuota, mutationIds, reset }
})
