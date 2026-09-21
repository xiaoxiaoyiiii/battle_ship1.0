# -*- coding: utf-8 -*-
"""无头对局驱动器：不用 socket、不进请求上下文、不 sleep，直接跑完整局。

【为什么需要它】
`server.py` 的 AI 回合由 `_ai_turn_loop` 驱动，而它每发炮弹 `time.sleep(0.3)`、
每次交回合还要重试等待，一局实测 30 秒以上；整条链路又必须走 socket.io
（Flask 请求上下文 + eventlet hub）。于是「测 1000 局的胜率」这件事根本做不了。

本模块把这两笔开销都去掉，做法是**直调模块级 handler**：
`handle_place_ships` / `handle_rps_choice` / `enter_battle_phase` / `handle_attack` /
`handle_enter_end_phase` / `end_turn` / `handle_use_magic_card` / `chain_response`，
载荷就是普通 dict（与前端 emit 的形状一致）。

【为什么直调能过身份校验】（已实测，不是推断）
`_identity_ok` 在**取不到请求上下文**时只做成员校验：
    server_pid = session.get(...)  → RuntimeError → None
    sid        = request.sid       → RuntimeError → None
    if server_pid is None and sid is None: return room is not None and pid in room.players
这正是给单测留的口子（CLAUDE.md 第 6 节）。`_has_request_context()` 同时为 False，
所以阶段转换的「优先权询问」（本来要等对方 10 秒）也自动跳过。

【为什么 AI 不会跟驱动器抢方向盘】
`_maybe_run_ai_turn` 有 4 个调用点（`handle_place_ships` 的灵气复苏分支、
`handle_rps_choice` 猜拳结束、`end_turn` 换回合、`switch_turn_after_end_phase`），
它们会 `socketio.start_background_task(_ai_turn_loop, room_id)`。
如果不处理，驱动器和 `_ai_turn_loop` 会**同时**操同一个房间：两边都调
`enter_battle_phase` / `handle_attack`，谁的调用先到谁生效、另一边的调用被
「当前不是战斗阶段」「本回合攻击次数已用尽」拒掉 —— 表现为对局随机性地半途停住。

本模块用 `_server_patches()` 在**自己的运行期间**把这几处换掉，跑完立刻还原：
  · `server._maybe_run_ai_turn` → 空操作（不再排 `_ai_turn_loop`）
  · `server.socketio.start_background_task` → 空操作（连锁超时 / 优先权超时 /
    掉线宽限 / 房间回收 这些定时器在无头环境里没有意义，且都会 sleep）
  · `server.emit` → 只往列表里记事件（不做 JSON 序列化、不碰 socket）
  · `db.record_card_use` 等三个统计写入 → 空操作（见 `_server_patches` 的
    `isolate_db`：一次 sqlite commit 占实测墙钟的 58%）
全程**不修改 server.py**，也不改它的模块级常量。还原用 try/finally，
在别的测试（尤其是 monkeypatch fixture）里调用本模块也不会泄漏补丁。

【连锁窗口 / 待办窗口谁来推】
`handle_use_magic_card` 压栈后调 `_advance_chain_window(room, 对手)`：
对手能响应就把 `chain_waiting=True` 挂住，等一个**真人**来点响应。
无头环境里没有真人，`_schedule_chain_timeout` 也被上面补丁封掉了，
所以驱动器必须自己泵：`_pump_chain()` 反复替窗口玩家调 `chain_response`（打牌或放弃），
直到 `room.chain` 空且 `chain_waiting` 为 False。
不泵的话，`handle_attack` / `end_turn` / `handle_use_magic_card` 会一律以
「连锁结算中」拒绝 → 回合推进不动 → 整局卡死（这正是本模块最重要的一个发现）。

同形状的还有三个**会冻结写操作**的待办窗口，由 `_pump_pending()` 应答：
神机妙算宣言（`handle_confirm_shenji_declare`）、放置落点
（`handle_confirm_reinforcement` / `handle_cancel_placement`）、
命运骰子弃牌（`handle_dice_discard_choose`）。

【实测踩到并已修的驱动器缺陷（都是"看着跑通了、其实静默跑歪"）】
  1. 出牌机会没被消耗：策略返回 None 时 `_play_card` 提前 return，战斗循环每圈
     重新问一次 → 200 圈原地打转（hard 手上只剩白名单外的卡时必现）。
  2. 只摆一次船：败者食尘 / 灵气复苏 / 回光返照 会把局面打回 `placing_ships`。
  3. `_turn` 只在进入时看一眼 state：这三张牌是在**回合中途**改 state 的，
     于是驱动器会对着"正在等布船"的房间继续开回合（双方 0 艘船跑满 200 回合）。
  4. "次数还有、却没有任何合法格可打"（36 格全打过）时必须直接请求结束阶段 ——
     这正是服务端自己那套思考超时兜底的判据。
"""
import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import random
import sys
import time

# 允许 `python tools/headless_game.py` 直接跑（脚本目录不是项目根）。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import server  # noqa: E402  （必须在 sys.path 处理之后）

from server import field_magic_name  # noqa: E402

CELLS = tuple((x, y) for x in range(6) for y in range(6))

# 「要施法者自己点选/摆放，无头环境里没人应答」的卡。CLAUDE.md 第 9 节的人机
# 出牌白名单 `_AI_SAFE_CARDS` 就是这份名单的来源（桃园结义 / 明智埋葬 / 神机妙算 /
# 仁王之盾 / 灵气复苏 / 增援 / 死者苏生 / 绝处逢生）。随机策略跳过它们，
# 否则打出去就会把整局卡在那一个回合 —— 那是"玩家还没选"，不是服务端缺陷。
_INTERACTIVE_CARDS = frozenset((
    '桃园结义', '明智埋葬', '神机妙算', '仁王之盾', '灵气复苏', '增援',
    '死者苏生', '绝处逢生',
))


# ===========================================================================
# 结果对象
# ===========================================================================
class GameResult:
    """一局的可复现记录。

    `actions` 是动作序列（`(类型, 玩家, 参数)` 三元组），
    `action_hash()` 是它的短哈希 —— 用来钉「同种子 → 同一个动作序列」。
    """

    __slots__ = ('seed', 'winner', 'loser', 'rounds', 'stalled', 'stall_reason',
                 'actions', 'violations', 'duration', 'p1', 'p2', 'room_id',
                 'final_state', 'sunk', 'kills', 'attacks_fired', 'hit_shots',
                 'miss_shots', 'shielded_shots', 'rejected_shots')

    def __init__(self, seed=None, p1=None, p2=None, room_id=None):
        self.seed = seed
        self.p1 = p1
        self.p2 = p2
        self.room_id = room_id
        self.winner = None
        self.loser = None
        self.rounds = 0
        self.stalled = False
        self.stall_reason = ''
        self.actions = []
        self.violations = []
        self.duration = 0.0
        # ── 「打疼了没有」这四个量（2026-09-22 加）─────────────────────────
        #
        # 为什么必须单独有它们：此前的度量只有胜率。而作者实报的
        # 「我甚至可以无伤赢他」在胜率里**完全看不见** —— 68.8% 既可以是
        # "互有攻防的险胜"，也可以是"对手从头到尾没打中过我"。没有这两个数，
        # 改完无法判断侵略性是涨了还是跌了（只能读噪声）。
        #
        # `sunk[座位]`  = 该座位**击沉了对方几艘**（= 对方的 max_ships − remaining_ships）
        # `hit_shots`   = 该座位的炮击里真的打中船的（含被盾/无敌吸收的）
        #
        # ⚠️ 全部是**终局快照 + 既有动作记录**推出来的，不新增任何随机源，
        #    也不改对局行为 —— 同种子两次跑的文字输出必须逐字节一致。
        self.sunk = {}
        self.kills = {}
        self.attacks_fired = {}
        self.hit_shots = {}
        self.miss_shots = {}
        self.shielded_shots = {}
        self.rejected_shots = {}
        # 收尾时的可观察房间状态（就是"卡在哪"的证据）。房间对象本身在
        # `__exit__` 里就被删掉了，所以必须在这里留一份**纯数据**快照。
        self.final_state = {}

    def action_hash(self, normalize=True) -> str:
        """动作序列的短哈希（默认把座位 id 归一成 p1/p2）。

        ⚠️ 必须归一：房间 id 是 `uuid4`（`create_ai_room` 里定的），而 AI 座位 id
        就是 `'ai-'+room_id`。直接哈希原始 id 的话，同种子两次跑永远得到不同的
        哈希 —— 判据看着很严，其实只证明了"uuid 每次都不一样"。
        归一之后它才真正等价于"同一个决策序列"。
        """
        actions = self.actions
        if normalize:
            mapping = {self.p1: 'p1', self.p2: 'p2'}
            actions = [(kind, mapping.get(pid, pid), detail)
                       for kind, pid, detail in self.actions]
        blob = json.dumps(actions, ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]

    def __repr__(self):
        return (f'<GameResult seed={self.seed} winner={self.winner!r} '
                f'rounds={self.rounds} actions={len(self.actions)} '
                f'stalled={self.stalled} hash={self.action_hash()}>')


