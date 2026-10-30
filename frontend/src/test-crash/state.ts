import { ref } from 'vue'

/** Route name whose screen should throw on its next render (test build only). */
export const crashTarget = ref<string | null>(null)

export function requestCrash(routeName: string): void {
  crashTarget.value = routeName
}
