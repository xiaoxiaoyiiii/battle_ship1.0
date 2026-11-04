"""唯一管理员的对局测试入口；复用真实玩法，隔离测试结算。"""
from __future__ import annotations

from ..domain.room import RoomState, RoomPhase
from ..domain import battle as battle_rules
from ..infra.logging import get_logger
from .rooms import Connection
from .priority import room_action

logger = get_logger('admin_console')

# 仅允许明确登记的局内方法，不接收任意 Python 方法名或可执行代码。
NORMAL_ACTIONS = {
    'place_ships': ('gameplay', '布船'), 'cancel_placement': ('gameplay', '取消布船'),
    'rps_choice': ('gameplay', '猜拳'), 'enter_battle_phase': ('gameplay', '进入战斗'),
    'enter_end_phase': ('gameplay', '进入结束'), 'end_turn': ('gameplay', '结束回合'),
    'attack': ('battle', '指定格炮击'), 'surrender': ('battle', '投降'),
    'use_magic_card': ('magic', '使用魔法卡'), 'select_magic_target': ('magic', '选择卡牌目标'),
    'confirm_magic_target': ('magic', '确认卡牌目标'), 'get_magic_temp_data': ('magic', '查看待选数据'),
    'get_discard_pile': ('magic', '查看弃牌堆'), 'cancel_magic_selection': ('magic', '取消选牌'),
    'confirm_reinforcement_position': ('magic', '确认补舰位置'), 'confirm_sacrifice': ('magic', '确认献祭'),
    'dice_discard_choose': ('magic', '骰子弃牌选择'), 'confirm_shenji_declare': ('magic', '确认神迹宣告'),
    'remove_field_magic': ('magic', '移除场地魔法'), 'papal_discard': ('magic', '教皇弃牌换攻击'),
    'chain_animation_complete': ('magic', '完成连锁演出'),
    'chain_response': ('magic', '响应连锁'), 'papal_attack': ('magic', '教皇攻击旧入口'),
    'set_decline_priority': ('rooms', '设置自动放弃阶段响应'),
}
TOOLS = {
    'inspect': '读取双方船位 / 手牌 / 连锁状态', 'draw_card': '获得指定卡牌',
    'all_cards': '获得全部卡牌', 'clear_effects': '清空效果与双方手牌',
    'win': '直接判自己胜利', 'lose': '直接判自己失败', 'auto_attack': '自动炮击',
    'own_ships': '重新生成己方舰队', 'opponent_ships': '重新生成对方舰队',
    'next_phase': '强制推进阶段', 'reset': '重置对局', 'set_attacks': '设置攻击次数',
    'set_phase': '设置当前阶段', 'ai_rps': '指定 AI 猜拳', 'chain_demo': '演示多区域连锁',
    'priority_response': '响应阶段转换询问',
}


def catalog(magic):
    return {'actions': [{'id': action, 'label': label, 'group': 'test'} for action, label in TOOLS.items()]
            + [{'id': action, 'label': label, 'group': 'normal'} for action, (_, label) in NORMAL_ACTIONS.items()],
            'cards': magic.debug_get_magic_cards_list()['magic_cards']}


def integer(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'数值必须是 {minimum}～{maximum} 的整数')
    return value


