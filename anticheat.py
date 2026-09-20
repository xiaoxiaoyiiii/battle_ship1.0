# -*- coding: utf-8 -*-
"""反作弊引擎（2026-09-19）—— **纯函数 + 纯数据，不碰数据库、不发事件**。

为什么单独一个模块（与 `ranks.py` / `leveling.py` / `achievements.py` 同一套路）：
  * `server.py` 已经 9800 行。规则再塞进去就是又一份"深埋在大文件里、没人敢改"的实现；
  * 本项目的老病根是「**同一个业务判断有两份实现就一定会漂移**」（CLAUDE.md §10.1）——
    反作弊判据一旦在"实时检测"和"事后审计"两处各写一遍，必然对不上；
  * 纯函数意味着**可单测、可复算、可解释**：给定同一份输入永远得到同一份判定，
    这是"处罚玩家"这件事的最低要求。

设计原则（按网络安全的标准）：
  1. **纵深防御**：一层被绕过，下一层还在。见 `RULES` 的四类。
  2. **默认怀疑、分级处置**：分数是累加的嫌疑度，不是布尔值。低分只记录、高分才拦。
  3. **只依据服务端事实**：一切判据来自服务端已记录的对局事实（回合数、击沉数、
     攻击次数、时间戳、用户 id），**不信客户端上报的任何东西**。
  4. **失败开放（fail-open）**：判定过程绝不允许把对局结算搞崩 —— 调用方包 try，
     本模块内部也全部用安全取值。
  5. **可解释**：每次判定都返回 `reasons`，能对玩家、对审计人员逐条讲清楚为什么。

⚠️ 本模块**只判定，不处罚**。扣分/拦截/封禁的**动作**由 `server.py` 按判定结果执行 ——
   这样"判据"与"处置"分离，改处罚力度不需要动判据。
"""

from typing import Any

# ---------------------------------------------------------------------------
# 嫌疑度权重（累加制）
#
# 数值不是拍脑袋：按「这个信号单独出现时，正常人误触的概率」定级。
# 越是不可能自然发生的信号，权重越高。
# ---------------------------------------------------------------------------
W = {
    # —— 致命信号（正常人几乎不可能触发）——
    'sweep_perfect_win': 100,      # 单回合内击沉对方全部船，且自己零损伤
    'mirror_positions': 90,        # 对手船位与历史某局完全一致（摆位可预测）
    'instant_surrender': 80,       # 开局立即投降（第 1 回合且零交火）
    # —— 强信号 ——
    'repeat_opponent_burst': 60,   # 短时间连续匹配同一个对手
    'one_sided_series': 55,        # 连续多局对同一对手，胜负 100% 一边倒
    'sub_round_win': 40,           # 极短回合内获胜
    # —— 中信号 ——
    'zero_engagement_loss': 30,    # 输的那方全程零次有效攻击
    'suspicious_timing': 25,       # 局间隔极短（批量重开特征）
    'win_streak_anomaly': 20,      # 异常连胜
}

# 分级阈值
LEVEL_RECORD = 30     # >= 只记录
LEVEL_FLAG = 60       # >= 标记为可疑
LEVEL_BLOCK = 100     # >= 拒绝结算排位分（"狠"的那一档）


def _g(obj, key, default=None):
    """安全取值：对象或 dict 都支持，取不到返回默认值（绝不抛）。"""
    try:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
    except Exception:
        return default


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ===========================================================================
# 规则一：摆位可预测 —— 「人肉靶子」的直接指纹
# ===========================================================================
def rule_sweep_perfect_win(facts: dict) -> list[dict]:
    """单回合内击沉对方全部船，且**只有一方开火**。

    这是本库真实作弊手法的**直接指纹**（见 `docs/ANTICHEAT_FORENSICS_2026_09_19.md`）：
    靶子把 6 艘船摆成一条线，大号第一回合 (0,0)~(5,0) 六发全沉。

    ⚠️ **判据刻意不依赖"谁是胜方"**（这一条是实测修出来的）：
    `matches.winner_id` 存的是 **user_id**，而对局日志 `detail.attacker` 存的是
    **socket sid** —— 两套 id 无法直接比对。第一版规则拿它们对齐，结果在
    已知的 166 局作弊上**召回率 0%**（一条都没抓到），而测试全绿。
    → 改用**位置无关的形态特征**：本局只有一方开过火，且它命中数 == 对方船数。
    这在语义上更强："另一方从头到尾一枪没放，却被全歼"本身就是铁证。

    事实字段：
      · `rounds`        —— 本局进行到第几回合（-1 = 未知）
      · `attackers`     —— 本局开过火的 sid 集合
      · `max_hits`      —— 单个攻击者的最大命中数
      · `foe_ships`     —— 对方总船数
    """
    out = []
    try:
        rounds = int(facts.get('rounds', -1))
        attackers = facts.get('attackers') or []
        max_hits = _int(facts.get('max_hits'))
        foe_ships = _int(facts.get('foe_ships'))
        only_one_shooter = len(set(attackers)) <= 1

        # ⚠️ `0 <= rounds <= 1` 而不是 `rounds <= 1`：回合数未知用 -1 表示，
        #    写成 `rounds <= 1` 会把"未知"也算成"第 1 回合"（老格式日志全中招）。
        if only_one_shooter and foe_ships > 0 and max_hits >= foe_ships \
                and 0 <= rounds <= 1:
            out.append({
                'rule': 'sweep_perfect_win',
                'weight': W['sweep_perfect_win'],
                'detail': (f'第 {rounds} 回合内单方连续击沉全部 {max_hits} 艘，'
                           f'另一方全程一枪未发 —— 船位可预测（人肉靶子）'),
            })
    except Exception:
        pass
    return out


