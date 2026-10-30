<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AppOverlay from './AppOverlay.vue'
import { useDmStore } from '../stores/dm'
import { acquireFriendsChannel } from '../realtime/friends'

/**
 * 好友面板（原 main 的 `#friends-modal`：三列表 + 私聊）。
 *
 * 数据全部走既有接口：`GET /api/friends`（friends / incoming / outgoing / counts）、
 * `POST /api/friends/respond`、`POST /api/friends/remove`、
 * `GET|POST /api/friends/messages`。未登录时接口返回 401 / `{"error":"未登录"}`，
 * 这里直接显示「登录后才能加好友」，不弹全局错误。
 */
interface FriendRow {
  user_id: string
  username: string
  avatar?: string
  online?: boolean
  in_game?: boolean
  unread?: number
}

interface BriefRow {
  user_id: string
  username: string
  created_at?: number
}

interface Counts {
  friends?: number
  incoming?: number
  outgoing?: number
  unread?: number
}

interface DmMessage {
  id: number
  body: string
  stamp?: string
  mine?: boolean
}

const emit = defineEmits<{ (event: 'close'): void }>()

const loading = ref(true)
const needsLogin = ref(false)
const error = ref('')
const notice = ref('')

const friends = ref<FriendRow[]>([])
const incoming = ref<BriefRow[]>([])
const outgoing = ref<BriefRow[]>([])
const counts = ref<Counts>({})

const dm = useDmStore()
const activeName = computed(() => dm.active)
const messages = computed(() => dm.activeMessages)
const draft = computed({
  get: () => dm.draft,
  set: (value: string) => { dm.draft = value },
})
const sending = ref(false)
const dmError = computed(() => dm.activeError)
const sendError = ref('')

const activeFriend = computed(() => friends.value.find((row) => row.username === activeName.value) ?? null)
const hasFriends = computed(() => friends.value.length > 0)
const pendingCount = computed(() => (counts.value.incoming ?? incoming.value.length) || 0)

async function api<T>(url: string, init?: RequestInit): Promise<{ ok: boolean; status: number; data: T | null }> {
  try {
    const response = await fetch(url, {
      headers: { accept: 'application/json', ...(init?.body ? { 'content-type': 'application/json' } : {}) },
      ...init,
    })
    const data = (await response.json().catch(() => null)) as T | null
    return { ok: response.ok, status: response.status, data }
  } catch {
    return { ok: false, status: 0, data: null }
  }
}

async function loadFriends(): Promise<void> {
  loading.value = true
  error.value = ''
  const result = await api<{
    friends?: FriendRow[]
    incoming?: BriefRow[]
    outgoing?: BriefRow[]
    counts?: Counts
    error?: string
  }>('/api/friends')

  if (result.status === 401) {
    needsLogin.value = true
    loading.value = false
    return
  }
  needsLogin.value = false
  if (!result.ok || !result.data) {
    error.value = '好友列表没读出来，稍后再试。'
    loading.value = false
    return
  }
  friends.value = result.data.friends ?? []
  incoming.value = result.data.incoming ?? []
  outgoing.value = result.data.outgoing ?? []
  counts.value = result.data.counts ?? {}
  dm.prune(friends.value.map((row) => row.username))
  // 服务端读数覆盖本地角标：刷新后两边计数不会互相对不上
  dm.syncUnread(
    Object.fromEntries(
      friends.value
        .filter((row) => Number(row.unread ?? 0) > 0)
        .map((row) => [row.username, Number(row.unread ?? 0)]),
    ),
  )
  if (!activeName.value && friends.value.length) {
    void openThread(friends.value[0].username)
  } else if (activeName.value) {
    // 刷新要能带出当前会话的新消息（审查 P2-2）
    await dm.open(activeName.value)
  }
  loading.value = false
}

