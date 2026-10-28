<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { createAiRoom, emitFindMatch } from '../../realtime/home'
import { acquireSettlementChannel, getSettlementSocket } from '../../realtime/settlement'
import { useGameStore } from '../../stores/game'
import { useHomeStore } from '../../stores/home'
import { usePlacementStore } from '../../stores/placement'
import { useResultStore } from '../../stores/result'
import { useUiStore } from '../../stores/ui'
import { useAudioStore } from '../../stores/audio'
import {
  aiDifficulty,
  matchModeLabel,
  matchModeOf,
  outcomeOf,
  progressPercent,
  readArray,
  readBoolean,
  readNumber,
  readObject,
  readString,
  signed,
  summaryText,
  toObjects,
  verdictText,
  type MatchMode,
  type Outcome,
} from './view'

/**
 * Ticket #22: the settlement screen (sample screen for the P3 migration).
 *
 * The view model lives in the Pinia stores; this component only renders it.
 * game_over arrives over the real socket channel, while xp/rank/badges are
 * optional follow-ups. A direct deep link (or a refresh after the server state
 * is gone) must never leave a white page, so the empty state is part of the
 * contract.
 */
const router = useRouter()
const game = useGameStore()
const home = useHomeStore()
const placement = usePlacementStore()
const result = useResultStore()
const ui = useUiStore()

let releaseChannel: (() => void) | null = null
let barTimer: ReturnType<typeof setTimeout> | null = null
let settleTimer: ReturnType<typeof setTimeout> | null = null

/**
 * Ticket #48: the three exits are three different actions.
 *  - 再来一局 re-queues the same mode (AI: same difficulty) and hands off to the
 *    normal matchmaking / placement flow; the settlement store is cleared only
 *    once the new match really starts.
 *  - 返回大厅 and 返回首页 go to two different screens.
 * The current match's mode comes from the game store (recorded at match start),
 * the AI difficulty from the last AI launch (localStorage bs.aiDifficulty,
 * default normal).
 */
const busy = ref(false)
const barsShown = ref(false)
const barsSettled = ref(false)
const barsInstant = ref(false)
const friendState = ref<'idle' | 'sending' | 'sent' | 'error'>('idle')
const friendMessage = ref('')

onMounted(() => {
  releaseChannel = acquireSettlementChannel()
  runBars()
})

onBeforeUnmount(() => {
  releaseChannel?.()
  releaseChannel = null
  if (barTimer !== null) clearTimeout(barTimer)
  if (settleTimer !== null) clearTimeout(settleTimer)
})

const gameOver = computed(() => result.gameOver)
const hasResult = computed(() => gameOver.value !== null)
const matchId = computed(() => result.gameOverMatchId)
const outcome = computed<Outcome>(() => outcomeOf(gameOver.value, game.state.player_id))
watch([hasResult, outcome], () => {
  if (hasResult.value) useAudioStore().playOutcome(game.state.room_id || matchId.value, outcome.value)
}, { immediate: true })
const verdict = computed(() => verdictText(outcome.value))
const summary = computed(() => {
  const record = gameOver.value
  if (!record) return ''
  return summaryText(record, outcome.value, game.state.round)
})

const selfName = computed(() => game.state.player_name || '你')
const opponentName = computed(() => game.state.opponent_name || '对手')
// Unknown values are hidden, never a row of "—" (spec story 93). The seat line
// only exists when the server really stamped a seat label.
const seatLabel = computed(() => game.state.player_seat || '')
const modeKey = computed<MatchMode>(() =>
  matchModeOf(game.state.ranked, game.state.mode, game.state.is_ai_room),
)
const modeLabel = computed(() => matchModeLabel(modeKey.value))

const attacks = computed(() => (Array.isArray(game.state.attacks) ? game.state.attacks : []))
const hits = computed(() => attacks.value.filter((cell) => cell && cell.hit).length)
const roundText = computed(() => (hasResult.value && game.state.round > 0 ? String(game.state.round) : ''))
const fireText = computed(() =>
  hasResult.value && attacks.value.length ? hits.value + ' / ' + attacks.value.length : '',
)
const shipsText = computed(() =>
  hasResult.value ? game.state.remaining_ships + ' / ' + game.state.opponent_remaining_ships : '',
)
const hasStats = computed(() => Boolean(roundText.value || fireText.value || shipsText.value))

