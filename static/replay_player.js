// 对局回放播放器：状态、帧解算、渲染、播放控制及设置入口。
// 回放 DOM 与播放状态由本文件维护；须在 game.js 之后、初始化事件触发之前加载。
const replayScreen = document.getElementById('replay-screen');
const replayPlayersTitleEl = document.getElementById('replay-players-title');
const replayStatusEl = document.getElementById('replay-status');
const replaySourceEl = document.getElementById('replay-source');
const replayStepIndexEl = document.getElementById('replay-step-index');
const replayStepTotalEl = document.getElementById('replay-step-total');
const replayStepKindEl = document.getElementById('replay-step-kind');
const replayStepActorEl = document.getElementById('replay-step-actor');
const replayTruncatedEl = document.getElementById('replay-truncated');
const replaySpeedGroup = document.getElementById('replay-speed-group');
const replayNameEls = [document.getElementById('replay-name-1'), document.getElementById('replay-name-2')];
const replayShipsEls = [document.getElementById('replay-ships-1'), document.getElementById('replay-ships-2')];
const replayBoardTitleEls = [document.getElementById('replay-board-title-1'), document.getElementById('replay-board-title-2')];
const replayBoardEls = [document.getElementById('replay-board-1'), document.getElementById('replay-board-2')];
const replayHandTitleEls = [document.getElementById('replay-hand-title-1'), document.getElementById('replay-hand-title-2')];
const replayHandEls = [document.getElementById('replay-hand-1'), document.getElementById('replay-hand-2')];
const replayCurrentEl = document.getElementById('replay-current');
const replayLogsEl = document.getElementById('replay-logs');
const replayPrevBtn = document.getElementById('replay-prev');
const replayPlayBtn = document.getElementById('replay-play');
const replayNextBtn = document.getElementById('replay-next');
const replayTrackEl = document.getElementById('replay-track');
const replayTrackFillEl = document.getElementById('replay-track-fill');
const replayTrackNodesEl = document.getElementById('replay-track-nodes');
const replayTrackThumbEl = document.getElementById('replay-track-thumb');
const replayNodeTipEl = document.getElementById('replay-node-tip');
const replayLeaveBtn = document.getElementById('replay-leave');
const allowReplayCheckbox = document.getElementById('settings-allow-replay');
const replaySettingMsg = document.getElementById('settings-replay-msg');

// REPLAY 界面段开始（对局回放屏，2026-09-23 回放批 §7）
// ===========================================================================
//
// 需求：在战绩里点开某一局详情 → 「对局回放」→ **全透视**回放（双方船位 + 双方手牌）。
// 以「每个人的每一次行动」为一步，可暂停 / 上一步 / 下一步 / 倍速；进度条标出关键节点，
// 鼠标移到节点能预览那一步发生了什么。**没有思考时间**，固定速度播放。
//
// ⚠️ 本段整体是**顶层作用域**的（不在 bindEventListeners 里）：入口在名片那套
//    嵌套作用域里，只有顶层定义才两边都调得到（CLAUDE.md 教训 #6：
//    顶层函数不许引用函数作用域里的东西 —— 那会 ReferenceError 被
//    `.then()` 吞掉、页面零提示）。
//
// ⚠️ 本段所有 DOM id 必须真的存在于 templates/index.html —— 引用了但页面里没有的 id
//    表现是 getElementById 拿到 null、被 `if (el)` 兜掉，**不报错、只是点了没反应**
//    （tools/dom_contract_check.mjs 就是查这个的）。

// 每一步的**固定**播放时长（毫秒）。契约 §7：没有思考时间，固定速度。
var REPLAY_STEP_MS = 900;
var REPLAY_SPEEDS = [1, 2, 4];

var replayState = {
    payload: null,      // 后端 JSON（steps / ships / hands / board_resets / nodes …）
    youAre: null,       // 'p1' | 'p2' | null（服务端算好的"你是哪一块棋盘"）
    k: 0,               // 当前帧（= steps 下标）
    playing: false,
    speed: 1,
    timer: null,        // setTimeout 链的句柄（暂停立刻清掉）
    scrubbing: false,
    frame: null,        // 当前帧解算结果（replayComputeFrame）
    nodeEls: [],        // 进度条节点元素（帧变化时只改 class，不重建）
    keyBound: false,
    /* 加载身份（generation）。每次"打开/退出/换一局"都 ++，回包时对不上就整包丢弃。
       ⚠️ 为什么必须有（A07，已读码 + 定向用例）：`/api/replay/<id>` 的响应原来
          无条件写进 replayState.payload，于是两条真实路径都能串局：
            · 先点 A 局（慢）再点 B 局（快）→ A 的响应后到，覆盖 B 的 payload，
              棋盘/事件/回合数全是 A 的，而屏幕上是 B 的标题；
            · 打开回放后马上退出 → 回包仍然写状态、**还会启动播放计时器**，
              回到首页之后后台还在按帧推进（没人看，但定时器在跑）。
          所以成功、失败、finally 三条路都要先核对身份与"回放屏是否还开着"。 */
    loadToken: 0,
    entryMatches: {},   // match_id → 战绩行（点回放时暂存，用来展示模式标签）
    socket: null        // 只读引用：退出时断开这条连接。**绝不 emit**
};

function replayIsActive() {
    return !!(replayScreen && replayScreen.classList.contains('active'));
}

// 座位 key。⚠️ 只能拼字符串：JS 里写 `'p%d' % (i+1)`（Python 那套）**不报错** ——
// `%` 是取余，label 恒为 NaN、棋盘一格不画，而控制台干干净净（本项目真栽过）。
// ⚠️ 这是"**槽位 i → 座位代号**"的**唯一实现**：棋盘、名字、手牌、候选格全走它。
//    本批缺陷 ④（`（你）`标到对面）的根因在**服务端**的 `you_are`（它按胜负算代号），
//    不在这个映射上 —— 见 `tools/dom_replay_frame_check.mjs` 的 E 组。
function replaySeatOf(index) {
    return index === 1 ? 'p2' : 'p1';
}

function replayInt(value, fallback) {
    var n = parseInt(value, 10);
    return isNaN(n) ? fallback : n;
}

// 卡名映射只共用 static/magic_cards.js（项目里唯一的卡面数据源）。
function replayCardOf(name) {
    var list = window.magicCards;
    if (!Array.isArray(list) || !name) return null;
    for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].name === name) return list[i];
    }
    return null;
}

function replayModeLabel(matchData, myId) {
    // ⚠️ 复用名片那套的**唯一口径**（`matchModeTagHTML`），本段不另写一份判据（教训 #1）。
    //    它在 bindEventListeners 的嵌套作用域里，但那是**函数声明会被提升**的同一个
    //    脚本作用域链 —— 运行时从顶层调它拿得到（本函数只在点按钮时执行）。
    return (typeof matchModeTagHTML === 'function') ? matchModeTagHTML(matchData, myId) : '';
}

