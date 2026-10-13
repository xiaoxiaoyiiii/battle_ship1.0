"""无效化模块通过注入的棋盘查询独立判牌，不共享运行时依赖。"""

from types import SimpleNamespace

from application.card_negation_effects import NegationEffects


class Result(SimpleNamespace):
    def __setitem__(self, key, value):
        setattr(self, key, value)


def _unused(*args):
    raise AssertionError('增援判据不应调用无关的棋盘操作')


def _effects(placement_query):
    return NegationEffects(
        alive_ships=_unused,
        opponent_of=_unused,
        cell_xy=_unused,
        placement_blocked_cells=placement_query,
        lanyu_requirement_reason=_unused,
        tear_down_field_magic=_unused,
    )


def _treaty_room():
    target = SimpleNamespace(player_id='b', card=SimpleNamespace(name='增援'))
    return SimpleNamespace(
        players={'a': SimpleNamespace(magic_blocked=False), 'b': SimpleNamespace()},
        chain=[target],
    )


def test_runtime_instances_keep_their_own_board_queries():
    """同一目标在有空位与无空位的运行时中，分别可康与不可康。"""
    has_space = _effects(lambda room, player_id: [])
    no_space = _effects(lambda room, player_id: list(range(36)))
    room = _treaty_room()
    card = SimpleNamespace(name='平等条约', type='普通')

    # 创建第二份运行时后再调用第一份，防止模块级依赖被后一次初始化覆盖。
    allowed = Result(success=True, message='')
    refused = Result(success=True, message='')
    assert has_space.apply(room, 'a', card, allowed) == (True, False)
    assert no_space.apply(room, 'a', card, refused) == (True, True)
    assert allowed.success and allowed.negate_target
    assert not refused.success
    assert not getattr(refused, 'negate_target', False)
    assert '没有可无效化的船数改变效果' in refused.message
    assert len(room.chain) == 1  # 判牌只返回结论，栈仍交给连锁结算器消费。


def test_failed_board_query_refuses_negation_with_reason():
    """棋盘查询失败时不能把不确定当成可无效化，也不能静默吞掉理由。"""
    def unavailable(room, player_id):
        raise RuntimeError('棋盘暂不可读')

    effects = _effects(unavailable)
    room = _treaty_room()
    result = Result(success=True, message='')
    card = SimpleNamespace(name='平等条约', type='普通')
    assert effects.apply(room, 'a', card, result) == (True, True)
    assert not result.success
    assert '棋盘暂不可读' in result.message
    assert not getattr(result, 'negate_target', False)
    assert len(room.chain) == 1