const rank = computed(() => result.rank)
const rankDeltaText = computed(() => signed(readNumber(rank.value, 'delta') ?? 0))
const rankRole = computed(() => {
  const role = readString(rank.value, 'role')
  if (role === 'winner') return '胜方'
  if (role === 'loser') return '败方'
  return ''
})
const rankBeforeLabel = computed(() => readString(readObject(rank.value, 'before'), 'label'))
const rankAfterLabel = computed(() => readString(readObject(rank.value, 'after'), 'label'))
const showRankTiers = computed(() => Boolean(rankBeforeLabel.value && rankAfterLabel.value))
const rankFill = computed(() => {
  const after = readObject(rank.value, 'after')
  return progressPercent(readNumber(after, 'progress'), readNumber(after, 'sub_points'))
})
const rankNote = computed(() => {
  if (!rank.value) return ''
  if (readBoolean(rank.value, 'clamped')) return '已到最低分，本局不再扣分'
  if (readBoolean(rank.value, 'admiral_promoted')) return '晋升大舰长'
  if (readBoolean(rank.value, 'admiral_demoted')) return '大舰长资格已失效'
  if (readBoolean(rank.value, 'promoted')) return '段位提升'
  if (readBoolean(rank.value, 'demoted')) return '段位下降'
  return ''
})

const xp = computed(() => result.xp)
const xpBefore = computed(() => readObject(xp.value, 'before'))
const xpAfter = computed(() => readObject(xp.value, 'after'))
const xpDeltaText = computed(() => '+' + (readNumber(xp.value, 'delta') ?? 0))
const xpLevelText = computed(() => 'Lv.' + (readNumber(xpAfter.value, 'level') ?? 1))
const xpNeed = computed(() => readNumber(xpAfter.value, 'need') ?? 0)
const xpInto = computed(() => readNumber(xpAfter.value, 'into') ?? 0)
const xpProgressText = computed(() => (xpNeed.value > 0 ? xpInto.value + ' / ' + xpNeed.value : '满级'))
const xpFill = computed(() => (xpNeed.value > 0 ? progressPercent(xpInto.value, xpNeed.value) : 100))
const xpLevelUpText = computed(() => {
  const before = readNumber(xpBefore.value, 'level')
  const after = readNumber(xpAfter.value, 'level')
  return before !== null && after !== null && after > before
    ? '升级！Lv.' + before + ' → Lv.' + after
    : ''
})
const xpBreakdown = computed(() =>
  toObjects(readArray(xp.value, 'breakdown')).map((item) => ({
    label: readString(item, 'label'),
    xp: readNumber(item, 'xp') ?? 0,
  })),
)
const achievementItems = computed(() => result.achievements)

/** Bars: a 600ms CSS reveal that can be skipped; no bar lasts beyond 2s. */
function runBars(): void {
  if (barTimer !== null) clearTimeout(barTimer)
  if (settleTimer !== null) clearTimeout(settleTimer)
  barTimer = null
  settleTimer = null
  barsShown.value = false
  barsInstant.value = false
  barsSettled.value = false
  if (!result.rank && !result.xp) {
    barsSettled.value = true
    return
  }
  barTimer = setTimeout(() => {
    barsShown.value = true
  }, 40)
  settleTimer = setTimeout(() => {
    barsSettled.value = true
  }, 900)
}

function skipBars(): void {
  if (barTimer !== null) clearTimeout(barTimer)
  if (settleTimer !== null) clearTimeout(settleTimer)
  barTimer = null
  settleTimer = null
  barsInstant.value = true
  barsShown.value = true
  barsSettled.value = true
}

watch(
  () => [Boolean(result.rank), Boolean(result.xp)],
  () => {
    if (result.rank || result.xp) runBars()
  },
)

