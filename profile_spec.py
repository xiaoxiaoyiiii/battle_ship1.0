# -*- coding: utf-8 -*-
"""个人信息名片的「称号 / 标签 / 头像框 / 名片底色」规格与解锁规则。

**纯函数 + 常量，无 IO**：这里不 import db / flask / server，接口层把 stats
传进来即可。解锁判定**只在服务端做最终裁决**（前端拿到 `catalog` 只是为了把
未解锁项灰掉并写出解锁条件，不是校验）。

`stats` 用到的字段全部来自现有表，本批**不新增任何每局结算写入**：

| 字段 | 来源 |
| --- | --- |
| `wins` / `losses` | `users` 表（总场次 = wins + losses） |
| `longest_streak` | `users` 表 |
| `created_at` | `users` 表（epoch 秒，用于「注册满 180 天」） |
| `card_uses_total` | `user_card_usage` 表按 user_id 汇总（由调用方传入） |
| `rank_tier` | `user_rank` 表 → `ranks.points_tier_index(points)`（段位批加，见下） |

⚠️ **契约冻结**（`docs/PROFILE_CARD_2026_09_17_PLAN.md` §2.1）：池子 id、字段名、
函数名都不要改名 —— T2/T3 的前端与 T4 的工具都按这份契约写。
池子条目里多带一个 `requirement`（自然语言的解锁条件），是为了让
「池子定义」与「解锁条件」只有一份来源：前端 `button.pf-opt[data-title]` 的
`title` 属性、`catalog` 的 `requirement` 字段、错误提示都取自它。
（这正是本项目「通用教训二：同一个业务判断有两份实现，就一定会漂移」的应对。）

⚠️ **段位解锁项（段位批）走的是同一条思路**：条目里直接写 `rank_tier`
（= `ranks` 里的段位下标），`requirement` 文案与判定函数都由它**现算**。
阈值只写一遍，所以"写着船长、判定按大副"这种漂移在结构上不可能发生。
"""
import time

import ranks                # 纯模块（只依赖 stdlib），阈值都从它取

MAX_TAGS = 3              # 标签最多 3 个（超出丢弃）
MAX_STATUS_LEN = 30       # 一句话状态 ≤30 字（超出截断）
VETERAN_DAYS = 180        # 「元老」= 注册满这么多天
VETERAN_SECONDS = VETERAN_DAYS * 24 * 3600

# ---------------------------------------------------------------------------
# 池子
# ---------------------------------------------------------------------------
# 7 个称号（设计稿 §5.1）
TITLES = [
    {"id": "rookie", "name": "新兵", "desc": "刚登上甲板的新面孔",
     "requirement": "无门槛"},
    {"id": "sailor", "name": "老水手", "desc": "风浪见得多，甲板踩得熟",
     "requirement": "总场次 ≥ 20"},
    {"id": "hunter", "name": "深海猎手", "desc": "在深海里找猎物的人",
     "requirement": "胜场 ≥ 30"},
    {"id": "streak10", "name": "十连胜", "desc": "连赢十场，手都没抖",
     "requirement": "最高连胜 ≥ 10"},
    {"id": "immortal", "name": "不败神话", "desc": "这个名号本身就是战报",
     "requirement": "最高连胜 ≥ 15"},
    {"id": "veteran", "name": "元老", "desc": "陪这艘船走过半年",
     "requirement": "注册满 180 天"},
    {"id": "cardmaster", "name": "卡牌大师", "desc": "手里有整本卡牌的账",
     "requirement": "累计出牌 ≥ 100"},
    # ---- 段位解锁（段位批）----
    # `requirement` 留空：下面 `_fill_rank_requirements` 按 `rank_tier` 现填。
    # 段位越高，称号越"贵"（作者："段位越高需要越精致越高级"）。
    {"id": "storm_helmsman", "name": "风暴舵手", "desc": "再大的浪也稳得住舵",
     "rank_tier": 2},
    {"id": "deep_navigator", "name": "深海领航", "desc": "闭着眼也能摸回航道",
     "rank_tier": 5},
    {"id": "iron_soul", "name": "铁骨", "desc": "轮机舱里的铁与火",
     "rank_tier": 6},
    {"id": "unsinkable", "name": "不沉之舰", "desc": "沉过一次的人才知道这四个字多重",
     "rank_tier": 7},
    {"id": "sea_emperor", "name": "海皇", "desc": "整片海域只认一个名字",
     "rank_tier": 8},
]

