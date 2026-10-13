"""按玩家管理选船待办、优先级仲裁与重连投影。"""

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
    # 命运骰子摇到 6：让对方牺牲两艘。同样是**卡牌自身结算**的一部分，
    # 略低于神之宣告（它是一次性随机效果，施法者自己的结算流程更短）
    'dice_sacrifice': 70,
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
    '命运骰子': 'dice_sacrifice',
    '守株待兔': 'trap_setup',
}


# ⚠️ 2026-09-21：`handle_confirm_sacrifice` 走到这里 = 玩家点船格触发牺牲。
# 只有 reason **确实要牺牲船**的才允许走到 `_do_demon_contract_sacrifice`。
# 不在这个白名单里的 reason（如 `shield_choice` 仁王之盾）必须显式拒绝并保留队列条目，
# 让玩家走正确的提交入口（仁王之盾走 `confirm_magic_target` 的 `ship_indices`）。
# 旧实现没有白名单 → 仁王之盾的护盾选择被 fall-through 走成"船牺牲"，
# 正是作者报的"第一次点击直接让自己的船牺牲了 / 第二次弹当前没有待牺牲的船"。
_SACRIFICE_REASONS = frozenset({
    'demon_contract',     # 恶魔契约：场地效果
    'divine_decree',      # 神之宣告：自身结算
    'dice_sacrifice',     # 命运骰子 6 点：对方牺牲两艘
    'trap_sacrifice',     # 守株待兔：踩陷阱者额外牺牲
})


_SHIP_PICK_LABELS = {
    'demon_contract': '恶魔契约',
    'divine_decree': '神之宣告',
    'kraken_eye': '克苏鲁之眼',
    'shield_choice': '仁王之盾',
    'trap_setup': '守株待兔',
    'trap_sacrifice': '守株待兔',
    'dice_sacrifice': '命运骰子',
}


def _ship_pick_priority(reason) -> int:
    """取某类选船效果的优先级；未登记的一律 0（排最后，不报错）。"""
    try:
        return int(SHIP_PICK_PRIORITY.get(str(reason), 0))
    except (TypeError, ValueError):
        return 0


