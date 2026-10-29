<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProfileStore, type JsonObject } from '../../stores/profile'
import { useSettingsStore } from '../../stores/settings'
import { useUiStore } from '../../stores/ui'

/**
 * Ticket #25: own / other player's profile card.
 *
 * Every number, badge, tier label and history row comes from the server. The
 * privacy flags are rendered, not enforced here: show_history / show_rank /
 * show_guestbook were already applied by the server, while show_stats /
 * show_fav_cards remain legacy frontend-only hides (DECISIONS D13).
 */
const route = useRoute()
const router = useRouter()
const store = useProfileStore()
const settings = useSettingsStore()
const ui = useUiStore()

const targetUsername = computed(() => String(route.query.username || '').trim())
const viewed = computed(() => store.viewed)
const stats = computed<JsonObject | null>(() => viewed.value.stats)

const isSelf = computed(() => {
  const row = stats.value
  if (!row) return false
  const name = String(row.username || '')
  return Boolean(name) && name === store.viewerName
})

function readObject(source: JsonObject | null | undefined, key: string): JsonObject | null {
  const value = source ? source[key] : null
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function readArray(source: JsonObject | null | undefined, key: string): unknown[] {
  const value = source ? source[key] : null
  return Array.isArray(value) ? value : []
}

function readString(source: JsonObject | null | undefined, key: string): string {
  const value = source ? source[key] : null
  return typeof value === 'string' ? value : ''
}

function readNumber(source: JsonObject | null | undefined, key: string): number | null {
  const value = Number(source ? source[key] : NaN)
  return Number.isFinite(value) ? value : null
}

function flag(key: string): boolean {
  const value = stats.value ? stats.value[key] : null
  return value === undefined || value === null ? true : Number(value) !== 0
}

const loading = computed(
  () =>
    viewed.value.status === 'loading' ||
    (store.ownStatus === 'loading' && !targetUsername.value),
)
const loginRequired = computed(
  () => !targetUsername.value && store.ownStatus === 'anonymous' && viewed.value.status === 'idle',
)
const empty = computed(() => viewed.value.status === 'empty')
const failed = computed(() => viewed.value.status === 'error')
const ready = computed(() => viewed.value.status === 'ready' && stats.value !== null)

const avatar = computed(() => readString(stats.value, 'avatar'))
const avatarInput = ref<HTMLInputElement | null>(null)
const avatarPreview = ref('')
const avatarUploading = ref(false)
const avatarMessage = ref('')
const avatarError = ref(false)
const avatarVersion = ref(0)
const displayedAvatar = computed(() => {
  if (avatarPreview.value) return avatarPreview.value
  if (!avatar.value || !avatarVersion.value) return avatar.value
  return avatar.value + (avatar.value.includes('?') ? '&' : '?') + 'v=' + avatarVersion.value
})
const displayName = computed(() => readString(stats.value, 'username') || targetUsername.value || '玩家')
const statusText = computed(() => readString(stats.value, 'status_text'))
const signature = computed(() => readString(stats.value, 'signature'))
const titleName = computed(() => readString(stats.value, 'title_name'))
const nameStyle = computed(() => readString(stats.value, 'name_style'))
const cardBg = computed(() => readString(stats.value, 'card_bg_id') || 'deep')
const frame = computed(() => readString(stats.value, 'frame_id') || 'none')

const tags = computed(() => {
  const names = readArray(stats.value, 'tag_names').map((item) => String(item))
  if (names.length) return names
  return readArray(stats.value, 'tags').map((item) => String(item))
})

const wins = computed(() => readNumber(stats.value, 'wins') ?? 0)
const losses = computed(() => readNumber(stats.value, 'losses') ?? 0)
const totalMatches = computed(() => wins.value + losses.value)
const winRateText = computed(() => {
  const total = totalMatches.value
  // Unknown is shown as 暂无, never as a dash row (spec story 97).
  return total ? Math.round((wins.value / total) * 100) + '%' : '暂无'
})
const streak = computed(() => readNumber(stats.value, 'longest_streak') ?? 0)

const levelInfo = computed(() => readObject(stats.value, 'level_info'))
const levelText = computed(() => 'Lv.' + (readNumber(levelInfo.value, 'level') ?? 1))
const levelCapped = computed(() => levelInfo.value?.capped === true)
const levelFill = computed(() => {
  if (!levelInfo.value) return 0
  if (levelCapped.value) return 100
  const ratio = readNumber(levelInfo.value, 'ratio') ?? 0
  return Math.max(0, Math.min(100, Math.round(ratio * 100)))
})
const levelProgressText = computed(() => {
  if (!levelInfo.value) return ''
  if (levelCapped.value) return '满级 ' + (readNumber(levelInfo.value, 'max_level') ?? 100)
  const into = readNumber(levelInfo.value, 'into') ?? 0
  const need = readNumber(levelInfo.value, 'need') ?? 0
  return into + ' / ' + need + ' 经验'
})

const rankInfo = computed(() => readObject(stats.value, 'rank_info'))
const showRank = computed(() => flag('show_rank'))
const rankFill = computed(() => {
  const row = rankInfo.value
  if (!row) return 0
  const sub = readNumber(row, 'sub_points') ?? 0
  const progress = readNumber(row, 'progress') ?? 0
  if (sub <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((progress / sub) * 100)))
})
const rankNextText = computed(() => {
  const next = rankInfo.value ? readNumber(rankInfo.value, 'to_next') : null
  return next === null ? '' : '还差 ' + next + ' 分'
})

