import type { Pinia } from 'pinia'
import { defineComponent, h, watch, type Component } from 'vue'
import { useRoute, type Router } from 'vue-router'
import { io, type Socket } from 'socket.io-client'
import { routeLoading } from './router'
import { fetchRemoteContractHash, type TypedSocket } from './socket/client'
import { CONTRACT_SCHEMA_HASH, ROOM_SYNC_FIELDS } from './socket/events.gen'
import { useGameStore } from './stores/game'
import { useLeaderboardStore } from './stores/leaderboard'
import { useProfileStore } from './stores/profile'
import { useReplayStore } from './stores/replay'
import { useResultStore } from './stores/result'
import { useSettingsStore } from './stores/settings'
import { useAudioStore } from './stores/audio'
import { CARD_ART_COUNT, missingCardArt } from './cards/cardArt'
import { useLobbyStore } from './stores/lobby'
import { useSpectateStore } from './stores/spectate'
import { GAME_STATE_SCHEMA, defaultGameState } from './stores/gameStateSchema'
import {
  SPECTATE_EVENTS,
  applySpectateEvent,
  getSpectateSocket,
  joinSpectate,
  leaveSpectate,
  resetSpectateChannelForTest,
  sendSpectateChat,
  spectateSocketConnected,
  type SpectateEventName,
} from './realtime/spectate'
import {
  applySettlementEvent,
  getSettlementSocket,
  settlementSocketConnected,
  type SettlementEventName,
} from './realtime/settlement'
import {
  BATTLE_EVENTS,
  applyBattleEvent,
  battleSocketConnected,
  getBattleSocket,
  type BattleEventName,
} from './realtime/battle'
import {
  applyMatchEvent,
  MATCH_EVENTS,
  setMatchAckInterceptor,
  type MatchEventName,
} from './realtime/match'
import {
  applyLobbyEvent,
  getLobbySocket,
  lobbySocketConnected,
  type LobbyEventName,
} from './realtime/lobby'
import { useMatchStore } from './stores/match'
import { usePlacementStore } from './stores/placement'
import { useRpsStore } from './stores/rps'
import { CrashProbe } from './test-crash/CrashProbe'
import { crashTarget, requestCrash } from './test-crash/state'

/**
 * Test-build-only introspection for the external browser gate
 * (D:/develop/battleship-verify/cases/22-sample/browser_check.mjs).
 *
 * Production entry points never import this module: main.ts decides between
 * the plain App and createTestRoot on the compile-time __BS_TEST_HOOKS__.
 */

interface RouteLoadingEntry {
  path: string
  loading: boolean
}

export interface SettlementTestApi {
  socket: () => TypedSocket | null
  connected: () => boolean
  state: () => {
    gameOver: unknown
    xp: unknown
    rank: unknown
    achievements: unknown[]
    recentOpponent: unknown
  }
  /** Feed the exact production handler with a frozen payload (test build only). */
  feed: (event: string, payload: Record<string, unknown>) => void
  /** A second real Socket.IO client, used to seat the opponent. */
  createSocket: () => Socket
}

export interface ReplayTestApi {
  state: () => {
    status: string
    error: string
    matchId: string
    youAre: string | null
    k: number
    playing: boolean
    speed: number
    stepCount: number
    truncated: string
  }
  payload: () => unknown
  frame: () => unknown
  load: (matchId: string) => Promise<void>
}

export interface SpectateTestApi {
  state: () => Record<string, unknown>
  feed: (event: string, payload: Record<string, unknown>) => void
  socket: () => TypedSocket | null
  connected: () => boolean
  join: (roomId: string) => Promise<{ ok: boolean; message: string }>
  leave: () => Promise<void>
  chat: (message: string) => Promise<{ ok: boolean; message: string }>
  resetChannel: () => void
}

export interface BattleTestApi {
  socket: () => TypedSocket | null
  connected: () => boolean
  /** The live battle store snapshot (log, prompts, marks) plus the game state. */
  state: () => Record<string, unknown>
  /** Feed the exact production reducer with a frozen frame (test build only). */
  feed: (event: string, payload: Record<string, unknown>) => void
}

export interface ScreensTestApi {
  /** Read-only snapshots of the ticket #25 screen stores. */
  profile: () => unknown
  leaderboard: () => unknown
  settings: () => unknown
}

