import { defineStore } from 'pinia'
import { ref } from 'vue'

const STORAGE_KEY = 'battleship.custom-rematch'
const STATUSES = ['available', 'pending', 'declined', 'canceled', 'expired', 'unavailable', 'started'] as const
type RematchStatus = (typeof STATUSES)[number]
type RematchRole = 'sender' | 'recipient'

export interface CustomRematchCredential {
  room_id: string
  token: string
}

export interface CustomRematchState extends CustomRematchCredential {
  opponent_name: string
  status: RematchStatus
  role: RematchRole | null
  expires_at: number | null
  server_now: number
  can_invite: boolean
  can_accept: boolean
  message: string
}

function asCredential(value: unknown): CustomRematchCredential | null {
  if (!value || typeof value !== 'object') return null
  const data = value as Record<string, unknown>
  if (typeof data.room_id !== 'string' || !data.room_id
    || typeof data.token !== 'string' || !data.token) return null
  return { room_id: data.room_id, token: data.token }
}

export function readCustomRematchCredential(): CustomRematchCredential | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? asCredential(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

export function hasCustomRematchResume(): boolean {
  return readCustomRematchCredential() !== null
}

function saveCredential(credential: CustomRematchCredential | null): void {
  try {
    if (credential) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(credential))
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // 私密浏览可能禁止存储。本页内的邀请仍可从连接恢复。
  }
}

function readState(value: unknown): CustomRematchState | null {
  const credential = asCredential(value)
  if (!credential) return null
  const data = value as Record<string, unknown>
  const status = STATUSES.find(candidate => candidate === data.status)
  const serverTime = data.server_now
  if (!status || typeof serverTime !== 'number' || !Number.isFinite(serverTime)) return null
  const expires = data.expires_at
  const deadline = typeof expires === 'number' && Number.isFinite(expires) ? expires : null
  const role = data.role === 'sender' || data.role === 'recipient' ? data.role : null
  if (status === 'pending' && (deadline === null || role === null)) return null
  return {
    ...credential,
    status,
    role,
    opponent_name: typeof data.opponent_name === 'string' ? data.opponent_name : '',
    expires_at: deadline,
    server_now: serverTime,
    can_invite: data.can_invite === true,
    can_accept: data.can_accept === true,
    message: typeof data.message === 'string' ? data.message : '',
  }
}

function isOpen(status: RematchStatus): boolean {
  return status === 'available' || status === 'pending'
}

export const useCustomRematchStore = defineStore('custom-rematch', () => {
  const state = ref<CustomRematchState | null>(null)
  const revision = ref(0)
  const credential = ref<CustomRematchCredential | null>(readCustomRematchCredential())
  const submitting = ref(false)
  const clockOffset = ref(0)
  let startedSourceRoom = ''

  function setCredential(next: CustomRematchCredential | null): void {
    credential.value = next
    saveCredential(next)
  }

  function applyState(payload: unknown, receivedAt = Date.now()): boolean {
    const next = readState(payload)
    if (!next || next.room_id === startedSourceRoom) return false
    const previous = state.value
    if (previous && previous.room_id === next.room_id) {
      if (next.server_now < previous.server_now) return false
      if (isOpen(next.status) && (!isOpen(previous.status)
        || (previous.status === 'pending' && next.status === 'available'))) return false
      if (previous.status === 'started' && next.status !== 'started') return false
    } else if (previous && next.status !== 'available' && credential.value?.room_id !== next.room_id) {
      // 切到新一局后，不接受旧房间迟到的回执。
      return false
    }
    state.value = next
    clockOffset.value = next.server_now - receivedAt
    revision.value++
    // 开局状态可能先于新房间的座位快照抵达，仍保留旧局凭据以便掉线补收。
    setCredential(isOpen(next.status) || next.status === 'started'
      ? { room_id: next.room_id, token: next.token }
      : null)
    return true
  }

  function clear(): void {
    state.value = null
    revision.value++
    setCredential(null)
  }

  function finishHandoff(sourceRoom: string): boolean {
    if (sourceRoom === startedSourceRoom) return false
    startedSourceRoom = sourceRoom
    if (state.value?.room_id === sourceRoom || credential.value?.room_id === sourceRoom) clear()
    return true
  }

  function remainingAt(now = Date.now()): number {
    const deadline = state.value?.expires_at
    if (state.value?.status !== 'pending' || deadline == null) return 0
    return Math.max(0, Math.ceil((deadline - now - clockOffset.value) / 1000))
  }

  return { state, credential, revision, submitting, applyState, clear, finishHandoff, remainingAt }
})
