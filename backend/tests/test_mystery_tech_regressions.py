"""终审发现的四个真实交互边界，禁止退回只测标记。"""
import asyncio
from test_mystery_tech_flow import stack
from battleship.domain import battle as battle_rules
from battleship.domain.room import RoomState, RoomPhase, Position, alive_ships
from battleship.domain.mystery_tech import effects as tech
from battleship.services.rooms import Connection


def test_unspent_reaction_survives_round_and_is_consumed_only_once():
    async def run():
        r,rooms,g,magic,battle,pub,clock=stack()
        r.round=5;r.state=RoomState.ATTACKING;r.current_phase=RoomPhase.BATTLE
        r.current_attacker='b';r.attack_order=['a','b'];r.attacks_remaining=3
        tech.apply(r,'a','overload_reaction',g.rng)
        ship=r.players['b'].ships[0];ship.hits=list(ship.positions);battle_rules.apply_ship_sunk(r,'b',ship)
        await magic.on_ship_sunk(r,'b',ship,magic=True,attacker_id='a')
        assert len(r.players['a'].magic_hand)==1 and r.attacks_remaining==3
        r.round=6;r.current_attacker='a';r.current_phase=RoomPhase.PREPARATION
        assert battle_rules.recalc_attacker_attacks(r)==4
        assert battle_rules.enter_battle(r,'a') is None and r.attacks_remaining==4
        assert battle_rules.recalc_attacker_attacks(r)==4
        r.current_phase=RoomPhase.PREPARATION
        assert battle_rules.enter_battle(r,'a') is None and r.attacks_remaining==3
    asyncio.run(run())


def test_self_sacrifice_never_rewards_the_previous_attacker():
    async def run():
        r,rooms,g,magic,battle,pub,clock=stack()
        r.state=RoomState.ATTACKING;r.current_phase=RoomPhase.BATTLE;r.current_attacker='a';r.attacks_remaining=3
        r.last_attack={'attacker':'a','x':5,'y':5,'hit':False}
        tech.apply(r,'a','overload_reaction',g.rng)
        await magic._sacrifice_ship(r,'b',r.players['b'].ships[0],'iron_bones',source_id='b')
        assert not r.players['a'].magic_hand and r.attacks_remaining==3
    asyncio.run(run())


def test_removed_but_reviveable_wreck_is_selectable_and_restored():
    r,rooms,g,magic,battle,pub,clock=stack()
    player=r.players['a'];ship=player.ships.pop(0)
    battle_rules.mark_ship_sunken(player,ship);player.remaining_ships-=1
    request=tech.target_request(r,'a','emergency_repair',now=100)
    assert request['ship_indices']
    index=request['ship_indices'][0]
    assert tech.answer(r,request,{'ship_index':index,'x':4,'y':4}) is None
    assert any(current is ship for current in player.ships)
    assert all(dead is not ship for dead in player.sunken_ships)
    assert player.remaining_ships==3 and ship.positions==[Position(4,4)]


def test_fold_waits_for_trap_sacrifices_before_second_tech_window():
    async def run():
        r,rooms,g,magic,battle,pub,clock=stack()
        r.round=5
        for ship in r.players['b'].ships: ship.trap=True
        await g.mystery_tech.begin(r)
        s=r.mystery_tech_state;s.update(stage='locked',locked={'a':'spacetime_fold','b':'sonar_pulse'})
        r.attack_order=['a','b'];r.current_attacker='a'
        await g.mystery_tech.start_resolution(r)
        assert r.pending_ship_picks
        assert s['stage']=='effect_waiting' and s['target'] is None
        for _ in range(2):
            ship=alive_ships(r.players['a'])[0];pos=ship.positions[0]
            result=await magic.confirm_sacrifice(Connection(sid='a',user_id='a'),
                {'room_id':r.id,'player_id':'a','position':{'x':pos.x,'y':pos.y}})
            assert result['status']=='success'
        assert not r.pending_ship_picks
        clock[0]=110
        await g.sweep_timeouts()
        assert s['target']['player_id']=='b' and s['target']['deadline']==125000
        assert r.players['a'].remaining_ships==1
    asyncio.run(run())


def test_tech_derived_obligations_use_existing_timeout_executor():
    async def run():
        from battleship.services.ai import AiService
        r,rooms,g,magic,battle,pub,clock=stack()
        AiService(rooms,g,battle,magic,rng=g.rng,pacing_seconds=0)
        r.round=5
        for ship in r.players['b'].ships: ship.trap=True
        await g.mystery_tech.begin(r)
        s=r.mystery_tech_state;s.update(stage='locked',locked={'a':'spacetime_fold','b':'sonar_pulse'})
        r.attack_order=['a','b'];r.current_attacker='a'
        await g.mystery_tech.start_resolution(r)
        await g.sweep_timeouts()
        clock[0]=191
        await g.sweep_timeouts()
        assert not r.pending_ship_picks
        assert s['target']['player_id']=='b' and s['target']['deadline']==206000
        assert r.players['a'].remaining_ships==1
        await magic.stop()
    asyncio.run(run())