const rankBarWidth = computed(() => (barsShown.value ? rankFill.value : 0))
const xpBarWidth = computed(() => (barsShown.value ? xpFill.value : 0))
const barsAnimating = computed(() => !barsSettled.value && Boolean(result.rank || result.xp))

/**
 * The opponent as a person, not a string: the server's private recent_opponent
 * frame carries the account id only when both seats are accounts (AI / guest
 * seats have none), so the friend and profile actions appear exactly then.
 */
const opponent = computed(() => result.recentOpponent)
const opponentUsername = computed(() => readString(opponent.value, 'username'))
const opponentRelation = computed(() => readString(opponent.value, 'relation'))
const opponentNameText = computed(() => opponentUsername.value || opponentName.value)
const showAddFriend = computed(
  () =>
    Boolean(opponentUsername.value) &&
    opponentRelation.value !== 'friend' &&
    opponentRelation.value !== 'self',
)
const friendButtonText = computed(() => {
  if (friendState.value === 'sending') return '发送中…'
  if (friendState.value === 'sent') return '已发送申请'
  return '加对手好友'
})

async function addFriend(): Promise<void> {
  const username = opponentUsername.value
  if (!username || friendState.value === 'sending' || friendState.value === 'sent') return
  friendState.value = 'sending'
  friendMessage.value = ''
  try {
    const response = await fetch('/api/friends/request', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', accept: 'application/json' },
      body: JSON.stringify({ username }),
    })
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>
    if (!response.ok) {
      friendState.value = 'error'
      friendMessage.value =
        typeof body.error === 'string' ? body.error : '好友申请发送失败，请稍后再试'
      return
    }
    const status = typeof body.status === 'string' ? body.status : ''
    if (status === 'sent' || status === 'pending') {
      friendState.value = 'sent'
      friendMessage.value = '好友申请已发送，等对方通过'
      return
    }
    if (status === 'friend') {
      friendState.value = 'sent'
      friendMessage.value = '你们已经是好友了'
      return
    }
    friendState.value = 'error'
    friendMessage.value =
      status === 'self'
        ? '不能加自己为好友'
        : typeof body.error === 'string'
          ? body.error
          : '好友申请发送失败，请稍后再试'
  } catch {
    friendState.value = 'error'
    friendMessage.value = '网络不稳定，请稍后再试'
  }
}

function openOpponentProfile(): void {
  if (!opponentUsername.value) return
  void router.push({ name: 'profile', query: { username: opponentUsername.value } })
}

function resetSettlement(): void {
  result.reset()
  game.reset()
}

function returnHome(): void {
  resetSettlement()
  void router.push({ name: 'start' })
}

/** 返回大厅 is a different destination from 返回首页 (spec story 97). */
function returnLobby(): void {
  resetSettlement()
  void router.push({ name: 'lobby' })
}

/**
 * 再来一局: queue again with this match's mode, or reopen an AI room with the
 * same difficulty. Custom rooms cannot be re-opened from the settlement (the
 * room is gone), so that mode offers only the two exits.
 */
async function socketReady(socket: ReturnType<typeof getSettlementSocket>, timeoutMs = 3000): Promise<boolean> {
  if (!socket) return false
  if (socket.socket.connected) return true
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 50))
    if (socket.socket.connected) return true
  }
  return false
}