async function respond(username: string, accept: boolean): Promise<void> {
  notice.value = ''
  const result = await api<{ status?: string; error?: string }>('/api/friends/respond', {
    method: 'POST',
    body: JSON.stringify({ username, accept }),
  })
  if (!result.ok || result.data?.status === 'error') {
    error.value = result.data?.error || '这条申请处理失败了。'
    return
  }
  notice.value = accept ? `已和 ${username} 成为好友。` : '已拒绝这条申请。'
  incoming.value = incoming.value.filter((row) => row.username !== username)
  counts.value = { ...counts.value, incoming: Math.max(0, (counts.value.incoming ?? 1) - 1) }
  if (accept) await loadFriends()
}

async function removeFriend(username: string): Promise<void> {
  notice.value = ''
  const result = await api<{ status?: string; error?: string }>('/api/friends/remove', {
    method: 'POST',
    body: JSON.stringify({ username }),
  })
  if (!result.ok || result.data?.status === 'error') {
    error.value = result.data?.error || '删除好友失败了。'
    return
  }
  friends.value = friends.value.filter((row) => row.username !== username)
  if (activeName.value === username) {
    dm.active = ''
    if (friends.value.length) void openThread(friends.value[0].username)
  }
}

async function openThread(username: string): Promise<void> {
  const row = friends.value.find((item) => item.username === username)
  if (row) row.unread = 0
  await dm.open(username)
  void dm.markRead(username)
}

async function loadOlder(): Promise<void> {
  if (activeName.value) await dm.loadOlder(activeName.value)
}

async function send(): Promise<void> {
  const name = activeName.value
  const body = draft.value
  if (!body.trim() || !name || sending.value) return
  sending.value = true
  const result = await dm.send(name, body)
  sending.value = false
  if (!result.ok && result.error) sendError.value = result.error
}

let releaseChannel: (() => void) | null = null

onMounted(() => {
  void loadFriends()
  try {
    releaseChannel = acquireFriendsChannel(undefined, { onRequest: () => { void loadFriends() } })
  } catch {
    // socket 还没建立起就退化为纯 HTTP：面板仍可读历史与发送。
    releaseChannel = null
  }
})

onUnmounted(() => {
  releaseChannel?.()
  releaseChannel = null
})

// 会话内的未读角标：以好友列表的 unread 与实时推送的计数取较大者
function badgeFor(row: FriendRow): number {
  return Math.max(row.unread ?? 0, dm.unreadFor(row.username))
}

// 键盘/鼠标选中会话后立刻清零未读
watch(activeName, (name) => {
  if (!name) return
  dm.unread[name] = 0
})
</script>

