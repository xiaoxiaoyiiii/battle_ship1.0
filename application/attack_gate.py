"""攻击动作进入战斗结算前的统一门禁。"""


class AttackGate:
    def __init__(self, *, frozen_reason, action_wait, cell_in_shenwei_hole):
        self._frozen_reason = frozen_reason
        self._action_wait = action_wait
        self._cell_in_shenwei_hole = cell_in_shenwei_hole

    def validate(self, room, attacker_id, target_x, target_y):
        if room.state == 'game_over':
            return {'error': '对局已结束'}
        frozen = self._frozen_reason(room, attacker_id)
        if frozen:
            return {'error': frozen}
        try:
            fx, fy = float(target_x), float(target_y)
        except (TypeError, ValueError):
            return {'error': '非法的攻击坐标'}
        if not (fx.is_integer() and fy.is_integer()):
            return {'error': '非法的攻击坐标'}
        target_x, target_y = int(fx), int(fy)
        if not (0 <= target_x <= 5 and 0 <= target_y <= 5):
            return {'error': '攻击坐标超出棋盘范围'}
        if attacker_id != room.current_attacker:
            return {'error': '还没到你的攻击回合'}
        if room.current_phase != 'battle':
            return {'error': '当前不是战斗阶段'}
        if room.chain or room.chain_waiting:
            return {'error': '连锁结算中，请等待响应窗口结束后再攻击'}
        waiting = self._action_wait(room, attacker_id)
        if waiting:
            return {'error': waiting}
        if room.attacks_remaining <= 0:
            return {'error': '本回合攻击次数已用尽'}
        if (target_x, target_y) in self.attacked_cells(room, attacker_id):
            return {'error': '你已经攻击过这个位置了'}
        defender_id = next(p for p in room.players if p != attacker_id)
        if self._cell_in_shenwei_hole(room, defender_id, target_x, target_y):
            return {'error': '该区域已被神威！扣掉，无法攻击'}
        return {
            'target_x': target_x,
            'target_y': target_y,
            'defender_id': defender_id,
        }

    @staticmethod
    def attacked_cells(room, player_id):
        player = (getattr(room, 'players', None) or {}).get(player_id)
        if player is None:
            return set()
        return {(attack.x, attack.y)
                for attack in (getattr(player, 'attacks', None) or [])}

    @staticmethod
    def available_cells(room, player_id):
        if player_id not in (getattr(room, 'players', None) or {}):
            return []
        attacked = AttackGate.attacked_cells(room, player_id)
        return [(x, y) for x in range(6) for y in range(6)
                if (x, y) not in attacked]