class ShipSelection:
    """队列保存在房间中；消息投递、存活查询与 AI 策略由运行时注入。"""

    def __init__(self, *, emit, alive_ships, is_ai_player, choose_ai_ship):
        self._emit = emit
        self._alive_ships = alive_ships
        self._is_ai_player = is_ai_player
        self._choose_ai_ship = choose_ai_ship

    def for_player(self, room, player_id) -> list:
        """该玩家当前挂着的全部待选项（按优先级降序、同优先级按 seq 升序）。"""
        picks = getattr(room, 'pending_ship_picks', None)
        if not isinstance(picks, list) or not player_id:
            return []
        mine = [p for p in picks if isinstance(p, dict) and p.get('player') == player_id]
        mine.sort(key=lambda p: (-_ship_pick_priority(p.get('reason')), int(p.get('seq') or 0)))
        return mine

    def top(self, room, player_id):
        """该玩家**当前应该处理**的那一项（队列里优先级最高的）；没有则 None。"""
        mine = self.for_player(room, player_id)
        return mine[0] if mine else None

    def emit_request(self, room, entry) -> None:
        """把某一项待选下发给对应玩家（内部用；失败绝不影响对局）。"""
        try:
            if entry.get('silent'):
                return                          # 静默登记项：前端有自己的选区 UI
            player = room.players.get(entry.get('player'))
            if player is None or not getattr(player, 'sid', None):
                return
            alive = self._alive_ships(player)
            if not alive:
                return
            self._emit('sacrifice_request', {
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

    def register_silent(self, room, player_id, reason, message) -> None:
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

    def dispatch(self, room, player_id) -> None:
        """把该玩家队列里优先级最高的那一项（重新）下发给前端。

        幂等：没有待选时不发任何事件（无事也发会让客户端白弹一次提示）。
        """
        entry = self.top(room, player_id)
        if entry is not None:
            self.emit_request(room, entry)

    def consume(self, room, player_id, reason=None) -> bool:
        """消费该玩家**栈顶**那一项，然后自动投递剩下的下一项。

        `reason` 给出时只消费匹配的那一项（防止"点了一下却把别的效果也吃掉"）。
        返回是否真的消费掉了。
        """
        picks = getattr(room, 'pending_ship_picks', None)
        if not isinstance(picks, list):
            return False
        top = self.top(room, player_id)
        if top is None:
            return False
        if reason is not None and top.get('reason') != reason:
            return False
        try:
            picks.remove(top)
        except ValueError:
            return False                       # 并发下已被消费，视作无事发生
        self.dispatch(room, player_id)   # 还有就接着弹下一项
        return True

    def clear(self, room, player_id=None) -> None:
        """清空待选队列（`player_id` 为 None 时清全部）。终局 / 重摆棋盘时用。"""
        picks = getattr(room, 'pending_ship_picks', None)
        if not isinstance(picks, list):
            return
        if player_id is None:
            room.pending_ship_picks = []
        else:
            room.pending_ship_picks = [
                p for p in picks if not (isinstance(p, dict) and p.get('player') == player_id)]

    def cancel_reason(self, room, reason) -> list:
        """撤掉所有 reason 匹配的待选条目；返回被撤掉的条目列表（含 player 字段）。

        用于"某个效果整体作废"的场景：例如恶魔契约场地被顶替后，挂在队列里的
        demon_contract 待选必须一起撤掉 —— 否则玩家会接到一个永远等不到的牺牲请求，
        而它的优先级又最高（100），会把后面所有低优先级选船卡（如仁王之盾 40）堵死，
        表现就是作者报的"场上根本没有恶魔契约在生效，但点船格还是被当成牺牲"。

        撤掉后会向受影响的玩家 emit `sacrifice_cancelled`，让前端撤回 sacrifice 弹窗：
        否则前端那个 `selectingOnBoard = true` 会一直挂着，把后续 createBoardAreaPicker
        等点选器全部挡在外面（"请先完成恶魔契约的点选"那条提示会反复弹）。
        """
        if not reason:
            return []
        picks = getattr(room, 'pending_ship_picks', None)
        if not isinstance(picks, list):
            return []
        removed = [p for p in picks
                   if isinstance(p, dict) and p.get('reason') == reason]
        if not removed:
            return []
        room.pending_ship_picks = [
            p for p in picks if not (isinstance(p, dict) and p.get('reason') == reason)]
        # 通知受影响的玩家：那个等待你点船的效果已经没了，撤回弹窗
        # （同一个玩家可能有多项被撤，去重后只发一次）
        affected_sids = set()
        for p in removed:
            pid = p.get('player')
            if pid and pid in room.players:
                sid = room.players[pid].sid
                if sid:
                    affected_sids.add(sid)
        for sid in affected_sids:
            try:
                self._emit('sacrifice_cancelled', {'reason': reason}, to=sid)
            except Exception:
                pass
        return removed

    def blocked_reason(self, room, player_id, card_name) -> str:
        """打这张卡是否被"更高优先级的待选"挡住。返回拒绝文案（空串 = 放行）。

        ⚠️ **只拦选船类卡**：非选船卡（轰炸等）任何时候都放行 ——
           闸门开大了会把正常出牌也堵死（`_action_wait_reason` 那种全局门禁不适合这里）。
        """
        reason_wanted = _SHIP_PICK_CARDS.get(str(card_name or ''))
        if not reason_wanted:
            return ''
        top = self.top(room, player_id)
        if top is None:
            return ''
        if _ship_pick_priority(top.get('reason')) <= _ship_pick_priority(reason_wanted):
            return ''
        pending_name = _SHIP_PICK_LABELS.get(str(top.get('reason')), '一个待处理的选船效果')
        return f'请先完成「{pending_name}」的选船，再使用这张卡'

    def pending_payload(self, room, player_id):
        """重连快照：该玩家当前该处理的那一项待选（没有/静默项 → None）。"""
        top = self.top(room, player_id)
        if top is None or top.get('silent'):
            return None
        return {k: top.get(k) for k in ('reason', 'message', 'priority')}

    def pending_ships(self, room, player_id, player):
        """重连快照：该玩家可点选的**活船**名单（与下发的候选保持一致）。

        只给活船 —— 沉船还留在 `player.ships` 里，混进去会让重连后又点到自己的沉船。
        """
        top = self.top(room, player_id)
        if top is None or top.get('silent'):
            return []
        return [{'positions': [{'x': q.x, 'y': q.y} for q in sh.positions]}
                for sh in self._alive_ships(player)]

    def request(self, room, chooser_id, reason, message, allow_duplicate=False):
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

        alive = self._alive_ships(chooser)
        if not alive:
            return None

        if self._is_ai_player(room, chooser_id):
            return self._choose_ai_ship(room, chooser_id, reason, alive)

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
                    self.dispatch(room, chooser_id)
                    return None

        room.ship_pick_seq = int(getattr(room, 'ship_pick_seq', 0) or 0) + 1
        picks.append({
            'player': chooser_id,
            'reason': reason,
            'message': message,
            'priority': _ship_pick_priority(reason),
            'seq': room.ship_pick_seq,
        })
        self.dispatch(room, chooser_id)
        return None
