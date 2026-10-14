"""主动牺牲类魔法卡效果。"""


def apply_steel_bone(room, caster_id, result, *, caster,
                     note_ship_lost, capture_observation,
                     mark_ship_sunken):
    """结算「钢筋铁骨」；返回是否已处理。"""
    if caster.remaining_ships < 2:
        result['success'] = False
        result['message'] = '需要至少2艘战舰才能发动'
        return True
    alive_ships = [ship for ship in caster.ships
                   if ship not in caster.sunken_ships]
    if not alive_ships:
        result['success'] = False
        result['message'] = '没有可牺牲的战舰'
        return True
    sacrificed = alive_ships[-1]
    note_ship_lost(
        capture_observation(room), caster_id,
        [{'x': pos.x, 'y': pos.y} for pos in sacrificed.positions],
    )
    caster.ships.remove(sacrificed)
    if sacrificed not in caster.sunken_ships:
        mark_ship_sunken(caster, sacrificed)
    caster.remaining_ships -= 1
    for ship in caster.ships:
        ship.invincible = True
    result['message'] = '牺牲一艘战舰，其他战舰进入无敌状态'
    return True