async function playAgain(): Promise<void> {
  if (busy.value) return
  const key = modeKey.value
  if (key === 'custom') {
    // Ticket #52: the custom room is gone after settlement, so "再来一局" can
    // never become "返回大厅" (spec §7: the three exits are different actions).
    ui.notify({ code: 'settlement-play-again-custom', tone: 'info', message: '自定义房间不能重开，回大厅再开一桌。' })
    return
  }
  const socket = getSettlementSocket()
  if (!(await socketReady(socket))) {
    ui.notify({ code: 'settlement-requeue', tone: 'error', message: '实时连接还没就绪，请稍后再试' })
    return
  }
  const live = socket as NonNullable<typeof socket>
  const playerName = game.state.player_name || '玩家'
  busy.value = true
  try {
    if (key === 'ai') {
      const created = await createAiRoom(live, playerName, aiDifficulty())
      if (!created.ok) {
        ui.notify({
          code: 'settlement-requeue',
          tone: 'error',
          message: created.message || '人机对战暂时不可用',
        })
        return
      }
      // 新房间已在入座回执前同步，只清理旧局展示，保留新的房间状态。
      result.reset()
      placement.reset()
      home.placementHandled()
      home.clearMatchFound()
      void router.push({ name: 'placement' })
      return
    }
    const mode: 'casual' | 'ranked' = key === 'ranked' ? 'ranked' : 'casual'
    home.expectPlacement()
    resetSettlement()
    await router.push({ name: 'start', query: { requeued: mode } })
    const ack = await emitFindMatch(live, playerName, mode)
    if (ack.status === 'error') {
      ui.notify({
        code: 'settlement-requeue',
        tone: 'error',
        message: ack.message || '重新排队失败，请回首页再试',
      })
    }
  } catch {
    ui.notify({ code: 'settlement-requeue', tone: 'error', message: '网络不稳定，请再试一次' })
  } finally {
    busy.value = false
  }
}

function openReplay(): void {
  const id = matchId.value
  if (!id) return
  void router.push({ name: 'replay', query: { match_id: id, from: 'game-over' } })
}
</script>

