"""真实组合根、隔离库胜负结算，以及既有重连接口。"""
import asyncio
import json

from test_skin_gacha import stack as application, register
from test_mystery_tech import make_room
from test_mystery_tech_flow import stack
from battleship.services.rooms import Connection
from battleship.domain.room import RoomState


def test_tech_windows_remain_in_live_spectator_directory(application):
    async def run():
        from battleship.services.spectators import SpectatorService
        app,client=application
        a=register(client,'tech_watch_a');b=register(client,'tech_watch_b')
        r=make_room();r.matchmade=True
        for pid,user in [('a',a),('b',b)]:
            r.players[pid].user_id=user['id'];r.players[pid].registered=True
        app.state.rooms.rooms[r.id]=r
        watching=SpectatorService(app.state.rooms,app.state.database)
        for user in (a,b): watching.set_setting(user['id'],True)
        for state in (RoomState.MYSTERY_TECH_SELECTION,RoomState.MYSTERY_TECH_RESOLUTION):
            r.state=state
            assert any(match['room_id']==r.id for match in watching.live_matches())
    asyncio.run(run())


def test_application_casual_outcome_saves_stats_and_replay_without_rank(application):
    async def run():
        app,client=application
        a=register(client,'tech_app_a');b=register(client,'tech_app_b')
        r=make_room();r.matchmade=True;r.ban_initial_placement_complete=True
        for pid,user in [('a',a),('b',b)]:
            r.players[pid].user_id=user['id'];r.players[pid].registered=True
        app.state.rooms.rooms[r.id]=r
        await app.state.gameplay.mystery_tech.begin(r)
        s=r.mystery_tech_state
        s['offers']={'a':[{'tech_id':'sonar_pulse','refresh_used':False}],
                     'b':[{'tech_id':'extra_supply','refresh_used':False}]}
        for pid,user,key in [('a',a,'sonar_pulse'),('b',b,'extra_supply')]:
            result=await app.state.gameplay.mystery_tech_choose(Connection(sid=pid,user_id=user['id']),
                {'room_id':r.id,'player_id':pid,'tech_id':key})
            assert result['status']=='success'
        result=await app.state.battle.surrender(Connection(sid='a',user_id=a['id']),{'room_id':r.id,'player_id':'a'})
        assert result['status']=='success' and r.winner=='b'
        assert r.settlement_result.ok and r.settlement_result.match_id
        from battleship.repositories.models import UserRank
        with app.state.database.unit_of_work() as u:
            match=u.matches.get(r.settlement_result.match_id)
            assert match.mode=='casual' and match.rewards_eligible
            assert u.users.get(a['id']).losses==1 and u.users.get(b['id']).wins==1
            for user in (a,b):
                rank=u.session.get(UserRank,user['id'])
                assert rank is None or (rank.points==0 and rank.ranked_wins==0 and rank.ranked_losses==0)
        response=client.get('/api/replay/'+r.settlement_result.match_id)
        assert response.status_code==200
        text=json.dumps(response.json(),ensure_ascii=False)
        assert 'sonar_pulse' in text and 'extra_supply' in text
        assert 'refresh_used' not in text and 'legal_cells' not in text
    asyncio.run(run())


def test_real_rejoin_restores_only_the_owners_options():
    async def run():
        r,rooms,g,magic,battle,pub,clock=stack()
        await g.mystery_tech.begin(r)
        ack=await rooms.get_reconnect_token(Connection(sid='a',user_id='a'),{'room_id':r.id,'player_id':'a'})
        token=ack['token'];before=r.mystery_tech_state['offers']['a']
        r.disconnected['a']={'deadline':130,'token':1}
        result=await rooms.rejoin_room(Connection(sid='a-new',user_id='a'),{'room_id':r.id,'player_id':'a','token':token})
        assert result['status']=='success'
        restored=[data for event,data,target in pub.events if event=='room_sync' and target.get('to')=='a-new'][-1]
        options=restored['mystery_tech_state']['options']
        assert [slot['tech_id'] for slot in options]==[slot['tech_id'] for slot in before]
        assert restored['mystery_tech_state']['deadline']==120000
        assert 'a' not in r.disconnected
        assert not any(target.get('room') and 'refresh_used' in json.dumps(data) for event,data,target in pub.events)
    asyncio.run(run())