# ===========================================================================
# 策略接口
# ===========================================================================
class Policy:
    """决策接口：驱动器每需要一次决定就调这里，返回值由策略给。

    约定（都允许返回 None = 「这一步我不做」）：
      · place_ships      → [{'positions': [{'x','y'}], 'hits': []}, …]（必须 max_ships 艘）
      · rps_choice       → 'rock' / 'paper' / 'scissors'
      · choose_attack    → (x, y)；None = 不再攻击，直接进结束阶段
      · choose_card      → 手牌下标；None = 本回合不出牌（每回合最多一张，与真 AI 一致）
      · choose_card_targets → 交给 `handle_use_magic_card` 的 targets；None = 这张卡不打
      · choose_chain_response → {'chain': bool, 'card': {...}|None, 'targets': ...}
      · choose_shenji_prediction → 0~6（神机妙算宣言值）
      · choose_dice_discard      → 手牌下标（命运骰子的弃牌待办）

    策略对象**不该**自己改 room 状态：只做选择，动手的是 server 的 handler。
    """

    name = 'base'
    # 本回合已出牌数：驱动器每回合调 `begin_turn` 置 0，用 `note_card_played` 累加。
    # 放在基类，任何策略（含 RandomPolicy）都自动具备，不用各自再记一份。
    cards_played = 0

    def begin_turn(self, room, pid):
        """每回合开始：清掉本回合的出牌计数（驱动器调用）。"""
        self.cards_played = 0

    def note_card_played(self):
        """驱动器确认「这次出牌机会真的用掉了」后累加。"""
        self.cards_played += 1

    def place_ships(self, room, pid):
        raise NotImplementedError

    def rps_choice(self, room, pid):
        return random.choice(('rock', 'paper', 'scissors'))

    def choose_attack(self, room, pid):
        return None

    def choose_card(self, room, pid):
        return None

    def cards_per_turn(self, room, pid):
        """本回合允许出几张牌。默认 1 —— 与 easy/normal/hard 的线上行为一致。

        ⚠️ 大师在线上是**每回合多张**（`ai_brain.CARDS_PER_TURN`），
           `ExistingAIPolicy` 会覆盖本方法。这里给默认值，是为了让驱动器
           对任何策略都能算预算，而不是把"1 张"写死在循环里。
        """
        return 1

    def choose_card_targets(self, room, pid, card):
        return {}

    def choose_chain_response(self, room, pid, window):
        return {'chain': False}

    def choose_shenji_prediction(self, room, pid):
        return 1

    def choose_dice_discard(self, room, pid):
        return 0

    def choose_placement(self, room, pid, pending):
        """放置流程（增援 / 死者苏生 / 神机妙算重部署 / 绝处逢生）的落点。

        返回 `(x, y)`；返回 None = 放弃（走 `cancel_placement`，已放置的保留）。
        """
        blocked = {(c['x'], c['y']) for c in server._placement_blocked_cells(room, pid)}
        allowed = pending.get('allowed')
        if allowed:
            blocked -= {(int(a[0]), int(a[1])) for a in allowed}
            legal = [(int(a[0]), int(a[1])) for a in allowed
                     if (int(a[0]), int(a[1])) not in blocked]
        else:
            legal = [c for c in CELLS if c not in blocked]
        if not legal:
            return None
        return random.choice(legal)


class RandomPolicy(Policy):
    """随机策略：给 fuzzing 用（炮击合法格 / 随机出拳 / 随机尝试出牌）。

    `rng` 由驱动器每局注入（`policy.bind(rng)`），所以同一个 seed 必定产生同一局。
    """

    name = 'random'

    def __init__(self, play_cards=False):
        self.rng = random.Random()
        # 默认不出牌：出牌会把「目标选择」这条又长又容易写错的路拉进来。
        # 做卡牌 fuzz 时打开（`RandomPolicy(play_cards=True)`），
        # 配合 `choose_card_targets` 的通用目标猜测。
        self.play_cards = play_cards

    def bind(self, rng):
        self.rng = rng

    def place_ships(self, room, pid):
        cells = self.rng.sample(CELLS, 6)
        return [{'positions': [{'x': x, 'y': y}], 'hits': []} for x, y in cells]

    def choose_attack(self, room, pid):
        attacked = {(a.x, a.y) for a in room.players[pid].attacks}
        candidates = [c for c in CELLS if c not in attacked]
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def choose_card(self, room, pid):
        """只从**当前合法**的卡里挑（`can_play_magic_card`）。

        不筛的话随机策略会一直撞「当前阶段/不是你的回合/禁忌果实」这些门禁，
        一局被拒上千次，fuzz 出来的全是拒绝分支、几乎打不出有内容的对局。
        再叠加 `_ship_pick_blocked_reason`：有更高优先级的选船待选时出选船卡
        会被拒，而且**待选状态会一直挂着**，那才是真正的卡死来源。
        """
        if not self.play_cards:
            return None
        hand = room.players[pid].magic_hand
        legal = []
        for idx, card in enumerate(hand):
            if card.name in _INTERACTIVE_CARDS:
                continue          # 要玩家自己点选/摆放，无头环境里没人应答
            if not server.can_play_magic_card(room, pid, card):
                continue
            if server._ship_pick_blocked_reason(room, pid, card.name):
                continue
            legal.append(idx)
        if not legal:
            return None
        return self.rng.choice(legal)

    def choose_card_targets(self, room, pid, card):
        """通用目标猜测：按卡牌大类给一份「形状对得上」的 targets。

        形状取自 CLAUDE.md 第 7 节（`target_area {x1,y1,x2,y2}` /
        `target_line {type,index}`）。猜错不算失败 —— handler 会以
        「不满足发动条件」拒绝并把牌退回手牌（`_refund_card_to_hand`），
        驱动器照常继续，这也是我们要 fuzz 的分支之一。
        """
        name = card.name
        if name in ('神威！', '冻结', '探测雷达'):
            x1 = self.rng.randrange(0, 4)
            y1 = self.rng.randrange(0, 4)
            return {'target_area': {'x1': x1, 'y1': y1, 'x2': 5, 'y2': 5}}
        if name == '轰炸':
            return {'target_line': {'type': self.rng.choice(('row', 'col')),
                                    'index': self.rng.randrange(6)}}
        # 其余一律空目标：无目标卡直接生效，需要点选的卡会被拒绝并退牌。
        return {}


