"""旧对局房间的可变状态与牌堆操作；Socket 发送留在入口适配类。"""

from __future__ import annotations

import random
import time
from typing import Any


class RoomState:
    id: str
    players: dict[str, Any]
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
    magic_discard: list[Any]
    magic_deck: list[Any]
    chain: list[dict[str, Any]]
    chain_waiting: bool
    chain_timer: float
    chain_window: str | None
    chain_passes: int
    chain_display_token: int | None
    chain_display_deadline: float | None
    last_attack: Any
    def __init__(self, room_id, hidden_card_names):
        self._hidden_card_names = hidden_card_names
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
        # ★ 战绩模式批：这间房是不是**匹配**出来的（`handle_find_match` 配对成功时置 True）。
        #   按 CLAUDE.md 第 10.11 条「新增房间级状态三件齐」：
        #     ① 这里初始化 ② 消费点 = `_match_history_mode`（战绩落库时的 `matches.mode`）
        #     ③ 回归 = tests/test_match_mode.py（含源码级穷举守卫 + 三条非匹配路径的反例）
        #   ⚠️ 存在的理由：`matches` 表原先只有 id / winner / loser / timestamp，
        #     "这一局是排位 / 匹配 / 人机 / 自定义房"**根本没存**，界面只能靠 id 猜人机
        #     （`isAiOpponent`）—— 那是猜测不是记录。有了它才谈得上如实标出模式。
        #   ⚠️ 它是"**事实**"而不是"从 `room.players` 的 key 形状反推"：key 有两套约定
        #     （自定义房 = user_id / 匹配房 = 入座 sid），历史上漂移过一次，
        #     形状判据一旦漂移就是"匹配局静默标成自定义局"，零报错。
        self.matchmade = False
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
        # ★ 2026-09-23 新增房间级状态三件齐（CLAUDE.md 第 10.11 条）：
        #   ① 这里初始化 ② 消费点 = `_finish_chain` / `_chain_display_then_resolve` /
        #   `_sweep_overdue_chain_display`；任何一次 `resolve_chain` 都会清掉它们
        #   ③ 回归 = tests/test_chain_display_delay.py
        # 含义见 `CHAIN_DISPLAY_DELAY_SECONDS`：结算前那段固定展示停留的代际令牌
        # 与兜底截止时刻（`time.monotonic()`）。None = 当前没有待结算的停留。
        self.chain_display_token = None
        self.chain_display_deadline = None
        self.last_attack = None  # 记录最后一次攻击的信息
        self.game_logs: list[dict[str, Any]] = []
        # ★ 2026-09-23（回放批）新增房间级状态三件齐（CLAUDE.md 第 10.11 条）：
        #   ① 这里初始化 ② 消费点 = `replay.note` / `replay.note_action` /
        #   `replay.note_board_reset` / `replay.note_ship_lost` /
        #   `replay.note_ship_returned` / `replay.note_board_replaced`（喂）
        #   与 `replay.finalize` + `replay.reset`（收）
        #   ③ 回归 = tests/test_replay_recorder.py / tests/test_replay_ship_loss.py
        # 形状见 replay._state（steps / 三条时间线 / board_resets / nodes / 截断标记）。
        # ⚠️ 每局常驻 ≤30 KB，`_finalize_match` 落库后**立刻置空**（契约 §1：服务器只有
        #    777 MB 可用内存在用 swap，回放绝不进内存缓存）。
        self.replay: dict[str, Any] | None = None
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
        # ★ 2026-09-22（第 5 批）：观战棋盘"脏了"的标记（按 CLAUDE.md 第 11 条三件齐）。
        #   `True` = 本次操作改过棋盘上的格（清格 / 整块重摆），要在收尾时补发一次
        #   `spectate_board` 帧。**标记而不立刻发**的理由见 `_mark_spectate_board_dirty`：
        #   清格发生在结算中段，同一张卡后面还会改局面（复活要加船数）——
        #   立刻发就是一条半成品帧（实测帧里船数是 5、真值 6）。
        #   消费点：`_flush_spectate_board_if_dirty`（由 `emit()` 收尾调用）。
        #   回归用例：tests/test_spectate_batch5.py（疗愈 / 灵气复苏 / 败者食尘 / 回光返照）。
        self.spectate_board_dirty = False
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
        # ★ 2026-09-24：`无忧梦呓`（判定卡）**打出并通过之后**挂着的延迟拼点。
        # 结构：`{caster_id: 份数}` —— 打出后**对方的回合开始时**结算并清除。
        # 消费点：`_settle_wuyou_dream`（两个回合开始处各调一次）。
        # 回归用例：`tests/test_wuyou_dream_card.py`。
        # ⚠️ 用 dict **计数**而不是单槽：单槽会被第二张同名牌静默覆盖
        #    （CLAUDE.md 教训 #29「单槽 = 隐藏的数据丢失」）。
        # 不放 magic_temp_data：它有 8 处被整体覆写成 {}（教训 #30）。
        self.pending_wuyou_dreams: dict[str, int] = {}
        # ★ 2026-09-25：`兵粮寸断`（判定卡）的两份房间级状态。
        #   · `pending_bingliang = {caster_id: 份数}`：打出后挂着、**对方的准备阶段开始时**
        #     摇一次骰子并 pop 掉（判定只发生一次）；
        #   · `bingliang_skip_draw = {player_id: 剩余跳过次数}`：判定通过后给目标挂 2 次，
        #     在**目标接下来两个准备阶段**的摸牌处各消耗一次，用完即清。
        # 消费点：`_settle_bingliang`（两个回合开始处各调一次）
        #         + `_bingliang_consume_skip`（新大回合发放摸牌处）。
        # 回归用例：`tests/test_bingliang_card.py`。
        # ⚠️ 两份都用 dict **计数**而不是单槽（教训 #29「单槽 = 隐藏的数据丢失」）；
        #    不放 `magic_temp_data`：它有 8 处被整体覆写成 {}（教训 #30）。
        self.pending_bingliang: dict[str, int] = {}
        self.bingliang_skip_draw: dict[str, int] = {}
        # 弃牌待办的**来源卡名**（`{player_id: 卡名}`），与 `pending_dice_discard`
        # **同生共死**：谁开的待办，日志与弹窗就写谁的名字。
        # 为什么另存一张表、而不是把 `pending_dice_discard` 的值改成字典：
        # 那个字段的 True/False 被 5 处下游按**布尔直读**
        # （`_check_dice_discard_complete` 的 all() / `_dice_discard_wait_reason` /
        #   `_master_unsettled` / `tools/headless_game.py` / `handle_dice_discard_choose`
        #   的 `is not False`），改类型会一次性打穿它们。
        # 两张表的**键集合必须同步** —— 由用例钉住（教训 #1：删不掉的镜像要用测试钉）。
        self.pending_dice_discard_label: dict[str, str] = {}
        # 掉线/重连（2026-09-07 新增）
        self.disconnected = {}        # player_id -> {'deadline': float, 'token': int}（宽限期内）
        self.disconnect_seq = 0       # 掉线计时器代际令牌
        self.reconnect_tokens = {}    # player_id -> 一次性重连 token
        self.game_over_reason = None  # None | 'opponent_disconnected'
        # 本局落库后的 match_id（由 `_finalize_match` 写，见 `_game_over_payload`）。
        # 初值 None = "还没有/取不到" —— 结算 payload 据此决定带不带这个键。
        self.match_id = None

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

        # ── 观战席（实时观战第 2 批）───────────────────────────────────
        # `sid -> {'name','user_id','joined_at'}`。
        # ★★ **观众绝不写进 `room.players`** ★★ ——
        #    这是本批最重要的既成安全属性：所有写操作 handler 的鉴权都是
        #    "`player_id in room.players` + `_identity_ok`"，观众不在 players 里，
        #    于是那 90 多处写 handler 天然、无一例外地拒绝它。
        #    把观众塞进 players（哪怕只是"为了让他收到广播"）＝ 一次性废掉全部鉴权。
        #    守卫：tests/test_spectate_batch2.py 的
        #    `test_spectator_is_never_written_into_room_players`
        #    （并附"故意塞进去 → 断言变红"的元测试）。
        #
        # ⚠️ 按 CLAUDE.md 第 11 条「新增房间级状态三件齐」：
        #    ① 这里初始化；② 消费点 = `handle_spectate_join` / `handle_spectate_leave`
        #    / `handle_disconnect` / `_drop_room` / `_build_spectate_snapshot`；
        #    ③ 回归用例见 `tests/test_spectate_batch2.py`。
        self.spectators: dict[str, dict[str, Any]] = {}

        # ── 观战席聊天（实时观战第 4 批）───────────────────────────────
        # **观众**的发言频率状态。与 `quick_chat_recent` 一样住房间级
        # （模块级全局会让 A 房间的连点吃光 B 房间另一个人的额度）。
        # key 一律是**观众的 sid**（观众不在 `room.players` 里，没有 player_id）。
        #   spectate_chat_recent: sid -> [发送时间戳…]（升序，只留窗口内的）
        #   spectate_chat_last:   sid -> {'id': 上一条正文, 'ts': 时间戳}
        # 判据**不在这里** —— 复用 `quick_chat.check_rate`（教训 #1：
        # 同一个业务判断不许有第二份实现）。这里只是它的状态存放处。
        # 消费点：`handle_spectate_chat_send`（读写都只在那里）。
        self.spectate_chat_recent: dict[str, list[float]] = {}
        self.spectate_chat_last: dict[str, dict[str, Any]] = {}

    def init_player_magic(self, player_id: str, magic_cards):
        """初始化玩家魔法卡相关状态"""
        # 初始化玩家的魔法卡状态
        self.players[player_id].magic_hand = []  # 初始手牌为空

        # 仅在第一次调用时初始化全局共享魔法卡堆
        if not self.magic_deck:
            # 复制并洗牌创建全局共享卡堆。
            # 剔除 HIDDEN_CARD_NAMES（暂时隐藏的卡）：牌堆里没有 ⇒ 谁也摸不到，
            # 而卡池、结算分支、前端文案都不动。
            self.magic_deck = [c for c in magic_cards if c.name not in self._hidden_card_names()]
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
        return card  # 返回抽到的卡牌

    def discard_card(self, player_id: str, card: Any):
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