class AdminConsole:
    def __init__(self, auth, rooms, battle, magic, gameplay):
        self.auth, self.rooms, self.battle, self.magic, self.gameplay = auth, rooms, battle, magic, gameplay

    async def execute(self, user_id, room_id, action, params):
        if not self.auth.is_admin(user_id):
            raise PermissionError('仅唯一管理员可操作')
        if action not in TOOLS and action not in NORMAL_ACTIONS:
            raise ValueError('未知控制台动作')
        if not isinstance(params, dict):
            raise ValueError('动作参数必须是 JSON 对象')
        room = self.rooms.get_room(room_id)
        seats = [pid for pid, player in room.players.items() if player.user_id == user_id] if room else []
        if len(seats) != 1:
            raise PermissionError('只能测试本人正在参与的对局')
        seat = seats[0]
        player = room.players[seat]
        connection = Connection(sid=player.socket_id or seat, user_id=user_id, username=player.name)
        # 两个身份字段只能来自服务端；进阶 JSON 不能冒充另一座位或另一房间。
        payload = {**params, 'room_id': room.id, 'player_id': seat}
        room._viewing_commit_hook = self.rooms.viewing.commit
        async with room_action(room):
            if not room.admin_test:
                room.admin_test = True
                await self.rooms._publisher.emit('message', {
                    'message': '本局已进入管理员测试模式，不计战绩、排位、任务或奖励。',
                }, room=room.id)
            logger.warning('管理员测试操作', extra={'actor': user_id, 'room_id': room.id, 'action': action})
            result = await self._run(room, seat, connection, action, payload)
            await self.rooms.push_room_sync(room)
            return {**result, 'admin_test': True}

    async def _run(self, room, seat, connection, action, params):
        if action in NORMAL_ACTIONS:
            owner = getattr(self, NORMAL_ACTIONS[action][0])
            return await getattr(owner, 'papal_discard' if action == 'papal_attack' else action)(connection, params)
        if action == 'priority_response':
            return await self.gameplay.priority.response(connection, params)
        if action == 'inspect':
            return self.battle.debug_get_game_state(room.id)
        if action == 'draw_card':
            from ..domain.magic.cards import card_by_name
            name = params.get('card_name')
            if not isinstance(name, str) or card_by_name(name) is None:
                raise ValueError('请选择有效卡牌')
            count = integer(params.get('count', 1), 1, 50)
            for _ in range(count):
                result = await self.magic.debug_add_card(room.id, seat, name)
            return result
        if action == 'all_cards':
            return await self.magic.debug_add_all_cards(room.id, seat)
        if action == 'clear_effects':
            return await self.magic.debug_clear_all_effects(room.id)
        if action in ('win', 'lose'):
            other = room.opponent_of(seat)
            if other is None:
                raise ValueError('对手尚未加入')
            winner, loser = (seat, other) if action == 'win' else (other, seat)
            await self.battle.finish_game(room, winner, loser, reason='admin_test')
            return {'status': 'success', 'message': '测试对局已结束，不产生结算收益'}
        if action == 'auto_attack':
            count = integer(params.get('count', 1), 1, 100)
            fired = 0
            for _ in range(count):
                if room.state != RoomState.ATTACKING or room.current_attacker != seat or room.attacks_remaining <= 0:
                    break
                cells = battle_rules.attackable_cells(room.players[seat])
                if not cells:
                    break
                x, y = self.battle.rng.choice(cells)
                result = await self.battle.attack(connection, {'room_id': room.id, 'player_id': seat, 'x': x, 'y': y})
                if result.get('status') != 'success':
                    return {**result, 'fired': fired}
                fired += 1
            return {'status': 'success', 'message': f'已按真实规则炮击 {fired} 次', 'fired': fired}
        if action in ('own_ships', 'opponent_ships'):
            count = integer(params.get('count', 6), 1, 6)
            method = self.battle.debug_set_player_ships if action == 'own_ships' else self.battle.debug_set_opponent_ships
            return await method(room.id, seat, count)
        if action == 'next_phase':
            if room.current_phase == RoomPhase.PREPARATION:
                room.current_phase = RoomPhase.BATTLE
            else:
                await self.gameplay.debug_end_turn(room.id)
            self.gameplay.touch_turn(room, room.current_attacker)
        elif action == 'set_phase':
            try:
                room.current_phase = RoomPhase(params.get('phase'))
            except (TypeError, ValueError):
                raise ValueError('阶段必须是 preparation / battle / end') from None
            self.gameplay.touch_turn(room, room.current_attacker)
        elif action == 'set_attacks':
            room.attacks_remaining = integer(params.get('count'), 0, 100)
        elif action == 'reset':
            self.magic.cancel_room_timers(room.id)
            await self.gameplay.debug_reset_game(room.id)
            room.settled, room.settlement_result = False, None
        elif action == 'ai_rps':
            choice = params.get('choice')
            if not room.is_ai_room or room.state != RoomState.ROCK_PAPER_SCISSORS:
                raise ValueError('只能指定本局 AI 在猜拳阶段的出拳')
            if choice not in ('rock', 'paper', 'scissors'):
                raise ValueError('请选择有效猜拳')
            room.test_ai_rps_choice = choice
        elif action == 'chain_demo':
            return await self.magic.debug_get_multi_area_chain(room.id, seat)
        return {'status': 'success', 'message': '测试状态已更新'}