class ExistingAIPolicy(Policy):
    """**真实**现有 AI 的策略适配器 —— 让「hard 胜率」量的是今天的 hard，不是复刻品。

    每个决策都直接调 `server.py` 里那份实现，一行逻辑都不重写：
      · 摆船   → `server._ai_place_ships`（真实现是直接改 player.ships，这里读回来）
      · 出拳   → `random.choice`（同 `handle_rps_choice` 里给 AI 自动出拳那一行）
      · 炮击   → 同 `_ai_turn_loop`：排除自己打过的格，`random.choice`
      · 出牌   → `server._ai_choose_magic_card`（含 `_AI_SAFE_CARDS` 白名单与速阶排序）
      · 连锁   → 同 `_ai_chain_respond`：hard 且能康时才用「失灵！」，否则放弃

    难度只影响「AI 自己的策略选择」，房间的 `ai_difficulty` 由驱动器按同一个值设好
    （`server._can_respond_chain` 会用房间字段判断 AI 能不能参与连锁）。
    """

    def __init__(self, difficulty='hard'):
        if difficulty not in server.AI_DIFFICULTIES:
            raise ValueError(f'未知难度 {difficulty!r}，可选 {server.AI_DIFFICULTIES}')
        self.difficulty = difficulty
        self.name = difficulty
        # 本回合已出牌数。由驱动器在每回合开始时置 0（`begin_turn`），出牌后累加。
        # ⚠️ 必须是**策略自己的**字段：驱动器不替策略记这个数，否则"策略有两个
        #    调用方"（真回合循环 + 驱动器）就会有两份计数，长成第二份真相。
        self.cards_played = 0
        self._pending_targets = {}

    def place_ships(self, room, pid):
        server._ai_place_ships(room, pid)
        player = room.players[pid]
        return [{'positions': [{'x': p.x, 'y': p.y} for p in ship.positions],
                 'hits': []} for ship in player.ships]

    def choose_attack(self, room, pid):
        """这一炮打哪格 —— **委托 server 的唯一实现**，不再自己抄一遍。

        ⚠️ 这里原本自己写了一份 `random.choice(candidates)`。后果是：模拟器量的是
           **复刻品**而不是真的 AI —— 改了 `_ai_turn_loop` 的选点逻辑，
           胜率数字纹丝不动（实测前后 464/536 完全一致），度量工具形同虚设。
           度量工具假绿比产品假红更危险（CLAUDE.md 教训 #15 的反面）。
        """
        return server._ai_choose_attack(room, pid)

    def choose_card(self, room, pid):
        """该打哪张手牌 —— 同样**委托 server 的唯一实现**。

        `server._ai_choose_card` 一次给出「下标 + 目标」，这里把目标缓存下来，
        由 `choose_card_targets` 交回（框架是分两步问的）。

        ⚠️ `cards_played` 必须传：大师每回合有**出牌预算**（`ai_brain.CARDS_PER_TURN`），
           不传的话驱动器会让它无限出牌 —— 量出来的就不是线上那个 AI 了
           （正是本文件头上那条"度量工具不能复刻被测对象"的同族错误：
             接口在，但参数没接对，同样是假绿）。
        """
        if getattr(room, 'ai_difficulty', 'normal') == 'easy':
            return None
        idx, targets = server._ai_choose_card(room, pid, self.cards_played)
        self._pending_targets = targets or {}
        return idx

    def begin_turn(self, room, pid):
        """每回合开始：清掉本回合的出牌计数与缓存的出牌目标。"""
        super().begin_turn(room, pid)
        self._pending_targets = {}

    def note_card_played(self):
        """驱动器确认「这次出牌机会真的用掉了」后累加。"""
        self.cards_played += 1

    def cards_per_turn(self, room, pid):
        """本回合允许出几张牌。easy/normal/hard 沿用「一回合一张」。"""
        if server._ai_difficulty_of(room, pid) != 'master':
            return 1
        return int(getattr(server.ai_brain, 'CARDS_PER_TURN', 1) or 1)

    def choose_placement(self, room, pid, pending):
        """放置落点：大师走 `ai_brain.resolve_placement`，其余沿用基类随机。

        ⚠️ 必须与线上**同一份决策**：线上是 `server._ai_consume_own_placement`
        （它调 `ai_brain.resolve_placement`）。这里若留在基类的 `random.choice`，
        量出来的就是"随机落点的大师"，与线上不是同一个 AI ——
        又回到本文件头上那条「度量工具不能复刻/替换被测对象」。
        """
        if server._ai_difficulty_of(room, pid) != 'master':
            return super().choose_placement(room, pid, pending)
        legal = _legal_placement_cells(room, pid, pending)
        if not legal:
            return None
        cell = server.ai_brain.resolve_placement(room, pid, pending.get('kind'), legal)
        return cell if cell is not None else None

    def choose_card_targets(self, room, pid, card):
        """`choose_card` 已经算好的目标，原样交回（不再自己算第二遍）。"""
        return getattr(self, '_pending_targets', None) or {}

    def choose_chain_response(self, room, pid, window):
        """照抄 `_ai_chain_respond` 的判据；无牌 / 康不动 → 明确放弃。"""
        if not server._ai_can_negate_chain_top(room, pid):
            return {'chain': False}
        card = next((c for c in room.players[pid].magic_hand if c.name == '失灵！'), None)
        if card is None:
            return {'chain': False}
        return {'chain': True, 'card': {'name': card.name, 'speed': card.speed,
                                        'type': card.type}, 'targets': []}


def _shot_verdict(room, pid, x, y):
    """这一炮打出去之后的判定：`'hit'` / `'shielded'` / `''`（未命中）。

    ⚠️ 判据**只读防守方的 `ships`**，而这是"棋盘本身"的公开信息（前端也拿得到
       被轰过的格子）。这里读它不是为了替 AI 决策 —— 决策层在 `ai_brain.py`，
       它的作弊守卫由 `tests/test_ai_brain.py` 钉着。本函数只服务于**度量**。

    为什么不能用别的方式拿这个数（都试过或权衡过）：
      · `handle_attack` 的返回值只有 `{'status':'success'}`（命中与否在
        `AttackResult` 里，只走 `emit`）；
      · 盾挡下的那一炮**不记进 `attacker.attacks`**（server.py 有意为之），
        所以 `attacks` 列表里的 `hit` 会漏掉它；
      · 攻守都是 AI 时，`room.last_attack` 会被下一炮/别的路径覆写。

    因此：打完后看"这一格是不是某艘船的格"。命中且该船**没多出命中数**（也没有
    强制击杀）就是被盾/无敌吸收 —— 两种都算"这一炮打中了"，但分开计数。
    """
    defender_id = next((o for o in room.players if o != pid), None)
    defender = room.players.get(defender_id) if defender_id else None
    if defender is None:
        return ''
    for ship in (getattr(defender, 'ships', None) or []):
        if {'x': x, 'y': y} in (ship.positions or []):
            return 'hit'
    return ''


def _sunk_at(room, pid, x, y):
    """这一炮打的那一格上，船是不是**沉了**（`len(hits) >= len(positions)`）。

    与 server 的存活判据同一份口径（CLAUDE.md 第 4 节：存活 = `len(hits) <
    len(positions)`）。无敌中的船**不记 hits**，所以这里自然返回 False。
    """
    defender_id = next((o for o in room.players if o != pid), None)
    defender = room.players.get(defender_id) if defender_id else None
    if defender is None:
        return False
    for ship in (getattr(defender, 'ships', None) or []):
        if {'x': x, 'y': y} not in (ship.positions or []):
            continue
        return len(ship.hits or []) >= len(ship.positions or [])
    return False


def _shielded_by(room, pid, x, y):
    """这一格上是否停着一艘「挨了这一炮却毫发无伤」的船（盾 / 无敌）。

    与 `_shot_verdict` 配对使用：`hit` 之后再看这一眼，就能把"打中了但没造成
    伤害"（盾/无敌）从"打中了且造成伤害"里分出来 —— 两者对"侵略性"的含义不同。
    """
    defender_id = next((o for o in room.players if o != pid), None)
    defender = room.players.get(defender_id) if defender_id else None
    if defender is None:
        return False
    for ship in (getattr(defender, 'ships', None) or []):
        if {'x': x, 'y': y} not in (ship.positions or []):
            continue
        return bool(getattr(ship, 'shield', False) or getattr(ship, 'invincible', False))
    return False


def _legal_placement_cells(room, pid, pending):
    """放置流程的合法候选格，**复用 server 的 `_placement_error`**（唯一判据）。

    口径与 `server._ai_consume_own_placement` 完全一致：
      · `last_stand` / `shenji_redeploy` 有"只能放这些格"的白名单；
      · `shenji_redeploy` 额外豁免"原位置"（那些格必然被对方打过）；
      · 其余按默认规则（未被打过、不在神威洞里、未被己方船占用）。
    不复刻规则 —— 复刻出来的候选集一旦与服务端漂移，
    驱动器就会量到"AI 挑了一个服务端不认的格子"，而这看起来像 AI 的错。
    """
    kind = pending.get('kind')
    allow = set()
    if kind == 'last_stand':
        allow = {(int(a[0]), int(a[1]))
                 for a in (room.game_effects.get('last_stand_cells') or [])}
    elif kind == 'shenji_redeploy':
        allow = {(int(a[0]), int(a[1]))
                 for a in (room.game_effects.get('shenji_redeploy_cells') or [])}
    ignore_sunken = kind == 'shenji_redeploy'
    out = []
    for x, y in CELLS:
        if allow and (x, y) not in allow:
            continue
        if server._placement_error(room, pid, x, y, allow_cells=allow,
                                  ignore_sunken=ignore_sunken):
            continue
        out.append((x, y))
    return out


# ===========================================================================
# 策略名 → 工厂。CLI 与 `make_policy()` 共用这一份。
# `master` 是设计文档里第 4 档难度，**尚未实现** —— 故意登记成"未实现"，
# 让 `python tools/headless_game.py --p1 master` 报一句能看懂的错，
# 而不是默默回落到别的策略给出一个假的胜率。
POLICY_FACTORIES = {
    'random': lambda: RandomPolicy(play_cards=True),
    'easy': lambda: ExistingAIPolicy('easy'),
    'normal': lambda: ExistingAIPolicy('normal'),
    'hard': lambda: ExistingAIPolicy('hard'),
    'master': lambda: ExistingAIPolicy('master'),
}


def make_policy(name):
    """按名字造策略；名字未知（含尚未实现的 master）时抛 ValueError 并列出合法值。"""
    if name not in POLICY_FACTORIES:
        raise ValueError(f'未知策略 {name!r}；可用：{", ".join(sorted(POLICY_FACTORIES))}')
    factory = POLICY_FACTORIES[name]
    if factory is None:
        raise ValueError(f'策略 {name!r} 尚未实现（现有可用：'
                         f'{", ".join(n for n, f in sorted(POLICY_FACTORIES.items()) if f)}）')
    return factory()


