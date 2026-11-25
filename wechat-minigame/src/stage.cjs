const { supportsCard } = require('./game-session.cjs')

const INK = '#e7f5ff'
const MUTED = '#91aec3'
const CYAN = '#60dccb'
const GOLD = '#ffc98a'
const PHASES = { preparation: '准备阶段', battle: '战斗阶段', end: '结束阶段' }
const PHASE_ACTIONS = { preparation: '进入战斗', battle: '进入结束阶段', end: '结束回合' }

function createStage(canvas, wx, actions) {
  const ctx = canvas.getContext('2d')
  let view
  let ui
  let width = 0
  let height = 0
  let top = 0
  let bottom = 0
  let inset = 18
  let contentWidth = 0
  let offset = 0
  let maxOffset = 0
  let touch
  let scene
  const targets = []

  function resize() {
    const display = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
    const ratio = Math.max(1, Math.min(3, display.pixelRatio || 1))
    const capsule = wx.getMenuButtonBoundingClientRect?.()
    width = display.windowWidth
    height = display.windowHeight
    top = Math.max(display.safeArea?.top || 0, capsule?.bottom || 0) + 8
    bottom = Math.max(0, height - Math.min(height, display.safeArea?.bottom ?? height))
    inset = Math.max(14, (width - 420) / 2)
    contentWidth = width - inset * 2
    canvas.width = Math.round(width * ratio)
    canvas.height = Math.round(height * ratio)
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    paint()
  }

  function box(x, y, w, h, fill, border, r = 12) {
    ctx.beginPath()
    ctx.moveTo(x + r, y)
    ctx.arcTo(x + w, y, x + w, y + h, r)
    ctx.arcTo(x + w, y + h, x, y + h, r)
    ctx.arcTo(x, y + h, x, y, r)
    ctx.arcTo(x, y, x + w, y, r)
    ctx.closePath()
    if (fill) {
      ctx.fillStyle = fill
      ctx.fill()
    }
    if (border) {
      ctx.lineWidth = 1
      ctx.strokeStyle = border
      ctx.stroke()
    }
  }

  function text(value, x, y, { size = 14, color = INK, weight = 400, align = 'left', max = contentWidth } = {}) {
    ctx.font = weight + ' ' + size + 'px sans-serif'
    ctx.textBaseline = 'middle'
    ctx.textAlign = align
    ctx.fillStyle = color
    const chars = Array.from(String(value ?? ''))
    let label = chars.join('')
    while (chars.length > 1 && ctx.measureText(label).width > max) {
      chars.pop()
      label = chars.join('') + '…'
    }
    ctx.fillText(label, x, y)
  }

  function button(label, x, y, w, callback, { primary = false, disabled = false, height: h = 44 } = {}) {
    box(x, y, w, h, primary && !disabled ? '#15635f' : '#142c40', primary && !disabled ? '#49bcb1' : '#34536b', 10)
    text(label, x + w / 2, y + h / 2, {
      size: 14, color: disabled ? '#8c9baa' : INK, align: 'center', weight: 650, max: w - 12,
    })
    if (!disabled) targets.push({ x, y, w, h, callback })
  }

  function wide(label, y, callback, options = {}) {
    button(label, inset, y, contentWidth, callback, options)
    return y + (options.height || 44) + 10
  }

  function split(left, right, y) {
    const w = (contentWidth - 10) / 2
    button(left[0], inset, y, w, left[1], left[2])
    button(right[0], inset + w + 10, y, w, right[1], right[2])
    return y + 54
  }

  function disc(x, y, radius, fill, outline = '') {
    ctx.beginPath()
    ctx.arc(x, y, radius, 0, Math.PI * 2)
    if (fill) {
      ctx.fillStyle = fill
      ctx.fill()
    }
    if (outline) {
      ctx.strokeStyle = outline
      ctx.lineWidth = 1.2
      ctx.stroke()
    }
  }

  function backdrop() {
    const sea = ctx.createLinearGradient(0, 0, width, height)
    sea.addColorStop(0, '#12364a')
    sea.addColorStop(0.52, '#0b2032')
    sea.addColorStop(1, '#071324')
    ctx.fillStyle = sea
    ctx.fillRect(0, 0, width, height)
    for (const radius of [92, 138, 184, 230]) {
      disc(width - inset - 55, top + 167, radius, '', 'rgba(68,159,168,0.13)')
    }
    for (let i = 0; i < 32; i++) {
      const x = (i * 149 + 5) % width
      const y = (i * 271 + 17) % height
      disc(x, y, i % 4 === 0 ? 1.35 : 0.7, 'rgba(170,225,234,0.22)')
    }
  }

  function shipMark(x, y, scale, fill) {
    ctx.beginPath()
    ctx.moveTo(x - 20 * scale, y + 1 * scale)
    ctx.lineTo(x + 20 * scale, y + 1 * scale)
    ctx.lineTo(x + 11 * scale, y + 10 * scale)
    ctx.lineTo(x - 13 * scale, y + 10 * scale)
    ctx.closePath()
    ctx.fillStyle = fill
    ctx.fill()
    ctx.fillRect(x - 9 * scale, y - 8 * scale, 18 * scale, 10 * scale)
    ctx.fillRect(x - 2 * scale, y - 16 * scale, 4 * scale, 9 * scale)
  }

  function board(y, cells, onCell, { skipAttacked = false } = {}) {
    const size = Math.floor(Math.min(contentWidth - 24, 338) / 6)
    const left = Math.floor((width - size * 6) / 2 + 6)
    const grid = y + 20
    box(left - 4, grid - 4, size * 6 + 8, size * 6 + 8, '#081828', '#355570', 9)
    for (let x = 0; x < 6; x++) {
      text('ABCDEF'[x], left + x * size + size / 2, y + 5, { size: 11, color: MUTED, align: 'center' })
    }
    for (let j = 0; j < 6; j++) {
      const cellY = grid + j * size
      text(j + 1, left - 12, cellY + size / 2, { size: 11, color: MUTED, align: 'center' })
      for (let i = 0; i < 6; i++) {
        const x = left + i * size
        const code = cells.get(i + ':' + j)
        const centerX = x + size / 2
        const centerY = cellY + size / 2
        const hit = code === 'hit'
        const marked = code === 'ship' || code === 'reveal'
        box(x + 1, cellY + 1, size - 2, size - 2,
          hit ? '#6b303e' : marked ? '#18676d' : (i + j) % 2 ? '#132f44' : '#173950',
          hit ? '#d27082' : marked ? '#5dbbaf' : '#295470', 5)
        if (marked) shipMark(centerX, centerY + 2, size / 70, code === 'reveal' ? GOLD : '#c1fff5')
        if (hit) text('×', centerX, centerY, { size: size * 0.67, color: '#ffe4e9', align: 'center', weight: 700 })
        if (code === 'miss') disc(centerX, centerY, size * 0.13, '', '#8fd9f3')
        const attacked = hit || code === 'miss'
        if (onCell && (!skipAttacked || !attacked)) {
          targets.push({ x, y: cellY, w: size, h: size, callback: () => onCell(i, j) })
        }
      }
    }
    return grid + size * 6 + 17
  }

  function marks(boardSide) {
    const cells = new Map()
    const game = view.game
    const self = boardSide === 'self'
    if (self) {
      for (const ship of game?.ships || []) {
        for (const pos of ship.positions || []) cells.set(pos.x + ':' + pos.y, ship.alive === false ? 'hit' : 'ship')
      }
    } else {
      for (const pos of game?.revealed_positions || []) cells.set(pos.x + ':' + pos.y, 'reveal')
    }
    for (const pos of (self ? game?.opponent_attacks : game?.attacks) || []) {
      const key = pos.x + ':' + pos.y
      if (pos.hit || !cells.has(key)) cells.set(key, pos.hit ? 'hit' : 'miss')
    }
    return cells
  }

  function drawLobby(y, disabled) {
    box(inset, y, contentWidth, 182, 'rgba(11,34,50,0.85)', '#396779', 18)
    disc(width / 2, y + 56, 31, '#183c51', '#459da4')
    shipMark(width / 2, y + 57, 0.95, CYAN)
    text('好友海战', width / 2, y + 111, { size: 32, weight: 750, align: 'center' })
    text('布舰、猜拳、开炮与施法', width / 2, y + 150, { color: MUTED, align: 'center' })
    y += 199
    y = wide('创建好友房', y, actions.create, { primary: true, disabled, height: 52 })
    y = wide('输入邀请码', y, actions.join, { disabled, height: 52 })
    text(ui.name, inset + 6, y + 16, { size: 13, color: MUTED })
    return y + 32
  }

  function drawWaiting(y, disabled) {
    box(inset, y, contentWidth, 116, '#102c42', '#3a697c')
    const center = width / 2
    text('等待好友加入', center, y + 31, { size: 23, weight: 700, align: 'center' })
    text('房间号  ' + view.roomId.toUpperCase(), center, y + 78, { size: 24, weight: 700, color: CYAN, align: 'center' })
    y += 132
    if (view.inviteToken) {
      y = wide('邀请微信好友', y, actions.share, { primary: true, disabled, height: 52 })
      y = wide('复制邀请码', y, actions.copy, { disabled })
    }
    return wide('关闭房间', y, actions.close, { disabled })
  }

  function drawPlacement(y, disabled) {
    const need = view.game?.max_ships || 6
    const placed = (view.game.ships || []).length >= need
    text('布置你的战舰', inset, y + 16, { size: 24, weight: 750 })
    const peerText = view.game.opponent_online === false ? '对手已掉线' : view.game.opponent_ready ? '好友已就绪' : ''
    if (peerText) {
      text(peerText, width - inset, y + 16, {
        size: 13, color: view.game.opponent_online === false ? GOLD : CYAN, align: 'right',
      })
    }
    const statusText = placed
      ? view.game.opponent_online === false ? '已提交 · 对手已掉线，等待重连' : '已提交 · 等待好友'
      : '已放置 ' + ui.cells.length + ' / ' + need
    text(statusText, inset, y + 47, { size: 13, color: CYAN })
    const cells = placed ? marks('self') : new Map(ui.cells.map(cell => [cell.x + ':' + cell.y, 'ship']))
    y = board(y + 65, cells, disabled || placed ? null : actions.toggleCell)
    if (placed) return y + 12
    y = split(['清空', actions.clear, { disabled }], ['随机布船', actions.random, { disabled }], y)
    return wide('确认布船', y, actions.place, { primary: true, disabled: disabled || ui.cells.length !== need })
  }

  function drawRps(y, disabled) {
    const choices = view.game.rps_choices || {}
    const submitted = Object.prototype.hasOwnProperty.call(choices, view.playerId)
    const other = Object.keys(choices).some(id => id !== view.playerId)
    text('猜拳决定先手', inset, y + 20, { size: 27, weight: 750 })
    text(submitted ? '你已提交，等待好友' : other ? '好友已提交，轮到你出拳' : '请选择一项', inset, y + 57, { color: MUTED })
    y += 78
    for (const [label, choice] of [['石头', 'rock'], ['剪刀', 'scissors'], ['布', 'paper']]) {
      y = wide(label, y, () => actions.choose(choice), { disabled: disabled || submitted, height: 51 })
    }
    return y
  }

  function drawDefense(y, disabled) {
    const chain = view.chain
    const priority = view.priority
    if (!chain && !priority) return y
    const responder = chain || priority.role === 'responder'
    const title = chain ? '连锁响应' : responder ? '阶段响应' : '等待对手响应'
    text(title, inset, y + 13, { color: GOLD, size: 16, weight: 700 })
    y += 29
    if (!responder) return y
    const responseCards = (chain?.speed3_cards || priority?.speed3_cards || []).filter(supportsCard)
    const respond = chain ? actions.replyChain : actions.replyPriority
    if (chain?.card?.name) {
      text(chain.card.name, inset + 1, y + 9, { color: MUTED, size: 13 })
      y += 26
    }
    y = wide('放弃响应', y, () => respond(), { disabled })
    for (const card of responseCards) y = wide('响应 · ' + card.name, y, () => actions.card(card, respond), { disabled })
    return y
  }

  function drawBattle(y, disabled) {
    const game = view.game
    const myTurn = view.playerId === game.current_attacker
    const blocked = Boolean(view.chain || view.priority || game.chain_waiting || game.interaction_waiting)
    text('第 ' + (game.round || 1) + ' 大回合', inset, y + 13, { weight: 750, size: 21 })
    text(myTurn ? '你的回合' : '对手回合', width - inset, y + 13, { weight: 700, color: myTurn ? CYAN : GOLD, align: 'right' })
    text((PHASES[game.current_phase] || '等待同步') + ' · 剩余炮击 ' + (game.attacks_remaining ?? 0),
      inset, y + 40, { size: 13, color: MUTED })
    y = drawDefense(y + 58, disabled)
    if (game.interaction_waiting) {
      text(game.interaction_waiting, inset, y + 11, { color: GOLD, size: 12 })
      y += 25
    }
    y = split(
      ['对手海域 · ' + (game.opponent_remaining_ships ?? '—'), () => actions.boardSide('enemy'), { primary: ui.boardSide === 'enemy' }],
      ['己方海域 · ' + (game.remaining_ships ?? '—'), () => actions.boardSide('self'), { primary: ui.boardSide === 'self' }],
      y,
    )
    const canAttack = myTurn && !blocked && !disabled && game.current_phase === 'battle' && game.attacks_remaining > 0
    y = board(y, marks(ui.boardSide), canAttack && ui.boardSide === 'enemy' ? actions.attack : null, {
      skipAttacked: ui.boardSide === 'enemy',
    })
    y = wide(PHASE_ACTIONS[game.current_phase] || '等待同步', y, actions.advance, {
      primary: true, disabled: disabled || !myTurn || blocked || !PHASE_ACTIONS[game.current_phase],
    })
    const hand = game.hand || []
    text('手牌 · ' + hand.length, inset, y + 10, { weight: 700 })
    y += 25
    for (const card of hand) y = wide(card.name + ' · 速阶 ' + card.speed, y, () => actions.card(card), { height: 38 })
    return wide('投降', y, actions.surrender, { disabled, height: 42 })
  }

  function resultReason(reason, won) {
    if (reason === 'attacks') return won ? '已击沉全部敌舰' : '己方舰队全灭'
    if (reason === 'surrender') return won ? '对手投降' : '己方投降'
    if (reason === 'opponent_disconnected') return won ? '对手掉线超时' : '掉线超时判负'
    return ''
  }

  function drawResult(y) {
    const winner = view.result?.winner
    const won = winner && winner === view.playerId
    const title = winner ? won ? '本局胜利' : '本局落败' : '对局结束'
    const reason = resultReason(view.result?.reason || view.game?.game_over_reason, won)
    box(inset, y, contentWidth, 186, '#112e46', won ? '#5cb29a' : '#516989', 18)
    shipMark(width / 2, y + 38, 0.9, won ? GOLD : MUTED)
    text(title, width / 2, y + 82, { size: 32, weight: 750, align: 'center', color: won ? GOLD : INK })
    text(
      (view.game?.opponent_name ? '对手 · ' + view.game.opponent_name : '自定义对局') + (reason ? ' · ' + reason : ''),
      width / 2, y + 123, { color: MUTED, align: 'center' },
    )
    if (view.game) {
      text(
        '己方余舰 ' + (view.game.remaining_ships ?? 0) + ' · 对手余舰 ' + (view.game.opponent_remaining_ships ?? 0),
        width / 2, y + 153, { size: 13, color: INK, align: 'center' },
      )
    }
    return wide('返回大厅', y + 202, actions.lobby, { primary: true })
  }

  function page() {
    if (view.result) return 'result'
    const state = view.game?.state
    if (state === 'placing_ships') return 'placement'
    if (state === 'rock_paper_scissors') return 'rps'
    if (state === 'attacking') return 'battle'
    return view.roomId ? 'waiting' : 'lobby'
  }

  function paint() {
    if (!view || !width || !height) return
    const next = page()
    if (scene !== next) {
      scene = next
      offset = 0
    }
    targets.length = 0
    backdrop()
    const line = top + 31
    text('战舰棋', inset, line, { size: 24, weight: 750 })
    const status = view.restoring ? '正在续座' : view.online ? '已连接' : '连接中'
    disc(width - inset - 58, line, 3, view.online ? CYAN : GOLD)
    text(status, width - inset, line, { size: 12, align: 'right', color: view.online ? CYAN : MUTED, max: 50 })
    const frameTop = top + 58
    const frameEnd = height - bottom - 10
    ctx.save()
    ctx.beginPath()
    ctx.rect(0, frameTop, width, Math.max(0, frameEnd - frameTop))
    ctx.clip()
    ctx.translate(0, -offset)
    const disabled = !view.online || view.busy || view.restoring
    let y = frameTop + 5
    if (view.notice) {
      box(inset, y, contentWidth, 31, '#341f2c', '#815265', 7)
      text(view.notice, inset + 8, y + 15, { color: '#ffd5dd', size: 12, max: contentWidth - 16 })
      y += 40
    }
    if (scene === 'placement') y = drawPlacement(y, disabled)
    else if (scene === 'rps') y = drawRps(y, disabled)
    else if (scene === 'battle') y = drawBattle(y, disabled)
    else if (scene === 'result') y = drawResult(y)
    else if (scene === 'waiting') y = drawWaiting(y, disabled)
    else y = drawLobby(y, disabled)
    ctx.restore()
    maxOffset = Math.max(0, y - frameEnd)
    if (offset > maxOffset) {
      offset = maxOffset
      paint()
      return
    }
    if (maxOffset > 0) {
      const area = Math.max(1, frameEnd - frameTop)
      const track = (area * area) / (area + maxOffset)
      ctx.fillStyle = 'rgba(118,192,203,0.4)'
      ctx.fillRect(width - 3, frameTop + (area - track) * offset / maxOffset, 2, track)
    }
  }

  wx.onTouchStart(event => {
    const first = event.touches[0]
    touch = first ? { x: first.clientX, y: first.clientY, initialOffset: offset, moved: false } : null
  })
  wx.onTouchMove(event => {
    const first = event.touches[0]
    if (!first || !touch || touch.y < top + 58) return
    const delta = first.clientY - touch.y
    if (Math.abs(delta) > 6) touch.moved = true
    if (touch.moved) {
      offset = Math.max(0, Math.min(maxOffset, touch.initialOffset - delta))
      paint()
    }
  })
  wx.onTouchCancel?.(() => { touch = null })
  wx.onTouchEnd(event => {
    const end = event.changedTouches[0]
    const started = touch
    touch = null
    if (!started || started.moved || !end) return
    const { clientX: x, clientY: y } = end
    if (y < top + 58 || y >= height - bottom - 10 || Math.abs(started.x - x) > 9 || Math.abs(started.y - y) > 9) return
    const contentY = y + offset
    const hit = targets.find(item => x >= item.x && x < item.x + item.w && contentY >= item.y && contentY < item.y + item.h)
    hit?.callback()
  })
  wx.onWindowResize?.(resize)
  resize()
  return {
    draw(nextView, nextUi) {
      view = nextView
      ui = nextUi
      paint()
    },
  }
}

module.exports = { createStage }