export interface MatchTestApi {
  /** Mirror of the placement / rps local state (draft board, wait, timeout). */
  state: () => { placement: Record<string, unknown>; rps: Record<string, unknown> }
  /** Feed the exact production handler with a frozen payload (test build only). */
  feed: (event: string, payload: Record<string, unknown>) => void
  /** Shrink the 6s ack waits so the timeout state is deterministic. */
  configureAckTiming: (options: { ackTimeoutMs?: number; tickMs?: number }) => void
  /** Drop the next match command frame, simulating a lost ack. */
  silenceNextAck: () => void
}

export interface LobbyTestApi {
  socket: () => TypedSocket | null
  connected: () => boolean
  state: () => {
    hello: unknown
    snapshot: unknown
    chat: unknown[]
    connected: boolean
    subscribed: boolean
    queueMode: string | null
    ownRoomId: string
    ownRoomName: string
    ownRoomPublic: boolean
    activeInvite: unknown
    friends: unknown[]
    friendsLoaded: boolean
    friendsGuest: boolean
    friendsError: string
    notice: string
    error: string
    startedRoomId: string
  }
  /** Feed the exact production handler with a frozen payload (test build only). */
  feed: (event: string, payload: Record<string, unknown>) => void
  /** Deterministic friends fixture for screenshots (no wire event exists). */
  setFriends: (payload: Record<string, unknown>) => void
  setNotice: (text: string) => void
  clearError: () => void
  clearChat: () => void
  clearOwnRoom: () => void
  reset: () => void
  /** A second real Socket.IO client, used to seat/invite the other player. */
  createSocket: () => Socket
}

export interface TestHooksApi {
  version: string
  router: Router
  currentRouteName: () => string | null
  routeLoadingHistory: () => RouteLoadingEntry[]
  clearRouteLoadingHistory: () => void
  contractHash: string
  fetchRemoteContractHash: typeof fetchRemoteContractHash
  roomSyncFields: string[]
  gameStateSchemaFields: string[]
  gameStateSchema: typeof GAME_STATE_SCHEMA
  defaultGameState: () => unknown
  gameState: () => unknown
  settlement: SettlementTestApi
  replay: ReplayTestApi
  spectate: SpectateTestApi
  battle: BattleTestApi
  screens: ScreensTestApi
  match: MatchTestApi
  lobby: LobbyTestApi
  cardArt: { count: number; missing: string[] }
  crashNext: (routeName: string) => void
}

declare global {
  interface Window {
    __BS_TEST__?: TestHooksApi
  }
}

/** Wrap the shell so the crash probe renders inside its ScreenBoundary slot. */
export function createTestRoot(Root: Component): Component {
  return defineComponent({
    name: 'TestRoot',
    setup() {
      const route = useRoute()
      return () =>
        h(Root, null, {
          'screen-extra': () => (crashTarget.value === route.name ? h(CrashProbe) : null),
        })
    },
  })
}

const LOBBY_EVENTS: readonly string[] = [
  'lobby_hello',
  'lobby_state',
  'lobby_chat_history',
  'lobby_chat',
  'match_queued',
  'match_canceled',
  'friend_invite',
  'game_state',
  'room_sync',
  'error',
]

const SETTLEMENT_EVENTS: readonly string[] = [
  'game_message',
  'game_over',
  'game_state',
  'room_sync',
  'xp_gained',
  'rank_changed',
  'achievements_unlocked',
  'ships_updated',
]

