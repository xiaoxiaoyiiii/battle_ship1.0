import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { useCommandersStore, type CommanderSkillCastEvent } from '../../stores/commanders'
import { useGameStore } from '../../stores/game'

type Side = 'self' | 'opponent'
type BoardCue = { side: Side; key: string; kind: 'sonar' | 'sacrifice' | 'shield'; cells?: string[] }

export function useCommanderBattleCues() {
  const commanders = useCommandersStore()
  const game = useGameStore()
  const active = shallowRef<CommanderSkillCastEvent | null>(null)
  const board = shallowRef<BoardCue | null>(null)
  let activeTimer: ReturnType<typeof setTimeout> | undefined
  let boardTimer: ReturnType<typeof setTimeout> | undefined

  function sideFor(playerId?: string | null): Side | null {
    if (!playerId) return null
    if (playerId === game.state.player_id) return 'self'
    const opponent = game.state.commander_state?.opponent as { player_id?: string } | null | undefined
    return opponent?.player_id === playerId ? 'opponent' : null
  }

  function setBoard(cue: BoardCue) {
    board.value = cue
    clearTimeout(boardTimer)
    boardTimer = setTimeout(() => { board.value = null }, 920)
  }

  watch(() => commanders.lastSkillEvent, (event) => {
    if (!event || !sideFor(event.player_id)) return
    active.value = event
    clearTimeout(activeTimer)
    activeTimer = setTimeout(() => { active.value = null }, 880)
    if (event.negated || event.success === false) return
    const cells = event.cells?.flatMap(({ x, y }) =>
      Number.isInteger(x) && Number.isInteger(y) && x >= 0 && y >= 0 && x <= 5 && y <= 5 ? [`${x}-${y}`] : [],
    )
    if (event.skill_id === 'delayed_lock' && event.stage === 'reveal' && cells?.length) {
      const side = sideFor(event.target_player_id)
      if (side) setBoard({ side, key: event.id, kind: 'sonar', cells })
    } else if (event.skill_id === 'sacrifice_gambit' && event.stage === 'chain_enter' && cells?.length) {
      const side = sideFor(event.player_id)
      if (side) setBoard({ side, key: event.id, kind: 'sacrifice', cells })
    } else if (event.skill_id === 'dauntless_fleet' && event.stage === 'resolve') {
      const side = sideFor(event.player_id)
      if (side) setBoard({ side, key: event.id, kind: 'shield' })
    }
  }, { flush: 'sync' })

  watch(() => game.state.room_id, () => {
    clearTimeout(activeTimer)
    clearTimeout(boardTimer)
    active.value = null
    board.value = null
  })
  onScopeDispose(() => {
    clearTimeout(activeTimer)
    clearTimeout(boardTimer)
  })

  function skillMatches(skillId?: string, caster?: string) {
    const event = active.value
    if (!skillId || event?.skill_id !== skillId || !caster) return false
    if (caster === event.player_id) return true
    const ownSeat = game.state.player_seat
    if (ownSeat !== 'p1' && ownSeat !== 'p2') return false
    const side = sideFor(event.player_id)
    return side === 'self' ? caster === ownSeat : side === 'opponent' && caster === (ownSeat === 'p1' ? 'p2' : 'p1')
  }

  const resolved = computed(() => active.value?.stage === 'resolve' && active.value.success !== false &&
    !active.value.negated ? active.value : null)
  const attackBuff = computed(() => resolved.value?.skill_id === 'firepower_control' ? resolved.value.id : '')
  const extraDraw = computed(() => resolved.value?.skill_id === 'sacrifice_gambit' && resolved.value.draw_count &&
    sideFor(resolved.value.player_id) === 'self'
    ? { id: resolved.value.id, count: resolved.value.draw_count }
    : null)
  return { active, board, skillMatches, attackBuff, extraDraw }
}