const showStats = computed(() => flag('show_stats'))
const showFavCards = computed(() => flag('show_fav_cards'))
const favCards = computed(() =>
  readArray(stats.value, 'fav_cards')
    .filter((item): item is JsonObject => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    .filter((item) => Boolean(item.name)),
)

const badges = computed(() => {
  // Owner view: the full catalogue comes from /api/achievements.
  if (store.achievements.length) return store.achievements
  return readArray(stats.value, 'achievements').filter(
    (item): item is JsonObject => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
})
const badgeCount = computed(() => store.achievementCount ?? readObject(stats.value, 'badge_count'))
const badgeUnlocked = computed(() => {
  const count = badgeCount.value ? readNumber(badgeCount.value, 'unlocked') : null
  return count ?? badges.value.filter((item) => item.unlocked === true).length
})
const badgeTotal = computed(() => {
  const count = badgeCount.value ? readNumber(badgeCount.value, 'total') : null
  return count ?? badges.value.length
})
const featuredBadge = computed(() => badges.value.find((item) => item.unlocked === true) || badges.value[0] || null)
const cosmeticCatalog = computed(() => {
  // /user_stats deliberately omits the full catalogue; the owner payload
  // loaded by /api/profile is the authoritative source for own cosmetics.
  return readObject(isSelf.value ? store.own : null, 'catalog') ?? readObject(stats.value, 'catalog')
})
const equippedCosmetics = computed(() => {
  const catalog = cosmeticCatalog.value
  const source = (isSelf.value ? store.own : null) ?? stats.value
  if (!catalog || !source) return []
  const definitions: { key: 'titles' | 'frames' | 'card_bgs'; kind: string; id: string; fallback: string }[] = [
    { key: 'titles', kind: '称号', id: readString(source, 'title_id'), fallback: '无称号' },
    { key: 'frames', kind: '头像框', id: readString(source, 'frame_id') || 'none', fallback: '无' },
    { key: 'card_bgs', kind: '头图主题', id: readString(source, 'card_bg_id') || 'deep', fallback: '深海' },
  ]
  return definitions.map(({ key, kind, id, fallback }) => {
    const row = readArray(catalog, key).find((item) => readString(item as JsonObject, 'id') === id)
    return { kind, id, name: row ? readString(row as JsonObject, 'name') : fallback }
  })
})

type EditorTab = 'hero' | 'frame' | 'title' | 'tags' | 'status'
const editorOpen = ref(false)
const editorTab = ref<EditorTab>('hero')
const editorDraft = ref({
  title_id: '',
  tags: [] as string[],
  status_text: '',
  frame_id: 'none',
  card_bg_id: 'deep',
})
const editorCatalog = computed(() =>
  readObject(settings.profile, 'catalog') ?? readObject(store.own, 'catalog') ?? readObject(stats.value, 'catalog'),
)
const editorOptions = computed(() => {
  const key = editorTab.value === 'hero' ? 'card_bgs' : editorTab.value === 'frame' ? 'frames' : editorTab.value === 'tags' ? 'tags' : 'titles'
  const options = readArray(editorCatalog.value, key)
  if (editorTab.value === 'title') {
    return [{ id: '', name: '无称号', desc: '名片上不展示称号', unlocked: true }, ...options]
  }
  return options
})
const editorSelection = computed(() => {
  if (editorTab.value === 'hero') return editorDraft.value.card_bg_id
  if (editorTab.value === 'frame') return editorDraft.value.frame_id
  if (editorTab.value === 'title') return editorDraft.value.title_id
  return ''
})
const editorTitle = computed(() => {
  if (!editorDraft.value.title_id) return '无称号'
  const row = readArray(editorCatalog.value, 'titles').find((item) => readString(item as JsonObject, 'id') === editorDraft.value.title_id)
  return row ? readString(row as JsonObject, 'name') : titleName.value || '无称号'
})
const editorStatus = computed(() => {
  if (settings.cardSaving) return '保存中…'
  if (settings.cardMessage) return settings.cardMessage
  return '修改只影响名片展示，不会重置战绩或装备'
})

function draftFrom(source: JsonObject): void {
  editorDraft.value = {
    title_id: readString(source, 'title_id'),
    tags: readArray(source, 'tags').map((item) => String(item)).slice(0, 3),
    status_text: readString(source, 'status_text'),
    frame_id: readString(source, 'frame_id') || 'none',
    card_bg_id: readString(source, 'card_bg_id') || 'deep',
  }
}

async function openEditor(): Promise<void> {
  if (!isSelf.value) return
  await settings.loadOwn()
  if (settings.profileStatus !== 'ready' || !settings.profile) {
    settings.cardError = true
    settings.cardMessage = settings.profileError || '无法加载个人名片'
    return
  }
  const source = settings.profile
  draftFrom(source)
  settings.cardMessage = ''
  settings.cardError = false
  editorTab.value = 'hero'
  editorOpen.value = true
}

function closeEditor(): void {
  if (settings.cardSaving) return
  editorOpen.value = false
}

function chooseEditorTab(tab: EditorTab): void {
  editorTab.value = tab
}

function chooseEditorOption(item: unknown): void {
  const row = item as JsonObject
  if (!editorItemUnlocked(item)) return
  const id = readString(row, 'id')
  if (editorTab.value === 'hero') editorDraft.value.card_bg_id = id
  if (editorTab.value === 'frame') editorDraft.value.frame_id = id
  if (editorTab.value === 'title') editorDraft.value.title_id = id
  if (editorTab.value === 'tags') {
    if (editorDraft.value.tags.includes(id)) {
      editorDraft.value.tags = editorDraft.value.tags.filter((tag) => tag !== id)
    } else if (editorDraft.value.tags.length < 3) {
      editorDraft.value.tags = [...editorDraft.value.tags, id]
    }
  }
}

function editorItemId(item: unknown): string {
  return readString(item as JsonObject, 'id')
}

function editorItemName(item: unknown): string {
  return readString(item as JsonObject, 'name')
}

function editorItemDescription(item: unknown): string {
  const row = item as JsonObject
  if (row.unlocked === undefined) return '点击选择，最多 3 个'
  return row.unlocked === true ? readString(row, 'desc') : readString(row, 'requirement')
}

function editorItemUnlocked(item: unknown): boolean {
  const unlocked = (item as JsonObject).unlocked
  return unlocked === undefined || unlocked === true
}

function editorTagSelected(id: string): boolean {
  return editorDraft.value.tags.includes(id)
}

const AVATAR_MAX_BYTES = 2 * 1024 * 1024
const AVATAR_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif'])
const AVATAR_MIME_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif'])

function setAvatarMessage(message: string, error = false): void {
  avatarMessage.value = message
  avatarError.value = error
}

function clearAvatarPreview(): void {
  if (avatarPreview.value.startsWith('blob:')) URL.revokeObjectURL(avatarPreview.value)
  avatarPreview.value = ''
}

function openAvatarPicker(): void {
  if (!isSelf.value || avatarUploading.value) return
  avatarInput.value?.click()
}

async function uploadAvatar(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (input) input.value = ''
  if (!file || !isSelf.value || avatarUploading.value) return

  const extension = file.name.toLowerCase().split('.').pop() || ''
  if (!AVATAR_MIME_TYPES.has(file.type) && !AVATAR_EXTENSIONS.has(extension)) {
    setAvatarMessage('请选择 PNG、JPG 或 GIF 图片', true)
    return
  }
  if (file.size > AVATAR_MAX_BYTES) {
    setAvatarMessage('头像不能超过 2MB', true)
    return
  }

  clearAvatarPreview()
  avatarPreview.value = URL.createObjectURL(file)
  avatarUploading.value = true
  setAvatarMessage('正在上传头像…')
  try {
    const form = new FormData()
    form.append('avatar', file)
    const response = await fetch('/api/profile/avatar', {
      method: 'POST',
      headers: { accept: 'application/json' },
      body: form,
    })
    let body: JsonObject | null = null
    try {
      const parsed: unknown = await response.json()
      body = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
        ? parsed as JsonObject
        : null
    } catch {
      body = null
    }
    if (!response.ok || body?.success !== true) {
      throw new Error(String(body?.error || '头像上传失败'))
    }
    await store.loadOwn(true)
    await settings.loadOwn()
    await refresh()
    avatarVersion.value = Date.now()
    clearAvatarPreview()
    setAvatarMessage('头像已更新')
  } catch (error) {
    clearAvatarPreview()
    setAvatarMessage(error instanceof Error ? error.message : String(error), true)
  } finally {
    avatarUploading.value = false
  }
}

async function saveEditor(): Promise<void> {
  if (settings.cardSaving || !editorOpen.value || !isSelf.value) return
  const saved = await settings.saveCard({
    title_id: editorDraft.value.title_id,
    tags: editorDraft.value.tags,
    status_text: editorDraft.value.status_text,
    frame_id: editorDraft.value.frame_id,
    card_bg_id: editorDraft.value.card_bg_id,
  })
  if (!saved) return
  store.own = saved
  await store.loadPublic(store.viewerName)
  editorOpen.value = false
  ui.notify({ code: 'profile-card-saved', tone: 'success', message: '名片已保存' })
}

const showHistory = computed(() => isSelf.value || flag('show_history'))
const history = computed(() => viewed.value.history)
const historyEmptyText = computed(() => {
  if (!showHistory.value) return '该玩家未公开对局历史'
  return isSelf.value ? '还没有对局记录' : '暂无历史战绩'
})

const winsRank = computed(() => readNumber(stats.value, 'rank'))
const createdAt = computed(() => {
  const seconds = readNumber(stats.value, 'created_at')
  if (!seconds) return ''
  const date = new Date(seconds * 1000)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')
})

function modeLabel(mode: unknown): string {
  switch (String(mode || '')) {
    case 'ranked':
      return '排位'
    case 'casual':
      return '休闲'
    case 'ai':
      return '人机'
    case 'custom':
      return '自定义'
    default:
      return ''
  }
}

function historyTime(row: JsonObject): string {
  const seconds = Number(row.timestamp)
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  const date = new Date(seconds * 1000)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN')
}

function historyOpponent(row: JsonObject): string {
  const selfId = stats.value ? String(stats.value.id || '') : ''
  const winnerId = String(row.winner_id || '')
  const name = winnerId === selfId ? row.loser_name : row.winner_name
  return String(name || '未知玩家')
}

function historyResult(row: JsonObject): string {
  const selfId = stats.value ? String(stats.value.id || '') : ''
  return String(row.winner_id || '') === selfId ? '胜' : '负'
}

function openReplay(matchId: string): void {
  if (!matchId) return
  void router.push({ name: 'replay', query: { match_id: matchId } })
}

function openSettings(): void {
  void router.push({ name: 'settings' })
}

/** Where 返回 goes: the query the caller sent, then browser history, then the board. */
const FROM_ROUTES: Record<string, { name: string }> = {
  start: { name: 'start' },
  home: { name: 'start' },
  leaderboard: { name: 'leaderboard' },
  lobby: { name: 'lobby' },
  'game-over': { name: 'game-over' },
  replay: { name: 'replay' },
  spectate: { name: 'spectate' },
}

function back(): void {
  const from = String(route.query.from || '')
  const target = FROM_ROUTES[from]
  if (target) {
    void router.push(target)
    return
  }
  const historyBack = router.options.history.state.back
  if (typeof historyBack === 'string' && historyBack && historyBack !== route.fullPath) {
    router.back()
    return
  }
  void router.push({ name: 'leaderboard' })
}

// ------------------------------------------------------- recent entries ----
// The three entries (badges / record / replay) are ordered by most recent use
// and the order is remembered, so a returning player's habitual entry is first.
type QuickKey = 'badges' | 'record' | 'replay'
const QUICK_KEY = 'battleship.profile.recent'
const QUICK_DEFAULT: QuickKey[] = ['badges', 'record', 'replay']
const QUICK_LABELS: Record<QuickKey, string> = { badges: '徽章', record: '战绩', replay: '回放' }
const QUICK_TARGETS: Record<QuickKey, string> = {
  badges: 'profile-badges',
  record: 'profile-history',
  replay: 'profile-history',
}

function readQuickOrder(): QuickKey[] {
  try {
    const raw = localStorage.getItem(QUICK_KEY)
    if (!raw) return [...QUICK_DEFAULT]
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return [...QUICK_DEFAULT]
    const valid = parsed.filter((item): item is QuickKey => QUICK_DEFAULT.includes(item as QuickKey))
    return [...valid, ...QUICK_DEFAULT.filter((item) => !valid.includes(item))]
  } catch {
    return [...QUICK_DEFAULT]
  }
}

const quickOrder = ref<QuickKey[]>(readQuickOrder())

function useQuick(key: QuickKey): void {
  quickOrder.value = [key, ...quickOrder.value.filter((item) => item !== key)]
  try {
    localStorage.setItem(QUICK_KEY, JSON.stringify(quickOrder.value))
  } catch {
    // Best effort: the order still changes for this visit.
  }
  document
    .querySelector('[data-testid="' + QUICK_TARGETS[key] + '"]')
    ?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

async function refresh(): Promise<void> {
  if (targetUsername.value) {
    await store.loadPublic(targetUsername.value)
    return
  }
  if (store.viewerName) {
    await store.loadPublic(store.viewerName)
  } else {
    store.clearViewed()
  }
}

onMounted(async () => {
  await store.loadOwn()
  await refresh()
})

watch(targetUsername, () => {
  editorOpen.value = false
  void refresh()
})
</script>

<template>
  <section
    class="screen profile"
    data-screen="profile"
    data-testid="screen-profile"
    :data-self="isSelf ? 'true' : 'false'"
    aria-labelledby="screen-profile-title"
  >
    <header class="profile__head">
      <p class="profile__eyebrow">竞技场 · 名片</p>
      <h1 id="screen-profile-title" class="profile__title" data-testid="profile-heading">名片</h1>
      <p class="profile__viewing" data-testid="profile-viewing">
        {{ ready ? (isSelf ? '我的名片' : displayName + ' 的名片') : '玩家名片' }}
      </p>
    </header>

    <p v-if="loading" class="profile__state" data-testid="profile-loading" role="status">正在加载名片…</p>

    <section v-else-if="loginRequired" class="profile__login" data-testid="profile-login-required">
      <h2>需要先登录</h2>
      <p>自己的名片、徽章与隐私设置都在登录后显示。</p>
      <button
        type="button"
        class="button"
        data-testid="profile-login-required-action"
        @click="ui.requestLogin('login', '登录后查看完整名片')"
      >
        登录 / 注册
      </button>
    </section>

    <p v-else-if="empty" class="profile__state" data-testid="profile-empty">
      没有找到这位玩家 —— 用户名可能拼错了，或账号已经不存在。
    </p>

    <p v-else-if="failed" class="profile__state profile__state--error" data-testid="profile-error" role="alert">
      无法加载名片：{{ viewed.error }}
    </p>

    <template v-else-if="ready">
      <!-- Most-recently-used first (spec story 120, ticket #49). -->
      <nav class="profile__quick" data-testid="profile-quick" aria-label="常用入口">
        <button
          v-for="key in quickOrder"
          :key="key"
          type="button"
          class="profile__quick-item"
          :data-testid="'profile-quick-' + key"
          @click="useQuick(key)"
        >
          {{ QUICK_LABELS[key] }}
        </button>
      </nav>

      <article class="profile__card" :data-bg="cardBg">
        <header class="profile__hero">
          <div class="profile__avatar-wrap">
            <img v-if="displayedAvatar" class="profile__avatar" data-testid="profile-avatar"
                 :src="displayedAvatar" :data-frame="frame" alt="" />
            <span v-else class="profile__avatar profile__avatar--empty" data-testid="profile-avatar"
                  :data-frame="frame" aria-hidden="true">⚓</span>
            <div v-if="isSelf" class="profile__avatar-control">
              <button
                type="button"
                class="profile__avatar-upload"
                data-testid="profile-avatar-upload-button"
                :disabled="avatarUploading"
                @click="openAvatarPicker"
              >
                {{ avatarUploading ? '上传中…' : '更换头像' }}
              </button>
              <input
                ref="avatarInput"
                class="profile__avatar-input"
                data-testid="profile-avatar-upload"
                type="file"
                accept="image/png,image/jpeg,image/gif"
                @change="uploadAvatar"
              />
              <span class="profile__avatar-hint">PNG / JPG / GIF · 2MB</span>
              <span v-if="avatarMessage" class="profile__avatar-message" :class="{ 'is-error': avatarError }" role="status">
                {{ avatarMessage }}
              </span>
            </div>
            <span class="profile__level" data-testid="profile-level">{{ levelText }}</span>
          </div>
          <div class="profile__who">
            <h2 class="profile__name">
              <span :class="{ 'is-rainbow': nameStyle === 'rainbow' }" data-testid="profile-name">{{ displayName }}</span>
              <span v-if="titleName" class="profile__title-chip" data-testid="profile-title">{{ titleName }}</span>
            </h2>
            <p v-if="statusText" class="profile__status" data-testid="profile-status">{{ statusText }}</p>
            <p v-if="signature" class="profile__signature" data-testid="profile-signature">
              {{ signature }}
            </p>
            <div v-if="tags.length" class="profile__tags" data-testid="profile-tags">
              <span v-for="tag in tags" :key="tag" class="profile__tag">{{ tag }}</span>
            </div>
          </div>
          <div v-if="isSelf" class="profile__hero-actions">
            <button type="button" class="profile__edit-button" data-testid="profile-edit-entry" @click="openEditor">
              ✎ 编辑名片
            </button>
          </div>
        </header>

        <div v-if="levelInfo" class="profile__bar-row">
          <div class="profile__bar" role="img" :aria-label="'等级进度 ' + levelFill + '%'">
            <div class="profile__bar-fill" data-testid="profile-level-fill" :style="{ width: levelFill + '%' }"></div>
          </div>
          <span class="profile__bar-text" data-testid="profile-level-text">{{ levelProgressText }}</span>
        </div>

        <section v-if="rankInfo" class="profile__rank" data-testid="profile-rank">
          <span class="profile__rank-label" data-testid="profile-rank-label">{{ readString(rankInfo, 'label') }}</span>
          <div class="profile__bar profile__bar--rank" role="img" :aria-label="'段位进度 ' + rankFill + '%'">
            <div class="profile__bar-fill profile__bar-fill--rank"
                 data-testid="profile-rank-fill" :style="{ width: rankFill + '%' }"></div>
          </div>
          <span v-if="rankNextText" class="profile__bar-text" data-testid="profile-rank-note">{{ rankNextText }}</span>
        </section>
        <p v-else-if="!isSelf && !showRank" class="profile__private" data-testid="profile-rank-private">
          该玩家未公开段位信息。
        </p>

        <section v-if="showStats" class="profile__stats" data-testid="profile-stats" aria-label="战绩">
          <div class="profile__stat"><b data-testid="profile-stat-streak">{{ streak }}</b><span>最高连胜</span></div>
          <div class="profile__stat"><b data-testid="profile-stat-rate">{{ winRateText }}</b><span>胜率</span></div>
          <div class="profile__stat"><b data-testid="profile-stat-total">{{ totalMatches }}</b><span>总场次</span></div>
        </section>
        <p v-else class="profile__private" data-testid="profile-stats-private">该玩家未公开战绩亮点。</p>

        <section class="profile__showcase" data-testid="profile-showcase" aria-label="个性展示">
          <div class="profile__showcase-feature">
            <p class="profile__showcase-kicker">FEATURED</p>
            <h3>本季名片焦点</h3>
            <div v-if="featuredBadge" class="profile__featured-badge">
              <span class="profile__featured-badge-mark" aria-hidden="true">✦</span>
              <div><b>{{ readString(featuredBadge, 'name') }}</b><small>{{ featuredBadge.unlocked === true ? readString(featuredBadge, 'desc') : readString(featuredBadge, 'requirement') }}</small></div>
            </div>
            <p v-else class="profile__private">完成成就后，这里会展示你的代表徽章。</p>
          </div>
          <div class="profile__showcase-pulse" aria-hidden="true"><i></i><i></i><i></i></div>
          <div v-if="isSelf && equippedCosmetics.length" class="profile__cosmetics" data-testid="profile-cosmetics">
            <div class="profile__showcase-kicker">当前装备 · {{ equippedCosmetics.length }}</div>
            <div class="profile__cosmetic-list"><span v-for="item in equippedCosmetics" :key="item.kind + item.id" :data-kind="item.kind"><i aria-hidden="true">✦</i><b>{{ item.name }}</b><small>{{ item.kind }}</small></span></div>
          </div>
        </section>

        <section v-if="badges.length" class="profile__block" data-testid="profile-badges" aria-label="徽章墙">
          <h3 class="profile__block-title">
            徽章墙
            <span class="profile__badge-count" data-testid="profile-badge-count">
              已解锁 {{ badgeUnlocked }} / {{ badgeTotal }}
            </span>
          </h3>
          <ul class="profile__badge-list">
            <li
              v-for="badge in badges"
              :key="readString(badge, 'id')"
              class="profile__badge"
              :class="{ 'is-locked': badge.unlocked !== true }"
              :data-testid="'profile-badge-' + readString(badge, 'id')"
              :title="readString(badge, 'requirement')"
            >
              <b>{{ readString(badge, 'name') }}</b>
              <span>{{ badge.unlocked === true ? readString(badge, 'desc') : readString(badge, 'requirement') }}</span>
            </li>
          </ul>
        </section>

        <section v-if="showFavCards" class="profile__block" data-testid="profile-favcards" aria-label="最爱用的卡">
          <h3 class="profile__block-title">最爱用的卡</h3>
          <ul v-if="favCards.length" class="profile__fav-list">
            <li v-for="card in favCards" :key="readString(card, 'name')"
                class="profile__fav" :data-testid="'profile-favcard-' + readString(card, 'name')">
              <span>{{ readString(card, 'name') }}</span>
              <small>{{ readNumber(card, 'uses') ?? 0 }} 次</small>
            </li>
          </ul>
          <p v-else class="profile__private">还没有常用的卡牌记录。</p>
        </section>
        <p v-else class="profile__private" data-testid="profile-favcards-private">该玩家未公开最爱用的卡。</p>

        <section v-if="showHistory" class="profile__block" data-testid="profile-history" aria-label="历史战绩">
          <h3 class="profile__block-title">历史战绩</h3>
          <ul v-if="history.length" class="profile__history">
            <li v-for="row in history" :key="readString(row, 'match_id')"
                class="profile__history-row"
                :data-testid="'profile-history-row-' + readString(row, 'match_id')">
              <span class="profile__history-time">{{ historyTime(row) }}</span>
              <span class="profile__history-opp">
                vs {{ historyOpponent(row) }}
                <small v-if="modeLabel(row.mode)">· {{ modeLabel(row.mode) }}</small>
              </span>
              <b :class="historyResult(row) === '胜' ? 'is-win' : 'is-lose'">{{ historyResult(row) }}</b>
              <button
                v-if="row.has_replay === true"
                type="button"
                class="button button--small"
                :data-testid="'profile-history-replay-' + readString(row, 'match_id')"
                @click="openReplay(readString(row, 'match_id'))"
              >
                回放
              </button>
            </li>
          </ul>
          <p v-else class="profile__private" data-testid="profile-history-empty">{{ historyEmptyText }}</p>
        </section>
        <p v-else class="profile__private" data-testid="profile-history-private">该玩家未公开对局历史。</p>

        <footer class="profile__meta" data-testid="profile-meta">
          <span v-if="createdAt" data-testid="profile-meta-joined">加入于 {{ createdAt }}</span>
          <span v-if="winsRank" data-testid="profile-meta-rank">战绩榜第 {{ winsRank }} 名</span>
          <span data-testid="profile-meta-record">{{ wins }} 胜 {{ losses }} 负</span>
        </footer>
      </article>

      <div class="profile__actions">
        <button v-if="isSelf" type="button" class="button" data-testid="profile-settings-link" @click="openSettings">
          隐私与设置
        </button>
        <button type="button" class="button button--ghost" data-testid="profile-back" @click="back">
          返回排行榜
        </button>
      </div>
    </template>

    <section v-if="editorOpen" class="profile-editor" data-testid="profile-editor" aria-label="编辑名片">
      <div class="profile-editor__backdrop" @click="closeEditor"></div>
      <div class="profile-editor__panel" role="dialog" aria-modal="true" aria-labelledby="profile-editor-title">
        <header class="profile-editor__head">
          <div><p class="profile__showcase-kicker">PROFILE CUSTOMIZER</p><h2 id="profile-editor-title">编辑名片</h2></div>
          <p class="profile-editor__status" :class="{ 'is-error': settings.cardError }" role="status">{{ editorStatus }}</p>
        </header>
        <div class="profile-editor__body">
          <div class="profile-editor__preview" :data-bg="editorDraft.card_bg_id">
            <div class="profile-editor__preview-label">实时预览</div>
            <div class="profile-editor__preview-cover"></div>
            <div class="profile-editor__preview-identity">
              <img v-if="displayedAvatar" class="profile-editor__preview-avatar" :src="displayedAvatar" :data-frame="editorDraft.frame_id" alt="" />
              <span v-else class="profile-editor__preview-avatar" :data-frame="editorDraft.frame_id">⚓</span>
              <div><h3>{{ displayName }}</h3><span>{{ editorTitle }}</span></div>
            </div>
            <p class="profile-editor__preview-status">{{ editorDraft.status_text || '写一句让别人记住你的航海状态' }}</p>
          </div>
          <div class="profile-editor__controls">
            <div class="profile-editor__tabs" role="tablist" aria-label="名片编辑分区">
              <button type="button" :class="{ 'is-active': editorTab === 'hero' }" @click="chooseEditorTab('hero')">头图主题</button>
              <button type="button" :class="{ 'is-active': editorTab === 'frame' }" @click="chooseEditorTab('frame')">头像框</button>
              <button type="button" :class="{ 'is-active': editorTab === 'title' }" @click="chooseEditorTab('title')">称号</button>
              <button type="button" :class="{ 'is-active': editorTab === 'tags' }" @click="chooseEditorTab('tags')">标签</button>
              <button type="button" :class="{ 'is-active': editorTab === 'status' }" @click="chooseEditorTab('status')">状态</button>
            </div>
            <div v-if="editorTab !== 'status'" class="profile-editor__options">
              <button
                v-for="item in editorOptions"
                :key="editorItemId(item) || 'empty-title'"
                type="button"
                class="profile-editor__option"
                :class="{ 'is-selected': editorTab === 'tags' ? editorTagSelected(editorItemId(item)) : editorItemId(item) === editorSelection, 'is-locked': !editorItemUnlocked(item) }"
                :disabled="!editorItemUnlocked(item)"
                @click="chooseEditorOption(item)"
              >
                <span class="profile-editor__option-mark" aria-hidden="true">{{ editorItemUnlocked(item) ? '✦' : '🔒' }}</span>
                <b>{{ editorItemName(item) }}</b>
                <small>{{ editorItemDescription(item) }}</small>
                <em v-if="editorTab === 'tags' ? editorTagSelected(editorItemId(item)) : editorItemId(item) === editorSelection">{{ editorTab === 'tags' ? '已选择' : '已装备' }}</em>
              </button>
            </div>
            <label v-else class="profile-editor__field"><span>一句话状态</span><textarea v-model="editorDraft.status_text" maxlength="30" rows="4" placeholder="写一句让别人记住你的航海状态"></textarea><small>{{ editorDraft.status_text.length }} / 30</small></label>
          </div>
        </div>
        <footer class="profile-editor__actions"><button type="button" class="button button--ghost" :disabled="settings.cardSaving" @click="closeEditor">取消</button><button type="button" class="button profile-editor__save" :disabled="settings.cardSaving" @click="saveEditor">{{ settings.cardSaving ? '保存中…' : '保存名片' }}</button></footer>
      </div>
    </section>
  </section>
</template>

<style scoped>
/* 个人名片：把身份、装备和成就做成一张有层次的舰队档案。 */
.profile {
  align-items: center;
  gap: 0;
  padding: 0 24px 40px;
}

.profile__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 14px;
  width: 1120px;
  max-width: 100%;
  padding: 14px 26px 10px;
  border: 1px solid var(--panel-line);
  border-bottom: 0;
  border-radius: var(--radius) var(--radius) 0 0;
  background: var(--panel);
}

.profile__eyebrow {
  margin: 0;
  color: var(--text-secondary);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.profile__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.profile__viewing {
  margin: 0 0 0 auto;
  color: var(--text-muted);
  font-size: 12px;
}

.profile__state,
.profile__login {
  width: 1120px;
  max-width: 100%;
  margin: 0;
  padding: 14px 26px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  color: var(--text-muted);
  font-size: 13px;
}

.profile__state--error {
  border-color: var(--danger);
  color: var(--danger);
}

.profile__login h2 {
  margin: 0 0 6px;
  color: var(--text);
  font-size: 18px;
}

.profile__login p {
  margin: 0 0 10px;
}

.profile__card {
  display: grid;
  gap: 12px;
  width: 1120px;
  max-width: 100%;
  padding: 0 0 18px;
  overflow: hidden;
  border: 1px solid var(--panel-line);
  border-radius: 0 0 var(--radius) var(--radius);
  background: var(--panel);
  box-shadow: 0 24px 70px rgb(2 6 18 / 34%);
}

.profile__card[data-bg='graphite'] {
  background: linear-gradient(160deg, #232a30, #10151a 70%);
}

.profile__card[data-bg='cyber'] {
  background: linear-gradient(160deg, #2a1840, #0f1a2c 70%);
}

.profile__card[data-bg='lava'] {
  background: linear-gradient(160deg, #3a1a12, #1a0f0c 70%);
}

.profile__card[data-bg='kelp_green'] { background: linear-gradient(150deg, #122f2e, #08171d 72%); }
.profile__card[data-bg='moonlit'] { background: linear-gradient(150deg, #1a294c, #080f22 72%); }
.profile__card[data-bg='coral_dawn'] { background: linear-gradient(150deg, #492637, #1b1424 72%); }
.profile__card[data-bg='abyssal_grid'] {
  background-color: #080d18;
  background-image: linear-gradient(rgb(201 162 76 / 8%) 1px, transparent 1px), linear-gradient(90deg, rgb(201 162 76 / 8%) 1px, transparent 1px), linear-gradient(160deg, #16131c, #060a12 76%);
  background-size: 24px 24px, 24px 24px, auto;
}
.profile__card[data-bg='season_deep_1'] { background: radial-gradient(circle at 78% 12%, rgb(78 200 224 / 22%), transparent 26%), linear-gradient(150deg, #10334b, #07121f 70%); }

.profile__hero {
  position: relative;
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 4px;
  min-height: 224px;
  padding: 156px 32px 24px;
}

.profile__hero::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 190px;
  border-bottom: 1px solid color-mix(in srgb, var(--role-action) 40%, transparent);
  background:
    repeating-linear-gradient(115deg, rgba(255, 255, 255, 0.06) 0 2px, transparent 2px 12px),
    radial-gradient(300px 120px at 22% 0%, rgba(255, 255, 255, 0.24), transparent 72%),
    linear-gradient(120deg, #7a5af0, #4029a4 70%);
}

.profile__hero::after {
  content: '航海档案';
  position: absolute;
  right: 26px;
  top: 20px;
  color: rgb(255 255 255 / 58%);
  font-size: 10px;
  letter-spacing: .22em;
}

.profile__card[data-bg='kelp_green'] .profile__hero::before { background: radial-gradient(300px 120px at 22% 0%, rgb(111 224 160 / 26%), transparent 72%), linear-gradient(120deg, #205c55, #102b2f 70%); }
.profile__card[data-bg='moonlit'] .profile__hero::before { background: radial-gradient(300px 120px at 22% 0%, rgb(130 175 255 / 25%), transparent 72%), linear-gradient(120deg, #35548d, #17294d 70%); }
.profile__card[data-bg='coral_dawn'] .profile__hero::before { background: radial-gradient(300px 120px at 22% 0%, rgb(255 181 145 / 24%), transparent 72%), linear-gradient(120deg, #a44f5e, #512c46 70%); }
.profile__card[data-bg='abyssal_grid'] .profile__hero::before { background: repeating-linear-gradient(115deg, rgb(255 255 255 / 5%) 0 2px, transparent 2px 12px), linear-gradient(120deg, #493924, #17151c 70%); }
.profile__card[data-bg='season_deep_1'] .profile__hero::before { background: radial-gradient(300px 120px at 22% 0%, rgb(142 220 236 / 28%), transparent 72%), linear-gradient(120deg, #1b7592, #17405f 70%); }

.profile__avatar-wrap {
  position: relative;
  display: grid;
  justify-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.profile__avatar-control {
  display: grid;
  justify-items: center;
  gap: 4px;
  min-height: 36px;
  margin-top: -2px;
}

.profile__avatar-upload {
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--role-action) 72%, white 8%);
  border-radius: 999px;
  background: color-mix(in srgb, var(--role-action) 18%, var(--panel));
  color: var(--text);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
  cursor: pointer;
}

.profile__avatar-upload:hover:not(:disabled) {
  background: color-mix(in srgb, var(--role-action) 30%, var(--panel));
}

.profile__avatar-upload:disabled {
  cursor: wait;
  opacity: .65;
}

.profile__avatar-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

.profile__avatar-hint,
.profile__avatar-message {
  color: var(--text-muted);
  font-size: 9px;
  line-height: 1.3;
  text-align: center;
}

.profile__avatar-message {
  color: var(--success);
}

.profile__avatar-message.is-error {
  color: var(--danger);
}

.profile__avatar {
  width: 128px;
  height: 128px;
  border: 3px solid rgba(11, 13, 24, 0.65);
  border-radius: 50%;
  object-fit: cover;
  background: #151a30;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.4);
}

.profile__avatar[data-frame='gold'] {
  border-color: var(--gold-strong);
}

.profile__avatar[data-frame='silver'] {
  border-color: #c6d3dd;
}

.profile__avatar[data-frame='aurora'] {
  border-color: var(--success);
}

.profile__avatar[data-frame='abyssal_glow'] { border-color: #58d5ed; box-shadow: 0 0 0 4px rgb(88 213 237 / 16%), 0 0 30px rgb(88 213 237 / 34%); }
.profile__avatar[data-frame='tideglass'] { border-color: #9bd8e7; box-shadow: 0 0 0 4px rgb(155 216 231 / 12%), inset 0 0 20px rgb(155 216 231 / 24%); }
.profile__avatar[data-frame='ember_wake'] { border-color: #e78353; box-shadow: 0 0 0 4px rgb(231 131 83 / 15%), 0 0 24px rgb(231 131 83 / 28%); }
.profile__avatar[data-frame='star_compass'] { border-color: #e7c36a; box-shadow: 0 0 0 4px rgb(231 195 106 / 16%), 0 0 22px rgb(231 195 106 / 26%); }
.profile__avatar[data-frame='season_tide_ring'] { border-color: #8ee0ef; box-shadow: 0 0 0 5px rgb(78 200 224 / 18%), 0 0 34px rgb(78 200 224 / 36%); }
.profile__avatar[data-frame='bronze_compass'] { border-color: #c58a55; box-shadow: 0 0 0 4px rgb(197 138 85 / 18%), 0 0 20px rgb(197 138 85 / 24%); }
.profile__avatar[data-frame='silver_chain'] { border-color: #b7c9d8; box-shadow: 0 0 0 5px rgb(183 201 216 / 16%), 0 0 24px rgb(183 201 216 / 26%); }
.profile__avatar[data-frame='golden_wheel'] { border-color: #f3c85f; box-shadow: 0 0 0 5px rgb(243 200 95 / 20%), 0 0 30px rgb(243 200 95 / 34%); animation: profile-frame-wheel 4s linear infinite; }
.profile__avatar[data-frame='mithril_ring'] { border-color: #cde8f3; box-shadow: 0 0 0 5px rgb(205 232 243 / 18%), 0 0 30px rgb(170 230 255 / 34%); animation: profile-frame-mithril 2.8s ease-in-out infinite; }
.profile__avatar[data-frame='king_aura'] { border-color: #f6d77a; box-shadow: 0 0 0 5px rgb(246 215 122 / 20%), 0 0 0 10px rgb(246 215 122 / 8%), 0 0 38px rgb(246 215 122 / 42%); animation: profile-frame-king-aura 2.6s ease-in-out infinite; }

@keyframes profile-frame-wheel {
  0%, 100% { box-shadow: 0 0 0 5px rgb(243 200 95 / 20%), 0 0 22px rgb(243 200 95 / 28%); }
  50% { box-shadow: 0 0 0 7px rgb(243 200 95 / 24%), 0 0 34px rgb(243 200 95 / 46%); }
}

@keyframes profile-frame-mithril {
  0%, 100% { box-shadow: 0 0 0 5px rgb(205 232 243 / 18%), 0 0 26px rgb(170 230 255 / 28%); }
  50% { box-shadow: 0 0 0 7px rgb(205 232 243 / 24%), 0 0 38px rgb(170 230 255 / 48%); }
}

@keyframes profile-frame-king-aura {
  0%, 100% { box-shadow: 0 0 0 5px rgb(246 215 122 / 20%), 0 0 0 10px rgb(246 215 122 / 8%), 0 0 30px rgb(246 215 122 / 32%); }
  50% { box-shadow: 0 0 0 7px rgb(246 215 122 / 28%), 0 0 0 13px rgb(246 215 122 / 12%), 0 0 48px rgb(246 215 122 / 55%); }
}

.profile__avatar--empty {
  display: grid;
  place-items: center;
  color: var(--role-action);
  font-size: 34px;
}

.profile__level {
  padding: 4px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: rgba(11, 13, 24, 0.72);
  color: var(--gold-strong);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.profile__who {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding-bottom: 8px;
}

.profile__name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 32px;
}

.profile__name .is-rainbow {
  background: linear-gradient(90deg, var(--role-enemy), var(--gold-strong), #6fe0a0, #4ec8e0);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.profile__title-chip {
  padding: 5px 10px;
  border: 1px solid color-mix(in srgb, var(--gold) 50%, transparent);
  border-radius: 999px;
  background: var(--gold-soft);
  color: var(--gold-strong);
  font-size: 14px;
}

.profile__status {
  margin: 0;
  color: var(--text);
  font-size: 15px;
}

.profile__signature {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.profile__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.profile__tag {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 12px;
}

.profile__hero-actions {
  position: absolute;
  top: 24px;
  right: 32px;
  z-index: 2;
}

.profile__edit-button {
  min-height: 44px;
  padding: 0 18px;
  border: 1px solid rgb(255 255 255 / 22%);
  border-radius: 11px;
  background: var(--role-action);
  color: #fff;
  font: inherit;
  font-size: 14px;
  font-weight: 750;
  cursor: pointer;
  box-shadow: 0 10px 28px rgb(39 198 236 / 24%);
}

.profile__edit-button:hover { filter: brightness(1.08); transform: translateY(-1px); }

.profile__bar-row,
.profile__rank,
.profile__stats,
.profile__block,
.profile__meta,
.profile__actions {
  margin-left: 26px;
  margin-right: 26px;
}

.profile__bar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.profile__bar {
  flex: 1 1 160px;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-sunken);
}

.profile__bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--role-success), var(--success));
}

.profile__bar-fill--rank {
  background: linear-gradient(90deg, var(--gold), var(--gold-strong));
}

.profile__bar-text {
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.profile__rank {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius-sm);
  background: var(--surface-deck);
}

.profile__rank-label {
  color: var(--gold-strong);
  font-size: 14px;
}

.profile__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.profile__stat {
  display: grid;
  gap: 2px;
  min-height: 106px;
  padding: 18px 16px;
  border: 1px solid rgba(42, 51, 88, 0.6);
  border-radius: var(--radius-sm);
  background: var(--surface-deck);
}

.profile__stat b {
  font-size: 28px;
  font-variant-numeric: tabular-nums;
}

.profile__stat span {
  color: var(--text-muted);
  font-size: 13px;
}

.profile__showcase {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) 96px minmax(0, 1fr);
  align-items: center;
  gap: 16px;
  margin: 2px 26px 0;
  padding: 18px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--role-action) 35%, var(--panel-line));
  border-radius: 12px;
  background: radial-gradient(circle at 50% 50%, rgb(124 92 240 / 13%), transparent 42%), var(--surface-deck);
}

.profile__showcase::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgb(255 255 255 / 3%), transparent);
  pointer-events: none;
}

.profile__showcase-feature h3 { margin: 0 0 9px; color: var(--text-primary); font-size: 20px; }
.profile__showcase-kicker { margin: 0 0 6px; color: var(--role-action); font-size: 10px; letter-spacing: .16em; }
.profile__featured-badge { display: flex; align-items: center; gap: 10px; }
.profile__featured-badge-mark { display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid var(--gold-strong); border-radius: 11px; background: var(--gold-soft); color: var(--gold-strong); font-size: 18px; box-shadow: 0 0 20px rgb(201 162 76 / 18%); }
.profile__featured-badge b,.profile__featured-badge small { display: block; }
.profile__featured-badge b { color: var(--text-primary); font-size: 16px; }
.profile__featured-badge small { margin-top: 3px; color: var(--text-muted); font-size: 13px; }
.profile__showcase-pulse { position: relative; display: grid; place-items: center; width: 76px; height: 76px; margin: 0 auto; }
.profile__showcase-pulse::before,.profile__showcase-pulse::after,.profile__showcase-pulse i { content: ''; position: absolute; border: 1px solid color-mix(in srgb, var(--role-action) 52%, transparent); border-radius: 50%; }
.profile__showcase-pulse::before { width: 24px; height: 24px; background: var(--role-action-soft); box-shadow: 0 0 22px rgb(124 92 240 / 24%); }
.profile__showcase-pulse::after { width: 52px; height: 52px; opacity: .55; }
.profile__showcase-pulse i:nth-child(1) { width: 72px; height: 72px; opacity: .22; }
.profile__showcase-pulse i:nth-child(2) { width: 7px; height: 7px; border: 0; background: var(--gold-strong); transform: translate(30px,-18px); }
.profile__showcase-pulse i:nth-child(3) { width: 5px; height: 5px; border: 0; background: var(--role-self); transform: translate(-27px,22px); }
.profile__cosmetics { min-width: 0; }
.profile__cosmetic-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.profile__cosmetic-list span { display: grid; grid-template-columns: 32px 1fr; grid-template-rows: auto auto; column-gap: 8px; align-items: center; min-height: 66px; padding: 9px; border: 1px solid var(--border-subtle); border-radius: 10px; background: var(--surface-sea); color: var(--text-secondary); }
.profile__cosmetic-list i { grid-row: 1 / -1; display: grid; place-items: center; width: 32px; height: 32px; border: 1px solid color-mix(in srgb, var(--gold) 44%, var(--border-subtle)); border-radius: 9px; background: var(--gold-soft); color: var(--gold-strong); font-style: normal; font-size: 16px; }
.profile__cosmetic-list b { color: var(--text-primary); font-size: 12px; }
.profile__cosmetic-list small { color: var(--text-muted); font-size: 10px; }
.profile__cosmetic-list span[data-kind='称号'] i { color: var(--gold-strong); }
.profile__cosmetic-list span[data-kind='头像框'] i { color: var(--role-self); }

.profile__block {
  padding: 12px 14px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius-sm);
  background: var(--surface-deck);
}

.profile__block-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 10px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 16px;
  letter-spacing: 0.06em;
}

.profile__badge-count {
  color: var(--accent-strong);
  letter-spacing: 0;
}

.profile__badge-list {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.profile__badge {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 9px 8px;
  border: 1px dashed var(--line-dash);
  border-radius: 8px;
  background: rgba(124, 92, 240, 0.06);
  text-align: center;
}

.profile__badge b {
  color: var(--gold-strong);
  font-size: 14px;
}

.profile__badge span {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.35;
}

.profile__badge.is-locked {
  opacity: 0.6;
}

.profile__badge.is-locked b {
  color: var(--text-muted);
}

.profile__fav-list,
.profile__history {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.profile__fav {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid rgba(124, 92, 240, 0.45);
  border-radius: 8px;
  background: var(--accent-soft);
  font-size: 12px;
}

.profile__fav small {
  color: var(--text-muted);
}

.profile__history {
  flex-direction: column;
  gap: 4px;
}

.profile__history-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--surface-deck);
  font-size: 12px;
}

.profile__history-time {
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

.profile__history-opp {
  flex: 1;
  min-width: 0;
}

.profile__history-row .is-win {
  color: var(--success);
}

.profile__history-row .is-lose {
  color: var(--role-enemy);
}

.profile__private {
  margin: 0;
  color: var(--text-dim);
  font-size: 13px;
}

.profile__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  padding-top: 10px;
  border-top: 1px dashed var(--line-dash);
  color: var(--text-muted);
  font-size: 11px;
}

.profile__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.profile__actions .button {
  min-height: 40px;
  padding: 8px 18px;
}

.profile__actions [data-testid='profile-settings-link'] {
  border-color: var(--accent-strong);
  background: var(--hero-grad);
  color: #fff;
}

.button--ghost {
  border-color: var(--border-strong);
  background: var(--surface-deck);
  color: var(--text-muted);
}

.profile-editor {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: grid;
  place-items: center;
  padding: 24px;
}

.profile-editor__backdrop {
  position: absolute;
  inset: 0;
  background: rgb(2 7 16 / 78%);
  backdrop-filter: blur(10px);
}

.profile-editor__panel {
  position: relative;
  display: grid;
  grid-template-rows: auto 1fr auto;
  width: min(1120px, 100%);
  max-height: min(820px, calc(100dvh - 48px));
  overflow: hidden;
  border: 1px solid var(--border-strong);
  border-radius: 20px;
  background: var(--surface-deck);
  box-shadow: 0 32px 100px rgb(0 0 0 / 48%);
}

.profile-editor__head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 28px 18px;
  border-bottom: 1px solid var(--border-subtle);
}

.profile-editor__head h2 { margin: 0; color: var(--text-primary); font-size: 25px; }
.profile-editor__status { margin: 0; color: var(--text-muted); font-size: 13px; }
.profile-editor__status.is-error { color: var(--danger); }

.profile-editor__body {
  display: grid;
  grid-template-columns: minmax(360px, .9fr) minmax(460px, 1.1fr);
  gap: 22px;
  min-height: 0;
  padding: 22px 28px;
  overflow: auto;
}

.profile-editor__preview {
  position: relative;
  min-height: 420px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--role-action) 42%, var(--panel-line));
  border-radius: 16px;
  background: linear-gradient(150deg, #182b54, #071323 82%);
}

.profile-editor__preview[data-bg='graphite'] { background: linear-gradient(150deg, #37414d, #101720 80%); }
.profile-editor__preview[data-bg='cyber'] { background: linear-gradient(150deg, #5b2f90, #102d4b 80%); }
.profile-editor__preview[data-bg='lava'] { background: linear-gradient(150deg, #8b3d29, #241113 80%); }
.profile-editor__preview[data-bg='dusk'] { background: linear-gradient(150deg, #6b477b, #171529 80%); }
.profile-editor__preview[data-bg='aurora'] { background: linear-gradient(150deg, #226d67, #0b2230 80%); }
.profile-editor__preview[data-bg='moonlit'] { background: linear-gradient(150deg, #2b4c83, #091329 80%); }
.profile-editor__preview[data-bg='coral_dawn'] { background: linear-gradient(150deg, #925067, #241321 80%); }
.profile-editor__preview[data-bg='abyssal_grid'] { background-color: #080d18; background-image: linear-gradient(rgb(201 162 76 / 8%) 1px, transparent 1px), linear-gradient(90deg, rgb(201 162 76 / 8%) 1px, transparent 1px); background-size: 24px 24px; }
.profile-editor__preview[data-bg='shoal'] { background: linear-gradient(150deg, #8d7553, #201a18 80%); }
.profile-editor__preview[data-bg='storm'] { background: linear-gradient(150deg, #3d4c5d, #111722 80%); }
.profile-editor__preview[data-bg='abyss'] { background: linear-gradient(150deg, #1d283d, #02050b 80%); }
.profile-editor__preview[data-bg='molten_gold'] { background: linear-gradient(150deg, #6b4b21, #18100b 80%); }
.profile-editor__preview[data-bg='starfield'] { background: radial-gradient(circle at 70% 24%, rgb(238 201 111 / 25%), transparent 4%), radial-gradient(circle at 24% 64%, rgb(111 224 244 / 22%), transparent 5%), linear-gradient(150deg, #182b5e, #060a18 80%); }
.profile-editor__preview[data-bg='season_deep_1'] { background: linear-gradient(150deg, #1d7691, #071522 80%); }
.profile-editor__preview-label { position: absolute; top: 18px; left: 20px; color: var(--cyan); font-size: 11px; letter-spacing: .16em; }
.profile-editor__preview-cover { position: absolute; inset: 0 0 auto; height: 190px; background: linear-gradient(120deg, rgb(122 90 240 / 88%), rgb(34 151 183 / 88%)); opacity: .82; }
.profile-editor__preview-identity { position: absolute; left: 24px; right: 24px; bottom: 110px; display: flex; align-items: center; gap: 14px; }
.profile-editor__preview-avatar { display: grid; place-items: center; width: 84px; height: 84px; border: 3px solid var(--role-action); border-radius: 50%; object-fit: cover; background: #182b54; color: #99ebff; font-size: 38px; box-shadow: 0 0 0 5px rgb(111 224 244 / 11%); }
.profile-editor__preview-avatar[data-frame='gold'] { border-color: var(--gold-strong); }
.profile-editor__preview-avatar[data-frame='silver'] { border-color: #c6d3dd; }
.profile-editor__preview-avatar[data-frame='aurora'] { border-color: var(--success); }
.profile-editor__preview-avatar[data-frame='crimson'] { border-color: #dd6b72; }
.profile-editor__preview-avatar[data-frame='abyssal_glow'] { border-color: #58d5ed; }
.profile-editor__preview-avatar[data-frame='tideglass'] { border-color: #9bd8e7; }
.profile-editor__preview-avatar[data-frame='ember_wake'] { border-color: #e78353; }
.profile-editor__preview-avatar[data-frame='star_compass'] { border-color: #e7c36a; }
.profile-editor__preview-avatar[data-frame='season_tide_ring'] { border-color: #8ee0ef; }
.profile-editor__preview-avatar[data-frame='bronze_compass'] { border-color: #c58a55; box-shadow: 0 0 0 5px rgb(197 138 85 / 18%), 0 0 20px rgb(197 138 85 / 28%); }
.profile-editor__preview-avatar[data-frame='silver_chain'] { border-color: #b7c9d8; box-shadow: 0 0 0 5px rgb(183 201 216 / 16%), 0 0 24px rgb(183 201 216 / 26%); }
.profile-editor__preview-avatar[data-frame='golden_wheel'] { border-color: #f3c85f; box-shadow: 0 0 0 5px rgb(243 200 95 / 20%), 0 0 28px rgb(243 200 95 / 36%); animation: profile-frame-wheel 4s linear infinite; }
.profile-editor__preview-avatar[data-frame='mithril_ring'] { border-color: #cde8f3; box-shadow: 0 0 0 5px rgb(205 232 243 / 18%), 0 0 28px rgb(170 230 255 / 34%); animation: profile-frame-mithril 2.8s ease-in-out infinite; }
.profile-editor__preview-avatar[data-frame='king_aura'] { border-color: #f6d77a; box-shadow: 0 0 0 5px rgb(246 215 122 / 20%), 0 0 0 10px rgb(246 215 122 / 8%), 0 0 34px rgb(246 215 122 / 42%); animation: profile-frame-king-aura 2.6s ease-in-out infinite; }
.profile-editor__preview-identity h3 { margin: 0; color: #fff; font-size: 25px; }
.profile-editor__preview-identity span { display: inline-block; margin-top: 7px; color: var(--gold-strong); font-size: 13px; }
.profile-editor__preview-status { position: absolute; left: 24px; right: 24px; bottom: 32px; margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }

.profile-editor__controls { min-width: 0; }
.profile-editor__tabs { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin-bottom: 18px; }
.profile-editor__tabs button { min-height: 44px; border: 1px solid var(--border-subtle); border-radius: 10px; background: var(--surface-sea); color: var(--text-muted); font: inherit; font-size: 13px; cursor: pointer; }
.profile-editor__tabs button.is-active { border-color: var(--role-action); background: var(--role-action-soft); color: var(--text-primary); box-shadow: inset 0 -2px var(--role-action); }
.profile-editor__options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.profile-editor__option { position: relative; display: grid; align-content: start; gap: 7px; min-height: 128px; padding: 14px; border: 1px solid var(--border-subtle); border-radius: 12px; background: var(--surface-sea); color: var(--text-muted); text-align: left; cursor: pointer; }
.profile-editor__option:hover:not(:disabled) { border-color: var(--role-action); transform: translateY(-1px); }
.profile-editor__option.is-selected { border-color: var(--role-action); background: var(--role-action-soft); box-shadow: inset 0 0 0 1px var(--role-action); }
.profile-editor__option.is-locked { opacity: .55; cursor: not-allowed; }
.profile-editor__option-mark { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: var(--gold-soft); color: var(--gold-strong); font-size: 18px; }
.profile-editor__option b { color: var(--text-primary); font-size: 14px; }
.profile-editor__option small { min-height: 28px; color: var(--text-muted); font-size: 11px; line-height: 1.4; }
.profile-editor__option em { position: absolute; top: 12px; right: 12px; color: var(--success); font-size: 10px; font-style: normal; }
.profile-editor__field { display: grid; gap: 9px; color: var(--text-secondary); font-size: 13px; }
.profile-editor__field textarea { resize: vertical; padding: 12px; border: 1px solid var(--border-subtle); border-radius: 10px; background: var(--surface-sea); color: var(--text-primary); font: inherit; line-height: 1.6; }
.profile-editor__field small { color: var(--text-muted); text-align: right; }
.profile-editor__actions { display: flex; justify-content: flex-end; gap: 10px; padding: 16px 28px 22px; border-top: 1px solid var(--border-subtle); }
.profile-editor__actions .button { min-width: 124px; min-height: 44px; }
.profile-editor__save { border-color: var(--role-action); background: var(--role-action); color: #fff; }

.profile__quick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 1120px;
  max-width: 100%;
  padding: 0 0 10px;
}

.profile__quick-item {
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: var(--surface-chamber);
  color: var(--text-secondary);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.profile__quick-item:hover {
  border-color: var(--role-self);
  color: var(--text-primary);
  background: var(--role-self-soft);
}

@media (max-width: 719px) {
  .profile__quick-item,
  .profile__actions .button,
  .profile__actions button,
  .profile__history-row button {
    min-height: 44px;
    min-width: 44px;
  }
}

@media (max-width: 760px) {
  .profile {
    padding: 0 12px 30px;
  }

  .profile__head {
    padding: 12px 16px 8px;
  }

  .profile__hero {
    padding: 104px 16px 8px;
  }

  .profile__hero::before {
    height: 128px;
  }

  .profile__avatar {
    width: 68px;
    height: 68px;
  }

  .profile__bar-row,
  .profile__rank,
  .profile__stats,
  .profile__block,
  .profile__meta,
  .profile__actions {
    margin-left: 16px;
    margin-right: 16px;
  }

  .profile__badge-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .profile__stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
  }

  .profile__showcase {
    grid-template-columns: 1fr;
    gap: 12px;
    margin-left: 16px;
    margin-right: 16px;
  }

  .profile__showcase-pulse { display: none; }

  .profile__hero { padding-top: 132px; }
  .profile__hero-actions { top: 18px; right: 16px; }
  .profile__edit-button { min-height: 40px; padding: 0 13px; font-size: 12px; }
  .profile__name { font-size: 26px; }
  .profile__avatar { width: 104px; height: 104px; }
  .profile-editor { padding: 10px; }
  .profile-editor__body { grid-template-columns: 1fr; }
  .profile-editor__preview { min-height: 300px; }
  .profile-editor__options { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