# ===========================================================================
# 无头环境补丁
# ===========================================================================
@contextlib.contextmanager
def _server_patches(capture=None, isolate_db=True):
    """临时把 socket/定时器/事件出口换成无副作用版本，退出时无条件还原。

    为什么不做成"只补一次"的全局开关：别的测试文件里有 monkeypatch fixture，
    本模块一旦长期占着 `server.emit`，会把那些 fixture 的意图盖掉；
    而 try/finally 还原能让本模块在任意上下文里安全嵌套调用。

    `isolate_db`：`handle_use_magic_card` 每打一张牌都会走
    `record_card_use` → `db.record_card_use` → **一次 sqlite3 commit**。
    实测（cProfile，100 局 hard vs hard）这一次 commit 占总墙钟时间的 **58%** ——
    对局本身只要 0.8ms/局，写库要 2.3ms/张牌。而"卡牌图鉴使用次数"这种统计跟
    胜负、回合数、动作序列**一个字都不沾**，所以无头批量跑默认把它关掉
    （只关统计写入，不改任何对局判据）。要连着统计一起测时传 `isolate_db=False`，
    再配合 `BATTLESHIP_DB_PATH` 指到临时库（CLAUDE.md 第 11.8 条）。
    """
    original = {
        'emit': server.emit,
        '_maybe_run_ai_turn': server._maybe_run_ai_turn,
        'start_background_task': server.socketio.start_background_task,
        'socketio_emit': server.socketio.emit,
        '_finalize_match': server._finalize_match,
        'record_card_use': server.record_card_use,
        'db_record_card_use': server.db.record_card_use,
        'db_record_user_card_use': server.db.record_user_card_use,
    }

    def record_emit(event, data, to=None, room=None):
        if capture is not None:
            capture.append((event, data, to, room))
        return None

    def no_op(*_args, **_kwargs):
        return None

    server.emit = record_emit
    server._maybe_run_ai_turn = no_op
    server.socketio.start_background_task = no_op
    server.socketio.emit = no_op
    if isolate_db:
        server.record_card_use = no_op
        server.db.record_card_use = no_op
        server.db.record_user_card_use = no_op
    try:
        yield
    finally:
        server.emit = original['emit']
        server._maybe_run_ai_turn = original['_maybe_run_ai_turn']
        server.socketio.start_background_task = original['start_background_task']
        server.socketio.emit = original['socketio_emit']
        server._finalize_match = original['_finalize_match']
        server.record_card_use = original['record_card_use']
        server.db.record_card_use = original['db_record_card_use']
        server.db.record_user_card_use = original['db_record_user_card_use']


def _state_hash(room) -> str:
    """房间**可观察状态**的短哈希：用于认「这一步到底有没有改变任何东西」。

    只取判据关心的叶子字段，不 dump 活对象（房间里有卡牌实例 / 日志列表，
    `json.dumps` 整个房间既慢又没有意义）。时间戳一律不取 —— 否则这个
    哈希永远在变，就识别不出"原地打转"了。
    """
    parts = [room.state, room.current_phase, str(room.round),
             str(room.attacks_remaining), str(room.current_attacker),
             '1' if room.chain else '0', '1' if room.chain_waiting else '0',
             str(len(room.magic_deck)), str(len(room.magic_discard)),
             field_magic_name(room)]
    for pid, p in sorted(room.players.items()):
        alive = sum(1 for s in p.ships if len(s.hits) < len(s.positions))
        parts.append(f'{pid}:{alive}:{len(p.magic_hand)}:{len(p.attacks)}')
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:12]