# 12 个标签（设计稿 §5.2），id 用拼音短名（计划 §2.1 冻结）
TAGS = [
    {"id": "aggressive", "name": "激进"},
    {"id": "steady", "name": "稳健"},
    {"id": "fast", "name": "速攻"},
    {"id": "turtle", "name": "蹲坑"},
    {"id": "cardflow", "name": "卡牌流"},
    {"id": "chain", "name": "连锁控"},
    {"id": "rookie", "name": "萌新"},
    {"id": "pro", "name": "大佬"},
    {"id": "nightowl", "name": "夜猫子"},
    {"id": "needmate", "name": "求带"},
    {"id": "serious", "name": "不苟言笑"},
    {"id": "chatty", "name": "爱聊"},
]

# 5 个头像框（设计稿 §5.3）
FRAMES = [
    {"id": "none", "name": "无", "desc": "不加任何边框",
     "requirement": "无门槛"},
    {"id": "silver", "name": "银环", "desc": "一圈冷银细环",
     "requirement": "无门槛"},
    {"id": "gold", "name": "金环", "desc": "金色重环，连胜的证明",
     "requirement": "最高连胜 ≥ 10"},
    {"id": "aurora", "name": "极光", "desc": "流动的极光环",
     "requirement": "胜场 ≥ 30"},
    {"id": "crimson", "name": "绯红", "desc": "暗红双环，打得够多才有",
     "requirement": "总场次 ≥ 50"},
    # ---- 段位解锁（段位批）----
    {"id": "bronze_compass", "name": "青铜罗盘", "desc": "指针有点旧，但从不指错",
     "rank_tier": 2},
    {"id": "silver_chain", "name": "银链锚", "desc": "一圈缠着锚链的银环",
     "rank_tier": 4},
    {"id": "golden_wheel", "name": "黄金舵轮", "desc": "舵轮镶金，转起来有分量",
     "rank_tier": 6},
    {"id": "mithril_ring", "name": "秘银环", "desc": "细看有细密纹路在流动",
     "rank_tier": 7},
    {"id": "king_aura", "name": "海皇光环", "desc": "环外还有一圈极淡的光",
     "rank_tier": 8},
]

# 6 个名片底色（设计稿 §5.4）
CARD_BGS = [
    {"id": "deep", "name": "深海", "desc": "默认冷蓝，最耐看",
     "requirement": "无门槛"},
    {"id": "graphite", "name": "石墨", "desc": "低饱和灰，安静",
     "requirement": "无门槛"},
    {"id": "cyber", "name": "赛博", "desc": "紫青撞色，电子味",
     "requirement": "胜场 ≥ 10"},
    {"id": "lava", "name": "熔岩", "desc": "暖橙岩浆，连胜时更烫",
     "requirement": "最高连胜 ≥ 5"},
    {"id": "dusk", "name": "暮光", "desc": "粉紫余晖",
     "requirement": "总场次 ≥ 30"},
    {"id": "aurora", "name": "极光", "desc": "青绿极光铺满整张卡",
     "requirement": "胜场 ≥ 50"},
    # ---- 段位解锁（段位批）----
    {"id": "shoal", "name": "浅滩", "desc": "暖沙色，一眼能看清水底",
     "rank_tier": 1},
    {"id": "storm", "name": "风暴", "desc": "铅灰云层压在卡面上",
     "rank_tier": 3},
    {"id": "abyss", "name": "深渊", "desc": "几乎全黑，只有一线冷光",
     "rank_tier": 5},
    {"id": "molten_gold", "name": "鎏金", "desc": "暗底上淌着熔金纹",
     "rank_tier": 7},
    {"id": "starfield", "name": "星海", "desc": "整片星海泡在海里",
     "rank_tier": 8},
]

DEFAULT_TITLE_ID = ''      # 空 = 不展示称号（库里的默认值）
DEFAULT_FRAME_ID = 'none'
DEFAULT_CARD_BG_ID = 'deep'

# ---------------------------------------------------------------------------
# 索引与解锁判定
# ---------------------------------------------------------------------------
_BY_ID = {
    'titles': {t['id']: t for t in TITLES},
    'tags': {t['id']: t for t in TAGS},
    'frames': {f['id']: f for f in FRAMES},
    'card_bgs': {b['id']: b for b in CARD_BGS},
}