<template>
  <section
    class="screen game-over"
    data-screen="game-over"
    data-testid="screen-game-over"
    :data-outcome="outcome"
    aria-labelledby="screen-game-over-title"
  >
    <header class="game-over__head">
      <p class="game-over__eyebrow">{{ hasResult ? modeLabel + ' · 结算' : '竞技场 · 结算' }}</p>
      <h1 id="screen-game-over-title" class="game-over__title" data-testid="game-over-heading">结算</h1>
      <p v-if="hasResult" class="game-over__verdict" data-testid="game-over-verdict">{{ verdict }}</p>
      <p v-if="hasResult" class="game-over__summary" data-testid="game-over-reason">{{ summary }}</p>
      <section class="game-over__players" data-testid="game-over-players" aria-label="双方信息">
        <div class="game-over__player">
          <span class="game-over__player-role">你</span>
          <b class="game-over__player-name" data-testid="game-over-self">{{ selfName }}</b>
          <span v-if="seatLabel" class="game-over__player-seat">{{ seatLabel }}</span>
        </div>
        <div class="game-over__vs" aria-hidden="true">VS</div>
        <div class="game-over__player game-over__player--opponent">
          <span class="game-over__player-role">对手</span>
          <b class="game-over__player-name" data-testid="game-over-opponent">{{ opponentName }}</b>
        </div>
        <span class="game-over__mode" data-testid="game-over-mode">{{ modeLabel }}</span>
      </section>
    </header>

    <section v-if="!hasResult" class="game-over__empty" data-testid="game-over-empty">
      <p class="game-over__empty-title">还没有收到本局结算数据</p>
      <p class="game-over__empty-hint">
        从对局结束进入时，这里会显示胜负、双方信息与本局数据；刷新后请返回首页重新进入。
      </p>
    </section>

    <template v-else>
      <section v-if="hasStats" class="game-over__stats" data-testid="game-over-stats" aria-label="本局数据">
        <h2 class="game-over__section-title">本 局 数 据</h2>
        <dl class="game-over__stat-grid">
          <div v-if="roundText" class="game-over__stat">
            <dt>回合</dt>
            <dd data-testid="game-over-stat-round">{{ roundText }}</dd>
          </div>
          <div v-if="fireText" class="game-over__stat">
            <dt>命中 / 开火</dt>
            <dd data-testid="game-over-stat-fire">{{ fireText }}</dd>
          </div>
          <div v-if="shipsText" class="game-over__stat">
            <dt>剩余战舰</dt>
            <dd data-testid="game-over-stat-ships">{{ shipsText }}</dd>
          </div>
        </dl>
      </section>

      <section v-if="hasResult && opponentUsername" class="game-over__opponent" data-testid="game-over-opponent-card">
        <p class="game-over__opponent-name">
          对手 <b data-testid="game-over-opponent-name">{{ opponentNameText }}</b>
        </p>
        <div class="game-over__opponent-actions">
          <button type="button" class="button button--ghost" data-testid="game-over-opponent-profile" @click="openOpponentProfile">
            查看对手档案
          </button>
          <button
            v-if="showAddFriend"
            type="button"
            class="button"
            data-testid="game-over-add-friend"
            :disabled="friendState === 'sending' || friendState === 'sent'"
            @click="addFriend"
          >
            {{ friendButtonText }}
          </button>
          <p
            v-if="friendMessage"
            class="game-over__friend-note"
            :class="{ 'is-error': friendState === 'error' }"
            data-testid="game-over-friend-status"
            role="status"
          >
            {{ friendMessage }}
          </p>
        </div>
      </section>

      <p v-if="barsAnimating" class="game-over__skip">
        <button type="button" class="button button--ghost" data-testid="game-over-skip-animation" @click="skipBars">
          跳过动画
        </button>
      </p>

      <div class="game-over__cards">
        <section v-if="rank" class="game-over__rank" data-testid="game-over-rank" aria-label="段位变化">
          <h2 class="game-over__section-title">段 位</h2>
          <p class="game-over__rank-head">
            <b class="game-over__rank-delta" data-testid="game-over-rank-delta">{{ rankDeltaText }}</b>
            <span class="game-over__rank-role" data-testid="game-over-rank-role">{{ rankRole }}</span>
          </p>
          <div v-if="showRankTiers" class="game-over__rank-tiers">
            <span class="game-over__rank-label" data-testid="game-over-rank-before">{{ rankBeforeLabel }}</span>
            <span class="game-over__rank-arrow" aria-hidden="true">→</span>
            <span class="game-over__rank-label game-over__rank-label--after" data-testid="game-over-rank-after">
              {{ rankAfterLabel }}
            </span>
          </div>
          <div class="game-over__bar" role="img" :aria-label="'段位进度 ' + rankFill + '%'">
            <div
              class="game-over__bar-fill"
              :class="{ 'is-instant': barsInstant }"
              data-testid="game-over-rank-fill"
              :style="{ width: rankBarWidth + '%' }"
            ></div>
          </div>
          <p v-if="rankNote" class="game-over__rank-note" data-testid="game-over-rank-note">{{ rankNote }}</p>
        </section>

        <section v-if="xp" class="game-over__xp" data-testid="game-over-xp" aria-label="本局经验">
          <h2 class="game-over__section-title">经 验</h2>
          <p class="game-over__xp-head">
            <b class="game-over__xp-delta" data-testid="game-over-xp-delta">{{ xpDeltaText }}</b>
            <span class="game-over__xp-level" data-testid="game-over-xp-level">{{ xpLevelText }}</span>
          </p>
          <div class="game-over__bar" role="img" :aria-label="'经验进度 ' + xpFill + '%'">
            <div
              class="game-over__bar-fill game-over__bar-fill--xp"
              :class="{ 'is-instant': barsInstant }"
              data-testid="game-over-xp-fill"
              :style="{ width: xpBarWidth + '%' }"
            ></div>
          </div>
          <p class="game-over__xp-progress" data-testid="game-over-xp-progress">{{ xpProgressText }}</p>
          <p v-if="xpLevelUpText" class="game-over__xp-levelup" data-testid="game-over-xp-levelup">{{ xpLevelUpText }}</p>
          <ul v-if="xpBreakdown.length" class="game-over__breakdown">
            <li v-for="row in xpBreakdown" :key="row.label">
              <span>{{ row.label }}</span>
              <b>+{{ row.xp }}</b>
            </li>
          </ul>
        </section>

        <section v-if="achievementItems.length" class="game-over__badges" data-testid="game-over-achievements" aria-label="本局解锁徽章">
          <h2 class="game-over__section-title">本 局 徽 章</h2>
          <ul class="game-over__badge-list">
            <li
              v-for="item in achievementItems"
              :key="readString(item, 'id')"
              class="game-over__badge"
              :data-testid="'game-over-achievement-' + readString(item, 'id')"
            >
              <b>{{ readString(item, 'name') }}</b>
              <span>{{ readString(item, 'desc') }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>

    <footer class="game-over__actions">
      <div v-if="modeKey !== 'custom'" class="game-over__action-block">
        <button
          type="button"
          class="button"
          data-testid="game-over-play-again"
          :disabled="busy"
          @click="playAgain"
        >
          {{ busy ? '正在排队…' : '再来一局' }}
        </button>
        <small class="game-over__action-hint" data-testid="game-over-play-again-hint">
          {{ modeKey === 'ai' ? '按同样难度再开一局' : modeKey === 'ranked' ? '会重新排队并计分' : '重新排队' }}
        </small>
      </div>
      <button v-if="matchId" type="button" class="button button--ghost" data-testid="game-over-replay" @click="openReplay">
        本局回放
      </button>
      <button type="button" class="button button--ghost" data-testid="game-over-return-lobby" @click="returnLobby">
        返回大厅
      </button>
      <button type="button" class="button button--ghost" data-testid="game-over-return-home" @click="returnHome">
        返回首页
      </button>
      <p v-if="hasResult && !matchId" class="game-over__replay-note" data-testid="game-over-replay-note">
        本局没有可回放的权威记录。
      </p>
    </footer>
  </section>
</template>

<style scoped>
.game-over {
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding-top: 8px;
}

/* The hero panel: C+ draws one wide, gold-edged banner with the verdict
   centred under an anchor sigil, then a single "本局数据" panel below it. */
.game-over__head {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  width: 100%;
  max-width: 1120px;
  padding: 20px 30px 22px;
  border: 1px solid color-mix(in srgb, var(--gold) 55%, transparent);
  border-radius: var(--radius);
  background:
    radial-gradient(420px 140px at 50% 0%, rgba(201, 162, 76, 0.12), transparent 72%),
    linear-gradient(160deg, rgba(32, 29, 40, 0.88), rgba(18, 20, 36, 0.92));
  box-shadow: 0 0 34px rgba(201, 162, 76, 0.1), var(--shadow-panel);
  text-align: center;
}

.game-over__head::before {
  content: '⚓';
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  margin: 0 auto 6px;
  border: 1px solid rgba(201, 162, 76, 0.6);
  border-radius: 11px;
  background: rgba(11, 13, 24, 0.6);
  color: var(--accent-cyan);
  font-size: 22px;
}

.game-over__eyebrow {
  margin: 0;
  color: var(--text-secondary);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.game-over__title {
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.26em;
}

.game-over__verdict {
  margin: 2px 0 0;
  font-size: 42px;
  font-weight: 800;
  letter-spacing: 0.14em;
  line-height: 1.1;
}

.game-over[data-outcome='win'] .game-over__verdict {
  color: var(--gold-strong);
  text-shadow: 0 0 26px color-mix(in srgb, var(--gold) 35%, transparent);
}

.game-over[data-outcome='lose'] .game-over__verdict {
  color: var(--role-enemy);
}

.game-over__summary {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__empty {
  display: grid;
  gap: 8px;
  width: 100%;
  max-width: 1120px;
  padding: 20px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--panel);
}

.game-over__empty-title {
  margin: 0;
  font-size: 18px;
}

.game-over__empty-hint {
  margin: 0;
  max-width: 52ch;
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__players {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px 16px;
  margin-top: 10px;
  padding: 0;
  border: 0;
  background: transparent;
}

.game-over__player {
  display: grid;
  gap: 1px;
}

.game-over__player--opponent {
  text-align: right;
}

.game-over__player-role {
  color: var(--text-dim);
  font-size: 10px;
  letter-spacing: 0.16em;
}

.game-over__player-name {
  font-size: 14px;
}

.game-over__player-seat {
  color: var(--text-muted);
  font-size: 11px;
}

.game-over__vs {
  color: var(--text-dim);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.game-over__mode {
  margin-left: 6px;
  padding: 3px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 11px;
}

.game-over__stats {
  width: 100%;
  max-width: 1120px;
  padding: 14px 24px 8px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.game-over__section-title {
  margin: 0 0 2px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.26em;
}

.game-over__stat-grid {
  display: block;
  margin: 0;
}

.game-over__stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 11px 2px;
  border-bottom: 1px dashed var(--surface-elevated);
  background: none;
}

.game-over__stat:last-child {
  border-bottom: 0;
}

.game-over__stat dt {
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__stat dd {
  margin: 0;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.game-over__cards {
  display: grid;
  gap: 14px;
  width: 100%;
  max-width: 1120px;
}

@media (min-width: 900px) {
  .game-over__cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .game-over__badges {
    grid-column: 1 / -1;
  }
}

.game-over__rank {
  padding: 16px 20px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.game-over__rank-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0 0 10px;
}

.game-over__rank-delta {
  color: var(--gold-strong);
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.game-over__rank-role,
.game-over__rank-arrow {
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__rank-tiers {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  margin-bottom: 8px;
}

.game-over__rank-label {
  font-size: 14px;
}

.game-over__rank-label--after {
  color: var(--gold-strong);
}

.game-over__bar {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--bg-sunken);
}

.game-over__bar-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--gold), var(--gold-strong));
  /* Ticket #48: 600ms reveal, inside the 2s budget, and skippable. */
  transition: width 600ms ease-out;
}

.game-over__bar-fill.is-instant {
  transition: none;
}

.game-over__rank-note {
  margin: 8px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__xp,
.game-over__badges {
  padding: 16px 20px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.game-over__xp-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0 0 10px;
}

.game-over__xp-delta {
  color: var(--success);
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.game-over__xp-level {
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__bar-fill--xp {
  background: linear-gradient(90deg, var(--role-success), var(--success));
}

.game-over__xp-progress,
.game-over__xp-levelup {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__xp-levelup {
  color: var(--success);
}

.game-over__breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
  color: var(--text-muted);
  font-size: 12px;
}

.game-over__breakdown b {
  color: var(--success);
}

.game-over__badges {
  width: 100%;
}

.game-over__badge-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.game-over__badge {
  display: grid;
  gap: 2px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--accent-soft);
}

.game-over__badge b {
  font-size: 12px;
}

.game-over__badge span {
  color: var(--text-muted);
  font-size: 11px;
}

.game-over__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  align-items: flex-start;
  gap: 10px;
  padding-top: 4px;
}

.game-over__action-block {
  display: grid;
  gap: 3px;
  justify-items: start;
}

.game-over__action-hint {
  color: var(--text-muted);
  font-size: 11px;
}

.game-over__skip {
  display: flex;
  justify-content: center;
  width: 100%;
  margin: 0;
}

.game-over__opponent {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 14px;
  width: 100%;
  max-width: 1120px;
  padding: 12px 18px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
}

.game-over__opponent-name {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.game-over__opponent-name b {
  color: var(--text);
}

.game-over__opponent-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.game-over__friend-note {
  margin: 0;
  color: var(--success);
  font-size: 12px;
}

.game-over__friend-note.is-error {
  color: var(--danger);
}

.game-over__actions .button {
  min-height: 40px;
  padding: 8px 22px;
}

.game-over__actions [data-testid='game-over-play-again'] {
  border-color: var(--accent-strong);
  background: var(--hero-grad);
  box-shadow: var(--shadow-accent);
  color: #fff;
  font-weight: 600;
}

.button--ghost {
  border-color: var(--border-strong);
  background: var(--surface-deck);
  color: var(--text-muted);
}

.game-over__replay-note {
  flex-basis: 100%;
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
  text-align: center;
}

@media (max-width: 899px) {
  .game-over {
    justify-content: flex-start;
  }
}

@media (max-width: 760px) {
  .game-over {
    gap: 10px;
  }

  .game-over__head {
    padding: 16px 16px 18px;
  }

  .game-over__verdict {
    font-size: 32px;
  }

  .game-over__stats {
    padding: 12px 14px 6px;
  }

  .game-over__players {
    gap: 6px 10px;
  }
}
</style>
