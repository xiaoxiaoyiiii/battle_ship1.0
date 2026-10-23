import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

/**
 * 私聊会话状态（原 main 的 `#dm-list` + `dm-load-more`）。
 *
 * 这个 store 是"一个会话"的唯一实现：请求时序、分页游标、实时推送合并、
 * 草稿保留都在这里，组件只负责渲染。深模块的理由：竞态和去重是最容易写错、
 * 也最容易被复制到第二个调用点的地方（审查 P1/P2-2/P2-3 都落在这一处）。
 *
 * 线协议（后端 services/friends.py + domain/social/messages.py）：
 *   GET  /api/friends/messages?username=&limit=&before=  → {has_more, messages[]}
 *   POST /api/friends/messages {username, body}          → {message}
 *   push friend_message {id, from_uid, from_username, from_avatar, body, created_at, stamp}
 */
export interface DmMessage {
  id: number
  from_uid?: string
  to_uid?: string
  body: string
  created_at?: number
  stamp?: string
  mine?: boolean
}

interface ThreadState {
  /** 已按 id 升序、无重复的消息。 */
  messages: DmMessage[]
  /** 还有更早的历史（服务端 has_more）。 */
  hasMore: boolean
  /** 首屏是否已经加载过（换会话时避免闪空白）。 */
  loaded: boolean
  loading: boolean
  loadingOlder: boolean
  error: string
}

const PAGE_LIMIT = 50

function emptyThread(): ThreadState {
  return { messages: [], hasMore: false, loaded: false, loading: false, loadingOlder: false, error: '' }
}

/** 合并两批消息：按 id 去重 + 升序。分页与实时推送都走这一条路径。 */
export function mergeMessages(current: DmMessage[], incoming: DmMessage[]): DmMessage[] {
  const byId = new Map<number, DmMessage>()
  for (const message of current) {
    if (message && typeof message.id === 'number') byId.set(message.id, message)
  }
  for (const message of incoming) {
    if (!message || typeof message.id !== 'number') continue
    byId.set(message.id, { ...byId.get(message.id), ...message })
  }
  return Array.from(byId.values()).sort((a, b) => a.id - b.id)
}