// ---------------------------------------------------------------------------
// 帧解算（纯函数，**一处实现**）
// ---------------------------------------------------------------------------
// 契约 §7：
//   · 第 k 帧的棋盘标记 = `attacks` 时间线里 `step ≤ k` 的格，**减去** `board_resets`
//     中 `step ≤ k` 的重置（重置把那一块棋盘上已有的标记全擦掉）；
//   · 船位 / 手牌 / 效果 = 三条时间线里 `step ≤ k` 的条目（见各自的语义）。
// ⚠️ 时间线的语义**不是同一种**，别混：
//     `ships` / `hands` / `effects` = **替换**（某一侧出现时整份盖掉）；
//     `attacks`                     = **累加**（每条只带这一步新增的格）。
// ⚠️ 稀疏 + 增量：某条只带变化的那一侧 ⇒ 必须**沿用上一帧另一侧的值**
//    （所以这里是"按 step 升序把所有 `step ≤ k` 的条目叠上去"，不是"取最后一条"）。
// ⚠️ `board_resets[].side` = **哪一块棋盘被重置**（不是发起方），所以重置只清那一侧的攻击标记。
// ⚠️ 标记**不再**从 attack 步反推（那是"同一件事两份数据源"，正是本批修掉的缺陷）：
//    只有普通炮击会写 attack 步，卡牌类伤害（轰炸/硫磺火焰/溅射/雷达子弹/探测雷达）
//    一条都不写。数据源统一成 `Player.attacks` 那份权威动作记录（与观战棋盘帧同一份）。
function replayComputeFrame(payload, k) {
    var frame = {
        ships: { p1: [], p2: [] },
        hand: { p1: [], p2: [] },
        marks: { p1: {}, p2: {} },
        resetAt: { p1: [], p2: [] },
        effect: { p1: null, p2: null },
        // ★ 剩余战舰数的**权威值**（`Player.remaining_ships`，服务端 `remaining` 时间线）。
        //   `null` = 这一份回放没有那条时间线（老 blob）⇒ `replayAliveShips` 退回数船格。
        alive: { p1: null, p2: null }
    };
    if (!payload || !Array.isArray(payload.steps)) return frame;

    var steps = payload.steps;
    var target = replayInt(k, 0);
    if (target < 0) target = 0;
    if (target > steps.length - 1) target = steps.length - 1;
    if (target < 0) return frame;

    // ① 两条时间线：按 step 升序**叠加**（增量），只保留 step ≤ k 的条目。
    //    ⚠️ 时间线已按 step 升序（后端按追加顺序写），这里直接顺序扫一遍 —— 一遍拿两侧，
    //       别每块棋盘各扫一次。
    replayFoldTimeline(payload.ships, target, frame.ships);
    replayFoldTimeline(payload.hands, target, frame.hand);
    // 效果时间线同一种"稀疏 + 增量"，叠进 frame.effect[side]（见 replayEffectOf）。
    replayFoldTimeline(payload.effects, target, frame.effect);
    // ★ 剩余战舰数（**权威计数**，与观战/实战同一份）：值不是数组而是数字，
    //   所以不能走 `replayFoldTimeline`（它按数组/对象处理），自己扫一遍。
    //   ⚠️ 老 blob 没有 `remaining` ⇒ 两个座位都留 `null` ⇒ 前端退回数船格
    //      （见 `replayAliveShips`），显示与改动前一致，不是"归零"。
    var rowsLeft = Array.isArray(payload.remaining) ? payload.remaining : [];
    for (var m = 0; m < rowsLeft.length; m++) {
        var rrow = rowsLeft[m] || {};
        if (replayInt(rrow.step, -1) > target) break;   // 时间线升序，后面都不用看了
        if (typeof rrow.p1 === 'number') frame.alive.p1 = rrow.p1;
        if (typeof rrow.p2 === 'number') frame.alive.p2 = rrow.p2;
    }

    // ② 棋盘重置：按侧收集 `step ≤ k` 的重置点（后面的攻击要判"是不是在重置之后"）。
    var resets = Array.isArray(payload.board_resets) ? payload.board_resets : [];
    for (var r = 0; r < resets.length; r++) {
        var reset = resets[r] || {};
        var resetSide = reset.side;
        var resetStep = replayInt(reset.step, -1);
        if ((resetSide === 'p1' || resetSide === 'p2') && resetStep >= 0 && resetStep <= target) {
            frame.resetAt[resetSide].push(resetStep);
        }
    }

    // ③ 攻击标记：数据源 = `payload.attacks`（**稀疏 + 增量**时间线，后端从
    //    `Player.attacks` 那份**权威动作记录**里取的 —— 与观战棋盘帧同一份数据源）。
    //
    // ⚠️⚠️ 这里**不许**再从 attack 步反推标记（本批之前就是那么写的，而且出过两次事故）：
    //    · 第 1 次：`var after = false; for (m…) if (resetAt[side][m] <= i) { after = true; break; }`
    //      然后 `if (!after) continue;` —— 即"**必须存在**一个 ≤ i 的重置才画这一炮"。
    //      而绝大多数局的 `board_resets` 是空的 ⇒ `after` 恒为 false ⇒ 每一炮都被丢掉
    //      ⇒ 回放里一个"已轰过的格"都看不到（作者实报，教训 #7 的"方向写反"型）。
    //      它当时全绿，因为既有断言只要求"拖拽 seek 与连点下一步自洽"（系统性丢标记也自洽）
    //      和"船格 6/6 与后端相等"（船 ≠ 攻击标记）——**没有任何一条断言要求标记真的出现过**。
    //    · 第 2 次（本批）：**只有普通炮击**会写 `type='attack'` 的游戏日志，而
    //      `轰炸` / `硫磺火焰` / `溅射` / `雷达子弹` / `探测雷达` 逐格写 `Player.attacks`
    //      **一条 attack 步都不写** ⇒ 那五张卡打出的格子在回放里**一个标记都没有**
    //      （作者实报："那一整行看着是没挨过炮的海面"）。
    //      所以标记的**唯一数据源**是这份时间线；日志步只能当"这一步发生了什么"的文案。
    //
    // ⚠️ 语义（与改动前逐格相同，别改）：
    //    一炮（时间线里 step = i 的那一格，落在 board B）在帧 k 要看得见，当且仅当
    //    **i ≤ k** 且它发生在 **B 的最后一次重置之后**（重置把那块棋盘上已有的标记全擦掉了）。
    //    等价写法就是取最大值 `lastReset`，没有重置则为 -1。
    var lastReset = { p1: -1, p2: -1 };
    for (var s = 0; s < 2; s++) {
        var rside = replaySeatOf(s);
        var list = frame.resetAt[rside];
        for (var n = 0; n < list.length; n++) {
            if (list[n] > lastReset[rside]) lastReset[rside] = list[n];
        }
    }
    // ③-1 先把 `step ≤ k` 的格**累加**到两块棋盘上（增量：每条只带这一步新增/改写的格）。
    //      ⚠️ 与 `ships` / `hands` 的"替换"语义**不同**：这里是**累加**，
    //         所以走自己那一段，不复用 `replayFoldTimeline`（那是替换）。
    var rowsAtk = Array.isArray(payload.attacks) ? payload.attacks : [];
    var hits = { p1: [], p2: [] };
    for (var t = 0; t < rowsAtk.length; t++) {
        var arow = rowsAtk[t] || {};
        var astep = replayInt(arow.step, -1);
        if (astep < 0) continue;
        if (astep > target) break;          // 时间线升序，后面都不用看了
        for (var q = 0; q < 2; q++) {
            var aboard = replaySeatOf(q);
            var cells = arow[aboard];
            if (!Array.isArray(cells)) continue;
            for (var c = 0; c < cells.length; c++) {
                hits[aboard].push({ step: astep, cell: cells[c] || {} });
            }
        }
    }
    // ③-2 再按"最后一次重置"过滤（重置之前的炮一律不画），同一格取**最后**一条。
    //      ⚠️ "同一格取最后一条"不是随手写的：真对局里约 3/10 局会出现"某一格先被炮击
    //         打沉、又被【轰炸】/【硫磺火焰】补一条落空"（服务端卡里那句过滤只按"这次
    //         真的摘掉了哪些船"，已经沉过的船不在候选表里）。实战前端逐条覆盖同一个键
    //         ⇒ 玩家**看到的是后写的那条**；`replay._attacks_snapshot` 也按同一口径取值。
    for (var b = 0; b < 2; b++) {
        var boardSide = replaySeatOf(b);
        var mine = hits[boardSide];
        for (var j = 0; j < mine.length; j++) {
            var hit = mine[j];
            var pt = hit.cell || {};
            var x = replayInt(pt.x, -1);
            var y = replayInt(pt.y, -1);
            if (x < 0 || y < 0 || x > 5 || y > 5) continue;
            if (hit.step <= lastReset[boardSide]) continue;      // 重置把它擦掉了
            frame.marks[boardSide][x + ',' + y] = {
                hit: pt.hit === true,
                sunk: pt.sunk === true
            };
        }
    }
    return frame;
}