def _as_int(value, default=0):
    """把 stats 里的值归一化成非负整数（脏数据/None/字符串一律兜住）。"""
    try:
        if isinstance(value, bool):
            return int(value)
        if value is None:
            return default
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def unlock_context(stats):
    """归一化 stats，得到解锁判定用的上下文。

    对已经归一化过的上下文再跑一次是幂等的（`unlocked_*` 系列内部会调用它，
    所以它们既能吃原始 stats，也能吃 `unlock_context` 的结果）。
    """
    stats = stats if isinstance(stats, dict) else {}
    wins = _as_int(stats.get('wins'))
    losses = _as_int(stats.get('losses'))
    return {
        'wins': wins,
        'losses': losses,
        'matches': wins + losses,
        'longest_streak': _as_int(stats.get('longest_streak')),
        'created_at': _as_int(stats.get('created_at')),
        'card_uses_total': _as_int(stats.get('card_uses_total')),
        # 段位下标（0=二级水手 … 7=船长，8=大舰长）。**缺省 0**：没打过排位
        # 就是最低段位，不凭空送段位外观；上界夹到 8（脏数据不该解锁海皇）。
        'rank_tier': min(ranks.ADMIRAL['index'], _as_int(stats.get('rank_tier'))),
    }


def _registered_long_enough(ctx, now=None):
    """注册满 180 天。created_at 缺失（0）视为未满 —— 不能凭空送称号。"""
    if not ctx['created_at']:
        return False
    now = int(time.time()) if now is None else int(now)
    return (now - ctx['created_at']) >= VETERAN_SECONDS


# id -> 判定函数（唯一的一份解锁规则）
_TITLE_RULES = {
    'rookie': lambda c: True,
    'sailor': lambda c: c['matches'] >= 20,
    'hunter': lambda c: c['wins'] >= 30,
    'streak10': lambda c: c['longest_streak'] >= 10,
    'immortal': lambda c: c['longest_streak'] >= 15,
    'veteran': lambda c: _registered_long_enough(c),
    'cardmaster': lambda c: c['card_uses_total'] >= 100,
}

_FRAME_RULES = {
    'none': lambda c: True,
    'silver': lambda c: True,
    'gold': lambda c: c['longest_streak'] >= 10,
    'aurora': lambda c: c['wins'] >= 30,
    'crimson': lambda c: c['matches'] >= 50,
}

_CARD_BG_RULES = {
    'deep': lambda c: True,
    'graphite': lambda c: True,
    'cyber': lambda c: c['wins'] >= 10,
    'lava': lambda c: c['longest_streak'] >= 5,
    'dusk': lambda c: c['matches'] >= 30,
    'aurora': lambda c: c['wins'] >= 50,
}


# ---------------------------------------------------------------------------
# 段位解锁项：文案与判定都从条目里的 `rank_tier` 现算（阈值只写一遍）
# ---------------------------------------------------------------------------
def _fill_rank_requirements(pool):
    """给带 `rank_tier` 的条目补上 `requirement` 文案（在 import 期跑一次）。

    ⚠️ **为什么不是手写文案**：手写就成两处阈值了 —— 文案说「船长」、判定写
    `rank_tier >= 5`（大副）这种漂移不会报错，只会让玩家看着条件解不开。
    现在文案是 `rank_tier` 的函数，"段位达到 船长"与 `c['rank_tier'] >= 7`
    必然一致。段位名同样取自 `ranks`，不在这里再抄一份中文。
    """
    for item in pool:
        tier = item.get('rank_tier')
        if tier is not None:
            item['requirement'] = '段位达到 ' + ranks.tier_of_index(tier)['name']
    return pool


def _rank_rules(pool):
    """从池子里挑出段位解锁项，生成 `{id: 判定}`。

    ⚠️ `t=` 默认参数不能省：lambda 里的循环变量是**晚绑定**的，写成
    `lambda c: c['rank_tier'] >= item['rank_tier']` 会让所有段位项都用
    最后一个条目的阈值（本项目已经在 `game.js` 的 `ReferenceError` 上
    踩过一次"看着对、跑起来全错"的同类坑）。
    """
    return {item['id']: (lambda c, t=item['rank_tier']: c['rank_tier'] >= t)
            for item in pool if item.get('rank_tier') is not None}


_fill_rank_requirements(TITLES)
_fill_rank_requirements(FRAMES)
_fill_rank_requirements(CARD_BGS)

_TITLE_RULES.update(_rank_rules(TITLES))
_FRAME_RULES.update(_rank_rules(FRAMES))
_CARD_BG_RULES.update(_rank_rules(CARD_BGS))


