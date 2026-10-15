/*
 * 魔法卡客户端规则与目标描述。
 *
 * 这个文件只保存卡牌使用门禁和目标选择的声明式镜像；实际 UI 组件仍在
 * game.js 中，Socket 事件仍由 client_socket_events.js 负责。使用经典脚本
 * 作用域以保持旧页面和旧测试入口兼容，后续可以再收窄为显式模块接口。
 */

// 结束阶段默认禁止使用魔法卡，但以下卡设计上就在结束阶段发动。
// （服务端 server.py 的 END_PHASE_PLAYABLE 有一份对应名单，改动需同步。）
const END_PHASE_PLAYABLE_CARDS = ['Freezing！'];

// 是否为「先手」（猜拳胜者）。判定条件与后端 freezing_block_reason 保持一致，
// 否则会出现「前端点得下去、后端拒绝」的割裂体验。
function isFirstPlayer() {
    const order = gameState.attackOrder || [];
    return order.length > 0 && order[0] === gameState.playerId;
}

// 绝处逢生是否正在生效：生效回合内自己的其余魔法卡全部无效
// （服务端 can_play_magic_card 第一条就拦这个，前端要给出同样的理由）。
//
// ⚠️ 绝处逢生在服务端是【两个】标记，生命周期不同：
//   · last_stand     → 锁卡，只持续发动回合
//   · last_stand_win → 击杀即胜，活到对局结束
// 两个标记的角标显示名都含"绝处逢生"，**所以绝不能靠卡名匹配**：
// 拿名字判断的话，"击杀即胜"会一直亮着，前端就以为魔法卡还被锁着 ——
// 玩家点卡被本地拒掉、弹"绝处逢生生效中"，而服务端其实放行了。
// 这里一律认标记名（服务端 room_sync 下发的布尔字段 / 角标对象的 key）。
//
// 认三种下发口径（老客户端 / 老快照升级瞬间也要能用）：
//   · room_sync（重连快照）        → last_stand_lock 布尔字段
//   · room_sync 的 effect_badges   → 角标对象的 key
//   · active_effects 事件          → 中文标签，退化为"绝处逢生·封锁魔法卡"
// 只读游戏状态、不改它，纯判定。
function _effectMarkerSet() {
    const out = new Set();
    const push = (v) => {
        if (v === null || v === undefined) return;
        if (typeof v === 'string') { if (v) out.add(v); return; }
        if (typeof v === 'object') {
            if (v.key) out.add(String(v.key));
            if (v.name) out.add(String(v.name));
        }
    };
    (Array.isArray(gameState.activeEffects) ? gameState.activeEffects : []).forEach(push);
    (Array.isArray(gameState.activeEffectsSelf) ? gameState.activeEffectsSelf : []).forEach(push);
    return out;
}

function isLastStandActive() {
    if (gameState.lastStandLock === true) return true;
    const markers = _effectMarkerSet();
    // 标记名精确匹配。老口径 'last_stand' 认；新的 'last_stand_win' **不认**。
    if (markers.has('last_stand') || markers.has('绝处逢生·封锁魔法卡')) return true;
    // 兜底：只有在"新口径标记一个都没出现"时才按旧卡名判断，
    // 免得升级瞬间（还没收到 room_sync 的新字段）把门禁整个放开。
    if (!markers.has('last_stand_win') && !markers.has('绝处逢生·击杀即胜')) {
        return markers.has('绝处逢生');
    }
    return false;
}

// 修改canPlayCard函数
function canPlayCard(card) {
    // 绝处逢生生效中：自己的其余魔法卡一律不能使用。
    // 这条必须排在速阶判定之前 —— 否则速阶1/2会被下面的阶段判断拒掉，
    // 玩家看到的是「当前阶段不允许使用速阶1」这种与真实原因无关的提示。
    if (isLastStandActive()) {
        return false;
    }
    // 特例：Freezing！ 只能在自己先手回合的结束阶段发动
    if (END_PHASE_PLAYABLE_CARDS.indexOf(card.name) >= 0) {
        return isFirstPlayer() &&
            gameState.currentPhase === 'end' &&
            gameState.currentAttacker === gameState.playerId;
    }
    // ⚠️ 速阶一律先转成数字再比较。
    // 此前写的是 card.speed === 1 / === 2 / === 3（严格相等）：
    // 只要 card.speed 是字符串 "2"（或 undefined），三个分支全部落空，
    // 函数直接掉到最后的 return false —— 于是【本来能用的卡被前端拦下】，
    // 并弹出「当前阶段preparation不允许使用速阶2」这种冤枉阶段的提示。
    // 服务端 can_play_magic_card 用的是 int(card.speed)，两边口径必须一致。
    // 实测复现：tools/diag_bomb_alert.mjs 里 speed 传 "2" 时
    // 准备阶段 + 自己回合的「轰炸」被判为不可用。
    const speed = Number(card.speed);
    // 速阶1: 只能在自己的准备阶段使用
    if (speed === 1) {
        return gameState.currentPhase === 'preparation' && gameState.currentAttacker === gameState.playerId;
    }
    // 速阶2: 可以在自己的准备阶段和战斗阶段使用
    else if (speed === 2) {
        return (gameState.currentPhase === 'preparation' || gameState.currentPhase === 'battle') &&
            gameState.currentAttacker === gameState.playerId;
    }
    // 速阶3: 任何时候都可以使用
    else if (speed === 3) {
        return true;
    }
    // 速阶读不出来（数据缺失）不能当作"不允许"：放行给服务端裁定，
    // 服务端有权威校验；这里静默拦下只会让玩家看到一条与事实不符的提示。
    return true;
}

