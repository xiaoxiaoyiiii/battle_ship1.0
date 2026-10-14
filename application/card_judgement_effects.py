"""三张判定魔法卡的登记与统一分派。"""


class JudgementEffects:
    def __init__(self, *, opponent_of, log_name, apply_dice):
        self._opponent_of = opponent_of
        self._log_name = log_name
        self._apply_dice = apply_dice

    def register_wuyou_dream(self, room, caster_id, result):
        opponent_id = self._opponent_of(room, caster_id)
        pending = getattr(room, 'pending_wuyou_dreams', None)
        if not isinstance(pending, dict):
            pending = {}
            room.pending_wuyou_dreams = pending
        pending[caster_id] = int(pending.get(caster_id) or 0) + 1
        result.message = (
            '无忧梦呓生效，'
            f'{self._log_name(room, opponent_id)} 的下一个回合开始时拼点判定'
        )

    def register_bingliang(self, room, caster_id, result):
        opponent_id = self._opponent_of(room, caster_id)
        pending = getattr(room, 'pending_bingliang', None)
        if not isinstance(pending, dict):
            pending = {}
            room.pending_bingliang = pending
        pending[caster_id] = int(pending.get(caster_id) or 0) + 1
        result.message = (
            '兵粮寸断生效，'
            f'{self._log_name(room, opponent_id)} 的准备阶段开始时判定'
        )

    def apply(self, room, caster_id, card, result):
        if card.name == '命运骰子':
            self._apply_dice(room, caster_id, result)
        elif card.name == '无忧梦呓':
            self.register_wuyou_dream(room, caster_id, result)
        elif card.name == '兵粮寸断':
            self.register_bingliang(room, caster_id, result)
        else:
            result.success = False
            result.message = f'未实现的判定魔法卡：{card.name}'