def _unlocked(rules, stats):
    """按规则算出已解锁集合。

    ⚠️ **特权账号直接全解锁**：`stats` 里带 `unlock_all_cosmetics` 标记时，
    池子里的每一项都算已解锁。这个标记由 **api 层**按 `user_perks` 表注入
    （见 `PERK_UNLOCK_ALL`）——本模块保持纯函数、不碰 IO，与第 2 批
    「判据只有一处」的写法一致：判据仍在 rules 里，特权只是"跳过阈值"。
    """
    if has_unlock_all(stats):
        return set(rules)
    ctx = unlock_context(stats)
    return {pid for pid, rule in rules.items() if rule(ctx)}


def unlocked_titles(stats):
    """已解锁的称号 id 集合。"""
    return _unlocked(_TITLE_RULES, stats)


def unlocked_frames(stats):
    """已解锁的头像框 id 集合。"""
    return _unlocked(_FRAME_RULES, stats)


def unlocked_card_bgs(stats):
    """已解锁的名片底色 id 集合。"""
    return _unlocked(_CARD_BG_RULES, stats)


def effective_equipped(stats, title_id='', frame_id='', card_bg_id=''):
    """把**存储的**外观按**当前解锁状态**过滤：失效的回落默认值。

    为什么必须有这个函数（2026-09-20 反作弊回收批）：
    外观解锁判定原先**只在保存路径**（`validate_payload` → `_pick_owned`）跑，
    **读路径直接原样下发存储值**（`api.build_own_profile` / `public_stats`）。
    于是同一条规则"一处校验、一处不校验"，后果：

      · 段位掉下去之后，已经戴上的高段位外观**照样显示**（写路径会拒绝它，
        读路径却放行）—— 玩家"不编辑名片就永远保留，一编辑就丢"，自相矛盾；
      · 靠刷分拿到高段位、事后被回滚分数的人，**奖励收不回来**：
        存储里那串 id 还在，前端照着渲染。

    判定口径与写路径**完全相同**（都用 `unlocked_*`），所以这里不是新政策，
    而是让已经存在的规则在读路径也生效 —— 正是本项目第 10 节第 1 条
    「同一个业务判断有两份实现就一定会漂移」的反面：这次是**只写了一份**。

    返回 `(title_id, frame_id, card_bg_id)`（失效项已换成默认值）。
    """
    # 称号：默认是空串（= 不展示），不是池子里的某一项
    tid = title_id if isinstance(title_id, str) else ''
    if tid and tid not in unlocked_titles(stats):
        tid = ''
    fid = frame_id if isinstance(frame_id, str) else ''
    if fid not in unlocked_frames(stats):
        fid = DEFAULT_FRAME_ID
    bid = card_bg_id if isinstance(card_bg_id, str) else ''
    if bid not in unlocked_card_bgs(stats):
        bid = DEFAULT_CARD_BG_ID
    return tid, fid, bid


# ---------------------------------------------------------------------------
# 特权（user_perks 表里的字符串）
# ---------------------------------------------------------------------------
# 这两个字符串是**唯一的一份**定义：db 层只存字符串，api 层用它读表/注入标记。
PERK_UNLOCK_ALL = 'unlock_all_cosmetics'   # 称号 / 头像框 / 名片底色 全部解锁
PERK_RAINBOW_NAME = 'rainbow_name'         # 彩虹渐变名字（别人也看得到，别人拿不到）
PERK_LEVEL_101 = 'level_101'               # 等级上限 101（普通账号封顶 100）

VALID_PERKS = (PERK_UNLOCK_ALL, PERK_RAINBOW_NAME, PERK_LEVEL_101)

# 注入进 stats 的标记键（前缀下划线避免与 users 表的真实列重名）
UNLOCK_ALL_FLAG = '_unlock_all_cosmetics'


def has_unlock_all(stats):
    """该账号是否持有"外观全解锁"特权（api 层注入的标记）。"""
    stats = stats if isinstance(stats, dict) else {}
    return bool(stats.get(UNLOCK_ALL_FLAG))


# ---------------------------------------------------------------------------
# 池子查询小工具（接口层用）
# ---------------------------------------------------------------------------
def is_valid_title(tid):
    return tid in _BY_ID['titles']


def is_valid_tag(tid):
    return tid in _BY_ID['tags']


