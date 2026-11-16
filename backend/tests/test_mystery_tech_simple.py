"""神秘科技大乱斗：目录、概率表与去重的纯函数简单测试。

只调用 `domain.mystery_tech.catalog` 与 `domain.mystery_tech.draft` 的公开函数，
不改任何引擎实现。期望值全部来自 bridge 目录的 SPEC.md（第 18 条清单与概率草案）
与 CONTRACT-codex.md（抽空、少出示、封顶口径）。
"""
import random

from battleship.domain.mystery_tech.catalog import TECHNOLOGIES, catalog
from battleship.domain.mystery_tech import draft
from battleship.domain.room import Room, Player, PlayerShip, Position

# SPEC「科技池 18 条」的原文顺序，按档分组。
QUALITY_NAMES = [
    '应急维修', '额外补给', '声呐脉冲', '稳固防线', '加速装填', '高效抽调',
]
LEGENDARY_NAMES = [
    '战场回撤', '火力过载', '全域扫描', '连锁增幅', '装甲镀层', '禁航区',
]
MYTHIC_NAMES = [
    '舰队重生', '寂静领域', '双重指令', '时空折叠', '潮汐改写', '过载反应',
]
EXPECTED_NAMES = QUALITY_NAMES + LEGENDARY_NAMES + MYTHIC_NAMES


def make_room(round_no=1):
    """两台已布好船的房间；只用于驱动抽选状态，不进入战斗。"""
    room = Room('simple-tech', mystery_tech=True, players={
        pid: Player(name=pid, user_id=pid, socket_id=pid, ships=[
            PlayerShip(positions=[Position(x, 0)]) for x in range(3)
        ], remaining_ships=3) for pid in ('a', 'b')})
    room.round = round_no
    return room


def test_catalog_has_eighteen_entries_six_per_tier():
    entries = catalog()
    assert len(entries) == 18
    assert len(TECHNOLOGIES) == 18
    assert [entry['name'] for entry in entries] == EXPECTED_NAMES
    assert [tech.name for tech in TECHNOLOGIES] == EXPECTED_NAMES

    ids = [entry['id'] for entry in entries]
    assert len(set(ids)) == 18
    assert all(isinstance(entry['id'], str) and entry['id'] for entry in entries)

    for tier, names in (
        ('quality', QUALITY_NAMES),
        ('legendary', LEGENDARY_NAMES),
        ('mythic', MYTHIC_NAMES),
    ):
        members = [entry for entry in entries if entry['tier'] == tier]
        assert len(members) == 6
        assert [entry['name'] for entry in members] == names

    # 即时/长效也是 SPEC 定稿的一部分，这里只钉取值域。
    assert {entry['timing'] for entry in entries} == {'instant', 'persistent'}
    assert all(entry['description'].strip() for entry in entries)


def test_probability_table_first_pick_and_every_five_rounds():
    # 第 k 次选择对应大回合 5*(k-1)，k 从 1 起。
    def rates(k):
        return draft.probabilities(5 * (k - 1) if k > 1 else 1)

    assert rates(1) == {'quality': 80, 'legendary': 18, 'mythic': 2}
    assert rates(2) == {'quality': 71, 'legendary': 24, 'mythic': 5}
    assert rates(3) == {'quality': 62, 'legendary': 30, 'mythic': 8}
    assert draft.probabilities(5) == draft.probabilities(9)
    assert draft.probabilities(10) != draft.probabilities(5)


def test_probability_table_floor_and_cap():
    # 品质降到 0 后不再往下扣；神话优先保留，传说被压缩，合计恒为 100。
    for k in range(1, 45):
        table = draft.probabilities(5 * (k - 1) if k > 1 else 1)
        assert set(table) == {'quality', 'legendary', 'mythic'}
        assert sum(table.values()) == 100, (k, table)
        assert min(table.values()) >= 0, (k, table)
        assert table['mythic'] == min(100, 2 + 3 * (k - 1)), (k, table)

    tenth = draft.probabilities(45)
    assert tenth == {'quality': 0, 'legendary': 71, 'mythic': 29}

    # 神话吃满 100 之后，传说与品质都只能是 0。
    full = draft.probabilities(500)
    assert full == {'quality': 0, 'legendary': 0, 'mythic': 100}


def test_offers_are_three_distinct_names():
    room = make_room(round_no=1)
    assert draft.begin(room, random.Random(11), now=1000)
    for pid in ('a', 'b'):
        slots = room.mystery_tech_state['offers'][pid]
        assert len(slots) == 3
        assert len({slot['tech_id'] for slot in slots}) == 3
        assert all(slot['refresh_used'] is False for slot in slots)


def test_used_names_are_never_offered_again():
    room = make_room(round_no=5)
    picked = {tech.id for tech in TECHNOLOGIES[:6]}
    room.mystery_tech_state['history'] = [
        {'player_id': 'a', 'tech_id': tech_id, 'round': 1} for tech_id in picked
    ]
    assert draft.begin(room, random.Random(12), now=2000)
    for pid in ('a', 'b'):
        ids = {slot['tech_id'] for slot in room.mystery_tech_state['offers'][pid]}
        assert ids.isdisjoint(picked)


def test_pool_shortage_and_exhaustion():
    # 只剩 2 条时少出示。
    room = make_room(round_no=5)
    keep = {TECHNOLOGIES[-2].id, TECHNOLOGIES[-1].id}
    room.mystery_tech_state['history'] = [
        {'player_id': 'a', 'tech_id': tech.id, 'round': 1}
        for tech in TECHNOLOGIES if tech.id not in keep
    ]
    assert draft.begin(room, random.Random(13), now=3000)
    slots = room.mystery_tech_state['offers']['a']
    assert len(slots) == 2
    assert {slot['tech_id'] for slot in slots} == keep
    assert draft.refresh(room, 'a', 0, random.Random(14), now=3001) is not None

    # 池子空时一条都不出示，但阶段照常进入，不会卡住对局。
    empty = make_room(round_no=5)
    empty.mystery_tech_state['history'] = [
        {'player_id': 'a', 'tech_id': tech.id, 'round': 1} for tech in TECHNOLOGIES
    ]
    assert draft.begin(empty, random.Random(15), now=4000)
    assert empty.mystery_tech_state['offers']['a'] == []
    assert draft.refresh(empty, 'a', 0, random.Random(16), now=4001) is not None


def test_pick_respects_first_round_weights():
    # 20k 次抽样只验证"首轮大概率出品质"，容差宽松，避免变成脆弱统计测试。
    by_id = {tech.id: tech for tech in TECHNOLOGIES}
    rng = random.Random(20261117)
    counts = {'quality': 0, 'legendary': 0, 'mythic': 0}
    samples = 20_000
    for _ in range(samples):
        counts[by_id[draft.pick(1, set(), rng)].tier] += 1
    assert abs(counts['quality'] / samples - 0.80) <= 0.02
    assert abs(counts['legendary'] / samples - 0.18) <= 0.02
    assert abs(counts['mythic'] / samples - 0.02) <= 0.01