# ===========================================================================
# 驱动器
# ===========================================================================
class HeadlessGame:
    """一局的驱动器：建无头房间 → 摆船 → 猜拳 → 逐回合推进 → 收尾。

    用法（`play_game()` 是它的薄封装）：

        with HeadlessGame(lambda: ExistingAIPolicy('hard'), lambda: RandomPolicy(),
                          seed=1) as game:
            result = game.run()
    """

    def __init__(self, p1, p2, seed=None, max_rounds=200, max_actions=4000,
                 max_stuck=60, finalize=False, keep_events=False,
                 isolate_db=True, ai_difficulty=None, player_names=('P1', 'P2')):
        self.p1_factory = p1
        self.p2_factory = p2
        self.seed = random.randrange(1 << 30) if seed is None else int(seed)
        self.max_rounds = int(max_rounds)
        self.max_actions = int(max_actions)
        self.max_stuck = int(max_stuck)
        self.finalize = bool(finalize)
        self.keep_events = bool(keep_events)
        self.isolate_db = bool(isolate_db)
        self.ai_difficulty = ai_difficulty
        self.player_names = player_names

        self.result = GameResult(seed=self.seed)
        self.events = []
        self.room = None
        # p1 = **房间里的 AI 座位**（id = 'ai-'+room_id，由 create_ai_room 预置）；
        # p2 = 真人座位。它俩是"座位"不是"先手"—— 先手由猜拳决定（见 `_rps`）。
        self.p1 = None
        self.p2 = None
        self._actions = 0
        self._stuck = 0
        self._last_state = None
        self.cards_played_this_turn = 0
        self._last_attack_error = ''

    # ── 生命周期 ────────────────────────────────────────────────────────
    def __enter__(self):
        self._rng_state = random.getstate()
        random.seed(self.seed)
        self._patch = _server_patches(self.events if self.keep_events else None,
                                      isolate_db=self.isolate_db)
        self._patch.__enter__()
        self._build()
        return self

    def __exit__(self, *exc):
        try:
            if self.room is not None:
                server.room_manager.delete_room(self.room.id)
                self.room = None
        finally:
            self._patch.__exit__(*exc)
            random.setstate(self._rng_state)
        return False

    def _build(self):
        """造房间。

        用 `room_manager.create_ai_room` 而不是自己拼 GameRoom：它负责
        `is_ai_room` / `ranked=False` / AI 座位 / `init_player_magic`（整副牌堆）
        这几件事，漏一件就不是"真 AI 房"了。

        ⚠️ 座位约定：AI 位 = `'ai-'+room_id`（先手座位 p1），真人位 = `'human-0'`（p2）。
        `determine_rps_winner` 取 `list(room.players)[0]` / `[1]`，所以座位顺序
        必须固定，否则猜拳结算的两边会随字典顺序漂。
        """
        result = self.result
        room_id = server.room_manager.create_ai_room(
            'human-0', self.player_names[1], None,
            self.ai_difficulty or 'hard')
        room = server.room_manager.get_room(room_id)
        room.players['human-0'] = server.Player(
            name=self.player_names[1], ships=[], attacks=[], remaining_ships=0,
            user_id=None, sid='human-0')
        room.init_player_magic('human-0', server.magic_cards)
        room.state = 'placing_ships'
        room.turn_started_at = time.time()
        self.room = room
        self.ai_id = server._ai_player_id(room)
        self.human_id = 'human-0'
        self.result.room_id = room_id

        # 座位约定：房间的 `ai_difficulty` 是**AI 座位（p1）**的能力档位。
        #
        # ⚠️ 它是 `_can_respond_chain` 判断"AI 能不能用「失灵！」响应连锁"的唯一依据
        # （normal 只能康、easy 不参与），所以必须与 p1 的策略对齐 —— 否则量出来的
        # 是"normal 也会康连锁 / hard 不康"，不是那一档的真实强度。
        #
        # ⚠️ 两个座位都是 AI 时（master vs hard 这类自对弈度量）**必须逐座位设**：
        #    房间级的单一档位会让 p2 也套用 p1 的档位 —— 于是 hard 那一侧也用大师的
        #    卡池与开炮逻辑，量出来的是"大师 vs 大师"，胜率必然贴着 50%。
        #    实测：修之前 master vs hard 是 50.0%，两个座位的行为其实一模一样。
        p1_difficulty = getattr(self._make(self.p1_factory), 'difficulty', None)
        p2_difficulty = getattr(self._make(self.p2_factory), 'difficulty', None)
        room.ai_difficulty = self.ai_difficulty or p1_difficulty or 'hard'
        if p1_difficulty and p2_difficulty:
            room.ai_difficulty_by_player = {self.ai_id: p1_difficulty,
                                            self.human_id: p2_difficulty}

        self.p1 = self.ai_id
        self.p2 = self.human_id
        # 座位 id 要写进结果：`summarize` 靠它把 winner 归到 p1/p2 两边。
        self.result.p1 = self.p1
        self.result.p2 = self.p2
        self.policies = {self.p1: self._make(self.p1_factory),
                         self.p2: self._make(self.p2_factory)}
        for pid, policy in self.policies.items():
            if hasattr(policy, 'bind'):
                policy.bind(random.Random(random.randrange(1 << 30)))

    @staticmethod
    def _make(factory):
        return factory() if callable(factory) else factory

    # ── 记录 ────────────────────────────────────────────────────────────
    def _record(self, kind, pid, detail=''):
        self._actions += 1
        self.result.actions.append((kind, pid, detail))

    def _note_shot(self, pid, hit=False, miss=False, shielded=False, rejected=False,
                   sunk=False):
        """记一炮的结果。只被**炮击动作**调用，所以计数恒等于开炮次数。

        四个桶互斥；`attacks_fired` 是总和。被拒的那一炮也算"试图开炮"
        （`rejected_shots`），与真的打出去分开记 —— 否则"有多少炮其实被
        门禁挡了"就看不见了。

        `sunk=True` 额外记一次 `kills`（这一炮**击沉**了一艘）。**必须分开记**：
        终局船数差（`sunk`）会被「死者苏生 / 增援 / 滥竽充数 / 疗愈」倒扣 ——
        实测大师 1000 局里 `_apply_ship_sunk_effects` 的事件数是 **4.69 次/局**，
        而终局船数差只有 **2.59 艘/局**，差的 2.1 艘全是这类卡把船捞回来的。
        拿终局差当"侵略性"会把"输出被对手回血抵消"读成"没输出"。
        """
        result = self.result
        result.attacks_fired[pid] = result.attacks_fired.get(pid, 0) + 1
        if sunk:
            result.kills[pid] = result.kills.get(pid, 0) + 1
        if rejected:
            result.rejected_shots[pid] = result.rejected_shots.get(pid, 0) + 1
        elif shielded:
            result.shielded_shots[pid] = result.shielded_shots.get(pid, 0) + 1
        elif hit:
            result.hit_shots[pid] = result.hit_shots.get(pid, 0) + 1
        elif miss:
            result.miss_shots[pid] = result.miss_shots.get(pid, 0) + 1

    def _violation(self, message):
        self.result.violations.append(message)

    def _stall(self, reason):
        if self.result.stalled:            # 幂等：卡死后会被反复撞到，只记第一次的原因
            return
        self.result.stalled = True
        self.result.stall_reason = reason
        self.result.rounds = self.room.round if self.room else 0
        self._record('stalled', '', reason)

    def observable_state(self) -> dict:
        """超预算时随报告一起给出的可观察状态（就是"卡在哪"的证据）。"""
        room = self.room
        if room is None:
            return {}
        return {
            'room_id': room.id,
            'state': room.state,
            'phase': room.current_phase,
            'round': room.round,
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining,
            'chain_len': len(room.chain),
            'chain_waiting': room.chain_waiting,
            'chain_window': room.chain_window,
            'priority_pending': bool(getattr(room, 'priority_pending', None)),
            'pending_ship_picks': len(getattr(room, 'pending_ship_picks', []) or []),
            'magic_temp_data_keys': sorted(room.magic_temp_data.keys()),
            'ships': {pid: [len(s.hits) < len(s.positions) for s in p.ships]
                      for pid, p in room.players.items()},
            'hand_sizes': {pid: len(p.magic_hand) for pid, p in room.players.items()},
            'last_attack_error': self._last_attack_error,
        }

    # ── 单步动作 ────────────────────────────────────────────────────────
    def _budget_left(self):
        if self._actions >= self.max_actions:
            self._stall(f'动作数达到上限 {self.max_actions}')
            return False
        if self.room.round > self.max_rounds:
            self._stall(f'回合数达到上限 {self.max_rounds}')
            return False
        return True

    def _tick(self):
        """每完成一个动作调一次：如果房间状态**一个字节都没变**，累计"原地打转"。

        这是"卡死"的判据 —— 比"动作数用完"精确：动作数用完可能是策略真的打不完，
        而状态不变说明**服务端已经拒绝了所有动作**（门禁卡住），必须报出来。
        """
        now = _state_hash(self.room)
        if now == self._last_state:
            self._stuck += 1
            if self._stuck >= self.max_stuck:
                self._stall(f'连续 {self._stuck} 个动作后房间状态无任何变化')
                return False
        else:
            self._stuck = 0
            self._last_state = now
        return True

    def _place_ships(self):
        """摆船。会被调用**不止一次**。

        败者食尘 / 灵气复苏 / 回光返照 三张牌都会把 `room.state` 打回
        `placing_ships`（清掉船或清双方船），等双方重新摆放完，
        `handle_place_ships` 的收尾分支会把局面接回去：
          · `huiguang_awaiting_placement` → 留在自己的准备阶段、攻击次数为 0
          · `lingqi_resurgence_applied`   → 恢复施法前的先后手与阶段
          · 其余（败者食尘 / 双方一起重摆）→ 退回 rock_paper_scissors 重新猜拳
        驱动器只摆一次的话，这三张牌一打出来整局就静静停在 placing_ships ——
        实测（seed=1001，round 1，human 打出「败者食尘」）就是这样卡住的。
        """
        room = self.room
        expected = 6
        for pid in (self.p1, self.p2):
            policy = self.policies[pid]
            player = room.players[pid]
            expected = int(getattr(player, 'max_ships', None) or 6)
            ships = policy.place_ships(room, pid)
            resp = server.handle_place_ships({'room_id': room.id, 'player_id': pid,
                                              'ships': ships})
            self._record('place_ships', pid, f'{len(ships or [])} 艘')
            if not (resp and resp.get('status') == 'success'):
                self._violation(f'摆船被拒：{pid} -> {resp}')
                # 再试一次：策略可能是随机的（RandomPolicy），重抽一次通常就合法了
                ships = policy.place_ships(room, pid)
                resp = server.handle_place_ships({'room_id': room.id, 'player_id': pid,
                                                  'ships': ships})
                if not (resp and resp.get('status') == 'success'):
                    self._violation(f'摆船连续两次被拒：{pid} -> {resp}')
                    self._stall(f'{pid} 摆船失败：{resp}')
                    return False
            self._tick()
        if any(len(p.ships) < expected for p in room.players.values()):
            self._stall('摆船结束后仍有玩家没有船')
            return False
        return True

    def _rps(self):
        """猜拳。

        AI 房下 `handle_rps_choice` 里 AI 会**自动**出拳（`random.choice`），
        所以这里只需要替真人出拳；平局由 `determine_rps_winner` 清空重来。
        每轮记一次动作，平局也算一次 —— 动作序列才对得上"实际发生了什么"。
        """
        room = self.room
        for _ in range(60):
            if room.state != 'rock_paper_scissors':
                return True
            for pid in (self.p1, self.p2):
                if room.state != 'rock_paper_scissors':
                    break
                choice = self.policies[pid].rps_choice(room, pid)
                server.handle_rps_choice({'room_id': room.id, 'player_id': pid,
                                          'choice': choice})
                self._record('rps', pid, choice)
                self._tick()
        self._stall('猜拳超过 60 次仍未分出先手')
        return False

    def _pump_chain(self):
        """把已挂起的连锁窗口推完（无头环境没有真人也没有超时定时器）。

        `chain_timer` 每开一次窗口自增一次，拿它当循环上界最实在：
        窗口轮到"谁都响应不了"的人时，`_advance_chain_window` 会内部顺延而不开窗口，
        `chain_passes` 不增，光看 passes 会以为卡住了。
        """
        room = self.room
        start = int(room.chain_timer)
        for _ in range(200):
            if not (room.chain or room.chain_waiting):
                return True
            if int(room.chain_timer) - start > 100:
                self._stall('连锁窗口推进次数异常')
                return False
            if room.chain_waiting:
                window = room.chain_window
                if not window or window not in self.policies:
                    self._stall(f'连锁窗口归属不明：{window!r}')
                    return False
                if not self._budget_left():
                    return False
                resp = self.policies[window].choose_chain_response(room, window, window)
                data = {'room_id': room.id, 'player_id': window,
                        'chain': bool(resp.get('chain'))}
                if resp.get('card'):
                    data['card'] = resp['card']
                if resp.get('targets'):
                    data['targets'] = resp['targets']
                server.chain_response(data)
                self._record('chain_response', window,
                             'negate' if resp.get('chain') else 'pass')
                self._tick()
                continue
            # chain 非空但没开窗口：`_advance_chain_window` 已经自己顺延/结算过了，
            # 正常不会走到这里；真走到就判卡死，免得 while 空转。
            self._stall('连锁栈非空但响应窗口未开启，无人推进')
            return False
        self._stall('连锁窗口 200 次仍未收敛')
        return False

    def _pending_window(self):
        """返回「当前正等着某个玩家做选择」的窗口：(类型, 玩家)；没有则 None。

        这些窗口全部会**冻结写操作**（`_action_wait_reason` 的四个来源），
        无头环境里没有真人也没有超时定时器，驱动器必须自己应答 ——
        不答就会以「对方正在宣言神机妙算，请等待宣言完成」之类的文案
        把整局卡死（这正是"AI 出牌把回合卡死"那条已知缺陷的同形状）。
        """
        room = self.room
        pending = (room.magic_temp_data or {}).get('pending_shenji')
        if pending and pending.get('caster') in self.policies:
            return ('shenji', pending['caster'])
        placement = (room.magic_temp_data or {}).get('pending_placement')
        if placement and placement.get('caster') in self.policies:
            return ('placement', placement['caster'])
        dice = getattr(room, 'pending_dice_discard', None)
        if isinstance(dice, dict):
            for pid, done in dice.items():
                if done is False and pid in self.policies:
                    return ('dice', pid)
        return None

    def _pump_pending(self):
        """把待办窗口应答掉：神机妙算宣言 / 放置落点 / 命运骰子弃牌。

        返回 True = 现在没有待办了，可以继续推进回合。
        """
        for _ in range(20):
            window = self._pending_window()
            if window is None:
                return True
            kind, pid = window
            if not self._budget_left():
                return False
            if kind == 'shenji':
                value = self.policies[pid].choose_shenji_prediction(self.room, pid)
                resp = server.handle_confirm_shenji_declare(
                    {'room_id': self.room.id, 'player_id': pid, 'prediction': value})
                self._record('confirm_shenji_declare', pid, f'prediction={value}')
                if not (resp and resp.get('status') == 'success'):
                    self._violation(f'神机妙算宣言被拒：{resp}')
                    self._stall(f'神机妙算宣言窗口无法关闭：{resp}')
                    return False
            elif kind == 'placement':
                pending = self.room.magic_temp_data['pending_placement']
                cell = self.policies[pid].choose_placement(self.room, pid, pending)
                if cell is None:
                    resp = server.handle_cancel_placement({'room_id': self.room.id,
                                                           'player_id': pid})
                    self._record('cancel_placement', pid, pending.get('kind', ''))
                else:
                    resp = server.handle_confirm_reinforcement(
                        {'room_id': self.room.id, 'player_id': pid,
                         'position': {'x': cell[0], 'y': cell[1]}})
                    self._record('confirm_reinforcement_position', pid,
                                 f'{cell[0]},{cell[1]}')
                if not (resp and resp.get('status') == 'success'):
                    self._violation(f'放置被拒：{pid} -> {resp}')
                    self._stall(f'放置流程无法推进：{resp}')
                    return False
            else:
                idx = self.policies[pid].choose_dice_discard(self.room, pid)
                resp = server.handle_dice_discard_choose(
                    {'room_id': self.room.id, 'player_id': pid, 'card_index': idx})
                self._record('dice_discard_choose', pid, f'card_index={idx}')
                if not (resp and resp.get('status') == 'success'):
                    self._violation(f'命运骰子弃牌被拒：{resp}')
                    self._stall(f'命运骰子弃牌待办无法完成：{resp}')
                    return False
            self._tick()
            self._pump_chain()
        self._stall('待办窗口 20 次仍未关闭')
        return False

    def _play_card(self, pid) -> bool:
        """出一张卡。返回 True = **这次出牌机会真的用掉了**（策略给出了牌）。

        ⚠️ 返回值是驱动器**不死循环**的关键：只有"策略没给出可打的牌"才返回 False，
        调用方据此继续往下走（去开炮），不会每一圈都重新问一遍 `choose_card`。
        实测踩过：`hard` 手上只有 Freezing！/滥竽充数 时正是这个形状 ——
        策略恒回 None，若把它当成"出过牌了"就会 200 圈原地打转、整局卡死。

        目标形状与 `handle_use_magic_card` 的载荷完全按前端那一份来：
        `card` 必须带 name+speed+type+description（否则 `MagicCard(**data['card'])`
        会去查卡表，速度/类型都可能对不上）。
        """
        room = self.room
        try:
            idx = self.policies[pid].choose_card(room, pid)
        except Exception as exc:                      # 策略自己炸了：记下来但别中断
            self._violation(f'choose_card 抛异常：{pid} {exc!r}')
            return False
        if idx is None:
            return False
        hand = room.players[pid].magic_hand
        if not isinstance(idx, int) or not 0 <= idx < len(hand):
            self._violation(f'choose_card 返回非法下标 {idx!r}（手牌 {len(hand)} 张）')
            return False
        card = hand[idx]
        targets = self.policies[pid].choose_card_targets(room, pid, card)
        if targets is None:
            return False
        resp = server.handle_use_magic_card({
            'room_id': room.id, 'player_id': pid,
            'card': {'name': card.name, 'speed': card.speed, 'type': card.type,
                     'description': getattr(card, 'description', '')},
            'targets': targets,
        })
        ok = bool(resp and resp.get('status') == 'success')
        self._record('use_magic_card', pid, card.name)
        if not ok:
            # 出牌被拒（条件不满足）不是缺陷：卡牌被 `_refund_card_to_hand` 退回手牌，
            # 同一回合再试会死循环，所以不管成功失败都算"本回合出过牌了"。
            self._violation(f'出牌被拒：{pid} {card.name} -> {resp}')
        self._tick()
        self._pump_chain()
        return True

    def _turn(self):
        """推进当前攻击者的一个回合：准备 → 战斗 → 结束 → 交回合。

        写成**平铺的单一循环**（而不是"准备/战斗/结束"三段嵌套）是有意的：
        每圈只做一件事、且必定消耗一次动作预算，所以"某个动作被服务端拒掉"
        永远不会变成不花预算的空转 —— 空转正是最容易被误判成"卡死"的形状。
        """
        room = self.room
        attacker = room.current_attacker
        policy = self.policies[attacker]
        if hasattr(policy, 'begin_turn'):
            policy.begin_turn(room, attacker)
        end_requested = False

        for _ in range(200):
            # ⚠️ 每圈都重新判断 state，不能只看进入 `_turn` 时的那一眼：
            # 出牌是在**回合中途**生效的，败者食尘就能在战斗阶段把局面打回
            # `placing_ships`。只检查一次的话，驱动器会继续对着"正在等待布船"的
            # 房间调 `enter_battle_phase` / `end_turn`（它们只看 current_attacker
            # 和 phase，不看 state）→ 双方 0 艘船却一路开着回合，整局静默跑完
            # 200 个大回合。实测（seed=3019，round 1 出败者食尘）就是这个形状。
            if room.state != 'attacking':
                return False
            if room.current_attacker != attacker:
                return room.state == 'game_over'
            if not self._budget_left():
                return False
            if not self._pump_pending():
                return False

            if room.current_phase == 'preparation':
                resp = server.enter_battle_phase({'room_id': room.id,
                                                  'player_id': attacker})
                self._record('enter_battle_phase', attacker, str(resp.get('status')))
                if resp.get('status') != 'success':
                    self._violation(f'进战斗阶段被拒：{resp}')
                    return False
                self._tick()
                continue

            if room.current_phase == 'battle':
                # ⚠️ 次数还有、**却一个合法格都没有**（36 格全打过）时，必须直接请求
                # 进结束阶段。这正是服务端自己那套思考超时兜底的判据
                # （`_auto_act_on_timeouts`：`if not candidates or room.attacks_remaining <= 0`），
                # 也是唯一能走出这个局面的路 —— `handle_attack` 会把任何重复坐标拒掉，
                # 一直问策略要到的是 None，就会变成"请求→被拒→请求"的死循环。
                # 实测（seed=1002 / round 10）就卡在这个形状上：rem=3、已打 36 格。
                attacked = {(a.x, a.y) for a in room.players[attacker].attacks}
                no_target = all(c in attacked for c in CELLS)
                if room.attacks_remaining <= 0 or no_target:
                    if no_target and room.attacks_remaining > 0:
                        self._last_attack_error = (
                            f'36 格全部打过，仍有 {room.attacks_remaining} 次攻击次数')
                        self._violation(self._last_attack_error)
                    end_requested = True
                elif policy.cards_played < policy.cards_per_turn(room, attacker):
                    # ★ 每打一炮之后**先问一句"有没有该打的牌"**再继续开炮。
                    #   顺序不能反：「溅射 / 雷达子弹 / 越战越勇 / 饮血」依赖
                    #   "上一发刚命中/刚击沉"，先开下一炮就把窗口永远错过了
                    #   （与 server._ai_master_turn 的第 1/2 步严格对应）。
                    if self._play_card(attacker):
                        policy.note_card_played()
                        if room.state == 'game_over' or room.current_attacker != attacker:
                            return room.state == 'game_over'
                        continue
                elif end_requested:
                    # 上一圈已经请求过结束阶段却被拒（比如卡牌刚把次数加回来）。
                    # 让策略再打一发，别在这里"请求→被拒→请求"地空转。
                    end_requested = False
                if not end_requested:
                    target = policy.choose_attack(room, attacker)
                    if target is None:
                        self._violation(f'策略放弃攻击但仍有 {room.attacks_remaining} 次攻击次数，'
                                        f'且已打过的格数={len(room.players[attacker].attacks)}')
                        end_requested = True
                    else:
                        x, y = int(target[0]), int(target[1])
                        resp = server.handle_attack({'room_id': room.id,
                                                     'player_id': attacker, 'x': x, 'y': y})
                        self._record('attack', attacker, f'{x},{y}')
                        verdict = _shot_verdict(room, attacker, x, y) if resp.get('status') == 'success' else ''
                        absorbed = verdict == 'hit' and _shielded_by(room, attacker, x, y)
                        # 这一炮有没有**击沉**（不是"打中"）：命中格上的那艘船
                        # `len(hits) >= len(positions)` 就是沉了（与 server 同一判据）。
                        sank = verdict == 'hit' and _sunk_at(room, attacker, x, y)
                        self._note_shot(
                            attacker,
                            hit=verdict == 'hit' and not absorbed,
                            shielded=absorbed,
                            miss=verdict != 'hit',
                            sunk=sank,
                            rejected=resp.get('status') != 'success')
                        if resp.get('status') != 'success':
                            self._last_attack_error = str(resp.get('message'))
                            self._violation(f'攻击被拒：{attacker} ({x},{y}) -> {resp}')
                        if not self._tick():
                            return False
                        continue

            if room.current_phase == 'end':
                resp = server.end_turn({'room_id': room.id, 'player_id': attacker})
                self._record('end_turn', attacker, str(resp.get('status')))
                if resp.get('status') != 'success':
                    self._violation(f'交回合被拒：{resp}')
                    return False
                self._tick()
                return room.state == 'game_over'

            # 走到这里只可能是"战斗阶段请求进结束阶段"那一支。
            resp = server.handle_enter_end_phase({'room_id': room.id, 'player_id': attacker})
            self._record('enter_end_phase', attacker, str(resp.get('status')))
            if resp.get('status') != 'success':
                self._violation(f'进结束阶段被拒：{resp}')
                if not self._tick():
                    return False
                continue
            self._tick()

        self._stall(f'{attacker} 的回合内 200 次尝试仍未交出回合')
        return False

    # ── 主循环 ──────────────────────────────────────────────────────────
    def run(self) -> GameResult:
        result = self.result
        started = time.perf_counter()
        try:
            if not self._place_ships():
                return self._finish(started)
            if not self._rps():
                return self._finish(started)
            for _ in range(self.max_actions):
                room = self.room
                if room.state == 'game_over' or room.winner:
                    result.winner = room.winner or result.winner
                    return self._finish(started)
                if not self._budget_left():
                    return self._finish(started)
                # `end_turn` 换大回合会把 state 退回 rock_paper_scissors（重新猜拳）。
                if room.state == 'rock_paper_scissors':
                    if not self._rps():
                        return self._finish(started)
                    continue
                # 三张重摆牌会把局面打回 placing_ships（见 `_place_ships` 的说明）。
                if room.state == 'placing_ships':
                    if not self._place_ships():
                        return self._finish(started)
                    continue
                if room.chain or room.chain_waiting:
                    if not self._pump_chain():
                        return self._finish(started)
                    continue
                if not self._pump_pending():
                    return self._finish(started)
                if not room.current_attacker:
                    self._stall('没有当前攻击者')
                    return self._finish(started)
                if self._turn() and room.winner:
                    result.winner = room.winner
                    return self._finish(started)
                # 一局的终止条件只有"有人赢了"或"撞上了硬上限"。
                # ⚠️ 这里**不能**写成"回合数没变就判卡死"：`_turn` 完全可能合法地
                # 不交出回合（连锁刚由 pump 结算、阶段被卡牌改动…），
                # 真正的不动由 `_tick` 的"状态哈希不变"来抓。
                if room.state == 'game_over' or room.winner:
                    result.winner = room.winner or result.winner
                    return self._finish(started)
            if not result.stalled:
                self._stall(f'动作数达到上限 {self.max_actions}')
            return self._finish(started)
        except Exception as exc:                       # 驱动器自身/服务端抛异常
            import traceback
            result.violations.append(f'驱动器异常：{exc!r}\n{traceback.format_exc()}')
            self._stall(f'驱动器异常：{exc!r}')
            return self._finish(started)

    def _finish(self, started):
        result = self.result
        result.rounds = self.room.round if self.room else 0
        if result.winner is None and self.room is not None and self.room.winner:
            result.winner = self.room.winner
        if result.winner:
            result.loser = self.p2 if result.winner == self.p1 else self.p1
        result.duration = time.perf_counter() - started
        # 「打疼了没有」的终局快照：双方各被击沉几艘。
        # 读 `remaining_ships`（终局船数）与 `max_ships`（本局起始船数）——
        # 两者都是房间里已有的字段，不新增任何状态。卡死局同样记，
        # 这样"改了之后卡死变多"不会让这个指标悄悄少算。
        room = self.room
        if room is not None:
            for pid, player in room.players.items():
                cap = int(getattr(player, 'max_ships', None) or 6)
                alive = int(getattr(player, 'remaining_ships', 0) or 0)
                result.sunk[pid] = max(0, cap - alive)
        # 房间对象马上要在 `__exit__` 里被删掉，卡死证据必须在这里先留一份纯数据。
        result.final_state = self.observable_state()
        # 结算（写库/徽章/段位）。默认关掉：它要读库（`_streak_context` 读连胜），
        # 会把"这一局的结果"和"上一局的历史"耦合起来 —— 同种子也跑不出同一个动作序列。
        # 量胜率只需要 winner/rounds，所以默认不走；单测要验结算时再打开。
        if self.finalize and self.room is not None and result.winner:
            try:
                server._finalize_match(self.room, result.winner, result.loser)
            except Exception as exc:
                result.violations.append(f'_finalize_match 异常：{exc!r}')
        return result