// 两条稀疏时间线 + 效果时间线共用的叠加逻辑（**一处实现**）。
// ⚠️ 效果行与 `ships` / `hands` 同一种**替换**语义（不是深合并）：某一侧出现时它带着
//    该座位效果的全部字段，所以"叠上去"就是"换成这一份"。
function replayFoldTimeline(rows, target, into) {
    if (!Array.isArray(rows)) return;
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i] || {};
        if (replayInt(row.step, -1) > target) break;   // 时间线升序，后面都不用看了
        if (Array.isArray(row.p1)) into.p1 = row.p1;
        else if (row.p1 && typeof row.p1 === 'object') into.p1 = row.p1;
        if (Array.isArray(row.p2)) into.p2 = row.p2;
        else if (row.p2 && typeof row.p2 === 'object') into.p2 = row.p2;
    }
}

// 某一侧棋盘上"某一格"的样子。⚠️ 新写一份（**不复用观战那套**）：
// 观战的渲染故意只会画"已轰过的格"，它的安全前提是"手上根本没有船位数据"；
// 回放要画船，两者绝不能共用渲染。
//
// ★ 字形口径（作者实报："船存在的格子显示错误会出现一个叉叉"）：
//     `✕` = **挨过炮**（命中）才有的字形；没挨过炮的船格必须是**船**。
//     原来写成 `(hasShip || hit) ? '✕' : …` ⇒ **任何有船的格子都是叉**
//     （那是"命中"的字形），看着就像"这一格已经被打过、别再点了"。
//     本屏用的三个字形各有各的含义、互不重复：
//       · `⛴` 船（有船、没挨过炮）  · `✕` 命中（挨过炮）  · `○` 落空。
//     ⚠️ 船格在**其它屏**上本来就不是靠字符表达的（`.cell.ship` 是不透明金属底
//        + 立体阴影，没有字形），所以这里必须新选一个符号；`⛴` 在本项目里
//        没有被别处占用（`❄` / `⛨` / `?` / `✕` / `○` 都已各有含义）。
function replayEffectOf(frame, side, x, y) {
    var eff = (frame && frame.effect) ? frame.effect[side] : null;
    if (!eff || typeof eff !== 'object') return null;
    var key = x + ',' + y;
    var i, cell;
    var shield = Array.isArray(eff.shield) ? eff.shield : [];
    for (i = 0; i < shield.length; i++) {
        cell = shield[i];
        if (Array.isArray(cell) && replayInt(cell[0], -1) === x && replayInt(cell[1], -1) === y) {
            return { kind: 'shield', label: '护盾：这一格有战舰护盾，能挡下下一炮' };
        }
    }
    var holes = Array.isArray(eff.shenwei_holes) ? eff.shenwei_holes : [];
    for (i = 0; i < holes.length; i++) {
        var h = holes[i] || {};
        if (x >= replayInt(h.x1, -1) && x <= replayInt(h.x2, -1)
            && y >= replayInt(h.y1, -1) && y <= replayInt(h.y2, -1)) {
            return { kind: 'hole', label: '神威：这一格被扣掉，暂时打不到' };
        }
    }
    var frozen = eff.frozen_area;
    if (frozen && typeof frozen === 'object'
        && x >= replayInt(frozen.x1, -1) && x <= replayInt(frozen.x2, -1)
        && y >= replayInt(frozen.y1, -1) && y <= replayInt(frozen.y2, -1)) {
        return { kind: 'frozen', label: '冻结区：这一格的战舰本回合不能开火' };
    }
    var stand = Array.isArray(eff.last_stand_cells) ? eff.last_stand_cells : [];
    for (i = 0; i < stand.length; i++) {
        var s = stand[i];
        var sx = Array.isArray(s) ? replayInt(s[0], -1) : replayInt(s && s.x, -1);
        var sy = Array.isArray(s) ? replayInt(s[1], -1) : replayInt(s && s.y, -1);
        if (sx === x && sy === y) {
            return { kind: 'laststand', label: '绝处逢生：新战舰可能出现在这一格' };
        }
    }
    return null;
}

function replayCellOf(frame, side, x, y) {
    var ships = (frame && frame.ships && Array.isArray(frame.ships[side])) ? frame.ships[side] : [];
    var marks = (frame && frame.marks && frame.marks[side]) ? frame.marks[side] : {};
    // ⚠️ 这里取的是**第一条**命中的船格。它与"以最后一条为准"**必须等价** ——
    //    判据在服务端：`replay._ship_cells` 保证**同一格最多只出一条**
    //    （`lost` 显式沉没登记优先于活船列表的推断，撞车时活船那条整条丢掉，
    //     见 `replay.py` 里那段 ★★ 说明）。所以本函数**不许**自己去仲裁
    //    "两份说法取哪一条"：那会让同一件事长出第二份实现（教训 #1），
    //    而且两处迟早漂移成"回放与后端说法不一致"。
    //    格子上的 `src` 字段就是给这条契约留的探针（守卫：tests/test_replay_lost_priority.py）。
    var shipCell = null;
    for (var i = 0; i < ships.length; i++) {
        var c = ships[i];
        if (c && replayInt(c.x, -1) === x && replayInt(c.y, -1) === y) { shipCell = c; break; }
    }
    var mark = marks[x + ',' + y] || null;
    var sunk = !!(shipCell && shipCell.sunk && shipCell.alive !== true);
    var effect = replayEffectOf(frame, side, x, y);
    var cell = {
        hasShip: !!shipCell,
        sunk: sunk,
        hit: !!(mark && mark.hit),
        miss: !!(mark && !mark.hit),
        effect: effect ? effect.kind : null
    };
    // 无障碍文本 / title —— 色盲与读屏用户拿到的就是这一条（与实战棋盘同口径）。
    // ⚠️ 效果格**先**说效果再说船/命中：一格可能同时是"有船的护盾格"，
    //    但玩家点开回放最想知道的是"这里为什么长得不一样"。
    var base;
    if (cell.sunk) base = '击沉：这一格的战舰已被打沉';
    else if (shipCell && cell.hit) base = '命中：这一格有战舰';
    else if (shipCell) base = '战舰：这一格有船，还没被打到';
    else if (cell.hit) base = '命中：这一格已经空了';
    else if (cell.miss) base = '落空：这一格打空了';
    else base = '海面：没有船，也没被打过';
    // ★ 神威！致死：这一格**同时**是"战舰被就地打沉"与"这片区域被从棋盘上扣掉"
    //   （`server.apply_magic_effect` 的 `神威！` 致死分支：区域内恰好 1 艘 ⇒
    //   登记成沉没格 + 整片 3×3 进 `shenwei_holes`）。
    //   作者拍板的口径：**格子按沉没画**（红叉），"这格被挖掉、暂时打不到"这条
    //   信息**放进 title/无障碍文案**里 —— 不要在同一格上再叠一个洞的视觉标记
    //   （两个标记叠在同一格上，玩家既读不出"沉了"也读不出"挖了"）。
    if (cell.sunk && effect && effect.kind === 'hole') {
        base += '（神威把这一格从棋盘上扣掉了，这一格的战舰不会再回来）';
    }
    cell.label = effect ? (effect.label + '（' + base + '）') : base;
    return cell;
}

