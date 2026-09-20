# eventlet 下必须先 monkey_patch，且必须早于任何可能使用 socket/ssl/threading
# 的标准库导入：否则后台任务里的 time.sleep 会阻塞整个单线程 hub
# （掉线宽限 30s / 连锁超时 10s 都会让服务器假死）。
try:
    import eventlet
    eventlet.monkey_patch()
except ImportError:
    pass

import functools
import json
import os
import random
import threading
import time
import uuid
import secrets
import sys
from typing import Any
import logging
from flask import render_template, request, session, jsonify, has_request_context
from flask_socketio import SocketIO, join_room, leave_room, emit as semit

import db  # local database helpers for users and matches
import achievements  # 徽章判据（纯函数，唯一一份 evaluate()）
import anticheat  # 反作弊判据（纯函数；只判定不处罚，动作在本文件里做）
import dm  # 私聊的形状与规则（纯数据/纯函数：推送 payload 的字段清单只此一份）
import leveling  # 等级曲线 / 每局经验 / 升级动画分段（唯一一份规则）
import match_guard  # 匹配规避规则（纯函数：同 IP / 近来对手，唯一一份）
import suspicion  # 累计嫌疑度 + 阶梯封禁（纯函数，唯一一份规则）
import profile_spec  # 特权常量（level_101 等）
import quick_chat  # 局内快捷语表 + 频率规则（纯数据/纯函数，前端从接口取同一份）
import ranks  # 段位规则 / 每局加减分 / 大舰长晋升（唯一一份，结算与接口共用）
import presence  # 在线 / 对局中状态（纯内存零依赖：api.py 也要读它，见 presence.py 头部说明）
from api import app
from file import read_json

# 调试事件开关：仅在显式设置环境变量 ENABLE_TEST_EVENTS=1 时启用。
# 默认关闭，避免公网玩家通过 test_* 事件作弊（直接判胜、白嫖卡牌、读取对方船位等）。
ENABLE_TEST_EVENTS = os.environ.get('ENABLE_TEST_EVENTS') == '1'

# 调试面板（按 F8 唤出）的账号白名单：逗号分隔的 user_id。
# ⚠️ 12 个 test_* handler 里**没有任何身份校验**（它们靠上面那个开关兜底），
# 所以只要在公网把开关打开，就等于对**所有访客**开放作弊。配置这个白名单之后，
# 即使开关打开，也只有名单里的登录账号能用（其余一律拒绝）。
# 留空 = 与旧行为一致（开关打开谁都能用）—— 只适合本地/自建环境。
DEBUG_ADMIN_USER_IDS = {
    u.strip() for u in os.environ.get('DEBUG_ADMIN_USER_IDS', '').split(',') if u.strip()
}


def _debug_actor_allowed() -> bool:
    """当前调用者是否被允许使用调试事件（配合 ENABLE_TEST_EVENTS 一起判断）。"""
    if not DEBUG_ADMIN_USER_IDS:
        return True                      # 未配白名单 → 沿用旧行为
    try:
        uid = session.get('user_id')
    except RuntimeError:
        uid = None                       # 无请求上下文（单测直调 / 后台重放）
    return bool(uid) and str(uid) in DEBUG_ADMIN_USER_IDS


def _test_event(fn):
    """包装调试事件：未启用时静默拒绝，防止公网滥用。
    启用后若配了 DEBUG_ADMIN_USER_IDS，则只放行白名单账号。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not ENABLE_TEST_EVENTS:
            return {'status': 'error', 'message': '调试事件未启用'}
        if not _debug_actor_allowed():
            return {'status': 'error', 'message': '调试事件未对你的账号开放'}
        return fn(*args, **kwargs)
    return wrapper


def _require_live_room(fn):
    """写操作门禁：对局已结束（state == 'game_over'）后一律拒绝。

    此前这些 handler 只校验「房间/玩家/身份」与阶段，不看 state，导致终局后：
    重新布船会把 game_over 倒回 rock_paper_scissors（对局复活，且该房间再也
    不会被 reaper 回收）；胜者还能继续投降，把已经记过账的胜负翻转。
    与 @_test_event 一样必须写在 @socketio.on(...) 的内侧。
    """
    @functools.wraps(fn)
    def wrapper(data=None, *args, **kwargs):
        room = None
        try:
            if isinstance(data, dict) and data.get('room_id'):
                room = room_manager.get_room(data['room_id'])
        except Exception:
            room = None
        if room is not None and getattr(room, 'state', None) == 'game_over':
            return {'status': 'error', 'message': '对局已结束'}
        result = fn(data, *args, **kwargs)
        # 成功做出一次操作的玩家 → 重置思考计时。
        # 超时兜底只针对「卡住完全不动」的人，不该惩罚在慢慢想、一直在操作的人。
        try:
            if (room is not None and isinstance(result, dict)
                    and result.get('status') == 'success'):
                pid = (data or {}).get('player_id')
                if pid and pid in room.players and room.current_attacker == pid:
                    room.turn_started_at = time.time()
        except Exception:
            pass
        return result
    return wrapper


def record_card_use(card, count=1, user_id=None):
    """记一次卡牌使用（卡牌图鉴里「使用次数」的来源）。

    只做统计，任何异常都吞掉：统计不该影响对局。场地魔法同样计数。

    `user_id` 可选：给了就**同时**写全局表与个人表（`user_card_usage`，
    个人信息名片里「最爱用的卡」的来源）。个人统计是 2026-09-17 新增的，
    老调用点不传就只写全局表，行为与以前一致。

    ⚠️ 传进来的必须是**真实用户 id**（`Player.user_id`）。`room.players` 的 key
    有两套约定：匹配房里它是 socket sid，不是用户 id（见 CLAUDE.md 第 6 节），
    拿它当 user_id 会把统计写到不存在的账号上。
    """
    try:
        name = getattr(card, 'name', card)
        if not name:
            return
        db.record_card_use(name, count)
        if user_id:
            db.record_user_card_use(user_id, name, count)
    except Exception:
        pass


def emit(event, data, to=None, room: str | None = None):
    json_data = json.dumps(data, default=lambda o: o.__dict__)
    try:
        return semit(event, json.loads(json_data), to=to, room=room)
    except RuntimeError:
        # 无请求上下文（如后台任务/定时器）时直接走 SocketIO 服务端发送
        return socketio.emit(event, json.loads(json_data), to=to, room=room)


class GameLog:
    def __init__(self, text: str, event_type: str = 'info', payload: dict | None = None):
        self.ts = int(time.time())
        self.type = event_type
        self.text = text
        self.detail = payload
    
    def to_dict(self):
        return {
            'ts': self.ts,
            'type': self.type,
            'text': self.text,
            'detail': self.detail
        }


def _log_name(room, player_id):
    """日志里统一用玩家名，取不到则退回 id。"""
    p = room.players.get(player_id)
    return (p.name or player_id) if p else player_id


def add_game_log(room, text: str, event_type: str = 'info', payload: dict | None = None):
    """Append a lightweight battle log entry and push it to clients."""
    if not hasattr(room, 'game_logs'):
        room.game_logs = []
    entry = GameLog(text, event_type, payload)
    room.game_logs.append(entry.to_dict())
    # 实时推送给房间内两个客户端（无 socket 上下文时 emit 内部已兜底）
    try:
        emit('game_log', entry.to_dict(), room=room.id)
    except Exception:
        pass


def log_magic(room, caster_id, card, extra=''):
    """统一记录魔法卡使用（连锁结算的唯一入口调用）。"""
    name = _log_name(room, caster_id)
    tail = f'，{extra}' if extra else ''
    add_game_log(room, f'第{room.round}回合 · {name} 使用了【{card.name}】{tail}',
                 'magic', {'caster': caster_id, 'card': card.name})


# 在线人数统计
# ⚠️ 唯一真相源是 `lobby_manager.presence`（定义在 RoomManager 之后）。
# 此前这里是一个裸 sid 集合 `online_users`——它没有名字，所以大厅列不出"谁在线"，
# 想补名字就只能再维护第二份结构（两份在线表 = 必然漂移，见 CLAUDE.md 通用教训二）。
magic_cards: list["MagicCard"]
@app.route('/api/online_count')
def api_online_count():
    """获取当前在线人数"""
    return jsonify({'online_count': lobby_manager.online_count()})

class Position:
    x: int
    y: int
    hit: bool = False
    ship_sunk: bool = False
    is_sulfur: bool = False
    is_bomb: bool = False
    is_splash: bool = False

    def __init__(self, x: int, y: int, hit=False, ship_sunk=False, is_sulfur=False, is_bomb=False, is_splash=False):
        self.x = x
        self.y = y
        self.ship_sunk = ship_sunk
        self.is_sulfur = is_sulfur
        self.round = None
        self.hit = hit
        self.is_bomb = is_bomb
        self.is_splash = is_splash

    def __eq__(self, other):
        if isinstance(other, dict):
            return self.x == other.get('x') and self.y == other.get('y')
        else:
            return self.x == other.x and self.y == other.y


class PlayerShip:
    invincible: bool
    positions: list[Position]
    hits: list[Position]
    shield: bool = False  # 是否有护盾
    trap: bool = False  # 守株待兔：是否带陷阱标记（本大回合内被击沉时让对方牺牲两艘）

    def __init__(self, positions: list[Position], hits: list[Position],**kwargs):
        self.invincible = False
        self.trap = False
        # 确保positions是Position对象列表
        self.positions = []
        for pos in positions:
            if isinstance(pos, dict):
                self.positions.append(Position(**pos))
            else:
                self.positions.append(pos)
        # 确保hits是Position对象列表
        self.hits = []
        for hit in hits:
            if isinstance(hit, dict):
                self.hits.append(Position(**hit))
            else:
                self.hits.append(hit)


class MagicCard:
    name: str
    speed: int
    type: str
    description: str

    def __init__(self, name: str, speed: int = "", type: str = "", description: str = ""):
        self.name = name
        if speed != "" and type != "" and description != "":
            self.speed = speed
            self.type = type
            self.description = description
            return
        # 客户端可能只传 name；按名查卡。找不到时抛 ValueError（而非 IndexError），
        # 由调用方捕获并返回错误响应，避免恶意/残缺卡牌数据直接让 handler 崩溃。
        card = next((c for c in magic_cards if c.name == name), None)
        if card is None:
            raise ValueError(f"未知的魔法卡: {name!r}")
        self.speed = card.speed
        self.type = card.type
        self.description = card.description


class EffectFlags:
    treasure_hunter: bool = False
    prediction: bool = False
    subsidy: bool = False
    subsidy_bonus: int = 0  # 百亿补贴：自己每沉一艘船累计的额外攻击次数
    no_draw: bool = False
    forced_kill: int = 0  # 强制击杀次数
    vampire: bool = False  # 饮血效果
    # 绝处逢生【拆分两个标记，生命周期不同】—— 此前合成一个，于是"击杀即胜"
    # 跟着回合清理一起过期，只在发动当回合有效（作者实测反馈）。
    #   last_stand     ：发动回合内自己的其余魔法卡全部无效 → 只持续本回合
    #   last_stand_win ：此后任意回合击杀对方战舰即直接获胜 → 活到对局结束
    last_stand: bool = False  # 绝处逢生：发动回合的锁卡
    last_stand_win: bool = False  # 绝处逢生：本局后续击杀即胜
    double_attacks: bool = False
    battle_spirit: bool = False
    # 五险一金：出牌时只「挂上保险」，等本回合攻击次数第一次归零、
    # 且那时确实没让对方减船，才真正 +3（见 _maybe_trigger_wuxian_yijin）。
    # 不放进 permanent_flags，所以回合切换会被清掉 —— 没触发就作废，符合卡面「这一回合」。
    wuxian: bool = False


# EffectFlags 里允许下发给前端的标记名（`_build_room_sync` 的 active_effects）。
# ⚠️ 只登记**玩家身上**的效果标记。房间级效果住在 room.game_effects，语义完全不同，
# 混进这份名单会出事：last_stand_cells / last_stand_owner 都以 'last_stand' 开头，
# 前端按前缀匹配就会把"候选格还在场"误判成"锁卡生效中"。
_PUBLIC_EFFECT_FLAGS = frozenset(
    name for name, value in vars(EffectFlags).items()
    if not name.startswith('_') and isinstance(value, (bool, int))
)


# ---------------------------------------------------------------------------
# 效果标记的生命周期分类
# ---------------------------------------------------------------------------
# 两处回合清理（end_turn 的普通换回合 / 大回合重新猜拳）都引用这里，
# 避免各写一份白名单而互相漂移 —— 此前一处写 1 个字段、一处写 5 个，
# 且两边都塞了 'holy_heart'/'reinforcement_check' 这种根本不属于 EffectFlags
# 的名字（它们住在 room.game_effects 里，永远匹配不到，是无效条目）。
#
# 分类依据是卡面原文：
#   越战越勇 "接下来【这一回合内】"      → 本回合，换回合即清
#   五险一金 "【这一回合】…第一次用尽时"  → 本回合，换回合即清
#   火力全开（double_attacks）本回合      → 换回合即清
#   绝处逢生 "在绝处逢生生效的【回合】"    → 本回合，换回合即清
#
# ⚠️ 上面这句只对绝处逢生的【锁卡】部分成立。它还有后半截
#    "只要自己击杀了对方的任何一艘船，自己直接获胜" —— 作者明确裁定这部分
#    **不随回合过期，活到对局结束**，所以拆成了独立标记 last_stand_win。
#    两个标记的字段含义差异见 EffectFlags 里的注释，改动时必须一起看。
#
# 下面这些写的是"接下来…"，没有回合限定，但按作者裁定统一为【本大回合】：
#   百亿补贴 / 饮血 / 八方来财 —— 跨小回合保留，大回合结束时清。
#   （此前它们在小回合切换就被清掉，于是对手回合里攒到的加成还没轮到自己
#     的回合就没了，玩家永远拿不到。）
#
# ⚠️ 这份名单是【唯一实现】。end_turn 里曾经另有一份写死的 permanent_flags
#    内联列表，两份一漂移就出事：绝处逢生的"击杀即胜"新标记加进来时只改了
#    注释、没加进任何一份名单，于是换小回合就被清掉（作者实测反馈）。改动时
#    只改这里，别在调用点再抄一份。
FLAGS_KEEP_ACROSS_TURN = frozenset({
    'no_draw',          # 无中生有：接下来这一个大回合内
    'prediction',       # 神机妙算：到对方结束阶段结束之后
    'forced_kill',      # 余音绕梁：本回合 + 下一个回合的攻击阶段
    'subsidy',          # 百亿补贴：接下来（本大回合内）
    'subsidy_bonus',    # 百亿补贴已累计的额外攻击次数，与上面同生命周期
    'vampire',          # 饮血：接下来自己的攻击
    'treasure_hunter',  # 八方来财：接下来场上战舰数主动变化
    # 绝处逢生的"击杀即胜"：活到对局结束（大回合白名单为空集，见下）
    'last_stand_win',
})

# 大回合结束（重新猜拳）时的白名单。
# ⚠️ 这份名单同样是【唯一实现】—— end_turn 的大回合分支直接调它，
#    别在那里另抄一份（小回合那边就抄过一份，见 FLAGS_KEEP_ACROSS_TURN 的说明）。
#
# 按作者裁定，百亿补贴等"接下来…"的效果都只持续本大回合，全部清掉；
# 唯一要跨大回合活下来的是绝处逢生的"击杀即胜"（活到对局结束）。
FLAGS_KEEP_ACROSS_ROUND = frozenset({
    'last_stand_win',
})


def _prune_effect_flags(room, keep):
    """按白名单裁剪双方的 effect_flags，返回是否有变化。

    用 __dict__ 过滤即可：EffectFlags 的字段是"类属性 + 注解"，
    没被显式赋过值的字段不在实例 __dict__ 里，读取时走类属性默认值（False/0），
    所以裁剪后实例依然是完整可用的对象。
    """
    changed = False
    for p_id in room.players:
        flags = room.players[p_id].effect_flags
        before = dict(flags.__dict__)
        after = {k: v for k, v in before.items() if k in keep}
        if after != before:
            flags.__dict__ = after
            changed = True
    return changed


class Player:
    magic_hand: list[MagicCard]
    effect_flags: EffectFlags
    name: str
    ships: list[PlayerShip]
    attacks: list[Position]
    remaining_ships: int
    needs_reset: bool
    revealed_positions: list[Position]
    # 设置新的船数限制
    max_ships: Any
    sunken_ships: Any
    user_id: str
    sid: str  # 添加sid属性来存储socket会话ID

    def __init__(self, name: str, ships: list[PlayerShip], attacks: list[Position], remaining_ships: int, user_id: str = None, sid: str = None):
        self.magic_blocked = None
        self.damage_dealt_this_turn = 0
        self.magic_hand = []
        self.effect_flags = EffectFlags()
        self.name = name
        self.ships = ships
        self.sid = sid  # 初始化sid属性
        self.attacks = attacks
        self.remaining_ships = remaining_ships
        self.needs_reset = False
        self.revealed_positions = []
        self.max_ships = None
        self.user_id = user_id
        self.sunken_ships = []  # 被击沉的船，用于死者苏生/疗愈等效果


class GameRoom:
    id: str
    players: dict[str, Player]
    state: str
    rps_choices: dict[str, str]
    attack_order: list[str]
    current_attacker: str
    attacks_remaining: int
    round: int
    winner: str
    field_magic: str
    magic_history: list[dict[str, Any]]  # 无写入
    game_effects: dict[str, Any]
    current_phase: str
    magic_temp_data: dict[str, Any]
    magic_discard: list[MagicCard]
    magic_deck: list[MagicCard]
    chain: list[dict[str, Any]]
    chain_waiting: bool
    chain_timer: float
    chain_window: str | None
    chain_passes: int
    last_attack: Any
    def __init__(self, room_id):
        self.id = room_id
        self.created_at = time.time()  # 用于回收「建了但一直没人入座」的房间
        self.players = {}
        self.state = 'waiting'  # waiting, placing_ships, rock_paper_scissors, attacking, game_over
        # 大厅可见性（2026-09-18 大厅批）：**新增房间级状态三件齐** ——
        #   ① 这里初始化 ② 消费点 = _lobby_visible_rooms() + handle_create_room 的写入
        #   ③ 回归测试 tests/test_lobby.py::test_room_defaults_are_lobby_safe
        # 默认 public=True 是有意的：大厅要能列出等待中的房间，默认私密等于这个功能不存在。
        self.name = ''       # 房间名（空 = 前端回落成"{房主名}的房间"）
        self.public = True   # False = 私密房，只认 6 位房间号，不出现在大厅列表
        self.rps_choices = {}
        self.attack_order = []
        self.current_attacker = ""
        self.attacks_remaining = 0
        self.round = 1
        self.winner = ""
        # 排位房标记（2026-09-17 排位批）：只有**匹配成功**的房才可能为 True，
        # 自定义房 / 人机房恒 False。唯一消费点是结算里的段位加减分
        # （`_settle_ranked_match`：`room.ranked and count_stats and 有开打时间`）
        # 与下发（`game_state` / `_build_room_sync` 的 `ranked` / `mode`）。
        # ⚠️ 必须在这里初始化（第 2 批的硬规矩：新增房间级状态要
        #   ① __init__ 初始化 ② 明确消费点 ③ 回归测试）—— 漏了就会在别处 AttributeError。
        self.ranked = False
        # 魔法卡相关状态
        self.field_magic = None  # 场地区域（存卡牌实例，空=None）
        self.magic_history = []  # 魔法卡使用历史
        self.game_effects = {}  # 游戏效果跟踪
        self.current_phase = 'preparation'  # 当前阶段
        self.magic_temp_data = {}  # 魔法卡临时数据
        self.field_magic_owner = None  # 当前场地魔法的施放者（用于归属判断）
        self.magic_discard = []  # 全局弃牌堆（所有玩家使用过的魔法卡）
        self.magic_deck = []  # 全局共享魔法卡堆
        # 连锁相关状态
        self.chain = []  # 连锁栈
        self.chain_waiting = False  # 是否有待响应的连锁窗口
        self.chain_timer = -1  # 连锁回应计时器（代际令牌）
        self.chain_window = None  # 当前响应窗口归属的玩家
        self.chain_passes = 0  # 连续放弃次数（达 2 即结算）
        self.last_attack = None  # 记录最后一次攻击的信息
        self.game_logs: list[dict[str, Any]] = []
        self.rps_processed = False  # 记录猜拳结果是否已经处理过
        self.skip_opponent_turn = None  # Freezing!：跳过对方本回合 → **直接进新大回合**
        self.skip_next_turn = None  # 用于跳过下一个玩家回合
        # ★ 2026-09-20 新增：神之宣告效果二「跳过这一个大回合内对方的所有阶段」。
        # 与 `skip_opponent_turn` **故意分开**（两者作用域不同）：
        #   · skip_opponent_turn    —— Freezing！，跳过对方后**翻页**（重新猜拳+发牌）
        #   · skip_opponent_stages  —— 神之宣告，只跳过对方在本大回合内的阶段，**不翻页**
        # 混用一个标记会让神之宣告白拿 Freezing 的翻页副作用（作者实测报的就是这个）。
        self.skip_opponent_stages = None
        # 回光返照：施法者正在重摆棋盘（布船完成后的收尾走"重开新大回合 + 重新猜拳"）
        self.huiguang_awaiting_placement = False
        # ★ 2026-09-20 新增：**待点选的战舰队列**（选船类效果的优先级仲裁）。
        #
        # 每项：`{'player': pid, 'reason': str, 'message': str, 'priority': int, 'seq': int}`
        #
        # 为什么不是单槽（旧实现是 `magic_temp_data['pending_sacrifice']` 一个 dict）：
        #   ① 单槽会被**第二个请求直接覆盖** —— 恶魔契约刚让 A 选船，A 又打出克苏鲁之眼
        #      让 B 选，A 再点船就变成"当前没有待牺牲的战舰"（作者实测报的 bug）；
        #   ② `magic_temp_data` 有 8 处被**整体覆写**成 `{}`，待选放在里面，
        #      等待期间打出别的卡就会把待选静默抹掉。
        # 队列放在房间级字段上，两个问题一起解决。
        # ⚠️ 按 CLAUDE.md 第 11 条「新增房间级状态三件齐」：这里是 __init__ 初始化，
        #    消费点见 `_consume_ship_pick`，回归用例见 `tests/test_ship_pick_priority.py`。
        self.pending_ship_picks: list[dict[str, Any]] = []
        self.ship_pick_seq = 0        # 单调递增序号：同优先级先到先得，且顺序确定可测
        # 命运骰子摇到 3 时的「双方各弃一张」待办（按 CLAUDE.md 第 11 条三件齐）。
        # 结构：{player_id: True/False}，True=已弃/无需弃，False=等待玩家选择。
        # 消费点：handle_dice_discard_choose / _start_dice_discard / _check_dice_discard_complete。
        # 不放 magic_temp_data：它有 8 处被整体覆写 = {}，等待期间打出别的卡就抹掉。
        self.pending_dice_discard: dict[str, bool] = {}
        # 掉线/重连（2026-09-07 新增）
        self.disconnected = {}        # player_id -> {'deadline': float, 'token': int}（宽限期内）
        self.disconnect_seq = 0       # 掉线计时器代际令牌
        self.reconnect_tokens = {}    # player_id -> 一次性重连 token
        self.game_over_reason = None  # None | 'opponent_disconnected'

        # ── 阶段转换的「优先权询问」 ──────────────────────────────────
        # 速阶3卡牌"任何时候都能使用"，于是双方会在阶段推进这类操作上抢时点：
        # 我推进阶段的同时对方出牌，谁先谁后没有定义（实测确认）。
        # 参照游戏王 YGO 的优先权确认：推进阶段前先问对方"要不要响应一下"。
        # 与连锁窗口（chain_*）是两套独立状态 —— 连锁窗口优先，询问期间不开
        # 新的连锁窗口，避免双重弹窗。
        self.priority_pending = None   # {'actor','responder','action','countdown'} 或 None
        self.priority_token = 0        # 代际令牌：旧定时器自动作废，防双重结算
        # 响应者在窗口里打出了速阶3 → 连锁结算完后要"续做"的那个阶段转换。
        # {'actor','action'} 或 None。⚠️ 必须在这里初始化：此前只在
        # _resolve_priority 里现赋，未打出卡时该属性不存在，任何
        # getattr/直读都可能踩 AttributeError。
        self.priority_continue = None
        # 拒绝开关：player_id -> bool。为 True 时不再向他弹这类询问
        # （作者要求做成可随时切回的开关，不是一次性按钮）。
        self.decline_priority = {}

        # ── 局内快捷语（第 4 批）───────────────────────────────────────
        # 频率状态住【房间级】，不能放模块级全局：否则 A 房间里连点会把
        # B 房间里另一个人的额度一起吃光（两个房间共用一个计数器）。
        # key 一律是 player_id：
        #   quick_chat_recent: player_id -> [发送时间戳…]（升序，只留窗口内的）
        #   quick_chat_last:   player_id -> {'id': msg_id, 'ts': 时间戳}
        # 唯一的消费点是 handle_quick_chat()（读写都只在那里）。
        # ⚠️ 必须在这里初始化 —— 漏了就会在第一个真人身上 AttributeError
        #    （第 2 批的硬规矩：新增房间级状态要 ① __init__ 初始化
        #     ② 有明确消费点 ③ 有回归测试）。
        self.quick_chat_recent: dict[str, list[float]] = {}
        self.quick_chat_last: dict[str, dict[str, Any]] = {}

    def init_player_magic(self, player_id: str, magic_cards):
        """初始化玩家魔法卡相关状态"""
        # 初始化玩家的魔法卡状态
        self.players[player_id].magic_hand = []  # 初始手牌为空

        # 仅在第一次调用时初始化全局共享魔法卡堆
        if not self.magic_deck:
            # 复制并洗牌创建全局共享卡堆。
            # 剔除 HIDDEN_CARD_NAMES（暂时隐藏的卡）：牌堆里没有 ⇒ 谁也摸不到，
            # 而卡池、结算分支、前端文案都不动。
            self.magic_deck = [c for c in magic_cards if c.name not in HIDDEN_CARD_NAMES]
            random.shuffle(self.magic_deck)

    def draw_card(self, player_id: str):
        """抽卡逻辑，返回抽到的卡牌，使用全局共享卡堆"""
        # 检查是否有禁止抽卡效果
        effect_flags = self.players[player_id].effect_flags
        if effect_flags.no_draw:
            return None

        # 牌堆为空，无法抽卡
        if not self.magic_deck:
            return None

        # 从全局共享牌堆顶部抽一张卡
        card = self.magic_deck.pop(0)

        # 检查手牌中是否已有相同卡牌（除了"失灵！"）
        if card.name != '失灵！' and any(c.name == card.name and c.speed == card.speed for c in
                                        self.players[player_id].magic_hand):
            # 避免重复卡牌，放入弃牌堆
            self.discard_card(player_id, card)
            return None

        # 将卡牌加入手牌
        self.players[player_id].magic_hand.append(card)
        # 通知客户端手牌更新
        player = self.players[player_id]
        emit('hand_updated', {
            'hand': player.magic_hand
        }, room=player.sid)

        return card  # 返回抽到的卡牌

    def discard_card(self, player_id: str, card: MagicCard):
        """将卡牌放入弃牌堆；若它仍在手牌中，一并移出手牌。

        注意：MagicCard 没有 __eq__，原先用 list.index(card) 在"牌堆抽出的同名牌"
        场景下必然抛 ValueError（把整条攻击/魔法结算打断）。这里改为按对象身份匹配，
        找不到就只进弃牌堆，不再抛异常。
        """
        hand = self.players[player_id].magic_hand
        removed = False
        for i, c in enumerate(hand):
            if c is card:
                hand.pop(i)
                removed = True
                break
        self.magic_discard.append(card)
        return removed
    
# 添加魔法卡牌数据定义（与客户端 magic_cards.js 保持一致）
magic_cards = list(map(lambda x: MagicCard(**x), read_json('./static/magic_card.json')))

# 暂时隐藏的魔法卡：**不进牌堆**，因此谁也摸不到（只对新开的对局生效）。
# 收口点唯一：能进手牌的路径只有 init_player_magic 建的这个共享牌堆
# （draw_card / 桃园结义候选牌都从它 pop；其余 append 都在 @_test_event 里）。
# 卡牌数据、apply_magic_effect 分支、前端文案、帮助里的图鉴全部保留 ——
# 复原方法：把卡名从这个集合里删掉（集合留空亦可），无需改动其它文件。
# 设计稿：docs/superpowers/specs/2026-09-16-hide-gangjintiegu-design.md
HIDDEN_CARD_NAMES = {'钢筋铁骨'}

# CORS：默认只放行本地开发地址；生产用环境变量 CORS_ORIGINS 指定域名（逗号分隔）。
_cors_origins = [
    o.strip()
    for o in os.environ.get(
        'CORS_ORIGINS',
        'http://localhost:5000,http://127.0.0.1:5000',
    ).split(',')
    if o.strip()
]
socketio = SocketIO(app, cors_allowed_origins=_cors_origins)

# 聊天消息最大长度
MAX_CHAT_MSG_LEN = 100

# ---------------------------------------------------------------------------
# 大厅系统（Lobby）—— 2026-09-18。冻结契约见 docs/LOBBY_2026_09_18.md。
# ---------------------------------------------------------------------------
# 改这里必须同步：docs/LOBBY_2026_09_18.md / tests/test_lobby.py / tools/lobby_check.mjs。
LOBBY_ROOM = '__lobby__'          # socket.io 房间名（房间 id 是 uuid4()[:6] 十六进制，撞不上）
LOBBY_CHAT_MAX_LEN = 120          # 大厅公屏单条上限（服务端截断，不报错）
LOBBY_CHAT_MIN_INTERVAL = 1.0     # 同一连接两条之间的最小间隔（秒），防刷
LOBBY_CHAT_BACKLOG = 30           # 新进大厅者补发的最近消息条数
LOBBY_MAX_PLAYERS = 200           # lobby_state.players 上限
LOBBY_STATE_TICK_SECONDS = 4.0    # 兜底定时广播间隔（只在有成员时才真的 emit）
LOBBY_PROFILE_TTL = 60.0          # 头像/称号缓存时长，避免每次广播都查库
LOBBY_NAME_MAX_LEN = 24           # 玩家名在大厅里的显示上限
LOBBY_ROOM_NAME_MAX_LEN = 20      # 大厅建房时的房间名上限

# ---------------------------------------------------------------------------
# 匹配模式（2026-09-17 排位批）
# ---------------------------------------------------------------------------
# 排位 / 休闲是**同一个队列**里的两种 mode：入队时记在队列条目上，配对时只在
# 同 mode 之间配（ranked 只能配到 ranked）。非法值一律当休闲，绝不因为前端多传
# 一个字段就把游客塞进排位池。
MATCH_MODE_CASUAL = 'casual'
MATCH_MODE_RANKED = 'ranked'
MATCH_MODES = (MATCH_MODE_CASUAL, MATCH_MODE_RANKED)


def _normalize_match_mode(value) -> str:
    """把前端传来的 `mode` 归一化：**只认逐字的 'ranked'**，其余（None / 非法 / 大小写混写）一律 'casual'。

    刻意不做大小写宽容：`mode` 是入排位池的开关，宁可把写错的值当休闲
    （游客误入排位池 = 排位局里坐着两个写不进库的账号），也不要猜前端想说什么。
    """
    return MATCH_MODE_RANKED if value == MATCH_MODE_RANKED else MATCH_MODE_CASUAL


def _room_match_mode(room) -> str:
    """房间当前的模式（`ranked` 是唯一真相源，mode 由它推出来，不另存一份）。"""
    return MATCH_MODE_RANKED if bool(getattr(room, 'ranked', False)) else MATCH_MODE_CASUAL


def _rank_payload(room) -> dict:
    """`game_state` 系列 payload 里的段位字段（`ranked` + `mode`）。

    重连快照（`_build_room_sync`）用的是同一份口径 —— 重连后前端不知道自己在打排位，
    结算表现就会错（打了排位却按休闲渲染）。
    """
    ranked = bool(getattr(room, 'ranked', False))
    return {'ranked': ranked, 'mode': MATCH_MODE_RANKED if ranked else MATCH_MODE_CASUAL}


class RoomManager:
    def __init__(self):
        # 游戏房间数据结构
        self.rooms: dict[str, GameRoom] = {}
        # 匹配队列：单结构列表，避免"三列平行数组"在并发下错位。
        # 每项形如 {'sid': str, 'name': str, 'user_id': str | None, 'mode': str}
        # ⚠️ `mode` 是 2026-09-17 排位批新增的第 4 个字段（'casual' / 'ranked'），
        #    **只在同 mode 之间配对**。所有使用点：入队 / 出队 / 去重 / 取消 /
        #    配对扫描（add_to_match_queue / remove_from_match_queue /
        #    has_player_in_match_queue / handle_find_match / handle_disconnect /
        #    handle_cancel_match）—— 改成平行数组的话漏一处就是错位。
        self.match_queue: list[dict] = []
        # 保护 rooms / match_queue 的读写（eventlet 下 threading 已被 monkey_patch）
        self._lock = threading.RLock()

    # 房间管理方法
    def create_room(self, room_id: str = None) -> str:
        """创建新房间，返回房间ID"""
        if not room_id:
            room_id = str(uuid.uuid4())[:6]
        room = GameRoom(room_id)
        # 自定义房（create_room / join_room）**恒为休闲局**：双方可以互相刷分，
        # 所以排位标记只可能由匹配流程（handle_find_match）置 True。
        room.ranked = False
        with self._lock:
            self.rooms[room_id] = room
        return room_id

    def create_ai_room(self, player_id: str, player_name: str, player_user_id=None,
                         difficulty: str = 'normal') -> str:
        """创建人机对战房间：预置AI玩家，真人随后 join_room 走正常双人开局流程"""
        room_id = str(uuid.uuid4())[:6]
        room = GameRoom(room_id)
        room.is_ai_room = True
        # 人机局不给段位分（打电脑不能刷段位，与"人机不计 users.wins / 不发徽章"同一口径）。
        room.ranked = False
        room.ai_difficulty = difficulty if difficulty in AI_DIFFICULTIES else 'normal'
        with self._lock:
            self.rooms[room_id] = room
        ai_id = 'ai-' + room_id
        room.players[ai_id] = Player(name='AI', ships=[], attacks=[], remaining_ships=0, user_id=None, sid=ai_id)
        room.init_player_magic(ai_id, magic_cards)
        return room_id

    def join_room(self, room_id: str, player_id: str, player_name: str, sid: str) -> bool:
        """玩家加入房间，返回是否成功"""
        with self._lock:
            if room_id not in self.rooms:
                return False

            room = self.rooms[room_id]
            if len(room.players) >= 2:
                return False

            # 自定义房恒为休闲局（排位房只由匹配流程直接建，不走这里）。
            room.ranked = False
            room.players[player_id] = Player(**{
                'name': player_name,
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': player_id,
                'sid': sid
            })
        return True

    def get_room(self, room_id: str) -> GameRoom | None:
        """获取房间对象"""
        return self.rooms.get(room_id)

    def delete_room(self, room_id: str) -> bool:
        """删除房间，返回是否成功"""
        with self._lock:
            if room_id in self.rooms:
                del self.rooms[room_id]
                return True
        return False

    def get_all_rooms(self) -> dict[str, GameRoom]:
        """获取所有房间"""
        return self.rooms

    # 匹配功能方法
    def add_to_match_queue(self, player_id: str, player_name: str, user_id: str = None,
                           mode: str = MATCH_MODE_CASUAL, ip: str = '') -> bool:
        """添加玩家到匹配队列，返回是否成功。

        `mode` 是**队列条目上的第四个字段**（2026-09-17 排位批）。队列本身仍是
        「单结构列表」（每项一个 dict，见 `match_queue` 的注释）—— 早年那版
        **三列平行数组** `[sids, names, user_ids]` 已被 2026-09-11 的有序性修复
        取代，因为"平行数组漏改一个就是错位"（把 A 的 mode 配给 B）。
        所以这里扩的是 dict 的键，不是列表的列；口径不变、错位风险更小。

        `ip` / `enqueued_at`（2026-09-20 匹配规避批）同样是**新增的键**：
        `ip` 用于同 IP 规避；`enqueued_at` 用于"等得久的人优先配上"。
        ⚠️ `ip` 只放在内存里，**不落库**（隐私决策，见 `_dirty_ips` 的说明）。
        """
        mode = _normalize_match_mode(mode)
        with self._lock:
            if any(e['sid'] == player_id for e in self.match_queue):
                return False
            self.match_queue.append({'sid': player_id, 'name': player_name,
                                     'user_id': user_id, 'mode': mode,
                                     'ip': ip or '',
                                     'enqueued_at': time.time()})
        return True

    def remove_from_match_queue(self, player_id: str) -> bool:
        """从匹配队列移除玩家，返回是否成功"""
        with self._lock:
            for i, entry in enumerate(self.match_queue):
                if entry['sid'] == player_id:
                    self.match_queue.pop(i)
                    return True
        return False

    def has_player_in_match_queue(self, player_id: str) -> bool:
        """检查玩家是否在匹配队列中"""
        return any(e['sid'] == player_id for e in self.match_queue)

    def get_match_queue_size(self) -> int:
        """获取匹配队列大小"""
        return len(self.match_queue)


# 创建RoomManager实例
room_manager = RoomManager()


# ---------------------------------------------------------------------------
# 大厅（Lobby）—— 2026-09-18。冻结契约见 docs/LOBBY_2026_09_18.md。
# ---------------------------------------------------------------------------
# 改造前的现状：`#lobby-screen` 是个空壳（列不出人、看不到房间、没有公屏），
# 且`online_users` 是个**裸 sid 集合**，连名字都没有。这里把它整个换掉。
#
# 两个结构，职责不同、不许混：
#   _presence  —— 在线表（= 在线人数口径）。连接建立即入表，断开即出表。
#   _members   —— 大厅成员（_presence 的**子集**）。只有真的站在大厅页面上的
#                 连接才收 lobby_state 推送；否则每个对局中的玩家都被大厅广播打扰。
def _lobby_clean_name(name, fallback: str = '游客') -> str:
    """玩家名的统一清洗：去首尾空白 → 截断 → 空串回落。

    ⚠️ 大厅的名字有三个来源（session / find_match 的 payload / 大厅订阅的 payload），
    必须在**入口处**统一，不能各写各的截断长度。
    """
    text = str(name or '').strip()
    if not text:
        return fallback
    return text[:LOBBY_NAME_MAX_LEN]


class LobbyManager:
    """大厅状态：在线表 + 成员表 + 公屏聊天。

    所有读写都持同一把锁（eventlet 下 threading 已被 monkey_patch，锁是绿的）。
    """

    def __init__(self):
        self._lock = threading.RLock()
        # sid -> {'name','user_id','connected_at','profile','profile_at'}
        self._presence: dict[str, dict] = {}
        # sid -> {'name','joined_at'}（presence 的子集）
        self._members: dict[str, dict] = {}
        # 公屏最近消息（只保留 LOBBY_CHAT_BACKLOG 条）
        self._chat: list[dict] = []
        # 单调序号：前端靠它做"这条我有没有"的判断。没有它就只能靠文案/时间猜，
        # 而补发的历史与实时推送**会重叠**（见 applyLobbyChatHistory 的注释）。
        self._chat_seq = 0
        # sid -> 上一条发言时间（防刷）
        self._last_chat_at: dict[str, float] = {}

    # ---- 在线表 -----------------------------------------------------------
    def add_connection(self, sid: str, name=None, user_id=None) -> None:
        """连接建立时登记。名字可能还不知道（游客在首页才输入），后面再补。"""
        with self._lock:
            row = self._presence.get(sid)
            if row is None:
                row = {'name': '', 'user_id': None, 'connected_at': time.time(),
                       'profile': None, 'profile_at': 0.0}
                self._presence[sid] = row
            if name:
                row['name'] = _lobby_clean_name(name)
            if user_id is not None:
                row['user_id'] = user_id

    def update_identity(self, sid: str, name=None, user_id=None) -> None:
        """补写身份（游客名 / 登录态）。连接不在表里时自动补登。"""
        if sid not in self._presence:
            self.add_connection(sid, name, user_id)
            return
        with self._lock:
            row = self._presence[sid]
            if name:
                row['name'] = _lobby_clean_name(name)
            if user_id is not None:
                row['user_id'] = user_id

    def remove_connection(self, sid: str) -> bool:
        """连接断开：同时退出在线表、成员表与防刷记录。"""
        with self._lock:
            existed = self._presence.pop(sid, None) is not None
            self._members.pop(sid, None)
            self._last_chat_at.pop(sid, None)
        return existed

    def online_count(self) -> int:
        with self._lock:
            return len(self._presence)

    def presence(self) -> dict:
        """在线表快照（浅拷贝，供 build_lobby_state 遍历用）。"""
        with self._lock:
            return {sid: dict(row) for sid, row in self._presence.items()}

    def profile_of(self, sid: str) -> dict:
        """取该连接的头像 / 称号缓存；过期或缺失时查库并回写（TTL = LOBBY_PROFILE_TTL）。

        ⚠️ 必须缓存：`lobby_state` 每 4 秒兜底广播一次，逐人查库等于每秒几十次查询。
        游客（没有 user_id）直接返回空缓存，不查库。
        """
        now = time.time()
        with self._lock:
            row = self._presence.get(sid)
            if row is None:
                return {'avatar': '', 'title': '', 'name_style': ''}
            cached = row.get('profile')
            if cached is not None and now - float(row.get('profile_at') or 0) < LOBBY_PROFILE_TTL:
                return dict(cached)
            uid = row.get('user_id')
        profile = _lobby_lookup_profile(uid)
        with self._lock:
            row = self._presence.get(sid)
            if row is not None:
                row['profile'] = profile
                row['profile_at'] = now
        return dict(profile)

    # ---- 大厅成员 ---------------------------------------------------------
    def subscribe(self, sid: str, name=None, user_id=None) -> bool:
        """进入大厅。幂等：重复调用只刷新名字，不重复入表。"""
        self.update_identity(sid, name, user_id)
        with self._lock:
            if sid in self._members:
                if name:
                    self._members[sid]['name'] = _lobby_clean_name(name)
                return False
            self._members[sid] = {'name': _lobby_clean_name(name), 'joined_at': time.time()}
        return True

    def unsubscribe(self, sid: str) -> bool:
        with self._lock:
            return self._members.pop(sid, None) is not None

    def is_member(self, sid: str) -> bool:
        with self._lock:
            return sid in self._members

    def member_count(self) -> int:
        with self._lock:
            return len(self._members)

    def members(self) -> list[str]:
        with self._lock:
            return list(self._members.keys())

    # ---- 公屏聊天 ---------------------------------------------------------
    def chat_allowed(self, sid: str, now: float = None) -> bool:
        """频率闸门：同一连接两条之间至少间隔 LOBBY_CHAT_MIN_INTERVAL 秒。"""
        now = time.time() if now is None else now
        with self._lock:
            last = self._last_chat_at.get(sid)
            if last is not None and now - last < LOBBY_CHAT_MIN_INTERVAL:
                return False
            self._last_chat_at[sid] = now
        return True

    def add_chat(self, sid: str, name: str, message: str) -> dict | None:
        """入库一条公屏消息。空白消息返回 None（调用方据此静默丢弃）。"""
        text = str(message or '').strip()[:LOBBY_CHAT_MAX_LEN]
        if not text:
            return None
        with self._lock:
            self._chat_seq += 1
            item = {'key': sid, 'name': _lobby_clean_name(name),
                    'message': text, 'ts': time.time(), 'seq': self._chat_seq}
            self._chat.append(item)
            if len(self._chat) > LOBBY_CHAT_BACKLOG:
                del self._chat[:len(self._chat) - LOBBY_CHAT_BACKLOG]
        return item

    def recent_chat(self) -> list[dict]:
        with self._lock:
            return [dict(m) for m in self._chat]


lobby_manager = LobbyManager()


def _lobby_lookup_profile(uid) -> dict:
    """查一个账号在大厅里要展示的外观字段（头像 / 称号 / 名字样式）。

    只读公开外观，**不碰任何隐私开关字段**（show_stats / show_guestbook 等）——
    大厅不是名片，不下发名片隐私数据。
    """
    blank = {'avatar': '', 'title': '', 'name_style': ''}
    if not uid:
        return blank
    uid = str(uid)
    try:
        user = db.get_user(uid=uid) or {}
        extra = db.get_user_profile_extra(uid) or {}
        perks = db.get_perks_map([uid]).get(uid) or set()
        title_id = str(extra.get('title_id') or '')
        return {
            'avatar': str(user.get('avatar') or ''),
            'title': profile_spec.title_name(title_id) if title_id else '',
            'name_style': 'rainbow' if profile_spec.PERK_RAINBOW_NAME in perks else '',
        }
    except Exception:
        return blank


def _lobby_sids_by_room_state() -> tuple:
    """一次遍历算出两拨人：真正在打的（in_game）与只是在房里等人的（in_room）。

    ⚠️ **必须区分这两拨**：建房者一按下「创建房间」就坐在自己的房里了，
    而那个房间的 state 是 'waiting' —— 把它算成"对局中"的话，大厅里所有
    开过房的人永远显示"对局中"，而他们其实完全可以被别人拉进一局。
    （浏览器工具实测抓到的：A 建房后在自己那一行显示"对局中"。）
    """
    in_game, in_room = set(), set()
    for room in room_manager.get_all_rooms().values():
        state = getattr(room, 'state', None)
        if state == 'game_over':
            continue
        bucket = in_room if state == 'waiting' else in_game
        for player in room.players.values():
            if player.sid:
                bucket.add(player.sid)
    return in_game, in_room


def _lobby_player_status(sid: str, in_game: set, in_room: set) -> str:
    """大厅里的四态之一：matching / in_game / in_room / idle。

    ⚠️ 顺序不能反：匹配中**优先于**对局中。匹配成功后队列条目立刻被 pop，
    两者不会同时成立；但先判对局会让"刚配到、还没进房"的一瞬显示成空闲。
    """
    if room_manager.has_player_in_match_queue(sid):
        return 'matching'
    if sid in in_game:
        return 'in_game'
    if sid in in_room:
        return 'in_room'
    return 'idle'


def _recycle_host_waiting_rooms(player_id: str) -> list:
    """回收该玩家**之前主持的、还没人入座**的等待房，返回被回收的 room_id 列表。

    ★ 为什么必须有它（2026-09-18 大厅批上线后实测的缺陷）：
    作者截图里大厅房间列表挂着 **7 间一模一样的房**（同名、同房主、都是 1/2）。
    复现确认「一次点击 = 一间房」（ack 正常、界面也正常跳到自定义房界面），
    所以不是双击/重复绑定 —— 是**玩家每回大厅点一次「创建房间」就多一间，而旧房
    永远不会消失**：

      · 等待房的回收 TTL 是 1 小时（`_WAITING_ROOM_TTL`）；
      · 大厅的可见规则只要求「房主仍在线」，而房主就是他自己 —— 当然一直在线上。

    于是两条规则各自都"没错"，合起来却把 7 间房全留在了榜上。
    规则改成：**一个玩家同时最多主持一间等待中的房**，再次建房 = 换一间。
    （只回收 `waiting` 且房内恰好 1 人、且那个人就是自己的房 —— 已经开打的、
    或者已经有人入座的房一律不碰。）
    """
    reaped = []
    for room_id, room in list(room_manager.get_all_rooms().items()):
        if getattr(room, 'state', None) != 'waiting':
            continue
        entries = list(room.players.items())
        if len(entries) != 1 or entries[0][0] != player_id:
            continue
        _drop_room(room_id, '建房时回收自己上一间等待房')
        reaped.append(room_id)
    return reaped


def _lobby_visible_rooms() -> list[dict]:
    """大厅房间列表。可见规则见 docs/LOBBY_2026_09_18.md §1.4。

    最容易被漏掉的是第 4 条「房主仍在线」：房间的回收 TTL 是 1 小时
    （_WAITING_ROOM_TTL），房主关掉标签页后房间还要在内存里躺一小时 ——
    不加这条就会在大厅里挂出一堆"点进去没人"的僵尸房。

    第 5 条（**同一房主只列最新的一间**）是防御性的：正常路径下
    `_recycle_host_waiting_rooms` 已经保证一个玩家只有一间等待房，但历史遗留
    （本批上线前建的房）、或者日后新增的建房路径都可能绕过它 —— 列表层再兜一次，
    大厅就永远不会出现"同一个人的一串同名房"。
    """
    online = set(lobby_manager.presence().keys())
    rows = []
    seen_hosts = set()
    # 按建房时间**倒序**扫：同一房主先命中的就是最新的那一间
    ordered = sorted(room_manager.get_all_rooms().values(),
                     key=lambda r: getattr(r, 'created_at', 0) or 0, reverse=True)
    for room in ordered:
        if getattr(room, 'state', None) != 'waiting':
            continue
        if getattr(room, 'is_ai_room', False):
            continue
        if not bool(getattr(room, 'public', True)):
            continue
        entries = list(room.players.items())
        if len(entries) != 1:
            continue
        host_key, host = entries[0]
        if not host.sid or host.sid not in online:
            continue
        if host_key in seen_hosts:
            continue          # 同一房主的第二间（见上面的第 5 条）
        seen_hosts.add(host_key)
        rows.append({
            'room_id': room.id,
            'name': str(getattr(room, 'name', '') or '') or f'{host.name}的房间',
            'host': host.name,
            'players': 1,
            'capacity': 2,
            'created_at': int(getattr(room, 'created_at', 0) or 0),
        })
    rows.sort(key=lambda r: r['created_at'])
    return rows


def build_lobby_state() -> dict:
    """组装一份 lobby_state（契约见 docs/LOBBY_2026_09_18.md §1.3）。

    每次广播现算：房间/队列/在线都在内存里，只有等级与段位要查库，且都是
    **批量**接口（一次 IN (...) 取完），绝不逐人查。
    """
    now = time.time()
    presence = lobby_manager.presence()
    members = set(lobby_manager.members())
    in_game, in_room = _lobby_sids_by_room_state()

    # 队列分 mode 计数（休闲 / 排位共用同一个队列）
    queue = list(room_manager.match_queue)
    ranked_n = sum(1 for e in queue if e.get('mode') == MATCH_MODE_RANKED)
    casual_n = len(queue) - ranked_n

    # 按连接时间排序，超出上限直接截断（契约 §5：本批不做分页）
    ordered = sorted(presence.items(), key=lambda kv: kv[1].get('connected_at') or 0)
    ordered = ordered[:LOBBY_MAX_PLAYERS]

    uids = [str(row.get('user_id')) for _, row in ordered if row.get('user_id')]
    try:
        xp_map = db.get_xp_map(uids) if uids else {}
    except Exception:
        xp_map = {}
    try:
        rank_map = db.get_rank_map(uids) if uids else {}
    except Exception:
        rank_map = {}

    players = []
    for sid, row in ordered:
        uid = row.get('user_id')
        uid_s = str(uid) if uid else ''
        profile = lobby_manager.profile_of(sid)
        level = 1
        if uid_s:
            try:
                level = leveling.level_from_xp(int(xp_map.get(uid_s, 0) or 0))
            except Exception:
                level = 1
        rank = None
        points_row = rank_map.get(uid_s) if uid_s else None
        if points_row is not None:
            try:
                points = points_row.get('points') if isinstance(points_row, dict) else points_row
                view = ranks.rank_view(points)
                rank = {'tier_id': view['tier_id'], 'tier_name': view['tier_name'],
                        'label': view['label']}
            except Exception:
                rank = None
        players.append({
            'key': sid,
            'name': row.get('name') or '游客',
            'guest': not bool(uid_s),
            'in_lobby': sid in members,
            'status': _lobby_player_status(sid, in_game, in_room),
            'avatar': profile.get('avatar') or '',
            'level': level,
            'name_style': profile.get('name_style') or '',
            'title': profile.get('title') or '',
            'rank': rank,
        })

    return {
        'ts': int(now),
        'online_count': len(presence),
        'lobby_count': len(members),
        'queue': {'casual': casual_n, 'ranked': ranked_n},
        'players': players,
        'rooms': _lobby_visible_rooms(),
    }


def _broadcast_lobby_state() -> dict:
    """给所有大厅成员推一份状态。没有成员时**不 emit**（省掉无意义的序列化）。"""
    if lobby_manager.member_count() <= 0:
        return {'sent': 0}
    state = build_lobby_state()
    socketio.emit('lobby_state', state, to=LOBBY_ROOM)
    return {'sent': lobby_manager.member_count(), 'state': state}


def _lobby_broadcast_soon() -> None:
    """在**后台任务**里补一次广播。

    ⚠️ `disconnect` 处理器里不能同步 emit（eventlet 会把 hub 卡住，
    见 CLAUDE.md §9 与 handle_disconnect 里的注释），所以断开路径走这里。
    """
    try:
        socketio.start_background_task(_lobby_broadcast_task)
    except Exception:
        pass


def _lobby_broadcast_task():
    try:
        _broadcast_lobby_state()
    except Exception:
        pass


_LOBBY_TICKER_STARTED = False


def _lobby_ticker_loop():
    """兜底定时广播：只在有成员时真的 emit。

    为什么需要它：广播点是**逐个 hook 上去的**（订阅/匹配/建房/掉线…），
    漏掉任何一条路径，玩家就会看到一份停住不动的列表 —— 而这类"没报错、
    只是不动"的故障是本项目最难查的一类（见 CLAUDE.md 通用教训）。
    定时兜底把最坏情况从"永远不动"压到"最多 4 秒后自己好"。
    """
    while True:
        time.sleep(LOBBY_STATE_TICK_SECONDS)
        try:
            if lobby_manager.member_count() > 0:
                _broadcast_lobby_state()
        except Exception:
            pass


def _ensure_lobby_ticker():
    global _LOBBY_TICKER_STARTED
    if _LOBBY_TICKER_STARTED:
        return
    _LOBBY_TICKER_STARTED = True
    socketio.start_background_task(_lobby_ticker_loop)


# ===========================================================================
# 好友功能（2026-09-18 好友批）· 实时侧：在线状态 / 事件推送 / 结算钩子
# ---------------------------------------------------------------------------
# 与 `api.py`（HTTP 侧好友接口）冻结的契约：
#   · 状态全在 `presence.py`（纯内存零依赖 —— api.py 要读它，而 api.py 被本文件
#     `from api import app` 反向依赖，写在本文件里就是循环导入）；
#   · 服务端→客户端的事件只有 4 个：`friend_request` / `friend_accepted` /
#     `friend_invite` / `recent_opponent`，名字与字段冻结，前端照这份写；
#   · `api.py` 只通过下面 3 个 `push_*` 推事件，**不要在 api.py 里直接 emit**
#     （那边是 HTTP 请求上下文，没有 `request.sid`，`flask_socketio.emit` 会乱发）。
#   · 全部只在**对方在线**时发；`friend_request` / `friend_invite` 要按
#     `presence.sids_of(uid)` 发给他的**每一张标签页**。
# ===========================================================================

# 好友关系取值（`db.get_friend_relation` 的返回值 × `recent_opponent.relation`）。
# ⚠️ 只有这一份：`_friend_relation_safe` 的兜底、`recent_opponent` 的下发都用它。
#    `blocked_by_me` / `blocked_me` 前端按"不能加好友"渲染（契约里没列，但 db 会返回；
#    多一种取值不会让前端崩，少一种才会 —— 未知取值一律降级成 'none'）。
FRIEND_RELATIONS = (
    'none', 'self', 'friends', 'pending_out', 'pending_in',
    'blocked_by_me', 'blocked_me',
)


def _live_uids(room) -> list:
    """房间里**真人登录账号**的 user_id 列表（AI 与游客跳过，重复的只留一个）。

    `room.players` 的 key 有两套约定（自定义/人机房 = user_id，匹配房 = socket sid），
    所以**只认 `Player.user_id`** —— 拿 key 当 uid 会把事件发给不存在的账号
    （CLAUDE.md 第 6 节，`record_card_use` 的注释里也栽过同一形状）。
    """
    out = []
    try:
        for player in room.players.values():
            uid = getattr(player, 'user_id', None)
            # AI 的 user_id 是 None；游客的 user_id == 入座时的 sid，这里也没法区分，
            # 所以判据只要求"有非空 user_id"，更严的口径在 `_recent_opponent_payloads`
            # （双方都得有 uid 才发，游客对局自然被跳过）。
            if uid and uid not in out:
                out.append(uid)
    except Exception:
        return out
    return out


def _bind_presence_game(room) -> None:
    """有人**进入对局**时把房间里的真人标成"对局中"（幂等，重复调没副作用）。

    挂点（**"真人坐进一局"的全部入口**，之后再也没有人能进 `room.players`）：
      · `handle_create_room`（建房自己入座）
      · `handle_join_room`（加入别人的房 / 人机房入座）
      · `handle_find_match`（配对成功后）
      · `handle_create_ai_room`（人机房建房）
      · `handle_rejoin_room`（掉线重连回一局没结束的对局，把断线时摘掉的标回来）
    为什么是这个粒度而不是"开局 / 放置完成 / 进入 attacking"等更多点：那些点更多、
    更分散，而且**同一个状态会被写更多次**（本项目"同一个判断有两份实现就一定会漂移"）。
    入座是关键事实，后面阶段怎么变都不改变"他在局里"。
    """
    for uid in _live_uids(room):
        try:
            presence.set_in_game(uid, True)
        except Exception:
            continue


def _release_presence_game(room) -> None:
    """对局**结束 / 人走了**时把房间里的人标成"不在局中"（幂等）。

    两个出口：`_finalize_match`（唯一结算收口，含人机那条早退路径）与
    `handle_disconnect`（这个连接离开座位）。掉线判胜 / 房间回收那几条路不用再挂 ——
    人已经在 disconnect 那一步摘过了。
    ⚠️ 别在这里顺手 `return` 掉别的收尾（本项目同形状栽过三次）。
    """
    for uid in _live_uids(room):
        try:
            presence.set_in_game(uid, False)
        except Exception:
            continue


def _drop_my_other_waiting_rooms(player_id, keep_room_id: str) -> list:
    """把这个人**独自占着**的其它等待房清掉，返回被清掉的房号列表。

    什么时候会有这种房：邀战修好之后**发起方也会进房**（`sendFriendInvite` 里的自动入房），
    于是"我已经在自己那间等待房里，又接受了另一个人的邀请"会把我的座位留在旧房里 ——
    那间房**只有我一个人**，既不自动回收（等待房 TTL 1 小时），大厅列表里还挂着，
    而且我同时占着两间房（`handle_join_room` 本身不拦这个）。
    口径与大厅批 `_recycle_host_waiting_rooms`（一人同时只能主持一间等待房）一致，
    只是那里只管"**自己建的**房"，这里扩到"任何我独自占着的等待房"。

    ⚠️ 房里**还有别人**时一律不删（有人在等我）—— 不替玩家做决定，只在日志里说一声。
    """
    reaped = []
    for rid, room in list(room_manager.get_all_rooms().items()):
        if rid == keep_room_id or getattr(room, 'state', None) != 'waiting':
            continue
        seats = list(room.players.keys())
        if len(seats) == 1 and seats[0] == player_id:
            _drop_room(rid, '他进了另一间房，而这一间等待房里只有他自己')
            reaped.append(rid)
        elif player_id in seats:
            print(f'[room] 他同时还在等待房 {rid} 里，但那里还有别人在等 —— 不替他清')
    return reaped


def _drop_room(room_id: str, why: str) -> bool:
    """删一间房，并把房里**还连着的真人**从「对局中」摘出来（幂等）。

    ⚠️ 为什么要收成一个口（2026-09-19 双浏览器实测踩到）：
    `_release_presence_game` 原来只在**结算**（`_finalize_match`）与**掉线**
    （`handle_disconnect`）两处调用，注释里那句「房间回收那几条路不用再挂 ——
    人已经在 disconnect 那一步摘过了」对**「解散房间」（`close_room`）不成立**：
    那条路上人是**连着**的、房却没了 → 他此后在好友面板里永远显示「对局中」，
    并被「局中不许邀战」那道护栏**永久拦住**（症状：解散之后再也邀不了战，只能刷新页面）。
    同形状还有两条：**对手掉线 → 对局取消**、**等待房 TTL 回收**（房主可能还连着）。

    ⚠️ 别把 `_release_presence_game` 的调用从 `_finalize_match` / `handle_disconnect`
    挪走：那两处的语义比「删房」更早（结算时房还在，房里的人要一起摘）。
    """
    room = room_manager.get_room(room_id)
    if room is not None:
        _release_presence_game(room)
    ok = room_manager.delete_room(room_id)
    print(f'[room] 删除房间 {room_id}（{why}）')
    return ok


def _friend_relation_safe(from_uid, to_uid) -> str:
    """取 `from_uid` → `to_uid` 的好友关系，**绝不外抛**。

    `db.get_friend_relation` 由好友批的另一个智能体在 `db.py` 里实现，本文件可能
    先落地（或那个 DAO 临时出错）——所以这里走 `getattr` 防御式调用，取不到就
    一律当 `'none'`。⚠️ 结算绝不能因为缺一个 DAO 就崩（`_finalize_match` 的
    第 1 批规矩就是"统计/播报失败不许把结算搞崩"）。
    """
    if not from_uid or not to_uid:
        return 'none'
    if str(from_uid) == str(to_uid):
        return 'self'
    try:
        getter = getattr(db, 'get_friend_relation', None)
        if not callable(getter):
            return 'none'
        value = getter(from_uid, to_uid)
    except Exception:
        return 'none'
    if not isinstance(value, str):
        return 'none'
    return value if value in FRIEND_RELATIONS else 'none'


def _opponent_display_name(player, uid) -> str:
    """对手在结算提示里的显示名：优先 `Player.name`（入座时的用户名），兜底查库。"""
    name = getattr(player, 'name', None)
    if name:
        return str(name)
    try:
        row = db.get_user(uid=uid) or {}
        return str(row.get('username') or uid)
    except Exception:
        return str(uid)


def _recent_opponent_payloads(winner, loser, winner_user_id, loser_user_id):
    """组装结算时要发的 `recent_opponent`：`[(uid, payload), ...]`，**一人一条**。

    只对**双方都是真人登录账号**的对局发（人机 / 游客局返回空 —— 跟"打电脑不记
    统计、不发徽章"同一口径）。`relation` 是"我 → 对手"的关系，两边各算各的，
    所以不能把一份 payload 发两次。

    ⚠️⚠️ 判据必须是"这个 uid **真的查得到账号**"，**不是"非空"**：
    自定义房里游客的 `Player.user_id` 是**入座时的 socket sid**
    （`handle_create_room` / `handle_join_room` 都写 `session.get('user_id', request.sid)`），
    非空、但根本不是账号。只判非空的话，登录玩家打完一局会在结算屏上看到一个
    **可点的「加好友」**，点下去必然 404「账号不存在」（端到端实测复现过：
    `a_recent` 里那个 `user_id` 就是 sid、`username` 是入座名"路边游客"）。
    匹配房没这个问题（`Player.user_id = session.get('user_id')`，游客恒 None），
    所以缺陷只在"登录玩家开自定义房 + 没登录的人点邀请链接进来"这条路上。
    """
    if not winner_user_id or not loser_user_id:
        return []
    try:
        if not (db.get_user(uid=winner_user_id) and db.get_user(uid=loser_user_id)):
            return []
    except Exception as e:                                          # noqa: BLE001
        # 播报失败不许把结算搞崩（`_finalize_match` 的第 1 批规矩），静默不发即可
        print(f'[friends] 结算播报查账号失败，本次不发 recent_opponent: {e}')
        return []
    try:
        w_uid, l_uid = str(winner_user_id), str(loser_user_id)
        return [
            (w_uid, {
                'user_id': l_uid,
                'username': _opponent_display_name(loser, l_uid),
                'avatar': getattr(loser, 'avatar', '') or '',
                'relation': _friend_relation_safe(w_uid, l_uid),
            }),
            (l_uid, {
                'user_id': w_uid,
                'username': _opponent_display_name(winner, w_uid),
                'avatar': getattr(winner, 'avatar', '') or '',
                'relation': _friend_relation_safe(l_uid, w_uid),
            }),
        ]
    except Exception:
        return []


def _push_friend_event(to_uid, event_name: str, payload: dict) -> bool:
    """把一条好友事件发给 `to_uid` 的**每一张在线标签页**；返回"有没有送出去"。

    三道门槛，顺序不能换：
      ① `to_uid` 非空 ② `presence.is_online(to_uid)`（**离线一律不发**，返回 False）
      ③ 逐 sid 发（`presence.sids_of`）。
    ⚠️ 用 `socketio.emit(..., room=sid)` 而**不是** `flask_socketio.emit`：后者要
    `request.sid` / 请求上下文，而这几个 push 函数是给 `api.py` 的 HTTP 请求
    调用的（以及无请求上下文的单测直调），`room=<sid>` 在两种上下文里都成立。
    """
    if not to_uid:
        return False
    try:
        if not presence.is_online(to_uid):
            return False
        sids = presence.sids_of(to_uid)
    except Exception:
        return False
    if not sids:
        return False
    delivered = False
    for sid in sids:
        if not sid:
            continue
        try:
            socketio.emit(event_name, payload, room=sid)
            delivered = True
        except Exception:
            # 单张标签页发失败不影响其余的（也不许把调用方 —— 常常是一个 HTTP 请求
            # 或者一次结算 —— 搞崩）
            continue
    return delivered


def push_friend_request(to_uid, from_uid, from_username, from_avatar) -> bool:
    """给在线的 `to_uid` 推一条好友申请（`api.py` 的申请接口调它）。

    payload 字段冻结：`from_user_id` / `from_username` / `from_avatar`。
    对方不在线 → 返回 False（**不发、不抛**；申请本身已经落库，等他上线自己看列表）。
    """
    return _push_friend_event(to_uid, 'friend_request', {
        'from_user_id': from_uid,
        'from_username': from_username,
        'from_avatar': from_avatar,
    })


def push_friend_accepted(to_uid, user_id, username, avatar) -> bool:
    """给在线的 `to_uid` 推"你发出的申请被接受了"（`api.py` 的同意接口调它）。

    这里的 `user_id` / `username` / `avatar` 是**同意方**（= 新好友）的资料。
    payload 字段冻结：`user_id` / `username` / `avatar`。
    """
    return _push_friend_event(to_uid, 'friend_accepted', {
        'user_id': user_id,
        'username': username,
        'avatar': avatar,
    })


def push_friend_invite(to_uid, room_id, from_uid, from_username) -> bool:
    """好友邀你打一局（`api.py` 的邀请接口调它）。

    payload 字段冻结：`room_id` / `from_user_id` / `from_username`。
    对方不在线 → 返回 False。⚠️ 本函数**不依赖 request 上下文**（邀请是 HTTP 接口
    发起的），所以绝不能用 `flask_socketio.emit` 那种要 `request.sid` 的写法。
    """
    return _push_friend_event(to_uid, 'friend_invite', {
        'room_id': room_id,
        'from_user_id': from_uid,
        'from_username': from_username,
    })


def push_friend_message(to_uid, message) -> bool:
    """把一条私聊推给收件人的**每一张标签页**（`api.py` 的发送接口调它）。

    契约（§4「Socket 事件」）冻结的 payload：
      `id` / `from_uid` / `from_username` / `from_avatar` / `body` / `created_at` / `stamp`

    ⚠️ 与 `push_friend_request` / `push_friend_invite` **共用同一个发车口**
    （`_push_friend_event`）：三道门槛（uid 非空 → `presence.is_online` → 逐 sid 发）
    与"多标签页每张都收到"的口径只此一份。本函数**只负责拼 payload**，
    自己再写一遍 `socketio.emit(..., room=sid)` 就是第二份实现 —— 两份必然漂移
    （本项目"推送只有一份实现"这条是硬规矩，见 `api.py` 顶部那段注释）。

    ⚠️ payload 里**带 `body` 与 `stamp`**（而不是只给一个 id 让前端回拉）：
    收件人可能正停在好友列表上、根本没打开那段会话，这时补一条
    "小红：在吗"的提示才是有用的；只给 id 的话前端什么也渲染不出来。

    ⚠️ 对方离线 → 返回 False，**不发、不抛**（消息已经落库，等他下次打开会话
    自己就拉到了）。调用方（HTTP 接口）**不许**因此回 error —— 这点与邀请不同：
    邀请必须是实时的，私聊不是。

    ⚠️ payload 的形状由 `dm.push_payload` **裁好**（唯一一份字段清单，契约 §4）。
    这里再走一次它：`api.py` 传进来的是**接口自己那份 dict**（带 `mine` / `to_uid`
    这类视角字段），多兜一道就不会因为"api 那边哪天多塞一个内部键"把收件人
    看到的东西改掉 —— 推给别人的 payload 必须只由这一处的形状决定。
    """
    body = dm.push_payload(message)
    return _push_friend_event(to_uid, 'friend_message', body)


def _identity_check(room, claimed_player_id, server_pid, sid):
    """纯身份校验（无副作用，便于单测）。房间 key 存在两种约定，两种都认：
    - 自定义房/人机房（走 join_room）：key = 登录用户的 session user_id（游客=入座 sid）
    - 匹配房：key = 入匹配队列时的 socket sid（无论是否登录，user_id 只存 Player.user_id）
    因此只要满足任一即可：
    1) 声称的 player_id == 会话 user_id（登录态，且容忍重连后 sid 变化）
    2) 该座位登记的连接 == 当前连接（key=sid 的各流程，以及登录用户同连接场景）"""
    if not room or claimed_player_id not in room.players:
        return False
    if server_pid and claimed_player_id == server_pid:
        return True
    return room.players[claimed_player_id].sid == sid


def _identity_ok(room, claimed_player_id):
    """从当前请求上下文取身份后校验，防止伪造他人 player_id 操作。
    无请求上下文（如单元测试直调 handler）时跳过连接校验，仅保留成员校验。"""
    try:
        server_pid = session.get('user_id')
    except RuntimeError:
        server_pid = None
    try:
        sid = request.sid
    except RuntimeError:
        sid = None
    if server_pid is None and sid is None:
        return room is not None and claimed_player_id in room.players
    return _identity_check(room, claimed_player_id, server_pid, sid)


def field_magic_name(room):
    """返回场地区域上的场地魔法卡名（字符串）；无场地时返回空字符串。"""
    if not room or not room.field_magic:
        return ""
    fm = room.field_magic
    return fm.name if hasattr(fm, 'name') else fm


def _clear_field_magic_effects(room, prev_field_name=None):
    """场地被顶替/拆除时，清理它留下的房间级效果标记，并纠正受影响的攻击次数。

    否则「加百列之光」拆掉恶魔契约/教皇旨意/伊甸园后，其效果仍永久生效。

    prev_field_name：刚离场的场地卡名。调用方若已经改动 room.field_magic，
    必须显式传入（见 _place_field_magic），否则这里读到的是新卡名。
    """
    had_papal = bool(room.game_effects.get('papal_edict'))
    # 未显式传入时（加百列拆场地的路径：先调这里、后清 field_magic）就地读取
    prev_field = prev_field_name if prev_field_name is not None else field_magic_name(room)
    room.game_effects.pop('demon_contract', None)
    room.game_effects.pop('papal_edict', None)

    # 攻击次数是按【当前场地规则】算出来的，场地一没，那个数就不再有效：
    #   · 教皇旨意：次数被压成 0 —— 不恢复的话玩家"有船却一次也打不出去"
    #   · 伊甸园：次数 = 6-船数 —— 不重算的话，场地被拆了还能白拿额外次数
    #     （实测：2 艘船时白拿 2 次攻击）
    #
    # ⚠️ 必须覆盖【所有相位】，不能只在 battle 里做。
    #   拆场地的守卫原先写了 current_phase == 'battle'，于是准备阶段的路径整段被跳过：
    #   准备阶段打出教皇旨意（次数归零）→ 场地被拆除 → 进战斗阶段时
    #   两个特例分支都不命中，次数停在 0 → 玩家 4 艘船零输出。
    #   （进战斗阶段的 _recalc 兜底也一并补上了，两处都要有。）
    #
    # ⚠️ 调用方的清理顺序不统一：_place_field_magic 是【先换 field_magic 再调这里】，
    #   而加百列拆场地是【先调这里再清 field_magic】。因此用 prev_field 判断，
    #   不依赖 field_magic 调用后的值 —— 否则后一种情况会按"旧场地还在"去算。
    if room.state != 'attacking':
        return
    pid = room.current_attacker
    if not pid or pid not in room.players:
        return
    # 场地没变过、且与影响攻击次数的场地无关 → 无需纠正
    if not had_papal and prev_field not in ('伊甸园', '教皇旨意'):
        return
    # ⚠️ 不能用 _recalc_attacker_attacks：它读 field_magic_name(room)，
    # 而加百列拆场地的路径是【先调这里、后清 field_magic】—— 此刻 field_magic
    # 还指向那张已离场的卡，重算结果不变，纠正等于没做（实测：伊甸园被拆后仍是 4 次）。
    # 这里显式按"那张场地已不存在"来算，只看【当前仍在场的场地】。
    stay_field = field_magic_name(room)
    if prev_field is not None and stay_field == prev_field:
        stay_field = None      # field_magic 尚未被清，说明它就是要拆掉的那张
    bonus = int(getattr(room.players[pid].effect_flags, 'subsidy_bonus', 0) or 0)
    if stay_field == '伊甸园':
        base = max(0, 6 - room.players[pid].remaining_ships)
    elif stay_field == '教皇旨意':
        base = 0
    else:
        base = max(0, room.players[pid].remaining_ships
                   - frozen_ship_count(room.players[pid]))
    room.attacks_remaining = max(0, base + bonus)
    emit('attacks_updated', {
        'current_attacker': pid,
        'attacks_remaining': room.attacks_remaining
    }, room=room.id)


def _place_field_magic(room, caster_id, card):
    """将场地魔法卡实例放入场地区域；若已有不同名的旧卡，将其（实例）移入弃牌堆。
    返回被顶掉的旧卡（可能为 None）。"""
    old = room.field_magic
    old_name = getattr(old, 'name', None)   # 换掉之前先记下旧场地名
    room.field_magic = card
    room.field_magic_owner = caster_id
    if old and old_name != card.name:
        room.magic_discard.append(old)
        # 必须把旧卡名显式传进去：此时 room.field_magic 已经指向新卡，
        # 让被调用方自己读会误判成"旧场地还在"，攻击次数就不重算了。
        _clear_field_magic_effects(room, prev_field_name=old_name)
    emit('field_magic_updated', {'player_id': caster_id, 'card': card}, room=room.id)
    return old




@socketio.on('debug_status')
def handle_debug_status(data=None):
    """调试面板（F8）用它判断"我这台客户端能不能显示面板"。

    只回布尔值，**不泄露任何对局数据**；即便返回 True，具体动作仍要过
    @_test_event 的开关 + 白名单两道校验。
    """
    allowed = bool(ENABLE_TEST_EVENTS and _debug_actor_allowed())
    return {
        'enabled': bool(ENABLE_TEST_EVENTS),
        'allowed': allowed,
        'allowlist': bool(DEBUG_ADMIN_USER_IDS),
    }


# 测试功能：添加所有魔法卡到手牌
@socketio.on('test_add_all_magic_cards')
@_test_event
def test_add_all_magic_cards(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 将所有魔法卡添加到玩家手牌
    room.players[player_id].magic_hand = magic_cards.copy()

    # 通知客户端手牌更新
    player = room.players[player_id]
    emit('hand_updated', {
        'hand': player.magic_hand
    }, room=player.sid)

    return {'status': 'success', 'message': f'已添加 {len(magic_cards)} 张魔法卡到手牌'}


@socketio.on('test_set_player_ships')
@_test_event
def test_set_player_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ship_count = data['ship_count']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    player = room.players[player_id]
    opponent_id = next(p for p in room.players if p != player_id)
    opponent = room.players[opponent_id]

    # 清除现有船只
    player.ships = []
    player.remaining_ships = 0

    # 添加新船只
    from random import sample
    all_positions = [(x, y) for x in range(6) for y in range(6)]
    used_positions = set()

    for ship_size in [3, 2, 2, 1, 1, 1][:ship_count]:
        # 随机生成船只位置（水平或垂直）
        placed = False
        while not placed:
            direction = sample(['horizontal', 'vertical'], 1)[0]
            if direction == 'horizontal':
                x = sample(range(6 - ship_size + 1), 1)[0]
                y = sample(range(6), 1)[0]
                positions = [(x + i, y) for i in range(ship_size)]
            else:
                x = sample(range(6), 1)[0]
                y = sample(range(6 - ship_size + 1), 1)[0]
                positions = [(x, y + i) for i in range(ship_size)]

            # 检查是否与现有船只重叠
            if not any(pos in used_positions for pos in positions):
                # 创建船只
                ship_positions = [Position(x=x, y=y) for x, y in positions]
                player.ships.append(PlayerShip(positions=ship_positions, hits=[]))
                player.remaining_ships += 1
                
                # 更新已用位置
                used_positions.update(positions)
                placed = True

    # 更新客户端
    _emit_ships_updated(room)

    return {'status': 'success', 'message': f'已设置玩家船只数量为 {ship_count}'}


@socketio.on('test_clear_all_effects')
@_test_event
def test_clear_all_effects(data):
    room_id = data['room_id']

    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '无效的房间'}

    # 清除所有游戏效果
    room.game_effects = {}
    room.field_magic = None
    room.polar_reversal_applied = False
    room.last_attack = None
    room.magic_temp_data = {}

    # 清除所有玩家效果
    for player_id in room.players:
        player = room.players[player_id]
        # 重置效果标志
        if hasattr(player, 'effect_flags'):
            player.effect_flags = EffectFlags()
        # 清除船只效果
        for ship in player.ships:
            ship.invincible = False
            ship.shield = False
            ship.trap = False
        # 清空沉船记录
        if hasattr(player, 'sunken_ships'):
            player.sunken_ships = []
        # 清除回合数据
        player.damage_dealt_this_turn = 0
        # 清空手牌：E2E 需要"手上有什么卡"完全可控
        # （这个事件本来就叫"清除所有效果"，手牌也算一种对局状态；
        #   不带上它，测试就分不清"我发的那张卡"和开局抽到的卡）
        player.magic_hand = []
        if getattr(player, 'sid', None):
            emit('hand_updated', {'hand': []}, to=player.sid)

    return {'status': 'success', 'message': '已清除所有魔法效果'}


@socketio.on('test_add_specific_magic_card')
@_test_event
def test_add_specific_magic_card(data):
    room_id = data['room_id']
    player_id = data['player_id']
    card_name = data['card_name']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 查找指定魔法卡
    card = next((c for c in magic_cards if c.name == card_name), None)
    if not card:
        return {'status': 'error', 'message': f'未找到名为 {card_name} 的魔法卡'}

    # 添加到玩家手牌
    room.players[player_id].magic_hand.append(card)

    # 通知客户端手牌更新
    player = room.players[player_id]
    emit('hand_updated', {
        'hand': player.magic_hand
    }, room=player.sid)

    return {'status': 'success', 'message': f'已添加魔法卡 {card_name} 到手牌'}


@socketio.on('test_get_game_state')
@_test_event
def test_get_game_state(data):
    room_id = data['room_id']

    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '无效的房间'}

    # 构建游戏状态信息
    game_state = {
        'room_id': room_id,
        'state': room.state,
        'current_attacker': room.current_attacker,
        'current_phase': room.current_phase,
        'attacks_remaining': room.attacks_remaining,
        # 大回合数：E2E 要能观测"极限增援 / 无暇圣心"这类按大回合计数的效果
        'round': room.round,
        'field_magic': room.field_magic.name if hasattr(room.field_magic, 'name') else room.field_magic,
        'game_effects': list(room.game_effects.keys()),
        # 优先权询问（方案 D）状态：E2E 要靠它判断"阶段有没有被推进"
        'priority_pending': (
            {'actor': room.priority_pending.get('actor'),
             'responder': room.priority_pending.get('responder'),
             'action': room.priority_pending.get('action')}
            if getattr(room, 'priority_pending', None) else None
        ),
        'decline_priority': dict(getattr(room, 'decline_priority', None) or {}),
        # 连锁窗口状态：E2E 用它确认"连锁挂起时不该弹优先权询问"
        'chain': [{'card': ci.card.name, 'player': ci.player_id,
                   'negated': ci.negated} for ci in (room.chain or [])],
        'chain_window': room.chain_window,
        'players': {}
    }

    # 添加玩家信息
    for player_id in room.players:
        player = room.players[player_id]
        game_state['players'][player_id] = {
            'remaining_ships': player.remaining_ships,
            'magic_hand_count': len(player.magic_hand),
            # 手牌卡名：E2E 要能判断"客户端收到的手牌"和"服务端真实手牌"是不是同一份。
            # 只比数量会漏掉"张数对但内容错"和"发错人"这两类问题。
            'magic_hand': [getattr(c, 'name', None) for c in player.magic_hand],
            'effect_flags': vars(player.effect_flags) if hasattr(player, 'effect_flags') else {},
            'damage_dealt_this_turn': getattr(player, 'damage_dealt_this_turn', 0),
            'ships': [{
                'positions': [(p.x, p.y) for p in ship.positions],
                'hits': [(p['x'], p['y']) if isinstance(p, dict) else (p.x, p.y) for p in ship.hits],
                'invincible': ship.invincible,
                'shield': ship.shield
            } for ship in player.ships]
        }

    return {'status': 'success', 'game_state': game_state}


@socketio.on('test_reset_game')
@_test_event
def test_reset_game(data):
    room_id = data['room_id']

    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '无效的房间'}

    # 重置游戏状态
    room.state = 'placing_ships'
    room.attack_order = []
    room.current_attacker = ""
    room.attacks_remaining = 0
    room.field_magic = None
    room.game_effects = {}
    room.polar_reversal_applied = False
    room.last_attack = None
    room.magic_temp_data = {}
    room.chain = []
    room.chain_waiting = False
    room.chain_window = None
    room.chain_passes = 0

    # 重置玩家状态
    for player_id in room.players:
        player = room.players[player_id]
        player.ships = []
        player.remaining_ships = 0
        player.attacks = []
        player.magic_hand = []
        player.damage_dealt_this_turn = 0
        
        if hasattr(player, 'effect_flags'):
            player.effect_flags = EffectFlags()
        
        if hasattr(player, 'opponent_attacks'):
            player.opponent_attacks = []
        
        player.revealed_positions = []
        player.needs_reset = True

    return {'status': 'success', 'message': '游戏状态已重置'}


@socketio.on('create_ai_room')
def handle_create_ai_room(data):
    """处理创建人机对战房间的请求"""
    player_id = request.sid
    player_name = data.get('player_name', '玩家')
    player_user_id = data.get('user_id', None)
    difficulty = data.get('difficulty') or 'normal'

    # 创建人机对战房间
    room_id = room_manager.create_ai_room(player_id, player_name, player_user_id, difficulty)
    
    # 让玩家加入房间
    join_room(room_id)

    # 好友功能：人机房同样算"对局中"（真人那一侧的标记由 join_room 那一步补上；
    # 这里挂了也不会有副作用 —— AI 的 user_id 是 None，`_live_uids` 会跳过）。
    _bind_presence_game(room_manager.get_room(room_id))
    
    # 返回房间信息
    return {
        'status': 'success',
        'room_id': room_id,
        'message': '人机对战房间创建成功'
    }


@socketio.on('test_set_opponent_ships')
@_test_event
def test_set_opponent_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ship_count = data['ship_count']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    opponent_id = next(p for p in room.players if p != player_id)
    opponent = room.players[opponent_id]
    player = room.players[player_id]

    # 清除现有船只
    opponent.ships = []
    opponent.remaining_ships = 0

    # 添加新船只
    from random import sample
    all_positions = [(x, y) for x in range(6) for y in range(6)]
    used_positions = set()

    for ship_size in [3, 2, 2, 1, 1, 1][:ship_count]:
        # 随机生成船只位置（水平或垂直）
        placed = False
        while not placed:
            direction = sample(['horizontal', 'vertical'], 1)[0]
            if direction == 'horizontal':
                x = sample(range(6 - ship_size + 1), 1)[0]
                y = sample(range(6), 1)[0]
                positions = [(x + i, y) for i in range(ship_size)]
            else:
                x = sample(range(6), 1)[0]
                y = sample(range(6 - ship_size + 1), 1)[0]
                positions = [(x, y + i) for i in range(ship_size)]

            # 检查是否与现有船只重叠
            if not any(pos in used_positions for pos in positions):
                # 创建船只
                ship_positions = [Position(x=x, y=y) for x, y in positions]
                opponent.ships.append(PlayerShip(positions=ship_positions, hits=[]))
                opponent.remaining_ships += 1
                
                # 更新已用位置
                used_positions.update(positions)
                placed = True

    # 更新客户端
    _emit_ships_updated(room)

    return {'status': 'success', 'message': f'已设置对方船只数量为 {ship_count}'}


@socketio.on('test_end_turn')
@_test_event
def test_end_turn(data):
    room_id = data['room_id']

    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '无效的房间'}

    # 结束当前回合
    if room.current_phase == 'battle':
        # 进入结束阶段
        room.current_phase = 'end'
    elif room.current_phase == 'end':
        # 切换到下一回合
        current_index = room.attack_order.index(room.current_attacker)
        next_index = (current_index + 1) % len(room.attack_order)
        room.current_attacker = room.attack_order[next_index]
        room.current_phase = 'preparation'
        room.attacks_remaining = room.players[room.current_attacker].remaining_ships

    return {'status': 'success', 'message': '回合已结束'}


@socketio.on('test_win_game')
@_test_event
def test_win_game(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 直接设置玩家为胜利
    room.state = 'game_over'
    room.winner = player_id
    
    emit('game_over', {'winner': player_id}, room=room_id)
    return {'status': 'success', 'message': '游戏胜利已设置'}


@socketio.on('test_lose_game')
@_test_event
def test_lose_game(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 直接设置玩家为失败
    opponent_id = next(p for p in room.players if p != player_id)
    room.state = 'game_over'
    room.winner = opponent_id
    
    emit('game_over', {'winner': opponent_id}, room=room_id)
    return {'status': 'success', 'message': '游戏失败已设置'}


@socketio.on('test_get_magic_cards_list')
@_test_event
def test_get_magic_cards_list(data):
    # 返回所有可用的魔法卡列表
    cards_list = []
    for card in magic_cards:
        cards_list.append({
            'name': card.name,
            'speed': card.speed,
            'type': card.type,
            'description': card.description
        })
    
    return {'status': 'success', 'magic_cards': cards_list}


@socketio.on('test_auto_attack')
@_test_event
def test_auto_attack(data):
    room_id = data['room_id']
    player_id = data['player_id']
    attack_count = data.get('count', 1)

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    opponent_id = next(p for p in room.players if p != player_id)
    opponent = room.players[opponent_id]

    # 记录攻击结果
    attack_results = []

    for _ in range(attack_count):
        if room.attacks_remaining <= 0:
            break

        # 选择一个未攻击过的随机位置        
        all_positions = [(x, y) for x in range(6) for y in range(6)]
        attacked_positions = [(a.x, a.y) for a in room.players[player_id].attacks]
        available_positions = [pos for pos in all_positions if pos not in attacked_positions]

        if not available_positions:
            break

        target_x, target_y = random.choice(available_positions)

        # 执行攻击
        hit = False
        ship_sunk = False
        
        for i, ship in enumerate(opponent.ships):
            if Position(x=target_x, y=target_y) in ship.positions:
                hit = True
                
                if ship.shield:
                    ship.shield = False
                elif not ship.invincible:
                    ship.hits.append(Position(x=target_x, y=target_y))
                    
                    if len(ship.hits) == len(ship.positions):
                        ship_sunk = True
                        opponent.remaining_ships -= 1
                
                break

        # 记录攻击
        attack = type('Attack', (), {})
        attack.x = target_x
        attack.y = target_y
        attack.hit = hit
        attack.ship_sunk = ship_sunk
        
        room.players[player_id].attacks.append(attack)
        room.attacks_remaining -= 1

        # 收集攻击结果
        attack_results.append({
            'x': target_x,
            'y': target_y,
            'hit': hit,
            'ship_sunk': ship_sunk
        })

        # 检查游戏是否结束
        if opponent.remaining_ships <= 0:
            room.state = 'game_over'
            room.winner = player_id
            emit('game_over', {'winner': player_id}, room=room_id)
            break

    return {'status': 'success', 'message': f'已执行 {len(attack_results)} 次自动攻击', 'attack_results': attack_results}



@app.route('/lobby')
def lobby():
    # SPA entry point for lobby view
    return render_template('index.html', username=session.get('username'))

@socketio.on('create_room')
def handle_create_room(data):
    data = data if isinstance(data, dict) else {}
    # 优先使用登录后的 user_id，否则使用 sid（游客模式）
    player_id = session.get('user_id', request.sid)
    player_name = session.get('username', data.get('player_name', '匿名玩家'))
    # ★ 累计封禁闸门（2026-09-20，最高档）：被封房间功能的账号不能建房。
    #   闸门放在**最前面**（任何副作用之前）—— 否则建了房再拒绝，
    #   大厅里会先挂出一间永远进不去的房。
    denied = _capability_denied(session.get('user_id'), suspicion.CAP_ROOM)
    if denied:
        emit('error', {'message': denied})
        return {'status': 'error', 'message': denied}
    # ★ 先回收自己上一间等待房，再建新的：一个玩家同时只能主持一间等待中的房。
    # 少了这一步，每点一次「创建房间」大厅里就多挂一间同名房（实测 7 间）。
    _recycle_host_waiting_rooms(player_id)
    room_id = room_manager.create_room()
    # 明确指定socket_id加入Socket.IO房间
    join_room(room_id, request.sid)
    room = room_manager.get_room(room_id)
    if room:
        # 大厅批：房间名与可见性（两个字段都可选，不传时沿用 GameRoom 的默认值）。
        # ⚠️ 名字必须清洗 + 截断：它是玩家可控输入，且会被广播给整个大厅。
        room.name = str(data.get('name') or '').strip()[:LOBBY_ROOM_NAME_MAX_LEN]
        room.public = bool(data.get('public', True))
        room.players[player_id] = Player(**{
            'name': player_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0,  # 初始化剩余战舰数量
            'user_id': player_id,
            'sid': request.sid  # 传递sid给Player构造函数
        })
    # 大厅批：建房这条路也带名字（游客从大厅直接建房时名字只在这里出现）。
    lobby_manager.update_identity(request.sid, player_name, session.get('user_id'))
    # 好友功能：进房即"对局中"（好友申请要提示"对局中"）。挂在 return 之前的收尾位上，
    # 不在任何分支里 —— 分支里随手 return 会静默吞掉这类收尾（本项目栽过三次）。
    if room:
        _bind_presence_game(room)
    return {'status': 'success', 'room_id': room_id}

@socketio.on('join_room')
def handle_join_room(data):
    room_id = data['room_id']
    # 优先使用登录后的 user_id，否则使用 sid（游客模式）
    player_id = session.get('user_id', request.sid)
    player_name = session.get('username', data.get('player_name', '匿名玩家'))
    # ★ 累计封禁闸门：最高档连房间也进不去（与建房同一口径）。
    denied = _capability_denied(session.get('user_id'), suspicion.CAP_ROOM)
    if denied:
        emit('error', {'message': denied})
        return {'status': 'error', 'message': denied}
    # 大厅批：入座这条路的连接可能还没登记过名字（游客直接凭房间号进来）。
    lobby_manager.update_identity(request.sid, player_name, session.get('user_id'))

    room = room_manager.get_room(room_id)
    if not room:
        emit('error', {'message': '房间不存在'}, room=request.sid)
        return {'status': 'error', 'message': '房间不存在'}

    # 进新房之前先把自己**独自占着**的其它等待房清掉（见 `_drop_my_other_waiting_rooms`）：
    # 不清的话旧房会变成没人管的僵尸房，我还同时占着两间。
    _drop_my_other_waiting_rooms(player_id, room_id)

    # ⚠️ **同一身份的重入**要先认出来：`room.players` 的 key 是 `session['user_id']`
    #    （游客是 sid），所以"同一个账号开第二个标签页 / 刷新后经 `?room=` 再进一次"
    #    如果走下面那条"新增座位"，只会**覆盖自己那个 key** —— 长度永远到不了 2
    #    → 这间房**永远开不了局**，而每次 join 的 ack 都是 success、页面上零提示。
    #    （2026-09-19 双浏览器实测钉出来的，症状与"约战开不了局"一模一样。）
    #    正确语义：同一身份 = **同一个座位**，这里只把座位上的连接换成新来这条。
    #    ⚠️ 只在 `waiting` 时这么做：局已经开打的刷新走既有的重连链路
    #    （`get_reconnect_token` / `rejoin_room`），别在这里抢它的活。
    seated = room.players.get(player_id)
    if seated is not None and getattr(room, 'state', None) == 'waiting':
        seated.sid = request.sid          # 之后所有 emit 都发到这条新连接上
        if player_name:
            seated.name = player_name
        join_room(room_id, request.sid)
        _lobby_broadcast_soon()
        _bind_presence_game(room)
        return {'status': 'success', 'player_id': player_id, 'seat': 'reused'}

    if len(room.players) >= 2:
        emit('error', {'message': '房间已满'}, room=request.sid)
        return {'status': 'error', 'message': '房间已满'}

    # 添加玩家到房间（key 为 user_id 或 sid）
    room.players[player_id] = Player(**{
        'name': player_name,
        'ships': [],
        'attacks': [],
        'remaining_ships': 0,  # 初始化剩余战舰数量
        'user_id': player_id,
        'sid': request.sid  # 传递sid给Player构造函数
    })

    # 添加玩家到Socket.IO房间
    join_room(room_id, request.sid)
    # 检查是否所有玩家都已加入
    if len(room.players) == 2:
        # 所有玩家都已加入，开始游戏
        room.state = 'placing_ships'

        # 初始化魔法卡牌系统
        room.init_player_magic(list(room.players.keys())[0], magic_cards)
        room.init_player_magic(list(room.players.keys())[1], magic_cards)

        # 为每个玩家添加对方的名字
        # 准备发送给两个玩家的游戏状态
        # `ranked` / `mode` 一并下发：自定义房恒为休闲局（见 create_room）。
        game_state_data = {
            'state': 'placing_ships',
            'room_id': room_id,
            **_rank_payload(room)
        }

        # 为每个玩家添加对方的名字
        for player_id in room.players:
            opponent_id = next(p for p in room.players if p != player_id)
            player = room.players[player_id]
            emit('game_state', {
                **game_state_data,
                'player_id': player_id,
                'player_name': player.name,
                'opponent_name': room.players[opponent_id].name
            }, to=player.sid)

    # 大厅批：房间列表变了（有人入座 / 房间已满）→ 推一次状态。
    _lobby_broadcast_soon()
    # 好友功能：进房即"对局中"。挂在 return 前的收尾位上（不在任何分支里）。
    _bind_presence_game(room)

    # 返回响应给客户端，包含player_id
    return {'status': 'success', 'player_id': player_id}


# 局内聊天事件
@socketio.on('connect')
def handle_connect():
    """处理客户端连接事件"""
    sid = request.sid
    # 在线表（唯一真相源，/api/online_count 也读它）。登录用户此刻就有名字；
    # 游客的名字要等首页输入后随 find_match / lobby_subscribe 送上来。
    lobby_manager.add_connection(sid, session.get('username'), session.get('user_id'))
    print(f"Client connected: {sid}, online users: {lobby_manager.online_count()}")

    # 好友功能（2026-09-18）：在**上面那张大厅在线表之外**，再记一份"按 uid 的在线/对局中"。
    # ⚠️ 这是**合并期留下的已知重复**：大厅批（2026-09-18）把旧的裸 sid 集合 `online_users`
    #    整个删掉、统一读 `lobby_manager.presence`（见 CLAUDE.md 坑 #17：在线表只能有一份）；
    #    而好友批独立地开了 `presence.py` 记 uid→sids + in_game（好友面板要显示"对局中"，
    #    大厅那张表只有 sid/名字、没有这个维度）。两批并行开发、各自解决了同一半问题。
    #    现状：**两张表并存**，`lobby_manager.presence` 管大厅展示与在线人数，
    #    `presence.py` 管好友侧（/api/friends 的 online / in_game）。口径不同：
    #    同一 uid 两个标签页在大厅表里是 2 个 sid、在 presence 里是 1 个人 2 条连接。
    #    → 以后要收口成一份时，**从这里改**（别只改一半，那正是坑 #1 的形状）。
    # 放在最前面（早于下面那些 try/except 与 `resume_game` 分支）：连上就算在线，
    # 任何后续分支都**不许**把它漏掉（分支里随手 return 会静默吞掉收尾，栽过三次）。
    try:
        _uid = session.get('user_id')
    except Exception:
        _uid = None                     # 无 session（游客 / 异常）→ 不登记，照旧走 sid 那套
    if _uid:
        presence.mark_online(_uid)
        presence.add_sid(_uid, sid)

    # 启动已结束房间的后台回收任务与回合计时看门狗（均幂等）
    try:
        _ensure_reaper()
    except Exception:
        pass
    try:
        _ensure_turn_timer()
    except Exception:
        pass
    try:
        _ensure_lobby_ticker()
    except Exception:
        pass

    # 掉线重连兜底：若该登录用户仍在一局未结束的对局中（且已不在宽限外），
    # 主动推送 resume_game，让客户端自动重连恢复（覆盖关标签页/浏览器后重开场景）。
    try:
        server_pid = session.get('user_id')
    except Exception:
        server_pid = None
    if server_pid:
        candidates = []
        for room_id, room in room_manager.get_all_rooms().items():
            if room.state == 'game_over':
                continue
            for pid, p in room.players.items():
                # 座位属于该登录用户（自定义/人机房 key=user_id，匹配房 key=sid 但 user_id 一致），
                # 且该座位登记的连接不是当前新连接（即刚掉线/换连接重开）
                if p.user_id == server_pid and p.sid != sid:
                    candidates.append((room_id, pid))
        if len(candidates) == 1:
            room_id, pid = candidates[0]
            emit('resume_game', {
                'room_id': room_id,
                'player_id': pid,
                'message': '检测到未结束的对局，正在恢复…',
            }, to=sid)
            # 预发放重连 token
            room = room_manager.get_room(room_id)
            if room:
                tok = secrets.token_hex(16)
                room.reconnect_tokens[pid] = tok
                emit('reconnect_token', {'token': tok}, to=sid)


@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接事件"""
    sid = request.sid
    lobby_manager.remove_connection(sid)
    print(f"Client disconnected: {sid}, online users: {lobby_manager.online_count()}")

    # 好友功能（2026-09-18）：注销这个连接（先摘 sid 再减计数，顺序反过来会让
    # `sids_of` 短暂留着一条已经死掉的连接）。⚠️ 必须在**下面那个 `return` 之前**
    # 做完 —— 座位匹配成功就直接返回了，放到后面等于掉线时永远不注销。
    # ⚠️ 这里只动纯内存，**绝不 emit**（disconnect 里同步 emit 会卡死 eventlet hub，
    #    见下面那段注释与 CLAUDE.md 第 9 节）。
    try:
        _uid = session.get('user_id')
    except Exception:
        _uid = None
    if _uid:
        try:
            presence.remove_sid(_uid, sid)
            presence.mark_offline(_uid)
        except Exception:
            pass

    # 清理相关数据：从匹配队列移除该连接
    if room_manager.has_player_in_match_queue(sid):
        room_manager.remove_from_match_queue(sid)

    # 大厅批：有人掉线 → 在线列表/房间列表都要变。**不能在这里同步 emit**
    # （eventlet 下会卡住 hub），所以放进后台任务（见 _lobby_broadcast_soon）。
    _lobby_broadcast_soon()

    # 掉线宽限：若该连接正坐在某未结束房间的座位上，启动 30s 重连窗口。
    # 注意：不能在 disconnect 处理器内同步 emit（eventlet 下会卡住 hub），
    # 因此把通知+计时整体放入后台任务（先让 disconnect 收尾完成）。
    for room_id, room in room_manager.get_all_rooms().items():
        for pid, p in list(room.players.items()):
            if p.sid == sid:
                # 人已经走了：把他的"对局中"标记摘掉（重连回来时再挂上；挂着不清会
                # 让离线账号永远显示"对局中"）。纯内存操作，同样不是 emit。
                try:
                    if getattr(p, 'user_id', None):
                        presence.set_in_game(p.user_id, False)
                except Exception:
                    pass
                socketio.start_background_task(_start_disconnect_grace, room_id, player_id=pid)
                return


@socketio.on('chat_message')
def handle_chat_message(data):
    player_id = session.get('user_id', request.sid)
    username = session.get('username', f'玩家{str(player_id)[:6]}')
    msg = (data.get('message') or '').strip()
    if not msg:
        return
    msg = msg[:MAX_CHAT_MSG_LEN]
    # 查找玩家所在房间
    room_id = data.get('room_id')
    # 仅房间内广播
    room = room_manager.get_room(room_id)
    # 安全：必须确实坐在这个房间里，否则任意连接都能向别人的房间发言
    if room and not any(p.sid == request.sid for p in room.players.values()):
        return
    if room:
        for pid in room.players:
            is_me = (room.players[pid].name == username)
            emit('chat_message', {
                'username': username,
                'message': msg,
                'isMe': is_me
            }, to=room.players[pid].sid)
        # 标记自己和对手
    else:
        # fallback: 仅回发给自己
        emit('chat_message', {'username': username, 'message': msg, 'isMe': True}, room=request.sid)


# ---------------------------------------------------------------------------
# 局内快捷语（第 4 批，契约见 docs/BATCH_2_3_4_PLAN.md §4）
# ---------------------------------------------------------------------------
def _quick_chat_fail(message: str):
    """把失败原因**明确**回给发起者：不发出去、也要让人知道为什么。

    绝不静默 return —— 静默的失败表现是"点了没反应"，本项目吃过多次
    （见 CLAUDE.md 第 11 节）。原因只回给发起者（`to=request.sid`）：
    对手没必要看到"你发太快了"。单测直调 handler（无请求上下文）时退化为
    房间外广播，与项目里既有的 `emit('error', {...}, to=request.sid)` 同一写法。
    """
    try:
        sid = request.sid
    except RuntimeError:
        sid = None
    if sid:
        emit('error', {'message': message}, to=sid)
    else:
        emit('error', {'message': message})
    return {'status': 'error', 'message': message}


@socketio.on('quick_chat')
def handle_quick_chat(data):
    """局内快捷语：广播给房间双方 + 记一句对局日志。

    房间 / 身份的取法与 handle_attack / end_turn 完全一致：payload 带
    `room_id` + `player_id`，再走 `room_manager.get_room()` 与 `_identity_ok()`。

    ⚠️ 三件【绝对不许】发生的事（契约 §4.3，三条各有回归测试）：
      1. 不许消耗 / 修改 `attacks_remaining`（发句话不是一次行动）；
      2. 不许改变 `state` / `current_phase`（不推进任何流程）；
      3. 不许往 `room.chain` 里塞东西、不许打开响应窗口，也不许动
         `pending_placement` / `pending_sacrifice`。
    因此这里**刻意不挂** `@_require_live_room`：终局之后正是「结束」组
    （GG，打得好 / 再来一局？）最该能发的时候。

    校验顺序：房间 → 身份 → 白名单 → 频率；每一步失败都 emit 一条 `error`，
    且**不广播**（白名单外 / 越界的消息一个字都不许进对手的屏幕）。
    """
    # 客户端可能发来任何东西（字符串 / 列表 / None）—— 不是 dict 就一律当空载荷，
    # 让它走"房间不存在"这条路，而不是在这里 AttributeError。
    if not isinstance(data, dict):
        data = {}
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    msg_id = data.get('msg_id')

    # ① 房间必须存在
    room = room_manager.get_room(room_id)
    if not room:
        return _quick_chat_fail('房间不存在')

    # ② 身份（伪造他人的 player_id 会在这里被挡；无请求上下文时只校验成员）
    if player_id not in room.players or not _identity_ok(room, player_id):
        return _quick_chat_fail('无效的房间或玩家')

    # ③ msg_id 必须在白名单内 —— 文案只从 quick_chat.by_id() 取
    item = quick_chat.by_id(msg_id)
    if item is None:
        return _quick_chat_fail('无效的快捷语')

    # ④ 频率：窗口内最多 3 条 + 同一句窗口内不重复（规则在 quick_chat.check_rate）
    now = time.time()
    recent = [t for t in room.quick_chat_recent.get(player_id, [])
              if now - t < quick_chat.WINDOW_SECONDS]
    ok, reason = quick_chat.check_rate(recent, now, room.quick_chat_last.get(player_id), msg_id)
    room.quick_chat_recent[player_id] = recent  # 顺手淘汰过期时间戳，避免无限增长
    if not ok:
        return _quick_chat_fail(reason)

    # 通过：**真的发出去之后**才记账（被拒的不留痕，否则拒绝也会占满窗口）
    recent.append(now)
    room.quick_chat_recent[player_id] = recent
    room.quick_chat_last[player_id] = {'id': msg_id, 'ts': now}

    name = _log_name(room, player_id)
    emit('quick_chat', {
        'player_id': player_id,
        'name': name,
        'msg_id': msg_id,
        'text': item['text'],   # 文案的唯一来源是 quick_chat.py，前端不写死
        'ts': int(now),
    }, room=room.id)
    # 记进双方的对局日志（沿用既有的日志助手：它自己会把 game_log 推给房间）
    add_game_log(room, f'{name}：{item["text"]}', 'quick_chat',
                 {'player_id': player_id, 'msg_id': msg_id})
    return {'status': 'success', 'msg_id': msg_id, 'text': item['text']}


def _client_ip() -> str:
    """当前 socket 请求的对端 IP（取不到返回空串）。

    ⚠️ **只信 `request.remote_addr`，不读 `X-Forwarded-For`**。
    线上是 `run_prod.py` 直接把 app 挂在 `0.0.0.0:5000`（**没有 nginx / 反代**，
    已实测确认），所以 `remote_addr` 就是真实对端、且客户端**无法伪造**；
    而 `X-Forwarded-For` 是纯客户端可写的头，信它等于把规避规则交给攻击者。
    将来若加了反代，必须在这里显式改为读代理头**并**确认代理会覆写它。
    """
    try:
        return (request.remote_addr or '').strip()
    except Exception:
        return ''


def _recent_foes(uid: str, limit: int = None) -> set:
    """该账号最近交手过的对手 user_id 集合（用于匹配规避）。

    ⚠️ 口径：看 `matches` 表最近的 N 局。**不做时间过滤** —— 时间窗由调用方
    （`match_guard.RECENT_OPPONENT_COOLDOWN_SEC`）用对局时间戳自行判定，
    这里只负责"最近跟谁打过"这件事，避免同一个判断有两份实现。
    """
    if not uid:
        return set()
    n = limit or match_guard.RECENT_OPPONENT_LOOKBACK
    try:
        with db.db._lock:
            cur = db.db.conn.execute(
                'SELECT winner_id, loser_id FROM matches '
                'WHERE (winner_id = ? OR loser_id = ?) '
                'ORDER BY timestamp DESC LIMIT ?', (uid, uid, int(n)))
            rows = cur.fetchall()
    except Exception:
        return set()
    out = set()
    for row in rows or ():
        try:
            w, l = (row[0], row[1]) if not isinstance(row, dict) else (row['winner_id'], row['loser_id'])
        except Exception:
            continue
        out.add(l if w == uid else w)
    out.discard(uid)
    out.discard(None)
    return out


def _dirty_ips() -> set:
    """有刷分标记的账号所对应的 IP 集合。

    ⚠️ 目前 **没有把 IP 落库**（本批刻意不做，见 `docs/ANTICHEAT_FORENSICS_2026_09_19.md` §8：
    采集 IP 是隐私决策，得先写进隐私说明）。所以这个函数**当前恒返回空集** ——
    即"脏 IP 硬拦"这条规则**暂时不会触发**，但它已经接好了线：
    一旦以后落了 IP，只需在这里补一条查询，规避逻辑不用改。
    """
    return set()


def _mk_candidate(entry: dict) -> 'match_guard.Candidate':
    """把一个队列条目转成 `match_guard.Candidate`（**唯一的转换入口**）。

    ⚠️ 取 `recent_foes` 要读库，所以这里包 try：读不到就当"没交过手"
    （少一层规避，绝不能因为查库失败让匹配直接崩掉）。
    """
    try:
        uid = entry.get('user_id')
        return match_guard.Candidate(
            sid=entry.get('sid'),
            uid=uid,
            mode=entry.get('mode'),
            ip=entry.get('ip') or '',
            recent_foes=_recent_foes(uid) if uid else (),
            ip_dirty=(entry.get('ip') in _dirty_ips()) if entry.get('ip') else False,
            waited_sec=int(time.time() - (entry.get('enqueued_at') or time.time())),
        )
    except Exception:
        # 失败开放：拿不到附加信息就退回"最小候选"（只有 sid/mode），
        # 这样至少同 mode / 同账号这两条**既有**规则还在。
        return match_guard.Candidate(
            sid=entry.get('sid'), uid=entry.get('user_id'),
            mode=entry.get('mode'), ip='', recent_foes=(), ip_dirty=False)


@socketio.on('find_match')
def handle_find_match(data):
    """处理玩家匹配请求。

    payload 可选 `mode`：`'ranked'`（排位）/ 其余一律 `'casual'`（休闲）。
    排位**必须登录** —— 游客排位要明确拒绝（emit `error`），而不是排进去之后
    永远配不上（因为排位房里结算要 `Player.user_id` 才能写库）。
    """
    socket_sid = request.sid
    db_user_id = session.get('user_id', socket_sid)
    player_name = data.get('player_name', '匿名玩家')
    user_id = session.get('user_id')
    mode = _normalize_match_mode(data.get('mode'))

    # 大厅批：游客的名字到这一刻才知道（首页输入框），补写在线表，
    # 否则大厅里这个连接会一直显示成"游客"。
    lobby_manager.update_identity(socket_sid, session.get('username') or player_name, user_id)

    # 排位必须登录：游客入排位池只会占着队列配不上（排位结算要写 user_rank）。
    if mode == MATCH_MODE_RANKED and not user_id:
        emit('error', {'message': '排位模式需要先登录'})
        return {'status': 'error', 'message': '排位模式需要先登录'}

    # ★ 累计封禁闸门（2026-09-20）：按等级拦。
    #   1 级只禁排位、2 级连休闲匹配也禁、3 级连房间都禁（房间在 create/join 处拦）。
    #   ⚠️ 两个能力要分别判：拿 CAP_MATCH 去拦排位是错的（休闲也一起禁了），
    #      拿 CAP_RANKED 去拦休闲更错（等于 1 级就直接全禁）。
    _cap = suspicion.CAP_RANKED if mode == MATCH_MODE_RANKED else suspicion.CAP_MATCH
    denied = _capability_denied(user_id, _cap)
    if denied:
        emit('error', {'message': denied})
        return {'status': 'error', 'message': denied}

    # 检查玩家是否已经在匹配队列中
    if room_manager.has_player_in_match_queue(socket_sid):
        return {'status': 'error', 'message': '你已经在匹配队列中'}

    # 将玩家加入队列（mode 一起存进队列条目，配对时只在同 mode 之间配）
    room_manager.add_to_match_queue(socket_sid, player_name, user_id, mode,
                                    ip=_client_ip())
    emit('match_queued', {'status': 'success', 'message': '已加入匹配队列', 'mode': mode})

    # 尝试匹配：队列操作全程持锁，事件在锁外发送，避免并发下队列错位。
    #
    # 配对规则（2026-09-20 起交给 `match_guard.pick_pair`，**规则只此一份**）：
    #   ① **同 mode 才配**（ranked 只配 ranked）；② 同一账号不配（多标签页）；
    #   ③ 同 IP / 近来交手过的对手**软规避** —— 有更好的选择时躲开；
    #   ④ 同 IP 且该 IP 两个账号都有作弊标记 → **硬拦**。
    #   ★ 兜底：只剩"软规避"的对象可配时**仍然配**（否则深夜两人永远开不了局），
    #     但这一局**不结算排位分**（`assessed=False` → `room.ranked` 为 False）。
    #
    # ⚠️ 扫描每次至少配掉两人 / 或直接 break，所以不会死循环。
    matched = []
    with room_manager._lock:
        while len(room_manager.match_queue) >= 2:
            entries = list(room_manager.match_queue)
            cands = [_mk_candidate(e) for e in entries]
            i, j, assessed = match_guard.pick_pair(cands)
            if i is None:
                # 没有可配的对（全是同账号重复记录 / 剩下的都在等另一种 mode 的人 /
                # 只剩硬拦的组合）：队列原样保留，等新玩家入队，绝不能原地重试。
                break
            p2 = room_manager.match_queue.pop(j)
            p1 = room_manager.match_queue.pop(i)

            room_id = room_manager.create_room()
            room = room_manager.get_room(room_id)
            # 匹配成功建房时打排位标记（自定义房/人机房恒 False，见 create_room /
            # create_ai_room）。两个人 mode 相同（上面刚判过），取 p1 的即可。
            #
            # ★ 兜底配出来的对（assessed=False）**不给排位标记** → 这一局不结算
            #   段位分。能给玩家开一局娱乐，但不给刷分收益。
            room.ranked = (p1.get('mode') == MATCH_MODE_RANKED) and bool(assessed)
            room.players[p1['sid']] = Player(**{
                'name': p1['name'],
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': p1['user_id'],
                'sid': p1['sid']
            })
            room.players[p2['sid']] = Player(**{
                'name': p2['name'],
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': p2['user_id'],
                'sid': p2['sid']
            })
            room.init_player_magic(p1['sid'], magic_cards)
            room.init_player_magic(p2['sid'], magic_cards)
            room.state = 'placing_ships'
            matched.append((room_id, p1, p2))

    for room_id, p1, p2 in matched:
        join_room(room_id, p1['sid'])
        join_room(room_id, p2['sid'])
        room = room_manager.get_room(room_id)
        # 好友功能：配对成功即"对局中"（匹配房里 key 是 sid，真人 uid 在 Player.user_id 上
        # —— `_live_uids` 只认后者，拿 key 当 uid 会标记到不存在的账号上）。
        _bind_presence_game(room)
        rank_fields = _rank_payload(room) if room else {}
        for me, opp in ((p1, p2), (p2, p1)):
            emit('game_state', {
                'state': 'placing_ships',
                'room_id': room_id,
                'player_id': me['sid'],
                'player_name': me['name'],
                'opponent_name': opp['name'],
                **rank_fields
            }, to=me['sid'])

    # 大厅批：入队 / 配对成功都会改变 status（idle→matching / matching→in_game），
    # 推一次让还站在大厅里的人看到列表变化。
    _broadcast_lobby_state()

    return {'status': 'success', 'message': '开始寻找匹配'}


@socketio.on('cancel_match')
def handle_cancel_match(data):
    """处理玩家取消匹配请求：队列以 socket sid 为 key，按当前连接出队。

    排位与休闲**共用同一个队列**，所以取消逻辑不需要分 mode —— 按 sid 定位即可
    （排位排队也能被取消，前端「取消排位」按钮走的就是这个事件）。
    """
    sid = request.sid
    room_manager.remove_from_match_queue(sid)
    emit('match_canceled', {'status': 'success', 'message': '已取消匹配'}, to=sid)
    # 大厅批：出队 → status 回到 idle，推一次。
    _broadcast_lobby_state()
    return {'status': 'success', 'message': '已取消匹配'}


# ---------------------------------------------------------------------------
# 大厅系统事件（2026-09-18）。冻结契约见 docs/LOBBY_2026_09_18.md §1.1 / §1.2。
# ---------------------------------------------------------------------------
# 事件名一览（改名前先 grep 全仓，前端 game.js 里有对应的 socket.on/emit）：
#   客户端 → 服务端：lobby_subscribe / lobby_unsubscribe / lobby_refresh
#                    / lobby_create_room / lobby_chat_send
#   服务端 → 客户端：lobby_hello / lobby_state / lobby_chat_history / lobby_chat
def _lobby_subscriber_name(sid, data) -> str:
    """订阅者显示名：登录态优先，其次 payload 里的 player_name，最后回落到在线表。"""
    if isinstance(data, dict):
        given = str(data.get('player_name') or '').strip()
        if given:
            return given
    row = lobby_manager.presence().get(sid) or {}
    return row.get('name') or '游客'


@socketio.on('lobby_subscribe')
def handle_lobby_subscribe(data=None):
    """进入大厅并订阅实时状态。**幂等**：重复调用只是刷新名字、重发一次当前状态。"""
    data = data if isinstance(data, dict) else {}
    sid = request.sid
    user_id = session.get('user_id')
    name = session.get('username') or _lobby_subscriber_name(sid, data)
    lobby_manager.subscribe(sid, name, user_id)
    # 订阅 = 加入 socket.io 房间，之后 _broadcast_lobby_state 一次 emit 全员收到
    join_room(LOBBY_ROOM, sid)

    # 身份键：前端靠它标"我"（lobby_state 是一条广播，没法逐人改 is_me）
    emit('lobby_hello', {'key': sid, 'name': _lobby_clean_name(name),
                         'guest': not bool(user_id)}, to=sid)
    # 补发公屏最近消息 + 立刻给一份状态（不用等下一次广播）
    emit('lobby_chat_history', {'messages': lobby_manager.recent_chat()}, to=sid)
    emit('lobby_state', build_lobby_state(), to=sid)
    # 通知其他人：大厅人数 + 玩家的 in_lobby 标记变了
    _broadcast_lobby_state()
    return {'status': 'success', 'key': sid}


@socketio.on('lobby_unsubscribe')
def handle_lobby_unsubscribe(data=None):
    """离开大厅：退订。**保留在线表**（人还连着，只是不在大厅页面上）。"""
    sid = request.sid
    lobby_manager.unsubscribe(sid)
    try:
        leave_room(LOBBY_ROOM, sid)
    except Exception:
        pass
    _broadcast_lobby_state()
    return {'status': 'success'}


@socketio.on('lobby_refresh')
def handle_lobby_refresh(data=None):
    """手动刷新：未订阅时顺带订阅（刷新按钮不该把人踢出大厅）。"""
    sid = request.sid
    if not lobby_manager.is_member(sid):
        return handle_lobby_subscribe(data)
    emit('lobby_state', build_lobby_state(), to=sid)
    return {'status': 'success'}


@socketio.on('lobby_create_room')
def handle_lobby_create_room(data=None):
    """在大厅里直接建房。

    复用 create_room 处理器（同一套：登记座位 / join socket.io 房间 / 房间名与可见性），
    避免大厅和自定义房间页各写一份建房逻辑（两份实现必然漂移）。
    """
    data = data if isinstance(data, dict) else {}
    payload = {
        'player_name': _lobby_subscriber_name(request.sid, data),
        'name': data.get('name'),
        'public': data.get('public', True),
    }
    result = handle_create_room(payload)
    if not isinstance(result, dict) or result.get('status') != 'success':
        return result if isinstance(result, dict) else {'status': 'error', 'message': '建房失败'}
    _broadcast_lobby_state()
    room = room_manager.get_room(result.get('room_id'))
    return {
        'status': 'success',
        'room_id': result.get('room_id'),
        'name': str(getattr(room, 'name', '') or ''),
        'public': bool(getattr(room, 'public', True)),
    }


@socketio.on('lobby_chat_send')
def handle_lobby_chat_send(data=None):
    """大厅公屏发言。

    三条闸门（顺序不能换）：
      ① 必须是**大厅成员** —— 否则任何连接都能往公屏灌字；
      ② 频率（LOBBY_CHAT_MIN_INTERVAL）—— 防刷屏；
      ③ 内容清洗（空白丢弃、超长截断）由 lobby_manager.add_chat 负责。
    """
    data = data if isinstance(data, dict) else {}
    sid = request.sid
    if not lobby_manager.is_member(sid):
        return {'status': 'error', 'message': '请先进入大厅'}
    if not lobby_manager.chat_allowed(sid):
        emit('error', {'message': f'发言太快了，请等 {LOBBY_CHAT_MIN_INTERVAL:.0f} 秒'}, to=sid)
        return {'status': 'error', 'message': '发言太快了'}
    row = lobby_manager.presence().get(sid) or {}
    name = session.get('username') or row.get('name') or '游客'
    item = lobby_manager.add_chat(sid, name, data.get('message'))
    if item is None:
        return {'status': 'error', 'message': '消息不能为空'}
    emit('lobby_chat', item, to=LOBBY_ROOM)
    return {'status': 'success', 'ts': item['ts']}


@socketio.on('close_room')
def handle_close_room(data=None):
    """解散自己主持的、还没开打的房。

    为什么要有它：大厅批上线后实测到"同一连接连点 7 次建房 → 大厅挂出 7 间同名房"，
    根因是等待房既不会自动回收（TTL 1 小时），玩家也**没有任何主动解散的出口** ——
    建错了只能干等一小时。这是那个出口。

    三条校验（少一条就是漏洞）：
      ① 房必须存在且仍是 `waiting`（已开打的房不许被房主一键解散，那会坑对手）；
      ② 房内**恰好 1 人**（只有房主自己，没有别人正在等他）；
      ③ 那 1 人就是**调用者自己** —— 用与建房同一条口径取 key
         （登录态 = session user_id，游客 = sid），否则任何人都能解散别人的房。
    """
    data = data if isinstance(data, dict) else {}
    room_id = str(data.get('room_id') or '')
    player_id = session.get('user_id', request.sid)
    room = room_manager.get_room(room_id) if room_id else None
    if room is None:
        return {'status': 'error', 'message': '房间不存在'}
    if getattr(room, 'state', None) != 'waiting':
        return {'status': 'error', 'message': '对局已开始，不能解散'}
    entries = list(room.players.items())
    if len(entries) != 1 or entries[0][0] != player_id:
        return {'status': 'error', 'message': '只能解散自己创建的房间'}
    # ⚠️ 走 `_drop_room`：这条路上人是**连着**的，房没了就必须把「对局中」摘掉 ——
    #    否则「局中不许邀战」那道护栏会把他**永久拦住**（实测踩过：解散之后再也邀不了战）。
    _drop_room(room_id, '房主解散等待房')
    _broadcast_lobby_state()
    return {'status': 'success', 'room_id': room_id}



@socketio.on('place_ships')
@_require_live_room
def handle_place_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ships = data['ships']
    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 服务端校验布船：数量匹配上限、坐标合法且不重叠，防止越界/重叠/刷船。
    if not isinstance(ships, list) or not ships:
        return {'status': 'error', 'message': '布船数据无效'}
    expected = int(getattr(room.players[player_id], 'max_ships', None) or 6)
    if len(ships) != expected:
        return {'status': 'error', 'message': f'需要放置 {expected} 艘战舰'}
    occupied = set()
    for s in ships:
        if not isinstance(s, dict):
            return {'status': 'error', 'message': '战舰数据格式错误'}
        positions = s.get('positions') or []
        if not isinstance(positions, list) or not positions:
            return {'status': 'error', 'message': '战舰缺少位置信息'}
        for pos in positions:
            if not isinstance(pos, dict):
                return {'status': 'error', 'message': '战舰坐标格式错误'}
            try:
                px, py = int(pos['x']), int(pos['y'])
            except (KeyError, TypeError, ValueError):
                return {'status': 'error', 'message': '战舰坐标非法'}
            if not (0 <= px <= 5 and 0 <= py <= 5):
                return {'status': 'error', 'message': '战舰坐标超出棋盘范围'}
            if (px, py) in occupied:
                return {'status': 'error', 'message': '战舰不能重叠'}
            occupied.add((px, py))

    room.players[player_id].ships = list(map(lambda x: PlayerShip(**x), ships))

    # AI房间：人类摆完后为AI自动摆船
    if getattr(room, 'is_ai_room', False):
        ai_id = _ai_player_id(room)
        if ai_id and player_id != ai_id and not room.players[ai_id].ships:
            _ai_place_ships(room, ai_id)

    # 新增：计算并设置剩余战舰数量（攻击次数）
    room.players[player_id].remaining_ships = len(ships)

    # 检查是否所有玩家都已放置战舰
    #
    # ⚠️ 这个判据是**为"双方一起重摆"设计的**（灵气复苏 / 败者食尘：两者都清双方船）。
    #    回光返照只清施法者一个人的船，对手 6 艘一直在 → 这里**恒为真**。
    #    所以回光返照那条路不能靠它兜，必须由下面的 `huiguang_awaiting_placement`
    #    显式接管（否则会掉进通用分支 → 不重新猜拳，作者实测报的就是这个）。
    all_placed = all(len(p.ships) > 0 for p in room.players.values())
    if all_placed:
        # ★ 回光返照（2026-09-20 第三版）：布完船 → **留在自己的回合，只是打不出去**。
        #
        # 作者裁定的完整流程（原话）：
        #   「用完之后应该自己还是处于准备阶段，然后进入战斗阶段但是攻击次数为 0，
        #     然后可以进入结束阶段，然后再结束结束阶段进入对方的回合」
        #
        # 也就是：**阶段照常走，只是攻击次数为 0**。
        # ⚠️ 前一版直接把行动权交给对手（跳过自己的准备/战斗/结束三个阶段），
        #    那是"跳过整个回合"，不是"跳过战斗阶段" —— 作者实测当场指出不对。
        #    卡面「跳过自己的战斗阶段」的落地方式是：能进战斗阶段，但一次都打不出去。
        #
        # 这样也才对得上 `last_chance` 的语义：本大回合内对手还能打到我（在他的回合里）。
        if getattr(room, 'huiguang_awaiting_placement', False):
            room.huiguang_awaiting_placement = False

            # 回到自己的回合、准备阶段；行动权**仍然在自己手上**。
            room.state = 'attacking'
            room.current_attacker = player_id
            room.current_phase = 'preparation'
            # 攻击次数为 0：卡面"跳过自己的战斗阶段" = 进得了战斗阶段、但打不出去。
            # ⚠️ 不能只设 0 就完事 —— `_recalc_attacker_attacks` 在进入战斗阶段时
            #    会按船数把它重算回 6。所以记一个**大回合级的玩家标记**，
            #    由 `_attacks_forced_zero` 兜住。
            #
            # ★ 必须用 `zero_attacks_for`（**玩家级**），**不是** `zero_attacks_round`
            #   （那是**房间级** = 败者食尘的"双方攻击都为 0"）。
            #   卡面写的是「跳过**自己的**战斗阶段」—— 对手不该受影响。
            #   作者实测报的"对手的攻击次数怎么归零了"就是借错机制造成的。
            room.attacks_remaining = 0
            room.game_effects['zero_attacks_for'] = {
                'player': player_id,
                'round': room.round,
            }
            emit('game_message', {
                'message': '回光返照：棋盘已重摆，本回合无法攻击（攻击次数为 0）',
            }, room=room_id)
            emit('game_state', {
                'state': 'attacking',
                'current_attacker': room.current_attacker,
                'current_phase': room.current_phase,
                'attacks_remaining': room.attacks_remaining,
                'round': room.round,
                **_rank_payload(room),
            }, room=room_id)
            return {'status': 'success'}

        # 灵气复苏：这是中途重新摆放，不重新猜拳。
        # 恢复到施法前的先后手与阶段，只把棋盘换成新船数。
        if getattr(room, 'lingqi_resurgence_applied', False):
            room.lingqi_resurgence_applied = False
            saved = getattr(room, 'lingqi_saved_state', None) or {}
            room.lingqi_saved_state = None

            room.attack_order = saved.get('attack_order') or list(room.players.keys())
            room.current_attacker = saved.get('current_attacker') or room.attack_order[0]
            room.round = saved.get('round', room.round)
            room.current_phase = saved.get('current_phase', 'preparation')
            room.state = 'attacking'

            # 攻击次数随船数变化：准备阶段还没开打，按新船数重算；
            # 战斗/结束阶段保留原本剩余次数，避免凭空多出攻击。
            if room.current_phase == 'preparation':
                _recalc_attacker_attacks(room)
            else:
                room.attacks_remaining = saved.get('attacks_remaining', room.attacks_remaining)

            # 败者食尘第二句「生效的大回合内双方攻击次数都为0」。
            # ⚠️ 必须在这里处理：那条规则原先挂在"猜拳结束"分支上
            # （见 determine_rps_winner），而败者食尘现在不重新猜拳，
            # 走不到那里 —— 不补这一处，攻击次数归零就会静默失效。
            if getattr(room, 'polar_reversal_applied', False):
                room.polar_reversal_applied = False
                room.attacks_remaining = 0

            emit('game_message', {
                'message': '双方已重新摆放战舰，继续当前回合',
                'type': 'info'
            }, room=room_id)
            emit('game_state', {
                'state': 'attacking',
                'current_attacker': room.current_attacker,
                'current_phase': room.current_phase,
                'attacks_remaining': room.attacks_remaining,
                'round': room.round,
                **_rank_payload(room),
            }, room=room_id)
            # 若当前攻击者是 AI，继续驱动其回合
            _maybe_run_ai_turn(room)
            return {'status': 'success'}

        room.state = 'rock_paper_scissors'
        # 重置猜拳选择和处理标记，确保新的猜拳阶段从空开始
        room.rps_choices = {}
        room.rps_processed = False

        emit('game_state', {'state': 'rock_paper_scissors', **_rank_payload(room)}, room=room_id)

    return {'status': 'success'}


@socketio.on('rps_choice')
@_require_live_room
def handle_rps_choice(data):
    room_id = data['room_id']
    player_id = data['player_id']
    choice = data['choice']  # 'rock', 'paper', 'scissors'

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 出拳值必须合法：此前任意字符串都会被写进 rps_choices，
    # determine_rps_winner 里 win_conditions[c1] 会直接 KeyError（结算方 handler
    # 抛异常、猜拳卡死、双方都拿不到 rps_result）；若非法值恰好属于 players[1]，
    # 又会走进 else 分支让「出非法拳的一方」直接获胜。
    if choice not in ('rock', 'paper', 'scissors'):
        return {'status': 'error', 'message': '无效的出拳'}

    # AI房间：AI自动出拳
    if getattr(room, 'is_ai_room', False):
        ai_id = _ai_player_id(room)
        if ai_id and ai_id not in room.rps_choices:
            room.rps_choices[ai_id] = random.choice(['rock', 'paper', 'scissors'])

    room.rps_choices[player_id] = choice
    
    # 检查是否所有玩家都已做出选择
    if len(room.rps_choices) == len(room.players) and not room.rps_processed:
        # 标记为已处理，防止重复执行
        room.rps_processed = True
        
        # 决定猜拳结果
        result = determine_rps_winner(room)
        emit('rps_result', result, room=room_id)

        # 平局：order 为空，不进攻击阶段，等双方重新出拳
        # （determine_rps_winner 已清空 rps_choices 并复位 rps_processed）
        if result.status == 'tie' or len(result.order) < 2:
            return {'status': 'success', 'message': '平局，重新猜拳'}

        # 设置攻击顺序
        room.attack_order = result.order
        winner = room.attack_order[0]  # 先手
        loser = room.attack_order[1]  # 后手
        room.current_attacker = winner

        # 初始化攻击次数 - 如果是败者食尘生效的回合，攻击次数为0
        if hasattr(room, 'polar_reversal_applied') and room.polar_reversal_applied:
            room.attacks_remaining = 0
            # 清除败者食尘标记
            room.polar_reversal_applied = False
        else:
            room.attacks_remaining = max(0, room.players[winner].remaining_ships - frozen_ship_count(room.players[winner]))
            _recalc_attacker_attacks(room)

        # 猜拳后抽卡逻辑：先手1张，后手2张
        # 先手抽1张
        winner_card = room.draw_card(winner)
        # 后手抽2张
        loser_card1 = room.draw_card(loser)
        loser_card2 = room.draw_card(loser)

        room.state = 'attacking'
        # 对局**真正开始**的时刻（猜拳结束、进入 attacking）。
        # 「闪电战」的用时以它为起点，而不是 room.created_at —— 自定义房间可能
        # 建好后放很久才有人入座，那段等待时间不该算进对局用时。
        # 只打点一次：重连恢复（`room.state = 'attacking'` 的另一处）不会覆盖它。
        if not getattr(room, 'match_started_at', None):
            room.match_started_at = time.time()
        # 设置当前阶段为准备阶段
        room.current_phase = 'preparation'
        # AI先手时自动驱动其回合
        _maybe_run_ai_turn(room)
        emit('game_state', {
            'state': 'attacking',
            'current_attacker': winner,
            'current_phase': 'preparation',
            'attacks_remaining': room.attacks_remaining,
            'winner_card': winner_card,
            'loser_cards': [loser_card1, loser_card2],
            'round': room.round,
            # 攻击顺序：[先手, 后手]。前端需要它来判断「自己是否先手」
            # （Freezing！ 这类卡只在先手方可用）
            'attack_order': list(room.attack_order),
            **_rank_payload(room),
        }, room=room_id)

    return {'status': 'success'}


class RPSResult:
    def __init__(self, status: str, message: str, winner: str = None, loser: str = None, choices: dict = None, order: list = None):
        self.status = status
        self.message = message
        self.winner = winner
        self.loser = loser
        self.choices = choices or {}
        self.order = order or []
    
    def to_dict(self):
        return {
            'status': self.status,
            'message': self.message,
            'winner': self.winner,
            'loser': self.loser,
            'choices': self.choices,
            'order': self.order
        }


class ChainItem:
    def __init__(self, player_id: str, card: MagicCard, targets: list, timestamp: float):
        self.player_id = player_id
        self.card = card
        self.targets = targets
        self.timestamp = timestamp
        self.negated = False  # 被连锁中更上方的卡牌无效化
        self.negated_by = None  # 康掉它的卡名（用于「X被Y无效化」的明确提示）

    def to_dict(self):
        return {
            'player_id': self.player_id,
            'card': self.card,
            'targets': self.targets,
            'timestamp': self.timestamp,
            'negated': self.negated,
            'negated_by': self.negated_by
        }


class AttackResult:
    def __init__(self, attacker: str, x: int, y: int, hit: bool, ship_sunk: bool, remaining_attacks: int, attacker_remaining_ships: int, defender_remaining_ships: int,
                 shield_blocked: bool = False):
        self.attacker = attacker
        self.x = x
        self.y = y
        self.hit = hit
        self.ship_sunk = ship_sunk
        self.remaining_attacks = remaining_attacks
        self.attacker_remaining_ships = attacker_remaining_ships
        self.defender_remaining_ships = defender_remaining_ships
        # 这一炮被「仁王之盾」挡下了（盾破了、船毫发无伤）。
        # 前端要据此画一个【破盾】标记，而不是普通的命中叉 —— 而且这一格
        # 【不算"已攻击"】，同一回合还能再打一次（见 handle_attack 里的说明）。
        self.shield_blocked = shield_blocked

    def to_dict(self):
        return {
            'attacker': self.attacker,
            'x': self.x,
            'y': self.y,
            'hit': self.hit,
            'ship_sunk': self.ship_sunk,
            'remaining_attacks': self.remaining_attacks,
            'attacker_remaining_ships': self.attacker_remaining_ships,
            'defender_remaining_ships': self.defender_remaining_ships,
            'shield_blocked': self.shield_blocked
        }


class ChainResult:
    def __init__(self, card: MagicCard, caster: str, success: bool = True, message: str = ''):
        self.card = card
        self.caster = caster
        self.success = success
        self.message = message
    
    def __getitem__(self, key):
        return getattr(self, key)
    
    def __setitem__(self, key, value):
        setattr(self, key, value)
    
    def to_dict(self):
        return {
            'card': self.card,
            'caster': self.caster,
            'success': self.success,
            'message': self.message
        }


def determine_rps_winner(room: GameRoom):
    players = list(room.players.keys())
    p1, p2 = players[0], players[1]
    c1, c2 = room.rps_choices[p1], room.rps_choices[p2]

    # 处理平局情况
    if c1 == c2:
        room.rps_choices = {}
        room.rps_processed = False  # 重置处理标记，确保可以重新处理
        return RPSResult('tie', '平局，重新猜拳')

    # 兜底：非法出拳值不得让结算抛 KeyError（handler 已做枚举校验，
    # 但这里是纯函数，任何调用路径都不该因为脏数据炸掉整局）
    if c1 not in ('rock', 'paper', 'scissors') or c2 not in ('rock', 'paper', 'scissors'):
        room.rps_choices = {}
        room.rps_processed = False
        return RPSResult('tie', '出拳无效，重新猜拳')

    # 判断胜负
    win_conditions = {
        'rock': 'scissors',
        'paper': 'rock',
        'scissors': 'paper'
    }

    # 正确逻辑：判断c1是否克制c2
    if win_conditions[c1] == c2:
        winner, loser = p1, p2
    else:
        winner, loser = p2, p1

    return RPSResult(
        status='win',
        message=f'{winner} 获胜',
        winner=winner,
        loser=loser,
        choices={p1: c1, p2: c2},
        order=[winner, loser]  # 攻击顺序
    )


# ============ 明智埋葬：选择解析与结算（两条链路共用同一份实现） ============
def _bury_choice_target(room, target_data):
    """把客户端提交的选择解析成 (source, index, 期望卡名)；失败返回 (None, 错误信息)。

    候选卡由 apply_magic_effect 按「牌堆在前、对方手牌在后」的扁平顺序下发：
    - card_index 是候选总表里的扁平下标（前端 cards.forEach 的 index）；
    - source_index 是该卡在自己来源列表（牌堆 / 对方手牌）内的下标。
    两者都要能落到同一张牌上：优先用 source_index 精确定位，否则用扁平下标
    到候选表里换取真实的 (source, index)；没有候选表（旧数据/测试直调）时，
    card_index 就按来源列表内的下标理解。
    """
    source = target_data.get('source')
    if source is None:
        source = 'deck'
    if source not in ('deck', 'opponent_hand'):
        return None, '无效的选择'

    def _as_index(value):
        # 注意 bool 是 int 的子类，True/False 不能当下标用
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    candidates = (room.magic_temp_data or {}).get('candidates') or []

    def _candidate_name(idx):
        for c in candidates:
            if c.get('source') == source and c.get('index') == idx:
                return c.get('name')
        return None

    expected = None
    index = _as_index(target_data.get('source_index'))
    if index is None:
        flat = _as_index(target_data.get('card_index'))
        if flat is not None and flat < len(candidates):
            candidate = candidates[flat]
            # 扁平下标只有与来源一致时才采用，否则退回「来源列表内下标」的约定
            if candidate.get('source') == source:
                index = _as_index(candidate.get('index'))
                expected = candidate.get('name')
        if index is None:
            index = flat
    else:
        expected = _candidate_name(index)

    if index is None:
        return None, '无效的选择'
    return (source, index, expected), None


def _apply_bury_choice(room, player_id, target_data):
    """结算明智埋葬：把选中的牌（牌堆或对方手牌）放进弃牌堆，施法者再摸一张。

    ⚠️ 必须从原位置真移除。只 append 到弃牌堆的话，同一张牌会同时留在
    牌堆/对方手牌里，对方还能再用一次（复制卡）。
    """
    resolved, err = _bury_choice_target(room, target_data)
    if resolved is None:
        return {'status': 'error', 'message': err}
    source, index, expected = resolved

    opponent = None
    if source == 'deck':
        pile = room.magic_deck if isinstance(room.magic_deck, list) else []
    else:
        opponent_id = _opponent_of(room, player_id)
        opponent = room.players.get(opponent_id) if opponent_id else None
        if opponent is None:
            return {'status': 'error', 'message': '无效的选择'}
        pile = opponent.magic_hand

    if not (0 <= index < len(pile)):
        return {'status': 'error', 'message': '无效的选择'}

    if expected and pile[index].name != expected:
        # 候选下发后位置可能被同一连锁里的其它卡改动（抽取/洗牌）：
        # 按下标埋会埋错牌，改按卡名找回原来那张。
        moved = next((i for i, c in enumerate(pile) if c.name == expected), None)
        if moved is None:
            return {'status': 'error', 'message': '选中的卡牌已不在原处'}
        index = moved

    buried = pile.pop(index)
    room.magic_discard.append(buried)

    # 无论有没有摸到牌，这次选择都已经用完：先清空待选择状态，避免重复结算
    room.magic_temp_data = {}

    # draw_card 内部会 emit hand_updated（摸到重名卡时那张会自动进弃牌堆）。
    # 先记下摸牌前的牌堆张数：摸牌后牌堆可能正好空掉，
    # 用它才能区分「本来就没牌可摸」和「摸到重名牌被丢弃」。
    deck_size_before = len(room.magic_deck) if isinstance(room.magic_deck, list) else 0
    drawn = room.draw_card(player_id)
    if opponent is not None:
        # 对方手牌少了一张，需要单独同步（draw_card 只通知施法者自己）
        emit('hand_updated', {'hand': opponent.magic_hand}, to=opponent.sid)

    # 摸牌可能被规则挡下（牌堆空 / 无中生有封锁 / 摸到重名牌自动进弃牌堆）。
    # 这些情况原先都是静默的，玩家只会看到「没有摸到牌」而不知为何 —— 如实说明。
    if drawn is not None:
        detail = f'埋葬了「{buried.name}」，并摸到了「{drawn.name}」'
    elif room.players[player_id].effect_flags.no_draw:
        detail = f'埋葬了「{buried.name}」，但「无中生有」生效中，本大回合无法摸牌'
    elif deck_size_before == 0:
        detail = f'埋葬了「{buried.name}」，但牌堆已空，没能摸到牌'
    else:
        detail = f'埋葬了「{buried.name}」，摸到的牌与手牌重复，已直接进弃牌堆'

    add_game_log(room, f'第{room.round}回合 · {_log_name(room, player_id)} 的【明智埋葬】{detail}',
                 'magic', {'caster': player_id, 'card': '明智埋葬', 'buried': buried.name})
    return {'status': 'success', 'message': detail}


# select_magic_target 允许客户端提交的字段白名单（其余一律丢弃）
_SELECTION_TARGET_KEYS = {
    'caster_choice', 'opponent_choice', 'card_index', 'ship_indices',
    'effect_choice', 'prediction', 'index', 'target_area', 'target_line',
    'source', 'source_index', 'chosen_index',
}


# 添加新的Socket事件处理
@socketio.on('select_magic_target')
@_require_live_room
def handle_magic_target(data):
    room_id = data['room_id']
    player_id = data['player_id']
    target_data = data['target_data']
    temp_data_id = data['temp_data_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 存储临时目标数据（仅接受"选择类"字段）
    # 安全：此前直接合并客户端任意 JSON，可注入 pending_placement 等
    # 服务端状态，从而无限增援战舰。这里白名单过滤，禁止覆盖服务端键。
    if not isinstance(target_data, dict):
        return {'status': 'error', 'message': '目标数据格式错误'}
    safe_target_data = {k: v for k, v in target_data.items()
                        if k in _SELECTION_TARGET_KEYS}
    room.magic_temp_data = {**room.magic_temp_data, **safe_target_data}

    # 需要选择的操作：全部委托给 confirm_magic_target（前端唯一在用的入口）。
    # 此前这里是第二套独立实现，与在用的那份语义已经漂移：桃园结义剩余牌
    # 进「弃牌堆」（在用版是放回牌堆）、不采用对方自选的 opponent_choice、
    # 也不广播 hand_updated / taoyuan_complete。两份实现并存 = 修一处漏一处。
    if temp_data_id in ('taoyuan_choice', 'bury_choice', 'shield_choice', 'wangyang_choice'):
        return confirm_magic_target({
            'room_id': room_id,
            'player_id': player_id,
            'temp_data_id': temp_data_id,
            'target_data': safe_target_data,
        })

    # 未知 temp_data_id：保持历史行为（只存不结算）
    return {'status': 'success'}


# 修改攻击处理函数，添加魔法效果检查
def frozen_ship_count(player) -> int:
    """统计处于冻结状态的战舰数（冻结的船不提供攻击次数）。

    ⚠️ 只能算【还活着】的船（2026-09-17）。攻击次数是
    `remaining_ships - frozen_ship_count(...)`，而 `remaining_ships` 早已把沉船
    排除在外了；这里若按 `player.ships` 全量统计（沉船仍留在列表里），
    沉掉的那艘就会被【重复扣一次】。实测玩家报的「冻结通过后被冻结方的攻击次数
    计算出问题」就是这个：冻住 3 艘、其中 1 艘后来被打沉 →
    5 - 3 = 2，而正确值是 5 - 2 = 3（死掉的那艘本来就不提供次数）。
    """
    return sum(1 for s in _alive_ships(player) if getattr(s, 'frozen', None))


def _grant_subsidy_bonus(room, holder_id: str) -> bool:
    """百亿补贴：持卡者的船被击败时，给【持卡者自己】累计 +3 次攻击。

    卡面：「接下来如果自己的船被对方击败了，自己的攻击次数每有一艘船死亡就加3」。
    原实现直接加在 room.attacks_remaining（属于当前攻击者 = 对手），
    等于把奖励送给了对手，且下回合重算后持卡者永远拿不到。
    """
    player = room.players.get(holder_id)
    if not player or not player.effect_flags.subsidy:
        return False
    flags = player.effect_flags
    flags.subsidy_bonus = int(getattr(flags, 'subsidy_bonus', 0) or 0) + 3
    emit('message', {'text': '百亿补贴生效，你的攻击次数 +3'}, to=player.sid)
    return True


def _count_stats_for(room) -> bool:
    """人机对局是否计入战绩。

    打电脑必胜，若算进 users.wins / 连胜，排行榜（按 wins DESC 排序）与个人战绩
    都会被刷成假数据（线上账号 z1w6qn 的「3 胜 0 负 3 连胜」全部来自人机）。
    人机对局仍写入 matches 表以便回看历史，只是不参与统计。
    """
    return not getattr(room, 'is_ai_room', False)


# ============ 对局结算收口（2026-09-17 第 2 批） ============
# 对局结束写库原先散在 6 处，各自 `try/except` 包着 `db.record_match`。
# 本批要加「累计击沉 / 场次 / 零伤获胜 / 最快用时」四项每局事实，再照着原样改 6 个
# 地方就是 6 份实现 —— 与「通用教训二：同一个业务判断有两份实现，就一定会漂移」
# 同源。所以先收口：6 处统一调 `_finalize_match()`，加统计只改一处。
#
# ⚠️ 注释与文档里**不要写出调用形式**（`db.record_match` 后面跟括号）：
# `tests/test_stats_display_fixes.py::test_every_record_match_call_site_passes_count_stats`
# 用正则扫全文（注释也算），会把注释里的字面量当成一处"漏传 count_stats"的调用点。
# 本文件里该方法只应出现在 `_finalize_match` 内部，且必须带 `count_stats=`。


def _match_duration_sec(room) -> int:
    """本局用时（秒）。拿不到开始时间就返回 0（= "没有可信用时"，不是 0 秒获胜）。"""
    start = _match_started_at(room)
    if not start:
        return 0
    elapsed = int(time.time() - start)
    return elapsed if elapsed > 0 else 0


# ===========================================================================
# 反作弊：结算前的事实提取 + 判定（2026-09-19）
#
# 判据在 `anticheat.py`（纯函数，唯一一份）；这里只负责**从房间对象取事实**——
# 与「规则只留一份、server 只组装」这条老规矩一致（`ranks.py` / `leveling.py` 同形）。
#
# ⚠️ 事实必须全部取自**服务端内存对象**：不解析对局日志、不信客户端上报。
#    第一版规则曾靠 `matches.winner_id`（user_id）去对齐日志里的 `detail.attacker`
#    （socket sid）——两套 id 根本比不了，结果在已知 166 局作弊上召回率 **0%**，
#    而单测全绿。教训：判据的输入必须来自**同一套 id 空间**。
# ===========================================================================
def _anticheat_facts(room, winner_id, loser_id) -> dict:
    """组装反作弊判据需要的事实（取不到的一律留空，绝不影响结算）。"""
    facts = {}
    try:
        winner = room.players.get(winner_id)
        loser = room.players.get(loser_id)

        # 本局开到第几回合（`room.round` 是服务端权威值）
        facts['rounds'] = max(0, int(getattr(room, 'round', 0) or 0))

        # 双方各自的"命中次数" —— 用**船上被打中的格子数**，与 `_took_any_damage` 同口径
        def _hits(p):
            if p is None:
                return 0
            return sum(len(getattr(s, 'hits', None) or []) for s in (getattr(p, 'ships', None) or []))

        wh, lh = _hits(winner), _hits(loser)
        facts['attacker_total_hits'] = wh
        facts['defender_total_hits'] = lh
        facts['loser_total_hits'] = lh

        # 形态特征：本局有几个玩家真正打中过对方 + 单方最大命中数
        # （不依赖 id 对齐 —— 见上面那段教训）
        n_shooters = (1 if wh > 0 else 0) + (1 if lh > 0 else 0)
        facts['attackers'] = ['a'] * n_shooters if n_shooters else []
        facts['max_hits'] = max(wh, lh)

        # 双方总船数（对手船数 = 判"全歼"的分母）
        w_ships = len(getattr(winner, 'ships', None) or []) if winner else 0
        l_ships = len(getattr(loser, 'ships', None) or []) if loser else 0
        facts['foe_ships'] = l_ships
        facts['total_ships'] = w_ships + l_ships     # 0 = 棋盘是空的，对局没真进行
        facts['duration_sec'] = _match_duration_sec(room)
        facts['ended_by'] = getattr(room, 'end_reason', None) or 'attacks'
    except Exception:
        pass
    return facts


def _anticheat_assess(room, winner_id, loser_id) -> dict:
    """对局结算前的反作弊判定（失败开放：出错就当"干净"，绝不阻断结算）。"""
    try:
        facts = _anticheat_facts(room, winner_id, loser_id)
        return anticheat.evaluate(facts)
    except Exception:
        return {'score': 0, 'level': 'clean', 'reasons': [], 'rules': [], 'blocked': False}


def _anticheat_report(room, winner_id, loser_id, result):
    """把判定结果落库（审计）+ 打日志。绝不允许把结算搞崩。"""
    try:
        if not result or result.get('level') == 'clean':
            return
        detail = anticheat.explain(result)
        try:
            db.record_anticheat_flag(
                match_id=getattr(room, 'id', '') or '',
                rule=','.join(result.get('rules') or []),
                severity=result.get('level') or '',
                detail=detail,
            )
        except Exception:
            pass
        print(f'[anticheat] room={getattr(room, "id", "?")} '
              f'score={result.get("score")} level={result.get("level")} :: {detail}')
    except Exception:
        pass


# ===========================================================================
# 累计嫌疑度 + 阶梯封禁（2026-09-20）
#
# 分工（**别混**）：
#   · `anticheat.py`  —— 判**一局**
#   · `suspicion.py`  —— 判**一个人**（把参与过的可疑局按时间衰减累计）
#   · 本段            —— 取数、落库、在关键入口**执行**封禁
#
# 三档封禁（等级由嫌疑度算出来，**绝不单独存** —— 见 `suspicion.py` 头部）：
#   1 = 禁排位   2 = 禁匹配   3 = 禁房间
# ===========================================================================
def _suspicion_matches_for(uid: str) -> list:
    """取某人的历史对局嫌疑度，并按"现在"折算 age_days。

    ⚠️ **时间必须在调用时算**（`age_days = (now - created_at) / 86400`），
    不能存进库 —— 存进去的话数值第二天就过期了，
    这正是本项目「会兜底的取数函数不能当判据」那类坑的同形。
    """
    try:
        rows = db.get_match_suspicion(uid)
    except Exception:
        return []
    now = time.time()
    out = []
    for r in rows or ():
        try:
            age = max(0.0, (now - float(r.get('created_at') or now)) / 86400.0)
        except (TypeError, ValueError):
            age = 0.0
        out.append({'score': r.get('score'), 'age_days': age})
    return out


def _suspicion_level(uid: str) -> int:
    """某人当前**实际生效**的封禁等级（含管理员覆盖）。失败开放为 0。

    ⚠️ 这里查两次库（明细 + 覆盖）。结算路径上每局每人一次，
    在本项目的量级（几十个账号）完全可接受；真到上万账号再加缓存。
    """
    if not uid:
        return 0
    try:
        score = suspicion.accumulate(_suspicion_matches_for(uid))
        override = db.get_anticheat_override(uid)
        return suspicion.effective_level(score, override)
    except Exception:
        return 0                 # 失败开放：算不出来就别拦人


def _capability_denied(uid: str, cap: str) -> str:
    """该用户做某件事是否被禁。返回**拒绝文案**（空串 = 放行）。

    文案统一由 `suspicion.denial_message` 生成 —— **前端不许自己拼**，
    避免"两份实现必然漂移"，也避免各处措辞不一泄露判据。
    """
    try:
        lv = _suspicion_level(uid)
        return suspicion.denial_message(lv, cap)
    except Exception:
        return ''               # 失败开放


def _record_match_suspicion_for(room, result):
    """把这一局的嫌疑度**按人**落库（双方各一条，含正常局）。

    为什么双方都要记：累计要算"这个人参与过多少可疑局"，
    所以**被打的一方同样要记**（他自己可能就是靶子账号）。

    为什么每局都记（含 score=0）：累计口径是"全部对局"，
    只记可疑局的话，就无法区分"打了 10 局全是可疑"与"打了 1000 局里有 10 局可疑"。
    """
    try:
        score = int((result or {}).get('score') or 0)
        level = str((result or {}).get('level') or '')
        room_id = getattr(room, 'id', '') or ''
        if not room_id:
            return
        uids = set()
        for p in (getattr(room, 'players', None) or {}).values():
            u = getattr(p, 'user_id', None)
            if u:
                uids.add(u)
        for u in uids:
            try:
                db.record_match_suspicion(room_id, u, score, level)
            except Exception:
                continue
    except Exception:
        pass


def _achievement_stats(uid: str) -> dict:
    """组装 `achievements.evaluate()` 需要的输入（结算路径用）。

    ⚠️ 组装**只有一份实现**：`db.get_achievement_stats()` —— 接口/图鉴路径（`api.py`）
    调的是同一个。曾经这里与 api.py 各拼一份：当时两份都覆盖了
    `achievements.CONTEXT_KEYS` 全集，所以结论一致；但那是巧合而非保证 ——
    谁漏加一个键，对应判据就会静默恒假（`achievement_context` 把缺字段按 0 算，不报错），
    正是本项目反复踩的「同一个业务判断有两份实现，就一定会漂移」。
    """
    return db.get_achievement_stats(uid)


def _bump_match_counters(room, winner, loser, winner_user_id, loser_user_id):
    """把这一局的「每局事实」累加进 `user_counters`。

    | 字段 | 这一局的值 |
    | --- | --- |
    | `sunk_total` | **对方的**沉船数（口径见 `_dead_ship_count`） |
    | `matches_played` | 双方各 +1（真人对局才有意义 —— 人机由调用方拦掉） |
    | `flawless_wins` | 赢家全场没被打中过 → +1 |
    | `fastest_win_sec` | 赢家本局用时（只在拿到开始时间时给；DAO 负责"取最小非零"） |

    输的一方拿不到 `flawless_wins` / `fastest_win_sec` —— 这两个字段的定义就是
    "获胜时的表现"，输了不该产生候选值。
    """
    duration = _match_duration_sec(room)
    if winner_user_id:
        db.bump_user_counters(
            winner_user_id,
            sunk_total=_dead_ship_count(loser),
            matches_played=1,
            flawless_wins=0 if _took_any_damage(winner) else 1,
            fastest_win_sec=duration,
        )
    if loser_user_id:
        db.bump_user_counters(
            loser_user_id,
            sunk_total=_dead_ship_count(winner),
            matches_played=1,
        )


def _grant_match_achievements(room, candidates):
    """按最新 stats 评估徽章、授予新增的，并给房间播报一句。

    `candidates` 是 `[(player, user_id), ...]`；返回 `[(user_id, [badge_id...]), ...]`，
    只含**本次新解锁**的（`grant_user_achievements` 靠主键幂等，不会把老徽章再念一遍）。

    判据**不在这里**：一律走 `achievements.evaluate()`（计划 §2.2.2 冻结的唯一一份）。
    """
    newly = []
    for player, uid in (candidates or ()):
        if not uid:
            continue
        granted = db.grant_user_achievements(uid, achievements.evaluate(_achievement_stats(uid)))
        if not granted:
            continue
        newly.append((uid, granted))
        try:
            display = getattr(player, 'name', None) or '玩家'
            names = '、'.join((achievements.name_of(bid) or bid) for bid in granted)
            # 沿用现有播报风格：整房间一条 message（`_finish_game` 等出口本来就
            # 紧接着 emit('game_over', room=...)），所以这里 emit 到房间是安全的。
            emit('message', {'text': f'{display} 解锁了新徽章：{names}'}, room=room.id)
            # ★ 结算提示：再**只发给本人**一条结构化事件。
            #   上面那条是给全房间看的（对手也看得到有人解锁了），而"本局刚解锁了哪几枚"
            #   是玩家自己的结算反馈 —— 前端拿它在结算界面弹一块「本局刚解锁」。
            #   只发本人：对手不需要收到，也避免以后有人拿它做"偷看别人进度"的入口。
            items = [d for d in (achievements.details(bid) for bid in granted) if d]
            sid = getattr(player, 'sid', None)
            if sid and items:
                emit('achievements_unlocked', {'items': items, 'count': len(items)}, room=sid)
        except Exception:
            # 播报失败不影响已经写进库的解锁
            pass
    return newly


def _finalize_match(room, winner_id, loser_id, streak_ctx=None):
    """对局结算的**唯一收口**：写战绩 → 累加每局统计 → 评估并授予徽章 → 播报。

    6 处对局结束（`_finish_game_win` / `_finish_game` / 掉线判胜 / 投降 / 回光返照判负 /
    魔法卡消灭最后一艘船）全部改调这里，别再各自写 `db.record_match` 调用。

    返回 `[(user_id, [badge_id...]), ...]`（本次新解锁的徽章）。

    **语义与改动前逐点对齐**（收口不能顺手改行为）：
      · 取不到 `room.players[...]`（KeyError）→ 整段不做（原来 `try` 包住了一切）；
      · 双方都不是登录用户 → 不写战绩、也不累计任何个人统计；
      · 人机对局 → 仍然写历史，但**不计统计、不发徽章**（`_count_stats_for`，
        与「人机不计入 wins / 连胜」同一口径：打电脑刷不出徽章）。

    **调用方不需要再包 `try/except`**：本函数内部吞掉所有异常（统计绝不允许把
    对局结算搞崩 —— 第 1 批就定下的风格，`db.py` 里每个 DAO 也是这么写的）。

    `streak_ctx`（2026-09-18 多因子批）：**赛前**连胜 / 连败上下文，由本函数开头
    自己算好（见下面 ⓪ 段）。参数是留给**测试**显式注入的（默认 None = 自己算），
    正常调用方一个都不传 —— 6 处调用点因此不需要改签名。
    """
    newly = []
    try:
        winner = room.players[winner_id]
        loser = room.players[loser_id]
    except Exception:
        return newly

    winner_user_id = getattr(winner, 'user_id', None)
    loser_user_id = getattr(loser, 'user_id', None)
    count_stats = _count_stats_for(room)

    # ⓪ **赛前上下文必须在写库之前取**（★ 这一段的位置就是这条功能的命门）。
    #    `record_match`（下一段 ①）会把这一局算进胜者的连胜，并把**败者的连胜清零**
    #    —— 那之后再读库，"本局是第几连胜 / 连败"读到的是**含本局**的值：
    #    表现为"第一局胜利就显示 1 连胜加成"（首胜不该有连胜加成），而且**不报错**。
    #    连败没有单独的列，要从 `matches` 表按 timestamp 倒着数，同样只能在写库前数。
    if streak_ctx is None:
        try:
            streak_ctx = _streak_context(winner, winner_user_id, loser, loser_user_id)
        except Exception:
            # 取不到就当"没有连胜/连败历史"（少给两个加成，但绝不许把结算搞崩）
            streak_ctx = {}

    # ① 写战绩（历史 + 胜负 / 连胜）
    if winner_user_id or loser_user_id:
        try:
            db.record_match(winner_user_id or winner_id, loser_user_id or loser_id,
                            getattr(room, 'game_logs', None), count_stats=count_stats)
        except Exception:
            pass

    if not count_stats:
        # 人机对局到此为止：只留下可回看的历史，不累计统计、不发徽章。
        # ⚠️ 但"对局中 → 不在局中"这一步**不能跟着被跳过**（人机房结束也要摘标记，
        #    否则打完人机的账号会永远显示"对局中"）—— 所以先摘标记再 return。
        _release_presence_game(room)
        return newly

    # ② 每局统计
    try:
        _bump_match_counters(room, winner, loser, winner_user_id, loser_user_id)
    except Exception:
        pass

    # ③ 徽章（判据在 achievements.evaluate，这里只负责组装 stats 与授予）
    try:
        newly = _grant_match_achievements(room, ((winner, winner_user_id), (loser, loser_user_id)))
    except Exception:
        pass

    # ④ 经验 / 等级（2026-09-17 追加）—— 与徽章一样，**只给登录用户**、只走这个收口。
    try:
        _grant_match_xp(room, ((winner_id, winner, winner_user_id, True),
                               (loser_id, loser, loser_user_id, False)))
    except Exception:
        pass

    # ⑤ 排位段位加减分（2026-09-17 排位批）—— 同样只追加，不动上面四段。
    #    门槛见 `_ranked_settlement_allowed`：排位房 + 计统计 + **真开打**，三条全满足
    #    才结算；休闲局 / 自定义房 / 人机局（`count_stats` 为假，上面已经 return 了）
    #    一分不加；赛前投降（还没猜完拳、没有开打打点）也不给分。事件在这里只**组装**，
    #    发送时机由 `_dispatch_rank_events` 决定（必须在调用方的 `game_over` 之后到前端）。
    #
    #    ★ 反作弊闸门（2026-09-19）：判定在**算分之前**，被判定为刷分的一律不给排位分。
    #      这是"让刷分不再有收益"的落点 —— 清理历史只是补救，闸门才是治本。
    #      ⚠️ 判据与取事实都失败开放：反作弊出任何问题都不许影响正常结算。
    ac_result = _anticheat_assess(room, winner_id, loser_id)
    _anticheat_report(room, winner_id, loser_id, ac_result)
    # ★ 累计批（2026-09-20）：把这一局的分数**按人**记下来（双方各一条，含正常局）。
    #   累计封禁要按"这个人参与过哪些局"算，所以必须每局都记 ——
    #   只记可疑局就无法区分"打 10 局全是可疑"与"打 1000 局里 10 局可疑"。
    _record_match_suspicion_for(room, ac_result)

    try:
        rank_events = _settle_ranked_match(room, winner_id, loser_id, streak_ctx) \
            if (_ranked_settlement_allowed(room, count_stats)
                and not ac_result.get('blocked')) else []
    except Exception:
        rank_events = []
    try:
        _dispatch_rank_events(room, rank_events)
    except Exception:
        pass

    # ⑥ 好友功能：结算钩子（2026-09-18）—— 给**双方各发一条** `recent_opponent`，
    #    让结算面板上能直接"加他好友 / 同意申请"。挂在这里的理由：`_finalize_match`
    #    是对局结束的**唯一收口**（6 处结束路径全调它），挂在别处就会漏路径 /
    #    出现 6 份实现（"同一个判断有两份实现就一定会漂移"）。
    #    顺序：放在 ⑤ 之后、`return` 之前 —— 既要排在段位事件之后，也不许占用人机
    #    那条早退路径（人机/游客本来就一条都不发，`_recent_opponent_payloads` 返回空）。
    #    ⚠️ 整段自己吞异常：好友关系 DAO（`db.get_friend_relation`，好友批另一个
    #    智能体实现）可能还没落地或临时出错，**绝不能因此把结算搞崩** ——
    #    `_friend_relation_safe` 已经兜了一手，这里再加一层。
    try:
        for _uid, _payload in _recent_opponent_payloads(
                winner, loser, winner_user_id, loser_user_id):
            _push_friend_event(_uid, 'recent_opponent', _payload)
    except Exception:
        pass

    # 结算完成 = 这局不再是"对局中"（人机那条早退路径上面已经摘过了，这里幂等）。
    _release_presence_game(room)

    return newly


def _grant_match_xp(room, rows):
    """结算发经验，并把"这一局涨了多少、要播几段动画"单独推给本人。

    `rows` = `[(player_id, player, user_id, is_winner), ...]`。

    为什么把**动画分段**放在服务端算：等级曲线只有 `leveling` 一份实现，
    前端要是自己算"下一级要多少"，就成了两份实现（第 2 批的教训）。
    所以这里下发 `segments`（每段：本级从 from 填到 to、够不够升级），前端只负责播动画。

    经验规则见 `leveling.match_xp`：参与 10 / 胜利 15 / 每击沉 2 / 零伤 10 / 闪电战 5。
    人机对局不发（与"打电脑不记统计、不发徽章"同一口径，`count_stats` 已经拦在前面了）。
    """
    for pid, player, uid, is_winner in (rows or ()):
        if not uid:
            continue
        try:
            cap = leveling.LEVEL_101 if db.has_user_perk(uid, profile_spec.PERK_LEVEL_101) \
                else leveling.MAX_LEVEL
            # 这一局的表现：击沉数 = 对方沉船数；零伤 = 自己一艘没沉；快局看对局时长
            foe = room.players.get(rows[1][0] if pid == rows[0][0] else rows[0][0])
            sunk = len(getattr(foe, 'sunken_ships', []) or []) if foe else 0
            flawless = bool(is_winner) and not (getattr(player, 'sunken_ships', []) or [])
            duration = _match_duration_sec(room)
            fast = bool(is_winner) and duration is not None and 0 < duration <= 180
            delta = leveling.match_xp(is_winner, sunk=sunk, flawless=flawless, fast=fast)
            before = db.get_user_xp(uid)
            after = db.add_user_xp(uid, delta)
            sid = getattr(player, 'sid', None)
            if not sid:
                continue
            emit('xp_gained', {
                'player_id': pid,
                'delta': int(max(0, after - before)),
                'xp_before': int(before),
                'xp_after': int(after),
                'win': bool(is_winner),
                'breakdown': leveling.xp_breakdown(is_winner, sunk=sunk, flawless=flawless, fast=fast),
                'before': leveling.level_view(before, cap),
                'after': leveling.level_view(after, cap),
                'segments': leveling.segments(before, after, cap),
            }, room=sid)
        except Exception:
            # 发经验失败不许把结算搞崩（与徽章同一条规矩）
            continue


# ============ 排位结算（2026-09-17 排位批） ============
# 加减段位分的**唯一收口点**就是 `_finalize_match` 末尾那一段：6 处对局结束
# （获胜 / 投降 / 断线判胜 / 回光返照 / 极限增援 / 卡牌消灭最后一艘船）都汇到那里，
# 所以"结算加分"只有一份实现 —— 与第 2 批为战绩 / 统计 / 徽章立下的规矩相同。


def _match_really_started(room) -> bool:
    """这局到底有没有**真开打**（只看显式打点，不许退回 `created_at`）。

    与 `_match_started_at` 的区别正是这条：后者在没有 `room.match_started_at` 时会退回
    `room.created_at`（建房时间，**含"等人入座"的等待时间**）—— 那个回退是给"闪电战用时"
    口径用的，不是给"这局开没开打"用的。拿它当开打判据的话，**任何真实房间都算已开打**
    （`created_at` 在 `GameRoom.__init__` 里无条件打点），门禁就形同虚设。

    `match_started_at` 的唯一打点是 `handle_rps_choice`（猜拳结束、真正进入 attacking 时），
    所以"有没有这个打点"就是"有没有真开打"。
    """
    return bool(getattr(room, 'match_started_at', None))


def _streak_context(winner, winner_user_id, loser, loser_user_id) -> dict:
    """取「**赛前**」的连胜 / 连败上下文（多因子加减分用）。

    ⚠️ **必须在任何写库动作之前调用** —— 唯一调用点是 `_finalize_match` 开头的 ⓪ 段，
       那里还没轮到 `record_match`。原因：
         · `users.current_streak` 只数**连胜**，且 `record_match` 会把它
           `+1`（胜者）/ 清零（败者）—— 写完之后再读就是**含本局**的值，
           于是"第一局胜利"会拿到 1 连胜加成（首胜根本不该有连胜加成）；
         · 连败**没有单独的列**，只能从 `matches` 表按 `timestamp` 倒着数连续负场，
           而 `record_match` 恰恰会往那张表里插入本局这一行。
       两个都不是"报错"，而是**静默算错** —— 所以这条顺序是这条功能的命门。

    返回 `{'win_streak_before', 'winner_loss_streak_before', 'lose_streak_before'}`：
      · `win_streak_before` = **胜者**赛前的连胜数（`current_streak`，本局胜之前）；
      · `winner_loss_streak_before` = **胜者**赛前的连败数 → 这就是本局**终结**的连败数
        （「终止连败」加成看的是**自己**之前连败了几场，见下面那条 ⚠️）；
      · `lose_streak_before` = **败者**赛前的连败数 → 给败者的「连败保护」用。

    ⚠️ **`winner_loss_streak_before` 与 `lose_streak_before` 是两个人的事，别合并**。
       第一版把"终结的连败数"直接等同于"败者赛前的连败数"，于是语义整个反了：
       **打赢一个正在连败的人会拿加成，而真正自己止住连败的人一分没有**。
       两个人的连败数都要查，只是分别用在两个人身上。
       （实测证据：真实 socket 连打三局，B 连败两场后赢下第三局 —— 明细里没有
        `streak_break`，而按定义那正是它该出现的场合。）

    ⚠️ 只读，不写库：用**独立游标**查 `matches`（与 db.py 里"共享游标会与写操作错位"
      那条注释同一个理由）。本函数失败一律返回全 0（少给两个加成，但绝不能把结算搞崩）。
    """
    ctx = {'win_streak_before': 0, 'winner_loss_streak_before': 0, 'lose_streak_before': 0}

    row = db.get_user(uid=winner_user_id) if winner_user_id else None
    if row:
        try:
            ctx['win_streak_before'] = max(0, int(row.get('current_streak') or 0))
        except (TypeError, ValueError):
            ctx['win_streak_before'] = 0

    ctx['winner_loss_streak_before'] = _consecutive_losses(winner_user_id)
    ctx['lose_streak_before'] = _consecutive_losses(loser_user_id)
    return ctx


def _consecutive_losses(uid) -> int:
    """某人**当前**连续输了几场（从 `matches` 表按 timestamp 倒着数）。

    ⚠️ **必须在 `record_match` 写库之前调用** —— 它会把本局那一行也插进 `matches`，
    晚一步数出来就是**含本局**的值（"第一局胜利"会被算成刚终结了 1 连败）。

    连败没有单独的列（`users.current_streak` 只数连胜、输一局就被清零），
    所以只能从历史数。只读、独立游标、失败返回 0。
    """
    if not uid:
        return 0
    cursor = None
    try:
        cursor = db.db.conn.cursor()
        cursor.execute(
            'SELECT winner_id FROM matches WHERE winner_id = ? OR loser_id = ? '
            'ORDER BY timestamp DESC LIMIT 50',
            (uid, uid))
        streak = 0
        for match_row in cursor.fetchall():
            if str(match_row['winner_id']) == str(uid):
                break          # 上一场是胜仗：连败到这里就断了
            streak += 1
        return streak
    except Exception:                                             # noqa: BLE001
        return 0
    finally:
        try:
            if cursor is not None:
                cursor.close()
        except Exception:                                         # noqa: BLE001
            pass


def _ranked_settlement_allowed(room, count_stats: bool) -> bool:
    """这一局该不该加减段位分：三条**同时**满足才结算。

    ① `room.ranked` —— 排位房（匹配成功时置位）；自定义房 / 人机房恒 False
       （自定义房双方可以互相刷分，人机房打电脑必胜）；
    ② `count_stats` —— 人机局不算（与"人机不计 users.wins / 不发徽章"同一口径）；
    ③ `_match_really_started(room)` —— **没真开打的不给分**：两个账号匹配成功后
       在摆船阶段直接投降、让对手白拿 +20，是最直接的刷分口子，必须堵。

    ⚠️ ③ **不能**写成 `_match_started_at(room) != 0`：那个函数在没有打点时退回
    `created_at`（真实房间恒非 0），用它当门禁等于没拦（详见 `_match_really_started`）。
    """
    if not bool(getattr(room, 'ranked', False)):
        return False
    if not count_stats:
        return False
    return _match_really_started(room)


def _emit_rank_events_now(events):
    """把 `[(sid, payload), ...]` 逐个发给本人（只发本人那一份，对手不需要）。"""
    for sid, payload in (events or ()):
        if not sid:
            continue
        try:
            emit('rank_changed', payload, room=sid)
        except Exception:
            # 发事件失败不许把已经落库的加减分搞崩（与徽章 / 经验同一条规矩）
            continue


def _dispatch_rank_events(room, events):
    """决定段位事件"什么时候"发：必须在 `game_over` **之后**到前端。

    ⚠️ 结算发生在**别人的 socket 请求**上下文里（投降 / 断线判胜 / 出牌打死最后一艘船
    都会走到这里），而 6 处调用点都是「先 `_finalize_match`，紧接着 `emit('game_over')`」。
    同步在这里 emit 的话 `rank_changed` 会**先于**结算面板到达，前端就会先弹段位面板。
    所以：有请求上下文时交给后台任务（脱离请求上下文后再发，那时 game_over 已经发出去了）
    —— 这正是本项目「在别人的 socket 请求里做事要先 start_background_task」那条硬教训；
    没有请求上下文（单测直调 / 自己已经在后台任务里）时直接发，保证顺序确定、可测。
    """
    if not events:
        return
    try:
        in_request = bool(has_request_context())
    except Exception:
        in_request = False
    if in_request:
        socketio.start_background_task(_emit_rank_events_now, events)
    else:
        _emit_rank_events_now(events)


def _settle_ranked_match(room, winner_id, loser_id, streak_ctx=None):
    """排位结算：多因子算分（`ranks.match_points`）→ 落库 → 组装 `rank_changed`。

    返回 `[(sid, payload), ...]`，每个**真人**玩家一条（`Player.user_id` 为空的游客
    与 AI 直接跳过，绝不写库）。

    每局加/扣多少由 `ranks.points_breakdown` 一处算出来（`docs/RANKED_2026_09_17.md` §2.5
    冻结的计分表）：胜负基础分 + 连胜 / 终止连败 / 闪电战 / 零伤 / 击沉 / 越级挑战 等因子，
    败局另有减免项并封在 `ranks.POINTS_LOSS_FLOOR`。**这里不重算任何因子**，
    只负责"把赛前事实取齐、算出来、落库、组装事件"。

    几个必须守住的点（都是冻结契约里写死的）：
      · **先读旧分再写**，`after` 一律**重新读库**得到 —— 不许用 `before + delta` 算
        （0 分封底时那样算是错的：5 分输一局实际只掉 5 分）；
      · `clamped` 透传 `ranks.apply_delta(before, delta)` 的第二个返回值；
      · `delta` 填**实际**变化量 `after - before`；`breakdown_total` 是**理论**值
        （封底前）—— 两个都要有，前端要拿它解释"为什么扣得比 −15 少"；
      · 大舰长要**两个玩家都写完分之后**再统一算一次船长池（先写的那个看到的是旧池子）；
      · `before` / `after` 是 `ranks.rank_view(...)` 的**原样返回**，`server_rank` 用
        `db.get_rank_position(uid)` 取（结算之后再取一次，让名次反映最新状态）；
      · `streak_ctx` 是**赛前**上下文（由 `_finalize_match` 开头取好，见 `_streak_context`）。

    ⚠️ **沉船数用 `_dead_ship_count`**（不是 `len(player.ships)`：本项目沉船**不移出**
      `ships`，那样数会得到"一艘都没沉"）。`sunk` = 对手棋盘上被击沉的船数，
      `lost` = 自己沉的船数；同理"零伤"取 `_dead_ship_count(自己) == 0`。
    """
    ctx = dict(streak_ctx or {})
    uname = getattr(room, 'players', None) or {}

    def _tier_of(uid, player):
        """段位下标——**结算前**取（写库后取到的就不是"赛前段位"了）。"""
        if not uid:
            return 0
        try:
            row = db.get_user_rank_row(uid)
            return int(ranks.points_tier_index(row.get('points') or 0))
        except Exception:
            return 0

    # 这一局的两份"赛前事实"：用时 / 大回合数（双方共用）+ 双方段位
    seconds = int(_match_duration_sec(room))
    rounds = max(0, int(getattr(room, 'round', 0) or 0))
    tiers = {pid: _tier_of(getattr(uname.get(pid), 'user_id', None), uname.get(pid))
             for pid in (winner_id, loser_id)}

    rows = []
    for pid, is_winner in ((winner_id, True), (loser_id, False)):
        player = room.players.get(pid)
        uid = getattr(player, 'user_id', None) if player else None
        if not uid:
            # 游客（或人机）：没有账号可写，跳过。绝不为此建一行 0 分的段位记录。
            continue
        foe_id = loser_id if is_winner else winner_id
        foe = room.players.get(foe_id)
        # 口径统一：沉船数一律走 `_dead_ship_count`（沉船不移出 `ships`，别数列表长度）
        sunk = _dead_ship_count(foe) if foe is not None else 0
        lost = _dead_ship_count(player)
        tier = tiers.get(pid, 0)
        opp_tier = tiers.get(foe_id, 0)
        factors = {
            'win_streak': (max(0, int(ctx.get('win_streak_before') or 0)) + 1)
                          if is_winner else 0,
            'lose_streak': (max(0, int(ctx.get('lose_streak_before') or 0)) + 1)
                           if not is_winner else 0,
            # ⚠️ **「终止连败」看的是胜者自己**赛前连了几场败（本局赢下来把它终结了），
            # 不是"败者赛前连败数"。第一版取的是后者（`ctx['loss_streak_broken']`
            # 直接等于败者的 `lose_streak_before`），语义整个反了 —— 后果是
            # **打赢一个正在连败的人反而拿加成**，而真正"自己止住连败"的人一分没有。
            # 实测抓到的（真实 socket 连打三局）：B 连败两场后赢下第三局，
            # 明细分文没有 `streak_break`；而按定义那正是它该出现的场合。
            'loss_streak_broken': max(0, int(ctx.get('winner_loss_streak_before') or 0))
                                  if is_winner else 0,
            'seconds': seconds,
            'rounds': rounds,
            'sunk': sunk,
            'lost': lost,
            'my_tier': tier,
            'opp_tier': opp_tier,
        }
        # 分只由 ranks 一处算（明细 + 总数同源，见 points_breakdown 里那条断言）
        base, bonuses, total = ranks.points_breakdown(bool(is_winner), **factors)
        delta = int(total)
        before_row = db.get_user_rank_row(uid)
        before_pts = int(before_row.get('points') or 0)
        # 0 分封底：clamped 由 apply_delta 判定；真正落库的值以写完后重读为准
        _predicted, clamped = ranks.apply_delta(before_pts, delta)
        db.add_rank_points(uid, delta)
        rows.append({
            'player': player,
            'uid': uid,
            'is_winner': bool(is_winner),
            'clamped': bool(clamped),
            'before_pts': before_pts,
            'before_admiral': bool(before_row.get('is_admiral')),
            'before_server_rank': db.get_rank_position(uid),
            'base': int(base),
            'bonuses': bonuses,
            'breakdown_total': int(total),
        })

    if not rows:
        return []

    # 大舰长：两个玩家都写完分之后统一算一次船长池
    pool_size = db.count_rank_at_least(ranks.CAPTAIN_FLOOR)
    pool = db.captains_ordered(limit=500)
    pool_positions = {}
    for item in (pool or ()):
        key = str(item.get('user_id'))
        if key not in pool_positions:
            pool_positions[key] = item.get('pool_position')

    events = []
    for row in rows:
        uid = row['uid']
        # 池内名次（不在船长池里 → None）。晋升判定与展示都用这一份口径。
        pool_position = pool_positions.get(str(uid))

        after_row = db.get_user_rank_row(uid)
        after_pts = int(after_row.get('points') or 0)

        # 大舰长晋升 / 掉回船长：判据与中文原因都由 ranks 给（别在这里自己编文案）
        ok, admiral_reason = ranks.can_promote_to_admiral(after_pts, pool_position, pool_size)
        admiral_promoted = bool(ok) and not row['before_admiral']
        admiral_demoted = bool(row['before_admiral']) and not ok
        if ok:
            db.add_rank_points(uid, 0, is_admiral=True)
        elif row['before_admiral'] and not ranks.ADMIRAL_STICKY:
            # `ranks.ADMIRAL_STICKY` 默认 False → **动态**称号：条件不满足要掉回船长。
            # 开启粘性（True）时不动这一列 —— 那正是"粘性"的含义，
            # 与 `ranks.is_admiral` 的判据保持一致（它也是先看粘性标记）。
            db.add_rank_points(uid, 0, is_admiral=False)

        # 写完（含上面那次 0 分改写）再读一次：下发的一切都反映最新落库状态
        final_row = db.get_user_rank_row(uid)
        after_pts = int(final_row.get('points') or 0)
        after_admiral = bool(final_row.get('is_admiral'))
        server_rank = db.get_rank_position(uid)

        # 升降级摘要（小级 / 大段）：只认 ranks.solve_delta，别在 server 里重算
        summary = ranks.solve_delta(row['before_pts'], after_pts)
        before_view = ranks.rank_view(row['before_pts'], is_admiral=row['before_admiral'],
                                      server_rank=row['before_server_rank'],
                                      captain_pool_rank=pool_position)
        after_view = ranks.rank_view(after_pts, is_admiral=after_admiral,
                                     server_rank=server_rank,
                                     captain_pool_rank=pool_position)

        events.append((getattr(row['player'], 'sid', None), {
            'role': 'winner' if row['is_winner'] else 'loser',
            # 实际生效的分差（封底时可能小于 -15）
            'delta': int(after_pts - row['before_pts']),
            'clamped': row['clamped'],
            'points_before': int(row['before_pts']),
            'points_after': int(after_pts),
            'before': before_view,
            'after': after_view,
            'promoted': bool(summary['promoted']),
            'demoted': bool(summary['demoted']),
            'tier_up': bool(summary['tier_up']),
            'tier_down': bool(summary['tier_down']),
            'admiral_promoted': admiral_promoted,
            'admiral_demoted': admiral_demoted,
            # 没晋升时说明"还差什么"（前端可能拿它显示条件）
            'admiral_reason': admiral_reason,
            # ---- 多因子明细（2026-09-18 追加；上面一个字段都没删/没改名）----
            # `delta` 是**实际**变化量（0 分封底时可能是 0），`breakdown_total` 是
            # **理论**值（封底之前）—— 两个都要有：前端靠它解释"为什么这局扣得比 −15 少"。
            'base': int(row['base']),
            'bonuses': [dict(b) for b in row['bonuses']],
            'breakdown_total': int(row['breakdown_total']),
            # 进度条动画路径（与 leveling.segments 同形；曲线只有 ranks 一份实现）
            'segments': ranks.segments(row['before_pts'], after_pts),
        }))
    return events


def _check_last_chance(room, attacker_id: str, defender_id: str) -> bool:
    """回光返照：对使用者的船造成伤害则其直接判负。返回是否触发。"""
    eff = room.game_effects.get('last_chance')
    if eff and eff.get('caster') == defender_id and eff.get('round', room.round) == room.round:
        room.state = 'game_over'
        room.winner = attacker_id
        add_game_log(room, f"第{room.round}回合 · {_log_name(room, defender_id)} 触发回光返照失败并判负", 'result', {
            'winner': attacker_id,
            'loser': defender_id
        })
        # 记录战绩 + 每局统计 + 徽章（统一收口，见 _finalize_match）
        _finalize_match(room, attacker_id, defender_id)
        emit('game_over', {'winner': attacker_id}, room=room.id)
        return True
    return False


def _mark_ship_sunken(player, ship):
    """把一艘船登记进沉船堆（带去重）。

    ⚠️ 全项目登记沉船都必须走这里。本项目的「击沉」不会把船移出 ships，
    所以同一艘船对象会在"沉→复活→再沉"的循环里被反复登记；不去重就会在
    sunken_ships 里留下重复引用，进而造成：
      · 幽灵计数：复活类 pop() 到重复条目时船其实还活着 → 只加 remaining_ships、
        棋盘上却没有船复活（玩家实测报的"疗愈后战舰并没有复活"）；
      · 一艘船被复活两次，船数突破 6 艘上限。
    返回 True 表示本次真的新增了一条。
    """
    if ship is None:
        return False
    sunken = getattr(player, 'sunken_ships', None)
    if sunken is None:
        player.sunken_ships = sunken = []
    if ship in sunken:
        return False
    sunken.append(ship)
    return True


def _on_ship_destroyed(room, owner_id: str, ship, hits_added=None, source='magic'):
    """一艘船被摧毁后的通用副作用（普通攻击与区域魔法共用同一份实现）。

    普通攻击路径原先在 _apply_ship_sunk_effects 里内联；溅射 / 轰炸 / 硫磺火焰
    各自又写了一份，且都漏掉了两件事：

      ① 平等条约快照（game_effects['last_ship_change']）—— 这些卡造成的船数
         变化因此**无法被平等条约无效化**（卡面允许无效化"船数改变效果"）；
      ② 无暇圣心**中断** —— 它们只把 no_damage 置 False，效果本身既没被中断
         也没有广播，等于"有船沉了但无暇圣心还在"。

    source 记录这艘船是「怎么死的」，平等条约据此判断能不能无效化：
      - 'attack' 普通炮击 / 教皇旨意弃卡攻击
      - 'magic'  魔法卡造成的击沉（溅射 / 轰炸 / 硫磺火焰）
    卡面只允许无效化【魔法卡】造成的船数改变，攻击造成的不在此列。
    """
    owner = room.players[owner_id]
    room.game_effects['last_ship_change'] = {
        'round': room.round,  # 卡面"立即发动"：只允许无效化本大回合的船数改变
        'player': owner_id,
        'count': 1,
        'ship': ship,  # 保存 ship 引用，供平等条约完全回滚
        'hits_added': list(hits_added or []),
        'source': source,
    }

    # 百亿补贴: 自己的船被击败时，自己的攻击次数 +3
    if _grant_subsidy_bonus(room, owner_id):
        if room.game_effects.get('last_ship_change', {}).get('player') == owner_id:
            room.game_effects['last_ship_change']['subsidy_granted'] = True

    # 无暇圣心：只要有战舰被击沉就中断
    if 'holy_heart' in room.game_effects:
        del room.game_effects['holy_heart']
        emit('holy_heart_interrupted', {
            'reason': '有战舰被击沉，无暇圣心效果中断'
        }, room=room.id)

    # 守株待兔：被击沉的船带陷阱标记 → 让对方牺牲 min(2, 对方活船数) 艘。
    # 卡面"如果这艘船死亡"按字面解释为任意死亡方式都触发；为防 caster
    # 自己主动牺牲陷阱船造成递归（牺牲→触发trap→对方牺牲→可能再触发），
    # 触发后**立刻清掉 trap 标记**，同一艘船只能触发一次。
    if getattr(ship, 'trap', False):
        ship.trap = False
        _trigger_ship_trap(room, owner_id, ship)

    # 把己方棋盘重新推给本人：不然前端手里那份还是摆船时自己拼的，
    # 既不知道哪艘已经沉了（没有 alive 标记），也不知道船被移除，
    # 「选一艘自己的船」类的卡就会把沉船也画成可点。
    _emit_player_ships(room, owner_id)


def _trigger_ship_trap(room, owner_id, sunk_ship):
    """守株待兔陷阱被踩中：让【对方】牺牲 min(2, 对方活船数) 艘战舰。

    与命运骰子摇到6共用牺牲链路：reason='trap_sacrifice'，allow_duplicate=True
    跳过同 reason 去重，让对方连点两艘；AI 路径由 _request_ship_pick 自动选。
    对方没有活船则跳过。
    """
    opponent_id = _opponent_of(room, owner_id)
    if not opponent_id or opponent_id not in room.players:
        return
    opponent = room.players[opponent_id]
    alive = _alive_ships(opponent)
    need = min(2, len(alive))
    if need <= 0:
        emit('trap_triggered', {
            'owner': owner_id, 'sunk_positions': [{'x': p.x, 'y': p.y} for p in sunk_ship.positions],
            'sacrificed': 0, 'message': '陷阱触发，但对方没有可牺牲的战舰',
        }, room=room.id)
        return

    emit('trap_triggered', {
        'owner': owner_id, 'sunk_positions': [{'x': p.x, 'y': p.y} for p in sunk_ship.positions],
        'sacrificed': need, 'message': f'陷阱触发！对方需牺牲{need}艘战舰',
    }, room=room.id)
    add_game_log(room,
                 f'第{room.round}回合 · {_log_name(room, owner_id)} 的【守株待兔】陷阱被踩中，'
                 f'对方需牺牲{need}艘战舰',
                 'magic', {'owner': owner_id, 'card': '守株待兔', 'sacrifice': need})

    for _ in range(need):
        picked = _request_ship_pick(room, opponent_id, 'trap_sacrifice',
                                    '守株待兔：请点选一艘战舰牺牲',
                                    allow_duplicate=True)
        if picked is not None:
            # AI 自动选好：立即执行
            _do_demon_contract_sacrifice(room, opponent_id, picked, 'trap_sacrifice')



def _apply_ship_sunk_effects(room, room_id, attacker_id, defender_id, ship, target_x, target_y):
    """击沉一艘战舰后的共同副作用（普通攻击 / 区域魔法 共用）。

    包含：船数扣减、沉船记录、平等条约快照、百亿补贴、恶魔契约、
    八方来财、无暇圣心中断。
    """
    defender = room.players[defender_id]
    defender.remaining_ships -= 1
    _mark_ship_sunken(defender, ship)   # 去重，见该函数说明

    # 平等条约快照 + 百亿补贴 + 无暇圣心中断（与区域魔法共用）
    # source='attack'：炮击造成的船数减少，平等条约无效化不了（卡面只针对魔法卡）
    _on_ship_destroyed(room, defender_id, ship, [Position(x=target_x, y=target_y)],
                       source='attack')

    # 恶魔契约: 绑定船数增减 - 任意一方船被击杀，另一方也要牺牲一艘
    # 牺牲由该方玩家自己在棋盘上点选（AI 自动），不再随机。
    if room.game_effects.get('demon_contract'):
        _request_demon_contract_sacrifice(room, defender_id)

    # 八方来财: 战舰数目变化时抽一张牌。
    # 这是【炮击/弃卡攻击】造成的减少，所以"己方击败对方的船"要排除 ——
    # 即：攻击方自己持有八方来财时，他打沉别人不算变化；
    # 而被击沉的那一方若持有八方来财，则照常摸牌（是对方击败了我方）。
    _notify_treasure_hunter(room, 1, exclude_player_id=attacker_id)

    # 检查无暇圣心效果：如果有战舰被击沉，中断效果
    if 'holy_heart' in room.game_effects:
        del room.game_effects['holy_heart']
        emit('holy_heart_interrupted', {
            'reason': '有战舰被击沉，无暇圣心效果中断'
        }, room=room_id)


def _apply_attacker_damage_buffs(room, room_id, attacker_id):
    """攻击造成伤害后攻击方触发的效果：饮血、越战越勇、伤害统计。"""
    attacker = room.players[attacker_id]
    if attacker.effect_flags.vampire:
        room.draw_card(attacker_id)
        emit('message', {'text': '饮血效果发动，抽一张卡'}, to=attacker.sid)
    if attacker.effect_flags.battle_spirit:
        room.attacks_remaining += 1
        emit('message', {'text': '越战越勇效果发动，攻击次数净增加1'}, room=room_id)
    attacker.damage_dealt_this_turn += 1


def _finish_game_win(room, room_id, winner_id, loser_id, log_message=None):
    """对局结束：置状态、记日志、记录战绩并广播 game_over。"""
    if room.state == 'game_over':
        # 幂等：对局已结束时不重复记账/广播（防止刷战绩）
        return
    room.state = 'game_over'
    room.winner = winner_id
    add_game_log(room, log_message or f"第{room.round}回合 · {_log_name(room, winner_id)} 获胜，游戏结束",
                 'result', {'winner': winner_id, 'loser': loser_id})
    # 记录战绩 + 每局统计 + 徽章（统一收口，见 _finalize_match）
    _finalize_match(room, winner_id, loser_id)
    emit('game_over', {'winner': winner_id}, room=room_id)


@socketio.on('attack')
@_require_live_room
def handle_attack(data):
    room_id = data['room_id']
    attacker_id = data['player_id']
    target_x = data['x']
    target_y = data['y']

    room = room_manager.get_room(room_id)
    if not room or attacker_id not in room.players or not _identity_ok(room, attacker_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if room.state == 'game_over':
        return {'status': 'error', 'message': '对局已结束'}
    frz = _frozen_reason(room, attacker_id)
    if frz:
        return {'status': 'error', 'message': frz}

    # 输入校验：坐标必须是 0-5 的【整数】，避免越界/非法类型被记为一次攻击；
    # 也拒绝 1.9 这类小数（原先 int() 会静默截断成 1，打到别的格子）
    try:
        fx, fy = float(target_x), float(target_y)
    except (TypeError, ValueError):
        return {'status': 'error', 'message': '非法的攻击坐标'}
    if not (fx.is_integer() and fy.is_integer()):
        return {'status': 'error', 'message': '非法的攻击坐标'}
    target_x, target_y = int(fx), int(fy)
    if not (0 <= target_x <= 5 and 0 <= target_y <= 5):
        return {'status': 'error', 'message': '攻击坐标超出棋盘范围'}

    # 检查是否是当前攻击者
    if attacker_id != room.current_attacker:
        return {'status': 'error', 'message': '还没到你的攻击回合'}

    # 新增：检查当前是否为战斗阶段
    if room.current_phase != 'battle':
        return {'status': 'error', 'message': '当前不是战斗阶段'}

    # 连锁窗口开着时不能继续攻击：卡牌效果要到 resolve_chain 才真正执行，
    # 此时放行会让「先结算的攻击」与「后结算的卡」互相盖掉（end_turn 早已用
    # 同一条件拦截，攻击却漏了 —— 同一状态两种口径）。
    if room.chain or room.chain_waiting:
        return {'status': 'error', 'message': '连锁结算中，请等待响应窗口结束后再攻击'}

    # 已被拦下的阶段转换：等待对方响应期间不能继续开炮。
    # 这是这个窗口存在的意义 —— 对方正在决定要不要打速阶3，
    # 这边要是能把攻击先打完，"拦下来问一句"就没有任何意义了。
    wait = _action_wait_reason(room, attacker_id)
    if wait:
        return {'status': 'error', 'message': wait}

    # 次数校验：此前缺失，改客户端（或前端连点绕过 DOM 判断）即可无限攻击
    if room.attacks_remaining <= 0:
        return {'status': 'error', 'message': '本回合攻击次数已用尽'}

    # 检查是否已经攻击过这个位置
    if any(a.x == target_x and a.y == target_y for a in room.players[attacker_id].attacks):
        return {'status': 'error', 'message': '你已经攻击过这个位置了'}

    # 找到对手
    defender_id = next(p for p in room.players if p != attacker_id)
    defender_ships = room.players[defender_id].ships

    # 神威！：被扣掉的区域不可攻击
    if _cell_in_shenwei_hole(room, defender_id, target_x, target_y):
        return {'status': 'error', 'message': '该区域已被神威！扣掉，无法攻击'}

    # 检查是否击中（统一路径：强制击杀与普通攻击共用一套结算）
    hit = False
    ship_sunk = False
    shield_blocked = False
    for i, ship in enumerate(defender_ships):
        if {'x': target_x, 'y': target_y} not in ship.positions:
            continue
        hit = True

        # 更新无暇圣心效果：如果有伤害，标记no_damage为False（无敌状态不算造成伤害）
        if 'holy_heart' in room.game_effects and not ship.invincible:
            room.game_effects['holy_heart']['no_damage'] = False

        # 检查攻击者是否有强制击杀效果
        has_forced_kill = room.players[attacker_id].effect_flags.forced_kill > 0

        if has_forced_kill:
            # 强制击杀效果：忽略无敌和盾牌状态，记录击中位置并直接击沉
            defender_ships[i].hits = defender_ships[i].hits + [Position(x=target_x, y=target_y)]
            ship_sunk = True
            _apply_ship_sunk_effects(room, room_id, attacker_id, defender_id,
                                     defender_ships[i], target_x, target_y)
        elif ship.invincible:
            # 无敌状态，只显形不造成伤害
            ship_sunk = False
        elif ship.shield:
            # 盾牌状态，抵挡一次伤害
            ship_sunk = False
            shield_blocked = True
            ship.shield = False
            # 盾挡下一击：必须明确广播"这一炮被挡了"。否则双方只看到一次普通
            # "命中"，防守方会以为自己的船挨了一炮（实际毫发无伤），
            # 也完全不知道自己的盾已经用掉。
            emit('shield_absorbed', {
                'player': defender_id,
                'positions': [{'x': p.x, 'y': p.y} for p in ship.positions],
            }, room=room_id)
            _emit_player_ships(room, defender_id)
        else:
            # 记录击中位置
            defender_ships[i].hits = defender_ships[i].hits + [Position(x=target_x, y=target_y)]
            # 检查船是否被击沉
            if len(defender_ships[i].hits) == len(defender_ships[i].positions):
                ship_sunk = True
                _apply_ship_sunk_effects(room, room_id, attacker_id, defender_id,
                                         defender_ships[i], target_x, target_y)
            else:
                ship_sunk = False

        # 造成伤害（含强制击杀）时才触发攻击方增益与胜负检查
        if has_forced_kill or (not ship.invincible and not ship.shield):
            # 检查回光返照效果：造成伤害即判负
            if _check_last_chance(room, attacker_id, defender_id):
                return {'status': 'success', 'game_over': True}

            # 发送战舰数更新事件
            _emit_ships_updated(room)

            # 饮血 / 越战越勇 / 伤害统计
            _apply_attacker_damage_buffs(room, room_id, attacker_id)

            # 检查绝处逢生效果：击杀任何一艘战舰直接获胜。
            #
            # ⚠️ 两个条件都不能少：
            # ① last_stand_win 而不是 last_stand —— 后者是"发动回合锁卡"的标记，
            #    换小回合就被清，用它会把效果限制在发动当回合（作者实测反馈：
            #    "只会在绝处逢生生效的那一个回合有效 到了下一个回合就没有了"）。
            # ② 必须【真的打死了一艘船】才判胜。原先只判"造成了伤害"就获胜，
            #    于是普通命中（甚至一次没打沉的炮）都能直接赢 —— 那不是卡面写的
            #    "击杀了对方的任何一艘船"。船沉了才走 _apply_ship_sunk_effects，
            #    到这一行 remaining_ships 已经扣过，所以判胜即"击杀"。
            #    强制击杀（余音绕梁）本身就是击杀，同样算数。
            if (room.players[attacker_id].effect_flags.last_stand_win
                    and (ship_sunk or has_forced_kill)):
                _finish_game_win(room, room_id, attacker_id, defender_id,
                                 f"第{room.round}回合 · {_log_name(room, attacker_id)} 绝处逢生击杀敌舰获胜")
                return {'status': 'success', 'game_over': True}

            # 注意：强制击杀按【攻击阶段】计数，不按击杀次数消耗，
            # 改为在进入结束阶段时消耗（见 handle_enter_end_phase）。
        break


    # 记录最后一次攻击（用于溅射等效果）
    room.last_attack = {
        'attacker': attacker_id,
        'x': target_x,
        'y': target_y,
        'hit': hit,
        'ship_sunk': ship_sunk,
        'round': room.round
    }

    # 减少攻击次数
    room.attacks_remaining -= 1
    # 确保攻击次数不会为负数
    room.attacks_remaining = max(0, room.attacks_remaining)

    # 记录本次攻击到attacks列表（修复重复攻击校验与AI追踪失效）
    #
    # ⚠️ 被盾挡下的那一炮【不记】。
    # `attacks` 的含义是"这一格已经打过了"：前端据此画叉并**不再绑定点击**，
    # 服务端也用它做重复攻击校验。可盾牌只是把这一炮吃掉、船毫发无伤 ——
    # 把格子算成"已打过"，玩家就会看到"打了一炮 → 格子变红叉 → 同一回合再也点不动"，
    # 而他的船明明还完好地停在那儿（作者实测反馈）。
    # 不记之后：同一回合可以再打这一格（盾已经破了，这一炮就正常结算伤害）。
    # 攻击次数照扣 —— 盾挡掉的是一发炮弹，这一点没有变化。
    if not shield_blocked:
        room.players[attacker_id].attacks.append(Position(**{
            'x': target_x,
            'y': target_y,
            'hit': hit,
            'ship_sunk': ship_sunk
        }))

    # 准备攻击结果
    attack_result = AttackResult(
        attacker=attacker_id,
        x=target_x,
        y=target_y,
        hit=hit,
        ship_sunk=ship_sunk,
        remaining_attacks=room.attacks_remaining,
        attacker_remaining_ships=room.players[attacker_id].remaining_ships,
        defender_remaining_ships=room.players[defender_id].remaining_ships,
        shield_blocked=shield_blocked
    )

    _shield_note = '，被护盾挡下' if shield_blocked else ('，击沉战舰' if ship_sunk else '')
    add_game_log(room, f"第{room.round}回合 · {_log_name(room, attacker_id)} 攻击 ({target_x},{target_y}) — {'命中' if hit else '未命中'}{_shield_note}",
                 'attack', {
                     'attacker': attacker_id,
                     'target': {'x': target_x, 'y': target_y},
                     'hit': hit,
                     'ship_sunk': ship_sunk,
                     'shield_blocked': shield_blocked
                 })

    emit('attack_result', attack_result, room=room_id)

    # 检查游戏是否结束（统一用 <= 0 判据，兼容效果的非常规扣减）；
    # 对手"根本没船"（未布船 / 放置流程中途）不算被消灭，避免空棋盘被一击判胜
    if (room.players[defender_id].remaining_ships <= 0
            and len(room.players[defender_id].ships) > 0):
        _finish_game_win(room, room_id, attacker_id, defender_id)
        return {'status': 'success', 'game_over': True}

    # 攻击次数为0时，不自动切换攻击者，让玩家手动进入结束阶段
    # 玩家需要点击"进入结束阶段"按钮来结束当前回合
    if room.attacks_remaining == 0:
        # 五险一金：本回合攻击次数第一次归零 —— 若此刻确实没让对方减船，则 +3
        # （触发后攻击次数不再是 0，下面的广播会把最新次数带给前端）
        _maybe_trigger_wuxian_yijin(room, attacker_id)

    if room.attacks_remaining == 0:
        # 只发送攻击次数更新，不切换攻击者
        emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining
        }, room=room_id)

    return {'status': 'success'}


@socketio.on('enter_battle_phase')
@_require_live_room
def enter_battle_phase(data, _priority_confirmed=False):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

    # 已被拦下的阶段转换：发起方在等待对方响应期间不能继续推进阶段。
    # （不加这条，双击「进入战斗阶段」就能绕过询问 —— 见 _priority_wait_reason）
    if not _priority_confirmed:
        wait = _action_wait_reason(room, player_id)
        if wait:
            return {'status': 'error', 'message': wait}

    # 检查是否是当前攻击者的准备阶段
    if room.current_attacker == player_id and room.current_phase == 'preparation':
        # ⚠️ 速阶3抢时点的仲裁：推进阶段前先问对方"要不要响应"。
        # 他放弃/超时后，_priority_continue 会带着 _priority_confirmed=True
        # 重新调用本函数，那时才真正推进。
        # 不询问的情形（人机房 / 对方已拒绝 / 有连锁挂起…）直接放行。
        if not _priority_confirmed and _ask_priority(room, player_id, 'enter_battle'):
            return {'status': 'success', 'awaiting_priority': True}

        # 切换到战斗阶段
        room.current_phase = 'battle'

        # ⚠️ 无条件按【当前场地规则】重算攻击次数。
        #
        # 旧实现只处理伊甸园与教皇旨意两个特例，其余情况原样保留准备阶段的值。
        # 于是出现两条实测缺陷：
        #   ① 准备阶段打出教皇旨意（次数被压成 0）→ 场地被拆除 → 进战斗阶段时
        #      两个特例都不命中 → 次数停在 0：玩家 4 艘船却一发都打不出去。
        #   ② 准备阶段挂着伊甸园（次数=6-船数）→ 场地被顶替/拆除 → 次数不被纠正。
        # _recalc_attacker_attacks 已经是"按当前场地规则算"的唯一权威实现，
        # 直接用它兜底，特例自然被覆盖，也不会再随场地增减而漂移。
        _recalc_attacker_attacks(room)

        # 攻击次数翻倍（火力全开）：直接翻【当前】攻击次数。
        #
        # ⚠️ 不能重算「船数 - 冻结数」再 ×2（旧实现）：那等于把场地魔法
        # 压过的次数又还原回来了。作者实测：自己先打了教皇旨意（本回合
        # 攻击次数归 0），对方用火力全开却照样拿到 2×船数 的次数。
        # 卡面是"自己的攻击次数翻倍"，所以基准就是 attacks_remaining 本身。
        if room.players[player_id].effect_flags.double_attacks:
            room.attacks_remaining = max(0, room.attacks_remaining) * 2
            # 广播攻击次数更新
            emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining
            }, room=room_id)
            # 移除翻倍效果，因为它只持续一个大回合
            room.players[player_id].effect_flags.double_attacks = False

        # 重算后必须广播，否则前端仍显示准备阶段的旧值
        emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining
        }, room=room_id)

        # 五险一金：进战斗阶段时攻击次数就可能是 0（教皇旨意直接把次数压成 0），
        # 这也算「本回合第一次归零」，要给它触发机会。
        # ⚠️ 但败者食尘生效的大回合不算：「双方攻击次数为 0」是大回合规则，
        # 让五险一金回填 3 次等于当场把这个 0 抹掉。
        if room.attacks_remaining <= 0 and not _attacks_forced_zero(room):
            _maybe_trigger_wuxian_yijin(room, player_id)

        # 广播阶段更新
        emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker
        }, room=room_id)
        return {'status': 'success'}

    return {'status': 'error', 'message': '无法进入战斗阶段'}


# 添加结束战斗阶段，进入结束阶段
@socketio.on('enter_end_phase')
@_require_live_room
def handle_enter_end_phase(data, _priority_confirmed=False):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 已被拦下的阶段转换：等待对方响应期间不能进入结束阶段
    if not _priority_confirmed:
        wait = _action_wait_reason(room, player_id)
        if wait:
            return {'status': 'error', 'message': wait}

    # 检查是否是当前攻击者的战斗阶段
    if room.current_attacker == player_id and room.current_phase == 'battle':
        # 检查是否还有剩余攻击次数
        if room.attacks_remaining > 0:
            return {'status': 'error', 'message': '你还有剩余攻击次数，无法进入结束阶段'}

        # ⚠️ 速阶3抢时点的仲裁：同 enter_battle_phase —— 推进前先问对方。
        if not _priority_confirmed and _ask_priority(room, player_id, 'enter_end'):
            return {'status': 'success', 'awaiting_priority': True}

        # 进入结束阶段
        room.current_phase = 'end'

        # 余音绕梁按攻击阶段计数：本回合的攻击阶段结束即消耗一次
        flags = room.players[player_id].effect_flags
        if getattr(flags, 'forced_kill', 0) > 0:
            flags.forced_kill -= 1
            if flags.forced_kill <= 0:
                del flags.forced_kill

        # 清除越战越勇效果
        room.players[player_id].effect_flags.battle_spirit=False
        
        emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker
        }, room=room_id)

        return {'status': 'success', 'message': '已进入结束阶段'}

    # 兜底：不满足条件时必须回一个 dict。
    # 返回 None 会让前端 ack 回调拿到 undefined，读 response.status 直接抛
    # TypeError，把真正的错误提示整个吞掉（控制台里只剩一行莫名其妙的报错）。
    return {'status': 'error', 'message': '当前不是你的战斗阶段'}


def switch_turn_after_end_phase(room, opponent_id):
    # 模拟结束阶段处理时间
    time.sleep(2)

    # 切换到对方回合
    room.current_attacker = opponent_id
    room.attacks_remaining = max(0, room.players[opponent_id].remaining_ships - frozen_ship_count(room.players[opponent_id]))  # 存活战舰数减去冻结数
    _recalc_attacker_attacks(room)
    room.current_phase = 'preparation'
    
    # 重置本回合伤害统计
    room.players[opponent_id].damage_dealt_this_turn = 0

    # 广播回合变化 - 移除了回合切换时的额外抽卡
    emit('turn_change', {
        'current_attacker': opponent_id,
        'attacks_remaining': room.attacks_remaining,
        'phase': 'preparation'
    }, room=room.id)
    # 轮到AI时自动驱动其回合
    _maybe_run_ai_turn(room)


# 添加结束结束阶段，切换到对方准备阶段
@socketio.on('end_turn')
@_require_live_room
def end_turn(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

    # 已被拦下的阶段转换：等待对方响应期间不能交回合
    wait = _action_wait_reason(room, player_id)
    if wait:
        return {'status': 'error', 'message': wait}

    # 连锁未结算时禁止结束回合。
    # 卡牌效果在 resolve_chain 里才真正执行，若此时放行换人，
    # 效果会落在「下一个人已经是当前攻击者」之后 —— Freezing！ 这种
    # 「跳过对方回合」的效果就这么凭空丢了（还不会被任何人察觉）。
    if room.chain or room.chain_waiting:
        return {'status': 'error', 'message': '连锁结算中，请等待响应窗口结束后再结束回合'}

    # 检查是否是当前攻击者的结束阶段
    if room.current_attacker == player_id and room.current_phase == 'end':
        current_index = room.attack_order.index(room.current_attacker)
        next_index = (current_index + 1) % len(room.attack_order)

        # ── 跳过回合（Freezing！/ 神之宣告）──────────────────────────────
        # ⚠️ 这段必须在 `next_index == 0` 的"进入新大回合"判断【之前】执行。
        # 旧实现放在后面的 else 分支里，于是"跳过对方后索引绕回起点"这件事
        # 根本不会被那个判断看到 —— 结果只是轮回到自己连续行动，
        # 而不是作者要的"跳过对方整个回合、直接开始新大回合（重新猜拳+摸牌）"。
        #
        # ★ 2026-09-20 修：**两张卡的跳过作用域不同，不能共用同一个标记**。
        #   卡面写得很清楚，是两张不同的牌：
        #     · Freezing！   —— "跳过对方**本回合**"，作者裁定语义 = 直接进新大回合
        #                       （重新猜拳 + 重新发牌），由
        #                       `test_freeze_skip_and_field_tear.py` 钉住；
        #     · 神之宣告     —— "跳过**这一个大回合内**对方的所有阶段"，
        #                       **不含翻页**。大回合该正常推进。
        #   旧实现两者共用 `skip_opponent_turn`，而它的消费点绑死在
        #   "绕回起点 → 开新大回合"那一支上 → 神之宣告**必然**带上 Freezing 的翻页，
        #   白送一次"重新猜拳 + 重新摸牌 + damage_dealt_this_turn 归零"。
        #   作者实测反馈的"效果二疑似没实现"，根因就在这里：
        #   它做的不是卡面承诺的那件事。
        next_attacker = room.attack_order[next_index]
        if room.skip_opponent_turn and room.skip_opponent_turn == next_attacker:
            room.skip_opponent_turn = None
            next_index = (next_index + 1) % len(room.attack_order)
            next_attacker = room.attack_order[next_index]
        if room.skip_next_turn and room.skip_next_turn == next_attacker:
            room.skip_next_turn = None
            next_index = (next_index + 1) % len(room.attack_order)
            next_attacker = room.attack_order[next_index]

        # 神之宣告：跳过对方在**本大回合**内的所有阶段（不翻页）。
        # 作用域差别的来历见上面那段。这里只吃 `skip_opponent_stages`，
        # 与 Freezing 的 `skip_opponent_turn` 各管一条路，互不干扰。
        skip_stages = False
        if room.skip_opponent_stages and room.skip_opponent_stages == next_attacker:
            room.skip_opponent_stages = None
            skip_stages = True
            # 跳到下一个人（正常是绕回自己），让大回合**正常推进**
            next_index = (next_index + 1) % len(room.attack_order)
            next_attacker = room.attack_order[next_index]
            emit('game_message', {
                'message': f'{_log_name(room, next_attacker)} 的回合被神之宣告跳过',
            }, room=room_id)

        # 如果是最后一个玩家结束回合（或跳过对方后绕回起点），开始新的大回合
        if next_index == 0:
            # 神之宣告跳过对方后，索引会绕回**起点**（自己）。
            # 那不等于"该开新大回合"—— 卡面明确说跳过的作用域是**本大回合内**，
            # 所以这里要把"翻页"按住：本大回合继续，只是行动权重回自己。
            # （Freezing！ 走 `skip_opponent_turn`，`skip_stages` 为假，
            #   翻页行为原样保留，见上面的守卫用例。）
            if skip_stages:
                room.current_attacker = next_attacker
                room.current_phase = 'preparation'
                room.attacks_remaining = 0
                room.state = 'attacking'
                emit('phase_updated', {
                    'current_phase': room.current_phase,
                    'current_attacker': room.current_attacker,
                }, room=room_id)
                emit('turn_skipped', {
                    'skipped': next_attacker,
                    'current_attacker': room.current_attacker,
                    'round': room.round,
                }, room=room_id)
                return {'status': 'success', 'message': '神之宣告：对方本回合被跳过'}
            # 进入新回合，重置状态
            room.round += 1

            # 看破！：新大回合开始重置双方的魔法封锁
            for p_id in room.players:
                room.players[p_id].magic_blocked = None

            # 神威！：除外的战舰到期回归原位，并恢复被扣掉的区域
            _restore_due_shenwei(room, room.round)

            # 解冻到期的战舰（冻结跨本大回合+下一大回合，第三大回合开始时解除）
            for p_id in room.players:
                thawed = False
                for s in room.players[p_id].ships:
                    if getattr(s, 'frozen', None) and s.frozen < room.round:
                        _thaw_ship(s)
                        thawed = True
                if thawed:
                    # 解冻同样要让玩家看到（否则棋盘上一直挂着雪花）
                    _emit_player_ships(room, p_id)

            # 守株待兔只在本大回合生效：进入新大回合时清掉所有船上的陷阱标记。
            # （卡面"这张牌只会在当前大回合生效"；旧标记残留到下一回合会让玩家
            #   以为陷阱还在，但触发条件已过。）
            for p_id in room.players:
                cleared = False
                for s in room.players[p_id].ships:
                    if getattr(s, 'trap', False):
                        s.trap = False
                        cleared = True
                if cleared:
                    _emit_player_ships(room, p_id)
                    emit('trap_expired', {'player': p_id}, room=room_id)

            # 冻结区域记录与解冻同步清理：条件与上面 `s.frozen < room.round` 一致，
            # 否则棋盘上会一直挂着那片斜纹、玩家以为还在冻结
            _fa = room.game_effects.get('frozen_area') if isinstance(room.game_effects, dict) else None
            if _fa and int(_fa.get('until_round') or 0) < int(room.round):
                room.game_effects.pop('frozen_area', None)
                emit('frozen_area', {'cleared': True}, room=room_id)

            # 回光返照只持续自己发动的那一个大回合
            room.game_effects.pop('last_chance', None)

            # 败者食尘的"双方攻击次数为 0"只属于生效的那个大回合。
            # 条件里已带 round 判定（_attacks_forced_zero），这里顺手清掉防残留。
            room.game_effects.pop('zero_attacks_round', None)

            # 绝处逢生的"候选格高亮"只在本大回合有效：新大回合双方棋盘信息重置，
            # 再亮着六个格子就是过期线索了（唯一一艘船还在，但线索不该跨回合留着）。
            if room.game_effects.pop('last_stand_cells', None):
                room.game_effects.pop('last_stand_owner', None)
                emit('last_stand_cells', {'cells': [], 'owner': None}, room=room_id)

            # 新大回合：双方本回合伤害统计归零
            # （此前唯一重置点在死代码 switch_turn_after_end_phase 内，
            #  导致 damage_dealt_this_turn 只增不减，五险一金/Freezing! 失效）
            for p_id in room.players:
                room.players[p_id].damage_dealt_this_turn = 0

            # 更新并检查极限增援效果
            if 'reinforcement_check' in room.game_effects:
                check = room.game_effects['reinforcement_check']
                # 卡面：不算生效的那个大回合，所以进入下一个大回合时先不递减
                # （room.round 此处已 +1；activated_round 那个大回合不计入）
                if room.round > int(check.get('activated_round', room.round - 1)) + 1:
                    check['remaining_turns'] -= 1
                remaining_turns = check['remaining_turns']

                # 通知客户端剩余回合更新
                emit('reinforcement_turn_updated', {
                    'remaining_turns': remaining_turns
                }, room=room_id)

                # 当剩余回合归0时，执行极限增援结算
                if remaining_turns <= 0:
                    # 卡面："船数少的一方直接获胜" —— 只说少的一方。
                    # 船数【相同】时没有"少的一方"，按作者裁定：不结算、继续对局。
                    # （旧实现用 random.choice 随机选一个获胜者，等于把胜负交给运气，
                    #   而且玩家/AI 双方看到的结果不透明，实测被当成"双方都被判胜"。）
                    player1_id = list(room.players.keys())[0]
                    player2_id = list(room.players.keys())[1]
                    player1_ships = room.players[player1_id].remaining_ships
                    player2_ships = room.players[player2_id].remaining_ships

                    winner = None
                    if player1_ships < player2_ships:
                        winner = player1_id
                    elif player2_ships < player1_ships:
                        winner = player2_id
                    else:
                        # 平局：把这张卡作废（避免每回合反复判定），但【绝对不要在这里
                        # return】—— 这一段位于 `if next_index == 0:` 内部，后面还有
                        # 「换人 / 进入新大回合 + 重置阶段 + 广播」的收尾。
                        # 以前这里直接 `return {'status': 'success'}`，把收尾整段跳过：
                        #   · room.state 不回到 rock_paper_scissors
                        #   · current_phase 留在 'end'、current_attacker 不变
                        #   · 一条 turn_change / phase_updated / game_state 都不发
                        # 而 room.round 已经 +1 了。客户端因此收不到任何状态变更，
                        # 界面停在旧阶段：交回合按钮不见了，只剩一个点了没反应的
                        # 「进入结束阶段」——作者反馈的"卡死、按钮直接消失"。
                        # 实测：tools/reinforcement_tie_check.mjs。
                        room.game_effects.pop('reinforcement_check', None)
                        emit('message', {
                            'text': '极限增援结算时双方船数相同，无人获胜，效果结束'
                        }, room=room_id)
                        # 别让下面那行又把 check 塞回 game_effects（否则下个大回合再判一次）
                        check = None

                    if winner is not None:
                        # 统一收尾：记日志 + 记战绩 + 广播 game_over
                        # （原先这条终局路径只置状态不写战绩）
                        loser = player2_id if winner == player1_id else player1_id
                        _finish_game_win(room, room_id, winner, loser,
                                         f"第{room.round}回合 · 极限增援生效，船数少的一方获胜")

                        # 广播游戏结束
                        emit('game_state', {
                            'state': 'game_over',
                            'winner': winner,
                            'reason': '极限增援生效，船数少的一方等到了增援并获胜了！',
                            **_rank_payload(room),
                        }, room=room_id)
                        return {'status': 'success', 'game_over': True, 'winner': winner}

                # 更新game_effects中的剩余回合（平局时 check 已被置空，不再塞回去）
                if check is not None:
                    room.game_effects['reinforcement_check'] = check

            # 更新并检查无暇圣心效果
            if 'holy_heart' in room.game_effects:
                check = room.game_effects['holy_heart']
                # 只有当双方都未造成伤害时才更新
                if check['no_damage']:
                    # 更新剩余回合计数
                    check['remaining_turns'] -= 1
                    remaining_turns = check['remaining_turns']

                    # 通知客户端剩余回合更新
                    emit('holy_heart_turn_updated', {
                        'remaining_turns': remaining_turns
                    }, room=room_id)

                    # 当剩余回合归0时，执行无暇圣心结算
                    if remaining_turns <= 0:
                        # 执行无暇圣心效果：施法者获胜
                        winner = check['caster']

                        # 直接结束游戏
                        room.state = 'game_over'
                        room.winner = winner

                        # 广播游戏结束
                        emit('game_state', {
                            'state': 'game_over',
                            'winner': winner,
                            'reason': '无暇圣心笼罩大地 愿这方世界不再有战争',
                            **_rank_payload(room),
                        }, room=room_id)
                        return {'status': 'success', 'game_over': True, 'winner': winner}

                    # 更新game_effects中的剩余回合
                    room.game_effects['holy_heart'] = check

            room.state = 'rock_paper_scissors'
            room.rps_choices = {}
            room.rps_processed = False

            # 神机妙算: 检查沉船数是否增加了x（击沉不从ships移除，用沉船差值判定）
            for p_id in room.players:
                player = room.players[p_id]
                pred = getattr(player.effect_flags, 'prediction', 0)
                if pred and isinstance(pred, int) and pred > 0:
                    # 从game_effects中读取初始快照
                    if f'prediction_initial_{p_id}' in room.game_effects:
                        saved = room.game_effects[f'prediction_initial_{p_id}']
                        diff = len(player.sunken_ships) - saved['sunken']
                        if diff == pred:
                            # 预言成功：卡面是「那些原本会减少的船不会减少并在
                            # 【原位置或者对方没有打过的位置重新部署】」——
                            # "重新部署"是玩家的主动选择，必须给摆放界面。
                            # 旧实现直接调 _revive_sunken_ships（原地复活、无交互），
                            # 实测玩家反馈"预言成功之后没有出现放置界面"。
                            _begin_shenji_redeploy(room, p_id, pred,
                                                   already_sunken_ids=saved.get('sunken_ids'))
                            del room.game_effects[f'prediction_initial_{p_id}']
                        room.players[p_id].effect_flags.prediction = 0
                    else:
                        # 快照缺失（旧对局/异常中断）：退回原地复活，至少不吞效果
                        room.players[p_id].effect_flags.prediction = 0

            # 大回合结束（重新猜拳）：本大回合内的所有效果到此为止。
            # 分类见 FLAGS_KEEP_ACROSS_ROUND 的说明。
            _prune_effect_flags(room, FLAGS_KEEP_ACROSS_ROUND)

            # 标记刚被清了一批，角标要跟着消失（否则百亿补贴等会一直亮着）
            _emit_active_effects(room)

            # 广播进入猜拳阶段
            emit('game_state', {
                'state': 'rock_paper_scissors',
                'round': room.round,
                **_rank_payload(room),
            }, room=room_id)
            # 新大回合开始，清掉上一回合残留的跳过标记。
            # 否则若 skip 未能匹配到目标，会一直留着并在后续回合误跳。
            room.skip_opponent_turn = None
            room.skip_next_turn = None
            # 阶段也要重置：Freezing！ 是在【结束阶段】打出的，跳过后若把
            # current_phase 留在 'end'，新大回合一开始就处于结束阶段 ——
            # 猜拳完直接能交回合、且准备/战斗阶段的 UI 与校验全都不对。
            room.current_phase = 'preparation'
            return {'status': 'success', 'new_round': True}
        else:
            # 跳过判定已经在上面的 `next_index == 0` 判断之前做完了
            # （否则"跳过对方后绕回起点"不会被识别为新大回合）。
            # 切换到下一个攻击者的准备阶段
            room.current_attacker = next_attacker
            room.current_phase = 'preparation'
            # 新回合伤害统计归零（见上：原重置点在死代码里）
            room.players[room.current_attacker].damage_dealt_this_turn = 0
            # 统一走 _recalc：伊甸园/教皇旨意下按场地规则计算
            _recalc_attacker_attacks(room)

            # 重置所有临时效果标志 —— 保留名单以 FLAGS_KEEP_ACROSS_TURN 为唯一声明。
            #
            # ⚠️ 这里原本是写死的内联列表，与上面的常量各存一份，注释却指着常量说
            #    "分类见 FLAGS_KEEP_ACROSS_TURN"。两份一漂移就出事：绝处逢生的
            #    "击杀即胜"（last_stand_win）两边都没登记 → 换小回合就被清掉，
            #    效果只在发动当回合有效（作者实测反馈）。现在统一走常量。
            _prune_effect_flags(room, FLAGS_KEEP_ACROSS_TURN)

            # 标记刚被清了一批，角标要跟着消失（否则百亿补贴等会一直亮着）
            _emit_active_effects(room)

            # 广播回合和阶段更新
            emit('phase_updated', {
                'current_phase': room.current_phase,
                'current_attacker': room.current_attacker
            }, room=room_id)
            emit('turn_change', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining,
                'phase': room.current_phase
            }, room=room_id)
            # 轮到AI时自动驱动其回合
            _maybe_run_ai_turn(room)
            return {'status': 'success'}

    return {'status': 'error', 'message': '无法结束当前回合'}






# ---------------------------------------------------------------------------
# AI 对战驱动：AI 自动摆船/出拳/回合推进（仅 is_ai_room 房间生效）
# ---------------------------------------------------------------------------
def _ai_player_id(room):
    """返回房间内AI玩家ID；不存在返回None。"""
    for pid in room.players:
        if pid.startswith('ai-'):
            return pid
    return None


def _ai_place_ships(room, ai_id: str):
    """为AI随机摆放战舰——规则与人类玩家完全一致：
    单格船、数量取该玩家的 max_ships（默认6）、坐标 0-5 内不重叠。"""
    import random as _rnd
    player = room.players[ai_id]
    player.ships = []
    player.remaining_ships = 0
    # 与人类一致：默认 6 艘（或按 room/玩家已设定的 max_ships，如灵气复苏后）
    max_ships = int(getattr(player, 'max_ships', 6) or 6)
    all_positions = [(x, y) for x in range(6) for y in range(6)]
    _rnd.shuffle(all_positions)
    for (px, py) in all_positions[:max_ships]:
        player.ships.append(PlayerShip(positions=[Position(x=px, y=py)], hits=[]))
        player.remaining_ships += 1


def _maybe_run_ai_turn(room):
    """若当前攻击者是AI，后台驱动其完整回合。"""
    if not getattr(room, 'is_ai_room', False) or room.state == 'game_over':
        return
    ai_id = _ai_player_id(room)
    if not ai_id or room.current_attacker != ai_id:
        return
    socketio.start_background_task(_ai_turn_loop, room.id)


AI_DIFFICULTIES = ('easy', 'normal', 'hard')

# AI 可以安全打出的卡：无目标、无后续选择、也不需要「本回合刚命中/刚击沉」之类前置条件。
# 其余卡一律不打，原因有二：
#   ① 桃园结义 / 明智埋葬 / 神机妙算 / 仁王之盾 / 灵气复苏 / 增援 / 死者苏生 / 绝处逢生
#      会等待「施法者自己」点选或放置（temp_data_id / pending_placement），AI 无从响应，
#      打出去会把整局卡死在那一个回合；
#   ② 溅射 / 雷达子弹 / 饮血 / 越战越勇 需要刚命中或刚击沉，随机打出只是浪费牌。
# 要扩卡池，先在 pytest 里确认该卡分支不会留下待处理状态。
_AI_SAFE_CARDS = (
    '余音绕梁', '火力全开', '无中生有', '极限增援', '无暇圣心',
    '看破！', '五险一金', '八方来财', '百亿补贴',
)


def _ai_choose_magic_card(room, ai_id: str):
    """纯函数：挑一张 AI 能安全打出的手牌，返回下标；没有则 None。

    只做选择、不改状态，方便单测。按速阶从低到高挑（速阶 1 最便宜）。
    """
    player = room.players.get(ai_id)
    if not player or not player.magic_hand:
        return None
    candidates = []
    for idx, c in enumerate(player.magic_hand):
        if c.name not in _AI_SAFE_CARDS:
            continue
        if not can_play_magic_card(room, ai_id, c):
            continue
        candidates.append((int(c.speed), idx))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _ai_maybe_play_magic(room, ai_id: str) -> bool:
    """AI 在自己回合打出一张安全的魔法卡；返回是否真的打出。

    每回合最多一张，避免把整手牌一次性倒光。简单难度（easy）不出牌。
    """
    if getattr(room, 'ai_difficulty', 'normal') == 'easy':
        return False
    idx = _ai_choose_magic_card(room, ai_id)
    if idx is None:
        return False
    card = room.players[ai_id].magic_hand[idx]
    resp = handle_use_magic_card({
        'room_id': room.id,
        'player_id': ai_id,
        'card': {'name': card.name, 'speed': card.speed, 'type': card.type,
                 'description': getattr(card, 'description', '')},
        'targets': {},
    })
    return bool(resp and resp.get('status') == 'success')


def _ai_turn_loop(room_id: str):
    """AI回合：进入战斗阶段→随机攻击至次数耗尽→结束阶段→交出回合。"""
    try:
        time.sleep(1)
        room = room_manager.get_room(room_id)
        if not room or room.state == 'game_over':
            return
        ai_id = _ai_player_id(room)
        if not ai_id or room.current_attacker != ai_id:
            return
        enter_battle_phase({'room_id': room_id, 'player_id': ai_id})

        # 先出一张安全卡（normal / hard 难度）。出牌可能打开连锁响应窗口，
        # 而连锁未结算时攻击会被 handle_attack 门禁拒绝 —— 必须等窗口关闭再开炮，
        # 否则 AI 的攻击会全军覆没、回合草草结束。
        _ai_maybe_play_magic(room, ai_id)
        for _ in range(40):
            room = room_manager.get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if not (room.chain or room.chain_waiting):
                break
            time.sleep(0.3)

        for _ in range(40):
            room = room_manager.get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if room.attacks_remaining <= 0:
                break
            attacked = {(a.x, a.y) for a in room.players[ai_id].attacks}
            candidates = [(x, y) for x in range(6) for y in range(6) if (x, y) not in attacked]
            if not candidates:
                break
            x, y = random.choice(candidates)
            handle_attack({'room_id': room_id, 'player_id': ai_id, 'x': x, 'y': y})
            time.sleep(0.3)
        room = room_manager.get_room(room_id)
        if not room or room.state == 'game_over' or room.current_attacker != ai_id:
            return

        # 收尾必须重试：连锁若还没结算完，enter_end_phase / end_turn 会被门禁拒绝，
        # 而 AI 回合没有别的触发点 —— 一旦这里失败，回合就会永远停在 AI 手上，
        # 真人只能干等（此前 AI 不出牌，所以碰不到这个竞态）。
        for _ in range(20):
            room = room_manager.get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if room.chain or room.chain_waiting:
                time.sleep(0.5)
                continue
            resp = handle_enter_end_phase({'room_id': room_id, 'player_id': ai_id})
            if resp and resp.get('status') == 'success':
                break
            time.sleep(0.5)
        time.sleep(0.5)

        for _ in range(20):
            room = room_manager.get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            resp = end_turn({'room_id': room_id, 'player_id': ai_id})
            if resp and resp.get('status') == 'success':
                return
            time.sleep(0.5)
    except Exception as e:
        print(f'AI turn error: {e}')


# ── 教皇旨意：弃一张魔法卡 → 自己的攻击次数 +2 ──────────────────────
#
# 卡面：「双方的攻击次数都变为0，攻击方式改为弃置一张魔法卡攻击对方两次」。
#
# 作者裁定（2026-09-14）：弃卡的效果应该是【让自己攻击次数 +2】，
# 之后【和正常攻击逻辑一样】—— 逐个格子点、每次消耗 1 次、走 handle_attack。
#
# 旧实现是"服务端一次性对着同一个格子打两发"，实测（tools/e2e_papal_baseline.py）
# 有三个问题：
#   · 弃卡后 attacks_remaining 仍然是 0 —— 玩家没有"次数"，也就无法选择打哪两格；
#   · 弃卡之后仍然走不了普通 attack 通道（实测报「本回合攻击次数已用尽」）；
#   · 走的是另一条 _do_attack 路径，与普通攻击的联动历史上漏过好几次
#     （余音绕梁 / 越战越勇 / 饮血 都曾在这条路上漏掉）。
PAPAL_DISCARD_BONUS = 2


def _papal_active(room):
    """教皇旨意是否生效（场地实例与房间级标记，任一成立即可）。"""
    return (room.game_effects.get('papal_edict') is True
            or field_magic_name(room) == '教皇旨意')


def _papal_discard_grant(room, player_id, discard_card_index=None):
    """弃一张魔法卡，给自己 +PAPAL_DISCARD_BONUS 次攻击。

    只改攻击次数，不执行攻击本身 —— 攻击交给玩家点格子走 handle_attack，
    这样余音绕梁 / 饮血 / 越战越勇 / 百亿补贴 / 八方来财 等联动全都自动生效。
    """
    player = room.players[player_id]

    if not _papal_active(room):
        return {'status': 'error', 'message': '教皇旨意未生效'}
    if room.current_attacker != player_id:
        return {'status': 'error', 'message': '还没到你的攻击回合'}
    if room.current_phase != 'battle':
        return {'status': 'error', 'message': '当前不是战斗阶段'}
    if not player.magic_hand:
        return {'status': 'error', 'message': '没有可弃置的魔法卡'}

    if discard_card_index is None:
        idx = 0
    else:
        try:
            idx = int(discard_card_index)
        except (TypeError, ValueError):
            return {'status': 'error', 'message': '无效的弃卡位置'}
        # 越界索引：旧实现里越界会"一张不弃却照打两次"（零代价攻击），必须拒绝
        if not (0 <= idx < len(player.magic_hand)):
            return {'status': 'error', 'message': '无效的弃卡位置'}

    discarded = player.magic_hand.pop(idx)
    room.magic_discard.append(discarded)
    room.attacks_remaining += PAPAL_DISCARD_BONUS

    emit('hand_updated', {'hand': player.magic_hand}, to=player.sid)
    emit('attacks_updated', {
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining,
    }, room=room.id)
    add_game_log(room,
                 f'第{room.round}回合 · {_log_name(room, player_id)} 教皇旨意弃置「{discarded.name}」，'
                 f'攻击次数 +{PAPAL_DISCARD_BONUS}',
                 'magic', {'player': player_id, 'card': discarded.name})
    emit('message', {'text': f'已弃置「{discarded.name}」：攻击次数 +{PAPAL_DISCARD_BONUS}，'
                             f'现在可以正常攻击了'},
         to=player.sid)

    return {
        'status': 'success',
        'discarded': discarded.name,
        'attacks_remaining': room.attacks_remaining,
        'message': f'已弃置「{discarded.name}」，攻击次数 +{PAPAL_DISCARD_BONUS}',
    }


@socketio.on('request_hand_sync')
def handle_request_hand_sync(data):
    """客户端发现手牌状态对不上时，主动要一份权威手牌。

    为什么需要这个事件：前端的手牌只有一个来源（hand_updated 的 payload），
    一旦某次推送丢了、或 payload 结构不对（旧缓存版本的前端 + 新版服务端），
    界面就会一直显示错误的手牌，**只有刷新页面才能恢复**（刷新走重连快照）。
    作者反馈的「手牌莫名消失，刷新又回来了」正是这种"客户端状态坏了但没人纠正它"。

    有了它，前端自己就能对不上就纠正，不用等玩家刷新。
    只回给请求者本人，不泄露对手手牌。
    """
    room = room_manager.get_room((data or {}).get('room_id'))
    player_id = (data or {}).get('player_id')
    if not room or not player_id or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    player = room.players[player_id]
    emit('hand_updated', {'hand': player.magic_hand, 'resync': True}, to=player.sid)
    return {'status': 'success', 'count': len(player.magic_hand)}


@socketio.on('papal_discard')
@_require_live_room
def handle_papal_discard(data):
    """教皇旨意：弃一张魔法卡换 2 次攻击。"""
    room = room_manager.get_room(data.get('room_id'))
    player_id = data.get('player_id')
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if room.state == 'game_over':
        return {'status': 'error', 'message': '对局已结束'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}
    return _papal_discard_grant(room, player_id, data.get('discard_card_index'))


@socketio.on('papal_attack')
@_require_live_room
def handle_papal_attack(data):
    """旧事件名，保留兼容（浏览器可能还缓存着旧的 game.js）。

    ⚠️ 改版后这个入口只做"弃卡换次数"，参数里的 x/y【不再使用】。
    旧版是直接把两发打在指定的那个格子上；现在改成给次数、由玩家自己点格子，
    这样才符合作者要求的"和正常攻击逻辑一样"。
    """
    room = room_manager.get_room(data.get('room_id'))
    player_id = data.get('player_id')
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if room.state == 'game_over':
        return {'status': 'error', 'message': '对局已结束'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

    res = _papal_discard_grant(room, player_id, data.get('discard_card_index'))
    if isinstance(res, dict) and res.get('status') == 'success':
        res['message'] += '（旧入口：x/y 已不再使用，请用普通攻击点选格子）'
    return res


def _sanitize_magic_targets(targets):
    """校验并归一化魔法卡目标坐标；返回 (targets, error_message)。

    仅处理 dict 形态的目标数据（前端 target_area/target_line/target_cells 等），
    数组/None 交由各卡牌分支自行处理。
    """
    if not isinstance(targets, dict):
        return targets, None

    area = targets.get('target_area')
    if isinstance(area, dict):
        for k in ('x1', 'y1', 'x2', 'y2'):
            if k not in area:
                return targets, '目标区域参数缺失'
            try:
                v = int(area[k])
            except (TypeError, ValueError):
                return targets, '目标区域坐标非法'
            if not (0 <= v <= 5):
                return targets, '目标区域坐标超出棋盘范围'
            area[k] = v

    line = targets.get('target_line')
    if isinstance(line, dict):
        if line.get('type') not in ('row', 'col'):
            return targets, '目标行列参数非法'
        try:
            idx = int(line.get('index'))
        except (TypeError, ValueError):
            return targets, '目标行列坐标非法'
        if not (0 <= idx <= 5):
            return targets, '目标行列坐标超出棋盘范围'
        line['index'] = idx

    for key in ('target_cells', 'selected_cells'):
        cells = targets.get(key)
        if isinstance(cells, list):
            for c in cells:
                if not isinstance(c, dict):
                    return targets, '目标格子格式错误'
                try:
                    cx, cy = int(c['x']), int(c['y'])
                except (KeyError, TypeError, ValueError):
                    return targets, '目标格子坐标非法'
                if not (0 <= cx <= 5 and 0 <= cy <= 5):
                    return targets, '目标格子坐标超出棋盘范围'
                c['x'], c['y'] = cx, cy

    return targets, None


def _pick_cell_from_target(target_data):
    """从目标数据里取出玩家点选的单个格子 (x, y)；取不到返回 None。

    兼容两种前端形态：
    - `{'target_area': {'x1': x, 'y1': y, ...}}`（single 选择器 → 1x1 区域）
    - `{'x': x, 'y': y}`
    """
    if not isinstance(target_data, dict):
        return None

    area = target_data.get('target_area')
    if isinstance(area, dict):
        try:
            return int(area['x1']), int(area['y1'])
        except (KeyError, TypeError, ValueError):
            return None

    if 'x' in target_data and 'y' in target_data:
        try:
            return int(target_data['x']), int(target_data['y'])
        except (TypeError, ValueError):
            return None

    return None


def _is_ship_alive(player, ship):
    """这艘船是否还活着（没沉、也没被牺牲掉）。

    ⚠️ 本项目的「击沉」只减 `player.remaining_ships`，**不会把船从 `player.ships` 里移走**
    —— 沉船留在列表里供复活类效果回收。所以任何「让玩家挑一艘自己的船」的地方都必须
    先过这一层，否则会出这些事：
      · 克苏鲁之眼：对手拿一艘早就沉了的船来「暴露」，等于什么都没暴露
      · 恶魔契约 / 神之宣告：拿沉船抵账 = 零代价发动
      · 仁王之盾：把护盾加在一艘沉船上，白白浪费
    判定同时看两份依据（沉船堆 / 命中数），任一成立即视为已死，避免两边不同步时漏判。
    """
    if ship is None:
        return False
    if ship in (getattr(player, 'sunken_ships', None) or []):
        return False
    positions = getattr(ship, 'positions', None) or []
    hits = getattr(ship, 'hits', None) or []
    return len(hits) < len(positions)


def _alive_ships(player):
    """该玩家目前还活着的船（顺序与 player.ships 一致，便于按原下标回传）。"""
    return [sh for sh in (getattr(player, 'ships', None) or []) if _is_ship_alive(player, sh)]


def _dead_ship_count(player) -> int:
    """该玩家**已经沉掉**的船数（第 2 批的「累计击沉」口径）。

    ⚠️ 不许写成 `len(player.ships)`：本项目的击沉大多**不把船移出 `ships`**
    （沉船留在列表里供复活回收），扫 `ships` 数长度会得到「一艘都没沉」这种完全
    相反的结论 —— 第 1 批为这个口径专门写过一节（`frozen_ship_count`、
    冻结播报、放置合法性都栽过）。

    不许只读 `len(sunken_ships)`：那只是**登记表**，虽然 `_mark_ship_sunken()`
    是唯一登记入口，但只要有一条路径忘了登记（本项目真发生过：幽灵计数那批），
    单看登记表就会漏计。所以取**两份来源的并集**（与 `_own_occupied_cells` 同一形状）：

      · `ships` 里**已经不活**的（`_is_ship_alive` 为假）—— 与 `_alive_ships()`
        用同一个判据，两者互补：一个数活的、一个数死的；
      · `sunken_ships` 里**已经不在 `ships` 中**的 —— 轰炸 / 硫磺火焰 / 牺牲会
        `ships.remove(...)`，这些船只剩在登记表里。

    复活会把船从 `sunken_ships` 里 pop 掉且 `hits < positions`，于是两边都不算它。

    ⚠️ **已知的口径边界**：自牺牲（恶魔契约 / 神之宣告 / 绝处逢生）也走
    `_mark_ship_sunken`，所以"己方自牺牲"会被算进**对方的**击沉数。要精确区分
    "被对方打沉"与"自己牺牲"需要额外的登记字段，本批不做（计划只要求「活船变死船」）。
    """
    ships = getattr(player, 'ships', None) or []
    dead = set()
    for ship in ships:
        if ship is not None and not _is_ship_alive(player, ship):
            dead.add(id(ship))
    for ship in (getattr(player, 'sunken_ships', None) or []):
        if ship is None:
            continue
        if ship not in ships:
            dead.add(id(ship))
    return len(dead)


def _took_any_damage(player) -> bool:
    """该玩家这局是否有过任何**实际伤害**（船被打中过）。

    「零伤获胜」的判据：被盾挡下的一炮不算伤害（仁王之盾把炮弹吃掉、船毫发无伤，
    盾挡的那一发也不会进 `hits` —— 这是 2026-09-14 那批定下的口径），
    无敌（infinite）与只显形不掉血的攻击同理：它们都**不往 `hits` 里写**，
    所以「扫 hits」天然就是「实际受伤」。
    """
    for ship in (getattr(player, 'ships', None) or []):
        if getattr(ship, 'hits', None):
            return True
    return False


def _match_started_at(room) -> float:
    """对局开始时间戳（用于「闪电战」的用时判定）。没有就返回 0，**不编**。

    优先取 `room.match_started_at`（猜拳结束、真正进入 attacking 时打点，
    见 `handle_rps_choice`）；老房间/测试构造的 room 没有这个字段，退回
    `room.created_at`（建房时间，真实存在但含"等人入座"的时间）。
    两个都没有就返回 0 —— 调用方据此判定「本次没有可信用时」而不是当成 0 秒。
    """
    for attr in ('match_started_at', 'created_at'):
        value = getattr(room, attr, None)
        try:
            if value:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _thaw_ship(ship) -> bool:
    """解除一艘船的冻结标记（frozen 是动态属性，没有就什么都不做）。

    解冻（大回合推进）、以及【复活】都必须走这里：沉船被打上 frozen 后仍留在
    `player.ships` 里，回合推进的解冻循环只扫 `player.ships`，被
    轰炸/硫磺火焰移出列表的船就漏掉了 —— 它带着上一轮的 frozen 复活回来，
    会继续被算进 `frozen_ship_count`，凭空少掉一次攻击。
    """
    if ship is not None and getattr(ship, 'frozen', None):
        try:
            del ship.frozen
        except AttributeError:
            return False
        return True
    return False


def _find_ship_at(player, cell, alive_only=False):
    """返回该玩家在指定格子上的一艘船；没有则返回 None。

    alive_only=True 时跳过已沉的船 —— 「选一艘自己的船」类的卡都必须这么用，
    否则点到自己沉船所在的格子也会被当成有效选择（见 _is_ship_alive）。
    """
    if not cell:
        return None
    x, y = cell
    for ship in getattr(player, 'ships', []) or []:
        if alive_only and not _is_ship_alive(player, ship):
            continue
        for pos in getattr(ship, 'positions', []) or []:
            if pos.x == x and pos.y == y:
                return ship
    return None


@socketio.on('use_magic_card')
@_require_live_room
def handle_use_magic_card(data):
    room_id = data['room_id']
    player_id = data['player_id']
    try:
        card = MagicCard(**data['card'])
    except (ValueError, TypeError, KeyError) as e:
        # 卡牌数据非法（未知卡名 / 非 dict / 缺字段）：返回错误而非让 handler 崩溃
        return {'status': 'error', 'message': f'魔法卡数据无效: {e}'}
    targets = data.get('targets', [])

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    targets, target_err = _sanitize_magic_targets(targets)
    if target_err:
        return {'status': 'error', 'message': target_err}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

    player = room.players[player_id]
    opponent_id = next(p for p in room.players if p != player_id)

    # 连锁响应窗口未关闭时，应通过 chain_response 响应，而不是再打出新牌
    if room.chain_waiting:
        return {'status': 'error', 'message': '连锁响应中，请先响应连锁'}

    # 已被拦下的阶段转换：等待对方响应期间发起方不能继续出牌。
    # （响应者不受影响 —— 他此刻要做的正是"响应"，走 priority_response。）
    wait = _action_wait_reason(room, player_id)
    if wait:
        return {'status': 'error', 'message': wait}

    # 看破！：被封锁的玩家本大回合无法使用魔法卡
    if player.magic_blocked:
        return {'status': 'error', 'message': '你的魔法卡已被看破，本回合无法使用'}

    # 检查卡牌是否在玩家手牌中
    if not any(c.name == card.name and c.speed == card.speed for c in player.magic_hand):
        return {'status': 'error', 'message': '你没有这张魔法卡'}

    # ★ 选船优先级闸门（2026-09-20）：有**更高优先级**的待选时，不许再打选船类卡。
    #   卡面语义就是"必须先牺牲船，然后才能暴露"——所以这里**拒绝出牌**并给出明确文案，
    #   而不是排队后延迟重放（那要处理"施法目标已被打沉"等一串边界，风险远大于收益）。
    #   ⚠️ 只拦选船类卡（`_SHIP_PICK_CARDS`）：非选船卡任何时候都放行。
    _pick_blocked = _ship_pick_blocked_reason(room, player_id, card.name)
    if _pick_blocked:
        return {'status': 'error', 'message': _pick_blocked}

    # 检查是否可以在当前阶段使用
    if not can_play_magic_card(room, player_id, card):
        reason = None
        if player.effect_flags.last_stand:
            # 绝处逢生：生效回合内自己的其余魔法卡全部无效。
            # 这条必须排在阶段兜底之前 —— 否则玩家会收到「当前阶段battle无法
            # 使用速阶1」这种与真实原因毫无关系的提示（阶段明明是对的）。
            reason = '绝处逢生生效中，本回合你的其余魔法卡全部无效'
        elif card.name in END_PHASE_PLAYABLE:
            # 这类卡有专属条件，把具体原因告诉玩家，别只报「速阶2」
            reason = freezing_block_reason(room, player_id, card)
        elif card.name == '五险一金' and field_magic_name(room) == '教皇旨意':
            reason = '教皇旨意生效中，本回合攻击次数为0，五险一金无法发动'
        elif field_magic_name(room) == '禁忌果实' and not (card.name == '失灵！' or card.type == '场地'):
            reason = '场地魔法“禁忌果实”生效中，非场地及失灵类魔法卡无法使用'
        elif int(card.speed) != 3 and room.current_attacker != player_id:
            # ⚠️ 必须排在阶段兜底之前。
            #
            # can_play_magic_card 里「速阶1/2 只能在自己的回合使用」这一条，
            # 是玩家最常撞上的拒绝原因，但此前没有对应的文案分支 —— 于是掉进
            # 最后的阶段兜底，弹出「当前阶段preparation无法使用速阶2的魔法卡」。
            # 阶段本身完全合法（准备阶段本来就允许速阶2），玩家据此以为游戏坏了、
            # 跑去反馈「轰炸在准备阶段用不了」，实际原因只是没轮到他。
            reason = f'速阶{card.speed}的魔法卡只能在自己的回合使用（现在不是你的回合）'
        return {'status': 'error',
                'message': reason or f'当前阶段{room.current_phase}无法使用速阶{card.speed}的魔法卡'}

    # 依赖「自己上一发攻击」的卡，在这里就把条件判掉。
    #
    # ⚠️ 为什么必须放在扣牌【之前】：下面那几行会先把手牌移入弃牌堆、再压入连锁栈，
    # 而这类卡要到 apply_magic_effect 结算时才发现条件不满足 —— 那时牌已经离手，
    # 失败也不会退还。玩家实测：打空一发后用饮血，提示「当前无法使用饮血」，
    # 但牌从手牌里消失了。溅射 / 雷达子弹 同理。
    hit_reason = _last_attack_requirement_reason(room, player_id, card)
    if hit_reason:
        return {'status': 'error', 'message': hit_reason}

    # 亡羊补牢：发动条件「弃牌区有卡牌」也必须扣牌前判，否则扣进去的亡羊补牢自己
    # 会让条件被动满足，玩家会以为「明明弃牌区空着却发动成功了」。
    wangyang_reason = _wangyang_requirement_reason(room, player_id, card)
    if wangyang_reason:
        return {'status': 'error', 'message': wangyang_reason}

    # 卧薪尝胆：发动条件「自己船数 < 对方船数」同样扣牌前判，避免无效发动消耗手牌。
    woxin_reason = _woxin_requirement_reason(room, player_id, card)
    if woxin_reason:
        return {'status': 'error', 'message': woxin_reason}

    # 找到并移除玩家手牌中的卡牌
    for i, c in enumerate(player.magic_hand):
        if c.name == card.name and c.speed == card.speed:
            player.magic_hand.pop(i)
            break
    if card.type != '场地':
        room.magic_discard.append(card)

    # 手牌变了就立刻以服务端为准推给玩家。
    #
    # ⚠️ 此前这里【一个 emit 都没有】：扣牌之后要等到连锁结算（resolve_chain 收尾
    # 那次统一重推）客户端才知道牌离手了。中间这段时间前端只能靠自己"打出成功
    # 后本地删一张"来凑（sendMagicCard 的 splice）。可这条本地推断会出错：
    #   · 出牌后紧接着收到别的 hand_updated，本地下标/内容已经换了
    #   · 效果自己也会改手牌（摸牌、被埋葬、盗亦有道），本地推断覆盖不到
    # 一旦本地推断和真实手牌错开，界面就会显示不存在的手牌 —— 也就是作者反馈的
    # 「打完一张，剩下的手牌就不对了 / 没了，刷新才恢复」。
    # 服务端是手牌的唯一权威，改了就说，别让前端猜。
    emit('hand_updated', {'hand': player.magic_hand}, to=player.sid)

    # 场地魔法卡不再在此预置：改由结算（apply_magic_effect 场地分支）实例入区，
    # 避免"打出即进弃牌堆 + 贴场"产生游离副本；被顶掉/被康时实例移入弃牌堆。

    # 统计"打出次数"（被康掉也算打出过，所以记在入链时刻而不是结算时刻）
    # 个人统计取施法者的 Player.user_id：匹配房里 room.players 的 key 是 socket
    # sid，不能当用户 id 用；游客没有 user_id，那就只写全局表。
    record_card_use(card, user_id=getattr(player, 'user_id', None))

    # 添加到连锁栈
    chain_item = ChainItem(player_id, card, targets, time.time())
    room.chain.append(chain_item)

    # 广播连锁更新
    emit('magic_chain_updated', {
        'chain': room.chain
    }, room=room_id)

    # 连锁响应窗口：先给对方；对方放弃后窗口回到最后压栈者（支持自连锁）
    room.chain_passes = 0
    _advance_chain_window(room, opponent_id)

    return {'status': 'success', 'message': f'魔法卡{card.name}已加入连锁'}


# 结束阶段默认禁止使用魔法卡，但以下卡设计上就在结束阶段发动。
# （前端 static/game.js 的 canPlayCard 有一份对应名单，改动需同步。）
END_PHASE_PLAYABLE = ('Freezing！',)


def freezing_block_reason(room, player_id, card):
    """Freezing！ 的专属发动条件；不满足时返回原因，满足返回 None。

    三条缺一不可：自己先手 / 结束阶段 / 本回合没让对方船数减少。
    """
    if room.attack_order and room.attack_order[0] != player_id:
        return 'Freezing！只能在自己先手的回合发动'
    if room.current_phase != 'end':
        return 'Freezing！只能在结束阶段发动'
    if room.players[player_id].damage_dealt_this_turn > 0:
        return '本回合已使对方船数减少，无法发动 Freezing！'
    return None


def _last_attack_requirement_reason(room, player_id, card):
    """依赖「自己上一发攻击」的卡，返回不满足条件的原因；满足则返回 None。

    这几张卡的卡面都写着「可在…后选择使用」，共同前提是自己刚打完一发：
      · 饮血     —— 须【击沉】一艘（卡面已同步为此口径）
      · 越战越勇 —— 须【击沉】一艘（卡面：「仅可在击沉对方的一艘战舰后立即使用才会有效」）
      · 溅射     —— 须【击中】（对命中格上下左右造成同等伤害）
      · 雷达子弹 —— 须【击中】（扫描命中格周围八格）

    必须在扣牌前调用：这些条件原先只在 apply_magic_effect 里判，那时牌已经
    移出手牌并进了弃牌堆，失败也不退还 —— 玩家会看到「无法使用」+ 牌没了。
    """
    if card.name not in ('饮血', '越战越勇', '溅射', '雷达子弹'):
        return None

    last = getattr(room, 'last_attack', None)
    if not last or last.get('attacker') != player_id:
        return f'{card.name}需要在自己攻击过之后才能使用'

    if card.name in ('饮血', '越战越勇'):
        # 击沉才算数：拿"命中"当门槛会让玩家打中一艘没沉的船就以为能发动。
        if not last.get('ship_sunk'):
            return f'{card.name}需要在击沉对方一艘战舰后立即使用'
    else:
        if not last.get('hit'):
            return f'{card.name}需要在自己上一发攻击命中对方后才能使用'

    return None


def _wangyang_requirement_reason(room, player_id, card):
    """亡羊补牢的发动条件；不满足时返回原因，满足则返回 None。

    卡面：「当弃牌区有卡牌时可以发动」。
    此处按字面判断 magic_discard 非空 —— 出牌扣牌流程尚未执行，
    所以判的是「打出亡羊补牢之前」弃牌区是否已有牌。
    这样判定与用户裁定「候选不含刚打出的亡羊补牢自己」一致：
    打出去之后即便它进了弃牌堆，自己也不算候选。
    """
    if card.name != '亡羊补牢':
        return None
    if not room.magic_discard:
        return '弃牌区没有卡牌，亡羊补牢无法发动'
    return None


def _woxin_requirement_reason(room, player_id, card):
    """卧薪尝胆的发动条件；不满足时返回原因，满足则返回 None。

    卡面：「当自己的船数小于对方的场合可以发动」。
    用 remaining_ships 比较（"船数"指当前剩余战舰数，与卡面字面一致）。
    """
    if card.name != '卧薪尝胆':
        return None
    opponent_id = _opponent_of(room, player_id)
    if not opponent_id or opponent_id not in room.players:
        return None
    mine = room.players[player_id].remaining_ships
    theirs = room.players[opponent_id].remaining_ships
    if mine >= theirs:
        return f'自己的船数({mine})不小于对方({theirs})，卧薪尝胆无法发动'
    return None


def can_play_magic_card(room, player_id, card):
    # 绝处逢生：生效回合内自己的其余魔法卡全部无效（last_stand 随回合标志重置自然过期）
    if room.players[player_id].effect_flags.last_stand:
        return False

    # Freezing！ 有专属条件（先手 / 结束阶段 / 未让对方减船），在此一并拦掉，
    # 避免"卡进了连锁、结算时才被拒"这种玩家看不到原因的失败。
    if card.name in END_PHASE_PLAYABLE:
        return freezing_block_reason(room, player_id, card) is None

    # 五险一金：教皇旨意优先级更高，它生效时本回合攻击次数恒为 0，这张牌一次都
    # 触发不了 —— 出牌前就拦掉，别让玩家白扔一张卡（结算时才拒的话卡已经没了）。
    if card.name == '五险一金' and field_magic_name(room) == '教皇旨意':
        return False

    # 确保speed是数字类型
    speed = int(card.speed)

    # 禁忌果实: 双方都无法使用任何魔法卡，除失灵！与其他场地魔法卡
    if field_magic_name(room) == '禁忌果实':
        if card.name != '失灵！' and card.type != '场地':
            return False

    if speed == 3:
        # 速阶3的卡牌可以在任何时候使用
        return True

    # 速阶1和速阶2只能在自己的回合使用
    if room.current_attacker != player_id:
        return False

    # 根据当前阶段和速阶检查
    if room.current_phase == 'preparation':
        # 准备阶段可以使用速阶1和速阶2的卡牌
        return speed in [1, 2]
    elif room.current_phase == 'battle':
        # 战斗阶段可以使用速阶1和速阶2的卡牌
        return speed in [1, 2]
    elif room.current_phase == 'end':
        # 结束阶段默认不能使用魔法卡；
        # 例外：Freezing！ 的设计就是「自己先手回合的结束阶段」发动。
        return card.name in END_PHASE_PLAYABLE
    return False


CHAIN_RESPONSE_SECONDS = 10

# 回合思考计时（秒）：0 = 关闭。此前只有连锁窗口有超时，炮击/准备阶段可以无限
# 长考，对手只能干等。超时只做一次「保底动作」，不判负：
#   准备阶段 → 自动进入战斗阶段；战斗阶段 → 随机开火一发；结束阶段 → 交出回合。
# 每做一次有效操作就重新计时（见 _require_live_room），只惩罚完全卡住不动的人。
TURN_TIMEOUT_SECONDS = int(os.environ.get('TURN_TIMEOUT_SECONDS', '90') or '0')


def _emit_player_ships(room, player_id):
    """只发给本人：同步己方棋盘（放置/原地复活后立刻显示新船）。"""
    player = room.players.get(player_id)
    if not player:
        return
    emit('player_ships_updated', {
        'ships': [{
            'positions': [{'x': p.x, 'y': p.y} for p in sh.positions],
            'hits': [],
            # 冻结状态必须一起下发：冻结的船不提供攻击次数，
            # 玩家此前在棋盘上完全看不出哪几艘被冻住了。
            'frozen': bool(getattr(sh, 'frozen', None)),
            # 存活状态：沉船仍留在 ships 列表里，前端自己判断不出死活；
            # 「选一艘自己的船」类的卡要靠它把沉船灰掉（克苏鲁之眼/仁王之盾…）。
            'alive': _is_ship_alive(player, sh),
            # 盾牌 / 无敌也要下发：仁王之盾一次性挡伤、钢筋铁骨让全船无敌，
            # 前端此前拿不到这两个状态，既画不出标记，也不知道盾已经被消耗掉
            # （图标做不出来，或画出来下不去）。
            'shield': bool(getattr(sh, 'shield', False)),
            'invincible': bool(getattr(sh, 'invincible', False)),
        } for sh in player.ships]
    }, to=player.sid)


def _emit_ships_updated(room):
    """按每个收件人自己的视角下发船数。

    原先统一以施法者/攻击者视角 room 广播，导致对手界面上
    "你的船数" 与 "对手船数" 互换。
    """
    for pid, player in room.players.items():
        opp_id = _opponent_of(room, pid)
        opp = room.players.get(opp_id) if opp_id else None
        emit('ships_updated', {
            'player_remaining_ships': player.remaining_ships,
            'opponent_remaining_ships': opp.remaining_ships if opp else 0,
        }, to=player.sid)


# 前端「当前生效效果」角标的数据源。
# 角标以前是前端自己 `innerHTML +=` 挂上去的，挂上就再没人摘 —— 百亿补贴明明
# 每回合切换就被清掉了，角标却一直亮着，玩家以为效果是永久的。
# 现在改成服务端在状态变化后广播真相，前端只负责照着画，不会再出现「贴上就下不来」。
# ── 「生效中效果」角标 ────────────────────────────────────────────────
# 每个效果是 (effect_flags 字段, 显示名, 失效时机)。
#
# 失效时机必须与代码里的真实清理点一致，不能凭卡面猜：
#   · 小回合切换（end_turn）只保留 permanent_flags 里那几个：
#       ['holy_heart', 'reinforcement_check', 'no_draw', 'prediction', 'forced_kill']
#     所以 no_draw / prediction 能跨小回合活下来 → 大回合结束才清；
#   · 其余（百亿补贴 / 饮血 / 八方来财 / 火力全开 …）交出回合就清；
#   · 五险一金是「触发一次即失效」的机制，既不是回合末也不是大回合末；
#   · 大回合结束统一走 _prune_effect_flags(room, FLAGS_KEEP_ACROSS_ROUND)（空集）。
_EFFECT_EXPIRY_ROUND = '本大回合结束（重新猜拳）时失效'
_EFFECT_EXPIRY_TURN = '本回合结束时失效'
_EFFECT_EXPIRY_TRIGGER = '本回合攻击次数第一次归零时触发一次，触发后失效'
_EFFECT_EXPIRY_MATCH = '本局一直有效'

# ⚠️ 绝处逢生挂【两个】角标，生命周期不同（见 EffectFlags 的注释）：
#   锁卡那条换小回合就灭，击杀即胜那条一直亮到对局结束。合成一条的话，
#   玩家要么以为击杀即胜过期了，要么以为还能继续锁卡，两种都会误判。
#
# 元组第 4 位是**可选的显示后缀**：两条角标的卡名都是「绝处逢生」（角标名必须
# 是真实卡名，浮层靠它取卡面说明 —— 有测试钉着这条契约），光看卡名分不出是哪条，
# 所以另给一个后缀让前端拼成「绝处逢生·锁卡 / 绝处逢生·击杀即胜」。
_EFFECT_BADGES = (
    ('subsidy', '百亿补贴', _EFFECT_EXPIRY_TURN, ''),
    ('wuxian', '五险一金', _EFFECT_EXPIRY_TRIGGER, ''),
    ('vampire', '饮血', _EFFECT_EXPIRY_TURN, ''),
    ('treasure_hunter', '八方来财', _EFFECT_EXPIRY_TURN, ''),
    ('prediction', '神机妙算', _EFFECT_EXPIRY_ROUND, ''),
    ('double_attacks', '火力全开', _EFFECT_EXPIRY_TURN, ''),
    ('battle_spirit', '越战越勇', _EFFECT_EXPIRY_TURN, ''),
    ('last_stand', '绝处逢生', _EFFECT_EXPIRY_TURN, '锁卡'),
    ('last_stand_win', '绝处逢生', _EFFECT_EXPIRY_MATCH, '击杀即胜'),
    ('no_draw', '无中生有', _EFFECT_EXPIRY_ROUND, ''),
)

# 效果名 → 卡面原文。前端悬停/点击角标时要显示「这个效果到底做什么」，
# 文字直接复用卡牌数据，避免两处各写一份而漂移。
_CARD_DESCRIPTION = {c.name: (c.description or '') for c in magic_cards}


def _effect_badges(player):
    """返回该玩家当前仍生效的效果，带卡面说明与失效时机（供前端角标与浮层用）。"""
    flags = getattr(player, 'effect_flags', None)
    if flags is None:
        return []
    out = []
    for attr, label, expiry, suffix in _EFFECT_BADGES:
        if not getattr(flags, attr, None):
            continue
        out.append({
            'name': label,
            'key': attr,
            # 显示名 = 卡名 +（可选）后缀。**卡名单独保留**，前端浮层靠 name 取卡面说明；
            # label 只用于展示。绝处逢生两条角标就是靠这个后缀区分开的。
            'label': f'{label}·{suffix}' if suffix else label,
            'description': _CARD_DESCRIPTION.get(label, ''),
            'expires': expiry,
        })
    return out


def _emit_active_effects(room):
    """把「当前生效效果」推给双方。

    ⚠️ 此前只发本人（注释写着"角标是给自己看的状态，不广播给对方"），
    于是玩家完全看不到对手身上挂着什么。作者要求双方都可见：
    这些效果本来就是对方明牌打出的卡造成的，公开不泄露任何信息。
    每条同时带上卡面说明与失效时机，前端悬停/点击即可展开。
    """
    for pid, player in room.players.items():
        if not getattr(player, 'sid', None):
            continue
        opp_id = _opponent_of(room, pid)
        opp = room.players.get(opp_id) if opp_id else None
        emit('active_effects', {
            'self': _effect_badges(player),
            'opponent': _effect_badges(opp) if opp else [],
        }, to=player.sid)


def _maybe_trigger_wuxian_yijin(room, player_id):
    """五险一金：本回合攻击次数【第一次归零】且那时没让对方减船 → 攻击次数 +3。

    卡面：「这一回合自己的攻击次数第一次用尽时，若自己未曾对对方造成一点伤害，
    则自己的攻击次数再加3」。关键是「什么时候结算」：出牌只是挂上保险
    （effect_flags.wuxian），真正的 +3 要等攻击次数第一次变成 0 才结算 ——
    不是一打出就白送 3 次。触发后立刻清标记，保证只生效一次。

    所有会让攻击次数归零的入口都要调它（攻击结算 / 进入战斗阶段 / 出牌瞬间已经是 0），
    否则会出现「已经 0 次了却永远等不到触发」的漏网情况。

    ⚠️ 教皇旨意优先级更高：它生效时双方攻击次数被压成 0 是**场地规则**，
    不是「你把攻击打光了」，所以这里绝不能给它补次数。

    返回 True 表示这次真的触发了。
    """
    player = room.players.get(player_id)
    if player is None or not getattr(player.effect_flags, 'wuxian', False):
        return False

    # 教皇旨意 > 五险一金：场地规则优先，补次数等于直接掀掉这张场地魔法
    if field_magic_name(room) == '教皇旨意':
        return False

    # 只有「当前攻击者」的攻击次数才是他自己的
    if room.current_attacker != player_id:
        return False
    if room.attacks_remaining > 0:
        return False
    # 这一回合让对方减过船就不给
    if player.damage_dealt_this_turn > 0:
        return False

    player.effect_flags.wuxian = False   # 只触发一次
    room.attacks_remaining += 3

    add_game_log(room, f'第{room.round}回合 · {_log_name(room, player_id)} 触发五险一金，攻击次数 +3',
                 'magic', {'player': player_id, 'card': '五险一金'})
    emit('message', {'text': '五险一金生效：攻击次数已用尽且未造成伤害，攻击次数 +3'},
         to=player.sid)
    emit('attacks_updated', {
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining
    }, room=room.id)
    # 标记已消耗，角标要跟着消失
    _emit_active_effects(room)
    return True


def _notify_treasure_hunter(room, times=1, exclude_player_id=None):
    """八方来财：场上战舰数目【主动变化】时，持卡者摸牌。

    卡面：「接下来如果场上的战舰数目主动发生了变化，每发生一次变化，自己摸一张牌。
           己方击败对方的船不算主动发生变化。」

    据作者澄清，判定口径（"己方"= 持卡者自己）：
      · 持卡者【自己】开炮击沉对方的船 → 不算（调用方传 exclude_player_id=持卡者）
      · 对方开炮击沉持卡者的船       → 算
      · 【任意一方】因卡牌效果主动改变船数（死者苏生 / 增援 / 疗愈 / 神威归还…）
                                    → 算

    ⚠️ 关键：判定的对象是【全场任意一方的】船数变化，而摸牌的是【持卡者】。
    这两者必须解耦 —— 此前实现把"变化方"和"持卡者"当成同一个人，
    于是"对方用增援复活自己的船"对持卡者毫无反应，与卡面不符。

    exclude_player_id：本次变化【不算数】的那个持卡者（"己方击败对方的船"）。
                       传变化方的 id 即可；其他持卡者照常摸牌。
    times：一次结算里变了 N 艘就摸 N 张。
    """
    holders = [pid for pid, p in room.players.items()
               if getattr(p.effect_flags, 'treasure_hunter', False)]
    total = 0
    for pid in holders:
        if exclude_player_id is not None and pid == exclude_player_id:
            continue          # 这一位是"己方击败对方的船"，按卡面不算
        n = max(0, int(times))
        for _ in range(n):
            room.draw_card(pid)
            total += 1
        if n:
            emit('message', {'text': f'八方来财生效，摸{n}张牌'},
                 to=room.players[pid].sid)
    return total


def _emit_board_attacks(room):
    """把「谁打过哪些格子」按收件人视角重新下发。

    ⚠️ 为什么必须有这个广播：前端的 myAttacks / opponentAttacks 是【本地缓存】，
    而 initGameBoards() 只在 `!alreadyAttacked` 时才给对手棋盘的格子绑点击监听。
    复活/增援/重新部署把格子从服务端攻击历史里清掉之后，如果不重发：

      · 当初打过这一格的对手，那颗仍画着 ✕、【没有点击监听】——
        作者实测报的「疗愈在原地复活之后对方无法攻击这个格子」就是这个：
        服务端数据其实已经放行，但前端连点都点不动。
      · 复活的这一方，自己棋盘上那格也仍留着对方的 ✕，看起来像还没活。

    两个列表都发，收到哪边就用哪个。
    """
    for pid, player in room.players.items():
        opp_id = _opponent_of(room, pid)
        opp = room.players.get(opp_id) if opp_id else None

        def _cells(owner):
            if owner is None:
                return []
            return [{'x': a.x, 'y': a.y, 'hit': bool(a.hit),
                     'ship_sunk': bool(getattr(a, 'ship_sunk', False))}
                    for a in getattr(owner, 'attacks', [])]

        emit('board_attacks_updated', {
            'my_attacks': _cells(player),
            'opponent_attacks': _cells(opp),
        }, to=player.sid)


def _clear_attacks_on_cells(room, positions, board_owner_id):
    """把指定格子从【对手打到这块棋盘上】的攻击历史里移除，并把结果重新下发给两端。

    复活 / 增援 / 重新部署之后必须做这一步，否则会出两种问题：
      · 前端仍按旧的攻击记录把这些格子画成"已命中"，玩家看到刚放上去的船
        挂着一个 ✕；
      · handle_attack 会以"你已经攻击过这个位置了"拒绝对方再打这里 ——
        这艘船永远打不沉，变成幽灵船，对手永远无法获胜。

    ⚠️ 2026-09-14 补充：清服务端数据【还不够】。前端那两个列表是本地缓存，
    必须用 _emit_board_attacks 重发一次 —— 否则玩家点不动那个格子
    （见该函数的注释）。

    ⚠️ 2026-09-16 修正：**只能清对手那份**。两个坐标空间是不同的 ——
    `room.players[p].attacks` 记的是「p 打到**对方**棋盘上的格子」。
    所以"我要把船放回**我的** (x,y)"这件事只跟**对手**的记录有关。
    旧实现把这一格从**双方**列表里都删，于是同一坐标在两边都存在时
    （例如双方都打过 (0,0)，实战里很常见）会把"我打在对方棋盘的 ✕"一起误删：
      · 自己看对方棋盘，那一格的 ✕ 凭空消失；
      · handle_attack 的"你已经攻击过这个位置"校验查的正是自己那份列表，
        被清后失效 → 能重复打那一格，等于白赚一炮。
    """
    cells = {(p.x, p.y) for p in (positions or [])}
    if not cells or not board_owner_id:
        return
    opponent_id = _opponent_of(room, board_owner_id)
    if not opponent_id or opponent_id not in room.players:
        return
    before = len(room.players[opponent_id].attacks)
    room.players[opponent_id].attacks = [
        a for a in room.players[opponent_id].attacks if (a.x, a.y) not in cells
    ]
    if len(room.players[opponent_id].attacks) != before:
        _emit_board_attacks(room)


def _reveal_cells_to(room, player_id, positions, kind=None):
    """把若干格子「显形」给某个玩家（写进持久的 revealed_positions 并立刻下发）。

    kind 供前端区分来源：'heal' = 疗愈原地复活（对方需要知道"船又回到这一格了"）；
    缺省 = 旧的通用显形（探测雷达 / 克苏鲁之眼等），保持原样不动。

    ⚠️ 只用于【本来就已经公开】的格子（例：沉船的原位置，双方都看见过）。
    死者苏生 / 增援 / 神机妙算重新部署是玩家自选的新位置，给他们做显形等于
    直接泄露新船位 —— 那三张卡不要调用这个函数。
    """
    player = room.players.get(player_id)
    if player is None or not positions:
        return
    payload = []
    for pos in positions:
        x, y = int(pos.x), int(pos.y)
        if not any(p.x == x and p.y == y for p in player.revealed_positions):
            player.revealed_positions.append(Position(x=x, y=y))
        payload.append({'x': x, 'y': y})
    if payload:
        emit('revealed_positions', {'positions': payload, 'kind': kind}, to=player.sid)


def _revive_sunken_ships(room, player, count, reveal_to=None):
    """把 count 艘已沉没的战舰放回棋盘（疗愈 / 神机妙算等复活类效果）。

    关键：必须清空 hits 并把原位置从双方攻击历史里移除。
    否则 hits 已等于 positions（船已沉），且这些格子谁都"已经打过"，
    该船将永远无法被击沉 → remaining_ships 永远 > 0 → 对手永远无法获胜。

    ⚠️ 必须校验"这艘船确实还没回到棋盘"：
    本项目的击沉不移出 ships，若 sunken_ships 里混进重复条目（历史数据、
    或修复前的旧对局），pop() 可能取到一艘其实还活着的船。此时若照旧
    remaining_ships += 1，就会出现"船数涨了、棋盘上没船"的幽灵计数 ——
    实测玩家报的"疗愈后战舰并没有复活"即由此而来。
    """
    revived_any = 0
    guard = 0
    while revived_any < int(count) and player.sunken_ships and guard < 32:
        guard += 1
        revived = player.sunken_ships.pop()
        # 这艘船其实没沉（重复条目）：丢弃这条幽灵记录，不计数
        if revived in player.ships and _is_ship_alive(player, revived):
            continue
        if revived not in player.ships:
            player.ships.append(revived)
        # ⚠️ 必须把该船在沉船堆里的【所有】记录一起清掉，不能只靠上面那一次 pop。
        # _is_ship_alive 的第一道判据是「船在 sunken_ships 里就视为已沉」——
        # 只要还留着一条重复记录，这艘船就仍被判为死船：hits 明明清空、
        # remaining_ships 也加了，前端按 alive=False 继续把它画成沉船 ——
        # 实测玩家报的"疗愈后战舰并没有复活"正是这个机制。
        while revived in player.sunken_ships:
            player.sunken_ships.remove(revived)
        # 注意：被击沉的船通常仍留在 ships 列表里，所以清空命中要无条件执行
        revived.hits = []
        for pos in revived.positions:
            pos.hit = False
        # 复活不该带回上一轮的冻结标记（见 _thaw_ship 说明）
        _thaw_ship(revived)
        # 这块棋盘属于 player：只清【对手】打在这里的记录
        _owner_id = next((pid for pid, pl in room.players.items() if pl is player), None)
        _clear_attacks_on_cells(room, revived.positions, _owner_id)
        # 原地复活：这一格对方"本来就知道"（那是他打沉的沉船位置），
        # 但对局中很容易忘。显形给他，前端用专属标记 + 悬停说明区分于雷达显形。
        if reveal_to is not None:
            _reveal_cells_to(room, reveal_to, revived.positions, kind='heal')
        player.remaining_ships += 1
        revived_any += 1
    # 八方来财：魔法卡造成的船数增加（疗愈 / 神机妙算复活）属于主动变化，
    # 全场持卡者都摸 —— 包括对手持有八方来财时，我复活自己的船他也摸。
    if revived_any:
        _notify_treasure_hunter(room, revived_any)
    return revived_any


def _opponent_of(room, player_id):
    """返回房间内另一名玩家的 id；找不到则 None。"""
    for pid in room.players:
        if pid != player_id:
            return pid
    return None


def _speed3_cards(room, player_id):
    player = room.players.get(player_id)
    if not player:
        return []
    return [c for c in player.magic_hand if int(c.speed) == 3]


def _ai_can_negate_chain_top(room, ai_id: str) -> bool:
    """困难难度下，AI 只在「康得动」时才开窗。

    ⚠️ 这里排除了「栈顶是自己打的牌」——这是 AI 的【策略选择】，不是规则限制：
    自连锁康自己的牌在规则上已经允许（见失灵！/加百列之光的分支），但 AI
    康自己的牌几乎总是自伤，所以让它别这么做。
    同时不能康看破！/加百列之光（卡面写明的免疫，硬康只会被服务端拒绝、
    白白把窗口拖到超时）。"""
    if not room.chain:
        return False
    top = room.chain[-1]
    if getattr(top, 'player_id', None) == ai_id:
        return False
    return getattr(getattr(top, 'card', None), 'name', None) not in ('看破！', '加百列之光')


def _can_respond_chain(room, player_id):
    """该玩家此刻能否打出速阶3响应连锁。

    AI 默认不参与；只有「困难」难度、手里有【失灵！】、且当前连锁康得动时才参与。
    """
    if not player_id:
        return False
    player = room.players.get(player_id)
    if not player or player.magic_blocked:
        return False
    # 绝处逢生：生效回合内自己的其余魔法卡全部无效 —— 连锁响应也不例外。
    # chain_response 里 can_play_magic_card 会拒掉，但那要等玩家点完卡才知道；
    # 在这里拦掉，窗口就不会打开，也不会被白白点一次。
    if player.effect_flags.last_stand:
        return False
    if player_id.startswith('ai-'):
        if getattr(room, 'ai_difficulty', 'normal') != 'hard':
            return False
        if not any(c.name == '失灵！' for c in player.magic_hand):
            return False
        return _ai_can_negate_chain_top(room, player_id)
    return bool(_speed3_cards(room, player_id))


def _advance_chain_window(room, player_id):
    """把响应窗口交给 player_id；无法响应者自动记为放弃并顺延。
    连续两次放弃（含自动放弃）后结算连锁。"""
    while True:
        if not player_id or player_id not in room.players:
            return resolve_chain(room)
        if _can_respond_chain(room, player_id):
            room.chain_window = player_id
            room.chain_waiting = True
            room.chain_timer += 1
            emit('chain_request', {
                'card': room.chain[-1].card,
                # 告诉客户端这张卡是谁打的：响应窗口会绕回最后压栈者自己
                # （自连锁），此时前端不能再写「对方发动了」。
                'caster': room.chain[-1].player_id,
                'speed3_cards': _speed3_cards(room, player_id),
                'countdown': CHAIN_RESPONSE_SECONDS,
            }, to=room.players[player_id].sid)
            _schedule_chain_timeout(room.id, room.chain_timer)
            if player_id.startswith('ai-'):
                # 窗口落在 AI 头上：让它自己响应，别干等到超时
                socketio.start_background_task(_ai_chain_respond, room.id, room.chain_timer)
            return
        # 无法响应：视为放弃
        room.chain_passes += 1
        if room.chain_passes >= 2:
            return resolve_chain(room)
        player_id = _opponent_of(room, player_id)


def _refund_card_to_hand(room, player_id, card, result) -> bool:
    """卡牌「根本没满足发动条件」时退回手牌，并明确告诉玩家原因。

    ⚠️ 为什么需要它：`handle_use_magic_card` 是【先扣牌进弃牌堆、再压连锁】，
    而一大批卡的条件要到 `apply_magic_effect` 结算时才发现不满足 ——
    那些分支一律 `result['success'] = False; return result`，牌既不退还也不回手，
    玩家看到「不满足某某条件」的同时牌没了（实测报的「效果没生效却把牌吞掉了」）。
    涉及：死者苏生/疗愈没有沉船、绝处逢生不足 3 艘、神之宣告不足 3 艘、
    平等条约没有船数变化、余音绕梁不在准备阶段、桃园结义撞上无中生有、
    区域卡没选目标、失灵！/加百列之光没有可无效化的目标 …

    只按【同一引用】退还：卡牌对象可能已被「盗亦有道」从弃牌堆偷走，
    按名字找会把同一张牌变成两张（凭空造牌），找不到一律不退。
    """
    player = room.players.get(player_id)
    if player is None or card is None:
        return False
    # 已经在手上：什么都不做（重复退还同样会造牌）
    if any(c is card for c in player.magic_hand):
        return False

    refunded = False
    for i, c in enumerate(room.magic_discard):
        if c is card:
            room.magic_discard.pop(i)
            player.magic_hand.append(card)
            refunded = True
            break
    if not refunded:
        # 场地卡出牌时【不入弃牌堆】（实例直接贴到 field_magic），
        # 所以它失败时只能在"确实不在场上"的前提下补回手牌。
        if getattr(card, 'type', None) == '场地' and room.field_magic is not card:
            player.magic_hand.append(card)
            refunded = True
    if not refunded:
        return False

    reason = (getattr(result, 'message', '') or '不满足发动条件').strip()
    emit('message', {'text': f'{card.name}未发动：{reason}，卡牌已退回手牌'}, to=player.sid)
    add_game_log(room, f'{_log_name(room, player_id)} 发动 {card.name} 失败：'
                       f'{reason}（卡牌退回手牌）', 'magic')
    return True


def resolve_chain(room):
    """结算连锁：栈顶先出（后发先至）。被无效化的项跳过效果。"""
    results = []

    while room.chain:
        chain_item = room.chain.pop()
        player_id = chain_item.player_id
        card = chain_item.card
        targets = chain_item.targets

        # 已被上方某张无效化卡标记：跳过其效果
        if chain_item.negated:
            # 把「被谁康的」写进提示：只说「X被无效化」玩家分不清是"被对手康了"
            # 还是"自己发动失败"，实测会误判成"效果没生效"。
            by = getattr(chain_item, 'negated_by', None)
            detail = f'{card.name}被{by}无效化' if by else f'{card.name}被无效化'
            result = ChainResult(card=card, caster=player_id, success=False,
                                 message=detail)
            result.negated_skip = True
            result.negated_by = by
            log_magic(room, player_id, card, f'但被{by}无效化' if by else '但被无效化')
            # 被无效化的场地卡：只进弃牌堆，绝不能顶掉/拆掉场上已有的场地。
            # （原实现用 _place_field_magic "贴了再拆"，会把场上另一张场地
            #   连带扫进弃牌堆 —— 一次无效化同时干掉两张场地。）
            if getattr(card, 'type', None) == '场地':
                if room.field_magic is not card:
                    room.magic_discard.append(card)
            results.append(result)
            continue

        # 应用卡牌效果
        result = apply_magic_effect(room, player_id, card, targets)
        result.caster = player_id
        log_magic(room, player_id, card, result.message if getattr(result, 'success', False) else '')

        # 条件不满足（效果根本没落地）：把牌退回手牌并说清原因，别让玩家白丢一张卡。
        # ⚠️ 被康的项不会走到这里（上面 negated 分支已经 continue），被康就该被消耗。
        if not getattr(result, 'success', False) and not getattr(result, 'negated_skip', False):
            _refund_card_to_hand(room, player_id, card, result)

        # 无效化类效果：把“正下方那一项”（下一个待结算项）标记为无效
        if getattr(result, 'negate_target', False) and room.chain:
            room.chain[-1].negated = True
            # 记下是谁康的，供结算时写出「X被Y无效化」这种明确因果
            room.chain[-1].negated_by = card.name

        results.append(result)
        # 记录魔法使用历史（盗亦有道等读取）
        if result.success:
            entry = {'card': card, 'caster': player_id,
                     'timestamp': time.time(), 'round': room.round}
            # 这张牌若在本轮连锁里已被「盗亦有道」偷走，写历史时要把标记带上 ——
            # 否则回退分支扫到这条没有 stolen 的记录，会允许同一张牌被再偷一次。
            ledger = room.game_effects.get('stolen_cards') or {}
            if id(card) in ledger:
                entry['stolen'] = True
            room.magic_history.append(entry)

    # 广播连锁结算结果
    emit('chain_resolved', {
        'results': results
    }, room=room.id)

    # 重置连锁状态
    room.chain = []
    room.chain_waiting = False
    room.chain_window = None
    room.chain_passes = 0
    # 盗亦有道的"已盗取"台账已完成合并，清掉避免无限增长
    # （卡牌实例被回收后 id() 可能被新对象复用，留着会误判新牌为已盗取）
    room.game_effects.pop('stolen_cards', None)

    # 这一批卡的效果刚落地，双方的 effect_flags 可能变了 —— 刷新角标
    _emit_active_effects(room)

    # 手牌也要重推：结算期间有多条路径会改变手牌，而它们各自的 emit 并不齐备 ——
    # 盗亦有道把偷来的牌 append 进手牌、桃园结义分配候选牌、无中生有等摸牌效果。
    # 漏推的表现是玩家看到"打出的牌还在手上"或"偷到了但没显示"。
    # 这里在连锁收尾统一同步一次，双方各自收自己的那份。
    for p in room.players.values():
        if getattr(p, 'sid', None):
            emit('hand_updated', {'hand': p.magic_hand}, to=p.sid)

    # 船数 / 自己的棋盘 / 阶段也要一并重推。
    # 结算期间有一批卡会直接改船或改阶段，而它们的分支里【一个 emit 都没有】：
    #   · 仁王之盾  —— 给至多 3 艘船加 shield，前端完全收不到（连加盾都不知道）
    #   · 钢筋铁骨  —— 牺牲 1 艘 + 其余无敌；前端仍显示 6 艘、无敌无标记
    #   · 回光返照  —— 清空自己的棋盘并把阶段推到 end
    # 靠每张卡各自补 emit 容易漏（已经漏过三次），统一在这里兜底最稳：
    # 与上面 active_effects / hand_updated 并列，覆盖所有在结算里改状态的卡。
    _emit_ships_updated(room)
    for pid in room.players:
        _emit_player_ships(room, pid)
    emit('phase_updated', {
        'current_phase': room.current_phase,
        'current_attacker': room.current_attacker
    }, room=room.id)

    # 优先权询问的收尾：响应者在窗口里打了速阶3，连锁现在结算完了，
    # 该把他拦下的那次阶段转换补上（否则发起者的回合永远停在原地）。
    # ⚠️ 先取出再清空：_priority_continue 会再进 enter_battle_phase，
    # 那条路径可能又开一次询问，不清就会重入。
    cont = getattr(room, 'priority_continue', None)
    if cont:
        room.priority_continue = None
        _priority_continue(room, cont['actor'], cont['action'])

    return results


def _ai_chain_respond(room_id: str, token: int):
    """困难难度：AI 在连锁响应窗口里用【失灵！】康掉对方的卡。

    响应不了（没牌 / 康不动）时明确放弃，避免把窗口拖到 10 秒超时。
    代际令牌保证过期窗口不会被旧任务误响应。
    """
    try:
        time.sleep(0.8)
        room = room_manager.get_room(room_id)
        if not room or room.state == 'game_over':
            return
        if not room.chain_waiting or room.chain_timer != token:
            return
        ai_id = room.chain_window
        if not ai_id or not ai_id.startswith('ai-'):
            return
        player = room.players.get(ai_id)
        if not player:
            return

        card = next((c for c in player.magic_hand if c.name == '失灵！'), None)
        if card is None or not _ai_can_negate_chain_top(room, ai_id):
            chain_response({'room_id': room_id, 'player_id': ai_id, 'chain': False})
            return

        resp = chain_response({
            'room_id': room_id,
            'player_id': ai_id,
            'chain': True,
            'card': {'name': card.name, 'speed': card.speed, 'type': card.type},
            'targets': [],
        })
        if not (resp and resp.get('status') == 'success'):
            # 万一被规则拒绝（例如窗口已过期），明确放弃而不是留个半开窗口
            chain_response({'room_id': room_id, 'player_id': ai_id, 'chain': False})
    except Exception as e:
        print(f'AI chain respond error: {e}')


def _schedule_chain_timeout(room_id: str, token: int):
    """连锁超时兜底：窗口玩家长时间未响应时视为放弃并顺延/结算。
    代际令牌使旧定时器自动作废，防止与玩家正常响应竞态双重结算。"""
    def _timeout():
        time.sleep(CHAIN_RESPONSE_SECONDS)
        room = room_manager.get_room(room_id)
        if room and room.chain_waiting and room.chain_timer == token:
            window_player = room.chain_window
            room.chain_waiting = False
            room.chain_window = None
            room.chain_passes += 1
            if room.chain_passes >= 2 or window_player is None:
                resolve_chain(room)
            else:
                _advance_chain_window(room, _opponent_of(room, window_player))
    socketio.start_background_task(_timeout)


# ============================================================================
# 阶段转换的「优先权询问」（速阶3抢时点的仲裁）
# ============================================================================
# 背景：速阶3卡牌"任何时候都能使用"，双方都能在任意时刻插入自己的牌。
# 而游戏只有一个仲裁点（连锁响应窗口），它：① 对方没有速阶3时会自动跳过、
# 不给选择权；② 不覆盖阶段推进这类非出牌操作。
# 实测：P2 在 P1 的准备阶段出速阶3，P1 随后仍能直接 enter_battle_phase，
# 两张牌的效果落地顺序没有任何定义。
#
# 方案 D（作者选定）：保留现有窗口机制，把"自动跳过"改成"总是询问"，
# 参照游戏王 YGO 的优先权确认。并新增「拒绝」开关防止占时间。
#
# 只问两个入口（作者裁定）：
#   · 进入战斗阶段（准备 → 战斗）
#   · 进入结束阶段（战斗 → 结束）
# 交回合不问（它本来就被连锁窗口拦着）；攻击不问（每回合 3-6 次，
# 一局上百次弹窗会毁掉体验）。
PRIORITY_SECONDS = CHAIN_RESPONSE_SECONDS   # 与连锁窗口统一为 10 秒


def _has_request_context():
    """当前是否处在真实的 socket 请求上下文里。

    与 _identity_ok 的"无上下文则跳过连接校验"是同一个惯例：
    单元测试直调 handler 时不该被询问机制挡住（没有真人可以点响应，
    弹窗也发不出去），否则所有调用 enter_battle_phase 的测试都会失败。
    """
    try:
        request.sid
        return True
    except RuntimeError:
        return False


# 阶段转换的显示名（只在提示文案里用）
PRIORITY_ACTION_TEXT = {
    'enter_battle': '进入战斗阶段',
    'enter_end': '进入结束阶段',
}


def _priority_pending_for(room, player_id):
    """如果该玩家正是"被拦下的那次阶段转换"的发起者，返回 pending，否则 None。"""
    pending = getattr(room, 'priority_pending', None)
    if pending and pending.get('actor') == player_id:
        return pending
    return None


def _priority_wait_reason(room, player_id):
    """发起方在等待对方响应期间，其余写操作一律冻结；返回拒绝原因，否则 None。

    ⚠️ 为什么必须冻（作者实测反馈：「在等待阶段转换的响应的时候，对方不能暂停行动」）：
    这个 10 秒窗口的**全部意义**就是仲裁"谁先动手"。可旧实现只拦了阶段转换本身，
    发起方在等待期间仍然能继续开炮、出牌、交回合 ——
    对方正在决定要不要打速阶3，这边已经把攻击打完了；
    窗口结束时 _priority_continue 再把阶段转换补上。
    于是"拦下来问一句"形同虚设，双方看到的效果顺序仍然没有定义。

    连带修掉的另一个洞：`_should_ask_priority` 看到已有 pending 会返回 False，
    于是发起方**再点一次**「进入战斗阶段」会直接跳过询问、当场推进
    （双击即可绕过询问）。
    """
    pending = _priority_pending_for(room, player_id)
    if not pending:
        return None
    action = PRIORITY_ACTION_TEXT.get(pending.get('action'), '阶段转换')
    return f'正在等待对方响应「{action}」，请稍候再操作'


def _should_ask_priority(room, actor_id, responder_id):
    """判断这次阶段转换是否需要先询问对方。返回 True/False。
    阻断条件（都不询问，直接放行）：
      · 无 socket 请求上下文（单元测试直调 handler）
      · 人机房 —— AI 不会主动响应，弹窗只会让人干等
      · 对方已掉线（在宽限期内）
      · 对局已结束
      · 对方已开启「拒绝」开关
      · 已有连锁窗口挂起 —— 连锁窗口优先，避免双重弹窗
      · 已有未处理的询问 —— 不叠加
    """
    if not _has_request_context():
        return False
    if getattr(room, 'is_ai_room', False):
        return False
    if not responder_id or responder_id not in room.players:
        return False
    if room.state == 'game_over':
        return False
    if responder_id in getattr(room, 'disconnected', {}):
        return False
    if (getattr(room, 'decline_priority', None) or {}).get(responder_id):
        return False
    if room.chain or room.chain_waiting:
        return False
    if getattr(room, 'priority_pending', None):
        return False
    return True


def _ask_priority(room, actor_id, action, on_decline=None):
    """向对手发起「是否响应」询问。

    返回 True 表示【已发出询问】——此时调用方必须立刻返回，
    真正的操作要等对方的响应（或超时）到了再执行，由 _resolve_priority 负责。
    返回 False 表示【无需询问】（人机房 / 对方已拒绝 / 有连锁挂起…），
    调用方可以继续执行原操作。

    action：给前端显示的文案键，如 'enter_battle' / 'enter_end'。
    on_decline：不需要 —— 真正要做的事由调用方在"无需询问"分支里自己执行；
                等待响应时，_resolve_priority 会重新走一遍调用方的入口函数
                （见 _priority_continue）。
    """
    responder_id = _opponent_of(room, actor_id)
    if not _should_ask_priority(room, actor_id, responder_id):
        return False

    room.priority_token += 1
    token = room.priority_token
    room.priority_pending = {
        'actor': actor_id,
        'responder': responder_id,
        'action': action,
        # 告知对方"他手上有没有速阶3卡"——没有也照样问（作者裁定：
        # 玩家要有选择权），但前端可以据此把提示写得更清楚。
        'speed3_cards': _speed3_cards(room, responder_id),
        'countdown': PRIORITY_SECONDS,
    }
    emit('priority_request', {
        'action': action,
        'actor': actor_id,
        'speed3_cards': _speed3_cards(room, responder_id),
        'countdown': PRIORITY_SECONDS,
    }, to=room.players[responder_id].sid)
    # 同时告诉【发起方】"你被拦下了，正在等对方"。
    # 以前只发 priority_request 给响应者，发起方那边毫无提示：
    # 点了「进入战斗阶段」之后界面一动不动，既不知道在等谁、也不知道等多久，
    # 甚至可以在等待期间继续操作（见 _priority_wait_reason 的说明）。
    emit('priority_waiting', {
        'action': action,
        'action_text': PRIORITY_ACTION_TEXT.get(action, '阶段转换'),
        'countdown': PRIORITY_SECONDS,
    }, to=room.players[actor_id].sid)
    _schedule_priority_timeout(room.id, token)
    return True


def _schedule_priority_timeout(room_id: str, token: int):
    """询问超时兜底：视为对方放弃，继续执行原操作。
    代际令牌使旧定时器自动作废，防止与玩家正常响应竞态双重执行。"""
    def _timeout():
        time.sleep(PRIORITY_SECONDS)
        room = room_manager.get_room(room_id)
        if room and room.priority_pending and room.priority_token == token:
            _resolve_priority(room, respond=False)
    socketio.start_background_task(_timeout)


def _clear_priority(room):
    """清掉待处理的询问状态（不触发后续动作）。

    顺带通知【发起方】"等待结束、可以继续操作了" ——
    前端要靠它把冻结的按钮恢复回来。漏发的话发起方会一直停在
    "等待对方响应"的界面里点不动（比卡死更难查：服务端其实已经继续了）。
    """
    pending = getattr(room, 'priority_pending', None)
    actor_id = pending.get('actor') if pending else None
    room.priority_pending = None
    room.priority_token += 1
    if actor_id and actor_id in room.players:
        sid = getattr(room.players[actor_id], 'sid', None)
        if sid:
            emit('priority_waiting_end', {
                'action': pending.get('action'),
            }, to=sid)


def _resolve_priority(room, respond=False, card=None, targets=None):
    """询问有结果了：对方放弃（或超时），或他打出了一张速阶3。

    respond=False → 继续执行被拦下的那个操作（重新走一遍入口）
    respond=True  → 先把他的牌入链；连锁结算完再继续原操作
    """
    pending = getattr(room, 'priority_pending', None)
    if not pending:
        return
    actor_id = pending['actor']
    responder_id = pending['responder']
    action = pending['action']
    # 先清状态（代际令牌 +1 使超时定时器作废）
    _clear_priority(room)

    if respond and card is not None:
        resp = _play_speed3_as_priority(room, responder_id, card, targets or [])
        if resp is not None and resp.get('status') == 'error':
            # 出牌失败（没这张牌 / 不是速阶3 / 被封锁…）：
            # 退回"放弃"处理，并把原因回给本人，避免对局卡住
            emit('message', {'text': resp.get('message', '响应失败，已视为取消')},
                 to=room.players[responder_id].sid)
            _priority_continue(room, actor_id, action)
            return
        # 出牌成功 → 已入链；连锁结算完后由这里继续原操作
        if room.chain or room.chain_waiting:
            # 结算完成后再继续：把续做动作挂上，交给 resolve_chain 之后触发
            room.priority_continue = {'actor': actor_id, 'action': action}
            return
        # 没有连锁要结算（理论上不会走到，入链必然有窗口）——直接续做
        _priority_continue(room, actor_id, action)
        return

    _priority_continue(room, actor_id, action)


def _priority_continue(room, actor_id, action):
    """询问结束后，继续执行被拦下的那个操作。

    ⚠️ 必须【脱离当前请求上下文】再执行（2026-09-13 实测踩坑）：
    本函数是在 *响应者* 的 socket 请求里被调用的（priority_response /
    超时后台任务），而它要代 *发起者* 重放 enter_battle_phase /
    handle_enter_end_phase。那两个 handler 开头都有 _identity_ok，
    会拿 request.sid（= 响应者的连接）去比对发起者座位的 sid —— 必然不匹配，
    于是重放静默失败（返回 error），阶段永远停在 preparation，
    玩家点完「取消」后整个回合就死了。

    实测证据：priority_pending 被清空、阶段仍是 preparation，
    发起者收不到任何事件。

    做法与 disconnect 处理器同一惯例：把重放丢进后台任务，
    那时已无请求上下文，_identity_ok 走"仅成员校验"分支（与单测一致）。
    """
    def _run():
        time.sleep(0)
        if room.state == 'game_over':
            return
        if action == 'enter_battle':
            enter_battle_phase({'room_id': room.id, 'player_id': actor_id},
                               _priority_confirmed=True)
        elif action == 'enter_end':
            handle_enter_end_phase({'room_id': room.id, 'player_id': actor_id},
                                   _priority_confirmed=True)

    try:
        socketio.start_background_task(_run)
    except Exception:
        # 没有 eventlet/socketio 上下文（如单测直调）时同步执行即可
        _run()


def _play_speed3_as_priority(room, player_id, card_data, targets):
    """优先权询问里打出的速阶3：走与出牌相同的校验与入链。

    复用 handle_use_magic_card，但入口处会因 chain_waiting 拦截 ——
    这里是询问场景，没有连锁窗口，所以直接调用即可。
    """
    return handle_use_magic_card({
        'room_id': room.id,
        'player_id': player_id,
        'card': card_data,
        'targets': targets,
    })


@socketio.on('priority_response')
@_require_live_room
def priority_response(data):
    """客户端对「是否响应阶段转换」的回答。

    data: {
      room_id, player_id,
      respond: bool,        # False = 取消（继续原操作）
      card: {...} | None,   # respond=True 时打出的速阶3
      targets: [...] ,
      decline_all: bool,    # 是否同时勾上「拒绝所有阶段转换时点」开关
    }
    """
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 拒绝开关（可随时切回）：勾上后本局不再向他弹这类询问
    if 'decline_all' in data:
        room.decline_priority[player_id] = bool(data.get('decline_all'))

    pending = getattr(room, 'priority_pending', None)
    if not pending:
        return {'status': 'error', 'message': '没有待处理的响应询问'}
    if pending['responder'] != player_id:
        return {'status': 'error', 'message': '当前不是你的响应窗口'}

    respond = bool(data.get('respond'))
    if respond and not data.get('card'):
        return {'status': 'error', 'message': '请选择要打出的速阶3卡牌'}

    _resolve_priority(room, respond=respond,
                      card=data.get('card'), targets=data.get('targets') or [])
    return {'status': 'success'}


@socketio.on('set_decline_priority')
@_require_live_room
def set_decline_priority(data):
    """单独切换「拒绝所有阶段转换时点」开关（不依赖某次询问）。"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    decline = bool(data.get('decline'))
    room.decline_priority[player_id] = decline
    emit('priority_setting_updated', {'decline': decline}, to=room.players[player_id].sid)
    return {'status': 'success', 'decline': decline}


# ============ 掉线宽限 / 重连 / 超时判负（2026-09-07 新增） ============
DISCONNECT_GRACE_SECONDS = 30


def _start_disconnect_grace(room_id: str, player_id: str):
    """玩家掉线：启动 30s 重连窗口并通知对手。由后台任务调用（避免在
    disconnect 处理器内同步 emit 导致 eventlet hub 卡死）。"""
    time.sleep(0.2)  # 让 disconnect 收尾完成
    room = room_manager.get_room(room_id)
    if not room or room.state == 'game_over' or player_id in room.disconnected:
        return
    room.disconnect_seq += 1
    deadline = time.time() + DISCONNECT_GRACE_SECONDS
    room.disconnected[player_id] = {'deadline': deadline, 'token': room.disconnect_seq}
    for pid, p in list(room.players.items()):
        if pid != player_id:
            emit('opponent_disconnected', {
                'player_id': player_id,
                'seconds': DISCONNECT_GRACE_SECONDS,
                'deadline': deadline,
            }, to=p.sid)
    socketio.start_background_task(_disconnect_timeout, room_id, player_id, room.disconnect_seq)


def _disconnect_timeout(room_id: str, player_id: str, token: int):
    """掉线宽限到期结算：未重连则按房间阶段决定取消对局或判对手胜利。"""
    time.sleep(DISCONNECT_GRACE_SECONDS)
    room = room_manager.get_room(room_id)
    if not room:
        return
    entry = room.disconnected.get(player_id)
    if not entry or entry.get('token') != token:
        return  # 已重连或已由其它路径处理
    room.disconnected.pop(player_id, None)

    other = next((p for p in room.players if p != player_id), None)
    ai_room = getattr(room, 'is_ai_room', False)
    pre_battle = room.state in ('placing_ships', 'rock_paper_scissors')

    if ai_room or pre_battle or other is None or other in room.disconnected or room.state == 'game_over':
        # 人机房 / 未开战 / 双方都不在场：取消对局，不计战绩
        emit('game_canceled', {
            'reason': 'opponent_disconnected',
            'message': '对局已取消（对手掉线）',
        }, room=room_id)
        # 房里可能还有人连着（掉线的是**对手**）→ 同样走收口，别留下「对局中」
        _drop_room(room_id, '对手掉线/未开局，取消对局')
        return

    # 正式对局：在场方判胜，正常计入战绩（无特殊标签）
    room.state = 'game_over'
    room.winner = other
    room.game_over_reason = 'opponent_disconnected'
    # 记录战绩 + 每局统计 + 徽章（统一收口，见 _finalize_match）
    _finalize_match(room, other, player_id)
    emit('game_over', {'winner': other, 'reason': 'opponent_disconnected'}, room=room_id)
    # 房间保留约 2 分钟：让掉线者重连时收到一次性警告
    socketio.start_background_task(_cleanup_ended_room, room_id, 120)


def _cleanup_ended_room(room_id: str, delay: float):
    time.sleep(delay)
    room_manager.delete_room(room_id)


# 已结束房间的回收：所有自然胜负/投降路径都会把 state 置为 game_over，
# 但并非每条路径都显式调度清理，因此用一个后台任务统一兜底，
# 避免 rooms 字典只增不减导致内存泄漏。
_ROOM_GRACE_SECONDS = 120
# 建房后一直没人入座（含人机房只坐了 AI）的房间：此前只回收 game_over 房，
# 这类房间会永久驻留 —— 每误点一次「创建房间/人机对战」就泄漏一个 GameRoom
# （含整副牌堆实例）。超过 TTL 直接回收。
_WAITING_ROOM_TTL = 3600
_reaper_started = False


def _reap_ended_rooms(now: float = None):
    """扫描并回收已结束且超过宽限期的房间（供后台任务与单测调用）。"""
    now = time.time() if now is None else now
    reaped = []
    for room_id, room in list(room_manager.get_all_rooms().items()):
        state = getattr(room, 'state', None)
        if state == 'waiting':
            created = getattr(room, 'created_at', None)
            if created is not None and now - created > _WAITING_ROOM_TTL:
                _drop_room(room_id, '等待房超过 TTL')
                reaped.append(room_id)
            continue
        if state != 'game_over':
            room._game_over_since = None
            continue
        ended = getattr(room, '_game_over_since', None)
        if ended is None:
            # 首次观察到该房间已结束，开始计时
            room._game_over_since = now
            continue
        if now - ended > _ROOM_GRACE_SECONDS:
            _drop_room(room_id, '已结束房宽限期到')
            reaped.append(room_id)
    return reaped


def _auto_act_on_timeouts(now: float = None):
    """对思考超时的真人玩家执行一次保底动作；返回被处理的房间 id 列表。

    做成"扫描式看门狗"而不是每人一个定时器：对局中的状态变化（换人、进阶段、
    开连锁、等待点选）太多，逐个排定时器容易漏排或重复触发。
    """
    if TURN_TIMEOUT_SECONDS <= 0:
        return []
    now = time.time() if now is None else now
    acted = []
    for room in list(room_manager.get_all_rooms().values()):
        if getattr(room, 'state', None) != 'attacking':
            continue
        if getattr(room, 'is_ai_room', False):
            continue                      # AI 自己会走完回合
        pid = room.current_attacker
        if not pid or pid not in room.players:
            continue
        # 换人/刚开局 → 重新计时
        if getattr(room, '_timer_attacker', None) != pid:
            room._timer_attacker = pid
            room.turn_started_at = now
            continue
        if now - getattr(room, 'turn_started_at', now) < TURN_TIMEOUT_SECONDS:
            continue
        # 这些状态下不该催：连锁有它自己的 10 秒窗口；等待点选是玩家正在操作
        if room.chain or room.chain_waiting:
            continue
        if getattr(room, 'disconnected', None):
            continue                      # 有人掉线宽限中
        temp = room.magic_temp_data or {}
        # ⚠️ 待选战舰现在在**房间级队列**里（不在 magic_temp_data），两边都要看
        if (temp.get('pending_placement') or temp.get('pending_shenji')
                or _my_ship_picks(room, pid)):
            continue

        try:
            if room.current_phase == 'preparation':
                enter_battle_phase({'room_id': room.id, 'player_id': pid})
                note = '思考超时：已自动进入战斗阶段'
            elif room.current_phase == 'battle':
                attacked = {(a.x, a.y) for a in room.players[pid].attacks}
                candidates = [(x, y) for x in range(6) for y in range(6)
                              if (x, y) not in attacked]
                if not candidates or room.attacks_remaining <= 0:
                    handle_enter_end_phase({'room_id': room.id, 'player_id': pid})
                    note = '思考超时：已自动进入结束阶段'
                else:
                    x, y = random.choice(candidates)
                    handle_attack({'room_id': room.id, 'player_id': pid, 'x': x, 'y': y})
                    note = f'思考超时：已自动开火 ({x},{y})'
            elif room.current_phase == 'end':
                end_turn({'room_id': room.id, 'player_id': pid})
                note = '思考超时：已自动交出回合'
            else:
                continue
        except Exception as e:
            print(f'Turn timeout auto-action error: {e}')
            room.turn_started_at = now
            continue

        emit('message', {'text': note}, to=room.players[pid].sid)
        emit('game_message', {'message': note, 'type': 'warning'}, room=room.id)
        room.turn_started_at = now
        acted.append(room.id)
    return acted


_TURN_TIMER_STARTED = False


def _turn_timer_loop():
    """后台看门狗：每 5 秒检查一次是否有人思考超时。"""
    while True:
        time.sleep(5)
        try:
            _auto_act_on_timeouts()
        except Exception:
            # 单个房间异常不应中断整个看门狗
            pass


def _ensure_turn_timer():
    global _TURN_TIMER_STARTED
    if _TURN_TIMER_STARTED or TURN_TIMEOUT_SECONDS <= 0:
        return
    _TURN_TIMER_STARTED = True
    socketio.start_background_task(_turn_timer_loop)


def _room_reaper():
    """后台清理任务：定期回收已结束且超过宽限期的房间。"""
    while True:
        time.sleep(30)
        try:
            _reap_ended_rooms()
        except Exception:
            # 单个房间异常不应中断回收任务
            pass


def _ensure_reaper():
    """惰性启动回收任务（只启动一次），避免在 import 期产生后台任务。"""
    global _reaper_started
    if _reaper_started:
        return
    _reaper_started = True
    socketio.start_background_task(_room_reaper)


def _shenji_wait_reason(room, player_id: str):
    """神机妙算宣言窗口开着时，只冻结【非施法者】；否则返回 None。

    为什么必须有：宣言窗口原先只是个标志，没有任何门禁引用它 —— 对方在
    "对方正在宣言"的这段时间里可以照常开炮、出牌、交回合。实测它还会进一步
    造成结算误判（见 _snapshot_shenji_baseline 的说明）。

    施法者自己不能冻：他此刻要做的正是宣言（confirm_shenji_declare）。
    """
    pending = (room.magic_temp_data or {}).get('pending_shenji') or {}
    caster = pending.get('caster')
    if not caster or caster == player_id:
        return None
    return '对方正在宣言神机妙算，请等待宣言完成'


def _action_wait_reason(room, player_id: str):
    """写操作统一门禁：神机妙算宣言窗口 > 命运骰子弃牌待办 > 阶段转换优先权。"""
    return (_shenji_wait_reason(room, player_id)
            or _dice_discard_wait_reason(room, player_id)
            or _priority_wait_reason(room, player_id))


def _dice_discard_wait_reason(room, player_id: str):
    """命运骰子摇到3：该玩家还有未完成的弃牌待办时，冻结其余写操作。

    为什么必须有：弃牌待办挂在房间级字段上，玩家在此期间打出别的牌 / 开炮
    会让连锁或攻击结算与待办交错，手牌变化也会让"弃第几张"的下标失效。
    与神机妙算宣言窗口同口径：把待办"卡住"直到玩家完成选择。
    """
    pending = getattr(room, 'pending_dice_discard', None)
    if isinstance(pending, dict) and pending.get(player_id) is False:
        return '命运骰子生效中，请先选择一张手牌弃置'
    return None


def _snapshot_shenji_baseline(room, caster_id: str):
    """在**牌生效那一刻**（也就是玩家打出这张卡的瞬间）拍下船数基线。

    ⚠️ 基线必须固定在出牌那一刻，不能等到"宣言确认"才拍。
    旧实现把快照写在 confirm 里，于是"出牌 → 对方开炮 → 才宣言"这条时序下，
    confirm 之前被打沉的船被并进基线，diff 少算 → `diff == pred` 误判预言成功
    （作者实测：宣言 1 艘、实际被打沉 2 艘，却提示预言成功）。

    同时记下当时每艘已沉船的 id：只记数量不够，sunken_ships 的排列顺序并不
    保证等于沉没先后（复活用 pop() 从末尾取、旧船也可能被重新沉回去）。
    """
    player = room.players.get(caster_id)
    if player is None:
        return
    sunken = list(getattr(player, 'sunken_ships', []) or [])
    room.game_effects[f'prediction_initial_{caster_id}'] = {
        'ships': player.remaining_ships,
        'sunken': len(sunken),
        'sunken_ids': [id(s) for s in sunken],
    }


SHENJI_DECLARE_SECONDS = 30


def _shenji_declare_timeout_fired(room_id: str, token):
    """超时回调的实体（独立出来便于单测直接调用，不必真的 sleep）。

    超时语义 = 与玩家自己点「取消」一致：清掉宣言窗口、本次效果作废。
    基线也要一起清掉，否则会留下一个没人消费的快照。
    """
    room = room_manager.get_room(room_id)
    if not room:
        return
    pending = (room.magic_temp_data or {}).get('pending_shenji') or {}
    if pending.get('token') != token:
        return                      # 代际令牌：已宣言 / 已取消，旧定时器作废
    caster = pending.get('caster')
    room.magic_temp_data.pop('pending_shenji', None)
    if caster:
        room.game_effects.pop(f'prediction_initial_{caster}', None)
    emit('shenji_waiting_end', {'reason': 'declaration_timeout'}, room=room.id)
    emit('message', {'text': '神机妙算宣言超时，本次效果作废'}, room=room.id)


def _schedule_shenji_declare_timeout(room_id: str, token):
    """宣言超时兜底：冻结对方之后，不能让一个人挂机把两边一起卡死。"""
    def _timeout():
        time.sleep(SHENJI_DECLARE_SECONDS)
        _shenji_declare_timeout_fired(room_id, token)
    socketio.start_background_task(_timeout)


def _open_shenji_declare_window(room, caster_id, result):
    """打开神机妙算宣言窗口：拍基线、通知对方等待、挂超时。"""
    token = int(time.time() * 1000)
    room.magic_temp_data['pending_shenji'] = {'caster': caster_id, 'token': token}
    _snapshot_shenji_baseline(room, caster_id)
    result.temp_data_id = 'shenji_declare'
    result.message = '请宣言预测减少的船数（0-6）'
    opponent_id = _opponent_of(room, caster_id)
    if opponent_id:
        emit('shenji_waiting', {
            'caster': caster_id,
            'text': '等待对方神机妙算宣言中',
        }, to=room.players[opponent_id].sid)
    _schedule_shenji_declare_timeout(room.id, token)


def _frozen_reason(room, player_id: str):
    """对方处于掉线宽限期时返回拒绝文案；否则返回 None（可继续行动）。"""
    for pid in room.disconnected:
        if pid != player_id:
            return '对手已掉线，等待重连中'
    return None


def _issue_reconnect_token(room, player_id: str) -> str:
    tok = secrets.token_hex(16)
    room.reconnect_tokens[player_id] = tok
    return tok


def _build_room_sync(room, player_id: str) -> dict:
    """重连后下发整局快照，供前端重建界面。"""
    p = room.players[player_id]
    opp = next((room.players[o] for o in room.players if o != player_id), None)
    return {
        'room_id': room.id,
        'state': room.state,
        'current_phase': getattr(room, 'current_phase', None),
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining,
        'round': room.round,
        'attack_order': room.attack_order,
        'player_id': player_id,
        'player_name': p.name,
        'opponent_name': opp.name if opp else None,
        'is_ai_room': getattr(room, 'is_ai_room', False),
        # 重连快照也要带排位标记：否则重连后前端以为在打休闲局，结算表现就会错。
        'ranked': bool(getattr(room, 'ranked', False)),
        'mode': _room_match_mode(room),
        'winner': room.winner,
        'game_over_reason': getattr(room, 'game_over_reason', None),
        'field_magic': (room.field_magic.name if hasattr(room.field_magic, 'name') else room.field_magic) or "",
        'remaining_ships': p.remaining_ships,
        'ships': [{'positions': [{'x': pos.x, 'y': pos.y} for pos in sh.positions],
                   'frozen': bool(getattr(sh, 'frozen', None)),
                   # 存活状态：重连后前端也要能把沉船从「可选的自己的船」里排除掉
                   'alive': _is_ship_alive(p, sh)} for sh in p.ships],
        'hand': [{'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description} for c in p.magic_hand],
        'attacks': [{'x': a.x, 'y': a.y, 'hit': a.hit} for a in getattr(p, 'attacks', [])],
        # 对手打在我方棋盘上的格：前端自己棋盘的伤损/沉船只认这份数据，
        # 此前快照不带它，重连后自己棋盘上被打过的格子会全部「复原」。
        'opponent_attacks': [
            {'x': a.x, 'y': a.y, 'hit': a.hit}
            for a in (getattr(opp, 'attacks', []) if opp else [])
        ],
        'opponent_remaining_ships': opp.remaining_ships if opp else 0,
        'shenwei_holes': list(room.game_effects.get('shenwei_holes') or []),
        # 连锁窗口：重连后能看到当前连锁栈与响应窗口，避免缺上下文无法操作
        'chain': [
            {
                'card': ({
                    'name': it.card.name, 'speed': it.card.speed,
                    'type': it.card.type, 'description': it.card.description,
                } if getattr(it, 'card', None) else None),
                'caster': getattr(it, 'player_id', None),
                'negated': getattr(it, 'negated', False),
            }
            for it in getattr(room, 'chain', [])
        ],
        'chain_waiting': getattr(room, 'chain_waiting', False),
        'chain_window': getattr(room, 'chain_window', None),
        # 阶段转换询问：重连正好落在等待窗口里时，发起方要能把
        # 「正在等待对方响应」的提示和冻结状态恢复回来（只给自己的那份）。
        'priority_waiting': (
            {
                'action': room.priority_pending.get('action'),
                'action_text': PRIORITY_ACTION_TEXT.get(room.priority_pending.get('action'), '阶段转换'),
            }
            if _priority_pending_for(room, player_id) else None
        ),
        # 神机妙算宣言窗口：重连落在窗口里时，**对方**要能恢复
        # 「等待对方神机妙算宣言中」横幅与被冻结的状态（只给非施法者那份）。
        'shenji_waiting': (
            {'text': '等待对方神机妙算宣言中'}
            if _shenji_wait_reason(room, player_id) else None
        ),
        # 生效中的效果标记名（只给玩家身上的 effect_flags，不含房间级 game_effects）。
        #
        # ⚠️ 这里以前发的是 `room.game_effects.keys()`，字段名却叫 active_effects ——
        # 前端把它当"我身上有哪些效果"读，而这份名单里的 last_stand_cells /
        # last_stand_owner 都**恰好以 last_stand 开头**，于是任何一个"绝处逢生
        # 候选格还在场"的时刻，前端都判定"锁卡生效中"（房间级效果 ≠ 玩家效果，
        # 两者语义完全不同）。现在只发真正的效果标记名。
        'active_effects': sorted(
            k for k, v in vars(p.effect_flags).items()
            if v and k in _PUBLIC_EFFECT_FLAGS
        ),
        # ⚠️ 绝处逢生的两个标记**显式下发**，前端不许靠卡名猜。
        # 它们的显示名都含"绝处逢生"，靠名字前缀匹配会把"击杀即胜"当成"锁卡"，
        # 于是锁卡过期后前端仍按"魔法卡被锁"给玩家弹拒绝提示（而服务端其实放行）。
        'last_stand_lock': bool(getattr(p.effect_flags, 'last_stand', False)),
        'last_stand_win': bool(getattr(p.effect_flags, 'last_stand_win', False)),
        # 双方「生效中效果」角标：重连后不能丢，否则玩家会以为效果没了。
        # 此前快照里完全没带这份数据，只能等下一次 _emit_active_effects 才恢复。
        'effect_badges': {
            'self': _effect_badges(p),
            'opponent': _effect_badges(opp) if opp else [],
        },
        # 复活/增援放置中途：仅下发给正在放置的玩家
        'pending_placement': (
            room.magic_temp_data.get('pending_placement')
            if isinstance(room.magic_temp_data, dict)
            and (room.magic_temp_data.get('pending_placement') or {}).get('caster') == player_id
            else None
        ),
        'pending_placement_blocked': (
            _placement_blocked_cells(room, player_id)
            if isinstance(room.magic_temp_data, dict)
            and (room.magic_temp_data.get('pending_placement') or {}).get('caster') == player_id
            else []
        ),
        # 放置流程的"必须放这些格"名单：
        #   · 绝处逢生      → last_stand_cells（只能放原本有战舰的位置）
        #   · 神机妙算重新部署 → shenji_redeploy_cells（原位置即便被对方打过也可选）
        # 重连时必须一起下发，否则面板恢复后这些格子会被画成不可点。
        'pending_placement_allowed': (
            (room.game_effects.get('shenji_redeploy_cells')
             or room.game_effects.get('last_stand_cells') or [])
            if isinstance(room.magic_temp_data, dict)
            and (room.magic_temp_data.get('pending_placement') or {}).get('caster') == player_id
            else []
        ),
        # 绝处逢生的候选格：公开信息（对方要据此知道唯一一艘新船可能在哪），
        # 重连后必须补回来，否则高亮没了、玩家又以为"这几格不能打"。
        'last_stand_cells': [
            {'x': cx, 'y': cy}
            for (cx, cy) in (room.game_effects.get('last_stand_cells') or [])
        ],
        # 这批候选格属于谁的棋盘（前端据此决定高亮画在哪块棋盘上）
        'last_stand_owner': room.game_effects.get('last_stand_owner'),
        # 冻结的 3×3 区域（区域属于受害者棋盘，owner 即受害者）：
        # 重连后必须补回来，否则玩家又会忘记冻的是哪片
        'frozen_area': dict(room.game_effects.get('frozen_area') or {}) or None,
        # 玩家级状态标记：重连后 UI 需要知道"被看破 / 无中生有 / 余音绕梁"等
        'magic_blocked': bool(getattr(p, 'magic_blocked', False)),
        'effect_flags': {k: v for k, v in vars(p.effect_flags).items() if v},
        # 待自己点选的战舰（恶魔契约 / 神之宣告 / 克苏鲁之眼）
        # ⚠️ 2026-09-20 改为读**优先队列**（旧实现读单槽 `magic_temp_data`）：
        #    重连后要恢复的是"轮到我的那一项"（优先级最高的），不是随便哪一项。
        #    静默登记项（仁王之盾）不下发 —— 它自己那套选区 UI 由 temp_data 恢复。
        'pending_sacrifice': _my_pending_sacrifice_payload(room, player_id),
        'pending_sacrifice_ships': _my_pending_sacrifice_ships(room, player_id, p),
        # 猜拳阶段：重连后需要知道该出拳
        'rps_choices': dict(room.rps_choices) if room.state == 'rock_paper_scissors' else {},
    }


@socketio.on('get_reconnect_token')
def handle_get_reconnect_token(data):
    room = room_manager.get_room(data.get('room_id'))
    pid = data.get('player_id')
    if not room or pid not in room.players or not _identity_ok(room, pid):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    return {'status': 'success', 'token': _issue_reconnect_token(room, pid)}


@socketio.on('rejoin_room')
def handle_rejoin_room(data):
    """掉线重连：校验 token/会话身份后重绑 sid，取消宽限并下发整局快照。"""
    room_id = data.get('room_id')
    pid = data.get('player_id')
    token = data.get('token')
    room = room_manager.get_room(room_id)
    if not room or pid not in room.players:
        return {'status': 'error', 'message': '房间不存在'}
    # 令牌必须真实发放且非空：None == None 曾导致无凭据重绑座位（座位劫持）
    stored_token = room.reconnect_tokens.get(pid)
    ok = bool(stored_token) and bool(token) and secrets.compare_digest(str(stored_token), str(token))
    if not ok:
        try:
            ok = bool(session.get('user_id') == pid)
        except Exception:
            ok = False
    if not ok:
        return {'status': 'error', 'message': '身份校验失败'}

    if room.state == 'game_over':
        # 掉线超时结束：给败方一次警告，房间稍后清理
        if room.game_over_reason == 'opponent_disconnected' and room.winner != pid:
            emit('reconnect_warning', {'message': '对局已因你掉线超时结束，请勿中途掉线'}, to=request.sid)
            socketio.start_background_task(_cleanup_ended_room, room_id, 3)
        else:
            emit('error', {'message': '对局已结束'}, to=request.sid)
        return {'status': 'success'}

    room.players[pid].sid = request.sid
    join_room(room_id, request.sid)
    # 好友功能：重连回一局没结束的对局 → 重新挂上"对局中"（disconnect 时摘过）。
    _bind_presence_game(room)
    was_reconnect = pid in room.disconnected
    if was_reconnect:
        room.disconnected.pop(pid, None)
    for opid, op in room.players.items():
        if opid != pid:
            emit('opponent_reconnected', {'player_id': pid}, to=op.sid)
    if was_reconnect:
        emit('room_sync', _build_room_sync(room, pid), to=request.sid)
    return {'status': 'success', 'reconnected': was_reconnect}


def _apply_shenji_prediction(room, caster_id, x, result=None):
    """神机妙算宣言落效：**只写数值 x** —— 基线早在出牌那一刻就拍好了。

    ⚠️ 绝不能在已有基线时重拍：重拍会把"宣言确认之前打掉的船"并进基线，
    造成 diff 少算、误判预言成功（作者实测的 ② 号问题）。
    """
    player = room.players[caster_id]
    player.effect_flags = player.effect_flags
    player.effect_flags.prediction = x
    if f'prediction_initial_{caster_id}' not in room.game_effects:
        # 基线缺失的老路径（magic_temp_data['prediction'] 直接落效 / 旧对局）：
        # 补拍一次总比没有强，但这是兜底，不是正常时序。
        _snapshot_shenji_baseline(room, caster_id)
    room.magic_temp_data.pop('prediction', None)
    room.magic_temp_data.pop('pending_shenji', None)
    if result is not None:
        result.message = f'宣言船数减少{x}，若预测成功则不会减少'


@socketio.on('confirm_shenji_declare')
@_require_live_room
def handle_confirm_shenji_declare(data):
    """神机妙算宣言确认：写入预测值并生效。"""
    room_id = data.get('room_id')
    pid = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or pid not in room.players or not _identity_ok(room, pid):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    pending = room.magic_temp_data.get('pending_shenji')
    if not pending or pending.get('caster') != pid:
        return {'status': 'error', 'message': '没有待宣言的神机妙算'}
    try:
        x = max(0, min(6, int(data.get('prediction', 0))))
    except Exception:
        return {'status': 'error', 'message': '宣言数值无效'}
    _apply_shenji_prediction(room, pid, x)
    for opid, op in room.players.items():
        if opid != pid:
            # 宣言完成 → 解除对方的等待横幅与行动冻结
            emit('shenji_waiting_end', {'reason': 'declared'}, to=op.sid)
            emit('message', {'text': f'对方宣言神机妙算：船数减少{x}时生效'}, to=op.sid)
    return {'status': 'success', 'message': f'已宣言：船数减少{x}时不减少'}


def _attacks_forced_zero(room) -> bool:
    """本大回合的攻击次数是否被规则强制为 0。

    两个来源，**作用域不同，别混**：

    ① `zero_attacks_round`（**房间级**）—— 败者食尘。
       卡面：「败者食尘生效的大回合内**双方**的攻击次数都为 0」。
       全房生效，与谁在行动无关。

    ② `zero_attacks_for`（**玩家级**）—— 回光返照。
       卡面：「跳过**自己的**战斗阶段」—— 只有施法者打不出去，对手照常。
       ⚠️ 这一条是作者实测报出来的：我第一版借用了①的机制，
          结果**对手的攻击次数也被归零**了。两张卡的作用域根本不同。

    这两个都是【大回合级】的硬规则，优先级高于任何"按船数重算 / 按增量加减"。
    写 `attacks_remaining` 的地方（`_recalc_attacker_attacks` /
    `_sync_attacks_after_ship_change` / `_apply_last_stand_attacks` /
    `_grant_extra_attacks`）都必须先过它，否则那个 0 会在进入战斗阶段时
    被按船数还原回来 —— 玩家实测：准备阶段确实是 0，一进战斗阶段又变成 6 次。

    ⚠️ ② 必须在 `room.current_attacker` 是施法者时才拦：他一旦交回合出去，
       这个 0 就不该再管别人（否则又变成房间级了）。
    """
    effects = getattr(room, 'game_effects', None)
    if not isinstance(effects, dict):
        return False
    try:
        rnd = int(room.round)
    except (TypeError, ValueError):
        return False

    # ① 房间级（败者食尘）
    try:
        if int(effects.get('zero_attacks_round') or -1) == rnd:
            return True
    except (TypeError, ValueError):
        pass

    # ② 玩家级（回光返照）：只对**该玩家**、且正好轮到他行动时生效
    try:
        entry = effects.get('zero_attacks_for')
        if isinstance(entry, dict):
            if int(entry.get('round') or -1) == rnd \
                    and entry.get('player') == room.current_attacker:
                return True
    except (TypeError, ValueError):
        pass

    return False


def _grant_extra_attacks(room, player_id, n=1) -> int:
    """给某玩家额外增加 n 次攻击次数，返回【实际】增加的次数。

    教皇旨意生效时本回合攻击次数恒为 0（攻击方式改为弃卡攻击），
    给它加次数没有意义 —— 与 `_sync_attacks_after_ship_change` 同口径返回 0。
    """
    if int(n) <= 0 or room.state != 'attacking':
        return 0
    if room.current_attacker != player_id:
        return 0
    if _attacks_forced_zero(room) or field_magic_name(room) == '教皇旨意':
        return 0
    before = int(room.attacks_remaining or 0)
    room.attacks_remaining = max(0, before + int(n))
    emit('attacks_updated', {
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining
    }, room=room.id)
    return room.attacks_remaining - before


def _recalc_attacker_attacks(room):
    """按当前攻击者在准备阶段结算攻击次数：伊甸园生效时 = 6-自身船数；否则按剩余船数-冻结。"""
    pid = room.current_attacker
    if not pid or pid not in room.players:
        return
    if _attacks_forced_zero(room):
        # 败者食尘生效的大回合：双方恒为 0，不许被船数重算覆盖
        room.attacks_remaining = 0
        return
    # 百亿补贴累计的额外次数（属于持卡者自己，跨回合保留）
    bonus = int(getattr(room.players[pid].effect_flags, 'subsidy_bonus', 0) or 0)
    if field_magic_name(room) == '教皇旨意':
        room.attacks_remaining = 0
    elif field_magic_name(room) == '伊甸园':
        room.attacks_remaining = max(0, 6 - room.players[pid].remaining_ships) + bonus
    else:
        # 用 remaining_ships：ships 列表含已沉没的战舰，不能直接取长度
        room.attacks_remaining = max(
            0, room.players[pid].remaining_ships - frozen_ship_count(room.players[pid])) + bonus


# 添加处理连锁响应
@socketio.on('chain_response')
@_require_live_room
def chain_response(data):
    room_id = data['room_id']
    player_id = data['player_id']
    chain = data.get('chain', False)
    card = data.get('card')
    targets = data.get('targets', [])

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    targets, target_err = _sanitize_magic_targets(targets)
    if target_err:
        return {'status': 'error', 'message': target_err}

    if not room.chain_waiting:
        return {'status': 'error', 'message': '没有待处理的连锁请求'}

    # 只有当前响应窗口的玩家可以响应
    if room.chain_window and room.chain_window != player_id:
        return {'status': 'error', 'message': '当前不是你的连锁响应窗口'}

    # 关闭当前窗口
    room.chain_waiting = False
    room.chain_window = None

    if chain and card:
        try:
            card = MagicCard(**card)
        except (ValueError, TypeError, KeyError) as e:
            return {'status': 'error', 'message': f'魔法卡数据无效: {e}'}
        player = room.players[player_id]
        # 防御：被看破者不能连锁（正常流程不会进入）
        if player.magic_blocked:
            room.chain_passes += 1
            if room.chain_passes >= 2:
                resolve_chain(room)
            else:
                _advance_chain_window(room, _opponent_of(room, player_id))
            return {'status': 'error', 'message': '你的魔法卡已被看破，无法连锁'}

        # 卡牌在手且为速阶3
        # 安全：改用服务端手牌里的真实实例，忽略客户端伪造的 speed/type，
        # 同时避免为同一张卡 new 出第二个实例（会导致抽到重名卡时崩溃）。
        hand_card = next((c for c in player.magic_hand
                          if c.name == card.name and c.speed == card.speed), None)
        if hand_card is None:
            return {'status': 'error', 'message': '你没有这张魔法卡'}
        card = hand_card
        if int(card.speed) != 3:
            return {'status': 'error', 'message': '只能使用速阶3的卡牌进行连锁'}

        # 与主动出牌一致地校验使用限制（禁忌果实 / 绝处逢生）。
        # 原先连锁路径完全跳过 can_play_magic_card，可绕过上述封锁；
        # 校验不通过按"放弃"处理，避免连锁窗口卡死。
        if not can_play_magic_card(room, player_id, card):
            room.chain_passes += 1
            if room.chain_passes >= 2:
                resolve_chain(room)
            else:
                _advance_chain_window(room, _opponent_of(room, player_id))
            return {'status': 'error', 'message': '当前无法使用这张魔法卡'}

        # 从手牌移除并进弃牌堆
        for i, c in enumerate(player.magic_hand):
            if c.name == card.name and c.speed == card.speed:
                player.magic_hand.pop(i)
                break
        room.magic_discard.append(card)

        # ⚠️ 必须推送手牌：前端手牌是照服务端数据渲染的，不推就停在旧状态 ——
        # 玩家会看到"连锁里打出的牌还在手上"（实测反馈）。此前这条路径只发了
        # magic_chain_updated（连锁栈），手牌更新从未下发，所有速阶3响应都受影响。
        emit('hand_updated', {'hand': player.magic_hand}, to=player.sid)

        room.chain.append(ChainItem(player_id, card, targets, time.time()))
        emit('magic_chain_updated', {'chain': room.chain}, room=room_id)

        # 打出新牌：放弃计数清零，窗口交给对方（对方放弃后回到自己，支持自连锁）
        room.chain_passes = 0
        _advance_chain_window(room, _opponent_of(room, player_id))
        return {'status': 'success', 'message': f'魔法卡{card.name}已加入连锁'}
    else:
        # 放弃：连续两次放弃即结算
        room.chain_passes += 1
        if room.chain_passes >= 2:
            resolve_chain(room)
        else:
            _advance_chain_window(room, _opponent_of(room, player_id))
        return {'status': 'success', 'message': '放弃连锁'}


@socketio.on('remove_field_magic')
@_require_live_room
def handle_remove_field_magic(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if room and player_id in room.players:
        # 只能拆自己的场地（原先任意客户端可随时拆掉对手的场地）
        owner = getattr(room, 'field_magic_owner', None)
        if room.field_magic and owner is not None and owner != player_id:
            return {'status': 'error', 'message': '只能移除自己的场地魔法'}
        # 将场地魔法加入弃牌堆并清除场地（旧卡不在手牌，不能用 discard_card）
        if room.field_magic:
            room.magic_discard.append(room.field_magic)
            _clear_field_magic_effects(room)
            room.field_magic = None
            room.field_magic_owner = None
        # 广播场地魔法更新
        emit('field_magic_updated', {
            'player_id': player_id,
            'card': None
        }, room=room_id)

    return {'status': 'success'}


@socketio.on('confirm_reinforcement_position')
@_require_live_room
def handle_confirm_reinforcement(data):
    """确认放置一艘（增援/复活）战舰。"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    position = data.get('position') or {}
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    pending = room.magic_temp_data.get('pending_placement') if room.magic_temp_data else None
    if not pending or pending.get('caster') != player_id:
        return {'status': 'error', 'message': '没有等待放置的战舰'}

    x, y = position.get('x'), position.get('y')
    if x is None or y is None:
        return {'status': 'error', 'message': '请选择放置位置'}
    try:
        x, y = int(x), int(y)
    except (TypeError, ValueError):
        return {'status': 'error', 'message': '请选择放置位置'}

    if pending['kind'] == 'last_stand':
        # 绝处逢生：只能放在"原本有自己战舰"的格子上（这些格子对方多半打过，
        # 因此不走 _placement_error 的"未被对方打过"规则）
        allowed = {(int(a[0]), int(a[1]))
                   for a in (room.game_effects.get('last_stand_cells') or [])}
        if (x, y) not in allowed:
            return {'status': 'error', 'message': '只能放在原本有自己战舰的格子上'}
    elif pending['kind'] == 'shenji_redeploy':
        # 神机妙算重新部署：允许"各自的原位置"（这些格子必然被对方打过）
        # 或"对方没有打过的空格"。用 allow_cells 把原位置豁免掉。
        # ignore_sunken：沉船还留在 ships 里，不跳过的话连原位都算被占用。
        allow = {(int(a[0]), int(a[1]))
                 for a in (room.game_effects.get('shenji_redeploy_cells') or [])}
        err = _placement_error(room, player_id, x, y,
                               allow_cells=allow, ignore_sunken=True)
        if err:
            return {'status': 'error', 'message': err}
    else:
        err = _placement_error(room, player_id, x, y)
        if err:
            return {'status': 'error', 'message': err}

    caster = room.players[player_id]
    if pending['kind'] == 'shenji_redeploy':
        # 从登记好的"本大回合新沉的船"里取一艘（不能用 pop()：沉船堆里还混着
        # 更早回合沉的船，那些不属于"原本会减少的船"）
        targets = room.game_effects.get('shenji_redeploy_ships') or []
        revived = None
        while targets:
            cand = targets.pop(0)
            if cand in caster.sunken_ships:
                revived = cand
                break
        room.game_effects['shenji_redeploy_ships'] = targets
        if revived is None:
            _finish_placement(room, player_id, 'shenji_redeploy')
            return {'status': 'error', 'message': '没有可重新部署的战舰'}
        caster.sunken_ships.remove(revived)
        # 与复活类一致：清空命中并移到新位置，否则复活后打不沉（幽灵船）
        revived.positions = [Position(x=x, y=y)]
        revived.hits = []
        revived.shield = False
        revived.invincible = False
        _thaw_ship(revived)          # 复活不继承上一轮的冻结
        if revived not in caster.ships:
            caster.ships.append(revived)
        caster.remaining_ships += 1
        _clear_attacks_on_cells(room, revived.positions, player_id)
        msg = f'神机妙算：战舰已重新部署到 ({x},{y})'
    elif pending['kind'] == 'revive':
        if not caster.sunken_ships:
            _finish_placement(room, player_id, 'revive')
            return {'status': 'error', 'message': '没有可复活的战舰'}
        revived = caster.sunken_ships.pop()
        # 清掉该船在沉船堆里的所有重复记录：_is_ship_alive 只要看到船还在
        # sunken_ships 里就判定它已沉，留一条就会让"复活"在棋盘上不生效
        while revived in caster.sunken_ships:
            caster.sunken_ships.remove(revived)
        # 关键修复：清空命中并移到新位置，否则复活后打不沉（幽灵船）
        revived.positions = [Position(x=x, y=y)]
        revived.hits = []
        revived.shield = False
        revived.invincible = False
        _thaw_ship(revived)          # 复活不继承上一轮的冻结
        if revived not in caster.ships:
            caster.ships.append(revived)
        caster.remaining_ships += 1
        _clear_attacks_on_cells(room, revived.positions, player_id)
        msg = f'复活战舰已部署到 ({x},{y})'
    elif pending['kind'] == 'last_stand':
        # 绝处逢生的"唯一一艘战舰"：牺牲掉的船留在沉船堆，这里放一艘新的
        new_ship = PlayerShip(positions=[Position(x=x, y=y)], hits=[])
        caster.ships.append(new_ship)
        caster.remaining_ships += 1
        _clear_attacks_on_cells(room, new_ship.positions, player_id)
        msg = f'绝处逢生：唯一一艘战舰已部署到 ({x},{y})'
    else:
        new_ship = PlayerShip(positions=[Position(x=x, y=y)], hits=[])
        caster.ships.append(new_ship)
        caster.remaining_ships += 1
        _clear_attacks_on_cells(room, new_ship.positions, player_id)
        msg = f'增援战舰已部署到 ({x},{y})'

    pending['remaining'] -= 1
    pending['placed'] += 1

    # 八方来财：船数主动增加（死者苏生 / 增援 / 绝处逢生的唯一一艘）要摸牌。
    # 这三条路径共用这段放置流程，挂在这里一处即可覆盖。
    # 全场持卡者都摸 —— 对方用增援复活自己的船，同样算"战舰数目主动变化"。
    _notify_treasure_hunter(room, 1)

    opponent_id = _opponent_of(room, player_id)
    _emit_ships_updated(room)
    # 同步放置后的己方棋盘（只发给本人），让新船立刻显示
    _emit_player_ships(room, player_id)
    emit('message', {'text': msg}, to=room.players[player_id].sid)

    if pending['remaining'] > 0:
        _emit_placement_request(room, player_id)
    else:
        _finish_placement(room, player_id, pending['kind'])
    return {'status': 'success', 'message': msg}


@socketio.on('confirm_sacrifice')
@_require_live_room
def handle_confirm_sacrifice(data):
    """恶魔契约 / 神之宣告 / 克苏鲁之眼：玩家在自己的棋盘上点选一艘战舰。

    ⚠️ 2026-09-20：待选从**单槽**改成**按玩家分组的队列**。
    旧实现读 `magic_temp_data['pending_sacrifice']` 这一个 dict，被第二次请求覆盖后，
    先那个玩家点船就会报「当前没有待牺牲的战舰」（作者实测报的 bug）。
    现在取该玩家**队列里优先级最高**的那一项 —— "这一下属于哪个效果"由优先级决定，
    不再由"谁最后写槽"决定。
    """
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    position = data.get('position') or {}
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    pending = _top_ship_pick(room, player_id)
    if not pending:
        return {'status': 'error', 'message': '当前没有待牺牲的战舰'}
    reason = pending.get('reason') or 'demon_contract'

    try:
        cell = (int(position.get('x')), int(position.get('y')))
    except (TypeError, ValueError):
        return {'status': 'error', 'message': '请选择一艘自己的战舰'}

    ship = _find_ship_at(room.players[player_id], cell, alive_only=True)
    if ship is None:
        return {'status': 'error',
                'message': '必须选择自己【还活着】的战舰所在的格子（已沉没的船不能选）'}

    if reason == 'kraken_eye':
        # 克苏鲁之眼：只把位置暴露给对方，不摧毁这艘船
        _consume_ship_pick(room, player_id, 'kraken_eye')
        other_id = _opponent_of(room, player_id)
        positions = ship.positions
        if other_id and other_id in room.players:
            room.players[other_id].revealed_positions.extend(positions)
            emit('revealed_positions', {'positions': positions}, to=room.players[other_id].sid)
        return {'status': 'success', 'message': '已暴露一艘战舰的位置'}

    if reason == 'trap_setup':
        # 守株待兔：把选中的船打上陷阱标记（不摧毁）
        # 陷阱只在本大回合生效；跨回合清理由 end_turn 内"进入新大回合"分支兜底。
        _consume_ship_pick(room, player_id, 'trap_setup')
        ship.trap = True
        add_game_log(room,
                     f'第{room.round}回合 · {_log_name(room, player_id)} 的【守株待兔】'
                     f'为一艘战舰设置陷阱',
                     'magic', {'caster': player_id, 'card': '守株待兔'})
        emit('trap_set', {
            'player': player_id,
            'positions': [{'x': p.x, 'y': p.y} for p in ship.positions],
        }, room=room.id)
        return {'status': 'success', 'message': '已为一艘战舰设置陷阱（本回合该船被击沉时对方需牺牲两艘）'}

    _do_demon_contract_sacrifice(room, player_id, ship, reason)
    return {'status': 'success', 'message': '已选择一艘战舰'}


@socketio.on('cancel_placement')
@_require_live_room
def handle_cancel_placement(data):
    """放弃剩余放置（防止无空格时卡死）。已放置的保留，未放置的作废。"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    pending = room.magic_temp_data.get('pending_placement') if room.magic_temp_data else None
    if not pending or pending.get('caster') != player_id:
        return {'status': 'error', 'message': '没有等待放置的战舰'}

    if pending['kind'] == 'last_stand':
        # 绝处逢生放弃放置会把玩家变成"0 艘船"无法继续，改为替其随机落一格
        cells = room.game_effects.get('last_stand_cells') or []
        if cells:
            cell = random.choice(cells)
            handle_confirm_reinforcement({'room_id': room_id, 'player_id': player_id,
                                          'position': {'x': cell[0], 'y': cell[1]}})
            return {'status': 'success', 'message': '已随机放置唯一一艘战舰'}

    _finish_placement(room, player_id, pending['kind'])
    emit('message', {'text': '已放弃剩余放置'}, to=room.players[player_id].sid)
    return {'status': 'success'}


@socketio.on('request_revealed_positions')
def handle_request_revealed_positions(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    positions = room.players[player_id].revealed_positions
    # 只发送给请求者
    emit('revealed_positions', {'positions': positions}, to=room.players[player_id].sid)
    return {'status': 'success'}


@socketio.on('get_magic_temp_data')
def get_magic_temp_data(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 只下发「等待你自己处理」的临时数据。此前对任何房内玩家原样 emit，
    # 对手只要手动 emit 一次就能读到桃园结义抽出的候选牌 ——
    # 而那张卡面明确写着「对方不可见被抽出来的所有 n 张牌」。
    temp = room.magic_temp_data or {}
    # ⚠️ 待选战舰自 2026-09-20 起在**房间级优先队列**里，不再写 `magic_temp_data`，
    #    所以这里要改成问队列 —— 否则"正等着点船的那个人"会被误判成非 owner。
    _top_pick = _top_ship_pick(room, player_id)
    owners = {
        temp.get('caster'),
        temp.get('caster_id'),
        (temp.get('pending_placement') or {}).get('caster'),
        (temp.get('pending_shenji') or {}).get('caster'),
        player_id if _top_pick is not None else None,
    }
    if player_id not in owners:
        return {'status': 'error', 'message': '没有等待你处理的魔法卡选择'}
    return {'status': 'success', 'data': temp}


@socketio.on('confirm_magic_target')
@_require_live_room
def confirm_magic_target(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    temp_data_id = data.get('temp_data_id')
    target_data = data.get('target_data', {})

    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    if temp_data_id == 'taoyuan_choice':
        # 处理桃园结义的选择
        caster_choice = target_data['caster_choice']

        # 分配卡牌
        caster = room.players[player_id]
        opponent_id = next(p for p in room.players if p != player_id)
        opponent = room.players[opponent_id]

        if 'cards' not in room.magic_temp_data:
            return {'status': 'error', 'message': '没有可分配的卡牌'}

        cards = room.magic_temp_data['cards']

        # 确保选择有效
        if 0 <= caster_choice < len(cards):
            # 给自己分配卡牌
            caster.magic_hand.append(cards[caster_choice])

            # 给对方分配卡牌（如果有剩余卡牌）
            opponent_choice = -1
            if len(cards) > 1:
                # 优先采用对方自己挑的那张（前端 showTaoyuanChoice 会把
                # opponent_choice 一起回传）。此前这里忽略该字段、固定取
                # 「第一张不是施法者选的」，导致卡面上「对方再选 1 张」
                # 这一步形同虚设。
                requested = -1
                if isinstance(target_data, dict):
                    try:
                        requested = int(target_data.get('opponent_choice', -1))
                    except (TypeError, ValueError):
                        requested = -1
                if 0 <= requested < len(cards) and requested != caster_choice:
                    opponent_choice = requested
                else:
                    for i in range(len(cards)):
                        if i != caster_choice:
                            opponent_choice = i
                            break

                if 0 <= opponent_choice < len(cards):
                    opponent.magic_hand.append(cards[opponent_choice])

            # 剩余卡牌放回牌堆
            remaining_cards = []
            for i, card in enumerate(cards):
                if i != caster_choice and i != opponent_choice:
                    remaining_cards.append(card)

            room.magic_deck += remaining_cards

            # 清除临时数据
            room.magic_temp_data = {}

            # 通知双方手牌更新
            emit('hand_updated', {
                'hand': caster.magic_hand
            }, to=room.players[player_id].sid)

            emit('hand_updated', {
                'hand': opponent.magic_hand
            }, to=room.players[opponent_id].sid)

            # 通知对手等待结束
            emit('taoyuan_complete', {
                'message': '对方桃园结义结算完成'
            }, to=room.players[opponent_id].sid)

            return {'status': 'success', 'message': '桃园结义选择完成'}
        else:
            return {'status': 'error', 'message': '无效的卡牌选择'}
    elif temp_data_id == 'lingqi_choice':
        # 处理灵气复苏的船数选择
        target_ships = target_data['target_ships']

        # 获取施法者和对手
        caster = room.players[player_id]
        opponent_id = next(p for p in room.players if p != player_id)
        opponent = room.players[opponent_id]

        # 验证选择是否有效
        if 'max_ships' not in room.magic_temp_data:
            return {'status': 'error', 'message': '没有可选择的船数范围'}

        max_ships = room.magic_temp_data['max_ships']
        if target_ships < 1 or target_ships > max_ships:
            return {'status': 'error', 'message': f'无效的船数选择，应在1-{max_ships}之间'}

        # 重置双方的战舰数据
        # 双方棋盘都要换掉 → 除外船不再是这批棋盘上的船；**范围效果也要终止**
        _clear_board_effects(room, list(room.players), '灵气复苏')
        # 跨回合计数效果（极限增援 / 无暇圣心…）也要终止：它们会在后续大回合
        # 继续递减，归零时凭空判胜负（见 _clear_multiturn_effects 的说明）
        _clear_multiturn_effects(room, '灵气复苏')
        # 棋盘被整批换掉 → 挂在旧船上的"点选一艘船"待办全部作废
        _clear_ship_picks(room)
        for p_id in room.players:
            player = room.players[p_id]
            player.ships = []
            player.attacks = []
            player.remaining_ships = 0
            player.needs_reset = True
            player.revealed_positions = []
            # 设置新的船数限制
            player.max_ships = target_ships

        # 清除临时数据
        room.magic_temp_data = {}

        # 记录当前对局进度：灵气复苏只重置棋盘与船数，
        # 先后手、阶段、回合数都按原对局继续 —— 不重新猜拳。
        room.lingqi_saved_state = {
            'attack_order': list(room.attack_order),
            'current_attacker': room.current_attacker,
            'current_phase': room.current_phase,
            'round': room.round,
            'attacks_remaining': room.attacks_remaining,
        }

        # 只切到摆放阶段；attack_order / current_attacker / current_phase 保留不动，
        # 待双方重新摆放完成后再回到攻击阶段（见 handle_place_ships）。
        room.state = 'placing_ships'

        # 添加灵气复苏应用标记，用于后续广播
        room.lingqi_resurgence_applied = True

        # 通知双方进入重新摆放阶段，并发送新的船数限制
        # ⚠️ to= 要的是 socket sid，不是 room.players 的 key。
        # 自定义房/人机房里登录用户的 key 是 user_id（≠ sid），传 p_id 会石沉大海 ——
        # 玩家那边界面毫无反应，只能手动刷新才发现要重新摆船。
        for p_id in room.players:
            emit('reset_gameboard', {
                'new_max_ships': target_ships,
                'message': f'灵气复苏生效，双方需要重新摆放{target_ships}艘战舰'
            }, to=room.players[p_id].sid)

        # 通知对手等待结束
        emit('lingqi_complete', {
            'message': '对方灵气复苏结算完成'
        }, to=room.players[opponent_id].sid)

        return {'status': 'success', 'message': '灵气复苏船数选择完成'}

    elif temp_data_id == 'bury_choice':
        # 明智埋葬：把选中的牌（牌堆中或对方手牌中的那张）放进弃牌堆，
        # 施法者再摸一张牌。
        #
        # ⚠️ 原实现把 card_index 当成「施法者自己手牌的下标」：
        #   手牌为空（刚把明智埋葬打出去后的常见情况）时直接报「无效的选择」，
        #   既不埋牌也不摸牌；手牌非空时埋掉的是自己的牌，而选中的那张
        #   从头到尾没进弃牌堆。这里改为与 select_magic_target 共用同一实现。
        temp = room.magic_temp_data or {}
        if temp.get('type') != 'bury_choice' or temp.get('caster') != player_id:
            return {'status': 'error', 'message': '当前没有待处理的明智埋葬选择'}
        return _apply_bury_choice(room, player_id, target_data)

    elif temp_data_id == 'wangyang_choice':
        # 亡羊补牢：把选中的卡牌加入施法者手牌，其余候选按原顺序回归弃牌堆末尾，
        # 再把暂存的「亡羊补牢自己」放回弃牌堆末尾。
        temp = room.magic_temp_data or {}
        if temp.get('type') != 'wangyang_choice' or temp.get('caster') != player_id:
            return {'status': 'error', 'message': '当前没有待处理的亡羊补牢选择'}
        cards = temp.get('cards') or []
        if not isinstance(cards, list) or not cards:
            return {'status': 'error', 'message': '没有可挑选的卡牌'}
        try:
            chosen_index = int(target_data.get('chosen_index', -1))
        except (TypeError, ValueError):
            chosen_index = -1
        if not (0 <= chosen_index < len(cards)):
            return {'status': 'error', 'message': '无效的卡牌选择'}
        chosen = cards[chosen_index]
        # 选中那张进施法者手牌
        room.players[player_id].magic_hand.append(chosen)
        # 其余候选按原顺序回归弃牌堆末尾
        for i, c in enumerate(cards):
            if i != chosen_index:
                room.magic_discard.append(c)
        # 暂存的亡羊补牢自己回归弃牌堆末尾
        own_card = temp.get('own_card')
        if own_card is not None:
            room.magic_discard.append(own_card)
        # 清空临时数据
        room.magic_temp_data = {}
        # 推送手牌变化给施法者；同步状态由 resolve_chain 收尾统一兜底
        emit('hand_updated', {'hand': room.players[player_id].magic_hand},
             to=room.players[player_id].sid)
        # 通知对手
        opponent_id = _opponent_of(room, player_id)
        if opponent_id and opponent_id in room.players:
            emit('wangyang_complete', {
                'message': f'对方亡羊补牢选择了「{chosen.name}」',
                'chosen': chosen.name,
            }, to=room.players[opponent_id].sid)
        add_game_log(room,
                     f'第{room.round}回合 · {_log_name(room, player_id)} 的【亡羊补牢】'
                     f'从弃牌区取回「{chosen.name}」加入手牌',
                     'magic', {'caster': player_id, 'card': '亡羊补牢',
                                'chosen': chosen.name})
        return {'status': 'success', 'message': f'已将「{chosen.name}」加入手牌'}

    elif temp_data_id == 'shield_choice':
        # 仁王之盾：至多 3 艘己方战舰进入护盾状态（同样补上真实链路）
        caster = room.players[player_id]
        raw_indices = target_data.get('ship_indices') or []
        if not isinstance(raw_indices, list) or not raw_indices:
            return {'status': 'error', 'message': '请至少选择一艘战舰'}
        applied = 0
        skipped = 0
        for idx in raw_indices[:3]:
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                continue
            if not (0 <= idx < len(caster.ships)):
                continue
            # 已沉的船不给加盾：护盾加在沉船上等于白白浪费一次选择
            if not _is_ship_alive(caster, caster.ships[idx]):
                skipped += 1
                continue
            caster.ships[idx].shield = True
            applied += 1
        if applied == 0:
            return {'status': 'error', 'message': '无效的选择（已沉没的船不能加护盾）'}
        room.magic_temp_data = {}
        # 消费优先队列里的那条登记（见仁王之盾发动处的说明）
        _consume_ship_pick(room, player_id, 'shield_choice')
        # （一次性挡伤，剩几艘有盾直接决定后面几炮打谁），前端此前完全收不到，
        # 连"我加了盾"都没有任何反馈。
        _emit_player_ships(room, player_id)
        emit('message', {'text': f'已为{applied}艘战舰添加护盾'}, to=caster.sid)
        msg = f'为{applied}艘战舰添加了护盾'
        if skipped:
            msg += f'（{skipped}艘已沉没，已跳过）'
        return {'status': 'success', 'message': msg}

    return {'status': 'error', 'message': '无效的临时数据ID'}


@socketio.on('cancel_magic_selection')
@_require_live_room
def handle_cancel_magic_selection(data):
    """放弃当前待选择状态（桃园结义 / 明智埋葬 / 仁王之盾 / 神机妙算宣言）。

    桃园结义：已抽出的牌放回牌堆，不产生任何效果。
    放置流程（增援/复活/绝处逢生）请用 cancel_placement，这里只做拒绝。
    """
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    temp = room.magic_temp_data or {}
    # 在清空 magic_temp_data 之前先把"这是哪个选择流程"记下来 —— 取消时要用它通知对手
    cancelled_kind = temp.get('type')
    pending = temp.get('pending_placement')
    if pending and pending.get('caster') == player_id:
        return {'status': 'error', 'message': '放置尚未完成，请用放置面板的「放弃」'}
    if temp.get('caster') and temp.get('caster') != player_id:
        return {'status': 'error', 'message': '当前不是你的选择'}

    cards = temp.get('cards')
    # 亡羊补牢的候选牌来自弃牌堆，取消时应当回归弃牌堆（而不是 magic_deck）。
    # 暂存的「亡羊补牢自己」也要一起放回弃牌堆末尾。
    if cancelled_kind == 'wangyang_choice':
        if isinstance(cards, list):
            for c in cards:
                if isinstance(c, MagicCard):
                    room.magic_discard.append(c)
        own_card = temp.get('own_card')
        if isinstance(own_card, MagicCard):
            room.magic_discard.append(own_card)
    elif isinstance(cards, list):
        # 只放回真正的卡牌实例（明智埋葬的候选是纯数据，混进牌堆会污染牌堆）
        room.magic_deck.extend(c for c in cards if isinstance(c, MagicCard))
    room.magic_temp_data = {}
    # 取消选船类效果时，把优先队列里那条登记一并撤掉
    # （不撤的话它会一直挡着别的选船卡，玩家以为卡死了）
    if cancelled_kind == 'shield_choice':
        _consume_ship_pick(room, player_id, 'shield_choice')

    # ⚠️ 必须同时通知对手。桃园结义在对手侧是一层**全屏等待浮层**
    # （.taoyuan-waiting-overlay，z-index 10000，挡住一切），而它只认 taoyuan_complete；
    # 取消时一个事件都不发 → 对手永久卡在那层浮层上、什么都点不了
    # （作者 2026-09-16 实测）。灵气复苏只发一条 toast，不必挡屏，但同样一并同步，
    # 免得两条流程行为不一致（下次改的人又要重新踩一遍）。
    if cancelled_kind in ('taoyuan_choice', 'lingqi_choice'):
        opponent_id = _opponent_of(room, player_id)
        if opponent_id and opponent_id in room.players:
            label = '桃园结义' if cancelled_kind == 'taoyuan_choice' else '灵气复苏'
            emit('taoyuan_complete' if cancelled_kind == 'taoyuan_choice' else 'lingqi_complete',
                 {'cancelled': True,
                  'message': f'对方取消了{label}（已放回牌堆），本回合继续'},
                 to=room.players[opponent_id].sid)

    # 亡羊补牢取消：通知对手结算完成
    if cancelled_kind == 'wangyang_choice':
        opponent_id = _opponent_of(room, player_id)
        if opponent_id and opponent_id in room.players:
            emit('wangyang_complete', {
                'cancelled': True,
                'message': '对方取消了亡羊补牢（弃牌区已还原）',
            }, to=room.players[opponent_id].sid)

    emit('message', {'text': '已取消本次选择'}, to=room.players[player_id].sid)
    return {'status': 'success', 'message': '已取消本次选择'}


@socketio.on('get_discard_pile')
def get_discard_pile(data):
    """获取玩家的弃牌堆数据（返回全局弃牌堆）"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')

    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 获取全局弃牌堆数据
    discard_pile = room.magic_discard

    # 过滤掉重复的非"失灵！"卡牌（场上仅存在一张）
    unique_discard = []
    seen = set()
    for card in discard_pile:
        if card.name == '失灵！' or card.name not in seen:
            unique_discard.append(card)
            if card.name != '失灵！':
                seen.add(card.name)

    return {'status': 'success', 'discard_pile': json.loads(json.dumps(unique_discard, default=lambda o: o.__dict__))}


# 添加辅助函数


def find_safe_position(room: GameRoom, player_id: str):
    """寻找未被攻击过的安全位置"""
    opponent_id = next(p for p in room.players if p != player_id)
    opponent_attacks = [(a.x, a.y) for a in room.players[opponent_id].attacks]

    for y in range(6):
        for x in range(6):
            if (x, y) not in opponent_attacks:
                return {'x': x, 'y': y}
    return None


# ============ 神威！“扣掉”区域（2026-09-10） ============
def _shenwei_holes(room):
    return room.game_effects.setdefault('shenwei_holes', [])


def _add_shenwei_hole(room, player_id, area, return_turn):
    """把某玩家棋盘上的一块 3x3 区域标记为“扣掉”。"""
    _shenwei_holes(room).append({
        'player': player_id,
        'x1': area['x1'], 'y1': area['y1'],
        'x2': area['x2'], 'y2': area['y2'],
        'return_turn': return_turn,
    })


def _cell_in_shenwei_hole(room, player_id, x, y):
    """该格子是否位于某玩家被扣掉的区域内。"""
    for hole in _shenwei_holes(room):
        if hole['player'] != player_id:
            continue
        if hole['x1'] <= x <= hole['x2'] and hole['y1'] <= y <= hole['y2']:
            return True
    return False


def _clear_due_shenwei_holes(room, current_round):
    """清除到期的扣洞标记，返回被恢复的区域列表。"""
    holes = _shenwei_holes(room)
    due = [h for h in holes if h['return_turn'] <= current_round]
    for h in due:
        holes.remove(h)
    return due


def _restore_due_shenwei(room, current_round):
    """到期回归：恢复被扣掉的区域，并把除外的战舰放回原位。

    ⚠️ 归还前必须确认那艘船【仍属于当前棋盘】。
    「重摆棋盘」类效果（回光返照 / 灵气复苏 / 绝处逢生 / 败者食尘）会把
    player.ships 整批换掉，被除外的旧船对象已经不在棋盘上了；无条件 append
    会让它们以"幽灵船"的身份回来 —— 实测 6 艘变 8 艘，突破上限且坐标与现有船重叠。
    重摆路径会调 _discard_excluded_ships() 把过期条目丢掉（见那里的说明），
    这里再做一次防御：不在棋盘上的船一律不归还。
    """
    entries = room.game_effects.get('excluded_ships') or []
    due = [e for e in entries if e['return_turn'] <= current_round]
    for entry in due:
        entries.remove(entry)
        owner = room.players[entry['player']]
        returned = 0
        for ship in entry['ships']:
            if ship in owner.ships:
                continue          # 已经在棋盘上，不重复加
            if getattr(ship, '_detached', False):
                continue          # 棋盘已被重摆，这艘船属于上一批
            owner.ships.append(ship)
            owner.remaining_ships += 1
            returned += 1
        # 八方来财：神威除外到期归还 = 船数主动增加（非攻击），全场持卡者都摸
        if returned:
            _notify_treasure_hunter(room, returned)
            # ★ 2026-09-20 修：归还后**必须把船数据发给本人**。
            #   以前这里只 append、只发下面的 `shenwei_hole_restored`，而那个事件
            #   在前端只负责**清掉格子上的斜纹样式**（`applyShenweiHoles`），
            #   它**不带船的数据** —— 于是格子干净了、船却没画出来，
            #   作者实测症状就是「神威区域恢复后船变得不可见」。
            #   参考对照：同文件里解冻路径（end_turn 大回合开始处）改完船之后
            #   明确调了 `_emit_player_ships`，归还路径当初漏了这一步。
            _emit_player_ships(room, entry['player'])
    if not entries:
        room.game_effects.pop('excluded_ships', None)
    # 船数变了 → 双方「你的船数 / 对手船数」视图也要同步。
    # ⚠️ 只在**真的有船归还**时发：无事也发会让客户端白重画一遍。
    if due:
        _emit_ships_updated(room)
    for hole in _clear_due_shenwei_holes(room, current_round):
        emit('shenwei_hole_restored', {'player': hole['player']}, room=room.id)


def _clear_board_effects(room, player_ids, why: str) -> None:
    """**重摆棋盘**时终止"持续生效的范围类"效果（幂等）。

    为什么需要它（作者 2026-09-19 实测报的）：重摆棋盘的卡（灵气复苏 / 回光返照 /
    败者食尘 / 绝处逢生）原来只调了 `_discard_excluded_ships()` —— 丢掉了「神威**除外**的船」，
    却**没人清「神威扣掉的区域」**（`game_effects['shenwei_holes']`）。
    于是棋盘已经换上新船，那片区域**继续挡攻击**，直到原本的 `return_turn` 才解除 ——
    玩家看到的就是「神威一直生效」。冻结的那片区域（`game_effects['frozen_area']`）同理。

    清三样：
      · `excluded_ships` → 走既有 `_discard_excluded_ships()`（重摆后旧船不属于新棋盘，
        不清的话到期会以"幽灵船"身份 append 回来 —— 7469 那条注释记录过 6 艘变 8 艘）
      · `shenwei_holes`  → 删掉受影响玩家的洞，并按玩家 `emit('shenwei_hole_restored', ...)`
        （前端就是**按玩家**清空全部洞再重画，见 `applyShenweiHoles()`）
      · `frozen_area`    → 看 `owner`（那片区域记在**受害者棋盘**上）落在受影响玩家里的那块，
        `pop` 并 `emit('frozen_area', {'cleared': True})`

    ⚠️ **只清"这次真的重摆了棋盘的玩家"**：回光返照只重摆自己 → 就不能顺手清掉对方棋盘上的
       区域标记（那是对方的公开信息，而且对方棋盘根本没被换）。
    ⚠️ 事件只在**真的清掉过东西**时才发：无事也发会让客户端白重画一遍棋盘。
    """
    ids = [str(p) for p in (player_ids or [])]
    if not ids:
        return
    # ① 除外船（每个受影响玩家各一次；`None` 才是"双方一起"）
    for pid in ids:
        _discard_excluded_ships(room, pid)

    effects = room.game_effects if isinstance(room.game_effects, dict) else None

    # ② 神威扣掉的区域
    if effects is not None:
        holes = effects.get('shenwei_holes') or []
        for pid in ids:
            mine = [h for h in holes if str(h.get('player')) == pid]
            if not mine:
                continue
            for h in mine:
                holes.remove(h)
            emit('shenwei_hole_restored', {'player': pid}, room=room.id)
        if not holes:
            effects.pop('shenwei_holes', None)

        # ③ 冻结的那片区域（记在受害者棋盘上，所以看 owner）
        area = effects.get('frozen_area')
        if isinstance(area, dict) and str(area.get('owner')) in ids:
            effects.pop('frozen_area', None)
            emit('frozen_area', {'cleared': True}, room=room.id)

    print(f'[board] {why}：已终止受影响棋盘上的范围效果（{",".join(ids)}）')


# ---------------------------------------------------------------------------
# 「跨回合计数类」效果 —— **唯一一份名单**（2026-09-20 重摆批）
#
# 与 `_clear_board_effects` 管的**范围类**（神威洞 / 冻结区，按格子）不同，
# 这些效果在 `game_effects` 里存的是**跨回合倒计时**，会在后续大回合继续递减，
# 归零时**直接判胜负**。所以重摆棋盘时必须一并终止，否则：
#   · `holy_heart`          → 归零时凭空判施法者获胜
#   · `reinforcement_check` → 归零时凭空判船少的一方获胜
#   · `demon_contract`      → 继续要求双方牺牲（棋盘都换了还挂着）
#
# ⚠️ 名单只有一份，四张重摆卡共用 —— 以前它们各自只调 `_clear_board_effects`，
#    而那个函数不管这些键，于是效果**静默残留**（本项目第 10 节第 1 条的老病根：
#    同一个判断散在多处就一定会漂移）。
#
# 每项：(game_effects 里的键, 给前端发的清除事件名, 是否广播给全房)
_MULTITURN_EFFECTS = (
    ('holy_heart', 'holy_heart_cleared', True),
    ('reinforcement_check', 'reinforcement_cleared', True),
    ('demon_contract', 'demon_contract_cleared', True),
)

# 这些键以玩家 id 结尾变体（如预测快照 `prediction_initial_<pid>`），单独前缀匹配清理
_MULTITURN_PREFIXES = ('prediction', 'prediction_initial_')


def _clear_multiturn_effects(room, why: str) -> None:
    """**重摆棋盘**时终止"跨回合计数类"效果（幂等）。

    为什么需要它（作者 2026-09-20 实测报的）：极限增援 / 无暇圣心这类卡
    跨多个大回合计数，而重摆棋盘的卡（灵气复苏 / 败者食尘 / 回光返照 / 绝处逢生）
    以前**只调 `_clear_board_effects`** —— 那个函数只管范围类（神威洞/冻结区），
    于是这些计数效果**留在 `game_effects` 里继续递减**，到 0 时凭空判胜负。

    除了判胜负，还有**前端角标**问题：前端收到过 `holy_heart_activated` /
    `reinforcement_activated`，若清除时不发事件，角标会一直亮着，
    玩家以为效果还在生效。所以这里**清掉的同时必须发对应的事件**。

    ⚠️ 只清名单里的键，**不碰**名单外的东西（比如 `no_draw` 属于别的机制）。
    """
    effects = getattr(room, 'game_effects', None)
    if not isinstance(effects, dict):
        return

    fired = []
    for key, event_name, broadcast in _MULTITURN_EFFECTS:
        if key not in effects:
            continue
        effects.pop(key, None)
        try:
            if broadcast:
                emit(event_name, {'reason': why}, room=getattr(room, 'id', None) or None)
            else:
                emit(event_name, {'reason': why}, room=getattr(room, 'id', None) or None)
        except Exception:
            pass          # 发事件失败不许把重摆流程搞崩（与其它收口同规矩）
        fired.append(key)

    # 前缀类（预测快照等）：按玩家各存一份，一并清掉
    for key in list(effects.keys()):
        if any(str(key).startswith(p) for p in _MULTITURN_PREFIXES):
            effects.pop(key, None)
            fired.append(key)

    if fired:
        print(f'[board] {why}：已终止跨回合效果（{",".join(fired)}）')


def _discard_excluded_ships(room, player_id=None):
    """棋盘被重摆时调用：放弃尚未归还的「神威！除外」船只。

    重摆会把 player.ships 整批换新，被除外的旧船对象已不属于棋盘；
    若仍留在 excluded_ships 里，到期会以幽灵船身份 append 回来
    （实测：6 艘变 8 艘，突破上限、坐标与现有船重叠）。
    player_id 为 None 时处理全部玩家（败者食尘这类双方一起重摆的场景）。
    """
    entries = room.game_effects.get('excluded_ships')
    if not entries:
        return
    if player_id is None:
        room.game_effects.pop('excluded_ships', None)
        return
    kept = [e for e in entries if e.get('player') != player_id]
    if kept:
        room.game_effects['excluded_ships'] = kept
    else:
        room.game_effects.pop('excluded_ships', None)


def _apply_ship_loss_linkage(room, caster_id, lost_player_id, count=1):
    """船数减少时的通用联动：无暇圣心 / 百亿补贴 / 八方来财 / 恶魔契约。

    与击沉路径保持一致，供神威！除外复用。
    """
    lost_player = room.players[lost_player_id]

    # 无暇圣心：造成船数变化即视为“有伤害”，中断效果
    if 'holy_heart' in room.game_effects:
        room.game_effects['holy_heart']['no_damage'] = False

    # 百亿补贴：自己的船被击败时，自己的攻击次数 +3
    _grant_subsidy_bonus(room, lost_player_id)

    # 八方来财：魔法卡造成的船数减少属于"主动变化"，全场持卡者都摸。
    # 注意这里【不排除】caster —— 卡面排除的只是"己方【击败】对方的船"（炮击），
    # 魔法卡（神威！等）造成的变化照算。
    _notify_treasure_hunter(room, 1)

    # 恶魔契约：一方船数减少，另一方也要牺牲一艘 —— 由该玩家自己点选（不再随机）
    if room.game_effects.get('demon_contract'):
        _request_demon_contract_sacrifice(room, lost_player_id)


# ===========================================================================
# 选船类效果的**优先级仲裁**（2026-09-20）
#
# 背景（作者实测报的）：需要选船的多个效果同时发生时，在选船环节会卡住。
# 最典型的是「恶魔契约生效中 + 自己在战斗阶段打出克苏鲁之眼」——
# 第二次请求把第一次的覆盖掉，先那个玩家点船就报「当前没有待牺牲的战舰」。
#
# 修法两条：
#   ① 待选从「单槽」改成**按玩家分组的队列**（`room.pending_ship_picks`），
#      同一个人的多项按**优先级**依次交付，不同玩家互不影响；
#   ② 低优先级的选船卡在有更高优先级待选时**拒绝出牌并给出明确文案**
#      （而不是排队后延迟重放 —— 见计划 §3.4 的取舍）。
#
# ⚠️ **优先级只有这一份**（与 `_MULTITURN_EFFECTS` / `FLAGS_KEEP_ACROSS_TURN` 同一路数）。
#    新增选船类效果时必须在这里登记，否则 `.get(reason, 0)` 会让它排到最后。
# ===========================================================================
SHIP_PICK_PRIORITY = {
    # 持续场地效果，船数**已经变了**，不立刻结算会与后续船数变化打架
    'demon_contract': 100,
    # 卡牌自身结算的组成部分：不出结果这张牌等于没打完
    'divine_decree': 80,
    # 守株待兔：打出去就要选船设陷阱，不出结果牌等于没打完
    'trap_setup': 75,
    # 纯信息披露，延后无任何副作用
    'kraken_eye': 60,
    # 仁王之盾（至多 3 艘加盾）：自己的战术选择，最可延后
    'shield_choice': 40,
}

# 「打这张卡会触发选船」的卡名 → 它对应哪个 reason（用于出牌闸门）。
# ⚠️ 只有**会产生待选请求**的卡在这里；`恶魔契约` 是场地效果、不由玩家主动打出。
_SHIP_PICK_CARDS = {
    '克苏鲁之眼': 'kraken_eye',
    '神之宣告': 'divine_decree',
    '仁王之盾': 'shield_choice',
    '守株待兔': 'trap_setup',
}


def _ship_pick_priority(reason) -> int:
    """取某类选船效果的优先级；未登记的一律 0（排最后，不报错）。"""
    try:
        return int(SHIP_PICK_PRIORITY.get(str(reason), 0))
    except (TypeError, ValueError):
        return 0


def _my_ship_picks(room, player_id) -> list:
    """该玩家当前挂着的全部待选项（按优先级降序、同优先级按 seq 升序）。"""
    picks = getattr(room, 'pending_ship_picks', None)
    if not isinstance(picks, list) or not player_id:
        return []
    mine = [p for p in picks if isinstance(p, dict) and p.get('player') == player_id]
    mine.sort(key=lambda p: (-_ship_pick_priority(p.get('reason')), int(p.get('seq') or 0)))
    return mine


def _top_ship_pick(room, player_id):
    """该玩家**当前应该处理**的那一项（队列里优先级最高的）；没有则 None。"""
    mine = _my_ship_picks(room, player_id)
    return mine[0] if mine else None


def _emit_ship_pick_request(room, entry) -> None:
    """把某一项待选下发给对应玩家（内部用；失败绝不影响对局）。"""
    try:
        if entry.get('silent'):
            return                          # 静默登记项：前端有自己的选区 UI
        player = room.players.get(entry.get('player'))
        if player is None or not getattr(player, 'sid', None):
            return
        alive = _alive_ships(player)
        if not alive:
            return
        emit('sacrifice_request', {
            'reason': entry.get('reason'),
            'message': entry.get('message') or '请点选一艘自己的战舰',
            # 只下发活船：前端直接拿这份来点亮可点格子（服务端即唯一真相）
            'ships': [
                {'positions': [{'x': p.x, 'y': p.y} for p in sh.positions]}
                for sh in alive
            ],
        }, to=player.sid)
    except Exception:
        pass


def _register_simple_ship_pick(room, player_id, reason, message) -> None:
    """把一项选船待办**只登记进优先级队列**，**不发** `sacrifice_request`。

    给"交互方式不同、但同样占用棋盘选区"的效果用（目前是仁王之盾：
    它走 `select_magic_target` 的多选，前端自己有选区 UI，不需要我们去弹提示）。
    登记的意义是让**优先级仲裁看得见它** —— 别的效果据此让路。
    """
    picks = getattr(room, 'pending_ship_picks', None)
    if not isinstance(picks, list):
        room.pending_ship_picks = picks = []
    for p in picks:
        if isinstance(p, dict) and p.get('player') == player_id \
                and p.get('reason') == reason:
            return                          # 已在队列里，不重复登记
    room.ship_pick_seq = int(getattr(room, 'ship_pick_seq', 0) or 0) + 1
    picks.append({
        'player': player_id,
        'reason': reason,
        'message': message,
        'priority': _ship_pick_priority(reason),
        'seq': room.ship_pick_seq,
        'silent': True,                     # 不发 sacrifice_request（前端自有点选 UI）
    })


def _dispatch_ship_pick(room, player_id) -> None:
    """把该玩家队列里优先级最高的那一项（重新）下发给前端。

    幂等：没有待选时不发任何事件（无事也发会让客户端白弹一次提示）。
    """
    entry = _top_ship_pick(room, player_id)
    if entry is not None:
        _emit_ship_pick_request(room, entry)


def _consume_ship_pick(room, player_id, reason=None) -> bool:
    """消费该玩家**栈顶**那一项，然后自动投递剩下的下一项。

    `reason` 给出时只消费匹配的那一项（防止"点了一下却把别的效果也吃掉"）。
    返回是否真的消费掉了。
    """
    picks = getattr(room, 'pending_ship_picks', None)
    if not isinstance(picks, list):
        return False
    top = _top_ship_pick(room, player_id)
    if top is None:
        return False
    if reason is not None and top.get('reason') != reason:
        return False
    try:
        picks.remove(top)
    except ValueError:
        return False                       # 并发下已被消费，视作无事发生
    _dispatch_ship_pick(room, player_id)   # 还有就接着弹下一项
    return True


def _clear_ship_picks(room, player_id=None) -> None:
    """清空待选队列（`player_id` 为 None 时清全部）。终局 / 重摆棋盘时用。"""
    picks = getattr(room, 'pending_ship_picks', None)
    if not isinstance(picks, list):
        return
    if player_id is None:
        room.pending_ship_picks = []
    else:
        room.pending_ship_picks = [
            p for p in picks if not (isinstance(p, dict) and p.get('player') == player_id)]


def _ship_pick_blocked_reason(room, player_id, card_name) -> str:
    """打这张卡是否被"更高优先级的待选"挡住。返回拒绝文案（空串 = 放行）。

    ⚠️ **只拦选船类卡**：非选船卡（轰炸等）任何时候都放行 ——
       闸门开大了会把正常出牌也堵死（`_action_wait_reason` 那种全局门禁不适合这里）。
    """
    reason_wanted = _SHIP_PICK_CARDS.get(str(card_name or ''))
    if not reason_wanted:
        return ''
    top = _top_ship_pick(room, player_id)
    if top is None:
        return ''
    if _ship_pick_priority(top.get('reason')) <= _ship_pick_priority(reason_wanted):
        return ''
    pending_name = _SHIP_PICK_LABELS.get(str(top.get('reason')), '一个待处理的选船效果')
    return f'请先完成「{pending_name}」的选船，再使用这张卡'


# 待选 reason → 中文名（只用于**给玩家看的提示**；判据一律用 reason 本身）
_SHIP_PICK_LABELS = {
    'demon_contract': '恶魔契约',
    'divine_decree': '神之宣告',
    'kraken_eye': '克苏鲁之眼',
    'shield_choice': '仁王之盾',
    'trap_setup': '守株待兔',
    'trap_sacrifice': '守株待兔',
    'dice_sacrifice': '命运骰子',
}


def _my_pending_sacrifice_payload(room, player_id):
    """重连快照：该玩家当前该处理的那一项待选（没有/静默项 → None）。"""
    top = _top_ship_pick(room, player_id)
    if top is None or top.get('silent'):
        return None
    return {k: top.get(k) for k in ('reason', 'message', 'priority')}


def _my_pending_sacrifice_ships(room, player_id, player):
    """重连快照：该玩家可点选的**活船**名单（与下发的候选保持一致）。

    只给活船 —— 沉船还留在 `player.ships` 里，混进去会让重连后又点到自己的沉船。
    """
    top = _top_ship_pick(room, player_id)
    if top is None or top.get('silent'):
        return []
    return [{'positions': [{'x': q.x, 'y': q.y} for q in sh.positions]}
            for sh in _alive_ships(player)]


def _request_ship_pick(room, chooser_id, reason, message, allow_duplicate=False):
    """让指定玩家在自己的棋盘上点选一艘【活着的】战舰（恶魔契约 / 神之宣告 / 克苏鲁之眼 共用）。

    AI 不参与交互：直接返回替它选中的那艘；人类玩家则**入队**并交付优先级最高的那一项。
    候选只给活船 —— 沉船还留在 player.ships 里，混进去会让玩家（或 AI）
    拿一艘早就沉了的船抵账，等于零代价。

    ⚠️ 2026-09-20 改为**队列**（旧实现是单槽覆写，第二个请求会把第一个挤掉）。
    ⚠️ `allow_duplicate`：默认同玩家+同 reason 去重（同一张卡不会连开两个一样的请求）；
       命运骰子摇到6需要对方连点两艘，传 True 跳过去重。
    """
    chooser = room.players.get(chooser_id) if chooser_id else None
    if not chooser:
        return None

    alive = _alive_ships(chooser)
    if not alive:
        return None

    if getattr(room, 'is_ai_room', False) and chooser_id == _ai_player_id(room):
        return random.choice(alive)

    picks = getattr(room, 'pending_ship_picks', None)
    if not isinstance(picks, list):
        room.pending_ship_picks = picks = []
    # 同一玩家、同一 reason **不重复入队**（同一张卡不会连开两个一样的请求；
    # 真出现也只需要一次点击，重复项会让玩家被要求连点两下）
    # 例外：allow_duplicate=True 时跳过（命运骰子摇到6要让对方连点两艘）
    if not allow_duplicate:
        for p in picks:
            if isinstance(p, dict) and p.get('player') == chooser_id \
                    and p.get('reason') == reason:
                _dispatch_ship_pick(room, chooser_id)
                return None

    room.ship_pick_seq = int(getattr(room, 'ship_pick_seq', 0) or 0) + 1
    picks.append({
        'player': chooser_id,
        'reason': reason,
        'message': message,
        'priority': _ship_pick_priority(reason),
        'seq': room.ship_pick_seq,
    })
    _dispatch_ship_pick(room, chooser_id)
    return None


def _request_demon_contract_sacrifice(room, lost_player_id):
    """恶魔契约触发：让另一方自己选择要牺牲的战舰（在其自方棋盘上点选）。"""
    sacrifice_id = _opponent_of(room, lost_player_id)
    picked = _request_ship_pick(room, sacrifice_id, 'demon_contract',
                                '恶魔契约生效：请点选一艘自己的战舰牺牲')
    if picked is not None:
        _do_demon_contract_sacrifice(room, sacrifice_id, picked)


def _do_demon_contract_sacrifice(room, player_id, ship, reason='demon_contract'):
    """执行"牺牲一艘船"：移除该船并公开广播，使双方都能看到沉没位置。

    reason 用于日志/广播文案：demon_contract / divine_decree。
    """
    player = room.players.get(player_id)
    if not player or ship is None or ship not in player.ships:
        return

    # 消费掉这一项待选（可能还有下一项 → 会自动接着投递）
    # ⚠️ 旧实现是 `magic_temp_data.pop('pending_sacrifice')` —— 单槽，且会误伤别人。
    _consume_ship_pick(room, player_id, reason)

    player.ships.remove(ship)
    _mark_ship_sunken(player, ship)
    player.remaining_ships = max(0, player.remaining_ships - 1)

    positions = [{'x': p.x, 'y': p.y} for p in ship.positions]
    reason_text = {'divine_decree': '神之宣告', 'dice_sacrifice': '命运骰子',
                   'trap_sacrifice': '守株待兔'}.get(reason, '恶魔契约')
    add_game_log(room,
                 f'第{room.round}回合 · {_log_name(room, player_id)} 因{reason_text}牺牲一艘战舰',
                 'magic',
                 {'player': player_id, 'reason': reason, 'positions': positions})

    # 公开广播：自己与对手都能看到这艘船被划掉
    emit('ship_sacrificed', {
        'player': player_id,
        'positions': positions,
        'reason': reason,
    }, room=room.id)

    # 船数按各自视角分别推送（广播同一份数据会导致双方看到的数字颠倒）
    _emit_ships_updated(room)


# ============ 判定魔法卡：命运骰子 ============
# 各点数对应的播报文案（前端动画结束后的"会发生什么效果"也用这份）
DICE_EFFECT_TEXT = {
    1: '复活对方的一艘战舰',
    2: '对方抽一张牌',
    3: '双方各弃一张手牌',
    4: '自己抽两张牌',
    5: '复活自己的至多两艘战舰',
    6: '对手牺牲两艘战舰',
}


def _apply_dice_of_fate(room, caster_id, result):
    """命运骰子：摇 1-6，按点数结算不同效果。

    1 复活对方一艘 / 2 对方抽一张 / 3 双方各弃一张 /
    4 自己抽两张 / 5 复活自己至多两艘 / 6 对方牺牲两艘。

    3 与 6 需要"玩家点选"，登记房间级待办：
      · 弃牌（3）：room.pending_dice_discard = {pid: False}
        + emit 'dice_discard_request' 给每位需弃牌的玩家；
        玩家通过 'dice_discard_choose' 事件回传选择。
      · 牺牲两艘（6）：复用 _request_ship_pick，reason='dice_sacrifice'，
        入队两次；人类走 sacrifice_request 流程，AI 由 _request_ship_pick 自动选。
    """
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]

    roll = random.randint(1, 6)
    effect_text = DICE_EFFECT_TEXT.get(roll, '')

    # 广播骰子动画 + 结果给双方（动画在前，结果文本一并下发，前端动画结束再显示文本）
    emit('dice_rolled', {
        'roll': roll,
        'caster': caster_id,
        'effect_text': effect_text,
    }, room=room.id)

    add_game_log(room,
                 f'第{room.round}回合 · {_log_name(room, caster_id)} 使用【命运骰子】摇出 {roll} 点：{effect_text}',
                 'magic', {'caster': caster_id, 'roll': roll, 'card': '命运骰子'})

    if roll == 1:
        # 复活对方一艘（原地复活，无副作用）。对方没有沉船则不复活。
        revived = 0
        if opponent.sunken_ships:
            revived = _revive_sunken_ships(room, opponent, 1, reveal_to=caster_id)
        result.message = '摇出1点：' + effect_text + (
            '，对方一艘战舰复活' if revived else '，对方没有沉船，未复活')
    elif roll == 2:
        drawn = room.draw_card(opponent_id)
        result.message = '摇出2点：' + effect_text + (
            '，对方抽了一张牌' if drawn else '，但对方未能抽牌（牌堆空或被禁止抽卡）')
    elif roll == 3:
        # 双方各弃一张：无牌者跳过；AI 自动弃第一张；人类登记待办
        _start_dice_discard(room, caster_id, opponent_id)
        result.message = '摇出3点：' + effect_text + '，等待双方选择弃牌'
    elif roll == 4:
        drawn = 0
        for _ in range(2):
            if room.draw_card(caster_id) is not None:
                drawn += 1
        result.message = f'摇出4点：{effect_text}（实际抽到{drawn}张）'
    elif roll == 5:
        count = min(2, len(caster.sunken_ships))
        revived = _revive_sunken_ships(room, caster, count, reveal_to=opponent_id) if count > 0 else 0
        result.message = '摇出5点：' + effect_text + (
            f'，自己复活了{revived}艘战舰' if revived else '，自己没有沉船，未复活')
    elif roll == 6:
        # 对方牺牲两艘：复用 ship_pick 队列，reason='dice_sacrifice'。
        # 人类入队两次（allow_duplicate=True 跳过同 reason 去重，否则第二次被吞）；
        # AI 由 _request_ship_pick 自动选并立即执行。
        alive = _alive_ships(opponent)
        need = min(2, len(alive))
        sacrificed = 0
        for _ in range(need):
            picked = _request_ship_pick(room, opponent_id, 'dice_sacrifice',
                                        '命运骰子：请点选一艘战舰牺牲',
                                        allow_duplicate=True)
            if picked is not None:
                _do_demon_contract_sacrifice(room, opponent_id, picked, 'dice_sacrifice')
                sacrificed += 1
        if need == 0:
            result.message = '摇出6点：' + effect_text + '，但对方没有可牺牲的战舰'
        elif sacrificed == need:
            result.message = f'摇出6点：{effect_text}（对方已牺牲{sacrificed}艘）'
        else:
            result.message = '摇出6点：' + effect_text + '，等待对方点选牺牲的战舰'


def _start_dice_discard(room, caster_id, opponent_id):
    """命运骰子摇到3：让双方各弃一张手牌。

    · 无手牌的玩家直接跳过；
    · AI 自动弃第一张；
    · 人类登记 room.pending_dice_discard[pid] = False 并 emit 'dice_discard_request'。
    """
    room.pending_dice_discard = {}
    ai_id = _ai_player_id(room) if getattr(room, 'is_ai_room', False) else None

    for pid in (caster_id, opponent_id):
        player = room.players[pid]
        if not player.magic_hand:
            # 无牌可弃：直接标记完成，不弹窗
            room.pending_dice_discard[pid] = True
            continue
        if pid == ai_id:
            # AI 自动弃第一张（与教皇旨意弃卡同一口径：随机选没意义，取首张）
            discarded = player.magic_hand.pop(0)
            room.magic_discard.append(discarded)
            emit('hand_updated', {'hand': player.magic_hand}, to=player.sid)
            add_game_log(room,
                         f'第{room.round}回合 · {_log_name(room, pid)} 因命运骰子弃置「{discarded.name}」',
                         'magic', {'player': pid, 'card': discarded.name, 'reason': 'dice_discard'})
            room.pending_dice_discard[pid] = True
        else:
            room.pending_dice_discard[pid] = False
            emit('dice_discard_request', {
                'message': '命运骰子：请选择一张手牌弃置',
                'reason': 'dice_discard',
            }, to=player.sid)

    # 双方都无需弃（都没手牌 / 都是 AI）→ 立即收尾，别留下空待办挂着
    _check_dice_discard_complete(room)


def _check_dice_discard_complete(room):
    """双方都完成弃牌后清掉待办并广播结束。"""
    pending = getattr(room, 'pending_dice_discard', None)
    if not isinstance(pending, dict) or not pending:
        return
    if all(pending.values()):
        room.pending_dice_discard = {}
        emit('dice_discard_complete', {}, room=room.id)


@socketio.on('dice_discard_choose')
@_require_live_room
def handle_dice_discard_choose(data):
    """命运骰子摇到3：玩家选定要弃的手牌。"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    card_index = data.get('card_index')

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    pending = getattr(room, 'pending_dice_discard', None)
    if not isinstance(pending, dict) or pending.get(player_id) is not False:
        return {'status': 'error', 'message': '当前没有等待你弃牌的命运骰子效果'}

    player = room.players[player_id]
    if not player.magic_hand:
        # 没牌可弃：直接完成
        room.pending_dice_discard[player_id] = True
        _check_dice_discard_complete(room)
        return {'status': 'success', 'message': '没有手牌可弃，已跳过'}

    try:
        idx = int(card_index)
    except (TypeError, ValueError):
        return {'status': 'error', 'message': '无效的卡牌位置'}
    if not (0 <= idx < len(player.magic_hand)):
        return {'status': 'error', 'message': '无效的卡牌位置'}

    discarded = player.magic_hand.pop(idx)
    room.magic_discard.append(discarded)
    emit('hand_updated', {'hand': player.magic_hand}, to=player.sid)
    add_game_log(room,
                 f'第{room.round}回合 · {_log_name(room, player_id)} 因命运骰子弃置「{discarded.name}」',
                 'magic', {'player': player_id, 'card': discarded.name, 'reason': 'dice_discard'})

    room.pending_dice_discard[player_id] = True
    _check_dice_discard_complete(room)
    return {'status': 'success', 'message': f'已弃置「{discarded.name}」'}


def _finish_game(room, winner_id, loser_id, reason):
    """统一结算：设置胜利者、记战绩、广播 game_over。"""
    room.state = 'game_over'
    room.winner = winner_id
    # 终局：待选队列整批作废（对局已经结束，再挂着只会挡住后续逻辑）
    _clear_ship_picks(room)
    # 命运骰子的弃牌待办同样作废（同 _clear_ship_picks 的理由）
    room.pending_dice_discard = {}
    add_game_log(room, f"第{room.round}回合 · {_log_name(room, winner_id)} 获胜，游戏结束",
                 'result', {'winner': winner_id, 'loser': loser_id, 'reason': reason})
    # 记录战绩 + 每局统计 + 徽章（统一收口，见 _finalize_match）
    _finalize_match(room, winner_id, loser_id)
    emit('game_over', {'winner': winner_id, 'reason': reason}, room=room.id)


# ============ 复活 / 增援 统一放置流程（2026-09-10） ============
def _own_occupied_cells(player, ignore_sunken=False):
    """己方棋盘上「被自己的战舰占着」的格子集合 `{(x, y)}`。

    ⚠️ 必须同时看 `ships` 与 `sunken_ships` 两份（2026-09-17）：
    本项目的击沉大多【不把船移出 ships】（沉船留在列表里供复活回收），
    但 轰炸 / 硫磺火焰 / 恶魔契约·神之宣告的牺牲 会 `ships.remove(...)`，
    这些船只剩在 `sunken_ships` 里。只扫 `ships` 就会漏掉它们的格子，于是
    「死者苏生的放置面板把刚沉掉的那一格亮成可点」——点下去还会顺手清掉
    对方打在那格的攻击历史，那一格对对方就"变回未知格子"了（玩家实测报的缺陷）。
    卡面写的是「摆放在对方没有打过的格子上」，原本有自己沉船的位置不该出现。

    ignore_sunken=True（神机妙算的"重新部署"）：沉船不占位，它的原格是合法落点。
    """
    cells = set()
    for ship in (getattr(player, 'ships', None) or []):
        if ignore_sunken and not _is_ship_alive(player, ship):
            continue
        for pos in (getattr(ship, 'positions', None) or []):
            cells.add((pos.x, pos.y))
    if not ignore_sunken:
        for ship in (getattr(player, 'sunken_ships', None) or []):
            for pos in (getattr(ship, 'positions', None) or []):
                cells.add((pos.x, pos.y))
    return cells


def _placement_error(room, player_id, x, y, allow_cells=None, ignore_sunken=False):
    """返回该格子不可放置的原因；None 表示可放置。
    规则：棋盘内、未被对方打过、不在神威扣洞内、未被己方船占用。

    allow_cells：一组 (x, y)，这些格子即使"已被对方打过"也放行。
    神机妙算预言成功后的"重新部署"要用它 —— 卡面写的是
    「在原位置**或者**对方没有打过的位置重新部署」，而原位置必然是被打过的，
    不加这个豁免就会把"回原位"这条路整个堵死。

    ignore_sunken：本项目的「击沉」只减 remaining_ships、**不会把船移出 ships**
    （沉船留在列表里供复活回收）。所以占位检查会把"沉船的原位置"也算成已占用，
    导致预言成功后连原位都放不回去。为 True 时跳过已沉的船。
    """
    if not (0 <= x <= 5 and 0 <= y <= 5):
        return '坐标超出棋盘范围'
    allow = allow_cells or set()
    opponent_id = _opponent_of(room, player_id)
    if opponent_id:
        opp_attacks = [(a.x, a.y) for a in room.players[opponent_id].attacks]
        if (x, y) in opp_attacks and (x, y) not in allow:
            return '该位置已被对方攻击过，不能放置'
    if _cell_in_shenwei_hole(room, player_id, x, y):
        return '该区域已被神威！扣掉，不能放置'
    owner = room.players[player_id]
    # 占位判定与 _placement_blocked_cells 共用一份口径（两份独立实现漂移过一次：
    # 一处把沉船算占用、一处不算，前端就画出"看着能点、点了报错"的格子）。
    if (x, y) in _own_occupied_cells(owner, ignore_sunken=ignore_sunken):
        return '该位置已被己方战舰占用'
    return None


def _placement_blocked_cells(room, player_id, ignore_sunken=False):
    """列出该玩家棋盘上不可放置的格子（已被攻击 / 己方占用 / 神威扣洞）。

    ⚠️ 必须与 _placement_error 的口径一致 —— 两套独立实现已经漂移过一次：
    这里把【所有】己方船（含沉船）的位置都算作占用，而 _placement_error 在
    ignore_sunken=True 时会跳过沉船，于是神机妙算重新部署时空格被误画成灰色，
    玩家以为"只能摆在原本沉船的地方"。
    2026-09-17 起两边共用 `_own_occupied_cells`，不再各写一份（另：沉船若已被
    轰炸/硫磺火焰移出 ships，只看 ships 会漏掉它的格子）。

    ignore_sunken：跳过已沉的船（它们的格子其实是空的）。
    """
    blocked = set()
    opponent_id = _opponent_of(room, player_id)
    if opponent_id:
        for a in room.players[opponent_id].attacks:
            blocked.add((a.x, a.y))
    owner = room.players[player_id]
    blocked |= _own_occupied_cells(owner, ignore_sunken=ignore_sunken)
    for h in _shenwei_holes(room):
        if h['player'] == player_id:
            for x in range(h['x1'], h['x2'] + 1):
                for y in range(h['y1'], h['y2'] + 1):
                    blocked.add((x, y))
    return [{'x': x, 'y': y} for (x, y) in sorted(blocked)]


def _cell_xy(cell):
    """把格子的两种形态统一成 (x, y)：`[x, y]` / `(x, y)` / `{'x':..,'y':..}`。

    `last_stand_cells` 在 `game_effects` 里存的是 `[x, y]`，而 `_build_room_sync`
    下发时转成 `{'x':..,'y':..}`；读取方两边都可能拿到，别再各写一份解包。
    拿不到就返回 None。
    """
    if isinstance(cell, dict):
        x, y = cell.get('x'), cell.get('y')
    elif isinstance(cell, (list, tuple)) and len(cell) >= 2:
        x, y = cell[0], cell[1]
    else:
        return None
    try:
        return (int(x), int(y))
    except (TypeError, ValueError):
        return None


def _emit_placement_request(room, player_id):
    p = room.magic_temp_data.get('pending_placement')
    if not p:
        return
    payload = {
        'kind': p['kind'],
        'remaining': p['remaining'],
        'total': p['total'],
        'placed': p['placed'],
        'blocked': _placement_blocked_cells(room, player_id),
    }
    if p['kind'] == 'last_stand':
        # 只允许放在原本有战舰的格子：交给前端做高亮/禁点
        payload['allowed'] = room.game_effects.get('last_stand_cells') or []
        # ⚠️ 白名单与黑名单绝不能互相矛盾（2026-09-17 实测回归，作者报「绝处逢生
        # 生效后没有可用位置供玩家选择」）：
        #   绝处逢生把【全部】战舰都牺牲了 —— 每艘都 `ships.remove()` 并记进
        #   `sunken_ships`。而 blocked 现在按「ships ∪ sunken_ships」算己方占位
        #   （那是为死者苏生/增援加的"刚沉掉那格不能摆"口径）→ 这 6 个候选格
        #   全被判成"已占用"。前端是 `if (blocked.has(key) || (allowed && !allowed.has(key)))`
        #   —— blocked 优先，于是六个格子全灰、一个都点不了。
        # 绝处逢生的合法性由服务端按 allowed 单独校验（见 handle_confirm_reinforcement），
        # 所以这里只要把候选格从 blocked 里剔除，就能恢复"只在这几格里选"的原意。
        allow = {_cell_xy(a) for a in payload['allowed']}
        allow.discard(None)
        payload['blocked'] = [b for b in payload['blocked']
                              if (b['x'], b['y']) not in allow]
    elif p['kind'] == 'shenji_redeploy':
        # 神机妙算：原位置（即便被对方打过）+ 对方未打过的空格都可选。
        # ⚠️ blocked 必须按"沉船不占位"的口径重算，不能沿用默认那份：
        # 默认口径把【所有】己方船（含沉船）都算作占用，于是旧沉船的位置
        # 也会被画成灰色 —— 实测玩家以为"只能摆在原本沉船的地方"。
        #
        # ⚠️ 这里【不能】下发 allowed：allowed 在前端是**白名单**语义
        # （game.js: `if (blocked.has(key) || (allowed && !allowed.has(key)))`
        # 直接禁点且不绑 click），那是绝处逢生"只准放在原本有船的格子"用的。
        # 神机妙算下发它 = 除了原位置全部点不动，玩家报的"只能摆在原位置/
        # 被打过的格子、放不到没打过的空格"就是这么来的。
        # 原位置的处理在下面：把它们从 blocked 里剔除即可，点得动。
        allow = {(int(a[0]), int(a[1]))
                 for a in (room.game_effects.get('shenji_redeploy_cells') or [])}
        payload['blocked'] = _placement_blocked_cells(room, player_id, ignore_sunken=True)
        payload['blocked'] = [b for b in payload['blocked']
                              if (b['x'], b['y']) not in allow]
        payload['message'] = '预言成功：请选择这艘战舰重新部署的位置（原位置或对方未打过的格子）'
    emit('placement_request', payload, to=room.players[player_id].sid)


def _start_placement(room, caster_id, kind, count):
    """开启放置流程：kind='reinforce' 增援 / 'revive' 复活 / 'shenji_redeploy' 神机妙算重新部署。"""
    room.magic_temp_data['pending_placement'] = {
        'caster': caster_id, 'kind': kind,
        'remaining': count, 'total': count, 'placed': 0,
    }
    _emit_placement_request(room, caster_id)


def _begin_shenji_redeploy(room, player_id, count, already_sunken_ids=None):
    """神机妙算预言成功：让玩家逐艘重新部署"原本会减少的那些船"。

    卡面：「那些原本会减少的船不会减少并在【原位置或者对方没有打过的位置重新部署】。」
    —— "重新部署"是玩家的主动选择，不能替他决定。

    ⚠️ 只算【本次判定所属的那个大回合内】沉的船（作者确认）。
    上一回合就沉掉的船不属于"原本会减少的船"，不该被复活。

    用【宣言时已沉船的 id 快照】做差集来判定"哪些是本回合新沉的" ——
    不能按 sunken_ships 的排列位置切分：那个列表的顺序并不保证等于沉没先后
    （复活用 pop() 从末尾取、旧船也可能被重新沉回去），按位置会取错船。
    """
    player = room.players.get(player_id)
    if player is None:
        return 0
    sunken = list(getattr(player, 'sunken_ships', []) or [])
    if already_sunken_ids is None:
        # 兼容旧快照（没有 sunken_ids 字段）：退回"按数量取最新 N 艘"。
        # 那个假设不总是成立，但总比什么都不做好。
        fresh = sunken[-int(count):] if count else []
    else:
        before = set(already_sunken_ids)
        fresh = [s for s in sunken if id(s) not in before]
    n = min(int(count), len(fresh))
    if n <= 0:
        return 0
    chosen = fresh[:n]
    # 把候选船的原位置记下来，供放置校验豁免
    original_cells = []
    for ship in chosen:
        for pos in ship.positions:
            original_cells.append([pos.x, pos.y])
    # 登记本次要重新部署的船，放置时按顺序取
    room.game_effects['shenji_redeploy_cells'] = original_cells
    room.game_effects['shenji_redeploy_ships'] = chosen
    _start_placement(room, player_id, 'shenji_redeploy', n)
    return n


def _finish_placement(room, player_id, kind):
    pending = room.magic_temp_data.get('pending_placement') or {}
    placed = int(pending.get('placed') or 0)
    room.magic_temp_data.pop('pending_placement', None)
    if kind == 'last_stand':
        room.game_effects.pop('last_stand_cells', None)
        room.game_effects.pop('last_stand_owner', None)
    if kind == 'shenji_redeploy':
        room.game_effects.pop('shenji_redeploy_cells', None)
        room.game_effects.pop('shenji_redeploy_ships', None)
    emit('placement_done', {'kind': kind}, to=room.players[player_id].sid)

    if kind == 'last_stand':
        # 绝处逢生：场上只剩这唯一一艘船，攻击次数必须【重算为 1】，
        # 不能按增量 +1 —— 那会保留发动前那一堆旧额度（实测：发动前 5 次，
        # 放完船变 6 次，与"只剩一艘船"完全脱节）。
        # 跨回合累积的百亿补贴加成属于持卡者本人，按既定规则保留叠加。
        _apply_last_stand_attacks(room, player_id)
    else:
        # 增援/复活改变了自己的船数，攻击次数要按【增量】跟着变：
        # 例：绝境中增援一艘船 = 多一条命，同时本回合还多一次攻击。
        # 注意不能用 _recalc_attacker_attacks 从头算——那会把已经用掉的次数退还。
        _sync_attacks_after_ship_change(room, player_id, placed)


def _sync_attacks_after_ship_change(room, player_id, ships_added=1):
    """己方船数变化后按增量同步攻击次数（仅当当前攻击者是本人时）。

    伊甸园（次数 = 6 - 船数）与教皇旨意（次数恒 0，靠弃卡攻击）的换算
    规则不同，这里按每艘船的增减量换算，保留已消耗的次数。
    """
    if room.state != 'attacking':
        return
    if room.current_attacker != player_id:
        return
    if _attacks_forced_zero(room):
        return          # 败者食尘生效的大回合：次数恒为 0，加不上去
    if ships_added <= 0:
        return
    field = field_magic_name(room)
    if field == '教皇旨意':
        per_ship = 0
    elif field == '伊甸园':
        per_ship = -1
    else:
        per_ship = 1
    if per_ship:
        room.attacks_remaining = max(0, room.attacks_remaining + per_ship * ships_added)
    emit('attacks_updated', {
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining
    }, room=room.id)


def _apply_last_stand_attacks(room, player_id):
    """绝处逢生放置完唯一一艘战舰后，把攻击次数【重算】为「1 + 保留的额外加成」。

    与 _sync_attacks_after_ship_change 的区别：后者按增量加减、保留旧额度，
    对绝处逢生不适用 —— 它牺牲了全部战舰，旧额度是按"牺牲前那一堆船"算出来的，
    留着就会出现"只剩 1 艘船却有 5 次攻击"。

    场地魔法仍按其规则换算：
      · 教皇旨意：攻击次数恒 0（改为弃卡攻击），不受绝处逢生影响
      · 伊甸园：次数 = 6 - 自身船数 = 6 - 1 = 5
      · 其余：1 次
    """
    if room.state != 'attacking' or room.current_attacker != player_id:
        return
    if _attacks_forced_zero(room):
        # 败者食尘生效的大回合：连"只剩一艘船的那 1 次"也不给
        room.attacks_remaining = 0
        emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining
        }, room=room.id)
        return
    field = field_magic_name(room)
    if field == '教皇旨意':
        base = 0
    elif field == '伊甸园':
        base = max(0, 6 - room.players[player_id].remaining_ships)
    else:
        base = 1
    # 百亿补贴等跨回合累积的加成属于持卡者自己，继续保留
    bonus = int(getattr(room.players[player_id].effect_flags, 'subsidy_bonus', 0) or 0)
    room.attacks_remaining = max(0, base + bonus)
    emit('attacks_updated', {
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining
    }, room=room.id)


def _tear_down_field_magic(room, caster_id):
    """拆除当前生效的场地魔法（失灵！/ 加百列之光 共用）。

    作者裁定：这两张无效化类卡「过了一会」也要能拆已贴出的场地 ——
    有连锁栈时照旧康连锁项，没有连锁栈时改成拆场地；
    自己贴的和对方贴的都可以拆。

    拆除时：
      · 场地实例进弃牌堆；
      · 清掉它留下的房间级标记（恶魔契约 / 教皇旨意），并按新规则
        纠正受影响的攻击次数（如教皇旨意被拆后恢复常规次数）；
      · 广播 field_magic_updated，双方棋盘一起刷新。

    返回被拆掉的卡（None 表示场上本来就没有场地）。
    """
    field = room.field_magic
    if not field:
        return None
    room.magic_discard.append(field)
    _clear_field_magic_effects(room)
    room.field_magic = None
    room.field_magic_owner = None
    emit('field_magic_updated', {'player_id': caster_id, 'card': None}, room=room.id)
    return field


def apply_magic_effect(room: GameRoom, caster_id: str, card: MagicCard, target_data):
    result = ChainResult(card=card, caster=caster_id, success=True, message='')
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    print(f"Applying magic effect: {card.name} target {target_data}")


    # ==== 速阶1 魔法卡 ====
    if card.name == '余音绕梁':
        # 卡面：只能在自己的准备阶段使用；接下来的「自己的攻击阶段」与
        # 「下一个回合自己的攻击阶段」造成伤害即强制击杀。
        # 因此 forced_kill 是【剩余攻击阶段数】，不是击杀次数：
        # 在 handle_attack 里只判断 >0，进入结束阶段时消耗一次。
        if room.current_phase != 'preparation' or room.current_attacker != caster_id:
            result['success'] = False
            result['message'] = '只能在自己的准备阶段使用'
            return result
        room.players[caster_id].effect_flags.forced_kill = 2
        result.message = '接下来两个攻击阶段（本回合与下一回合）将造成强制击杀'
    elif card.name == '桃园结义':
        # 无中生有生效期间双方都不能以任何方式获得魔法卡（原实现直接 pop 牌堆绕过）
        if caster.effect_flags.no_draw or room.players[opponent_id].effect_flags.no_draw:
            result['success'] = False
            result['message'] = '无中生有生效期间，双方无法获得魔法卡'
            return result
        # 从牌堆抽取n张牌(n为自己的战舰数)，自己选1张，再给对方选1张，已修复
        n = caster.remaining_ships
        drawn_cards = []

        # 只抽取牌堆中实际存在的牌
        for i in range(min(n, len(room.magic_deck))):
            drawn_cards.append(room.magic_deck.pop(0))

        if drawn_cards:
            # 记录待选择的牌
            room.magic_temp_data = {
                'type': 'taoyuan_choice',
                'caster': caster_id,
                'opponent': opponent_id,
                'cards': drawn_cards,
                'player_deck_backup': []  # 备份，用于记录放回的牌
            }
            result.message = f'抽了{len(drawn_cards)}张牌，请选择'
            result.temp_data_id = 'taoyuan_choice'
            result['cards'] = [{'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description} for c in drawn_cards]
            # 通知对手等待
            emit('taoyuan_waiting', {
                'message': '对方正在结算桃园结义效果 请等待'
            }, to=room.players[opponent_id].sid)
        else:
            result.success = False
            result.message = '无法抽取卡牌'

    elif card.name == '无中生有':
        # 抽两张牌，本回合双方无法获得魔法卡。
        #
        # ⚠️ draw_card 可能返回 None（牌堆已空 / 已被 no_draw 挡下 / 摸到重名牌
        # 自动进弃牌堆），旧实现无论实际抽到几张都报"抽了2张牌"——
        # 实测玩家因此以为卡坏了（"手牌只有无中生有时只摸上来一张"，
        # 真实原因是全局共享的 43 张牌堆快摸完了）。
        # 这里按实际抽到的张数给提示，让玩家能区分"规则限制"和"牌堆空了"。
        drawn = 0
        for _ in range(2):
            if room.draw_card(caster_id) is not None:
                drawn += 1
        # 设置禁止抽卡标记
        room.players[caster_id].effect_flags.no_draw = True
        room.players[opponent_id].effect_flags.no_draw = True
        if drawn == 2:
            result.message = '抽了2张牌，本回合双方无法获得魔法卡'
        elif drawn == 1:
            result.message = '只抽到1张牌（牌堆不足），本回合双方无法获得魔法卡'
        else:
            result.message = '牌堆已空，没有抽到牌；本回合双方仍无法获得魔法卡'

    elif card.name == '亡羊补牢':
        # 从弃牌区最新 n 张里挑 1 张进手牌，其余回归弃牌堆。
        # n = 双方剩余船数的最大值（用户裁定）。
        # ⚠️ 候选不含刚打出的亡羊补牢自己：出牌扣牌流程已经把它 append 到
        # magic_discard 末尾，所以先把它 pop 出来暂存，结算后再放回。
        n = max(caster.remaining_ships, opponent.remaining_ships)
        # 暂存刚打出的亡羊补牢自己（位于 magic_discard 末尾）
        own_card = room.magic_discard.pop() if room.magic_discard else None
        # 防御性兜底：理论上 handle_use_magic_card 已经拦过发动条件，
        # 但连锁结算时弃牌堆可能被同批次的别的卡清空，这里再判一次。
        if not room.magic_discard or n <= 0:
            result.success = False
            result.message = '弃牌区没有可挑选的卡牌'
            if own_card is not None:
                room.magic_discard.append(own_card)
            return result
        # 从末尾取 min(n, len) 张作为候选（末尾是最新）
        take = min(n, len(room.magic_discard))
        candidates = room.magic_discard[-take:]
        del room.magic_discard[-take:]
        room.magic_temp_data = {
            'type': 'wangyang_choice',
            'caster': caster_id,
            'cards': candidates,         # MagicCard 实例列表（结算时引用同一对象）
            'own_card': own_card,        # 暂存的亡羊补牢自己，结算后回归弃牌堆
        }
        result['cards'] = [
            {'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description}
            for c in candidates
        ]
        result.message = f'请从弃牌区最新{len(candidates)}张牌中选1张加入手牌'
        result.temp_data_id = 'wangyang_choice'

    elif card.name == '极限增援':
        # 两个大回合后，船少的一方获胜，已修复
        total_turns = 2
        room.game_effects["reinforcement_check"] = {
            'turn': room.round + total_turns,
            'caster': caster_id,
            'remaining_turns': total_turns,  # 添加剩余回合计数
            # 卡面：不算他生效的这个大回合 → 计数从下一个大回合才开始递减
            'activated_round': room.round,
        }
        # 通知双方客户端，极限增援已激活并显示剩余回合
        emit('reinforcement_activated', {
            'remaining_turns': total_turns
        }, room=room.id)
        result.message = '极限增援已激活，剩余2回合后结算'

    elif card.name == '无暇圣心':
        # 两个大回合后如果双方都没造成伤害，施法者获胜，已修复
        total_turns = 2
        room.game_effects['holy_heart'] = {
            'turn': room.round + total_turns,
            'caster': caster_id,
            'remaining_turns': total_turns,  # 剩余回合计数
            'no_damage': True  # 初始状态：双方都未造成伤害
        }
        # 通知双方客户端，无暇圣心已激活并显示剩余回合
        emit('holy_heart_activated', {
            'remaining_turns': total_turns
        }, room=room.id)
        result.message = '无暇圣心已激活，剩余2回合后结算'

    elif card.name == '火力全开':
        # 本回合攻击次数翻倍。
        #
        # ⚠️ 不能只设标记等 enter_battle_phase 去消费：那是速阶1的卡，
        # can_play_magic_card 允许它在【战斗阶段】使用，而阶段转换早已发生
        # （且 enter_battle_phase 在 phase 已是 battle 时直接返回 error），
        # 标记就永远没人读 —— 实测：战斗阶段打出后 attacks 仍是 6 不翻倍，
        # 标记一直挂着，玩家白扔一张牌还以为生效了。
        # 卡面是「在这一个大回合内自己的攻击阶段时，自己的攻击次数翻倍」，
        # 所以：还在准备阶段就留给 enter_battle_phase 翻（那时才知道最终次数）；
        # 已经进入战斗阶段就【立即】翻当前次数。
        #
        # ⚠️ 基准是【当前攻击次数】attacks_remaining，不是「船数 - 冻结数」。
        # 旧实现按船数重算，会把教皇旨意等场地压过的次数还原回来 ——
        # 作者实测：自己先打教皇旨意（次数归 0），对方火力全开却照样
        # 拿到 2×船数 的次数。翻倍就该是「现在有几次，就变成几次的两倍」，
        # 已经是 0 的话翻倍仍是 0。
        flags = room.players[caster_id].effect_flags
        in_battle = (room.state == 'attacking'
                     and room.current_phase == 'battle'
                     and room.current_attacker == caster_id)
        if in_battle and not flags.double_attacks:
            room.attacks_remaining = max(0, room.attacks_remaining) * 2
            flags.double_attacks = False      # 已当场消费，不再留给阶段转换
            emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining
            }, room=room.id)
            result.message = f'本回合攻击次数翻倍，当前攻击次数为{room.attacks_remaining}'
        else:
            flags.double_attacks = True
            result.message = '本回合攻击次数翻倍'

    elif card.name == '灵气复苏':
        # 计算双方最大船数，已修复
        max_ships = max(caster.remaining_ships, opponent.remaining_ships)
        if max_ships < 1:
            max_ships = 1

        # 存储临时数据，等待玩家选择船数
        room.magic_temp_data = {
            'type': 'lingqi_choice',
            'caster': caster_id,
            'opponent': opponent_id,
            'max_ships': max_ships
        }

        # 设置结果，只发送给施法者
        result.message = '请选择灵气复苏的船数'
        result.temp_data_id = 'lingqi_choice'
        result.max_ships = max_ships

        # 通知对手等待
        emit('lingqi_waiting', {
            'message': '对方正在结算灵气复苏效果 请等待'
        }, to=room.players[opponent_id].sid)
    
    elif card.name == '教皇旨意':
        # 场地魔法，攻击次数变为0，通过弃置魔法卡攻击
        _place_field_magic(room, caster_id, card)
        room.game_effects['papal_edict'] = True

        # ⚠️ 必须【在这里】立即归零，不能只依赖"进入战斗阶段"那一刻。
        # 教皇旨意是速阶1，而 can_play_magic_card 允许速阶1在【战斗阶段】使用 ——
        # 从战斗阶段打出时，enter_battle_phase 的阶段转换早已发生（或压根不再发生），
        # attacks_remaining 会一直停在旧值（实测：6），于是
        # handle_enter_end_phase 的 "还有剩余攻击次数" 门禁永远拒绝 → 对局卡死。
        room.attacks_remaining = 0
        emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining
        }, room=room.id)

        result['message'] = '教皇旨意已生效，双方攻击次数变为0，通过弃置魔法卡攻击对方两次'

    elif card.name == '败者食尘':
        # 卡面："立即重启正常对局但保留双方的手牌。
        #        败者食尘生效的大回合内双方的攻击次数都为0。"
        #
        # 「重启正常对局」= 双方棋盘清空、各回 6 艘重新摆放（作者确认）。
        # ⚠️ 原实现是【交换双方的船数】（caster.max_ships = opponent_ships），
        # 卡面里根本没有这回事 —— 实测玩家反馈"重置后船数不对"即源于此。
        # 这里改为双方一律重置为默认船数（6）。
        DEFAULT_SHIPS = 6
        # 双方棋盘都要换掉 → 除外船不再是这批棋盘上的船；**范围效果也要终止**
        _clear_board_effects(room, list(room.players), '败者食尘')
        # 跨回合计数效果一并终止（**在 game_effects 整体清空之前**：
        # 直接清空会让前端收不到清除事件，角标永远挂着）
        _clear_multiturn_effects(room, '败者食尘')
        for p_id in room.players:
            player = room.players[p_id]
            player.ships = []
            player.attacks = []
            player.remaining_ships = 0
            player.needs_reset = True
            player.revealed_positions = []
            player.max_ships = DEFAULT_SHIPS
            # 棋盘相关的一次性状态也清掉，避免上一局残留（冻结/无敌/护盾）
            player.sunken_ships = []
            if hasattr(player, 'opponent_attacks'):
                player.opponent_attacks = []
            for ship in list(getattr(player, 'ships', []) or []):
                ship.frozen = False
                ship.invincible = False
                ship.shield = False
                ship.trap = False

        # 冻结区域记录也一并清掉（重开棋盘后区域标记不该残留）
        if isinstance(room.game_effects, dict):
            room.game_effects.pop('frozen_area', None)

        # 只保留手牌 —— 场地魔法、生效中的效果、弃牌堆统统回到开局状态
        # （作者确认：「只保留手牌，其余全部重置」）
        room.field_magic = None
        room.field_magic_owner = None
        room.game_effects = {}
        room.magic_discard = []
        room.magic_temp_data = {}
        room.chain = []
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes = 0
        room.last_attack = None
        room.skip_opponent_turn = None
        # 双方的玩家级效果标记清零（EffectFlags 整个换新）
        for p_id in room.players:
            room.players[p_id].effect_flags = EffectFlags()
            room.players[p_id].magic_blocked = False

        # 与灵气复苏同样保存进度：重新摆放完成后回到原先后手与阶段，不重新猜拳。
        room.lingqi_saved_state = {
            'attack_order': list(room.attack_order),
            'current_attacker': room.current_attacker,
            'current_phase': room.current_phase,
            'round': room.round,
            'attacks_remaining': room.attacks_remaining,
        }
        # 复用灵气复苏的"摆放完成即恢复"分支
        room.lingqi_resurgence_applied = True

        room.state = 'placing_ships'
        # 卡面第二句：本大回合内双方攻击次数为 0。
        # 这里先置 0（摆放期间本就没有攻击），摆放完成回到攻击阶段时会再确认一次
        # （见 handle_place_ships 里的 polar_reversal_applied 分支）。
        room.attacks_remaining = 0
        room.polar_reversal_applied = True
        # ⚠️ 大回合级标记：上面 `room.game_effects = {}` 已经清过一次场，
        # 所以必须写在这一行【之后】。它让本大回合内**双方**的攻击次数恒为 0 ——
        # 只靠上面那个一次性标记的话，进战斗阶段时会被按船数重算成 6（实测缺陷）。
        room.game_effects['zero_attacks_round'] = room.round

        for p_id in room.players:
            player = room.players[p_id]
            emit('reset_gameboard', {
                'new_max_ships': player.max_ships,
                'message': '败者食尘生效，双方棋盘已重置为6艘，请重新摆放（手牌保留）'
            }, to=player.sid)

        result['message'] = '败者食尘生效：双方棋盘重置为6艘并重新摆放，手牌保留；本大回合双方攻击次数为0'
        # 立即返回：已清空双方战舰并重置为布船阶段，
        # 不能落入末尾"对手剩余船数<=0 则游戏结束"的兜底判断（会误判 game_over）
        return result

    # ==== 速阶2 魔法卡 ===
    elif card.name == '溅射':
        # 对击中格子的上下左右四格造成伤害
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack.get('hit'):
            result['success'] = False
            result['message'] = '必须在击中对方后使用'
            return result

        x, y = room.last_attack["x"], room.last_attack["y"]
        splash_positions = [
            {'x': x, 'y': y - 1},  # 上
            {'x': x, 'y': y + 1},  # 下
            {'x': x - 1, 'y': y},  # 左
            {'x': x + 1, 'y': y}  # 右
        ]

        # 过滤有效位置
        valid_positions = [p for p in splash_positions if 0 <= p['x'] < 6 and 0 <= p['y'] < 6]
        hit_count = 0
        ships_changed = False

        affected_positions = []
        for pos in valid_positions:
            # 检查是否击中
            hit = False
            ship_sunk = False
            for i, ship in enumerate(opponent.ships):
                if Position(**pos) in ship.positions and Position(**pos) not in ship.hits:
                    # 溅射伤害不受无敌影响（文本），但受护盾影响（护盾抵挡一次）
                    # 造成伤害：解除无暇圣心"双方未受伤"判定
                    if 'holy_heart' in room.game_effects:
                        room.game_effects['holy_heart']['no_damage'] = False
                    if ship.shield:
                        hit = True
                        ship.shield=False
                        ship_sunk = False
                    else:
                        hit = True
                        ship.hits.append(Position(**pos))
                        if len(ship.hits) == len(ship.positions):
                            ship_sunk = True
                            opponent.remaining_ships -= 1
                            ships_changed = True
                            # 记录本回合造成的伤害（五险一金/Freezing! 判定）
                            caster.damage_dealt_this_turn += 1

                            # 保存被击沉的船到sunken_ships
                            _mark_ship_sunken(opponent, ship)

                            # 平等条约快照 + 百亿补贴 + 无暇圣心中断（与普通攻击共用）
                            _on_ship_destroyed(room, opponent_id, ship, [Position(**pos)])

                            # 八方来财
                            _notify_treasure_hunter(room, 1)   # 魔法卡造成的变化：全场持卡者都摸

                            # 恶魔契约（由牺牲方自己点选，AI 自动）：
                            # 一次结算里多艘沉没时只请求一次。判据查**优先队列**（该玩家已有待选就跳过）；
                            # 队列内部也会按 player+reason 去重，这里是双保险。
                            if (room.game_effects.get('demon_contract')
                                    and not _my_ship_picks(room, _opponent_of(room, opponent_id))):
                                _request_demon_contract_sacrifice(room, opponent_id)
                                ships_changed = True

                            # 检查回光返照效果（统一走 helper：置状态 / 记日志 / 记战绩 / 广播）
                            # 注意必须返回 ChainResult：原实现返回普通 dict，
                            # resolve_chain 里对 result.caster 赋值会抛 AttributeError，
                            # 导致连锁不结算、残留连锁栈。
                            if _check_last_chance(room, caster_id, opponent_id):
                                result['game_over'] = True
                                return result
                    hit_count += 1
                    break

            # 记录攻击（包括未命中）
            caster.attacks.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'is_splash': True
            }))

            # 发送单点攻击结果，保持与普通攻击一致的 UI 更新
            attack_result = {
                'attacker': caster_id,
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'remaining_attacks': room.attacks_remaining,
                'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                'defender_remaining_ships': opponent.remaining_ships
            }
            emit('attack_result', attack_result, room=room.id)

            affected_positions.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk
            }))

        # 若有船只数量变化，广播更新
        if ships_changed:
            _emit_ships_updated(room)

        result['message'] = f'溅射攻击命中{hit_count}个目标'
        result['affected_positions'] = affected_positions
        result['caster_id'] = caster_id

    elif card.name == '雷达子弹':
        # 显示击中位置周围八格的战舰
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['hit']:
            result['success'] = False
            result['message'] = '必须在击中对方战舰后使用'
            return result
        affected_positions = []
        x, y = room.last_attack["x"], room.last_attack["y"]
        # 记录需要显示的位置
        new_positions = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0: continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < 6 and 0 <= ny < 6:
                    pos = {'x': nx, 'y': ny}
                    room.players[caster_id].revealed_positions.append(Position(**pos))
                    new_positions.append(pos)
        for pos in new_positions:
            # 检查是否击中
            hit = False
            ship_sunk = False
            for i, ship in enumerate(opponent.ships):
                if Position(**pos) in ship.positions and Position(**pos) not in ship.hits:
                    hit=True
            if hit:continue 
            # 记录攻击（包括未命中）
            caster.attacks.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'is_splash': True
            }))

            # 发送单点攻击结果，保持与普通攻击一致的 UI 更新
            attack_result = {
                'attacker': caster_id,
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'remaining_attacks': room.attacks_remaining,
                'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                'defender_remaining_ships': opponent.remaining_ships
            }
            emit('attack_result', attack_result, room=room.id)

            affected_positions.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk
            }))
        # 立即将被揭示的位置发送给触发方
        emit('revealed_positions', {'positions': new_positions}, to=room.players[caster_id].sid)
        result['message'] = '已扫描周围八格战舰位置'
        result['affected_positions'] = affected_positions

    elif card.name == '越战越勇':
        # 每击沉一艘战舰，攻击次数净增加1
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['ship_sunk']:
            result['success'] = False
            result['message'] = '必须在击沉对方战舰后立即使用'
            return result

        # 添加越战越勇效果标记（本大回合内每次击沉都再 +1）
        room.players[caster_id].effect_flags.battle_spirit = True

        # ⚠️ 发动前提就是"刚刚击沉了一艘"，所以那一艘的 +1 必须【当场结算】。
        # 旧实现只挂标记，要等下一发击沉才生效 —— 玩家实测报「打完这张牌攻击次数
        # 没有任何变化，以为卡没生效」，而卡面写的是「攻击次数净增加1」。
        gained = _grant_extra_attacks(room, caster_id, 1)
        if gained:
            result['message'] = (f'越战越勇生效：攻击次数 +{gained}'
                                 f'（当前 {room.attacks_remaining} 次），本大回合再击沉战舰还会 +1')
        else:
            result['message'] = '越战越勇生效，本回合击沉战舰时攻击次数净增加1'

    elif card.name == '神威！':
        # 选定己方/对方棋盘上的 3*3 区域：该区域从棋盘上“扣掉”，
        # 区域内战舰暂时除外，下一个大回合开始时回归原位、区域恢复。
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result

        area = target_data['target_area']
        board = target_data.get('board', 'opponent')  # 'self' | 'opponent'
        target_id = caster_id if board == 'self' else opponent_id
        target_player = room.players[target_id]

        # 收集并移除区域内的战舰
        excluded_ships = []
        for i in range(len(target_player.ships) - 1, -1, -1):
            ship = target_player.ships[i]
            in_area = any(
                area['x1'] <= pos.x <= area['x2'] and
                area['y1'] <= pos.y <= area['y2']
                for pos in ship.positions
            )
            if in_area:
                excluded_ships.append(ship)
                del target_player.ships[i]
                target_player.remaining_ships -= 1

        # 把这片区域从棋盘上扣掉（下个大回合恢复）
        return_turn = room.round + 1
        _add_shenwei_hole(room, target_id, area, return_turn)
        emit('shenwei_hole', {
            'player': target_id, 'area': area, 'return_turn': return_turn
        }, room=room.id)

        # 卡面：仅当作用于对方棋盘且区域内恰好 1 艘船时，直接死亡
        if board != 'self' and len(excluded_ships) == 1:
            _mark_ship_sunken(target_player, excluded_ships[0])
            _apply_ship_loss_linkage(room, caster_id, opponent_id, count=1)
            result['message'] = '目标区域内1艘战舰被击沉'
        else:
            room.game_effects.setdefault('excluded_ships', []).append({
                'ships': excluded_ships,
                'player': target_id,
                'return_turn': return_turn,
            })
            if excluded_ships:
                _apply_ship_loss_linkage(room, caster_id, target_id,
                                         count=len(excluded_ships))
            result['message'] = f'目标区域内{len(excluded_ships)}艘战舰被暂时除外'

        _emit_ships_updated(room)

        # 斩杀线：对方船被清空直接获胜；己方自扣清空则判负
        if opponent.remaining_ships <= 0 and room.state != 'game_over':
            _finish_game(room, caster_id, opponent_id, '神威！清空对方棋盘')
            result['message'] += '，对方战舰全灭，直接获胜'
        elif caster.remaining_ships <= 0 and room.state != 'game_over':
            _finish_game(room, opponent_id, caster_id, '神威！清空己方棋盘')
            result['message'] += '，己方战舰全灭，判负'

    elif card.name == '冻结':
        # 冻结3*3区域内的船，使其无法攻击
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result

        area = target_data['target_area']
        frozen_count = 0

        # 标记区域内的战舰
        for ship in opponent.ships:
            # 已沉没的船不参与冻结（2026-09-17）：
            #   · 它本来就不提供攻击次数，算进 frozen_count 只会让播报数字虚高
            #     （实测玩家报「冻结的战舰数目居然会把已经死亡的战舰加进去」）；
            #   · 给它打上 frozen 标记也没意义，反而会在被复活后带着旧标记回来。
            if not _is_ship_alive(opponent, ship):
                continue
            in_area = any(
                area['x1'] <= pos.x <= area['x2'] and
                area['y1'] <= pos.y <= area['y2']
                for pos in ship.positions
            )

            if in_area and getattr(ship, 'frozen', None) is None:
                ship.frozen = room.round + 1  # 冻结到下一回合
                frozen_count += 1

        if frozen_count:
            # 立刻把「哪几艘被冻住了」同步给被冻结的一方（画在ta自己的棋盘上）
            _emit_player_ships(room, opponent_id)
        result['message'] = f'冻结了{frozen_count}艘战舰'

        # ★ 记录"冻的是哪片 3×3 区域"并**下发给双方**（2026-09-16）。
        # 作者实测：施法方原先什么都收不到（上面那个 _emit_player_ships 只发受害者），
        # 过一会儿就忘了自己冻的是哪片；受害者也只看到自己的船上有雪花、看不出区域边界。
        # 区域属于【受害者棋盘】，所以带 owner 让前端按归属决定画在哪块棋盘上
        # （与 last_stand_cells 同一套归属模式）。
        # ⚠️ 即便一艘都没冻住也照发：那片区域是公开信息（双方都看到了选区），
        # 前端会按 frozen 数量决定怎么描述。
        room.game_effects['frozen_area'] = {
            'x1': int(area['x1']), 'y1': int(area['y1']),
            'x2': int(area['x2']), 'y2': int(area['y2']),
            'owner': opponent_id,        # 这片区域在哪块棋盘上（受害者）
            'caster': caster_id,         # 谁冻的
            'frozen': frozen_count,
            'until_round': room.round + 1,
        }
        emit('frozen_area', dict(room.game_effects['frozen_area']), room=room.id)


    elif card.name == '轰炸':
        # 选定一行或一列进行轰炸
        if 'target_line' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标行或列'
            return result

        line = target_data['target_line']
        # 检查是行还是列
        if line["type"] == 'row':
            positions = [{'x': x, 'y': line['index']} for x in range(6)]
        else:
            positions = [{'x': line['index'], 'y': y} for y in range(6)]

        # 找出所有与该行/列相交的船只，整艘摧毁
        to_remove = [ship for ship in opponent.ships if len(ship.hits) < len(ship.positions) and any(pos in ship.positions for pos in positions)]
        sunk_count = 0
        ships_changed = False
        removed_positions = set()

        # 移除受影响的船只，并为其所有格子生成命中事件
        for ship in to_remove:
            if ship in opponent.ships:
                # 保存被摧毁的船到sunken_ships
                _mark_ship_sunken(opponent, ship)
                opponent.ships.remove(ship)
                opponent.remaining_ships -= 1
                ships_changed = True
                sunk_count += 1
                # 记录本回合伤害（五险一金/Freezing!）
                caster.damage_dealt_this_turn += 1

                # 平等条约快照 + 百亿补贴 + 无暇圣心中断（与普通攻击共用）
                _on_ship_destroyed(room, opponent_id, ship)

                # 恶魔契约：一次结算里多艘沉没时只请求一次
                # （判据查**优先队列**：该玩家已有待选就跳过；队列内部也会按
                #   player+reason 去重，这里是双保险）
                if (room.game_effects.get('demon_contract')
                        and not _my_ship_picks(room, _opponent_of(room, opponent_id))):
                    _request_demon_contract_sacrifice(room, opponent_id)
                    ships_changed = True

                # 八方来财
                _notify_treasure_hunter(room, 1)   # 魔法卡造成的变化：全场持卡者都摸
                for ship_pos in ship.positions:
                    removed_positions.add((ship_pos.x, ship_pos.y))
                    caster.attacks.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'is_bomb': True
                    }))
                    attack_result = {
                        'attacker': caster_id,
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                        'defender_remaining_ships': opponent.remaining_ships
                    }
                    emit('attack_result', attack_result, room=room.id)

        # 对于该行/列中未命中的格子也发出未命中事件，以保持 UI 一致性
        for pos in positions:
            if (pos['x'], pos['y']) not in removed_positions:
                caster.attacks.append(Position(**{
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': False,
                    'ship_sunk': False,
                    'is_bomb': True
                }))
                attack_result = {
                    'attacker': caster_id,
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': False,
                    'ship_sunk': False,
                    'remaining_attacks': room.attacks_remaining,
                    'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                    'defender_remaining_ships': opponent.remaining_ships
                }
                emit('attack_result', attack_result, room=room.id)

        # 若有船只数量变化，广播更新
        if ships_changed:
            _emit_ships_updated(room)

        result['message'] = f'轰炸成功击沉{sunk_count}艘战舰'

    elif card.name == '硫磺火焰':
        # 对选定的连续6格释放硫磺火焰，强制击杀这些格子上所属的所有战舰（无视护盾/无敌）
        if 'target_cells' not in target_data:
            result['success'] = False
            result['message'] = '需要选择6个连续的目标格子'
            return result
        positions = target_data['target_cells']
        if not isinstance(positions, list) or len(positions) != 6:
            result['success'] = False
            result['message'] = '需要选择恰好6个连续的格子'
            return result

        # 找出所有与这些格子相交的船只，并整艘摧毁
        to_remove = [ship for ship in opponent.ships if len(ship.hits) < len(ship.positions) and any(pos in ship.positions for pos in positions)]
        sunk_count = 0
        ships_changed = False
        removed_positions = set()
        affected_positions: list[Position] = []
        for ship in to_remove:
            if ship in opponent.ships:
                # 保存被摧毁的船到sunken_ships
                _mark_ship_sunken(opponent, ship)
                opponent.ships.remove(ship)
                opponent.remaining_ships -= 1
                ships_changed = True
                sunk_count += 1
                # 记录本回合伤害（五险一金/Freezing!）
                caster.damage_dealt_this_turn += 1

                # 八方来财: 战舰数目变化时抽一张牌
                _notify_treasure_hunter(room, 1)   # 魔法卡造成的变化：全场持卡者都摸

                # 平等条约快照 + 百亿补贴 + 无暇圣心中断（与普通攻击共用）
                _on_ship_destroyed(room, opponent_id, ship)

                # 恶魔契约：一次结算里多艘沉没时只请求一次
                # （判据查**优先队列**：该玩家已有待选就跳过；队列内部也会按
                #   player+reason 去重，这里是双保险）
                if (room.game_effects.get('demon_contract')
                        and not _my_ship_picks(room, _opponent_of(room, opponent_id))):
                    _request_demon_contract_sacrifice(room, opponent_id)
                    ships_changed = True
                for ship_pos in ship.positions:
                    removed_positions.add((ship_pos.x, ship_pos.y))
                    caster.attacks.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'is_sulfur': True
                    }))
                    attack_result = {
                        'attacker': caster_id,
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                        'defender_remaining_ships': opponent.remaining_ships
                    }
                    emit('attack_result', attack_result, room=room.id)
                    affected_positions.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True
                    }))

        # 对于选定格子中未命中的格子，发送未命中事件
        for pos in positions:
            if (pos["x"], pos["y"]) not in removed_positions:
                caster.attacks.append(Position(**{
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False,
                    'is_sulfur': True
                }))
                attack_result = {
                    'attacker': caster_id,
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False,
                    'remaining_attacks': room.attacks_remaining,
                    'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                    'defender_remaining_ships': opponent.remaining_ships
                }
                emit('attack_result', attack_result, room=room.id)
                affected_positions.append(Position(**{
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False
                }))

        # 广播被摧毁舰只更新
        if ships_changed:
            _emit_ships_updated(room)

        result['message'] = f'硫磺火焰成功击杀{sunk_count}艘战舰'
        result['affected_positions'] = affected_positions
        result['caster_id'] = caster_id
        
        # 添加游戏日志
        add_game_log(room, f"第{room.round}回合 · {_log_name(room, caster_id)} 使用了【硫磺火焰】，击杀了{sunk_count}艘战舰", 'magic', {
            'caster_id': caster_id,
            'card_name': card.name,
            'sunk_count': sunk_count,
            'affected_positions': affected_positions
        })

    elif card.name == '探测雷达':
        # 显示2*2区域内的战舰
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result

        area = target_data['target_area']
        positions = []
        room.players[caster_id].revealed_positions = room.players[caster_id].revealed_positions
        affected_positions = []
        # 添加需要显示的位置
        for y in range(area['y1'], area['y2'] + 1):
            for x in range(area['x1'], area['x2'] + 1):
                pos = {'x': x, 'y': y}
                room.players[caster_id].revealed_positions.append(Position(**pos))
                positions.append(pos)
        for pos in positions:
            # 检查是否击中
            hit = False
            ship_sunk = False
            for i, ship in enumerate(opponent.ships):
                if Position(**pos) in ship.positions and Position(**pos) not in ship.hits:
                    hit=True
            if hit:continue 
            # 记录攻击（包括未命中）
            caster.attacks.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'is_splash': True
            }))

            # 发送单点攻击结果，保持与普通攻击一致的 UI 更新
            attack_result = {
                'attacker': caster_id,
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'remaining_attacks': room.attacks_remaining,
                'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                'defender_remaining_ships': opponent.remaining_ships
            }
            emit('attack_result', attack_result, room=room.id)

            affected_positions.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk
            }))
        # 立即发送给触发者
        emit('revealed_positions', {'positions': positions}, to=room.players[caster_id].sid)
        result['message'] = '已探测目标区域战舰位置'
        result['affected_positions'] = affected_positions

    elif card.name == '饮血':
        # 卡面："可在击中对方后选择使用" —— 发动前提是自己上一次攻击【击沉了一艘船】。
        #
        # ⚠️ 判定依据必须是 last_attack['ship_sunk'] 而不是 ['hit']：
        #   hit 只说明那一格有船，ship_sunk 才是"击杀"。
        #   卡面后半句是"接下来每击杀一艘船抽一张牌"，拿 hit 当门槛会让玩家
        #   打中一艘没沉的船就以为能发动，实际摸不到牌。
        last = getattr(room, 'last_attack', None) or {}
        if not (last.get('attacker') == caster_id and last.get('ship_sunk')):
            result['success'] = False
            result['message'] = '需要在击沉对方一艘战舰后才能使用'
            return result

        room.players[caster_id].effect_flags.vampire = True

        # 刚打完的那一发「补算」：饮血是在击沉之后才打出的，若只对以后生效，
        # 玩家会觉得自己刚打沉的那艘白沉了。这里立即补摸一张。
        # （每张饮血只补一次 —— 它记录的就是"发动时那一次击沉"。）
        room.draw_card(caster_id)
        emit('message', {'text': '饮血发动，立即抽一张卡'}, to=room.players[caster_id].sid)
        result['message'] = '饮血生效：已为刚才击沉的战舰抽一张牌，接下来每击杀一艘船再抽一张。'

    elif card.name == '克苏鲁之眼':
        # 双方各暴露一艘船。施法者必须点选一艘【自己的船】所在格，不能选空格。
        if not caster.ships or not opponent.ships:
            result['success'] = False
            result['message'] = '双方都必须有战舰才能使用'
            return result

        cell = _pick_cell_from_target(target_data)
        if cell is None:
            result['success'] = False
            result['message'] = '请选择一艘自己的战舰'
            return result

        caster_ship = _find_ship_at(caster, cell, alive_only=True)
        if caster_ship is None:
            result['success'] = False
            result['message'] = '必须选择自己【还活着】的战舰所在的格子（已沉没的船不能选）'
            return result

        caster_positions = caster_ship.positions
        # 先把自己的位置暴露给对方
        room.players[opponent_id].revealed_positions.extend(caster_positions)
        emit('revealed_positions', {'positions': caster_positions}, to=room.players[opponent_id].sid)

        # 卡面：然后【对方也选择一艘船】暴露位置（AI 由服务端代选）
        picked = _request_ship_pick(
            room, opponent_id, 'kraken_eye',
            '克苏鲁之眼生效：请点选一艘自己的战舰暴露位置')
        opponent_positions = picked.positions if picked is not None else []
        if picked is not None:
            room.players[caster_id].revealed_positions.extend(picked.positions)
            emit('revealed_positions', {'positions': picked.positions}, to=room.players[caster_id].sid)
        emit('revealed_positions', {'positions': caster_positions}, to=room.players[opponent_id].sid)

        result['message'] = '双方各暴露一艘战舰位置'

    elif card.name == 'Freezing！':
        # 发动条件（三条缺一不可）：
        #   1. 自己先手（attack_order[0]）
        #   2. 当前是结束阶段
        #   3. 本回合没有让对方船数减少
        if room.attack_order and room.attack_order[0] != caster_id:
            result['success'] = False
            result['message'] = 'Freezing！只能在自己先手的回合发动'
            return result

        if room.current_phase != 'end':
            result['success'] = False
            result['message'] = 'Freezing！只能在结束阶段发动'
            return result

        # damage_dealt_this_turn 只在击沉对方战舰时累加，等价于「让对方船数减少」
        if caster.damage_dealt_this_turn > 0:
            result['success'] = False
            result['message'] = '本回合已使对方船数减少，无法发动 Freezing！'
            return result

        # 跳过对方本回合的所有阶段
        room.skip_opponent_turn = opponent_id
        result['message'] = 'Freezing！生效，跳过对方本回合的所有阶段'

    elif card.name == '五险一金':
        # 教皇旨意生效中本回合任何人都没有攻击次数（场地规则），这张牌一次都触发不了，
        # 直接拒绝出牌，别让它白白浪费。
        if field_magic_name(room) == '教皇旨意':
            result['success'] = False
            result['message'] = '教皇旨意生效中，本回合攻击次数为0，五险一金无法发动'
            return result

        # 本回合已经让对方减过船 → 这张牌无论如何都不会再触发了，直接拒绝，别浪费一张卡
        if caster.damage_dealt_this_turn > 0:
            result['success'] = False
            result['message'] = '本回合已造成伤害，无法发动'
            return result

        # 只「挂上保险」：真正的 +3 要等本回合攻击次数第一次归零时才结算，
        # 不是一打出就白送 3 次（见 _maybe_trigger_wuxian_yijin）。
        caster.effect_flags.wuxian = True
        if _maybe_trigger_wuxian_yijin(room, caster_id):
            # 出牌时攻击次数本来就已是 0：条件当场成立
            result['message'] = '攻击次数已用尽且未造成伤害，攻击次数 +3'
        else:
            result['message'] = '五险一金已生效：用完本回合所有攻击次数且未造成伤害时，攻击次数 +3'

    elif card.name == '明智埋葬':
        # 埋葬对象 = 牌堆中的卡 + 对方手牌（可埋葬对方手里的牌）
        deck = room.magic_deck or []
        opp_hand = opponent.magic_hand or []
        if not deck and not opp_hand:
            result['success'] = False
            result['message'] = '牌堆与对方手牌均为空，无法发动'
            return result

        # 候选池：先牌堆，后对方手牌（扁平下标 = 前端展示顺序）。
        # 只存纯数据、不存 MagicCard 实例：magic_temp_data 会被
        # get_magic_temp_data 原样 emit，实例无法 JSON 序列化。
        candidates = []
        for source, pile in (('deck', deck), ('opponent_hand', opp_hand)):
            for i, c in enumerate(pile):
                candidates.append({
                    'source': source, 'index': i, 'name': c.name, 'speed': c.speed,
                    'type': c.type, 'description': c.description,
                })

        room.magic_temp_data = {
            'type': 'bury_choice',
            'caster': caster_id,
            'candidates': candidates,
        }
        # index 是该卡在自己来源列表内的下标，前端回传 source_index 用它精确定位
        result['cards'] = [dict(c) for c in candidates]
        result['message'] = '请选择要埋葬的卡牌（牌堆或对方手牌）'
        result['temp_data_id'] = 'bury_choice'

    elif card.name == '仁王之盾':
        # 选择至多3艘船进入盾牌状态
        if caster.remaining_ships == 0:
            result['success'] = False
            result['message'] = '没有战舰可保护'
            return result

        # 记录需要选择的船
        # ⚠️ 这里**不能**改成 `pending_ship_picks` 的选船请求：仁王之盾是"至多 3 艘"
        #    的**多选**（走 `select_magic_target` 的 ship_indices），与
        #    "点一艘船"的 `confirm_sacrifice` 不是同一种交互。
        #    但仍然要在**优先级队列**里登记一条，理由：
        #      · 它同样会占用棋盘选区（前端 `selectingOnBoard`）；
        #      · 别的选船效果要能看到"这个人手上有优先级 40 的选船待办"。
        #    消费点在 `shield_choice` 的确认分支与 `cancel_magic_selection`。
        room.magic_temp_data = {
            'type': 'shield_choice',
            'caster': caster_id,
            'ships': caster.ships
        }
        _register_simple_ship_pick(room, caster_id, 'shield_choice',
                                   '仁王之盾：请选择要保护的战舰（至多 3 艘）')
        result['message'] = '请选择要保护的战舰'
        result['temp_data_id'] = 'shield_choice'

    # ==== 速阶3 魔法卡 ====
    elif card.name == '八方来财':
        # 战舰数目主动变化时抽一张牌
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.treasure_hunter = True
        result['message'] = '战舰数目变化时抽一张牌'

    elif card.name == '平等条约':
        # 船数改变时无效化导致改变的【魔法卡】（攻击造成的不在此列）
        if 'last_ship_change' not in room.game_effects:
            result['success'] = False
            result['message'] = '没有可无效化的船数改变效果'
            return result

        # 卡面"立即发动"：超过本大回合的快照不允许回滚
        # （原先无过期点，第 9 回合还能回滚第 1 回合的击沉）
        if room.game_effects['last_ship_change'].get('round', room.round) != room.round:
            room.game_effects.pop('last_ship_change', None)
            result['success'] = False
            result['message'] = '船数改变发生在上一个大回合，无法再无效化'
            return result

        # 卡面只允许无效化【魔法卡】造成的船数改变；普通炮击/教皇旨意造成的击沉
        # 无法被无效化。这里必须保留快照（不能 pop）—— 否则接着摸到一张魔法卡
        # 造成船数变化时，玩家会因为快照被提前消费而莫名其妙地无效化不了。
        if room.game_effects['last_ship_change'].get('source') == 'attack':
            result['success'] = False
            result['message'] = '平等条约只能无效化魔法卡造成的船数减少，无法无效化炮击造成的击沉'
            return result

        # 无效化最后一次船数改变
        last_change = room.game_effects.pop('last_ship_change')
        # 恢复船数和被移除的ship
        affected_player_id = last_change['player']
        affected_player = room.players[affected_player_id]
        count = last_change['count']
        affected_player.remaining_ships += count

        # 完全回滚: 把ship重新加回列表，从sunken_ships中移除（防重复：击沉时船仍留在ships中）
        if 'ship' in last_change and last_change['ship'] is not None:
            if last_change['ship'] not in affected_player.ships:
                affected_player.ships.append(last_change['ship'])
            # 从sunken_ships中移除
            if last_change['ship'] in affected_player.sunken_ships:
                affected_player.sunken_ships.remove(last_change['ship'])
            # 撤销本次击沉：移除击中格，避免回滚后成为打不死的幽灵船
            for h in last_change.get('hits_added', []):
                if h in last_change['ship'].hits:
                    last_change['ship'].hits.remove(h)

        # 回滚连带撤销百亿补贴为这次击沉发放的 +3
        if last_change.get('subsidy_granted'):
            flags = affected_player.effect_flags
            flags.subsidy_bonus = max(0, int(getattr(flags, 'subsidy_bonus', 0) or 0) - 3)

        # 广播更新
        _emit_ships_updated(room)

        result['message'] = '成功无效化船数改变效果'

    elif card.name == '百亿补贴':
        # 船被击败时攻击次数加3
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.subsidy = True
        result['message'] = '船被击败时攻击次数加3'

    elif card.name == '神之宣告':
        # 牺牲两艘船，选择一个效果。
        # ⚠️ 判据是 **<= 2**（即需要 3 艘以上），不是 `< 2`（作者 2026-09-19 明确要求）：
        #    牺牲两艘之后至少得留一艘 —— 否则"打出这张牌"等于把自己送到 0 艘，
        #    紧接着就被判负，那不是玩家想要的取舍。
        if caster.remaining_ships <= 2:
            result['success'] = False
            result['message'] = '您的船数不足，无法使用神之宣告'
            return result

        # 牺牲两艘船：优先采用玩家点选的两艘（前端 own_ships → selected_cells），
        # 非法/不足时用随机补齐（AI 与老客户端仍可出牌）。
        chosen = []
        cells = target_data.get('selected_cells') if isinstance(target_data, dict) else None
        if isinstance(cells, list):
            for c in cells:
                try:
                    pos = (int(c.get('x')), int(c.get('y')))
                except (AttributeError, TypeError, ValueError):
                    continue
                # alive_only：点到沉船的格子不算数（否则牺牲变成零代价）
                ship_at = _find_ship_at(caster, pos, alive_only=True)
                if ship_at is not None and ship_at not in chosen:
                    chosen.append(ship_at)
        if len(chosen) < 2:
            # 只从"还活着"的船里补：已沉的船在 ships 里仍占位，不排除会把
            # 牺牲变成零代价（沉船堆还会出现重复条目）
            pool = [s for s in _alive_ships(caster) if s not in chosen]
            random.shuffle(pool)
            chosen.extend(pool[:2 - len(chosen)])
        if len(chosen) < 2:
            result['success'] = False
            result['message'] = '您的船数不足，无法使用神之宣告'
            return result

        # 逐个走统一结算：移船 + 记日志 + 公开广播 ship_sacrificed + 按视角刷船数。
        # 以前这里是自己 remove/append 就完事，结果对方完全看不到这两艘船沉了。
        for sacr in chosen[:2]:
            _do_demon_contract_sacrifice(room, caster_id, sacr, 'divine_decree')

        # 获取选择的效果：优先采用出牌时携带的 effect_choice（前端出牌前选择），
        # 其次回退到临时数据，缺省为 1（摧毁对方一艘战舰）。
        if isinstance(target_data, dict) and target_data.get('effect_choice'):
            try:
                effect_choice = int(target_data['effect_choice'])
            except (TypeError, ValueError):
                effect_choice = 1
        else:
            try:
                effect_choice = int(room.magic_temp_data.get('effect_choice', 1))
            except (TypeError, ValueError):
                effect_choice = 1
        if effect_choice == 1:
            # 卡面：让对方【自己选择】一艘船使其死亡（AI 由服务端代选）
            picked = _request_ship_pick(
                room, opponent_id, 'divine_decree',
                '神之宣告生效：请点选一艘自己的战舰，使其阵亡')
            if picked is not None:
                _do_demon_contract_sacrifice(room, opponent_id, picked, 'divine_decree')
                result['message'] = '牺牲两艘战舰，对方一艘战舰被摧毁'
            else:
                result['message'] = '牺牲两艘战舰，等待对方选择阵亡的战舰'
        else:
            # 跳过对方**本大回合内**的所有阶段（存玩家ID）。
            # ⚠️ 用 `skip_opponent_stages` 而**不是** `skip_opponent_turn`：
            #    后者是 Freezing！ 的标记，它跳完会**直接翻页**（重新猜拳 + 发牌）。
            #    卡面写的是"跳过这一个大回合内对方的所有阶段" —— **不含翻页**。
            #    两者混用会让神之宣告白送一次状态重置（作者实测反馈的
            #    "效果二疑似没实现"根因就在这，它做的不是卡面承诺的事）。
            room.skip_opponent_stages = opponent_id
            result['message'] = '牺牲两艘战舰，跳过对方本回合所有阶段'

    elif card.name == '绝处逢生':
        # 卡面：牺牲自己所有的战舰，然后在"所有原本有战舰的地方"选一格，
        # 放置唯一一艘战舰；此后击杀对方任何一艘船直接获胜。
        if caster.remaining_ships < 3:
            result['success'] = False
            result['message'] = '需要至少3艘战舰才能发动'
            return result

        # 只取【活船】：沉船还留在 caster.ships 里，把它们也算进"牺牲"会重复入堆，
        # 复活类卡牌据此会把已经沉掉的船再恢复一次。
        sacrificed = _alive_ships(caster)
        original_cells = [(p.x, p.y) for sh in sacrificed for p in sh.positions]

        # 牺牲 = 走完整击沉流程，不再"凭空消失"：
        #   ① 从 caster.ships 移入 caster.sunken_ships（供复活类回收）
        #   ② 置满命中，让"这艘船已经没了"在双方棋盘与 _is_ship_alive 上口径一致
        #   ③ 触发击沉通用副作用（平等条约快照 / 无瑕圣心中断 / 百亿补贴 / 八方来财 / 恶魔契约）
        #
        # ⚠️ 通用副作用只结算【一次】，不能逐艘调 _on_ship_destroyed ——
        # 那会把 last_ship_change 快照反复覆盖、并触发 N 次无瑕圣心中断与 N 次恶魔契约。
        for sh in sacrificed:
            sh.hits = list(sh.positions)  # 满命中 = 已沉
            if sh in caster.ships:
                caster.ships.remove(sh)
            if sh not in caster.sunken_ships:
                _mark_ship_sunken(caster, sh)
        caster.remaining_ships = 0

        # ⚠️ 绝处逢生同样是"重摆自己棋盘"（全部牺牲 + 只放 1 艘）：这里也得终止
        #    自己棋盘上的范围效果与除外船 —— 少这一句，除外的船到期会 append 回来
        #    变成幽灵船（本项目实测过 6 艘变 8 艘）。
        _clear_board_effects(room, [caster_id], '绝处逢生')

        if sacrificed:
            # source='sacrifice'：这是自己牺牲、不是被对方打沉的。平等条约只允许
            # 无效化【魔法卡造成】的船数变化，绝处逢生的自牺牲不在此列。
            #
            # ⚠️ 顺序要紧：**先**走击沉结算，**再**清跨回合效果。
            #    `_on_ship_destroyed` 会用 `holy_heart_interrupted`（"因船被沉而中断"）
            #    这个**更具体**的原因清掉无暇圣心；若我们先清，那条路径就什么都找不到，
            #    玩家看到的原因从"有船被击沉"退化成"棋盘被重摆"——语义变糊，
            #    而且 `tests/test_last_stand_and_steal_fix.py` 钉的就是前者。
            #    所以下面那句 `_clear_multiturn_effects` 必须排在击沉结算**之后**
            #    （它负责兜住"没被击沉路径清掉"的那些，比如玩家没牺牲任何船的情况）。
            _on_ship_destroyed(room, caster_id, sacrificed[-1], source='sacrifice')
            # 逐艘公开广播，让双方棋盘都画出"这艘船没了"，而不是无声消失
            for sh in sacrificed:
                emit('ship_sacrificed', {
                    'player': caster_id,
                    'positions': [{'x': p.x, 'y': p.y} for p in sh.positions],
                    'reason': 'last_stand',
                }, room=room.id)
            _emit_ships_updated(room)
            _emit_player_ships(room, caster_id)

        # ⚠️ 兜底清理排在这里（击沉结算**之后**）：被 `holy_heart_interrupted`
        #    处理掉的不再重复，没被处理掉的（比如本局没牺牲任何船）由这里收口。
        #    跨回合计数效果是**房间级**的（记的是"再过几回合谁获胜"），
        #    绝处逢生虽只重摆自己的棋盘，也必须终止它们。
        _clear_multiturn_effects(room, '绝处逢生')

        # 神机妙算按"沉船差值"判定，牺牲不是被击沉，需同步快照避免误判
        snap = room.game_effects.get(f'prediction_initial_{caster_id}')
        if isinstance(snap, dict):
            snap['sunken'] = len(caster.sunken_ships)

        room.game_effects['last_stand_cells'] = original_cells
        # ⚠️ 必须记下这批候选格是【谁棋盘上的】。两块棋盘各有自己的 0-5 坐标，
        # 不下发归属的话前端无从判断该高亮哪块 —— 实测（2026-09-16 作者反馈）
        # 施法者自己放绝处逢生时，他那几个候选格被画到了**对手棋盘**上，
        # 看着像"敌方可能在这儿"，直接误导他自己的攻击。
        room.game_effects['last_stand_owner'] = caster_id
        # 把"原本有战舰的格子"公开给双方 —— 对方要据此知道唯一一艘新船可能在哪，
        # 而且这些格子必须【能打】。
        #
        # ⚠️ 以前这里只发 ship_sacrificed（reason='last_stand'），前端把它当成
        # 「牺牲的船」画成红叉 —— 而红叉在玩家眼里就是"已打过、别再点了"，
        # 结果对方看着六个叉子根本不知道能打哪儿、也以为打不了（作者实测反馈）。
        # 现在改成下发一份"候选格"名单，前端画成高亮而不是叉。
        cells_payload = [{'x': cx, 'y': cy} for (cx, cy) in original_cells]
        emit('last_stand_cells', {'cells': cells_payload, 'owner': caster_id}, room=room.id)
        # 生效回合内其余魔法卡无效 + 击杀任何船直接获胜
        # ⚠️ 两个标记生命周期不同，别合并：
        #   last_stand     —— 锁卡，换小回合就被清（卡面写的是"在……生效的回合"）
        #   last_stand_win —— 击杀即胜，作者裁定"接下来所有回合"都有效，活到对局结束
        caster.effect_flags.last_stand = True
        caster.effect_flags.last_stand_win = True
        # 角标要在发动当场就亮起来。这里没有走"裁剪返回 True 才发"的那条路
        # （新标记是直接赋值的），所以得显式广播一次。
        _emit_active_effects(room)
        _start_placement(room, caster_id, 'last_stand', 1)
        result.temp_data_id = 'last_stand_choice'
        result['message'] = '已牺牲全部战舰，请在所有原本有战舰的格子上选择一格放置唯一一艘战舰'

    elif card.name == '死者苏生':
        # 复活一艘船：必须有已阵亡的战舰，否则不可用。
        # 没有"6 艘上限"（作者确认：船数只受棋盘格数限制）。
        if not caster.sunken_ships:
            result['success'] = False
            result['message'] = '没有可复活的战舰'
            return result

        _start_placement(room, caster_id, 'revive', 1)
        result.temp_data_id = 'revive_choice'
        result['message'] = '请选择复活战舰的部署位置（未被攻击过的空格）'

    elif card.name == '疗愈':
        # 复活至多两艘被击杀的船（原地复活）。
        # 没有"6 艘上限"（作者确认：船数只受棋盘格数限制）。
        if not caster.sunken_ships:
            result['success'] = False
            result['message'] = '没有可复活的战舰'
            return result

        # 卡面："选定自己至多两艘被击杀的船并将他们在原地复活。"
        # 原先走的是"选一个未打过的空格"的放置流程，与卡面不符。
        count = min(2, len(caster.sunken_ships))
        # reveal_to=对手：疗愈是【原地复活】，那些格子的位置对方本来就知道
        # （是他打沉的），显形只是防止他忘记、不是泄露新信息（作者 2026-09-16 要求）
        revived = _revive_sunken_ships(room, caster, count, reveal_to=_opponent_of(room, caster_id))
        _emit_ships_updated(room)
        _emit_player_ships(room, caster_id)
        result['message'] = f'疗愈生效，{revived} 艘战舰在原地复活'

    elif card.name == '盗亦有道':
        # 卡面：立即获取对方打出的上一张魔法卡。
        #
        # ⚠️ 不能在连锁里读 room.magic_history：连锁是 LIFO（后发先至）结算，
        # 盗亦有道先出栈时，它要偷的那张对手的牌【还没轮到结算、自然还没写进历史】，
        # 于是恒报「对方没有使用过魔法卡」。这与失灵！当初康不到目标是同一个病灶，
        # 修法也一致 —— 读【连锁栈】而不是读历史。
        # 结算中当前项已出栈，故 chain[-1] 即"紧邻下方那一项"（下一个待结算项）。
        stolen_card = None
        stolen_entry = None
        stolen_from_chain = False

        target = room.chain[-1] if room.chain else None
        if target is not None and target.player_id != caster_id:
            # 连锁内：偷栈上紧邻的下方那一项
            stolen_card = target.card
            stolen_from_chain = True
        else:
            # 非连锁（对手的牌已结算完）或栈顶是自己：回退到全局历史里对方最近的一张
            for entry in reversed(room.magic_history):
                if entry['caster'] != caster_id and not entry.get('negated_skip'):
                    stolen_entry = entry
                    stolen_card = entry['card']
                    break

        if stolen_card is None:
            result['success'] = False
            result['message'] = '对方没有使用过魔法卡'
            return result

        # 同一条历史只能被偷一次，否则可反复盗取同一张卡造成卡牌增殖
        if stolen_entry is not None and stolen_entry.get('stolen'):
            result['success'] = False
            result['message'] = '该魔法卡已被盗取过'
            return result

        # 连锁内偷到的牌【还没结算】，此刻不可能有历史条目可标记。把"这张牌已被盗取"
        # 记在房间级台账里，等 resolve_chain 真正结算它、写入历史时再合并进去。
        # （不能在这里往 magic_history 塞占位条目 —— 那会让同一张牌出现两条记录，
        #   回退分支扫到没标记的那条就会重复盗取，等于凭空造牌。）
        ledger = room.game_effects.setdefault('stolen_cards', {})
        if id(stolen_card) in ledger:
            result['success'] = False
            result['message'] = '该魔法卡已被盗取过'
            return result

        # 从弃牌堆中移除对应卡牌，保证是"转移"而非"复制"
        # （非场地卡在出牌时即进入弃牌堆，不移除会出现弃牌堆与手牌同时存在的副本）
        for i, c in enumerate(room.magic_discard):
            if c is stolen_card or (c.name == stolen_card.name and c.speed == stolen_card.speed):
                room.magic_discard.pop(i)
                break

        if stolen_from_chain:
            ledger[id(stolen_card)] = True
        else:
            stolen_entry['stolen'] = True

        caster.magic_hand.append(stolen_card)

        result['message'] = f'成功盗取对方的{stolen_card.name}'

    elif card.name == '回光返照':
        # 只能在自己先手时发动
        if room.attack_order and room.attack_order[0] != caster_id:
            result['success'] = False
            result['message'] = '只能在自己先手时发动'
            return result

        # 清空棋盘重新摆放6艘船
        # 棋盘换新 → 除外船不再是这批棋盘上的船；**范围效果也要终止**
        # ⚠️ 只清**自己**棋盘上的（对方棋盘没被重摆，那上面的区域照旧）
        _clear_board_effects(room, [caster_id], '回光返照')
        # 同上：跨回合计数效果是房间级的，施法者重摆棋盘就得一起终止
        _clear_multiturn_effects(room, '回光返照')
        caster.ships = []
        caster.remaining_ships = 0
        # ⚠️ 要清的是【对方打在我方棋盘上的记录】＝ `opponent.attacks`，
        # 不是 `caster.attacks`。两个数组是不同坐标空间：
        #   · caster.attacks   = 我打在【对方】棋盘上的格子 → 与本次重摆无关；
        #     清掉反而会把我已经探明的格子重新变成可打（白赚一炮）。
        #   · opponent.attacks = 对方打在【我方】棋盘上的格子 → 卡面
        #     「在使用回光返照后，也会清空对方视角中自己的棋盘」清的就是它。
        # 旧实现清错了那一份，于是玩家实测：「原本被打过 / 沉船的格子仍然会
        # 显示在使用回光返照者的棋盘上」。
        room.players[opponent_id].attacks = []
        # 标记需要重新摆放
        room.players[caster_id].needs_reset = True
        # 清空对方视角（显形记录 + 攻击历史一起清，否则前端本地缓存还画着 ✕）
        room.players[opponent_id].revealed_positions = []
        _emit_board_attacks(room)

        # 跳过自己的战斗阶段
        room.current_phase = 'end'

        # ★ 2026-09-20 修（第二版）：让施法者进入**摆放阶段**，只发给他一个人。
        #
        # 卡面：「立即清空自己的棋盘，并在其上重新摆放 6 艘船。**跳过自己的战斗阶段**。
        #        接下来如果对方**在这一个大回合内**对任何一艘自己的船造成了伤害，
        #        那么自己直接判负。」
        #
        # ⚠️ 两条必须点，前一版各自栽过一次：
        #
        # ① **走服务端驱动的 `reset_gameboard`**（与败者食尘同一条路），
        #    而不是靠前端 `applyCardEffect` 的 `case '回光返照'`。
        #    那个 case 是**广播**处理器（双方都跑），会把对手也拽进布船界面，
        #    而且让"谁该重摆"有两份实现（前端 case + 服务端状态）。按 sid 单发天然只有施法者收到。
        #
        # ② `room.state` 显式置为 `'placing_ships'`。
        #    否则 `handle_place_ships` 的收尾判据 `all(len(p.ships) > 0 ...)`
        #    在"对手没被清船"时**恒为真**，直接掉进通用分支 → 收尾不受控。
        #
        # ③ ★ **`max_ships` 必须显式给一个数**。
        #    `Player.max_ships` 初值是 `None`，而 `reset_gameboard` 的
        #    `new_max_ships` 会被前端写进 `gameState.maxShips` ——
        #    传 None 过去，前端 `placedShips >= maxShips` 立刻成立 →
        #    **点格子没反应**，且 `ships` 始终为空 → 「布船数据无效」。
        #    （败者食尘在它那边显式设了 `player.max_ships = DEFAULT_SHIPS`，回光返照漏了。）
        room.state = 'placing_ships'
        room.attacks_remaining = 0          # 摆放期间本就没有攻击
        caster.max_ships = int(caster.max_ships or 6)
        # 标记"这次摆放属于回光返照" → `handle_place_ships` 走**本回合续行**的收尾
        room.huiguang_awaiting_placement = True
        emit('reset_gameboard', {
            'new_max_ships': caster.max_ships,
            'message': '回光返照生效，请重新摆放战舰',
        }, to=caster.sid)
        
        # 设置效果：如果对方在这一大回合内对自己的船造成伤害，自己直接判负
        room.game_effects['last_chance'] = {
            'caster': caster_id,
            'active': True,
            'round': room.round,
        }

        result['message'] = '已清空棋盘，请重新摆放战舰，本回合战斗阶段跳过。若对方在本大回合内对您的船造成伤害，您将直接判负'

    elif card.name == '加百列之光':
        # 无效化：连锁栈里有牌就康「正下方那一项」；没有连锁栈则主动拆场地魔法。
        # （作者裁定：这两条是二选一 —— 这解决了"场地早贴上了、过了一会想反悔"
        #   却因为没有连锁窗口而做不到的问题。）
        #
        # ⚠️ 不判归属：此前要求 chain[-1].player_id != caster_id，导致【自连锁】
        # 时康不掉自己前面打出的牌 —— 实测场景：对方出牌 → 我失灵 → 我又加百列，
        # 结算时加百列看到正下方是自己的失灵就不康，失灵照常无效化了对方那张牌。
        # 作者裁定：同一连锁里后手应能推翻前手，一律康正下方那一项。
        negated_count = 0
        chain_negated = False
        if room.chain:
            result.negate_target = True
            chain_negated = True
            negated_count += 1
        elif room.field_magic is None and room.magic_history \
                and room.magic_history[-1]['caster'] != caster_id:
            # 既没有连锁项、场上也没有场地：回退到"对方最近用过的那张"
            # （原行为，别让这张卡在这种情形下变成纯粹的空牌）
            room.magic_history.pop()
            chain_negated = True
            negated_count += 1

        # 没有连锁项时：拆掉当前生效的场地魔法（自己贴的与对方贴的都可以拆）
        torn = None
        if not chain_negated and room.field_magic:
            torn = _tear_down_field_magic(room, caster_id)
            negated_count += 1

        if negated_count == 0:
            result['success'] = False
            result['message'] = '没有可无效化的魔法卡或场地魔法'
            return result
        if torn is not None:
            result['message'] = f'成功无效化场地魔法「{getattr(torn, "name", "")}」'
        else:
            result['message'] = '成功无效化连锁中的魔法卡'

    elif card.name == '钢筋铁骨':
        # 牺牲一艘船，其他船进入无敌状态
        if caster.remaining_ships < 2:
            result['success'] = False
            result['message'] = '需要至少2艘战舰才能发动'
            return result

        # 牺牲一艘船（进入沉船堆，可被复活类卡牌回收）。
        # 注意：普通击沉只减 remaining_ships、不会把船从 ships 里移除，
        # 所以不能直接 pop 列表末尾 —— 那可能是一艘已沉的船，等于零代价发动，
        # 还会让沉船堆出现重复条目（复活类卡牌按 len(sunken_ships) 恢复时
        # 会把船数算多，产生幽灵船）。
        alive_ships = [sh for sh in caster.ships if sh not in caster.sunken_ships]
        if not alive_ships:
            result['success'] = False
            result['message'] = '没有可牺牲的战舰'
            return result
        popped = alive_ships[-1]
        caster.ships.remove(popped)
        if popped not in caster.sunken_ships:
            _mark_ship_sunken(caster, popped)
        caster.remaining_ships -= 1

        # 其他船进入无敌状态
        for ship in caster.ships:
            ship.invincible = True

        result['message'] = '牺牲一艘战舰，其他战舰进入无敌状态'

    elif card.name == '守株待兔':
        # 守株待兔（速阶1 普通）：选自己一艘船打上陷阱标记，
        # 本大回合内这艘船被击沉时让对方牺牲 min(2, 对方活船数) 艘。
        # 卡面只在本大回合生效 → 跨回合清理由 end_turn 内"进入新大回合"分支兜底。
        if caster.remaining_ships == 0:
            result['success'] = False
            result['message'] = '没有战舰可设置陷阱'
            return result

        # 用 _request_ship_pick 让施法者点选一艘自己的活船；
        # AI 路径会直接随机返回一艘，立刻打上陷阱；人类路径入队，由
        # handle_confirm_sacrifice 的 'trap_setup' 分支确认后打上陷阱。
        picked = _request_ship_pick(room, caster_id, 'trap_setup',
                                    '守株待兔：请点选一艘自己的战舰设置陷阱')
        if picked is not None:
            # AI 自动选好：直接打标记
            picked.trap = True
            add_game_log(room,
                         f'第{room.round}回合 · {_log_name(room, caster_id)} 的【守株待兔】'
                         f'为一艘战舰设置陷阱',
                         'magic', {'caster': caster_id, 'card': '守株待兔'})
            emit('trap_set', {
                'player': caster_id,
                'positions': [{'x': p.x, 'y': p.y} for p in picked.positions],
            }, room=room.id)
            result['message'] = '已为一艘战舰设置陷阱（本回合该船被击沉时对方需牺牲两艘）'
        else:
            # 人类：等待玩家点选
            result['message'] = '请选择要设置陷阱的战舰'

    elif card.name == '卧薪尝胆':
        # 卧薪尝胆（速阶1 普通）：为所有活船添加护盾（同仁王之盾的 shield=True）。
        # 发动条件「自己船数 < 对方船数」已在 handle_use_magic_card 扣牌前拦过，
        # 这里再判一次作纯防御（连锁结算时船数可能变化）。
        opponent_id = _opponent_of(room, caster_id)
        if opponent_id and opponent_id in room.players:
            if caster.remaining_ships >= room.players[opponent_id].remaining_ships:
                result.success = False
                result.message = '自己的船数不小于对方，卧薪尝胆无法发动'
                return result
        alive = _alive_ships(caster)
        if not alive:
            result.success = False
            result.message = '没有战舰可添加护盾'
            return result
        applied = 0
        for ship in alive:
            ship.shield = True
            applied += 1
        _emit_player_ships(room, caster_id)
        emit('shields_added', {
            'player': caster_id,
            'count': applied,
            'positions': [{'x': p.x, 'y': p.y} for s in alive for p in s.positions],
        }, room=room.id)
        add_game_log(room,
                     f'第{room.round}回合 · {_log_name(room, caster_id)} 的【卧薪尝胆】'
                     f'为{applied}艘战舰添加护盾',
                     'magic', {'caster': caster_id, 'card': '卧薪尝胆', 'count': applied})
        result['message'] = f'已为{applied}艘战舰添加护盾'

    elif card.name == '神机妙算':
        # 宣言x：若结束阶段自己船数减少恰好x，那些船不减少。
        # 尚未宣言 → 打开宣言窗口（同时拍基线、冻结对方、挂超时）；
        # 已宣言（confirm 落临时数据）→ 直接生效。
        if 'prediction' not in room.magic_temp_data:
            _open_shenji_declare_window(room, caster_id, result)
        else:
            x = room.magic_temp_data.get('prediction')
            try:
                x = max(0, min(6, int(x)))
            except Exception:
                x = 0
            _apply_shenji_prediction(room, caster_id, x, result)

    # ==== 判定魔法卡 ====
    # 与「普通」「场地」并列的第三类。先摇骰子（动画+结果广播给双方），
    # 再按点数结算不同效果。命运骰子是第一张判定卡；为后续扩展留 type 分支。
    elif card.type == '判定':
        if card.name == '命运骰子':
            _apply_dice_of_fate(room, caster_id, result)
        else:
            result.success = False
            result.message = f'未实现的判定魔法卡：{card.name}'

    # ==== 场地魔法卡 ====
    elif card.type == '场地':
        # 场地魔法处理 - 全场只能有一张场地魔法卡生效。
        # 将实例放入场地区域；被顶掉的旧卡实例移入弃牌堆（不造副本）。
        _place_field_magic(room, caster_id, card)

        if card.name == '恶魔契约':
            room.game_effects['demon_contract'] = True
            result.message = '恶魔契约生效，双方船数增减绑定'
        elif card.name == '禁忌果实':
            result.message = '禁忌果实生效，双方只能使用失灵！和场地魔法'
        elif card.name == '伊甸园':
            result.message = '伊甸园生效，攻击次数变为6-n'
            if room.state == 'attacking' and getattr(room, 'current_phase', None) == 'preparation' and room.current_attacker in room.players:
                # 场地变更需要整体重算（不是"船数增减"），用 _recalc
                _recalc_attacker_attacks(room)
                emit('attacks_updated', {
                    'current_attacker': room.current_attacker,
                    'attacks_remaining': room.attacks_remaining
                }, room=room.id)
        # 注意：教皇旨意在上面的场地魔法分支之前就被 elif card.name 捕获，
        # 这里原本还有一份重复分支，永远不可达，已删除。

    # ==== 已实现的魔法卡 ====
    elif card.name == '失灵！':
        # 连锁结算中：康紧邻下方那一项（下一个待结算项）。
        # ⚠️ 与「加百列之光」同口径：不判归属 —— 自连锁时要能康掉自己前面
        # 打出的牌（作者裁定：同一连锁里后手能推翻前手）。
        if room.chain:
            target = room.chain[-1]
            tname = getattr(target.card, 'name', None)
            if tname == '看破！':
                result.success = False
                result.message = '看破！优先于失灵！，无法无效化'
                return result
            if tname == '加百列之光':
                result.success = False
                result.message = '加百列之光免疫失灵！'
                return result
            result.negate_target = True
            result.message = f'将无效化{target.card.name}'
            return result

        # 没有连锁栈：优先主动拆掉已贴出的场地魔法。
        # 作者裁定 —— 这解决了"场地早贴上了、过了一会想反悔"却因为没有
        # 连锁窗口而做不到的问题（原实现在这种情况下只能回退到历史记录）。
        # 自己贴的与对方贴的都可以拆。
        if room.field_magic:
            torn = _tear_down_field_magic(room, caster_id)
            result.message = f'成功无效化场地魔法「{getattr(torn, "name", "")}」'
            return result

        # 直接调用（无连锁栈、场上也没有场地）时回退历史记录。
        # 卡面："无效化对方使用的上一张魔法卡，被影响的魔法卡必须为当前时段刚使用的。"
        if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
            last_magic = room.magic_history[-1]
            if getattr(last_magic.get('card'), 'name', None) in ('看破！', '加百列之光'):
                result.success = False
                result.message = '该魔法免疫失灵！'
                return result
            # 只允许无效化本大回合内刚使用的卡（老条目没有 round 时按旧行为放行）
            if last_magic.get('round', room.round) != room.round:
                result.success = False
                result.message = '对方上一张魔法卡不是本回合使用的，失灵！无法无效化'
                return result
            room.magic_history.pop()
            result.message = f'无效化了{last_magic["card"].name}（若其效果已结算则不会回滚）'
            result.negated = last_magic
        else:
            result.success = False
            result.message = '没有可无效化的魔法卡'

    elif card.name == '看破！':
        # 无效化对方本回合所有魔法卡
        room.players[opponent_id].magic_blocked = True
        result.message = '本回合对方魔法卡被无效化'

    elif card.name == '增援':
        # 召唤一艘战舰：等待玩家选择放置位置。
        # ⚠️ 没有"6 艘上限"这种东西 —— 作者确认船数只受棋盘格数（36 格）限制。
        # 旧实现在 remaining_ships >= 6 时直接拒绝，但那时牌已经离手
        # （handle_use_magic_card 先扣牌再结算），玩家被白吞一张卡。
        _start_placement(room, caster_id, 'reinforce', 1)
        result.temp_data_id = 'reinforcement_choice'
        result.message = '请选择增援战舰的部署位置（未被攻击过的空格）'

    else:
        result.success = False
        result.message = f'未实现的魔法卡: {card.name}'



    
    #result['success'] = False
    #result['message'] = f'魔法效果应用失败: {str(e)}'

    # 魔法卡消灭对方最后一艘船时也判定游戏结束（与攻击路径一致）
    # 注意：对方从未布船（ships 为空，如测试构造态/未开局）不算被消灭，
    # 否则在空房间出任何一张卡都会直接判胜。
    if (opponent and opponent.remaining_ships <= 0 and len(opponent.ships) > 0
            and room.state != 'game_over'):
        room.state = 'game_over'
        room.winner = caster_id
        add_game_log(room, f"第{room.round}回合 · {_log_name(room, caster_id)} 获胜，游戏结束", 'result', {'winner': caster_id, 'loser': opponent_id})
        # 记录战绩 + 每局统计 + 徽章（统一收口，见 _finalize_match）
        _finalize_match(room, caster_id, opponent_id)
        emit('game_over', {'winner': caster_id}, room=room.id)

    return result


def get_uuid() -> str:
    return str(uuid.uuid4())[:4]


@socketio.on('surrender')
@_require_live_room
def handle_surrender(data):
    # 处理投降请求
    player_id = data.get('player_id') or session.get('user_id', request.sid)
    room_id = data.get('room_id')
    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '房间不存在'}

    # 必须通过身份校验：避免他人凭 room_id+player_id 替对手投降
    if player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '你不在这个房间'}

    # 设置游戏结束状态
    room.state = 'game_over'

    # 投降玩家失败，对手获胜
    opponent_id = next(p for p in room.players if p != player_id)
    room.winner = opponent_id

    # 记录战绩 + 每局统计 + 徽章（统一收口，见 _finalize_match）
    _finalize_match(room, opponent_id, player_id)
    # 向房间发送游戏结束事件
    emit('game_over', {
        'winner': opponent_id,
        'reason': 'surrender'  # 添加投降原因标记
    }, room=room_id)
    return {'status': 'success'}


def create_custom_room_for_invite():
    """给"好友邀战"建一个自定义房（**唯一实现**）。

    好友对战一律走自定义房：不给段位分、不计战绩。api.py 通过注入调用这个函数
    （见文件末尾），所以这里的 `room_manager` 永远是**正在服务**的那一份。
    """
    return room_manager.create_room()


def _admin_user_ids_for_api():
    """把管理员白名单交给 `api.py`（反作弊管理后台用）。

    ⚠️ 这是**唯一一份**管理员名单（`DEBUG_ADMIN_USER_IDS`）。
    不在 api.py 里另读一次环境变量 —— 两份配置必然漂移，
    会出现"调试面板能进、管理后台进不去"这种对不上的状态。
    """
    return set(DEBUG_ADMIN_USER_IDS)


# ---------------------------------------------------------------------------
# 把"实时推送 / 建房"交给 api.py 用（好友功能）
#
# api.py 不能 import 本模块：应用以 `python server.py` 启动时本模块名是 `__main__`，
# `import server` 会把整个文件再执行一遍成另一个模块对象 —— 那份 socketio 发不出事件
# （申请/接受**静默丢弃**，接口照样回 sent/ok）、那份 room_manager 建的房在真进程里
# 根本不存在（邀战回一个野 room_id）。而生产是 run_prod.py 起的，模块名又正常 ——
# 属于"本地坏、线上好"的环境相关 bug，详见 api.py 顶部那段注释。
#
# 所以反过来：由这里在 import 期把**本模块对象自己**（`sys.modules[__name__]`，
# 无论叫 `__main__` 还是 `server`，都一定是正在跑的那一份）交给 api.py。
# 推送与建房仍然各只有一份实现；api 侧按名字现取，测试里的 monkeypatch 照样有效。
# ---------------------------------------------------------------------------
try:
    import api as _api    # ⚠️ 本文件是 `from api import app`，`api` 这个名字**没绑定** ——
                          # 直接写 `api.xxx` 会 NameError 被下面的 except 吞成一句警告。
    _api.register_friend_backend(
        sys.modules[__name__],
        # 好友能力按名字登记（`api.py` 侧 `_friend_backend(name)` 现取）。
        # 注入的是**模块对象自己**，所以下面这几个名字只是"这份契约的清单"：
        # 少写一个不会报错，只会让 `api.py` 那一侧静默拿到 None（推送失效），
        # 所以新增推送函数时**必须**在这里补一行（私聊批就是这么加的）。
        push_friend_message='push_friend_message',
        # 反作弊管理后台（2026-09-20）：管理员白名单**只有一份**，就是这个集合。
        # `api.py` 侧按名字取（`api._admin_backend('_admin_user_ids_for_api')`），
        # 绝不新造第二套管理员概念。
        #
        # ⚠️ `**names` 是「键=值」的**校验清单**，不是改名映射 ——
        #    `_friend_backend(name)` 用的是**调用方传的名字**去 getattr，
        #    清单只负责在 import 期把"名字不存在"喊出来。
        #    所以这里的**键必须等于真实函数名**，写成别名（`admin_user_ids=...`）
        #    不会报错，只会让 api 侧 getattr 拿到 None → 白名单恒为空 →
        #    **管理员自己也进不去**（本批就踩了，已由 admin 用例钉住）。
        _admin_user_ids_for_api='_admin_user_ids_for_api',
    )
except Exception as _e:                                          # noqa: BLE001
    # 注入失败只记日志：好友的实时提示会降级成"对方刷新后自己看到"，
    # 绝不能让整个服务起不来。
    print(f'[friends] 注入后端模块失败（好友实时提示将不可用）: {_e}')


if __name__ == '__main__':
    # 初始化数据库
    db.init_db()
    # 添加详细日志输出

    logging.basicConfig(level=logging.DEBUG)
    # 启动服务器
    # 默认关闭调试模式（Werkzeug 调试器可被用于远程代码执行）；
    # 本地需要时设置环境变量 FLASK_DEBUG=1。
    socketio.run(
        app,
        debug=os.environ.get('FLASK_DEBUG') == '1',
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
    )