<template>
  <AppOverlay id="friends-overlay" labelledby="friends-title" @close="emit('close')">
    <div class="friends">
      <header class="friends__head">
        <div>
          <p class="friends__eyebrow">社交 · 好友与私聊</p>
          <h2 id="friends-title" class="friends__title">好友</h2>
        </div>
        <div class="friends__head-actions">
          <span class="friends__meta" data-testid="friends-counts">
            好友 {{ counts.friends ?? friends.length }} · 待处理 {{ pendingCount }}
          </span>
          <button type="button" class="button button--ghost" data-testid="friends-refresh" @click="loadFriends">刷新</button>
          <button type="button" class="button button--ghost" data-testid="friends-close" @click="emit('close')">关闭</button>
        </div>
      </header>

      <p v-if="notice" class="friends__notice" data-testid="friends-notice" role="status">{{ notice }}</p>
      <p v-if="error" class="friends__error" data-testid="friends-error" role="alert">{{ error }}</p>

      <p v-if="needsLogin" class="friends__empty" data-testid="friends-needs-login">
        登录后才能加好友、发申请和私聊。游客可以继续打对局。
      </p>

      <div v-else class="friends__grid">
        <section class="friends__col" aria-label="好友列表">
          <h3 class="friends__col-title">好友</h3>
          <p v-if="loading" class="friends__empty">正在读取…</p>
          <p v-else-if="!hasFriends" class="friends__empty" data-testid="friends-empty">
            还没有好友。在大厅或对局结束页可以向玩家发起申请。
          </p>
          <ul v-else class="friends__list" data-testid="friends-list">
            <li
              v-for="row in friends"
              :key="row.user_id"
              class="friends__row"
              :class="{ 'is-active': row.username === activeName }"
            >
              <button type="button" class="friends__row-main" @click="openThread(row.username)">
                <span class="friends__dot" :class="{ 'is-online': row.online }" aria-hidden="true"></span>
                <span class="friends__name">{{ row.username }}</span>
                <span v-if="row.in_game" class="friends__tag">对局中</span>
                <span v-if="badgeFor(row)" class="friends__badge">{{ badgeFor(row) }}</span>
              </button>
              <button
                type="button"
                class="friends__drop"
                :aria-label="'删除好友 ' + row.username"
                @click="removeFriend(row.username)"
              >×</button>
            </li>
          </ul>

          <h3 class="friends__col-title friends__col-title--gap">申请</h3>
          <p v-if="!incoming.length" class="friends__empty">没有待处理的申请。</p>
          <ul v-else class="friends__list" data-testid="friends-incoming">
            <li v-for="row in incoming" :key="'in-' + row.user_id" class="friends__row friends__row--request">
              <span class="friends__name">{{ row.username }}</span>
              <span class="friends__request-actions">
                <button type="button" class="button button--primary friends__mini" @click="respond(row.username, true)">接受</button>
                <button type="button" class="button button--ghost friends__mini" @click="respond(row.username, false)">拒绝</button>
              </span>
            </li>
          </ul>
          <p v-if="outgoing.length" class="friends__hint">
            已发出：{{ outgoing.map((row) => row.username).join('、') }}
          </p>
        </section>

        <section class="friends__col friends__col--chat" aria-label="私聊">
          <h3 class="friends__col-title">
            {{ activeName ? '与 ' + activeName + ' 的私聊' : '私聊' }}
          </h3>
          <p v-if="!activeName" class="friends__empty">在左侧选一位好友开始私聊。</p>
          <template v-else>
            <p v-if="dmError || sendError" class="friends__error" data-testid="friends-dm-error" role="alert">{{ dmError || sendError }}</p>
            <button
              v-if="dm.activeHasMore"
              type="button"
              class="button button--ghost friends__more"
              data-testid="friends-load-more"
              :disabled="dm.activeLoadingOlder"
              @click="loadOlder"
            >{{ dm.activeLoadingOlder ? '正在读取更早的消息…' : '加载更早的消息' }}</button>
            <ol class="friends__thread" data-testid="friends-thread">
              <li
                v-for="message in messages"
                :key="message.id"
                :data-msg-id="message.id"
                class="friends__msg"
                :class="{ 'is-mine': message.mine }"
              >
                <span class="friends__msg-body">{{ message.body }}</span>
                <span class="friends__msg-stamp">{{ message.stamp }}</span>
              </li>
            </ol>
            <p v-if="!messages.length && !dm.activeLoading" class="friends__empty">还没有消息，打个招呼吧。</p>
            <p v-if="dm.activeLoading" class="friends__empty" data-testid="friends-thread-loading">正在读取…</p>
            <button
              v-if="dm.activeError"
              type="button"
              class="button button--ghost friends__more"
              data-testid="friends-thread-retry"
              @click="openThread(activeName)"
            >重试</button>
            <form class="friends__compose" @submit.prevent="send">
              <label class="friends__sr" for="friends-draft">私聊内容</label>
              <input
                id="friends-draft"
                v-model="draft"
                class="friends__input"
                data-testid="friends-draft"
                maxlength="500"
                placeholder="说点什么…"
                autocomplete="off"
              />
              <button
                type="submit"
                class="button button--primary"
                data-testid="friends-send"
                :disabled="sending || !draft.trim()"
              >发送</button>
            </form>
            <p v-if="activeFriend?.in_game" class="friends__hint">对方正在对局中，消息会在局内收到。</p>
          </template>
        </section>
      </div>
    </div>
  </AppOverlay>
</template>