// 还有几艘船活着。★★ 数据源 = **权威计数** `Player.remaining_ships`
// （服务端 `remaining` 时间线，与观战 / 实战 / 重连快照读的是同一个字段）。
//
// ⚠️⚠️ 这里**不许**改成"数船格"（本批之前就是那么写的，而且真的画错过）：
//     船格上的 `alive` 用的是 `len(hits) < len(positions)` 这条判据，而
//     `Player.remaining_ships` 是**另一份**记账 —— 两者实测会不等（`神威！` 致死支
//     把船从 `ships` 里摘掉却不登记沉没、也不加回计数；`ships`/`sunken_ships` 在几条
//     魔法路径上也会错开）。实测（seed 4242 的真对局）：`remaining_ships=1` 而船格
//     里有 3 个 `alive` ⇒ 回放屏写 3、实战/观战屏写 1，同一件事两个数。
//     ⇒ 回放的职责是**与其它屏说同一句话**，权威计数归 `remaining_ships`；
//        船格只表达"船在哪、沉没没沉"。**两者对不上时错在游戏侧的记账**，
//        由 pytest 的 `test_replay_remaining_matches_the_game_counter` 那一族盯着，
//        回放**不许**在这里再长出一份自己的计数推导（教训 #1）。
//
// ⚠️ 老 blob（本批之前落的）没有 `remaining` ⇒ `frame.alive` 是 `null` ⇒ 退回数船格
//     （与改动前一致）。判据必须写 `== null` 而不是 `!n`：**0 艘是合法值**
//     （全灭），写成假值判断会让"全灭"退回数船格、又变回两套口径。
function replayAliveShips(frame, side) {
    var counted = (frame && frame.alive) ? frame.alive[side] : null;
    if (counted !== null && counted !== undefined && isFinite(counted)) {
        return Math.trunc(counted);
    }
    var ships = (frame && frame.ships && Array.isArray(frame.ships[side])) ? frame.ships[side] : [];
    var seen = {};
    var alive = 0;
    for (var i = 0; i < ships.length; i++) {
        var c = ships[i] || {};
        var key = replayInt(c.x, -1) + ',' + replayInt(c.y, -1);
        if (seen[key]) continue;
        seen[key] = true;
        if (c.alive === true || c.sunk !== true) alive++;
    }
    return alive;
}

// ---------------------------------------------------------------------------
// 关键节点（**只用服务端给的 `nodes`**，前端不许另算一套 —— 两套判据必然漂移）
// ---------------------------------------------------------------------------
// 关键节点在进度条上的**位置**：按它**真实落在第几步**算，不是按它是第几个节点。
//
// ⚠️ 这两者**必须**同口径，否则节点与进度、跳转全对不上（本批修掉的缺陷）：
//    拖动/点击/`fill`/`thumb` 用的都是 `k / (steps.length - 1)`（见 `updateReplayTrack`
//    与 `replaySeekFromPointer`），而节点原来按 `i / (nodes.length - 1)` 摆 ——
//    节点是**稀的**（只有魔法卡 / 命中 / 击沉 / 阶段 / 重置才有一个），
//    一局 91 步里只有 51 个节点时，绝大多数节点都被摆到了与它真实步骤无关的位置
//    （实测那局 51 个节点里 47 个位置不符），于是"点这个点跳到那一步"完全错位。
//
// ⚠️ 越界夹住：服务端 `board_resets` 的重置点记在**下一个** step 上
//    （`replay.note_board_reset` 不追加步骤，直接记 `len(steps)`），
//    若这次重置之后再没有步骤，那个重置节点就落在"最后一格的下一格"。
//    位置夹到最后一格（与"这一刻还没有下一步"的语义一致）——
//    `updateReplayTrack` 判"到了没"用的仍是 `node.step <= k` 的原值，两者不冲突。
//
// ⚠️ `totalSteps <= 1`（0 步 / 只有 1 步）时返回 **0**，不是 50：
//    `updateReplayTrack` 的 `percent = total > 1 ? (index / (total - 1)) * 100 : 0`
//    （`updateReplayTrack`）把 `fill` / `thumb` 放在 **0%** ——
//    这是分母 `total - 1 == 0` 的唯一有意义的取值（没有可拖动的区间，
//    游标只能停在起点）。节点若按"摆正中"给 50%，
//    就会出现"游标在 0%、唯一的节点在中间"的坐标不一致（本批审查发现）。
//    两边同口径 ⇒ 单步回放里节点与游标重叠，点击跳转也仍落在它自己那一步。
function replayNodePercent(step, totalSteps) {
    var total = replayInt(totalSteps, 0);
    if (total <= 1) return 0;
    var at = replayInt(step, 0);
    if (at < 0) at = 0;
    if (at > total - 1) at = total - 1;
    return (at / (total - 1)) * 100;
}

// 某个节点的 tooltip：说出"那一步做了什么"（契约 §7）。
function replayNodeTipText(node) {
    if (!node) return '';
    var payload = replayState.payload;
    var step = (payload && Array.isArray(payload.steps))
        ? payload.steps[replayInt(node.step, -1)] : null;
    var label = String(node.label || '');
    var parts = ['第 ' + (replayInt(node.step, 0) + 1) + ' 步'];
    // 行动者：只在**标签里还没有这个名字**时补上。
    // ⚠️ 服务端的阶段类节点标签本身就带名字（`note_action` 的 label 是
    //    `_log_name(...)` 拼的），无脑补一下会得到
    //    「第 3 步 · 甲 · 甲 进入战斗阶段」（本批实测就是这么读出来的）。
    var actor = (step && step.actor) ? String(step.actor) : '';
    if (actor && label.indexOf(actor) < 0) parts.push(actor);
    parts.push(label);
    var text = parts.join(' · ');
    if (step && step.text && String(step.text) !== label && String(step.text).indexOf(label) < 0) {
        text += '\n' + String(step.text);
    }
    return text;
}

function replayStepKindText(kind) {
    var map = {
        attack: '炮击', magic: '魔法卡', quick_chat: '快捷消息', game_over: '对局结束',
        system: '系统', place_ships: '摆放战舰', rps_choice: '猜拳', enter_battle: '进攻阶段',
        enter_end: '结束阶段', end_turn: '结束回合', surrender: '投降', result: '对局结束'
    };
    var k = String(kind || '');
    return map[k] || (k || '—');
}

// ---------------------------------------------------------------------------
// 渲染
// ---------------------------------------------------------------------------
function renderReplayBoards() {
    var frame = replayState.frame;
    if (!frame) return;
    for (var index = 0; index < replayBoardEls.length; index++) {
        var board = replayBoardEls[index];
        if (!board) continue;
        var side = replaySeatOf(index);
        renderReplayBoard(board, frame, side);
    }
}

