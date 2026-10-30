import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Leaderboard view state (ticket #25).
 *
 * The two boards are two independent data sources with independent loading and
 * error states (port map 14 §1.8): switching one must never blank the other.
 * Rows are server-ordered; the client only formats them and never re-sorts or
 * recomputes a rank.
 */
export type JsonObject = Record<string, unknown>
export type BoardTab = 'record' | 'ranked'
export type BoardStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface BoardState {
  status: BoardStatus
  rows: JsonObject[]
  error: string
  total: number
  /** Server-order position of the viewer on this board; null = not ranked. */
  myRank: number | null
}

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function asObjects(value: unknown): JsonObject[] {
  return Array.isArray(value)
    ? value.filter((item): item is JsonObject => asObject(item) !== null)
    : []
}

async function getJson(url: string): Promise<unknown> {
  const response = await fetch(url, { headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error('网络错误 ' + response.status)
  return response.json()
}

function emptyBoard(): BoardState {
  return { status: 'idle', rows: [], error: '', total: 0, myRank: null }
}

export const useLeaderboardStore = defineStore('leaderboard', () => {
  const activeTab = ref<BoardTab>('record')
  const record = ref<BoardState>(emptyBoard())
  const ranked = ref<BoardState>(emptyBoard())

  let recordToken = 0
  let rankedToken = 0

  async function loadRecord(): Promise<void> {
    const token = ++recordToken
    record.value = { status: 'loading', rows: record.value.rows, error: '', total: 0, myRank: null }
    try {
      const data = await getJson('/api/leaderboard')
      if (token !== recordToken) return
      if (!Array.isArray(data)) throw new Error('战绩榜数据异常')
      record.value = { status: 'ready', rows: asObjects(data), error: '', total: data.length, myRank: null }
    } catch (error) {
      if (token !== recordToken) return
      record.value = {
        status: 'error',
        rows: record.value.rows,
        error: error instanceof Error ? error.message : String(error),
        total: 0,
        myRank: null,
      }
    }
  }

  async function loadRanked(): Promise<void> {
    const token = ++rankedToken
    ranked.value = { status: 'loading', rows: ranked.value.rows, error: '', total: ranked.value.total, myRank: null }
    try {
      const data = await getJson('/api/ranked_leaderboard?limit=100&offset=0')
      if (token !== rankedToken) return
      const body = asObject(data)
      const rows = body ? body.leaderboard : null
      if (!Array.isArray(rows)) throw new Error('段位榜数据异常')
      const myRank = Number(body ? body.my_rank : NaN)
      ranked.value = {
        status: 'ready',
        rows: asObjects(rows),
        error: '',
        total: typeof body?.total === 'number' ? body.total : rows.length,
        // Ticket #43 exposes the viewer's full-server position; null = unranked.
        myRank: Number.isFinite(myRank) && myRank > 0 ? myRank : null,
      }
    } catch (error) {
      if (token !== rankedToken) return
      ranked.value = {
        status: 'error',
        rows: ranked.value.rows,
        error: error instanceof Error ? error.message : String(error),
        total: 0,
        myRank: null,
      }
    }
  }

  function setTab(tab: BoardTab): void {
    const want: BoardTab = tab === 'ranked' ? 'ranked' : 'record'
    activeTab.value = want
    // The ranked board is computed per request, so it is fetched only when the
    // player actually opens it. Returning to the wins board keeps its rows.
    if (want === 'ranked') void loadRanked()
  }

  const active = computed(() => (activeTab.value === 'ranked' ? ranked.value : record.value))

  function reset(): void {
    activeTab.value = 'record'
    record.value = emptyBoard()
    ranked.value = emptyBoard()
  }

  return { activeTab, record, ranked, active, loadRecord, loadRanked, setTab, reset }
})