def rule_mirror_positions(facts: dict) -> list[dict]:
    """对手船位与历史对局完全一致 —— 船位没变，说明是固定靶子。

    `facts['foe_position_signature']` 与 `facts['past_signatures']` 都是
    排好序的坐标字符串（如 `"0,0|1,0|2,0|3,0|4,0|5,0"`）。服务端比对，
    重复出现即命中。
    """
    out = []
    try:
        sig = facts.get('foe_position_signature')
        past = facts.get('past_signatures') or []
        if sig and sig in past:
            n = list(past).count(sig)
            out.append({
                'rule': 'mirror_positions',
                'weight': W['mirror_positions'],
                'detail': f'对手船位与该账号历史上 {n} 局完全相同（船位未变，疑似固定靶子）',
            })
    except Exception:
        pass
    return out


# ===========================================================================
# 规则二：见面投降 / 零交火
# ===========================================================================
def rule_instant_surrender(facts: dict) -> list[dict]:
    """开局即投降且双方零交火 —— "见面就投"。

    注意与既有的「赛前投降不给分」区分：那条拦的是**还没开打**（没猜拳/没进攻击阶段），
    本规则拦的是**已经开打但一枪未放就投** —— 这是绕开前者的口子。
    """
    out = []
    try:
        if facts.get('ended_by') != 'surrender':
            return out
        rounds = _int(facts.get('rounds'))
        attacker_hits = _int(facts.get('attacker_total_hits'))
        defender_hits = _int(facts.get('defender_total_hits'))
        if rounds <= 1 and attacker_hits == 0 and defender_hits == 0:
            out.append({
                'rule': 'instant_surrender',
                'weight': W['instant_surrender'],
                'detail': '开局第 1 回合、双方零次有效攻击即投降',
            })
    except Exception:
        pass
    return out


def rule_zero_engagement_loss(facts: dict) -> list[dict]:
    """输的那一方全程零次有效攻击（挨打不还手）。

    三处豁免，每一处都是**实测修出来的**（不是设计出来的）：

    ① **投降的局不算**：主动投降的玩家本来就可能一枪未放就认输 —— 那是
       **规则允许的正当行为**，不是"不还手"。见面就投由 `rule_instant_surrender`
       按"是否第 1 回合"单独管。
    ② **没有船的不算**：`rounds >= 2` 但**棋盘是空的**（双方都没摆船 / 摆船前就结束）
       同样会得到"零命中"，那是**对局根本没进行**，不是玩家不动。
       ⚠️ 这条是接进服务端后才暴露的：老测试房间直接调 `_finalize_match`，
       双方 `ships` 都是空列表、`round` 却有值 → 大批正常用例被判 `record`。
    ③ 因此判据必须**同时**要求"对方确实有船可打"（`foe_ships > 0`）。
    """
    out = []
    try:
        if facts.get('ended_by') == 'surrender':
            return out
        loser_hits = _int(facts.get('loser_total_hits'))
        rounds = _int(facts.get('rounds'))
        foe_ships = _int(facts.get('foe_ships'))
        total_ships = _int(facts.get('total_ships'))
        # 棋盘是空的 → 对局没真进行，不适用本条
        if foe_ships <= 0 or total_ships <= 0:
            return out
        if rounds >= 2 and loser_hits == 0:
            out.append({
                'rule': 'zero_engagement_loss',
                'weight': W['zero_engagement_loss'],
                'detail': f'败方 {rounds} 个回合内零次有效攻击（全程不还手）',
            })
    except Exception:
        pass
    return out


# ===========================================================================
# 规则三：匹配操纵 —— 一直撞同一个人
# ===========================================================================
def rule_repeat_opponent_burst(facts: dict) -> list[dict]:
    """短时间内连续匹配同一个对手。

    `facts['opponent_gaps_sec']` = 本局之前，与该对手最近 N 局的间隔秒数列表。
    正常的随机匹配队列里，几分钟内反复撞同一个人是极不自然的 —— 刷分特征是
    "两个号同时排队，必然互相匹配"。
    """
    out = []
    try:
        gaps = facts.get('opponent_gaps_sec') or []
        if len(gaps) < 3:
            return out
        fast = [g for g in gaps if _int(g) <= 300]     # 5 分钟内
        if len(fast) >= 3:
            out.append({
                'rule': 'repeat_opponent_burst',
                'weight': W['repeat_opponent_burst'],
                'detail': (f'与同一对手 {len(gaps)} 局中，{len(fast)} 局的间隔在 5 分钟内'
                           f'（最短 {min(_int(g) for g in fast)} 秒）—— 疑似同时排队对刷'),
            })
    except Exception:
        pass
    return out