// 画一块**全透视**棋盘。⚠️ 这是本批新写的那一份渲染（见文件顶部那条隔离说明）。
function renderReplayBoard(board, frame, side) {
    // ⚠️ 先算完整帧、再清空 DOM：先清后填的渲染一旦中途抛异常就会留下半块空棋盘
    //    （CLAUDE.md 硬规矩："先清空再填充"的渲染必须先校验数据）。
    var cells = [];
    for (var y = 0; y < 6; y++) {
        for (var x = 0; x < 6; x++) {
            cells.push({ x: x, y: y, cell: replayCellOf(frame, side, x, y) });
        }
    }
    board.innerHTML = '';
    for (var i = 0; i < cells.length; i++) {
        var item = cells[i];
        var el = document.createElement('div');
        var cls = 'cell';
        if (item.cell.sunk) cls += ' ship sunk hit';
        else if (item.cell.hasShip && item.cell.hit) cls += ' ship hit';
        else if (item.cell.hasShip) cls += ' ship';
        else if (item.cell.hit) cls += ' hit';
        else if (item.cell.miss) cls += ' miss';
        else cls += ' replay-water';
        // 场上公开效果（仁王之盾的护盾格 / 神威挖的洞 / 冻结区 / 绝处逢生的候选格）。
        // ⚠️ 复用**实战场已经在用**的那几个类名（一份样式，两处用它）：
        //    `shielded`（带出 .cell.ship.shielded 的 🛡）/ `shenwei-hole` /
        //    `frozen-area` / `last-stand-candidate`。别在这里另起一套类名（教训 #1）。
        // ⚠️ 但它们放在**并列的分支**里：一格可能同时是"有船的护盾格"，
        //    所以不能写成上面那种 if/else 链。
        // ★ 例外（2026-09-24）：**沉没格不叠效果类**。`神威！`致死那一格有两重身份
        //   （战舰沉了 + 整片区域被扣掉），而 `.cell.shenwei-hole` 的
        //   `background: repeating-linear-gradient(...) !important` 会**盖掉**红色沉没底
        //   （`.cell.hit` 那份只是普通 background）⇒ 画出来是一片斜纹、不是红叉。
        //   作者口径：格子按沉没画，"被挖掉"这条信息放 title/无障碍文案（见 `replayCellOf`）。
        //   ⚠️ 这条判据只在**沉没**时短路，护盾 / 冻结 / 绝处逢生候选格照旧叠加
        //      （那几种与"挨过炮"不冲突：`.cell.hit` 的底不会被它们的描边盖掉）。
        if (!item.cell.sunk) {
            if (item.cell.effect === 'shield') cls += ' shielded';
            else if (item.cell.effect === 'hole') cls += ' shenwei-hole';
            else if (item.cell.effect === 'frozen') cls += ' frozen-area';
            else if (item.cell.effect === 'laststand') cls += ' last-stand-candidate';
        }
        el.className = cls;
        el.dataset.x = String(item.x);
        el.dataset.y = String(item.y);
        el.title = item.cell.label;
        el.setAttribute('aria-label', item.cell.label);
        // ★ 字形（缺陷 ①）：**只有挨过炮才是 ✕**。
        //   击沉格也是 ✕（打沉的那一炮本身是命中），没挨过炮的船格是 ⛴。
        if (item.cell.sunk || item.cell.hit) el.textContent = '✕';
        else if (item.cell.hasShip) el.textContent = '⛴';
        else if (item.cell.miss) el.textContent = '○';
        else el.textContent = '';
        board.appendChild(el);
    }
}

function renderReplayPlayers() {
    var payload = replayState.payload;
    if (!payload) return;
    var frame = replayState.frame;
    // ⚠️ **槽位口径与座位口径必须一一对齐**（本批的缺陷 ④ 就出在这条对齐上，只不过
    //    错的那一头在服务端的 `you_are`，见 `replay.you_are` 的说明）：
    //      · `names` / `replayNameEls` / `replayBoardEls` … 都是**槽位**下标（0 = 左边）；
    //      · `replaySeatOf(i)` 把槽位 i 映射到座位代号（0→p1、1→p2），**一处实现**；
    //      · `payload.p1_name` 与 `frame.*['p1']` 都是**座位**口径。
    //    所以"槽位 i 的显示名"必须等于"座位 `replaySeatOf(i)` 的名字"，两处不许各配一次。
    var names = { p1: payload.p1_name || '先手', p2: payload.p2_name || '后手' };
    for (var i = 0; i < 2; i++) {
        var side = replaySeatOf(i);
        var name = String(names[side]);
        var mine = replayState.youAre === side;
        if (replayNameEls[i]) replayNameEls[i].textContent = name + (mine ? '（你）' : '');
        if (replayShipsEls[i]) replayShipsEls[i].textContent = String(replayAliveShips(frame, side));
        if (replayBoardTitleEls[i]) replayBoardTitleEls[i].textContent = name + ' 的棋盘';
        if (replayHandTitleEls[i]) replayHandTitleEls[i].textContent = name + ' 的手牌';
        if (replayBoardEls[i]) replayBoardEls[i].classList.toggle('replay-board-mine', mine);
    }
}

// 双方手牌：**只读展示卡名**（用 magic_cards.js 的映射取显示名/图标），
// 不可点击、不触发任何操作（契约 §7）。
function renderReplayHands() {
    var frame = replayState.frame;
    if (!frame) return;
    for (var i = 0; i < replayHandEls.length; i++) {
        var el = replayHandEls[i];
        if (!el) continue;
        var side = replaySeatOf(i);
        var hand = Array.isArray(frame.hand[side]) ? frame.hand[side] : [];
        el.innerHTML = '';
        if (!hand.length) {
            var empty = document.createElement('span');
            empty.className = 'replay-hand-empty';
            empty.textContent = '（没有手牌）';
            el.appendChild(empty);
            continue;
        }
        for (var j = 0; j < hand.length; j++) {
            var cardName = String(hand[j]);
            var card = replayCardOf(cardName);
            var chip = document.createElement('span');
            chip.className = 'replay-hand-card';
            chip.textContent = card ? (card.icon ? card.icon + ' ' + card.name : card.name) : cardName;
            if (card && card.type) chip.title = card.type + '·速阶' + card.speed;
            // 明确标成只读：没有 tabindex、没有监听、不是 button。
            chip.setAttribute('aria-readonly', 'true');
            el.appendChild(chip);
        }
    }
}

function renderReplayCurrentStep() {
    if (!replayCurrentEl) return;
    var payload = replayState.payload;
    var step = (payload && Array.isArray(payload.steps)) ? payload.steps[replayState.k] : null;
    if (!step) { replayCurrentEl.textContent = '—'; return; }
    var kind = replayStepKindText(step.kind);
    var who = step.actor ? String(step.actor) : '（无人）';
    replayCurrentEl.textContent = '第 ' + (replayState.k + 1) + ' 步 · ' + kind + ' · '
        + who + '：' + String(step.text || '');
}

function renderReplayLogs() {
    if (!replayLogsEl) return;
    var payload = replayState.payload;
    var steps = (payload && Array.isArray(payload.steps)) ? payload.steps : [];
    // ⚠️ 先在内存里拼好、再一次性铺 DOM（避免"清空后填充"留下半帧）。
    var items = [];
    var upto = Math.min(replayState.k, steps.length - 1);
    for (var i = 0; i <= upto; i++) {
        var step = steps[i] || {};
        items.push({
            i: i,
            current: i === replayState.k,
            text: '第' + (i + 1) + '步 · ' + (step.actor ? step.actor + '：' : '') + String(step.text || '')
        });
    }
    replayLogsEl.innerHTML = '';
    if (!items.length) {
        replayLogsEl.textContent = '暂无行动记录';
        return;
    }
    for (var j = 0; j < items.length; j++) {
        var row = document.createElement('div');
        row.className = 'replay-log-item' + (items[j].current ? ' replay-log-current' : '');
        row.textContent = items[j].text;
        replayLogsEl.appendChild(row);
    }
    replayLogsEl.scrollTop = replayLogsEl.scrollHeight;
}