// 依赖「自己上一发攻击」的卡是否能发动。返回 null 表示可以；否则返回原因文案。
// 与服务端 _last_attack_requirement_reason 保持同一口径：
//   · 饮血     —— 须【击沉】（卡面：可在击沉对方一艘战舰后选择使用）
//   · 溅射     —— 须【击中】
//   · 雷达子弹 —— 须【击中】
// ⚠️ 饮血此前漏在这里：它只在服务端结算时才判，而那时牌已经离手，失败也不退还。
function afterHitBlockReason(card) {
    if (!card) return null;
    const needsLastAttack = card.name === '饮血' || card.name === '溅射' || card.name === '雷达子弹';
    if (!needsLastAttack) return null;

    const last = gameState.lastAttack;
    if (!last || last.attacker !== gameState.playerId) {
        return '你这一局还没有攻击过';
    }
    if (card.name === '饮血') {
        if (!last.shipSunk) return '需要你先击沉对方一艘战舰';
        return null;
    }
    if (!last.hit) return '需要你上一发攻击命中对方';
    return null;
}

// 限制需命中后才能发动的卡（保留旧签名供既有调用点使用）
function canPlayAfterHit(card) {
    return afterHitBlockReason(card) === null;
}


// ===========================================================================
// 区域卡目标选择的**声明式真源**（前端侧）
// ---------------------------------------------------------------------------
// ★ 2026-09-27 区域预览批：原来这张表写在 `needsTargetSelection` 的**函数体内**
//   （`const map = {...}`），于是"服务端要镜像它"就只能靠正则去啃函数体
//   （脆弱且容易假绿），而且"卡名 → 作用棋盘"这个判据在前端没有任何可被
//   引用的名字。现在提到模块级：
//
//   · `MAGIC_TARGET_DESCRIPTORS` —— 卡名 → 选择器描述（形状 + 棋盘归属）；
//   · `server.spectate.AREA_TARGET_BOARDS` —— 卡名 → 棋盘归属的**服务端权威表**
//     （`self` / `opponent` / `choice`）。**两张表必须逐卡一致**，
//     由 `tests/test_area_preview.py::test_frontend_mirror_matches_server` 钉死
//     （先例 `tests/test_ship_pick_mirror.py`）。
//
// ⚠️ 同步要求（CLAUDE.md 教训 #1：同一判断两份实现必然漂移）：
//   新增一张"要玩家点选区域/行列/连续格/单格"的卡时，**两边都要登记**，
//   漏一边那条同步用例就会红。这里只有"选什么形状/打在哪块棋盘"，
//   真正的放行/拒绝一律由服务端裁决（`_sanitize_magic_targets` 校验 board）。
//
//   形状（type）：area（方阵，size×size）/ line（整行整列）/ continuous（连续 length 格）
//                / single（单格）/ shenwei（先选棋盘再点 3×3）/ own_ships（多选自己的船）
//   归属（board）：'self' = 作用在自己棋盘；'opponent' = 对方棋盘；
//                 **缺省 = 玩家当场二选一**（只有「神威！」如此，服务端记作 'choice'）
const MAGIC_TARGET_DESCRIPTORS = {
    '冻结': { type: 'area', size: 3, board: 'opponent' },          // 3x3区域
    '探测雷达': { type: 'area', size: 2, board: 'opponent' },      // 2x2区域
    '轰炸': { type: 'line', board: 'opponent' },                  // 行或列
    '硫磺火焰': { type: 'continuous', length: 6, board: 'opponent' }, // 6个连续格子
    '克苏鲁之眼': { type: 'single', board: 'self' },             // 选择自己的船暴露
    '神之宣告': { type: 'own_ships', count: 2 },                  // 选择两艘自己的船牺牲
    '神威！': { type: 'shenwei' }                                 // 己方/对方 3x3 扣区
};

// 添加魔法卡目标选择判断函数（返回目标选择描述）
function needsTargetSelection(cardName) {
    return MAGIC_TARGET_DESCRIPTORS[cardName] || null;
}