<style scoped>
.friends {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: min(940px, calc(100vw - 48px));
  max-height: calc(100dvh - 96px);
  overflow: auto;
  padding: 18px 20px 20px;
}

.friends__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.friends__eyebrow {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.friends__title {
  margin: 0;
  font-size: 20px;
  color: var(--text-primary);
}

.friends__head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.friends__meta {
  font-size: 12px;
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.friends__grid {
  display: grid;
  grid-template-columns: minmax(0, 340px) minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
}

.friends__col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  padding: 12px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-chamber);
}

.friends__col-title {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
}

.friends__col-title--gap {
  margin-top: 8px;
}

.friends__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 4px;
  overflow-y: auto;
  max-height: 260px;
}

.friends__row {
  display: flex;
  align-items: center;
  gap: 6px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-raised) 70%, transparent);
}

.friends__row.is-active {
  outline: 1px solid color-mix(in srgb, var(--role-action) 55%, transparent);
}

.friends__row--request {
  justify-content: space-between;
  padding: 6px 8px;
}

.friends__row-main {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 8px;
  border: 0;
  background: none;
  color: var(--text-primary);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.friends__row-main:hover {
  color: var(--role-action);
}

.friends__drop {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  margin-right: 6px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--text-tertiary);
  cursor: pointer;
}

.friends__drop:hover {
  color: var(--role-danger);
  background: color-mix(in srgb, var(--role-danger) 14%, transparent);
}

.friends__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border-strong);
}

.friends__dot.is-online {
  background: var(--role-success);
  box-shadow: 0 0 6px color-mix(in srgb, var(--role-success) 70%, transparent);
}

.friends__name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.friends__tag {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 999px;
  color: var(--role-warning);
  background: color-mix(in srgb, var(--role-warning) 16%, transparent);
}

.friends__badge {
  min-width: 18px;
  padding: 0 5px;
  border-radius: 999px;
  font-size: 11px;
  text-align: center;
  color: var(--on-accent);
  background: var(--role-danger);
}

.friends__request-actions {
  display: flex;
  gap: 6px;
}

.friends__mini {
  height: 28px;
  min-height: 28px;
  padding: 0 10px;
  font-size: 11.5px;
}

.friends__thread {
  flex: 1 1 auto;
  min-height: 120px;
  max-height: 300px;
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
}

.friends__msg {
  align-self: flex-start;
  max-width: 82%;
  padding: 6px 9px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-raised) 85%, transparent);
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-primary);
}

.friends__msg.is-mine {
  align-self: flex-end;
  background: color-mix(in srgb, var(--role-action) 22%, transparent);
}

.friends__msg-stamp {
  display: block;
  margin-top: 2px;
  font-size: 10px;
  color: var(--text-tertiary);
}

.friends__compose {
  display: flex;
  gap: 8px;
  margin-top: auto;
}

.friends__input {
  flex: 1 1 auto;
  min-height: 36px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-deck);
  color: var(--text-primary);
  font-size: 13px;
}

.friends__empty,
.friends__hint {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-tertiary);
}

.friends__notice {
  margin: 0;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--role-success);
  background: color-mix(in srgb, var(--role-success) 12%, transparent);
}

.friends__error {
  margin: 0;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--role-danger);
  background: color-mix(in srgb, var(--role-danger) 12%, transparent);
}

.friends__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}

@media (max-width: 860px) {
  .friends {
    width: min(100%, calc(100vw - 24px));
    padding: 14px 14px 16px;
  }

  /* 手机宽度下标题与按钮挤在一行会把「刷新/关闭」压成竖排，改成两行排列。 */
  .friends__head {
    flex-wrap: wrap;
    align-items: center;
  }

  .friends__head-actions {
    flex: 1 1 100%;
    justify-content: space-between;
    gap: 6px;
  }

  .friends__head-actions .button {
    flex: 0 0 auto;
    white-space: nowrap;
  }

  .friends__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .friends__thread {
    max-height: 220px;
  }
}
</style>
