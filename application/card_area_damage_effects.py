"""溅射、轰炸和硫磺火焰的范围伤害效果。"""

from application.player_state import Position

AREA_CARD_NAMES = frozenset({'溅射', '轰炸', '硫磺火焰'})


def apply_area_damage_card_effect(
        room, caster_id, card, target_data, result, emit, *,
        apply_ship_sunk_effects, check_last_chance, emit_ships_updated,
        is_ship_alive, my_ship_picks, opponent_of,
        request_demon_contract_sacrifice, mark_ship_sunken,
        notify_treasure_hunter, on_ship_destroyed, log_name, add_game_log):
    """返回（已处理，需提前结束），由原结算入口保留最终胜负检查。"""
    if card.name not in AREA_CARD_NAMES:
        return False, False
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    if card.name == '溅射':
        # 对击中格子的上下左右四格造成伤害
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack.get('hit'):
            result['success'] = False
            result['message'] = '必须在击中对方后使用'
            return True, True
        x, y = room.last_attack["x"], room.last_attack["y"]
        splash_positions = [
            {'x': x, 'y': y - 1},  # 上
            {'x': x, 'y': y + 1},  # 下
            {'x': x - 1, 'y': y},  # 左
            {'x': x + 1, 'y': y}  # 右
        ]

        # 过滤有效位置
        valid_positions = [p for p in splash_positions if 0 <= p['x'] < 6 and 0 <= p['y'] < 6]
        hit_count = 0
        ships_changed = False
        demon_contract_requested = False

        affected_positions = []
        for pos in valid_positions:
            # 检查是否击中
            hit = False
            ship_sunk = False
            for ship in opponent.ships:
                position = Position(**pos)
                if (is_ship_alive(opponent, ship)
                        and position in ship.positions
                        and position not in ship.hits):
                    # 溅射无视护盾和无敌，并在命中任一未受伤船格时直接击沉整艘船。
                    # 造成伤害：解除无暇圣心"双方未受伤"判定。
                    if 'holy_heart' in room.game_effects:
                        room.game_effects['holy_heart']['no_damage'] = False
                    hit = True
                    ship.shield = False
                    ship.hits.append(Position(**pos))
                    ship_sunk = True
                    ships_changed = True
                    # 使用普通击沉的唯一收口，保证存活状态、双方棋盘和击沉副作用一致。
                    apply_ship_sunk_effects(
                        room, room.id, caster_id, opponent_id, ship,
                        exclude_attacker_from_treasure=False,
                        request_demon_contract=False,
                    )
                    # 记录本回合造成的伤害（五险一金/Freezing! 判定）。
                    caster.damage_dealt_this_turn += 1

                    # 恶魔契约（由牺牲方自己点选，AI 自动）：一次结算里只请求一次。
                    if (not demon_contract_requested
                            and room.game_effects.get('demon_contract')
                            and not my_ship_picks(room, opponent_of(room, opponent_id))):
                        request_demon_contract_sacrifice(room, opponent_id)
                        demon_contract_requested = True
                        ships_changed = True

                    # 检查回光返照效果（统一走 helper：置状态 / 记日志 / 记战绩 / 广播）。
                    if check_last_chance(room, caster_id, opponent_id):
                        result['game_over'] = True
                        return True, True
                    hit_count += 1
                    break

            # 记录攻击（包括未命中）
            caster.attacks.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'is_splash': True
            }))

            # 发送单点攻击结果，保持与普通攻击一致的 UI 更新
            attack_result = {
                'attacker': caster_id,
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'shield_blocked': False,
                'remaining_attacks': room.attacks_remaining,
                'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                'defender_remaining_ships': opponent.remaining_ships
            }
            emit('attack_result', attack_result, room=room.id)

            affected_positions.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk
            }))

        # 若有船只数量变化，广播更新
        if ships_changed:
            emit_ships_updated(room)

        result['message'] = f'溅射攻击命中{hit_count}个目标'
        result['affected_positions'] = affected_positions
        result['caster_id'] = caster_id

    elif card.name == '轰炸':
        # 选定一行或一列进行轰炸
        if 'target_line' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标行或列'
            return True, True
        line = target_data['target_line']
        # 检查是行还是列
        if line["type"] == 'row':
            positions = [{'x': x, 'y': line['index']} for x in range(6)]
        else:
            positions = [{'x': line['index'], 'y': y} for y in range(6)]

        # 找出所有与该行/列相交的船只，整艘摧毁
        to_remove = [ship for ship in opponent.ships if len(ship.hits) < len(ship.positions) and any(pos in ship.positions for pos in positions)]
        sunk_count = 0
        ships_changed = False
        removed_positions = set()

        # 移除受影响的船只，并为其所有格子生成命中事件
        for ship in to_remove:
            if ship in opponent.ships:
                # 保存被摧毁的船到sunken_ships
                mark_ship_sunken(opponent, ship)
                opponent.ships.remove(ship)
                opponent.remaining_ships -= 1
                ships_changed = True
                sunk_count += 1
                # 记录本回合伤害（五险一金/Freezing!）
                caster.damage_dealt_this_turn += 1

                # 百亿补贴 + 无暇圣心中断（与普通攻击共用）
                on_ship_destroyed(room, opponent_id, ship)

                # 恶魔契约：一次结算里多艘沉没时只请求一次
                # （判据查**优先队列**：该玩家已有待选就跳过；队列内部也会按
                #   player+reason 去重，这里是双保险）
                if (room.game_effects.get('demon_contract')
                        and not my_ship_picks(room, opponent_of(room, opponent_id))):
                    request_demon_contract_sacrifice(room, opponent_id)
                    ships_changed = True

                # 八方来财
                notify_treasure_hunter(room, 1)   # 魔法卡造成的变化：全场持卡者都摸
                for ship_pos in ship.positions:
                    removed_positions.add((ship_pos.x, ship_pos.y))
                    caster.attacks.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'is_bomb': True
                    }))
                    attack_result = {
                        'attacker': caster_id,
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                        'defender_remaining_ships': opponent.remaining_ships
                    }
                    emit('attack_result', attack_result, room=room.id)

        # 对于该行/列中未命中的格子也发出未命中事件，以保持 UI 一致性
        for pos in positions:
            if (pos['x'], pos['y']) not in removed_positions:
                caster.attacks.append(Position(**{
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': False,
                    'ship_sunk': False,
                    'is_bomb': True
                }))
                attack_result = {
                    'attacker': caster_id,
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': False,
                    'ship_sunk': False,
                    'remaining_attacks': room.attacks_remaining,
                    'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                    'defender_remaining_ships': opponent.remaining_ships
                }
                emit('attack_result', attack_result, room=room.id)

        # 若有船只数量变化，广播更新
        if ships_changed:
            emit_ships_updated(room)

        result['message'] = f'轰炸成功击沉{sunk_count}艘战舰'

    elif card.name == '硫磺火焰':
        # 对选定的连续6格释放硫磺火焰，强制击杀这些格子上所属的所有战舰（无视护盾/无敌）
        if 'target_cells' not in target_data:
            result['success'] = False
            result['message'] = '需要选择6个连续的目标格子'
            return True, True
        positions = target_data['target_cells']
        if not isinstance(positions, list) or len(positions) != 6:
            result['success'] = False
            result['message'] = '需要选择恰好6个连续的格子'
            return True, True
        # 找出所有与这些格子相交的船只，并整艘摧毁
        to_remove = [ship for ship in opponent.ships if len(ship.hits) < len(ship.positions) and any(pos in ship.positions for pos in positions)]
        sunk_count = 0
        ships_changed = False
        removed_positions = set()
        affected_positions: list[Position] = []
        for ship in to_remove:
            if ship in opponent.ships:
                # 保存被摧毁的船到sunken_ships
                mark_ship_sunken(opponent, ship)
                opponent.ships.remove(ship)
                opponent.remaining_ships -= 1
                ships_changed = True
                sunk_count += 1
                # 记录本回合伤害（五险一金/Freezing!）
                caster.damage_dealt_this_turn += 1

                # 八方来财: 战舰数目变化时抽一张牌
                notify_treasure_hunter(room, 1)   # 魔法卡造成的变化：全场持卡者都摸

                # 百亿补贴 + 无暇圣心中断（与普通攻击共用）
                on_ship_destroyed(room, opponent_id, ship)

                # 恶魔契约：一次结算里多艘沉没时只请求一次
                # （判据查**优先队列**：该玩家已有待选就跳过；队列内部也会按
                #   player+reason 去重，这里是双保险）
                if (room.game_effects.get('demon_contract')
                        and not my_ship_picks(room, opponent_of(room, opponent_id))):
                    request_demon_contract_sacrifice(room, opponent_id)
                    ships_changed = True
                for ship_pos in ship.positions:
                    removed_positions.add((ship_pos.x, ship_pos.y))
                    caster.attacks.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'is_sulfur': True
                    }))
                    attack_result = {
                        'attacker': caster_id,
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                        'defender_remaining_ships': opponent.remaining_ships
                    }
                    emit('attack_result', attack_result, room=room.id)
                    affected_positions.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True
                    }))

        # 对于选定格子中未命中的格子，发送未命中事件
        for pos in positions:
            if (pos["x"], pos["y"]) not in removed_positions:
                caster.attacks.append(Position(**{
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False,
                    'is_sulfur': True
                }))
                attack_result = {
                    'attacker': caster_id,
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False,
                    'remaining_attacks': room.attacks_remaining,
                    'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                    'defender_remaining_ships': opponent.remaining_ships
                }
                emit('attack_result', attack_result, room=room.id)
                affected_positions.append(Position(**{
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False
                }))

        # 广播被摧毁舰只更新
        if ships_changed:
            emit_ships_updated(room)

        result['message'] = f'硫磺火焰成功击杀{sunk_count}艘战舰'
        result['affected_positions'] = affected_positions
        result['caster_id'] = caster_id
        
        # 添加游戏日志
        add_game_log(room, f"第{room.round}回合 · {log_name(room, caster_id)} 使用了【硫磺火焰】，击杀了{sunk_count}艘战舰", 'magic', {
            'caster_id': caster_id,
            'card_name': card.name,
            'sunk_count': sunk_count,
            'affected_positions': affected_positions
        })

    return True, False
