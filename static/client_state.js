// Phase 8：从 game.js 原样迁出；作为经典脚本共享页面作用域。
// 游戏状态
window.gameState = {
    socket: null,
    playerId: null,
    playerSeat: null,       // 服务端公开的 p1/p2 座位，用于把连锁目标映射到正确棋盘
    roomId: null,
    playerName: '玩家',
    opponentName: '对手',
    ships: [],
    placedShips: 0,
    maxShips: 6,            // 默认可摆放的船数为6
    isMyTurn: false,
    attackOrder: [],        // 攻击顺序 [先手, 后手]；用于判断「自己是否先手」
    myAttacks: [],
    opponentAttacks: [],
    lastAttack: null,
    // 大厅（2026-09-18 大厅批）：最近一份 lobby_state、自己的身份键、
    // 是否已订阅（离开大厅页面时要退订，否则对局中还在收大厅广播）。
    lobbyState: null,
    lobbyKey: null,
    lobbySubscribed: false,
    // ── 实时观战（第 3 批）：观众侧的全部状态──────────────────────────
    // ⚠️ 这些字段**只属于观战屏**，绝不许被对局屏读到，反之亦然。
    //    观众没有 playerId（服务端给 game_state 的 attacking 分支不设它），
    //    所以观战屏的渲染一律靠 seatLabels 把座位对齐到 p1/p2，**不靠 playerId**。
    spectate: {
        active: false,          // 我是否正在观战（决定事件要不要处理、返回键去哪儿）
        roomId: null,           // 正在观战哪一局
        snapshot: null,         // 最后一次 spectate_sync（全场局状态的唯一来源）
        seatLabels: {},         // 原始座位 key -> 'p1'/'p2'（服务端 seat_labels 原样存）
        attacks: { p1: [], p2: [] },   // 各座位**打出去**的格（x/y/hit/ship_sunk）
        logs: [],               // 净化后的对局日志（增量追加，只留最近若干条）
        count: 0,
        limit: 0,
        ended: false,
        // ── 观战席名单 / 观战席聊天（第 4 批）──────────────────────────
        // ⚠️ 这三份数据**只存在于观战屏**：服务端把它们**只发给
        //    `spectate:<room_id>`** 这一个通道，对局双方根本不在那个收件人集合里
        //    （玩家侧只有 `count`，见 renderSpectateCounts 里那句注释）。
        me: null,               // 我自己在观战席上的显示名（来自 spectate_you）
        roster: [],             // [{name, joined_at}] —— 顺序 = 入席顺序
        chat: [],               // [{kind:'msg'|'notice', name, text}] 已渲染进 DOM
    },
    deck: [],               // 牌堆
    hand: [],               // 手牌
    discardPile: [],        // 弃牌堆
    chain: [],              // 连锁栈
    shenweiHoles: [],       // 神威！扣掉的区域 [{player,x1,y1,x2,y2,return_turn}]
    currentPhase: null,     // 当前游戏阶段
    fieldMagic: null,       // 场地魔法
    revealedCells: [],      // 已被卡牌显形的对方格子（服务端是持久记录，本地也要留住）
    pendingChainCard: null, // 连锁响应窗口里已选好、正在点目标的速阶3卡
    pendingEffectChoice: null, // 神之宣告：出牌前选好的效果
    selectedCardIndex: -1,  // 当前选中的卡牌索引，-1表示未选中
    selectedCardKey: null,  // 选中的是哪张卡（name+speed）——手牌一变下标就不可信了
    inRoom: false,          // 是否在对局房间中（用于掉线重连）
    reconnectToken: null,   // 对局重连 token
    frozen: false,          // 对手掉线宽限期内冻结操作
    opponentGone: null,     // 对手掉线信息 {deadline}
    sacrificedSelf: [],     // 自己因效果（恶魔契约等）牺牲的格子 → 画在自己棋盘上
    sacrificedOpponent: [], // 对方牺牲的格子（公开信息）→ 画在对方棋盘上
    // 「仁王之盾」被打破的格子：打了一炮被盾挡下，船毫发无伤。
    // ⚠️ 它【不算已攻击】：同一回合还能再打这一格（服务端也不记进 attacks）。
    // 画成"破盾"标记而不是普通命中叉，玩家才看得懂发生了什么。
    shieldBrokenMine: [],       // 我打出来的破盾格 → 画在对方棋盘
    shieldBrokenOpponent: [],   // 对方打出来的破盾格 → 画在我自己棋盘
    // 对方公开施加护盾的战舰位置；按整艘船分组，破盾或击沉时可准确清除。
    opponentShieldedShips: [],
    // 「绝处逢生」的候选格：牺牲前原本有战舰的那几格，唯一一艘新船必在其中。
    // 公开信息，双方棋盘都高亮；这些格子【不是红叉】，对方照样能打。
    lastStandCells: [],
    // 上面那批候选格属于【谁的棋盘】（服务端 last_stand_cells.owner 下发）。
    // 两块棋盘各有自己的 0-5 坐标，画错棋盘会让玩家以为"敌方可能在这几格"。
    lastStandOwner: null,
    // 冻结的 3×3 区域（服务端 frozen_area 下发）：{x1,y1,x2,y2,owner,caster,frozen,until_round}。
    // owner = 这片区域在哪块棋盘上（受害者）。船上的雪花仍只给被冻的人看，这里是"区域"。
    frozenArea: null,
    // 正等待自己点选一艘船牺牲（恶魔契约等）。棋盘每次重绘后靠它把高亮补回来，
    // 否则伤害结算的重绘会把选区冲掉、让人以为「点了没反应」。
    pendingSacrifice: null,
    // ★ 棋盘选区的**归属**（2026-09-20 优先级仲裁批）。
    // `selectingOnBoard` 只说"有人在选"，不说"是谁在选"；两张效果同时想抢棋盘时，
    // 后来的那个会因为 `selectingOnBoard` 为真而静默失败（玩家报的"点了没反应"）。
    // 记下归属后就能给出明确提示：{kind:'sacrifice', reason, label}。
    boardSelection: null,
    // 正等待自己点选至多 3 艘船加护盾（仁王之盾）：{max, picked, cells}。
    // 同样靠它让 paintRenwangCells() 在棋盘重绘后补回高亮 + 保住已选。
    renwangPick: null,
    // 当前生效的效果角标（服务端 active_effects / room_sync 下发）。
    // 出牌门禁要读它判断「绝处逢生」，所以必须有初值 —— 此前只在 room_sync
    // 里被赋值，未重连过的玩家这里是 undefined，读取方得各自容错。
    activeEffects: [],
    // 绝处逢生的两个标记，服务端 room_sync 显式下发（别再靠卡名猜，理由见
    // isLastStandActive 的注释）。lastStandWin 只用于提示文案，不参与门禁。
    lastStandLock: false,
    lastStandWin: false,
    // 生效中效果角标的数据（服务端按收件人视角分别下发 self / opponent）。
    // 浮层靠这两份数据按卡名回查说明，所以角标重绘后也能正确展开。
    activeEffectsSelf: [],
    activeEffectsOpponent: [],
    // 「拒绝所有阶段转换时点」开关（服务端 decline_priority 的本地镜像）。
    // 勾上后服务端不再向我发优先权询问；开关本身可随时取消勾选。
    declinePriority: false,
    // 已经把这个偏好推给哪个房间了（每个房间推一次就够）
    declinePrioritySyncedRoom: null,
    // 优先权询问里已选好、正在点目标的速阶3卡（与 pendingChainCard 同构）
    pendingPriorityCard: null,
    // 我发起的阶段转换正被拦下、在等对方响应（服务端 priority_waiting 下发）。
    // 非空时阶段按钮全部禁用 —— 与后端的 _priority_wait_reason 同一口径。
    priorityWaiting: null,
    // 对方正在宣言神机妙算（服务端 shenji_waiting 下发）。
    // 非空时我也不能行动 —— 与后端的 _shenji_wait_reason 同一口径。
    shenjiWaiting: null
}