function updateReplayChrome() {
    var payload = replayState.payload;
    var steps = (payload && Array.isArray(payload.steps)) ? payload.steps : [];
    var total = steps.length;
    var step = steps[replayState.k] || null;
    if (replayStepIndexEl) replayStepIndexEl.textContent = String(total ? replayState.k + 1 : 0);
    if (replayStepTotalEl) replayStepTotalEl.textContent = String(total);
    if (replayStepKindEl) replayStepKindEl.textContent = step ? replayStepKindText(step.kind) : '—';
    if (replayStepActorEl) replayStepActorEl.textContent = (step && step.actor) ? String(step.actor) : '—';
    if (replaySourceEl) replaySourceEl.textContent = '战绩';
    if (replayTruncatedEl) {
        var truncated = payload && payload.truncated ? String(payload.truncated) : '';
        replayTruncatedEl.textContent = truncated;
        replayTruncatedEl.classList.toggle('hidden', !truncated);
    }
    if (replayPlayersTitleEl) {
        replayPlayersTitleEl.textContent = payload
            ? String(payload.p1_name || '先手') + ' vs ' + String(payload.p2_name || '后手') : '—';
    }
    // 两端要禁用按钮（别让 k 越界）。
    if (replayPrevBtn) replayPrevBtn.disabled = replayState.k <= 0;
    if (replayNextBtn) replayNextBtn.disabled = total === 0 || replayState.k >= total - 1;
    if (replayPlayBtn) {
        replayPlayBtn.textContent = replayState.playing ? '暂停' : '播放';
        replayPlayBtn.disabled = total === 0;
    }
    updateReplayTrack();
}

function updateReplayTrack() {
    var payload = replayState.payload;
    var steps = (payload && Array.isArray(payload.steps)) ? payload.steps : [];
    var total = steps.length;
    var index = total ? replayState.k : 0;
    var percent = total > 1 ? (index / (total - 1)) * 100 : 0;
    if (replayTrackFillEl) replayTrackFillEl.style.width = percent + '%';
    if (replayTrackThumbEl) replayTrackThumbEl.style.left = percent + '%';
    if (replayTrackEl) {
        replayTrackEl.setAttribute('aria-valuemin', '0');
        replayTrackEl.setAttribute('aria-valuemax', String(Math.max(0, total - 1)));
        replayTrackEl.setAttribute('aria-valuenow', String(index));
        replayTrackEl.setAttribute('aria-valuetext',
            total ? ('第 ' + (index + 1) + ' 步 / 共 ' + total + ' 步') : '没有可回放的行动');
    }
    // 节点只重建一次；每帧只改"到没到"这一个 class（重建 2000 个节点会卡）。
    for (var i = 0; i < replayState.nodeEls.length; i++) {
        var item = replayState.nodeEls[i];
        if (!item || !item.el) continue;
        item.el.classList.toggle('passed', item.node.step <= replayState.k);
    }
}

function buildReplayTrackNodes() {
    if (!replayTrackNodesEl) return;
    var payload = replayState.payload;
    var nodes = (payload && Array.isArray(payload.nodes)) ? payload.nodes : [];
    var steps = (payload && Array.isArray(payload.steps)) ? payload.steps : [];
    replayTrackNodesEl.innerHTML = '';
    replayState.nodeEls = [];
    for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i] || {};
        var el = document.createElement('span');
        el.className = 'replay-track-node kind-' + String(node.kind || 'phase');
        // ★ 位置按**节点真实的 step**（不是节点序号）：与进度条的
        //   `k / (steps.length - 1)` 同一把尺子，点节点跳转才落在它自己那一步。
        el.style.left = replayNodePercent(replayInt(node.step, 0), steps.length) + '%';
        el.dataset.step = String(replayInt(node.step, 0));
        el.dataset.nodeIndex = String(i);
        el.title = replayNodeTipText(node);
        el.setAttribute('aria-label', replayNodeTipText(node));
        replayTrackNodesEl.appendChild(el);
        replayState.nodeEls.push({ el: el, node: node });
    }
}

function updateReplayNodeTip(node, clientX, clientY) {
    if (!replayNodeTipEl) return;
    if (!node) {
        replayNodeTipEl.classList.add('hidden');
        replayNodeTipEl.textContent = '';
        return;
    }
    replayNodeTipEl.textContent = replayNodeTipText(node);
    replayNodeTipEl.classList.remove('hidden');
    var rect = replayNodeTipEl.getBoundingClientRect();
    var left = Math.min(Math.max(4, clientX + 10), Math.max(4, window.innerWidth - rect.width - 8));
    var top = clientY - rect.height - 10;
    if (top < 4) top = clientY + 18;
    replayNodeTipEl.style.left = Math.round(left) + 'px';
    replayNodeTipEl.style.top = Math.round(top) + 'px';
}

function hideReplayNodeTip() {
    if (!replayNodeTipEl) return;
    replayNodeTipEl.classList.add('hidden');
    replayNodeTipEl.textContent = '';
}

// 整体重画某一帧（契约 §7：上一步/下一步 = 改 k 后整体重画，≤2000 步直接重算）。
function renderReplayFrame() {
    if (!replayState.payload) return;
    replayState.frame = replayComputeFrame(replayState.payload, replayState.k);
    renderReplayBoards();
    renderReplayPlayers();
    renderReplayHands();
    renderReplayCurrentStep();
    renderReplayLogs();
    updateReplayChrome();
}

// ---------------------------------------------------------------------------
// 播放控制
// ---------------------------------------------------------------------------
function replayStepTo(k, opts) {
    var payload = replayState.payload;
    var steps = (payload && Array.isArray(payload.steps)) ? payload.steps : [];
    var max = Math.max(0, steps.length - 1);
    var next = replayInt(k, 0);
    if (next < 0) next = 0;
    if (next > max) next = max;          // 别让 k 越界
    replayState.k = next;
    renderReplayFrame();
    if (opts && opts.stopAtEnd && steps.length && next >= max) replayPause();
}

function replayStopTimer() {
    if (replayState.timer !== null) {
        clearTimeout(replayState.timer);
        replayState.timer = null;
    }
}

// ⚠️ 用 **setTimeout 链**驱动（不用 setInterval：它会累积漂移，暂停时也容易残留）。
function replayScheduleNext() {
    replayStopTimer();
    if (!replayState.playing) return;
    var delay = Math.max(1, Math.round(REPLAY_STEP_MS / replayState.speed));
    replayState.timer = setTimeout(function () {
        replayState.timer = null;
        if (!replayState.playing) return;
        var steps = (replayState.payload && Array.isArray(replayState.payload.steps))
            ? replayState.payload.steps : [];
        if (!steps.length || replayState.k >= steps.length - 1) {
            replayPause();               // 播完自动停（不循环，免得看不出"看完了"）
            return;
        }
        replayStepTo(replayState.k + 1, {});
        replayScheduleNext();
    }, delay);
}

function replayPlay() {
    var steps = (replayState.payload && Array.isArray(replayState.payload.steps))
        ? replayState.payload.steps : [];
    if (!steps.length) return;
    // 已经在末尾时按播放 = 从头再放一遍（否则点了没反应 —— 教训 #32）。
    if (replayState.k >= steps.length - 1) replayStepTo(0, {});
    replayState.playing = true;
    updateReplayChrome();
    replayScheduleNext();
}

function replayPause() {
    replayState.playing = false;
    replayStopTimer();                   // 暂停**立刻**清掉定时器
    updateReplayChrome();
}

function replayTogglePlay() {
    if (replayState.playing) replayPause();
    else replayPlay();
}

function replaySetSpeed(speed) {
    var found = false;
    for (var i = 0; i < REPLAY_SPEEDS.length; i++) if (REPLAY_SPEEDS[i] === speed) found = true;
    if (!found) return;
    replayState.speed = speed;
    if (replaySpeedGroup) {
        var btns = replaySpeedGroup.querySelectorAll('[data-replay-speed]');
        for (var j = 0; j < btns.length; j++) {
            btns[j].classList.toggle('active', replayInt(btns[j].dataset.replaySpeed, 0) === speed);
        }
    }
    if (replayState.playing) replayScheduleNext();   // 立刻按新节奏续上
}