# ===========================================================================
# 对外入口
# ===========================================================================
def play_game(p1, p2, seed=None, **kwargs) -> GameResult:
    """跑一整局，返回 `GameResult`。

    p1 / p2 可以是策略实例，也可以是「无参工厂」（推荐传工厂：每局拿一个干净实例）。
    `seed` 固定时，同一对策略必定产生同一个 winner / rounds / action_hash。
    """
    with HeadlessGame(p1, p2, seed=seed, **kwargs) as game:
        return game.run()


def run_many(p1, p2, games=1, seed=1, progress=None, quiet=False, **kwargs):
    """连续跑 `games` 局，返回结果列表。

    每局的种子是 `seed + i`（可复现：换台机器、换顺序都得到同一批局面）。
    `progress` 给了就每局回调一次（CLI 用来打进度点）。

    `quiet=True`：把对局过程里 `apply_magic_effect` 等处的 `print` 吞掉。
    那些 print 是**每打一张牌一行**，1000 局会有十万行 —— 工具调用方
    （`tools/master_ablation.py` 已经自己包了 redirect）必须能关掉它，
    否则真实终端里前面的输出全被冲走（本函数原先没有这个开关）。
    """
    results = []
    with contextlib.redirect_stdout(io.StringIO()) if quiet else contextlib.nullcontext():
        for i in range(int(games)):
            result = play_game(p1, p2, seed=int(seed) + i, **kwargs)
            results.append(result)
            if progress is not None:
                progress(i, result)
    return results


