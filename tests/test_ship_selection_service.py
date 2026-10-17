"""选船应用层脱离服务器后的房间隔离、恢复与投递失败契约。"""

from types import SimpleNamespace

from application.ship_selection import ShipSelection


def make_room():
    ship = SimpleNamespace(positions=[SimpleNamespace(x=1, y=2)])
    player = SimpleNamespace(sid='sid-p1', ships=[ship])
    return SimpleNamespace(players={'p1': player}, pending_ship_picks=[], ship_pick_seq=0)


def make_service(emit):
    return ShipSelection(
        emit=emit, alive_ships=lambda player: player.ships,
        is_ai_player=lambda room, pid: False,
        choose_ai_ship=lambda *args: None,
    )


def test_rooms_reconnect_and_duplicate_cancellation_are_isolated():
    """相同玩家标识在不同房间不串队列；重复待办只取消通知一次。"""
    events = []
    service = make_service(lambda event, payload, **kw: events.append((event, payload, kw)))
    first, second = make_room(), make_room()
    service.register_silent(first, 'p1', 'shield_choice', '选择护盾')
    service.request(first, 'p1', 'demon_contract', '选择牺牲')
    service.request(first, 'p1', 'demon_contract', '再次牺牲', allow_duplicate=True)
    service.request(second, 'p1', 'kraken_eye', '展示战舰')
    assert service.pending_payload(first, 'p1') == {
        'reason': 'demon_contract', 'message': '选择牺牲', 'priority': 100,
    }
    assert service.pending_ships(first, 'p1', first.players['p1']) == [
        {'positions': [{'x': 1, 'y': 2}]},
    ]
    events.clear()
    assert len(service.cancel_reason(first, 'demon_contract')) == 2
    assert events == [('sacrifice_cancelled', {'reason': 'demon_contract'}, {'to': 'sid-p1'})]
    assert service.pending_payload(first, 'p1') is None
    assert service.pending_ships(first, 'p1', first.players['p1']) == []
    assert service.pending_payload(second, 'p1')['reason'] == 'kraken_eye'
    assert service.consume(first, 'p1', 'shield_choice')
    assert len(second.pending_ship_picks) == 1


def test_failed_delivery_preserves_pending_selection_for_reconnect():
    """瞬时发送失败不丢待办；重复请求恢复投递而不增加队列条目。"""
    def failed_emit(*args, **kwargs):
        raise RuntimeError('连接已断开')

    room = make_room()
    service = make_service(failed_emit)
    service.request(room, 'p1', 'dice_sacrifice', '选择牺牲')
    assert service.pending_payload(room, 'p1')['reason'] == 'dice_sacrifice'
    events = []
    restored = make_service(lambda event, payload, **kw: events.append((event, payload, kw)))
    restored.request(room, 'p1', 'dice_sacrifice', '选择牺牲')
    assert len(room.pending_ship_picks) == 1
    assert len(events) == 1
    assert events[0][0] == 'sacrifice_request'
    assert events[0][2] == {'to': 'sid-p1'}