def rule_one_sided_series(facts: dict) -> list[dict]:
    """对同一对手连续多局、胜负 100% 一边倒。"""
    out = []
    try:
        n = _int(facts.get('opponent_total_games'))
        w = _int(facts.get('opponent_wins'))
        l = _int(facts.get('opponent_losses'))
        if n >= 5 and (w == 0 or l == 0):
            loser = '本方' if w == 0 else '对方'
            out.append({
                'rule': 'one_sided_series',
                'weight': W['one_sided_series'],
                'detail': f'与同一对手交手 {n} 局，{loser}一局未胜（100% 一边倒）',
            })
    except Exception:
        pass
    return out


# ===========================================================================
# 规则四：时间与连胜异常
# ===========================================================================
def rule_suspicious_timing(facts: dict) -> list[dict]:
    """局间隔极短 —— 批量重开。真实对局不可能 30 秒一局。"""
    out = []
    try:
        gap = _int(facts.get('since_last_match_sec'), -1)
        duration = _int(facts.get('duration_sec'))
        if 0 <= gap <= 20:
            out.append({
                'rule': 'suspicious_timing',
                'weight': W['suspicious_timing'],
                'detail': f'距上一局仅 {gap} 秒（批量重开特征）',
            })
        elif duration > 0 and duration <= 30:
            out.append({
                'rule': 'suspicious_timing',
                'weight': W['suspicious_timing'],
                'detail': f'本局用时仅 {duration} 秒',
            })
    except Exception:
        pass
    return out


def rule_win_streak_anomaly(facts: dict) -> list[dict]:
    """异常连胜：排位连赢场次远超正常分布。"""
    out = []
    try:
        streak = _int(facts.get('ranked_win_streak'))
        if streak >= 12:
            out.append({
                'rule': 'win_streak_anomaly',
                'weight': W['win_streak_anomaly'],
                'detail': f'排位已连胜 {streak} 场（异常值）',
            })
    except Exception:
        pass
    return out


# ===========================================================================
# 规则五：终局形态 —— 极短回合获胜
# ===========================================================================
def rule_sub_round_win(facts: dict) -> list[dict]:
    """极短回合内获胜（但没到"完美横扫"那么极端）。"""
    out = []
    try:
        rounds = _int(facts.get('rounds'))
        sunk = _int(facts.get('sunk'))
        if 2 <= rounds <= 3 and sunk > 0:
            out.append({
                'rule': 'sub_round_win',
                'weight': W['sub_round_win'],
                'detail': f'{rounds} 个回合内结束对局（击沉 {sunk} 艘）',
            })
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
RULES = (
    rule_sweep_perfect_win,
    rule_mirror_positions,
    rule_instant_surrender,
    rule_repeat_opponent_burst,
    rule_one_sided_series,
    rule_zero_engagement_loss,
    rule_suspicious_timing,
    rule_win_streak_anomaly,
    rule_sub_round_win,
)


def evaluate(facts: dict) -> dict:
    """对**一局**做全规则判定。

    返回：
      {
        'score': int,            # 累加嫌疑度
        'level': str,            # 'clean' | 'record' | 'flag' | 'block'
        'reasons': [ {...}, ],   # 逐条命中原因（可解释）
        'rules': [ 'rule_name', ],
        'blocked': bool,         # 是否达到"拒绝结算排位分"的档位
      }

    ⚠️ **失败开放**：任何异常都退化成"干净"，绝不允许把对局结算搞崩
    （与 `_finalize_match` 里各段 `try/except` 同一风格）。
    """
    reasons: list[dict] = []
    try:
        for fn in RULES:
            try:
                reasons.extend(fn(facts or {}) or [])
            except Exception:
                continue
    except Exception:
        reasons = []

    score = sum(_int(r.get('weight')) for r in reasons)
    if score >= LEVEL_BLOCK:
        level = 'block'
    elif score >= LEVEL_FLAG:
        level = 'flag'
    elif score >= LEVEL_RECORD:
        level = 'record'
    else:
        level = 'clean'

    return {
        'score': score,
        'level': level,
        'reasons': reasons,
        'rules': [r.get('rule') for r in reasons],
        'blocked': level == 'block',
    }


def explain(result: dict) -> str:
    """把判定结果压成人话（写日志 / 审计用）。"""
    try:
        if not result or result.get('level') == 'clean':
            return '无异常'
        parts = [f"{r.get('rule')}(+{r.get('weight')}): {r.get('detail')}"
                 for r in (result.get('reasons') or [])]
        return f"嫌疑度 {result.get('score')} [{result.get('level')}] — " + "；".join(parts)
    except Exception:
        return '（判定结果无法解释）'