// 拖拽/点击进度条 → 任意 seek（**拖拽时自动暂停**）。
function replaySeekFromPointer(clientX) {
    if (!replayTrackEl) return;
    var payload = replayState.payload;
    var steps = (payload && Array.isArray(payload.steps)) ? payload.steps : [];
    if (!steps.length) return;
    var rect = replayTrackEl.getBoundingClientRect();
    if (rect.width <= 0) return;
    var ratio = (clientX - rect.left) / rect.width;
    if (ratio < 0) ratio = 0;
    if (ratio > 1) ratio = 1;
    replayStepTo(Math.round(ratio * (steps.length - 1)), {});
}

// ---------------------------------------------------------------------------
// 进 / 出 / 清理
// ---------------------------------------------------------------------------
function resetReplayState() {
    replayStopTimer();
    /* 作废在飞的加载包：退出/换局时 ++，迟到的响应于是整包丢弃
       （否则退出之后回包还会写状态并启动按帧推进的计时器）。 */
    replayState.loadToken++;
    replayState.payload = null;
    replayState.youAre = null;
    replayState.k = 0;
    replayState.playing = false;
    replayState.speed = 1;
    replayState.scrubbing = false;
    replayState.frame = null;
    replayState.nodeEls = [];
    hideReplayNodeTip();
    if (replayTrackNodesEl) replayTrackNodesEl.innerHTML = '';
    if (replayTrackFillEl) replayTrackFillEl.style.width = '0%';
    if (replayTrackThumbEl) replayTrackThumbEl.style.left = '0%';
    if (replayLogsEl) replayLogsEl.textContent = '';
    if (replaySpeedGroup) {
        var btns = replaySpeedGroup.querySelectorAll('[data-replay-speed]');
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.toggle('active', replayInt(btns[i].dataset.replaySpeed, 0) === 1);
        }
    }
}

function replaySetStatus(text, isError) {
    if (!replayStatusEl) return;
    replayStatusEl.textContent = text;
    replayStatusEl.classList.toggle('replay-error', !!isError);
}

// 离开回放屏。⚠️ 必须进 switchScreen / 返回逻辑，别让玩家进去出不来。
function leaveReplayScreen() {
    resetReplayState();
    // ⚠️ 断开的是回放期间新开的那条 socket 连接（进回放前如果本来就有连接，
    //    原样留着）—— **绝不 emit 任何事件**。
    if (replayState.socket) {
        try { replayState.socket.disconnect(); } catch (e) { /* 忽略：断开失败不影响看回放 */ }
        replayState.socket = null;
    }
    switchScreen(startScreen);
}

// 打开回放屏：**只拉一次数据**，之后所有帧都从这份 JSON 本地解算。
function replayHandleLoadFailure(status) {
    // 每一种失败都要有**人话**提示，绝不静默什么都不发生（教训 #32）。
    // 401/403/404/409/500/503 逐条区分：404（这局没有回放）与 500（数据坏了）必须分开。
    var messages = {
        401: '请先登录后再查看对局回放。',
        403: '你没有权限查看这一局的回放。',
        404: '这局没有可回放的行动。',
        409: '这条回放的格式版本不支持，无法播放。',
        500: '这条回放已损坏或体积异常，无法播放。',
        503: '服务暂时无法读取回放，请稍后重试。'
    };
    replaySetStatus(messages[status] || '加载回放失败，请稍后重试。', true);
}

function openReplayForMatch(matchId, matchData, playerId) {
    if (!replayScreen) { showAlert('回放界面不存在，请刷新页面后重试。'); return; }
    if (!matchId) { showAlert('这一局没有可用的对局编号。'); return; }

    // ⚠️ 关掉**所有**浮层，不只是战绩详情：回放是整屏，`#user-stats-modal` 与
    //    `#match-detail-modal` 都还在文档里挂着（回放屏在它们**后面**），
    //    不清掉就会出现"进了回放屏却还看着战绩弹窗"。
    //    本批实测截图就是这么发现的（截图里是战绩弹窗，不是回放屏）。
    //    `closeOverlaysExcept` 是按类名取全量 `.modal-overlay`，不用手抄 id 清单
    //    （手抄必漏 —— tests/test_screen_overlay_registry.py 就是为这个形状写的）。
    if (typeof closeOverlaysExcept === 'function') closeOverlaysExcept(null);

    replayState.entryMatches[String(matchId)] = { matchData: matchData, playerId: playerId };

    switchScreen(replayScreen);        // 进门第一件事：切屏（`hideAllScreens` 会摘掉别的 active）
    replaySetStatus('正在加载回放…', false);
    if (replayPlayersTitleEl) replayPlayersTitleEl.textContent = '加载中…';
    // 回放期间不要把这条连接悬着：可能弹连接提示挡视线。
    // ⚠️ 这条**不是**回放通道，也不发任何事件 —— 回放只走 HTTP。
    // 回放期间不要把这条连接悬着：可能弹连接提示挡视线。
    // ⚠️ 这条**不是**回放通道，也不发任何事件 —— 回放只走 HTTP。
    replayState.socket = (typeof socket !== 'undefined' && socket) ? socket : null;
    if (replayState.socket && replayState.socket.connected === false) replayState.socket = null;

    bindReplayKeys();

    // 这一趟加载的身份。**先取号再发请求**，回包时用它判断"我还是不是当前那一次"。
    var loadToken = ++replayState.loadToken;
    /* "这一包还算数吗"只有一个判据：身份没被作废 **且** 回放屏还开着。
       第二条不能省：退出回放只是把屏切走，不会自动让 fetch 停 —— 只靠 token
       的话"退出后再打开同一局"会因为 token 相同而把旧包当新包用。 */
    function replayLoadStillCurrent() {
        return loadToken === replayState.loadToken && replayIsActive();
    }

    fetch('/api/replay/' + encodeURIComponent(String(matchId)), {
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json' }
    }).then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, status: resp.status, data: data }; },
            function () { return { ok: false, status: resp.status, data: null }; });
    }).then(function (out) {
        if (!replayLoadStillCurrent()) return;      // 过期包 / 已经退出：不写 UI、不启动计时器
        var data = out.data || {};
        if (!out.ok || data.success !== true || !data.replay) {
            replayHandleLoadFailure(out.status);
            return;
        }
        replayState.payload = data.replay;
        replayState.youAre = (data.you_are === 'p1' || data.you_are === 'p2') ? data.you_are : null;
        replayState.k = 0;
        replayState.speed = 1;
        var trunc = data.replay.truncated ? String(data.replay.truncated) : '';
        replaySetStatus(trunc ? ('回放已加载（' + trunc + '）') : '回放已加载，可以拖动进度条或点下一步。', !!trunc);
        buildReplayTrackNodes();
        renderReplayFrame();
    }).catch(function () {
        if (!replayLoadStillCurrent()) return;
        replaySetStatus('加载回放失败（网络问题），请稍后重试。', true);
    });
}

function bindReplayKeys() {
    if (replayState.keyBound) return;
    replayState.keyBound = true;
    document.addEventListener('keydown', function (e) {
        if (!replayIsActive()) return;
        var tag = (e.target && e.target.tagName) ? String(e.target.tagName).toLowerCase() : '';
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
        if (e.key === 'ArrowRight') { e.preventDefault(); replayStepTo(replayState.k + 1, {}); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); replayStepTo(replayState.k - 1, {}); }
        else if (e.key === ' ' || e.key === 'Spacebar') { e.preventDefault(); replayTogglePlay(); }
        else if (e.key === 'Escape') { e.preventDefault(); leaveReplayScreen(); }
    });
}