def _mean(values):
    values = list(values)
    return (sum(values) / len(values)) if values else 0.0


def damage_stats(results) -> dict:
    """「打疼了没有」的汇总：双方各击沉几艘、各打了几炮、命中率多少。

    为什么单开一个函数而不是塞进 `summarize()`：`summarize()` 的返回字典已经被
    `tools/master_ablation.py` 等工具按名字取用，往里塞字段会让所有调用点都要
    重新表态；而这两个量是**同一批结果上的第二个视角**，分开算最省事。

    ⚠️ p1 = 房间里的 AI 座位、p2 = 真人座位（见 `HeadlessGame._build` 的座位约定）。
       先手由猜拳决定，所以 `sunk_by_p1` 不是"先手打沉几艘"。
    """
    played = len(results)
    fired = sum(sum(r.attacks_fired.values()) for r in results)
    hits = sum(sum(r.hit_shots.values()) for r in results)
    p1_wins = [r for r in results if r.winner and r.winner == r.p1]
    p2_wins = [r for r in results if r.winner and r.winner == r.p2]
    return {
        # 平均每局：p1 打沉了 p2 几艘 / p2 打沉了 p1 几艘 —— 胜率看不见的那两个数
        # ⚠️ 这是**终局船数差**，会被「死者苏生 / 增援 / 滥竽充数 / 疗愈」倒扣。
        'sunk_by_p1': _mean(r.sunk.get(r.p1, 0) for r in results),
        'sunk_by_p2': _mean(r.sunk.get(r.p2, 0) for r in results),
        # 炮击击沉**事件**数（不看对手回不回血）—— 衡量"输出"本身
        'kills_by_p1': _mean(r.kills.get(r.p1, 0) for r in results),
        'kills_by_p2': _mean(r.kills.get(r.p2, 0) for r in results),
        # 「无伤」：赢的那一方一艘都没沉 —— 作者实报的那句就是它
        'p1_flawless_wins': sum(1 for r in p1_wins if r.sunk.get(r.p1, 0) == 0),
        'p2_flawless_wins': sum(1 for r in p2_wins if r.sunk.get(r.p2, 0) == 0),
        'p1_flawless_rate': (sum(1 for r in p1_wins if r.sunk.get(r.p1, 0) == 0) / len(p1_wins))
                            if p1_wins else 0.0,
        'p2_flawless_rate': (sum(1 for r in p2_wins if r.sunk.get(r.p2, 0) == 0) / len(p2_wins))
                            if p2_wins else 0.0,
        'p1_hit_rate': _hit_rate(results, 'p1'),
        'p2_hit_rate': _hit_rate(results, 'p2'),
        'shots_per_game': (fired / played) if played else 0.0,
        'hit_rate': (hits / fired) if fired else 0.0,
        'shielded_total': sum(sum(r.shielded_shots.values()) for r in results),
        'rejected_total': sum(sum(r.rejected_shots.values()) for r in results),
    }