def is_valid_frame(fid):
    return fid in _BY_ID['frames']


def is_valid_card_bg(bid):
    return bid in _BY_ID['card_bgs']


def title_name(tid):
    """称号 id → 名称。空 id 表示不展示，返回空串。"""
    entry = _BY_ID['titles'].get(tid)
    return entry['name'] if entry else ''


def tag_name(tid):
    entry = _BY_ID['tags'].get(tid)
    return entry['name'] if entry else ''


def frame_name(fid):
    entry = _BY_ID['frames'].get(fid)
    return entry['name'] if entry else ''


def card_bg_name(bid):
    entry = _BY_ID['card_bgs'].get(bid)
    return entry['name'] if entry else ''


def catalog(stats):
    """给接口层用的完整池子 + 解锁状态（计划 §2.3 的 `profile.catalog` 形状）。

    titles / frames / card_bgs 每项：{id, name, desc, unlocked, requirement}
    tags 每项：{id, name}

    ⚠️ 下发字段是**白名单展开**，不是 `{**item}`。段位解锁项在池子里多带一个
    `rank_tier`（内部阈值，前端用不着），直接展开会把它漏给前端 ——
    而契约只有 5 个键（`tests/test_profile_card.py` 就是按这 5 个断言的）。
    `requirement` 文案里已经写明「段位达到 船长」，前端要显示的信息不缺。
    """
    title_ok = unlocked_titles(stats)
    frame_ok = unlocked_frames(stats)
    bg_ok = unlocked_card_bgs(stats)

    def dump(pool, unlocked):
        out = []
        for item in pool:
            out.append({'id': item['id'], 'name': item['name'], 'desc': item['desc'],
                        'requirement': item['requirement'],
                        'unlocked': item['id'] in unlocked})
        return out

    return {
        'titles': dump(TITLES, title_ok),
        'tags': [dict(t) for t in TAGS],
        'frames': dump(FRAMES, frame_ok),
        'card_bgs': dump(CARD_BGS, bg_ok),
    }


# ---------------------------------------------------------------------------
# 保存校验
# ---------------------------------------------------------------------------
WRITABLE_FIELDS = ('title_id', 'tags', 'status_text', 'frame_id', 'card_bg_id',
                   'show_stats', 'show_fav_cards', 'show_history', 'show_guestbook',
                   'show_rank', 'friend_requests_open')

# ⚠️ `show_guestbook`（留言板公开）是第 3 批加的**第四个展示开关**。
# 它走的是与另外三个完全相同的通道（`POST /api/profile/card`，9 个字段全发），
# 而不是单独开一个接口 —— 理由就是下面那条规矩：允许缺字段 = 保持原值
# 会变成"保存了但没生效"这种最难查的静默失败；留言板隐私属于同一类展示开关，
# 就该跟另外三个同进同出。默认 1 = 公开（计划 §3.4）。
#
# `show_rank`（段位是否公开）是段位批加的**第五个**，走完全相同的路：
# 载荷 9 → 10 字段。同样默认 1 = 公开。
# `friend_requests_open`（是否允许别人加我好友）是好友批加的，**复用同一套开关通道**，
# 但语义上它**不是展示开关**（管的是社交权限，不进 `public_stats`）。
# 之所以不另开一套：这五个 `_to_flag` 归一化 + "缺字段一律拒绝"的规矩已经跑熟三批，
# 再抄一份只会多一处会漂移的实现。
_FLAG_KEYS = ('show_stats', 'show_fav_cards', 'show_history', 'show_guestbook', 'show_rank',
              'friend_requests_open')

# 展示开关的文案（错误提示里用中文键名，别把 snake_case 甩给玩家）
_FLAG_LABELS = {
    'show_stats': '战绩展示',
    'show_fav_cards': '最爱用的卡展示',
    'show_history': '对局历史公开',
    'show_guestbook': '留言板公开',
    'show_rank': '段位公开',
    'friend_requests_open': '允许他人加我好友',
}


def normalize_status(text):
    """一句话状态：去掉控制字符 → 去掉首尾空白 → 截断到 30 字。

    控制字符（\\x00 等）是前端 `innerText` 渲染不出来、却能进库的脏数据，
    这里统一清掉；不报错（设计稿 §4：超出截断、清掉控制字符）。
    """
    if not isinstance(text, str):
        return ''
    cleaned = ''.join(ch for ch in text if ch == '\n' or ord(ch) >= 32)
    cleaned = cleaned.replace('\n', ' ').strip()
    return cleaned[:MAX_STATUS_LEN]


