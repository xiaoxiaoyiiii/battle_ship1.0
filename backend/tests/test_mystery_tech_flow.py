"""真实服务、共享牌堆和权限投影贯穿选择、猜拳与逐艘部署。"""
import asyncio
import json
import random
from test_mystery_tech import make_room
from battleship.services.rooms import RoomService, Connection
from battleship.services.gameplay import GameplayService
from battleship.services.magic import MagicService
from battleship.services.battle import BattleService
from battleship.domain.room import RoomState, RoomPhase, build_room_sync, Position
from battleship.domain.magic.deck import init_shared_deck


class Publisher:
    def __init__(self): self.events=[]
    async def emit(self,event,data,**target): self.events.append((event,data,target))
    async def enter_room(self,*a): pass
    async def leave_room(self,*a): pass


def stack():
    rooms=RoomService(); r=make_room(); r.matchmade=True
    rooms.rooms[r.id]=r
    clock=[100.0]; publisher=Publisher(); rng=random.Random(11)
    magic=MagicService(rooms,clock=lambda:clock[0],rng=rng,chain_entry_delay_seconds=0,chain_display_delay_seconds=0)
    gameplay=GameplayService(rooms,clock=lambda:clock[0],rng=rng,draw_hook=magic.draw)
    battle=BattleService(rooms,clock=lambda:clock[0]);magic.finish_hook=battle.finish_game
    battle.sink_hooks.append(magic.on_ship_sunk)
    gameplay.magic=magic
    for service in (rooms,gameplay,magic,battle): service.bind(publisher)
    init_shared_deck(r,rng=rng)
    return r,rooms,gameplay,magic,battle,publisher,clock


