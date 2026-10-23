import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'

export type CardStatus = 'idle' | 'loading' | 'ready' | 'missing' | 'error'
export type StatsRecord = Record<string, unknown>

export interface PlayerCard {
  status: CardStatus
  stats: StatsRecord | null
}

/**
 * 局内双方的公开资料（头像 / 战绩），走既有的 GET /user_stats?username=。
 * 隐私字段由服务端先过滤；这里不补默认值、不编造头像。游客、人机、查无此人
 * 都落到 `missing`，界面据此退回首字占位。
 */
export function usePlayerCards(options: {
  selfName: Ref<string>
  opponentName: Ref<string>
  opponentIsAi: Ref<boolean>
  /** 服务端可信的 opponent_registered；缺省/false 一律不查对手资料。 */
  opponentRegistered: Ref<boolean>
}) {
  const self = ref<PlayerCard>({ status: 'idle', stats: null })
  const opponent = ref<PlayerCard>({ status: 'idle', stats: null })
  const tokens = { self: 0, opponent: 0 }
  const controllers: Record<'self' | 'opponent', AbortController | null> = { self: null, opponent: null }

  async function load(side: 'self' | 'opponent', name: string, skip: boolean): Promise<void> {
    const target = side === 'self' ? self : opponent
    const token = ++tokens[side]
    controllers[side]?.abort()
    controllers[side] = null
    if (!name || skip) {
      target.value = { status: 'missing', stats: null }
      return
    }
    target.value = { status: 'loading', stats: null }
    const controller = new AbortController()
    controllers[side] = controller
    try {
      const response = await fetch('/user_stats?username=' + encodeURIComponent(name) + '&limit=1', {
        headers: { accept: 'application/json' },
        credentials: 'same-origin',
        signal: controller.signal,
      })
      if (token !== tokens[side]) return
      if (!response.ok) {
        target.value = { status: 'error', stats: null }
        return
      }
      const body = (await response.json().catch(() => null)) as { stats?: unknown } | null
      const stats = body?.stats && typeof body.stats === 'object' && !Array.isArray(body.stats)
        ? (body.stats as StatsRecord)
        : null
      target.value = stats ? { status: 'ready', stats } : { status: 'missing', stats: null }
    } catch (error) {
      if (token !== tokens[side]) return
      if ((error as { name?: string })?.name === 'AbortError') return
      target.value = { status: 'error', stats: null }
    }
  }

  watch(options.selfName, (name) => void load('self', name, false), { immediate: true })
  watch(
    [options.opponentName, options.opponentIsAi, options.opponentRegistered],
    ([name, ai, registered]) => void load('opponent', name, ai || !registered),
    { immediate: true },
  )

  function avatarOf(card: PlayerCard): string {
    const value = card.stats?.avatar
    return typeof value === 'string' ? value : ''
  }

  const selfAvatar = computed(() => avatarOf(self.value))
  const opponentAvatar = computed(() => avatarOf(opponent.value))

  onBeforeUnmount(() => {
    tokens.self++
    tokens.opponent++
    controllers.self?.abort()
    controllers.opponent?.abort()
  })

  return { self, opponent, selfAvatar, opponentAvatar, reload: load }
}
