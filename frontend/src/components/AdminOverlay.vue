<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppOverlay from './AppOverlay.vue'

/**
 * 反作弊管理弹层（原 main `#admin-modal` + `static/admin.js` 的 Vue 迁移）。
 *
 * ⚠️ 前端这里只是「别让普通玩家看到一个点不动的按钮」：真正的门禁在服务端
 * （`api._admin_required()`，非管理员一律 403）。入口按 `/api/admin/me` 的
 * `is_admin` 决定是否渲染。
 */
const emit = defineEmits<{ (event: 'close'): void }>()

interface PlayerRow {
  user_id: string
  username?: string
  suspicion?: number
  level?: number
  level_name?: string
  next_threshold?: number
  blocked?: string[]
  overridden?: boolean
  match_count?: number
}

interface PlayerDetail extends PlayerRow {
  stats?: {
    wins?: number
    losses?: number
    win_rate?: number
    rank_points?: number
    ranked_wins?: number
    ranked_losses?: number
  }
  flagged_matches?: Array<{ severity?: string; rule?: string; detail?: string }>
  override_history?: Array<{
    level?: number
    cleared?: boolean
    reason?: string
    actor?: string
    created_at?: number
  }>
}

const tab = ref<'list' | 'detail'>('list')
const players = ref<PlayerRow[]>([])
const detail = ref<PlayerDetail | null>(null)
const search = ref('')
const loading = ref(false)
const error = ref('')
const detailLoading = ref(false)
const detailError = ref('')
const reason = ref('')
const busy = ref(false)

const CAPABILITY_LABEL: Record<string, string> = { ranked: '排位赛', match: '匹配', room: '房间' }
const LEVEL_LABEL: Record<number, string> = { 0: '正常', 1: '禁排位', 2: '禁匹配', 3: '禁房间' }

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return players.value
  return players.value.filter((row) => String(row.username || '').toLowerCase().includes(q))
})

function errorText(data: unknown, fallback: string): string {
  const body = data as { error?: string } | null
  return body && typeof body.error === 'string' ? body.error : fallback
}

async function loadList(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/admin/suspicion?limit=300', { headers: { accept: 'application/json' } })
    const data = (await response.json().catch(() => null)) as
      | { success?: boolean; players?: PlayerRow[]; error?: string }
      | null
    if (!response.ok || !data?.success) {
      error.value = errorText(data, response.status === 403 ? '无权访问' : '读取失败')
      players.value = []
      return
    }
    players.value = Array.isArray(data.players) ? data.players : []
  } catch {
    error.value = '读取失败（网络）'
    players.value = []
  } finally {
    loading.value = false
  }
}

