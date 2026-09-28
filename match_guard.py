# -*- coding: utf-8 -*-
"""匹配规避（Matchmaking Avoidance，2026-09-20）—— **纯函数 + 纯数据，不碰 socket、不碰数据库**。

为什么单独一个模块（与 `anticheat.py` / `ranks.py` / `leveling.py` 同一套路）：
  * 配对逻辑现在内联在 `handle_find_match` 的双层循环里。往那儿再塞 IP 冷却、
    对手冷却、优先级降级，就是一堆没人敢改的嵌套条件；
  * 判据要能**单独测**：给定的队列 + 给定的事实 → 给定的一对（或不配）。纯函数才能做到；
  * 本项目老病根「同一个业务判断有两份实现就一定会漂移」——规避逻辑只此一份。

═══════════════════════════════════════════════════════════════════════════════
★ 最重要的设计约束：**绝不能让队列卡死**
═══════════════════════════════════════════════════════════════════════════════
规避规则天然与「尽快配对」冲突。深夜只有两个人在线、而他们恰好刚打完一局 /
恰好同 IP（比如同一个宿舍）时，硬性规避 = **两个人永远配不上**，
表现为"点了匹配没反应" —— 这比刷分更伤正常玩家。

所以采用**软规避 + 硬兜底**：

  · **硬规避**（绝不配）：① 同一账号（本来就是既有行为）；
    ② 同一 IP **且** 该 IP 下账号出现过刷分标记 —— 只对"已经脏了"的 IP 硬拦。
  · **软规避**（先躲开，躲不开就让步）：同一 IP、近来交手过的对手。
    优先配"干净"的对；队列里实在只有这对可配时，**仍然配**。

⚠️⚠️ **兜底配上之后，这一局照常结算排位分。**
「要不要给分」是**对局内容**的问题（是不是刷分局），由 `anticheat` 判据决定，
**不是**由"配得好不好"决定。

本项目真的栽过这一次（2026-09-20，玩家实测："排位分都不加/不扣了"）：
早先的写法是"兜底配出来的对不结算排位分"，本意是"刷分拿不到收益"，
但**小社区里「和刚打过的人再打一局」恰恰是最常见的匹配** →
大量完全正常的排位对局静默不结算。把**配对偏好**当成**结算判据**，
误伤面极大。详见 `pick_pair` 的说明与 CLAUDE.md 第 33 条。
"""

from typing import Any

# ---------------------------------------------------------------------------
# 调参集中在这里（唯一一份）
# ---------------------------------------------------------------------------
# 近来交手过的对手，在这段时间内优先不匹配（秒）。30 分钟：
# 真实刷分是"几分钟内刷几十局"，30 分钟足以打断；而正常玩家 30 分钟后
# 再撞上同一个人是很自然的事，不该被永久拆开。
RECENT_OPPONENT_COOLDOWN_SEC = 30 * 60

# 「近来交手」看最近多少局（不是全部历史 —— 几十局前碰过一次不算）
RECENT_OPPONENT_LOOKBACK = 8

# 回避计数在**这次排队**里记几次（同一次排队内持续抬高回避强度）
# 这里只用于排序打分，不做硬拦。

# 同 IP 软规避的强度（分越高越优先配上）
SCORE_BASE = 1000
PENALTY_SAME_IP = 400            # 同 IP：明显降权，但不到"绝不配"
PENALTY_RECENT_OPPONENT = 300    # 近来交手过：降权
PENALTY_SAME_IP_DIRTY = 10_000   # 同 IP + 该 IP 有过作弊标记：实际上等于不配


def _usable_ip(ip) -> str:
    """这个 IP 能不能用来做"同 IP"判定。

    ⚠️ **回环 / 内网地址一律视为"没有 IP"**（等价于不判定同 IP）。

    为什么必须这样（这条是实测撞出来的，不是设计出来的）：
    同 IP 软规避一旦生效于回环地址，**本机跑测试 / 局域网访问 / 内网部署**时
    所有人都是 `127.0.0.1` 或 `192.168.x.x` → 每一对都被降权 → 兜底 →
    `room.ranked=False` → **排位分静默全部不结算**（接口照常返回、页面照常开局，
    没有任何报错）。测试里表现为"排位分测试整片变红"，线上则是一场静默事故。

    所以：只有**看起来像公网**的地址才参与同 IP 规避。判定刻意保守 ——
    宁可漏判（少数人用同一出口刷分，仍由 `anticheat` 在收益侧兜住），
    也绝不误伤（把正常玩家的排位悄悄关掉）。
    """
    s = (ip or '').strip()
    if not s:
        return ''
    low = s.lower()
    if low in ('localhost', '::1', '0.0.0.0', '::'):
        return ''
    # IPv4 回环 / 私有 / 链路本地
    if low.startswith('127.') or low.startswith('10.') \
            or low.startswith('192.168.') or low.startswith('169.254.'):
        return ''
    if low.startswith('172.'):
        try:
            second = int(low.split('.')[1])
            if 16 <= second <= 31:
                return ''
        except (IndexError, ValueError):
            return ''
    # IPv6 链路本地 / 唯一本地
    if low.startswith('fe80:') or low.startswith('fc') or low.startswith('fd'):
        return ''
    # IPv4-mapped IPv6（::ffff:127.0.0.1 这类）→ 剥掉前缀再判一次。
    # ⚠️ 必须按 `::ffff:` 的**长度**切，不能 `split(':')[-1]`：
    #    后者会把 `::ffff:127.0.0.1` 切成 `127.0.0.1` 之外的怪东西。
    if low.startswith('::ffff:'):
        return _usable_ip(s[len('::ffff:'):])
    return s


