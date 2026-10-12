"""旧玩家、船位与效果标记的可变运行时状态。"""

from __future__ import annotations

from typing import Any


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
    magic_hand: list[Any]
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