export const useDmStore = defineStore('dm', () => {
  const active = ref('')
  const threads = ref<Record<string, ThreadState>>({})
  const drafts = ref<Record<string, string>>({})
  /** 未读：仅统计"不在当前会话"的推送，打开会话即清零。 */
  const unread = ref<Record<string, number>>({})

  /** 每个会话一个令牌：迟到的响应与令牌不一致就丢弃（审查 P1 的根因）。 */
  const tokens: Record<string, number> = {}
  const controllers: Record<string, AbortController> = {}

  function ensure(name: string): ThreadState {
    if (!threads.value[name]) threads.value[name] = emptyThread()
    return threads.value[name]
  }

  function bumpToken(name: string): number {
    tokens[name] = (tokens[name] ?? 0) + 1
    return tokens[name]
  }

  const activeMessages = computed<DmMessage[]>(() => (active.value ? ensure(active.value).messages : []))
  const activeHasMore = computed(() => (active.value ? ensure(active.value).hasMore : false))
  const activeLoading = computed(() => (active.value ? ensure(active.value).loading : false))
  const activeError = computed(() => (active.value ? ensure(active.value).error : ''))
  const activeLoadingOlder = computed(() => (active.value ? ensure(active.value).loadingOlder : false))
  const unreadFor = computed(() => (name: string) => unread.value[name] ?? 0)
  const draft = computed({
    get: () => (active.value ? drafts.value[active.value] ?? '' : ''),
    set: (value: string) => {
      if (active.value) drafts.value[active.value] = value
    },
  })

  async function fetchPage(name: string, before?: number): Promise<{ messages: DmMessage[]; hasMore: boolean; error: string }> {
    const params = new URLSearchParams({ username: name, limit: String(PAGE_LIMIT) })
    if (before) params.set('before', String(before))
    const controller = new AbortController()
    controllers[name]?.abort()
    controllers[name] = controller
    try {
      const response = await fetch('/api/friends/messages?' + params.toString(), {
        headers: { accept: 'application/json' },
        signal: controller.signal,
      })
      const data = (await response.json().catch(() => null)) as
        | { messages?: DmMessage[]; has_more?: boolean; error?: string }
        | null
      if (!response.ok) {
        return { messages: [], hasMore: false, error: data?.error || '私聊记录没读出来。' }
      }
      return { messages: data?.messages ?? [], hasMore: Boolean(data?.has_more), error: '' }
    } catch (error) {
      if ((error as { name?: string })?.name === 'AbortError') {
        return { messages: [], hasMore: false, error: '' }
      }
      return { messages: [], hasMore: false, error: '私聊记录没读出来。' }
    }
  }

  /** 打开一个会话：已有内容就先用着，同时刷新最新一页；令牌保证迟到响应不会串台。 */
  async function open(name: string): Promise<void> {
    active.value = name
    unread.value[name] = 0
    const thread = ensure(name)
    const token = bumpToken(name)
    thread.loading = true
    thread.error = ''
    const page = await fetchPage(name)
    if (tokens[name] !== token) return
    thread.loading = false
    if (page.error) {
      thread.error = page.error
      return
    }
    // 首屏是最新一页：与已有的实时消息合并，而不是覆盖
    thread.messages = mergeMessages(thread.messages, page.messages)
    thread.hasMore = page.hasMore
    thread.loaded = true
  }

  async function loadOlder(name: string): Promise<void> {
    const thread = ensure(name)
    const oldest = thread.messages[0]?.id
    if (thread.loadingOlder || !thread.hasMore || !oldest) return
    const token = bumpToken(name)
    thread.loadingOlder = true
    thread.error = ''
    const page = await fetchPage(name, oldest)
    if (tokens[name] !== token) return
    thread.loadingOlder = false
    if (page.error) {
      thread.error = page.error
      return
    }
    thread.messages = mergeMessages(pathMessages(page.messages, thread.messages), [])
    thread.hasMore = page.hasMore
  }

  function pathMessages(older: DmMessage[], current: DmMessage[]): DmMessage[] {
    return mergeMessages(older, current)
  }

  /**
   * 发送：捕获发起时的会话名，回包只落回那一会话（切人后不会插进当前会话），
   * 成功后才清空该会话的草稿。
   */
  async function send(name: string, body: string): Promise<{ ok: boolean; error: string }> {
    const text = body.trim()
    if (!text || !name) return { ok: false, error: '' }
    try {
      const response = await fetch('/api/friends/messages', {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify({ username: name, body: text }),
      })
      const data = (await response.json().catch(() => null)) as
        | { status?: string; error?: string; message?: DmMessage }
        | null
      if (!response.ok || data?.status === 'error') {
        return { ok: false, error: data?.error || '消息没发出去。' }
      }
      const thread = ensure(name)
      if (data?.message) thread.messages = mergeMessages(thread.messages, [data.message])
      if ((drafts.value[name] ?? '').trim() === text) drafts.value[name] = ''
      return { ok: true, error: '' }
    } catch {
      return { ok: false, error: '消息没发出去。' }
    }
  }

  /** 实时推送：归到发送者那一会话；不是当前会话就记未读。 */
  function receivePush(payload: Record<string, unknown> | null | undefined): { name: string; unread: number } {
    if (!payload) return { name: '', unread: 0 }
    const name = String(payload.from_username ?? '')
    const id = Number(payload.id ?? 0)
    if (!name || !id) return { name, unread: 0 }
    const message: DmMessage = {
      id,
      body: String(payload.body ?? ''),
      stamp: String(payload.stamp ?? ''),
      created_at: Number(payload.created_at ?? 0),
      from_uid: String(payload.from_uid ?? ''),
      mine: false,
    }
    const thread = ensure(name)
    thread.messages = mergeMessages(thread.messages, [message])
    if (active.value !== name) {
      unread.value[name] = (unread.value[name] ?? 0) + 1
      return { name, unread: unread.value[name] }
    }
    return { name, unread: 0 }
  }

  /** 重新拉一次列表后：清掉已不是好友的会话缓存，保留正在看的会话。 */
  function prune(allowed: string[]): void {
    const keep = new Set(allowed)
    for (const name of Object.keys(threads.value)) {
      if (!keep.has(name) && name !== active.value) delete threads.value[name]
    }
  }

  function reset(): void {
    active.value = ''
    threads.value = {}
    drafts.value = {}
    unread.value = {}
    for (const key of Object.keys(tokens)) delete tokens[key]
    for (const key of Object.keys(controllers)) {
      controllers[key].abort()
      delete controllers[key]
    }
  }

  return {
    active,
    threads,
    drafts,
    unread,
    activeMessages,
    activeHasMore,
    activeLoading,
    activeLoadingOlder,
    activeError,
    unreadFor,
    draft,
    open,
    loadOlder,
    send,
    receivePush,
    prune,
    reset,
  }
})
