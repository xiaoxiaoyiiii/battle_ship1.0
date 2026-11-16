"""科技抽选与真实效果的回归；随机源和时钟由夹具固定。"""
import random
import pytest

from battleship.domain.room import Room, Player, PlayerShip, Position


def make_room():
    return Room('tech-test', mystery_tech=True, players={
        pid: Player(name=pid, user_id=pid, socket_id=pid, ships=[
            PlayerShip(positions=[Position(x, 0)]) for x in range(3)
        ], remaining_ships=3) for pid in ('a', 'b')})


def test_catalog_probability_and_exhaustion():
    from battleship.domain.mystery_tech.catalog import TECHNOLOGIES
    from battleship.domain.mystery_tech.draft import probabilities, pick
    assert len(TECHNOLOGIES) == len({t.name for t in TECHNOLOGIES}) == 18
    assert probabilities(1) == {'quality': 80, 'legendary': 18, 'mythic': 2}
    assert probabilities(5) == {'quality': 71, 'legendary': 24, 'mythic': 5}
    assert probabilities(1000) == {'quality': 0, 'legendary': 0, 'mythic': 100}
    for turn in range(1, 100):
        rates = probabilities(turn)
        assert sum(rates.values()) == 100 and min(rates.values()) >= 0
    rng = random.Random(5)
    last = TECHNOLOGIES[-1]
    assert pick(1, {t.id for t in TECHNOLOGIES[:-1]}, rng) == last.id
    assert pick(1, {t.id for t in TECHNOLOGIES}, rng) is None


def test_private_refresh_deadline_and_global_unique_lock():
    from battleship.domain.mystery_tech import draft
    r = make_room(); rng = random.Random(3)
    assert draft.begin(r, rng, now=100)
    mine = draft.snapshot(r, 'a', now=101)
    assert len(mine['options']) == 3 and mine['remaining_ms'] == 19000
    old = [x['tech_id'] for x in mine['options']]
    assert draft.refresh(r, 'a', 1, rng, now=105) is None
    after = draft.snapshot(r, 'a', now=105)
    assert after['deadline'] == 120000
    assert after['options'][0]['tech_id'] == old[0] and after['options'][2]['tech_id'] == old[2]
    assert after['options'][1]['refresh_used']
    assert draft.refresh(r, 'a', 1, rng, now=106)
    assert 'options' not in draft.snapshot(r, None, now=106)
    choice = after['options'][0]['tech_id']
    assert draft.lock(r, 'a', choice, rng, now=106) is None
    assert not draft.snapshot(r, 'b', now=106)['selected']
    draft.expire(r, rng, now=120)
    public = draft.snapshot(r, None, now=120)
    assert len(public['selected']) == 2
    assert len({x['tech_id'] for x in public['selected']}) == 2
    assert not draft.begin(r, rng, now=130)


def test_colliding_picks_same_tier_replacement_and_empty_pool():
    from battleship.domain.mystery_tech import draft
    from battleship.domain.mystery_tech.catalog import TECHNOLOGIES, BY_ID
    r=make_room();rng=random.Random(9);draft.begin(r,rng,now=1)
    r.mystery_tech_state['offers']={pid:[{'tech_id':'extra_supply','refresh_used':False}] for pid in r.players}
    assert draft.lock(r,'a','extra_supply',rng,now=2) is None
    assert draft.lock(r,'b','extra_supply',rng,now=2)
    b=draft.snapshot(r,'b',now=2)
    assert BY_ID[b['options'][0]['tech_id']].tier=='quality'
    assert b['deadline']==21000 and not b['selected']
    draft.expire(r,rng,now=21)
    r.round=5
    r.mystery_tech_state['history']=[{'player_id':'a','tech_id':t.id,'round':1} for t in TECHNOLOGIES]
    assert draft.begin(r,rng,now=30)
    assert draft.snapshot(r,'a',now=30)['options']==[]
    draft.expire(r,rng,now=50)
    assert len(r.mystery_tech_state['history'])==18


def test_probability_sampling_and_exhausted_tier_fallback():
    from collections import Counter
    from battleship.domain.mystery_tech.draft import pick
    from battleship.domain.mystery_tech.catalog import BY_ID, TECHNOLOGIES
    rng=random.Random(104)
    counts=Counter(BY_ID[pick(1,set(),rng)].tier for _ in range(12000))
    assert abs(counts['quality']/12000-.8)<.02
    assert abs(counts['legendary']/12000-.18)<.02
    assert abs(counts['mythic']/12000-.02)<.01
    excluded={t.id for t in TECHNOLOGIES if t.tier=='mythic'}
    assert BY_ID[pick(1000,excluded,rng,tier='mythic')].tier!='mythic'
