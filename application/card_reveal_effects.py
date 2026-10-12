"""侦查、冻结及双方选船公开效果。"""

from application.player_state import Position

REVEAL_CARD_NAMES = frozenset({'雷达子弹', '冻结', '探测雷达', '克苏鲁之眼'})


def _reveal_cells(room, caster_id, caster, opponent, positions, emit):
    """两种雷达共用的公开与空格探测流程；事件顺序保持一致。"""
    for pos in positions:
        room.players[caster_id].revealed_positions.append(Position(**pos))

    affected_positions = []
    for pos in positions:
        hit = False
        ship_sunk = False
        for ship in opponent.ships:
            if Position(**pos) in ship.positions and Position(**pos) not in ship.hits:
                hit = True
        if hit:
            continue
        caster.attacks.append(Position(**{
            'x': pos['x'], 'y': pos['y'], 'hit': hit,
            'ship_sunk': ship_sunk, 'is_splash': True,
        }))
        emit('attack_result', {
            'attacker': caster_id,
            'x': pos['x'], 'y': pos['y'],
            'hit': hit, 'ship_sunk': ship_sunk,
            'remaining_attacks': room.attacks_remaining,
            'attacker_remaining_ships': room.players[caster_id].remaining_ships,
            'defender_remaining_ships': opponent.remaining_ships,
        }, room=room.id)
        affected_positions.append(Position(**{
            'x': pos['x'], 'y': pos['y'],
            'hit': hit, 'ship_sunk': ship_sunk,
        }))

    emit('revealed_positions', {'positions': positions}, to=room.players[caster_id].sid)
    return affected_positions


def apply_reveal_card_effect(
        room, caster_id, card, target_data, result, emit, *,
        is_ship_alive, emit_player_ships, pick_cell_from_target,
        find_ship_at, request_ship_pick):
    """返回（已处理，需提前结束），由原结算入口保留最终胜负检查。"""
    if card.name not in REVEAL_CARD_NAMES:
        return False, False
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    if card.name == '雷达子弹':
        # 显示击中位置周围八格的战舰
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['hit']:
            result['success'] = False
            result['message'] = '必须在击中对方战舰后使用'
            return True, True
        x, y = room.last_attack["x"], room.last_attack["y"]
        positions = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < 6 and 0 <= ny < 6:
                    positions.append({'x': nx, 'y': ny})
        result['affected_positions'] = _reveal_cells(
            room, caster_id, caster, opponent, positions, emit)
        result['message'] = '已扫描周围八格战舰位置'

    elif card.name == '冻结':
        # 冻结3*3区域内的船，使其无法攻击
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return True, True
        area = target_data['target_area']
        frozen_count = 0

        # 标记区域内的战舰
        for ship in opponent.ships:
            # 已沉没的船不参与冻结（2026-09-17）：
            #   · 它本来就不提供攻击次数，算进 frozen_count 只会让播报数字虚高
            #     （实测玩家报「冻结的战舰数目居然会把已经死亡的战舰加进去」）；
            #   · 给它打上 frozen 标记也没意义，反而会在被复活后带着旧标记回来。
            if not is_ship_alive(opponent, ship):
                continue
            in_area = any(
                area['x1'] <= pos.x <= area['x2'] and
                area['y1'] <= pos.y <= area['y2']
                for pos in ship.positions
            )

            if in_area and getattr(ship, 'frozen', None) is None:
                ship.frozen = room.round + 1  # 冻结到下一回合
                frozen_count += 1

        if frozen_count:
            # 立刻把「哪几艘被冻住了」同步给被冻结的一方（画在ta自己的棋盘上）
            emit_player_ships(room, opponent_id)
        result['message'] = f'冻结了{frozen_count}艘战舰'

        # ★ 记录"冻的是哪片 3×3 区域"并**下发给双方**（2026-09-16）。
        # 作者实测：施法方原先什么都收不到（上面那个 _emit_player_ships 只发受害者），
        # 过一会儿就忘了自己冻的是哪片；受害者也只看到自己的船上有雪花、看不出区域边界。
        # 区域属于【受害者棋盘】，所以带 owner 让前端按归属决定画在哪块棋盘上
        # （与 last_stand_cells 同一套归属模式）。
        # ⚠️ 即便一艘都没冻住也照发：那片区域是公开信息（双方都看到了选区），
        # 前端会按 frozen 数量决定怎么描述。
        room.game_effects['frozen_area'] = {
            'x1': int(area['x1']), 'y1': int(area['y1']),
            'x2': int(area['x2']), 'y2': int(area['y2']),
            'owner': opponent_id,        # 这片区域在哪块棋盘上（受害者）
            'caster': caster_id,         # 谁冻的
            'frozen': frozen_count,
            'until_round': room.round + 1,
        }
        emit('frozen_area', dict(room.game_effects['frozen_area']), room=room.id)

    elif card.name == '探测雷达':
        # 显示2*2区域内的战舰
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return True, True
        area = target_data['target_area']
        positions = []
        for y in range(area['y1'], area['y2'] + 1):
            for x in range(area['x1'], area['x2'] + 1):
                positions.append({'x': x, 'y': y})
        result['affected_positions'] = _reveal_cells(
            room, caster_id, caster, opponent, positions, emit)
        result['message'] = '已探测目标区域战舰位置'

    elif card.name == '克苏鲁之眼':
        # 双方各暴露一艘船。施法者必须点选一艘【自己的船】所在格，不能选空格。
        if not caster.ships or not opponent.ships:
            result['success'] = False
            result['message'] = '双方都必须有战舰才能使用'
            return True, True
        cell = pick_cell_from_target(target_data)
        if cell is None:
            result['success'] = False
            result['message'] = '请选择一艘自己的战舰'
            return True, True
        caster_ship = find_ship_at(caster, cell, alive_only=True)
        if caster_ship is None:
            result['success'] = False
            result['message'] = '必须选择自己【还活着】的战舰所在的格子（已沉没的船不能选）'
            return True, True
        caster_positions = caster_ship.positions
        # 先把自己的位置暴露给对方
        room.players[opponent_id].revealed_positions.extend(caster_positions)
        emit('revealed_positions', {'positions': caster_positions}, to=room.players[opponent_id].sid)

        # 卡面：然后【对方也选择一艘船】暴露位置（AI 由服务端代选 —— 见
        # `_request_ship_pick`：chooser 是 AI 才同步返回一艘船，是真人则**只入队**）。
        picked = request_ship_pick(
            room, opponent_id, 'kraken_eye',
            '克苏鲁之眼生效：请点选一艘自己的战舰暴露位置')
        opponent_positions = picked.positions if picked is not None else []
        if picked is not None:
            room.players[caster_id].revealed_positions.extend(picked.positions)
            emit('revealed_positions', {'positions': picked.positions}, to=room.players[caster_id].sid)
        emit('revealed_positions', {'positions': caster_positions}, to=room.players[opponent_id].sid)

        # ⚠️ 2026-09-22：**不能说假话**。
        # 对手是真人时上面那句 `_request_ship_pick` 只是**入队**（对方还没选），
        # 这里却曾经无条件宣布「双方各暴露一艘战舰位置」—— 卡面承诺的事只完成了
        # 一半，而对外宣称全做完了（CLAUDE.md 的落地口径：等真人回答的效果，
        # 不许在回答之前宣称完成）。文案按"对手到底选了没"分岔。
        if picked is not None:
            result['message'] = '双方各暴露一艘战舰位置'
        else:
            result['message'] = '已暴露自己一艘战舰的位置，等待对方选择要暴露的战舰'

    return True, False