// 控件绑定：**各绑一次**（回放屏的 DOM 不会被整段重建，所以不需要委托）。
function bindReplayControls() {
    if (replayPrevBtn) {
        replayPrevBtn.addEventListener('click', function () {
            replayPause();
            replayStepTo(replayState.k - 1, {});
        });
    }
    if (replayNextBtn) {
        replayNextBtn.addEventListener('click', function () {
            replayPause();
            replayStepTo(replayState.k + 1, {});
        });
    }
    if (replayPlayBtn) replayPlayBtn.addEventListener('click', replayTogglePlay);
    if (replayLeaveBtn) replayLeaveBtn.addEventListener('click', leaveReplayScreen);

    if (replaySpeedGroup) {
        // 委托一次（按钮组不会被重建；委托也免得以后加了档位就漏绑）
        replaySpeedGroup.addEventListener('click', function (e) {
            var btn = (e.target && e.target.closest) ? e.target.closest('[data-replay-speed]') : null;
            if (!btn) return;
            replaySetSpeed(replayInt(btn.dataset.replaySpeed, 1));
        });
    }

    if (replayTrackEl) {
        // 点节点 = 跳那一步（**在 track 自己的委托里先判节点**，再当 seek 处理）
        replayTrackEl.addEventListener('click', function (e) {
            var node = (e.target && e.target.closest) ? e.target.closest('.replay-track-node') : null;
            if (node) {
                replayPause();
                replayStepTo(replayInt(node.dataset.step, 0), {});
                return;
            }
            replaySeekFromPointer(e.clientX);
        });
        // 悬停节点出 tooltip（那是"这一步做了什么"的预览）
        replayTrackEl.addEventListener('mouseover', function (e) {
            var node = (e.target && e.target.closest) ? e.target.closest('.replay-track-node') : null;
            if (!node) { hideReplayNodeTip(); return; }
            var idx = replayInt(node.dataset.nodeIndex, -1);
            var nodes = (replayState.payload && Array.isArray(replayState.payload.nodes))
                ? replayState.payload.nodes : [];
            updateReplayNodeTip(nodes[idx], e.clientX, e.clientY);
        });
        replayTrackEl.addEventListener('mousemove', function (e) {
            var node = (e.target && e.target.closest) ? e.target.closest('.replay-track-node') : null;
            if (!node) { hideReplayNodeTip(); return; }
            var idx = replayInt(node.dataset.nodeIndex, -1);
            var nodes = (replayState.payload && Array.isArray(replayState.payload.nodes))
                ? replayState.payload.nodes : [];
            updateReplayNodeTip(nodes[idx], e.clientX, e.clientY);
        });
        replayTrackEl.addEventListener('mouseleave', hideReplayNodeTip);
        // 拖拽 track 任意 seek —— 拖拽时自动暂停
        replayTrackEl.addEventListener('pointerdown', function (e) {
            replayPause();
            replayState.scrubbing = true;
            try { replayTrackEl.setPointerCapture(e.pointerId); } catch (err) { /* 老浏览器没有就算了 */ }
            replaySeekFromPointer(e.clientX);
        });
        replayTrackEl.addEventListener('pointermove', function (e) {
            if (!replayState.scrubbing) return;
            replaySeekFromPointer(e.clientX);
        });
        var endScrub = function (e) {
            if (!replayState.scrubbing) return;
            replayState.scrubbing = false;
            try { replayTrackEl.releasePointerCapture(e.pointerId); } catch (err) { /* 同上 */ }
        };
        replayTrackEl.addEventListener('pointerup', endScrub);
        replayTrackEl.addEventListener('pointercancel', endScrub);
        // 键盘：进度条可聚焦，左右箭头一步步走
        replayTrackEl.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                e.stopPropagation();
                replayPause();
                replayStepTo(replayState.k + (e.key === 'ArrowRight' ? 1 : -1), {});
            }
        });
    }
}

// ---------------------------------------------------------------------------
// 设置面里的「允许保留我的对局回放」（契约 §5）
// ---------------------------------------------------------------------------
function setReplaySettingMsg(text, isError) {
    if (!replaySettingMsg) return;
    replaySettingMsg.textContent = text;
    replaySettingMsg.classList.toggle('settings-error', !!isError);
}

// 拉服务端的真实开关值。**不做任何前端默认值兜底** ——
// "服务端关着、前端显示开着"正是要避免的那种假象（教训 #21 同族）。
function loadReplaySetting() {
    if (!allowReplayCheckbox) return;
    fetch('/api/replay/setting', { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
            if (!data || data.success !== true) {
                allowReplayCheckbox.disabled = true;
                setReplaySettingMsg('登录后才能设置回放权限。', false);
                return;
            }
            allowReplayCheckbox.disabled = false;
            allowReplayCheckbox.checked = data.allow_replay === true;
            setReplaySettingMsg(data.allow_replay === true
                ? '打开中：你打完的对局会留下可回看的记录。'
                : '关闭中：你打完的对局不会留下回放。', false);
        })
        .catch(function () {
            allowReplayCheckbox.disabled = true;
            setReplaySettingMsg('读取回放设置失败（网络），暂时不能修改。', true);
        });
}

function saveReplaySetting(on) {
    if (!allowReplayCheckbox) return;
    fetch('/api/replay/setting', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ allow_replay: on === true })
    }).then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
    }).then(function (out) {
        var data = out.data || {};
        if (!out.ok || data.success !== true) {
            // 保存失败必须回滚 UI 并说明 —— 否则玩家以为改好了（静默失败）
            allowReplayCheckbox.checked = !(on === true);
            setReplaySettingMsg(data.error || '保存失败，请稍后再试。', true);
            return;
        }
        allowReplayCheckbox.checked = data.allow_replay === true;
        setReplaySettingMsg(data.allow_replay === true
            ? '已保存：你打完的对局会留下回放。'
            : '已保存：你打完的对局不会留下回放。', false);
    }).catch(function () {
        allowReplayCheckbox.checked = !(on === true);
        setReplaySettingMsg('保存失败（网络），请稍后再试。', true);
    });
}

// 对局详情页里的「对局回放」入口与设置开关，**各绑一次**。
// ⚠️ 详情内容是每次点开时整段重建的（innerHTML 换掉），所以监听必须
//    **委托**在不被重建的容器 `#match-detail-modal` 上 —— 绑在 `#match-detail-content`
//    上会被换掉，逐行绑按钮更是必漏（大厅/排行榜都踩过这个坑）。
function bindReplayEntryPoints() {
    if (typeof matchDetailModal !== 'undefined' && matchDetailModal
        && matchDetailModal.dataset.replayEntryBound !== '1') {
        matchDetailModal.dataset.replayEntryBound = '1';
        matchDetailModal.addEventListener('click', function (e) {
            var btn = (e.target && e.target.closest) ? e.target.closest('.match-replay-btn') : null;
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            if (btn.disabled === true) return;      // 置灰的按钮点了什么也不做（原因写在旁边）
            var matchId = btn.dataset.matchId || '';
            var entry = replayState.entryMatches[matchId] || {};
            openReplayForMatch(matchId, entry.matchData || null, entry.playerId || null);
        });
    }
    if (allowReplayCheckbox && allowReplayCheckbox.dataset.replaySettingBound !== '1') {
        allowReplayCheckbox.dataset.replaySettingBound = '1';
        allowReplayCheckbox.addEventListener('change', function () {
            saveReplaySetting(allowReplayCheckbox.checked === true);
        });
    }
}