def test_ordered_resolution_reconnect_and_private_recording():
    async def run():
        r,rooms,g,magic,battle,pub,clock=stack()
        from battleship.domain.mystery_tech import draft
        from battleship.domain.spectate import build_spectate_snapshot
        from battleship.domain.replay_v2 import finalize_v2
        assert await g.mystery_tech.begin(r)
        r.mystery_tech_state['offers']={'a':[{'tech_id':'sonar_pulse','refresh_used':False}],
                                     'b':[{'tech_id':'extra_supply','refresh_used':False}]}
        for pid,tech_id in [('a','sonar_pulse'),('b','extra_supply')]:
            ack=await g.mystery_tech_choose(Connection(sid=pid,user_id=pid),{'room_id':r.id,'player_id':pid,'tech_id':tech_id})
            assert ack['status']=='success'
            if pid=='a':
                assert not draft.snapshot(r,'b')['selected']
                assert 'sonar_pulse' not in json.dumps(build_spectate_snapshot(r))
        assert r.state==RoomState.ROCK_PAPER_SCISSORS
        for pid,choice in [('a','rock'),('b','scissors')]:
            assert (await g.rps_choice(Connection(sid=pid,user_id=pid),{'room_id':r.id,'player_id':pid,'choice':choice}))['status']=='success'
        assert r.state==RoomState.MYSTERY_TECH_RESOLUTION
        assert not r.players['b'].magic_hand
        private=build_room_sync(r,'a')['mystery_tech_state']
        assert private['target']['kind']=='sonar_pulse' and private['target']['deadline']==115000
        assert build_room_sync(r,'b')['mystery_tech_state']['target'] is None
        request=private['target']['request_id']
        ack=await g.mystery_tech_target(Connection(sid='b',user_id='b'),{'room_id':r.id,'player_id':'b','request_id':request,'x':0,'y':0})
        assert ack['status']=='error'
        ack=await g.mystery_tech_target(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a','request_id':request,'x':0,'y':0})
        assert ack['status']=='success' and r.state==RoomState.ATTACKING
        assert len(r.players['a'].revealed_positions)==2
        assert {(p.x,p.y) for p in r.players['a'].attacks}=={(0,1),(1,1)}
        assert len(r.players['b'].magic_hand)==4
        recording=finalize_v2(r)
        text=json.dumps(recording,ensure_ascii=False)
        assert 'sonar_pulse' in text and 'extra_supply' in text
        assert 'refresh_used' not in text and 'legal_cells' not in text
    asyncio.run(run())


def test_real_armor_and_reaction_and_future_shields():
    async def run():
        from battleship.domain.mystery_tech import effects as e
        from battleship.domain.magic import deck
        from battleship.domain import battle as rules
        r,rooms,g,magic,battle,pub,clock=stack()
        r.state=RoomState.ATTACKING;r.current_phase=RoomPhase.BATTLE;r.current_attacker='a';r.attacks_remaining=6
        e.apply(r,'b','armor_plating',g.rng)
        first=rules.resolve_attack(r,'a',0,0)
        assert first.hit and not first.ship_sunk and r.players['b'].remaining_ships==3
        assert Position(0,0) in r.players['a'].revealed_positions
        e.apply(r,'a','overload_reaction',g.rng)
        before=len(r.players['a'].magic_hand);budget=r.attacks_remaining
        ack=await battle.attack(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a','x':0,'y':0})
        assert ack['status']=='success'
        assert r.attacks_remaining==budget
        assert len(r.players['a'].magic_hand)==before+1
        e.apply(r,'b','steady_defense',g.rng)
        assert deck.revive_sunken_ships(r,'b',1)==1
        assert r.players['b'].ships[0].shield
        assert not e.absorb_armor(r,'b',r.players['b'].ships[0])
    asyncio.run(run())


def test_real_chain_amplifier_and_double_command():
    async def run():
        from battleship.domain.mystery_tech import effects as e
        from battleship.domain.magic.chain import ChainItem
        from battleship.domain.magic.cards import card_by_name
        r,rooms,g,magic,battle,pub,clock=stack()
        r.state=RoomState.ATTACKING;r.current_phase=RoomPhase.BATTLE;r.current_attacker='b'
        e.apply(r,'a','double_command',g.rng);e.apply(r,'a','chain_amplifier',g.rng)
        r.players['a'].magic_hand=[card_by_name('火力全开')]
        r.chain=[ChainItem('b',card_by_name('看破！'))];r.chain_waiting=True;r.chain_window='a'
        ack=await magic.chain_response(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a','chain':True,'card':card_by_name('火力全开').to_payload()})
        assert ack['status']=='success'
        if r.chain:
            await magic.resolve_chain(r)
        assert len(r.players['a'].magic_hand)==1
        await magic.stop()
    asyncio.run(run())


def test_target_timeout_fleet_stops_repair_fills_and_stale_reply_fails():
    async def one(tech_id):
        from battleship.domain.mystery_tech import draft
        from battleship.domain import battle as rules
        r,rooms,g,magic,battle,pub,clock=stack()
        if tech_id=='battlefield_recall':
            for ship in r.players['a'].ships[:2]:
                ship.hits=list(ship.positions);rules.apply_ship_sunk(r,'a',ship)
        await g.mystery_tech.begin(r)
        s=r.mystery_tech_state
        s.update(stage='locked',locked={'a':tech_id,'b':'extra_supply'})
        r.state=RoomState.ROCK_PAPER_SCISSORS;r.attack_order=['a','b'];r.current_attacker='a'
        await g.mystery_tech.start_resolution(r)
        request=s['target']['request_id'];clock[0]=115
        await g.sweep_timeouts()
        assert r.players['a'].remaining_ships==3
        assert r.state==RoomState.ATTACKING
        assert (await g.mystery_tech_target(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a','request_id':request,'x':5,'y':5}))['status']=='error'
    asyncio.run(one('fleet_rebirth'))
    asyncio.run(one('battlefield_recall'))


def test_disconnect_in_rps_is_a_casual_loss():
    async def run():
        from battleship.domain.settlement import settlement_facts
        r,rooms,g,magic,battle,pub,clock=stack()
        r.state=RoomState.ROCK_PAPER_SCISSORS;r.match_started_at=100;r.ban_initial_placement_complete=True
        r.ranked=True;r.disconnected['a']={'deadline':90,'token':1}
        await rooms._disconnect_timeout(r.id,'a',1)
        assert r.state==RoomState.GAME_OVER and r.winner=='b' and not r.ranked
        facts=settlement_facts(r,'b','a')
        assert facts.mode=='casual' and facts.count_stats
        assert any(event=='game_over' for event,data,target in pub.events)
    asyncio.run(run())


def test_before_placement_cannot_skip_and_normal_room_rejects_tech():
    async def run():
        r,rooms,g,magic,battle,pub,clock=stack()
        r.state=RoomState.PLACING_SHIPS;r.players['b'].ships=[]
        ack=await g.rps_choice(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a','choice':'rock'})
        assert ack['status']=='error' and r.state==RoomState.PLACING_SHIPS
        r.mystery_tech=False
        for method in (g.mystery_tech_choose,g.mystery_tech_refresh,g.mystery_tech_target):
            ack=await method(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a','slot':0,'tech_id':'extra_supply'})
            assert ack['status']=='error'
    asyncio.run(run())


def test_real_preparation_draws_and_round_five_gate():
    async def run():
        from battleship.domain.mystery_tech import effects as e
        from battleship.domain.magic.cards import card_by_name
        r,rooms,g,magic,battle,pub,clock=stack()
        # 失灵允许同名入手，确保断言检验真实摸牌次数而非重复弃牌规则。
        r.magic_deck=[card_by_name('失灵！') for _ in range(30)]
        r.round=4;r.state=RoomState.ROCK_PAPER_SCISSORS;r.attack_order=['a','b'];r.current_attacker='a'
        e.apply(r,'a','efficient_dispatch',g.rng);e.apply(r,'b','exclusion_zone',g.rng)
        await g._complete_rps_turn(r)
        assert len(r.players['a'].magic_hand)==1 and len(r.players['b'].magic_hand)==2
        r.current_attacker='b';r.current_phase=RoomPhase.END
        result=await g._apply_turn_end(r,'b')
        assert result['new_round'] and r.round==5 and r.state==RoomState.MYSTERY_TECH_SELECTION
        assert r.mystery_tech_state['selection_round']==5
    asyncio.run(run())


def test_both_targets_stay_sequential_and_second_deadline_starts_later():
    async def run():
        r,rooms,g,magic,battle,pub,clock=stack()
        await g.mystery_tech.begin(r)
        s=r.mystery_tech_state;s.update(stage='locked',locked={'a':'sonar_pulse','b':'fleet_rebirth'})
        r.attack_order=['a','b'];r.current_attacker='a'
        await g.mystery_tech.start_resolution(r)
        first=s['target'];assert first['player_id']=='a'
        clock[0]=110
        await g.mystery_tech_target(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a','request_id':first['request_id'],'x':0,'y':0})
        assert s['target']['player_id']=='b' and s['target']['deadline']==125000
        assert r.players['a'].remaining_ships==3
        clock[0]=125
        await g.sweep_timeouts()
        assert r.players['a'].remaining_ships==3 and r.players['b'].remaining_ships==3
        assert r.state==RoomState.ATTACKING
    asyncio.run(run())


def test_regular_magic_cannot_interrupt_tech_selection_or_resolution():
    async def run():
        from battleship.domain.magic.cards import card_by_name
        r,rooms,g,magic,battle,pub,clock=stack()
        r.current_attacker='a';r.current_phase=RoomPhase.PREPARATION
        card=card_by_name('无中生有');r.players['a'].magic_hand=[card]
        await g.mystery_tech.begin(r)
        for state in (RoomState.MYSTERY_TECH_SELECTION,RoomState.ROCK_PAPER_SCISSORS,RoomState.MYSTERY_TECH_RESOLUTION):
            r.state=state
            ack=await magic.use_magic_card(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a','card':card.to_payload()})
            assert ack['status']=='error' and r.players['a'].magic_hand==[card]
            assert not r.chain
        await magic.stop()
    asyncio.run(run())


def test_mode_guard_timeout_and_forfeit():
    async def run():
        r,rooms,g,magic,battle,pub,clock=stack()
        r.ranked=True;r.ban_enabled=True;r.ban_phase='selection';r.mutation_ids=['E2'];r.mutation_entries=[{'id':'E2'}]
        await g.mystery_tech.begin(r)
        assert not r.ranked and not r.ban_enabled and not r.mutation_ids
        clock[0]=120
        await g.sweep_timeouts()
        assert r.state==RoomState.ROCK_PAPER_SCISSORS
        assert len(r.mystery_tech_state['history'])==2
        assert (await battle.surrender(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a'}))['status']=='success'
        assert r.state==RoomState.GAME_OVER and r.winner=='b' and not r.ranked
        assert not any(event=='rank_changed' for event,data,target in pub.events)
    asyncio.run(run())