class Candidate:
    """队列里的一个人 + 他相对另一个人的「可配性」。

    纯数据，不持有任何服务端对象。
    """

    __slots__ = ('sid', 'uid', 'mode', 'ip', 'recent_foes', 'ip_dirty', 'waited_sec')

    def __init__(self, sid, uid=None, mode='', ip=None,
                 recent_foes=(), ip_dirty=False, waited_sec=0):
        self.sid = sid
        self.uid = uid
        self.mode = mode
        # ★ 回环 / 内网地址在这里就被归一成"没有 IP"，后续所有判定天然放行
        self.ip = _usable_ip(ip)
        self.recent_foes = tuple(recent_foes or ())
        self.ip_dirty = bool(ip_dirty)
        self.waited_sec = int(waited_sec or 0)


def _same_account(a: Candidate, b: Candidate) -> bool:
    """同一账号（同一 user_id 的两个标签页）—— 既有行为，绝不配。"""
    au, bu = a.uid, b.uid
    return au is not None and au == bu


def hard_block(a: Candidate, b: Candidate) -> str:
    """返回不可配的原因（空串 = 可配）。

    ⚠️ **只放"绝不配"的规则**。任何会写进这里的规则都可能让人配不上，
    所以判断标准是：**配上的危害 远大于 配不上的危害**。
    """
    if _same_account(a, b):
        return 'same_account'
    # 同 IP + 该 IP 有作弊标记：这是刷分机房的典型特征，硬拦。
    # 注意要求**双方**同 IP 且该 IP 脏 —— 单侧脏不拦（脏的人也可能在网吧）。
    if a.ip and a.ip == b.ip and a.ip_dirty and b.ip_dirty:
        return 'same_ip_dirty'
    return ''


def pair_score(a: Candidate, b: Candidate) -> int:
    """分数越高越优先配对。纯排序用，不决定"能不能配"。"""
    score = SCORE_BASE
    if a.ip and a.ip == b.ip:
        score -= PENALTY_SAME_IP
        if a.ip_dirty or b.ip_dirty:
            score -= PENALTY_SAME_IP_DIRTY
    # 近来交手过（双向都查：只要有一方把对方记在近期对手里就算）
    if b.uid and b.uid in a.recent_foes:
        score -= PENALTY_RECENT_OPPONENT
    if a.uid and a.uid in b.recent_foes:
        score -= PENALTY_RECENT_OPPONENT
    # 等得越久越该配上（避免某个人被反复"让位"而一直排不上）
    score += min(int(a.waited_sec), 600) // 10
    score += min(int(b.waited_sec), 600) // 10
    return score


def pick_pair(queue: list) -> tuple:
    """从队列里挑一对可配的人。

    返回 `(i, j, assessed)`：
      · `i, j`   —— 在 `queue` 里的下标（`i < j`）；没得配时返回 `(None, None, False)`
      · `assessed` —— **这一对是不是"规避规则下的最优选择"**（纯**配对偏好**指标）：
          True  = 没吃到任何软规避扣分（不同 IP、近来没打过）
          False = 只配到了"本该躲开"的对象（仍然配上，只是偏好上不是最优）

    ⚠️⚠️ **`assessed` 绝不可以拿去决定"这一局给不给排位分"。**
    它表达的是"配得好不好"；而"给不给分"取决于**对局内容**（是不是刷分局），
    那件事由 `anticheat` 判据负责。

    本项目**真的栽过这一次**（2026-09-20，玩家实测报的）：
    `server.py` 曾写成 `room.ranked = (mode == ranked) and bool(assessed)`，
    于是小社区里最常见的情形 ——「和刚打过的人再打一局」——
    **全部静默不结算**：赢的不加分、输的不扣分，双方都以为排位坏了。
    根因是把**配对偏好**当成了**结算判据**。详见 CLAUDE.md 第 33 条。

    算法：
      ① 遍历所有 **mode 相同** 且 **未被硬拦** 的组合，取 `pair_score` 最高的；
      ② 最高分 ≥ `SCORE_BASE` 时 `assessed=True`（没吃任何软规避扣分）；
      ③ 一个都没有 → 返回全 `None`（**队列原样保留**，等新玩家入队，不死循环）。

    ⚠️ ③ 与既有实现语义一致：`handle_find_match` 的循环靠"没配到就 break"退出。
    这里**绝不**为了"必须配成"而放宽到打破硬拦 —— 硬拦的就该一直等。
    """
    best = None            # (score, i, j)
    for i in range(len(queue)):
        a = queue[i]
        for j in range(i + 1, len(queue)):
            b = queue[j]
            if a.mode != b.mode:
                continue
            if hard_block(a, b):
                continue
            s = pair_score(a, b)
            if best is None or s > best[0]:
                best = (s, i, j)
    if best is None:
        return None, None, False

    score, i, j = best
    # 干净 = 没有吃到任何软规避扣分（等于基准分 + 等待加成 ≥ 基准分）
    clean = score >= SCORE_BASE
    return i, j, clean
