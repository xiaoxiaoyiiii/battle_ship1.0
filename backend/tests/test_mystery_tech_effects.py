"""逐条科技断言，使用真实舰队、摸牌与施法规则。"""
import random
import pytest
from test_mystery_tech import make_room
from battleship.domain.room import Position, PlayerShip, RoomState, RoomPhase
from battleship.domain.magic.cards import card_by_name
from battleship.domain import battle


def tech():
    from battleship.domain.mystery_tech import effects
    return effects


@pytest.mark.parametrize('tech_id,count', [('extra_supply', 2), ('tidal_rewrite', 4)])
def test_supply_and_rewrite(tech_id, count):
    e=tech(); r=make_room(); r.players['a'].magic_hand=[card_by_name('轰炸')]
    result=e.apply(r,'a',tech_id,random.Random(1))
    assert result['draw']==count
    if tech_id=='tidal_rewrite':
        assert not r.players['a'].magic_hand and r.magic_discard[-1].name=='轰炸'


@pytest.mark.parametrize('tech_id,count', [('emergency_repair',1),('battlefield_recall',2),('fleet_rebirth',3)])
def test_player_places_revive_and_replenishment(tech_id,count):
    e=tech();r=make_room();p=r.players['a']
    if tech_id!='fleet_rebirth':
        for ship in list(p.ships)[:2]:
            battle.apply_ship_sunk(r,'a',ship);ship.hits=list(ship.positions)
    r.players['b'].attacks=[Position(5,5)]
    request=e.target_request(r,'a',tech_id,now=10)
    assert request['deadline']==25000
    assert {'x':5,'y':5} not in request['legal_cells']
    for i in range(count):
        request=e.target_request(r,'a',tech_id,now=10,remaining=count-i,request_id='same')
        ship_index=request['ship_indices'][0] if request['ship_indices'] else None
        before=p.remaining_ships
        assert e.answer(r,request,{'x':i,'y':3,'ship_index':ship_index}) is None
        assert p.remaining_ships==before+1
    assert p.remaining_ships==(6 if tech_id=='fleet_rebirth' else 1+count)


def test_sonar_scan_and_fold():
    e=tech();r=make_room();rng=random.Random(1)
    request=e.target_request(r,'a','sonar_pulse',now=1)
    assert e.answer(r,request,{'x':0,'y':0}) is None
    assert Position(0,0) in r.players['a'].revealed_positions
    assert Position(1,0) in r.players['a'].revealed_positions
    assert len(r.players['a'].revealed_positions)==4
    e.apply(r,'a','global_scan',rng)
    assert Position(2,0) in r.players['a'].revealed_positions
    request=e.target_request(r,'a','spacetime_fold',now=1)
    assert e.answer(r,request,{'ship_index':0}) is None
    assert r.players['b'].remaining_ships==2
    assert r.players['b'].sunken_ships[0] is r.players['b'].ships[0]
    assert not r.players['b'].permanently_destroyed_ships


def test_shield_future_revives_armor_and_attack_budget():
    e=tech();r=make_room();rng=random.Random(1)
    e.apply(r,'a','steady_defense',rng)
    assert all(s.shield for s in r.players['a'].ships)
    ship=r.players['a'].ships[0];ship.shield=False
    e.protect_new_ship(r,'a',ship)
    assert ship.shield
    e.apply(r,'a','armor_plating',rng)
    ship.shield=False
    assert e.absorb_armor(r,'a',ship)
    assert not e.absorb_armor(r,'a',ship)
    assert Position(0,0) in r.players['b'].revealed_positions
    e.apply(r,'a','accelerated_loading',rng)
    e.apply(r,'a','firepower_overload',rng)
    r.current_attacker='a';r.state=RoomState.ATTACKING;r.current_phase=RoomPhase.BATTLE
    assert battle.recalc_attacker_attacks(r)==8
    r.round=2
    assert battle.recalc_attacker_attacks(r)==4


def test_preparation_and_chain_amplification():
    e=tech();r=make_room();rng=random.Random(1)
    e.apply(r,'a','efficient_dispatch',rng)
    e.apply(r,'b','exclusion_zone',rng)
    assert e.prepare_draw_count(r,'a',1)==1
    r.mystery_tech_state['active']['b'].append('exclusion_zone')
    assert e.prepare_draw_count(r,'a',1)==0
    e.apply(r,'a','chain_amplifier',rng)
    assert e.chain_draw_count(r,'a',1,{'a'})==0
    assert e.chain_draw_count(r,'a',4,{'a','b'})==3
    assert e.chain_draw_count(r,'a',4,{'b'})==0


def test_silence_and_double_command_obey_real_cast_gate():
    e=tech();r=make_room();rng=random.Random(1)
    from battleship.domain.magic.rules import evaluate_cast,can_play_magic_card
    from battleship.domain.magic.chain import usable_speed3_cards
    r.state=RoomState.ATTACKING;r.current_attacker='b';r.current_phase=RoomPhase.BATTLE
    card=card_by_name('火力全开');r.players['a'].magic_hand=[card]
    assert not can_play_magic_card(r,'a',card)
    e.apply(r,'a','double_command',rng)
    assert can_play_magic_card(r,'a',card)
    assert card in usable_speed3_cards(r,'a')
    e.apply(r,'b','silent_domain',rng)
    assert not e.magic_blocked(r,'a')
    for turn in (2,3):
        r.round=turn
        assert e.magic_blocked(r,'a') and evaluate_cast(r,'a',card)
        assert not usable_speed3_cards(r,'a')
    r.round=4
    assert not e.magic_blocked(r,'a')


def test_overload_reaction_gains_one_per_enemy_sink():
    e=tech();r=make_room();e.apply(r,'a','overload_reaction',random.Random(1))
    r.state=RoomState.ATTACKING;r.current_phase=RoomPhase.BATTLE;r.current_attacker='a';r.attacks_remaining=2
    assert e.on_sink(r,'a','b')==1 and r.attacks_remaining==3
    assert e.on_sink(r,'a','a')==0 and r.attacks_remaining==3


def test_splash_armor_is_not_damage_to_last_chance():
    async def run():
        from test_mystery_tech_flow import stack
        from battleship.domain.magic.chain import ChainItem
        from battleship.domain.magic.registry import effect_for
        r,rooms,g,magic,service,pub,clock=stack()
        r.state=RoomState.ATTACKING;r.current_attacker='a';r.current_phase=RoomPhase.BATTLE
        e=tech();e.apply(r,'b','armor_plating',random.Random(1))
        r.last_attack={'attacker':'a','x':0,'y':1,'hit':True}
        r.game_effects['last_chance']={'caster':'b','active':True,'round':r.round}
        result=await effect_for('溅射')(magic._context(r,ChainItem('a',card_by_name('溅射'))))
        assert result.success
        assert r.state!=RoomState.GAME_OVER and not result.game_over
        assert r.players['b'].remaining_ships==3
    import asyncio
    asyncio.run(run())
