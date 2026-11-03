import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useResultStore } from '../../stores/result'
import { useAudioStore } from '../../stores/audio'
import { getLobbySocket } from '../../realtime/lobby'
import type { DailyChallengeView } from './dailyChallenge'

export function useDailyChallenge() {
  const auth = useAuthStore()
  const router = useRouter()
  const open = ref(false)
  const view = ref<DailyChallengeView | null>(null)
  const busy = ref(false)
  const error = ref('')
  let timer: ReturnType<typeof setTimeout> | null = null
  let alive = true
  const label = computed(() => ({ available: '可挑战', in_progress: '进行中', completed: '已完成', failed: '已失败', unavailable: '今日暂无', unauthorized: '登录参与' })[view.value?.status || 'unavailable'])
  async function load(): Promise<void> {
    try {
      const response = await fetch('/api/daily-challenge', { credentials: 'same-origin', cache: 'no-store' })
      if (!response.ok) throw new Error('今日挑战读取失败，请刷新重试。')
      const body = await response.json() as DailyChallengeView
      if (!alive) return
      view.value = body
      error.value = ''
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => { void load() }, Math.max(1000, body.next_reset_at * 1000 - Date.now() + 100))
    } catch (e) { if (alive) error.value = e instanceof Error ? e.message : '读取失败，请刷新重试。' }
  }
  async function start(): Promise<void> {
    if (busy.value) return
    const socket = getLobbySocket()
    if (!socket?.socket.connected) { error.value = '连接尚未就绪，请稍后重试。'; return }
    busy.value = true
    error.value = ''
    try {
      const ack = view.value?.status === 'in_progress'
        ? await socket.emitEvent('rejoin_room', { room_id: view.value?.room_id, player_id: auth.user?.id })
        : await socket.emitEvent('create_ai_room', { daily_challenge: true })
      if (ack.status !== 'success') throw new Error(String(ack.message || '无法进入今日挑战'))
      useResultStore().beginMatch()
      useAudioStore().resetMatchAudio()
      open.value = false
      await router.push({ name: 'game' })
    } catch (e) {
      const message = e instanceof Error ? e.message : '进入失败，请刷新后确认挑战状态。'
      await load()
      error.value = message
    } finally { busy.value = false }
  }
  function show(): void { open.value = true; void load() }
  function focus(): void { void load() }
  onMounted(() => {
    void load()
    if (router.currentRoute.value.query.challenge === '1') open.value = true
    window.addEventListener('focus', focus)
  })
  onBeforeUnmount(() => { alive = false; if (timer) clearTimeout(timer); window.removeEventListener('focus', focus) })
  return { open, view, busy, error, label, load, start, show }
}