export function installTestHooks(router: Router, pinia: Pinia): void {
  const history: RouteLoadingEntry[] = []
  watch(routeLoading, (loading) => {
    history.push({ path: router.currentRoute.value.fullPath, loading })
  })

  const game = useGameStore(pinia)
  const result = useResultStore(pinia)
  const replay = useReplayStore(pinia)
  const spectate = useSpectateStore(pinia)
  const battleStore = useMatchStore(pinia)
  const profile = useProfileStore(pinia)
  const leaderboard = useLeaderboardStore(pinia)
  const settings = useSettingsStore(pinia)
  const audio = useAudioStore(pinia)

  const snapshot = (value: unknown): unknown => JSON.parse(JSON.stringify(value))

  const screens: ScreensTestApi = {
    profile: () =>
      snapshot({
        ownStatus: profile.ownStatus,
        viewerName: profile.viewerName,
        viewed: profile.viewed,
      }),
    leaderboard: () =>
      snapshot({
        activeTab: leaderboard.activeTab,
        record: leaderboard.record,
        ranked: leaderboard.ranked,
      }),
    settings: () =>
      snapshot({
        profileStatus: settings.profileStatus,
        privacy: settings.privacy,
        replay: settings.replay,
        spectate: settings.spectate,
        passwordMessage: settings.passwordMessage,
        wallpaper: settings.wallpaper,
        audio: {
          sfxMuted: audio.sfxMuted,
          sfxVolume: audio.sfxVolume,
          bgmMuted: audio.bgmMuted,
          bgmVolume: audio.bgmVolume,
          bgmPlaying: audio.bgmPlaying,
        },
      }),
  }

  const lobbyStore = useLobbyStore(pinia)

  const settlement: SettlementTestApi = {
    socket: () => getSettlementSocket(),
    connected: () => settlementSocketConnected(),
    state: () =>
      JSON.parse(JSON.stringify({
        gameOver: result.gameOver,
        xp: result.xp,
        rank: result.rank,
        achievements: result.achievements,
        recentOpponent: result.recentOpponent,
      })),
    feed: (event, payload) => {
      if (!SETTLEMENT_EVENTS.includes(event)) throw new Error('unknown settlement event: ' + event)
      applySettlementEvent(event as SettlementEventName, payload, pinia)
    },
    createSocket: () => {
      const socket = io({ autoConnect: false, withCredentials: true, transports: ['websocket', 'polling'] })
      socket.connect()
      return socket
    },
  }

  const placement = usePlacementStore(pinia)
  const rps = useRpsStore(pinia)
  let silencedAcks = 0
  setMatchAckInterceptor(() => {
    if (silencedAcks > 0) {
      silencedAcks -= 1
      return true
    }
    return false
  })

  const match: MatchTestApi = {
    state: () =>
      JSON.parse(JSON.stringify({
        placement: {
          maxShips: placement.maxShips,
          cells: placement.cells,
          placedCount: placement.placedCount,
          submitted: placement.submitted,
          pending: placement.pending,
          countdown: placement.countdown,
          error: placement.error,
          resetMessage: placement.resetMessage,
          resetPhase: placement.resetPhase,
          canSubmit: placement.canSubmit,
          hint: placement.hint,
        },
        rps: {
          result: rps.result,
          pendingChoice: rps.pendingChoice,
          waiting: rps.waiting,
          countdown: rps.countdown,
          error: rps.error,
        },
      })),
    feed: (event, payload) => {
      if (!MATCH_EVENTS.includes(event as MatchEventName)) throw new Error('unknown match event: ' + event)
      applyMatchEvent(event as MatchEventName, payload, pinia)
    },
    configureAckTiming: (options) => {
      placement.configureAckTiming(options)
      rps.configureAckTiming(options)
    },
    silenceNextAck: () => {
      silencedAcks += 1
    },
  }

  const lobby: LobbyTestApi = {
    socket: () => getLobbySocket(),
    connected: () => lobbySocketConnected(),
    state: () =>
      JSON.parse(JSON.stringify({
        hello: lobbyStore.hello,
        snapshot: lobbyStore.snapshot,
        chat: lobbyStore.chat,
        connected: lobbyStore.connected,
        subscribed: lobbyStore.subscribed,
        queueMode: lobbyStore.queueMode,
        ownRoomId: lobbyStore.ownRoomId,
        ownRoomName: lobbyStore.ownRoomName,
        ownRoomPublic: lobbyStore.ownRoomPublic,
        activeInvite: lobbyStore.activeInvite,
        friends: lobbyStore.friends,
        friendsLoaded: lobbyStore.friendsLoaded,
        friendsGuest: lobbyStore.friendsGuest,
        friendsError: lobbyStore.friendsError,
        notice: lobbyStore.notice,
        error: lobbyStore.error,
        startedRoomId: lobbyStore.startedRoomId,
      })),
    feed: (event, payload) => {
      if (!LOBBY_EVENTS.includes(event)) throw new Error('unknown lobby event: ' + event)
      applyLobbyEvent(event as LobbyEventName, payload, pinia)
    },
    setFriends: (payload) => lobbyStore.recordFriends(payload),
    setNotice: (text) => lobbyStore.setNotice(text),
    clearError: () => lobbyStore.clearError(),
    clearChat: () => lobbyStore.clearChat(),
    clearOwnRoom: () => lobbyStore.clearOwnRoom(),
    reset: () => lobbyStore.reset(),
    createSocket: () => {
      const socket = io({ autoConnect: false, withCredentials: true, transports: ['websocket', 'polling'] })
      socket.connect()
      return socket
    },
  }

  const replayApi: ReplayTestApi = {
    state: () =>
      JSON.parse(JSON.stringify({
        status: replay.status,
        error: replay.error,
        matchId: replay.matchId,
        youAre: replay.youAre,
        k: replay.k,
        playing: replay.playing,
        speed: replay.speed,
        stepCount: replay.stepCount,
        truncated: replay.payload?.truncated ?? '',
      })),
    payload: () => JSON.parse(JSON.stringify(replay.payload)),
    frame: () => JSON.parse(JSON.stringify(replay.frame)),
    load: (matchId: string) => replay.load(matchId),
  }

  const spectateApi: SpectateTestApi = {
    state: () =>
      JSON.parse(JSON.stringify({
        phase: spectate.phase,
        error: spectate.error,
        roomId: spectate.roomId,
        endedReason: spectate.endedReason,
        winnerLabel: spectate.winnerLabel,
        stateValue: spectate.stateValue,
        currentPhase: spectate.currentPhase,
        currentAttacker: spectate.currentAttacker,
        attacksRemaining: spectate.attacksRemaining,
        round: spectate.round,
        fieldMagic: spectate.fieldMagic,
        ranked: spectate.ranked,
        seatLabels: spectate.seatLabels,
        sides: spectate.sides,
        attacks: spectate.attacks,
        count: spectate.count,
        limit: spectate.limit,
        me: spectate.me,
        roster: spectate.roster,
        chat: spectate.chat,
        chain: spectate.chain,
        logs: spectate.logs,
      })),
    feed: (event: string, payload: Record<string, unknown>) => {
      if (!SPECTATE_EVENTS.includes(event as SpectateEventName)) {
        throw new Error('unknown spectate event: ' + event)
      }
      applySpectateEvent(event as SpectateEventName, payload, pinia)
    },
    socket: () => getSpectateSocket(),
    connected: () => spectateSocketConnected(),
    join: (roomId: string) => joinSpectate(roomId, pinia),
    leave: () => leaveSpectate(pinia),
    chat: (message: string) => sendSpectateChat(message, pinia),
    resetChannel: () => resetSpectateChannelForTest(),
  }

  const battle: BattleTestApi = {
    socket: () => getBattleSocket(),
    connected: () => battleSocketConnected(),
    state: () =>
      JSON.parse(
        JSON.stringify({
          ...battleStore.snapshot(),
          game: {
            hand: game.state.hand,
            chain: game.state.chain,
            attacks: game.state.attacks,
            opponent_attacks: game.state.opponent_attacks,
            effect_badges: game.state.effect_badges,
            state: game.state.state,
            current_phase: game.state.current_phase,
            attacks_remaining: game.state.attacks_remaining,
            remaining_ships: game.state.remaining_ships,
            opponent_remaining_ships: game.state.opponent_remaining_ships,
            frozen_area: game.state.frozen_area,
            shenwei_holes: game.state.shenwei_holes,
          },
        }),
      ),
    feed: (event, payload) => {
      if (!(BATTLE_EVENTS as readonly string[]).includes(event)) {
        throw new Error('unknown battle event: ' + event)
      }
      applyBattleEvent(event as BattleEventName, payload, pinia)
    },
  }

  window.__BS_TEST__ = {
    version: 'ticket-25+ticket-23+ticket-24+ticket-28+ticket-27',
    router,
    currentRouteName: () => (router.currentRoute.value.name as string | null) ?? null,
    routeLoadingHistory: () => history.slice(),
    clearRouteLoadingHistory: () => {
      history.length = 0
    },
    contractHash: CONTRACT_SCHEMA_HASH,
    fetchRemoteContractHash,
    roomSyncFields: [...ROOM_SYNC_FIELDS],
    gameStateSchemaFields: Object.keys(GAME_STATE_SCHEMA.fields),
    gameStateSchema: GAME_STATE_SCHEMA,
    defaultGameState: () => defaultGameState(),
    gameState: () => JSON.parse(JSON.stringify(game.state)),
    settlement,
    replay: replayApi,
    spectate: spectateApi,
    battle,
    screens,
    cardArt: { count: CARD_ART_COUNT, missing: missingCardArt() },
    match,
    lobby,
    crashNext: (routeName: string) => requestCrash(routeName),
  }
}
