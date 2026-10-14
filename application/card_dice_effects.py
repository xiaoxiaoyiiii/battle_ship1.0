"""命运骰子的六种结果与共享弃牌待办；传入的房间由调用方完成身份验证。"""

DICE_EFFECT_TEXT = {
    1: '复活对方的一艘战舰',
    2: '对方抽一张牌',
    3: '双方各弃一张手牌',
    4: '自己抽两张牌',
    5: '复活自己的至多两艘战舰',
    6: '对手牺牲两艘战舰',
}


class DiceEffects:
    """统一处理骰子效果、弃牌请求及确认；状态继续归属于房间。"""

    def __init__(self, *, emit, add_game_log, log_name, roll, revive,
                 alive_ships, request_ship_pick, sacrifice, ai_player_id):
        self._emit = emit
        self._add_game_log = add_game_log
        self._log_name = log_name
        self._roll = roll
        self._revive = revive
        self._alive_ships = alive_ships
        self._request_ship_pick = request_ship_pick
        self._sacrifice = sacrifice
        self._ai_player_id = ai_player_id

    def apply(self, room, caster_id, result):
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

        roll = self._roll(1, 6)
        effect_text = DICE_EFFECT_TEXT.get(roll, '')

        # 广播骰子动画 + 结果给双方（动画在前，结果文本一并下发，前端动画结束再显示文本）
        self._emit('dice_rolled', {
            'roll': roll,
            'caster': caster_id,
            'effect_text': effect_text,
        }, room=room.id)

        self._add_game_log(room,
                     f'第{room.round}回合 · {self._log_name(room, caster_id)} 使用【命运骰子】摇出 {roll} 点：{effect_text}',
                     'magic', {'caster': caster_id, 'roll': roll, 'card': '命运骰子'})

        if roll == 1:
            # 复活对方一艘（原地复活，无副作用）。对方没有沉船则不复活。
            revived = 0
            if opponent.sunken_ships:
                revived = self._revive(room, opponent, 1, reveal_to=caster_id)
            result.message = '摇出1点：' + effect_text + (
                '，对方一艘战舰复活' if revived else '，对方没有沉船，未复活')
        elif roll == 2:
            drawn = room.draw_card(opponent_id)
            result.message = '摇出2点：' + effect_text + (
                '，对方抽了一张牌' if drawn else '，但对方未能抽牌（牌堆空或被禁止抽卡）')
        elif roll == 3:
            # 双方各弃一张：无牌者跳过；AI 自动弃第一张；人类登记待办
            self.start_discard(room, caster_id, opponent_id)
            result.message = '摇出3点：' + effect_text + '，等待双方选择弃牌'
        elif roll == 4:
            drawn = 0
            for _ in range(2):
                if room.draw_card(caster_id) is not None:
                    drawn += 1
            result.message = f'摇出4点：{effect_text}（实际抽到{drawn}张）'
        elif roll == 5:
            count = min(2, len(caster.sunken_ships))
            revived = self._revive(room, caster, count, reveal_to=opponent_id) if count > 0 else 0
            result.message = '摇出5点：' + effect_text + (
                f'，自己复活了{revived}艘战舰' if revived else '，自己没有沉船，未复活')
        elif roll == 6:
            # 对方牺牲两艘：复用 ship_pick 队列，reason='dice_sacrifice'。
            # 人类入队两次（allow_duplicate=True 跳过同 reason 去重，否则第二次被吞）；
            # AI 由 _request_ship_pick 自动选并立即执行。
            alive = self._alive_ships(opponent)
            need = min(2, len(alive))
            sacrificed = 0
            for _ in range(need):
                picked = self._request_ship_pick(room, opponent_id, 'dice_sacrifice',
                                            '命运骰子：请点选一艘战舰牺牲',
                                            allow_duplicate=True)
                if picked is not None:
                    self._sacrifice(room, opponent_id, picked, 'dice_sacrifice')
                    sacrificed += 1
            if need == 0:
                result.message = '摇出6点：' + effect_text + '，但对方没有可牺牲的战舰'
            elif sacrificed == need:
                result.message = f'摇出6点：{effect_text}（对方已牺牲{sacrificed}艘）'
            else:
                result.message = '摇出6点：' + effect_text + '，等待对方点选牺牲的战舰'

    def start_discard(self, room, caster_id, opponent_id, only_player=None,
                            card_name='命运骰子'):
        """命运骰子摇到3：让双方各弃一张手牌。

        · 无手牌的玩家直接跳过；
        · AI 自动弃第一张；
        · 人类登记 room.pending_dice_discard[pid] = False 并 emit 'dice_discard_request'。

        ★ 2026-09-24 两条参数（都是为 `无忧梦呓` 加的，**不改既有语义**）：

        * `only_player` —— 只让**这一位**弃牌。`无忧梦呓` 的「对方必须弃置一张手牌」
          只针对对方一个人，走的是同一条链路（作者裁定：复用，不另起一套）。
          传 `None` = 原有行为（双方各弃一张），命运骰子的调用点未受影响。
        * `card_name` —— 弹窗文案与日志里的来源卡名。默认仍是 `命运骰子`
          → 既有文案逐字不变。

        ⚠️ **不再无条件 `room.pending_dice_discard = {}`**（这是一处真 bug 的修复）：
           那个字段是**房间级单槽**，旧写法会把进行中的待办静默抹掉。
           真会发生：命运骰子摇到 3 时**没轮到的那一方**可以带着未完成的待办
           把回合交出去（`_dice_discard_wait_reason` 只冻他自己），
           随后 `无忧梦呓` 在对方回合开始时再开一次 —— 两条待办叠在同一时刻，
           旧写法会让先那条无声消失（正是作者对 `_start_dice_discard` 的预警）。
           现在改成**并入**：只写自己要写的那几个键，别人的原样留着。
        """
        pending = getattr(room, 'pending_dice_discard', None)
        if not isinstance(pending, dict):
            pending = {}
            room.pending_dice_discard = pending
        labels = getattr(room, 'pending_dice_discard_label', None)
        if not isinstance(labels, dict):
            labels = {}
            room.pending_dice_discard_label = labels

        targets = (only_player,) if only_player else (caster_id, opponent_id)
        ai_id = self._ai_player_id(room) if getattr(room, 'is_ai_room', False) else None

        for pid in targets:
            player = room.players[pid]
            # 这位玩家已经有一张没弃完：不重复开窗、也不改写那条待办的来源名
            # （他眼前开着的弹窗写着第一次那张卡，改写会让"点了之后日志说的是另一张卡"）。
            # 代价是两次弃牌义务合并成"弃一张"——既有链路的已知收窄，
            # 单槽布尔存不下计数，要修得改 `pending_dice_discard` 的值类型（会打穿 5 处下游）。
            if pending.get(pid) is False:
                continue
            if not player.magic_hand:
                # 无牌可弃：直接标记完成，不弹窗
                pending[pid] = True
                labels[pid] = card_name
                continue
            if pid == ai_id:
                # AI 自动弃第一张（与教皇旨意弃卡同一口径：随机选没意义，取首张）
                discarded = player.magic_hand.pop(0)
                room.magic_discard.append(discarded)
                self._emit('hand_updated', {'hand': player.magic_hand}, to=player.sid)
                self._add_game_log(room,
                             f'第{room.round}回合 · {self._log_name(room, pid)} 因{card_name}弃置「{discarded.name}」',
                             'magic', {'player': pid, 'card': discarded.name,
                                       'reason': 'dice_discard', 'source': card_name})
                pending[pid] = True
                labels[pid] = card_name
            else:
                pending[pid] = False
                labels[pid] = card_name
                self._emit('dice_discard_request', {
                    'message': f'{card_name}：请选择一张手牌弃置',
                    'reason': 'dice_discard',
                    'card': card_name,
                }, to=player.sid)

        # 双方都无需弃（都没手牌 / 都是 AI）→ 立即收尾，别留下空待办挂着
        self.complete_discard(room)

    def complete_discard(self, room):
        """双方都完成弃牌后清掉待办并广播结束。"""
        pending = getattr(room, 'pending_dice_discard', None)
        if not isinstance(pending, dict) or not pending:
            return
        if all(pending.values()):
            room.pending_dice_discard = {}
            # 待办没了，来源名跟着清 —— 两张表同期"非空"（键集合同步由用例钉住）
            room.pending_dice_discard_label = {}
            self._emit('dice_discard_complete', {}, room=room.id)

    def choose_discard(self, room, player_id, card_index):
        pending = getattr(room, 'pending_dice_discard', None)
        if not isinstance(pending, dict) or pending.get(player_id) is not False:
            return {'status': 'error', 'message': '当前没有等待你弃牌的魔法效果'}

        labels = getattr(room, 'pending_dice_discard_label', None)
        source = '命运骰子'
        if isinstance(labels, dict):
            source = labels.get(player_id) or source

        player = room.players[player_id]
        if not player.magic_hand:
            # 没牌可弃：直接完成
            room.pending_dice_discard[player_id] = True
            self.complete_discard(room)
            return {'status': 'success', 'message': '没有手牌可弃，已跳过'}

        try:
            idx = int(card_index)
        except (TypeError, ValueError):
            return {'status': 'error', 'message': '无效的卡牌位置'}
        if not (0 <= idx < len(player.magic_hand)):
            return {'status': 'error', 'message': '无效的卡牌位置'}

        discarded = player.magic_hand.pop(idx)
        room.magic_discard.append(discarded)
        self._emit('hand_updated', {'hand': player.magic_hand}, to=player.sid)
        self._add_game_log(room,
                     f'第{room.round}回合 · {self._log_name(room, player_id)} 因{source}弃置「{discarded.name}」',
                     'magic', {'player': player_id, 'card': discarded.name,
                               'reason': 'dice_discard', 'source': source})

        room.pending_dice_discard[player_id] = True
        self.complete_discard(room)
        return {'status': 'success', 'message': f'已弃置「{discarded.name}」'}
