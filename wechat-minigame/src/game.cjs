const { createWechatSocket } = require('./socket.cjs')
const { createGameSession, supportsCard } = require('./game-session.cjs')
const { buildShare, createInviteCode, parseInvite } = require('./invite.cjs')
const { createStage } = require('./stage.cjs')

const STORAGE_PREFIX = 'battleship.wx.' + __BATTLESHIP_ORIGIN__ + '.'

function storage(key) {
  const name = STORAGE_PREFIX + key
  return {
    get() {
      try { return wx.getStorageSync(name) || null } catch { return null }
    },
    set(value) {
      try { wx.setStorageSync(name, value) } catch { /* 本次会话仍保留内存状态。 */ }
    },
    clear() {
      try { wx.removeStorageSync(name) } catch { /* 存储权限不可用。 */ }
    },
  }
}

function playerName() {
  const cache = storage('name')
  const existing = cache.get()
  if (typeof existing === 'string' && existing) return existing
  const name = '舰长' + (1000 + Math.floor(Math.random() * 9000))
  cache.set(name)
  return name
}

const ui = { cells: [], boardSide: 'enemy', name: playerName() }
let activeRoom = ''
let pendingInvite = null
const canvas = wx.createCanvas()
const socket = createWechatSocket(wx, __BATTLESHIP_ORIGIN__)

function toast(message) {
  wx.showToast({ title: String(message), icon: 'none', duration: 1800 })
}

function run(action) {
  Promise.resolve().then(action).catch(error => toast(error.message))
}

function readInvite(options) {
  return parseInvite(options?.query)
}

function offerJoin(options) {
  const invite = readInvite(options)
  if (!invite) return
  pendingInvite = invite
  render(session.snapshot())
}

function render(view) {
  if (activeRoom !== view.roomId) {
    activeRoom = view.roomId
    ui.cells = []
    ui.boardSide = 'enemy'
  }
  stage.draw(view, ui)
  if (!pendingInvite || !view.online || view.busy || view.restoring) return
  const invitation = pendingInvite
  pendingInvite = null
  if (view.roomId) {
    if (view.result) session.returnToLobby()
    else {
      if (view.roomId !== invitation.roomId) toast('请先结束当前对局')
      return
    }
  }
  run(() => session.joinRoom(invitation))
}

const session = createGameSession({ socket, storage: storage('seat'), playerName: ui.name, onChange: render })
const redraw = () => render(session.snapshot())
const stage = createStage(canvas, wx, {
  create: () => run(() => session.createRoom()),
  join: () => wx.showModal({
    title: '加入好友房',
    editable: true,
    placeholderText: '粘贴邀请码或输入公开房号',
    confirmText: '加入',
    success: result => { if (result.confirm) run(() => session.joinRoom(result.content)) },
  }),
  share: () => wx.shareAppMessage(buildShare(session.snapshot())),
  copy: () => {
    const code = createInviteCode(session.snapshot())
    if (code) wx.setClipboardData({ data: code })
  },
  close: () => run(() => session.leaveWaitingRoom()),
  toggleCell: (x, y) => {
    const need = session.snapshot().game?.max_ships || 6
    const index = ui.cells.findIndex(cell => cell.x === x && cell.y === y)
    if (index >= 0) ui.cells.splice(index, 1)
    else if (ui.cells.length < need) ui.cells.push({ x, y })
    else toast(need === 6 ? '已放置六艘，先点已有战舰撤回' : '已放置 ' + need + ' 艘，先点已有战舰撤回')
    redraw()
  },
  clear: () => {
    ui.cells = []
    redraw()
  },
  random: () => {
    const need = session.snapshot().game?.max_ships || 6
    const cells = Array.from({ length: 36 }, (_, index) => ({ x: index % 6, y: Math.floor(index / 6) }))
    for (let i = 0; i < need; i++) {
      const at = i + Math.floor(Math.random() * (cells.length - i))
      const selected = cells[at]
      cells[at] = cells[i]
      cells[i] = selected
    }
    ui.cells = cells.slice(0, need)
    redraw()
  },
  place: () => run(() => session.place(ui.cells)),
  choose: choice => run(() => session.choose(choice)),
  boardSide: side => {
    ui.boardSide = side
    redraw()
  },
  attack: (x, y) => run(() => session.attack(x, y)),
  advance: () => run(() => session.advance()),
  replyPriority: card => run(() => session.replyPriority(card)),
  replyChain: card => run(() => session.replyChain(card)),
  card: (card, respond) => {
    const current = session.snapshot()
    const reason = current.game?.card_unavailable_reasons?.[card.name]
    const supported = supportsCard(card)
    const canPlay = supported && (respond || !reason) && current.online && !current.busy && !current.restoring
    const hint = !supported ? '试玩版暂未接入这张牌的交互。' : !respond && reason ? reason : ''
    wx.showModal({
      title: card.name,
      content: [card.description, hint].filter(Boolean).join('\n'),
      showCancel: Boolean(canPlay),
      confirmText: canPlay ? '确认发动' : '知道了',
      success: result => {
        if (result.confirm && canPlay) {
          if (respond) respond(card)
          else run(() => session.playCard(card))
        }
      },
    })
  },
  surrender: () => wx.showModal({
    title: '确认投降',
    content: '投降后，本局将以落败结算。',
    confirmText: '确认投降',
    success: result => { if (result.confirm) run(() => session.surrender()) },
  }),
  lobby: () => session.returnToLobby(),
})

wx.showShareMenu?.({ menus: ['shareAppMessage'] })
wx.onShareAppMessage?.(() => buildShare(session.snapshot()))
wx.onShow?.(options => {
  offerJoin(options)
  if (!socket.connected && !socket.active) session.connect()
})
pendingInvite = readInvite(wx.getLaunchOptionsSync?.())
redraw()
session.connect()
