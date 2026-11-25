const { parseInvite } = require('./invite.cjs')

const PHASE_ACTION = {
  preparation: 'enter_battle_phase',
  battle: 'enter_end_phase',
  end: 'end_turn',
}

// 首版接入无需选目标、由服务端直接结算的魔法。
const SIMPLE_CARD_NAMES = new Set(['火力全开', '八方来财', '五险一金', '失灵！'])

function supportsCard(card) {
  return SIMPLE_CARD_NAMES.has(card?.name)
}

function success(ack) {
  if (ack?.status !== 'success') throw new Error(ack?.message || '服务端没有完成操作')
  return ack
}

function createGameSession({ socket, storage, playerName, onChange = () => {} }) {
  let seat = storage.get()
  let recoverySnapshot = false
  let openRoom = false
  const state = {
    roomId: seat?.roomId || '',
    playerId: seat?.playerId || '',
    inviteToken: seat?.inviteToken || '',
    game: null,
    online: false,
    busy: false,
    restoring: false,
    notice: '',
    priority: null,
    chain: null,
    result: null,
  }

  const snapshot = () => ({ ...state })
  const publish = () => onChange(snapshot())
  function resetRoom() {
    seat = null
    storage.clear()
    Object.assign(state, {
      roomId: '', playerId: '', inviteToken: '', game: null,
      priority: null, chain: null, result: null,
    })
  }

  function identity() {
    if (!state.roomId || !state.playerId) throw new Error('还没有进入房间')
    return { room_id: state.roomId, player_id: state.playerId }
  }

  async function request(event, payload) {
    if (!socket.connected) throw new Error('连接还未恢复')
    try {
      return await socket.timeout(8000).emitWithAck(event, payload)
    } catch {
      throw new Error('连接暂时中断，请等房间同步后再试')
    }
  }

  async function act(fn) {
    if (state.busy || state.restoring) throw new Error('正在同步，请稍候')
    state.busy = true
    state.notice = ''
    publish()
    try {
      return await fn()
    } catch (error) {
      state.notice = error.message
      throw error
    } finally {
      state.busy = false
      publish()
    }
  }

  async function rememberSeat() {
    const { roomId, playerId, inviteToken } = state
    const sid = socket.id
    const ack = success(await request('get_reconnect_token', identity()))
    if (state.roomId !== roomId || state.playerId !== playerId || socket.id !== sid || state.result) return
    if (typeof ack.token !== 'string' || !ack.token) throw new Error('未取得续座凭据')
    seat = { roomId, playerId, inviteToken, token: ack.token }
    storage.set(seat)
  }

  async function onConnect() {
    state.online = true
    state.restoring = Boolean(seat)
    state.notice = ''
    publish()
    if (!seat) {
      if (state.roomId && !state.result) {
        resetRoom()
        state.notice = '连接已重建，未保存续座凭据，已返回大厅'
        publish()
      }
      return
    }
    const current = seat
    const sid = socket.id
    recoverySnapshot = false
    try {
      const ack = await request('rejoin_room', {
        room_id: current.roomId, player_id: current.playerId, token: current.token,
      })
      if (socket.id !== sid) return
      if (ack?.status !== 'success' || !recoverySnapshot) {
        const reason = ack?.message || state.notice || '原对局已结束'
        resetRoom()
        state.notice = reason
      } else {
        await rememberSeat()
      }
    } catch (error) {
      if (socket.id === sid) state.notice = error.message
    } finally {
      if (socket.id === sid) {
        state.restoring = false
        publish()
      }
    }
  }

  function onState(data, full) {
    if (!data || (!state.roomId && !openRoom)) return
    if (data.room_id && state.roomId && data.room_id !== state.roomId) return
    if (data.player_id && state.playerId && data.player_id !== state.playerId) return
    state.roomId = data.room_id || state.roomId
    state.playerId = data.player_id || state.playerId
    if (!state.roomId) return
    const old = state.game
    const clearedRps = data.state === 'rock_paper_scissors' && old?.round !== data.round
    const reset = clearedRps ? { rps_choices: {} } : {}
    if (data.state === 'rock_paper_scissors') {
      const choices = data.rps_choices
      if (choices && typeof choices === 'object') {
        const submitted = {}
        for (const pid of Object.keys(choices)) submitted[pid] = pid === state.playerId ? choices[pid] : 'submitted'
        data = { ...data, rps_choices: submitted }
      }
    }
    state.game = { ...(full ? {} : old), ...reset, ...data }
    if (old?.state === 'rock_paper_scissors' && data.state === 'attacking' && state.notice === '猜拳平局，请重新出拳') {
      state.notice = ''
    }
    if (full) {
      recoverySnapshot = true
      state.priority = data.priority_waiting || null
      if (!data.chain_waiting || data.chain_window !== state.playerId) {
        state.chain = null
      } else if (!state.chain) {
        const cardsInChain = Array.isArray(data.chain)
          ? data.chain
          : Array.isArray(data.chain?.chain)
            ? data.chain.chain
            : []
        const topRaw = cardsInChain[cardsInChain.length - 1]?.card
        const topCard = typeof topRaw === 'string' ? { name: topRaw } : topRaw || null
        state.chain = {
          responder: state.playerId,
          card: topCard,
          speed3_cards: data.magic_blocked
            ? []
            : (Array.isArray(data.hand) ? data.hand : []).filter(card => Number(card.speed) === 3),
        }
      }
    }
    if (state.game.state === 'game_over' && !state.result) {
      finish({ winner: state.game.winner, reason: state.game.game_over_reason })
      return
    }
    publish()
  }

  function finish(result) {
    if (!state.roomId) return
    state.result = result
    state.priority = null
    state.chain = null
    seat = null
    storage.clear()
    publish()
  }

  socket.on('connect', onConnect)
  socket.on('disconnect', () => {
    state.online = false
    state.restoring = false
    state.notice = '正在重新连接海战服务器'
    publish()
  })
  socket.on('connect_error', () => {
    state.notice = '暂时连不上服务器，正在重试'
    publish()
  })
  socket.on('room_sync', data => onState(data, true))
  socket.on('game_state', data => onState(data, false))
  socket.on('game_over', finish)
  socket.on('game_canceled', data => {
    if (!state.roomId) return
    resetRoom()
    state.notice = data?.message || '房间已取消'
    publish()
  })
  for (const event of ['error', 'reconnect_warning']) {
    socket.on(event, data => {
      state.notice = data?.message || '房间出现异常'
      publish()
    })
  }
  socket.on('priority_request', data => {
    state.priority = { ...data, role: 'responder' }
    publish()
  })
  socket.on('priority_waiting', data => {
    state.priority = { ...data, role: data.role || 'actor' }
    publish()
  })
  socket.on('priority_waiting_end', data => {
    if (data?.token && state.priority?.token !== data.token) return
    state.priority = null
    publish()
  })
  socket.on('rps_result', data => {
    if (data?.status === 'tie') {
      state.notice = '猜拳平局，请重新出拳'
      publish()
    }
  })
  socket.on('chain_request', data => {
    if (data?.responder && data.responder !== state.playerId) return
    state.chain = data
    publish()
  })
  socket.on('chain_resolving', () => {
    if (!state.chain) return
    state.chain = null
    publish()
  })
  socket.on('chain_resolved', () => {
    state.chain = null
    publish()
  })
  socket.on('opponent_disconnected', () => {
    if (state.game) state.game = { ...state.game, opponent_online: false }
    if (!state.result) state.notice = '对手已掉线，等待重连（30秒）'
    publish()
  })
  socket.on('opponent_reconnected', () => {
    if (state.game) state.game = { ...state.game, opponent_online: true }
    if (state.notice.includes('对手已掉线')) state.notice = ''
    publish()
  })
  socket.on('hand_updated', data => {
    if (state.game && Array.isArray(data?.hand)) {
      state.game = { ...state.game, hand: data.hand }
      publish()
    }
  })

  function enterRoom(event, payload) {
    return act(async () => {
      if (state.roomId) throw new Error('请先结束当前房间')
      openRoom = true
      const sid = socket.id
      try {
        const ack = success(await request(event, { ...payload, player_name: playerName }))
        state.roomId = ack.room_id || state.roomId || payload.room_id
        state.playerId = ack.player_id || state.playerId || sid
        state.inviteToken = event === 'create_room' ? ack.invite_token || '' : ''
        try {
          await rememberSeat()
        } catch {
          state.notice = '房间已进入，暂未保存续座凭据'
        }
        return ack
      } finally {
        openRoom = false
      }
    })
  }

  const send = (event, value = {}) => act(async () => success(await request(event, { ...identity(), ...value })))
  function cardPayload(card) {
    if (!supportsCard(card)) throw new Error('试玩版尚未支持这张魔法卡')
    return { card, targets: {} }
  }

  return {
    snapshot,
    connect: () => socket.connect(),
    createRoom: () => enterRoom('create_room', { public: false, name: '战舰棋好友对战' }),
    joinRoom: input => {
      const invite = parseInvite(input)
      if (!invite) return Promise.reject(new Error('邀请码格式不正确'))
      return enterRoom('join_room', {
        room_id: invite.roomId, ...(invite.inviteToken ? { invite_token: invite.inviteToken } : {}),
      })
    },
    leaveWaitingRoom: () => act(async () => {
      const ack = success(await request('close_room', identity()))
      resetRoom()
      return ack
    }),
    returnToLobby: () => {
      if (!state.result) return
      resetRoom()
      state.notice = ''
      publish()
    },
    place: cells => send('place_ships', { ships: cells.map(cell => ({ positions: [cell] })) }),
    choose: choice => send('rps_choice', { choice }),
    attack: (x, y) => send('attack', { x, y }),
    advance: () => {
      const event = PHASE_ACTION[state.game?.current_phase]
      return event ? send(event) : Promise.reject(new Error('当前没有可切换的阶段'))
    },
    surrender: () => send('surrender'),
    playCard: card => send('use_magic_card', cardPayload(card)),
    replyPriority: card => {
      const current = state.priority
      if (!current?.token || current.role !== 'responder') return Promise.reject(new Error('没有可响应的阶段'))
      return send('priority_response', { token: current.token, respond: Boolean(card), ...(card ? cardPayload(card) : {}) })
    },
    replyChain: card => send('chain_response', { chain: Boolean(card), ...(card ? cardPayload(card) : {}) }),
  }
}

module.exports = { createGameSession, supportsCard }