def _to_flag(value):
    """0/1 归一化。无法识别返回 None（调用方据此报错，不静默降级）。"""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, str) and value.strip() in ('0', '1'):
        return int(value.strip())
    return None


def validate_payload(payload, stats):
    """逐项校验一次保存请求。

    返回 `(已归一化的可写入字段, 错误列表)`：
      · 错误非空 → 调用方必须**拒绝整次保存**，且此时第一个返回值是 `{}`
        （结构上就不给"部分写入"留口子）；
      · 归一化（截断 / 去重 / 去控制字符 / 0-1 化）不算错误。

    规则见设计稿 §4 与计划 §2.4，逐条：

    | 字段 | 规则 | 违规 |
    | --- | --- | --- |
    | `title_id` | 空串 = 不展示；否则必须在池内**且已解锁** | 拒绝 |
    | `tags` | 数组、去重、≤3 个、元素在池内 | 池外拒绝 / 超出丢弃 |
    | `status_text` | ≤30 字，去控制字符与首尾空白 | 截断（不报错） |
    | `frame_id` / `card_bg_id` | 池内且已解锁 | 拒绝 |
    | `show_*` | 0 / 1 | 拒绝 |

    ⚠️ 11 个字段**必须全部出现**在请求体里（第 3 批加到 9 个，
    段位批加到 10 个 —— 多了 `show_rank`；好友批加到 11 个 —— 多了
    `friend_requests_open`）。缺字段一律拒绝并点名，
    而不是"保持原值"—— 后者会变成"保存了但没生效"这种最难查的静默失败。
    """
    if not isinstance(payload, dict):
        return {}, ['请求体必须是 JSON 对象']

    missing = [k for k in WRITABLE_FIELDS if k not in payload]
    if missing:
        return {}, ['缺少字段：' + '、'.join(missing)]

    errors = []
    fields = {}

    def _pick_owned(pid, pool_name, unlocked, name_of, allow_empty=False):
        """称号 / 头像框 / 名片底色的公共校验（三处规则一致，就只写一份）。"""
        if not isinstance(pid, str):
            errors.append(f'{pool_name}格式不正确')
            return None
        pid = pid.strip()
        if pid == '' and allow_empty:
            return ''            # 称号允许留空 = 不展示
        if not pid:
            errors.append(f'请选择一个{pool_name}')
            return None
        if pid not in unlocked:
            if name_of(pid):
                errors.append(f'未解锁的{pool_name}：{name_of(pid)}')
            else:
                errors.append(f'未知的{pool_name}：{pid}')
            return None
        return pid

    title_id = _pick_owned(payload.get('title_id'), '称号',
                           unlocked_titles(stats), title_name, allow_empty=True)
    if title_id is not None:
        fields['title_id'] = title_id

    tags = payload.get('tags')
    if not isinstance(tags, list):
        errors.append('标签必须是数组')
    else:
        picked = []
        for raw in tags:
            if not isinstance(raw, str):
                errors.append('标签格式不正确')
                continue
            tid = raw.strip()
            if not tid:
                continue                      # 空串直接忽略，不算错
            if not is_valid_tag(tid):
                errors.append(f'未知的标签：{tid}')
                continue
            if tid not in picked:
                picked.append(tid)
        fields['tags'] = picked[:MAX_TAGS]    # 超出的丢掉（设计稿 §4）

    status = payload.get('status_text')
    if status is None:
        status = ''
    if not isinstance(status, str):
        errors.append('一句话状态必须是文本')
    else:
        fields['status_text'] = normalize_status(status)

    frame_id = _pick_owned(payload.get('frame_id'), '头像框',
                           unlocked_frames(stats), frame_name)
    if frame_id is not None:
        fields['frame_id'] = frame_id

    card_bg_id = _pick_owned(payload.get('card_bg_id'), '名片底色',
                             unlocked_card_bgs(stats), card_bg_name)
    if card_bg_id is not None:
        fields['card_bg_id'] = card_bg_id

    for key in _FLAG_KEYS:
        flag = _to_flag(payload.get(key))
        if flag is None:
            errors.append(f'{_FLAG_LABELS[key]}只能是 0 或 1')
        else:
            fields[key] = flag

    if errors:
        # 拒绝整次保存：连带把已归一化的字段清空，调用方想写也写不进去
        return {}, errors
    return fields, []