async function openPlayer(userId: string): Promise<void> {
  tab.value = 'detail'
  detailLoading.value = true
  detailError.value = ''
  try {
    const response = await fetch(`/api/admin/player/${encodeURIComponent(userId)}`, {
      headers: { accept: 'application/json' },
    })
    const data = (await response.json().catch(() => null)) as
      | { success?: boolean; player?: PlayerDetail; error?: string }
      | null
    if (!response.ok || !data?.success || !data.player) {
      detailError.value = errorText(data, '读取失败')
      detail.value = null
      return
    }
    detail.value = data.player
    reason.value = ''
  } catch {
    detailError.value = '读取失败（网络）'
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

async function override(payload: Record<string, unknown>): Promise<void> {
  const player = detail.value
  if (!player || busy.value) return
  busy.value = true
  detailError.value = ''
  try {
    const response = await fetch(`/api/admin/player/${encodeURIComponent(player.user_id)}/override`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: JSON.stringify({ ...payload, reason: reason.value }),
    })
    const data = (await response.json().catch(() => null)) as { success?: boolean; error?: string } | null
    if (!response.ok || !data?.success) {
      detailError.value = errorText(data, '处置失败')
      return
    }
    await openPlayer(player.user_id)
    await loadList()
  } catch {
    detailError.value = '处置失败（网络）'
  } finally {
    busy.value = false
  }
}

function fmtTime(value?: number): string {
  if (!value) return ''
  const date = new Date(value * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function historyText(entry: NonNullable<PlayerDetail['override_history']>[number]): string {
  if (entry.cleared) return '解除限制'
  const level = typeof entry.level === 'number' ? entry.level : undefined
  return level === undefined ? '未知处置' : '设为 ' + (LEVEL_LABEL[level] ?? String(level))
}

function close(): void {
  emit('close')
}

onMounted(loadList)
</script>

<template>
  <AppOverlay id="admin-overlay" labelledby="admin-overlay-title" @close="close">
    <header class="admin__head">
      <div>
        <p class="ui-kicker">运营 · 反作弊</p>
        <h2 id="admin-overlay-title" class="admin__title">反作弊管理</h2>
      </div>
      <div class="admin__head-actions">
        <button type="button" class="button button--ghost" data-testid="admin-refresh" @click="loadList">刷新</button>
        <button type="button" class="button button--ghost" data-testid="admin-close" @click="close">关闭</button>
      </div>
    </header>

    <div class="admin__tabs" role="tablist" aria-label="反作弊视图">
      <button
        type="button"
        role="tab"
        class="admin__tab"
        :class="{ 'is-active': tab === 'list' }"
        :aria-selected="tab === 'list'"
        data-testid="admin-tab-list"
        @click="tab = 'list'"
      >
        嫌疑度总览
      </button>
      <button
        type="button"
        role="tab"
        class="admin__tab"
        :class="{ 'is-active': tab === 'detail' }"
        :aria-selected="tab === 'detail'"
        data-testid="admin-tab-detail"
        @click="tab = 'detail'"
      >
        玩家详情
      </button>
    </div>

    <section v-if="tab === 'list'" class="admin__view" data-testid="admin-list">
      <div class="admin__toolbar">
        <input
          v-model="search"
          type="text"
          class="admin__search"
          placeholder="搜索用户名…"
          autocomplete="off"
          data-testid="admin-search"
        />
        <span class="admin__count">共 {{ filtered.length }} 人</span>
      </div>
      <p v-if="error" class="admin__error" role="alert" data-testid="admin-error">{{ error }}</p>
      <p v-else-if="loading" class="admin__empty">加载中…</p>
      <p v-else-if="!filtered.length" class="admin__empty">暂无数据。</p>
      <ul v-else class="admin__rows">
        <li v-for="row in filtered" :key="row.user_id">
          <button
            type="button"
            class="admin__row"
            :data-testid="'admin-row-' + row.user_id"
            @click="openPlayer(row.user_id)"
          >
            <span class="admin__row-name">{{ row.username || '(已删除)' }}</span>
            <span class="admin__badge" :class="'is-lvl-' + (row.level ?? 0)">{{ row.level_name || '正常' }}</span>
            <span class="admin__row-suspicion">嫌疑度 {{ row.suspicion ?? 0 }}</span>
            <span v-if="row.overridden" class="admin__badge is-lvl-blue">已干预</span>
            <span v-if="(row.blocked || []).length" class="admin__row-blocked">
              {{ (row.blocked || []).map((c) => '禁' + (CAPABILITY_LABEL[c] || c)).join(' / ') }}
            </span>
          </button>
        </li>
      </ul>
    </section>

    <section v-else class="admin__view" data-testid="admin-detail-view">
      <p v-if="detailError" class="admin__error" role="alert" data-testid="admin-detail-error">{{ detailError }}</p>
      <p v-else-if="detailLoading" class="admin__empty">加载中…</p>
      <p v-else-if="!detail" class="admin__empty">从左侧列表点一个玩家。</p>
      <article v-else class="admin__detail" data-testid="admin-detail">
        <header class="admin__detail-head">
          <h3 class="admin__detail-name">{{ detail.username || '(已删除)' }}</h3>
          <span class="admin__badge" :class="'is-lvl-' + (detail.level ?? 0)">{{ detail.level_name || '正常' }}</span>
          <span class="admin__detail-suspicion">
            嫌疑度 <b>{{ detail.suspicion ?? 0 }}</b>
            <template v-if="(detail.next_threshold ?? 0) > 0">（距下一档还差 {{ detail.next_threshold }}）</template>
            <template v-else>（已最高档）</template>
          </span>
        </header>

        <h4 class="admin__subtitle">战绩</h4>
        <div class="admin__stats">
          <span>总胜 {{ detail.stats?.wins ?? 0 }}</span>
          <span>总负 {{ detail.stats?.losses ?? 0 }}</span>
          <span>胜率 {{ Math.round(Number(detail.stats?.win_rate ?? 0) * 100) }}%</span>
          <span>排位分 {{ detail.stats?.rank_points ?? 0 }}</span>
          <span>排位 {{ detail.stats?.ranked_wins ?? 0 }}胜 {{ detail.stats?.ranked_losses ?? 0 }}负</span>
        </div>

        <h4 class="admin__subtitle">当前限制</h4>
        <div v-if="(detail.blocked || []).length" class="admin__blocked">
          <span v-for="cap in detail.blocked" :key="cap" class="admin__badge is-lvl-red">
            禁{{ CAPABILITY_LABEL[cap] || cap }}
          </span>
        </div>
        <p v-else class="admin__ok">无限制</p>

        <h4 class="admin__subtitle">手动处置</h4>
        <div class="admin__actions">
          <input
            v-model="reason"
            type="text"
            class="admin__search"
            placeholder="理由（会记入审计日志）"
            autocomplete="off"
            data-testid="admin-reason"
          />
          <div class="admin__btnrow">
            <button type="button" class="button button--ghost" :disabled="busy" data-testid="admin-clear" @click="override({ cleared: true })">
              解除限制
            </button>
            <button type="button" class="button button--ghost" :disabled="busy" data-testid="admin-set1" @click="override({ level: 1 })">
              禁排位
            </button>
            <button type="button" class="button button--ghost" :disabled="busy" data-testid="admin-set2" @click="override({ level: 2 })">
              禁匹配
            </button>
            <button type="button" class="button button--ghost" :disabled="busy" data-testid="admin-set3" @click="override({ level: 3 })">
              禁房间
            </button>
          </div>
        </div>

        <h4 class="admin__subtitle">违规记录（{{ (detail.flagged_matches || []).length }}）</h4>
        <div v-if="(detail.flagged_matches || []).length" class="admin__flags" data-testid="admin-flags">
          <div v-for="(flag, index) in (detail.flagged_matches || []).slice(0, 30)" :key="index" class="admin__flag">
            <span class="admin__badge is-lvl-orange">{{ flag.severity }}</span>
            <span class="admin__flag-rule">{{ flag.rule }}</span>
            <span class="admin__flag-detail">{{ flag.detail }}</span>
          </div>
        </div>
        <p v-else class="admin__ok">没有可疑对局记录。</p>

        <h4 class="admin__subtitle">干预历史（{{ (detail.override_history || []).length }}）</h4>
        <div v-if="(detail.override_history || []).length" class="admin__history" data-testid="admin-history">
          <div v-for="(entry, index) in detail.override_history" :key="index" class="admin__hist-row">
            <span>{{ fmtTime(entry.created_at) }}</span>
            <span>{{ historyText(entry) }}</span>
            <span>{{ entry.reason || '-' }}</span>
            <span>{{ entry.actor || '-' }}</span>
          </div>
        </div>
        <p v-else class="admin__ok" data-testid="admin-history">没有干预记录。</p>
      </article>
    </section>
  </AppOverlay>
</template>

<style scoped>
.admin__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.admin__title {
  margin: 2px 0 0;
  font-size: 22px;
  letter-spacing: 0;
}

.admin__head-actions {
  display: flex;
  gap: 8px;
}

.admin__tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 8px;
}

.admin__tab {
  height: 34px;
  padding: 0 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  color: var(--text-secondary);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.admin__tab.is-active {
  border-color: var(--role-action);
  background: var(--role-action-soft);
  color: var(--text-primary);
}

.admin__view {
  min-height: 220px;
}

.admin__toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.admin__search {
  flex: 1 1 auto;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: 13px;
}

.admin__count {
  color: var(--text-tertiary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.admin__rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: min(52vh, 420px);
  overflow-y: auto;
}

.admin__row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.admin__row:hover {
  border-color: var(--role-action);
}

.admin__row-name {
  min-width: 120px;
  font-weight: 600;
}

.admin__row-suspicion,
.admin__row-blocked {
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}

.admin__badge {
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border-subtle);
  background: var(--surface-deck);
  font-size: 11px;
  color: var(--text-secondary);
}

.admin__badge.is-lvl-1,
.admin__badge.is-lvl-2,
.admin__badge.is-lvl-3,
.admin__badge.is-lvl-red {
  border-color: color-mix(in srgb, var(--role-enemy) 55%, transparent);
  color: var(--role-enemy);
}

.admin__badge.is-lvl-orange {
  border-color: color-mix(in srgb, var(--role-warning) 55%, transparent);
  color: var(--role-warning);
}

.admin__badge.is-lvl-blue {
  border-color: color-mix(in srgb, var(--role-self) 55%, transparent);
  color: var(--role-self);
}

.admin__detail-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 6px;
}

.admin__detail-name {
  margin: 0;
  font-size: 17px;
}

.admin__detail-suspicion {
  color: var(--text-secondary);
  font-size: 12.5px;
}

.admin__subtitle {
  margin: 16px 0 8px;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.admin__stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  font-size: 12.5px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.admin__blocked {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.admin__actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.admin__btnrow {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.admin__flags,
.admin__history {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: min(30vh, 220px);
  overflow-y: auto;
}

.admin__flag,
.admin__hist-row {
  display: flex;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
  font-size: 12px;
  color: var(--text-secondary);
}

.admin__hist-row {
  justify-content: space-between;
  font-variant-numeric: tabular-nums;
}

.admin__empty,
.admin__ok,
.admin__error {
  margin: 4px 0;
  font-size: 12.5px;
  color: var(--text-tertiary);
}

.admin__error {
  color: var(--role-enemy);
}
</style>