def _hit_rate(results, seat):
    """某个座位的命中率（命中 ÷ 开炮）。`seat` 取 `'p1'` / `'p2'`。"""
    fired = sum(r.attacks_fired.get(getattr(r, seat), 0) for r in results)
    hits = sum(r.hit_shots.get(getattr(r, seat), 0) for r in results)
    return (hits / fired) if fired else 0.0


def summarize(results) -> dict:
    """把结果列表汇成统计：胜率 + Wilson 置信区间 + 平均回合 + 卡死数。"""
    played = len(results)
    p1_wins = sum(1 for r in results if r.winner and r.winner == r.p1)
    p2_wins = sum(1 for r in results if r.winner and r.winner == r.p2)
    draws = played - p1_wins - p2_wins
    stalled = sum(1 for r in results if r.stalled)
    rounds = [r.rounds for r in results]
    return {
        'games': played,
        'p1_wins': p1_wins,
        'p2_wins': p2_wins,
        'draws': draws,
        'stalled': stalled,
        'p1_win_rate': (p1_wins / played) if played else 0.0,
        'p1_win_rate_ci': wilson_interval(p1_wins, played),
        'avg_rounds': (sum(rounds) / played) if played else 0.0,
        'elapsed': sum(r.duration for r in results),
        'violations': sum(len(r.violations) for r in results),
    }


def wilson_interval(successes, total, z=1.96):
    """Win rate 的 Wilson 置信区间（小样本/极端比例下比正态近似稳）。

    1000 局里赢 800 局时正态近似够用，但"hard vs easy 全胜"这种 100%
    用正态近似会给出 [1.0, 1.0] 这种假区间 —— Wilson 不会。
    """
    if total <= 0:
        return (0.0, 0.0)
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


# ===========================================================================
# CLI
# ===========================================================================
def _build_parser():
    parser = argparse.ArgumentParser(
        prog='headless_game.py',
        description='无头对局驱动器：不用 socket、不 sleep，批量跑完整局（见文件头说明）。')
    parser.add_argument('--games', type=int, default=1, help='局数（默认 1）')
    parser.add_argument('--p1', default='hard',
                        help='p1 策略名 = 房间里的 AI 座位（见 --list-policies）')
    parser.add_argument('--p2', default='hard',
                        help='p2 策略名 = 房间里的真人座位（先手由猜拳决定，不是座位）')
    parser.add_argument('--seed', type=int, default=None, help='起始种子（默认随机）')
    parser.add_argument('--max-rounds', type=int, default=200, help='单局大回合上限')
    parser.add_argument('--max-actions', type=int, default=4000, help='单局动作数上限')
    parser.add_argument('--player-names', nargs=2, default=('P1', 'P2'),
                        metavar=('P1名', 'P2名'))
    parser.add_argument('--violations', type=int, default=0,
                        help='最多打印几条被拒动作样本（默认 0）')
    parser.add_argument('--dump-state', type=int, default=0,
                        help='打印前 N 局卡死局的可观察状态（默认 0）')
    parser.add_argument('--list-policies', action='store_true', help='列出可用策略名后退出')
    parser.add_argument('--quiet', action='store_true',
                        help='吞掉对局过程里的 print（每打一张牌一行，批量跑会刷屏）')
    return parser


def _print_policies():
    for name in sorted(POLICY_FACTORIES):
        mark = '' if POLICY_FACTORIES[name] else '   （尚未实现）'
        print(f'  {name}{mark}')


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.list_policies:
        print('可用策略：')
        _print_policies()
        return 0

    # 先校验名字再开跑：不然未知策略（含尚未实现的 master）会在第一局才报错，
    # 前面已经白跑了几百局。
    try:
        for name in (args.p1, args.p2):
            make_policy(name)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    p1_factory = (lambda: make_policy(args.p1))
    p2_factory = (lambda: make_policy(args.p2))

    seed0 = args.seed if args.seed is not None else random.randrange(1 << 30)
    started = time.perf_counter()
    results = run_many(p1_factory, p2_factory, games=args.games, seed=seed0,
                       max_rounds=args.max_rounds, max_actions=args.max_actions,
                       player_names=tuple(args.player_names), quiet=args.quiet,
                       ai_difficulty=(args.p1 if args.p1 in server.AI_DIFFICULTIES else None))
    elapsed = time.perf_counter() - started
    stats = summarize(results)
    dmg = damage_stats(results)
    lo, hi = stats['p1_win_rate_ci']

    print(f'策略：p1={args.p1}  p2={args.p2}  种子={seed0}')
    print(f'局数            : {stats["games"]}')
    print(f'p1 胜 / p2 胜 / 平局 : {stats["p1_wins"]} / {stats["p2_wins"]} / {stats["draws"]}')
    print(f'p1 胜率         : {stats["p1_win_rate"]:.4f}  (95% CI {lo:.4f} ~ {hi:.4f})')
    # ★ 「打疼了没有」——胜率看不见的那一半。作者实报的「我甚至可以无伤赢他」
    #   在这里才有数字：`sunk_by_p1` = p1 打沉对方几艘，`sunk_by_p2` = p2 打沉 p1 几艘。
    print(f'平均击沉对方(p1) : {dmg["sunk_by_p1"]:.3f} 艘/局'
          f'   平均被击沉(p1) : {dmg["sunk_by_p2"]:.3f} 艘/局')
    print(f'炮击击沉事件 p1/p2: {dmg["kills_by_p1"]:.3f} / {dmg["kills_by_p2"]:.3f} 次/局'
          f'   （与上面的差 = 对手用卡把船捞回来的量）')
    print(f'无伤获胜 p1 / p2 : {dmg["p1_flawless_wins"]} 局 ({dmg["p1_flawless_rate"]:.1%})'
          f' / {dmg["p2_flawless_wins"]} 局 ({dmg["p2_flawless_rate"]:.1%})')
    print(f'命中率 p1 / p2   : {dmg["p1_hit_rate"]:.4f} / {dmg["p2_hit_rate"]:.4f}'
          f'   （每局开炮 {dmg["shots_per_game"]:.2f} 次，被拒 {dmg["rejected_total"]}）')
    print(f'平均大回合数     : {stats["avg_rounds"]:.2f}')
    print(f'卡死局数 (stalled): {stats["stalled"]}')
    print(f'被拒动作总数     : {stats["violations"]}')
    print(f'总用时          : {elapsed:.2f}s  ({stats["games"] / elapsed if elapsed else 0:.1f} 局/秒)')

    if stats['stalled']:
        print('\n卡死样本（前 5 局）：')
        for result in [r for r in results if r.stalled][:5]:
            print(f'  seed={result.seed} round={result.rounds} 原因={result.stall_reason}')
    if args.dump_state:
        import collections
        kinds = collections.Counter()
        for result in results:
            for message in result.violations:
                kinds[message.split('：')[0]] += 1
        print('\n被拒动作分类（前 10）：')
        for kind, count in kinds.most_common(10):
            print(f'  {count:>7}  {kind}')
        print(f'\n卡死局可观察状态（前 {args.dump_state} 局）：')
        for result in [r for r in results if r.stalled][:args.dump_state]:
            print(f'  seed={result.seed} {result.stall_reason}')
            print(f'    {result.final_state}')
    if args.violations:
        shown = 0
        for result in results:
            for message in result.violations:
                if shown >= args.violations:
                    break
                print(f'  [seed={result.seed}] {message}')
                shown += 1
            if shown >= args.violations:
                break
    return 1 if stats['stalled'] else 0


if __name__ == '__main__':
    sys.exit(main())
