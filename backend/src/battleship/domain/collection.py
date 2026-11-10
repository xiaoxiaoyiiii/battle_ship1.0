"""卡牌收藏、熟练与航海成就的唯一规则表及服务端对局事实。"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

THRESHOLDS = (10, 50, 100, 500)
MILESTONES = ((12, 50), (24, 100), (36, 150), (48, 300))
ACHIEVEMENTS = (
    {'id':'first_voyage','name':'初次出航','metric':'matches','target':1,'tide':30,'description':'完成 1 场有效匹配或排位'},
    {'id':'old_sailor','name':'老水手','metric':'wins','target':50,'tide':100,'description':'累计赢下 50 场匹配或排位'},
    {'id':'fleet_commander','name':'舰队统帅','metric':'wins','target':300,'tide':300,'title':'collection_commander','description':'累计赢下 300 场匹配或排位'},
    {'id':'winning_streak','name':'连战连捷','metric':'best_streak','target':5,'tide':100,'description':'在匹配或排位连赢 5 场'},
    {'id':'chain_breaker','name':'断链者','metric':'negations','target':2,'tide':80,'description':'一局内用失灵！成功打断 2 条不同连锁'},
    {'id':'deep_chain','name':'深潜连锁','metric':'chain','target':4,'tide':80,'description':'参与至少 4 层的连锁，并赢下这一局'},
    {'id':'last_ship','name':'孤舰翻盘','metric':'comeback','target':1,'tide':150,'title':'collection_last_ship','description':'己方仅剩 1 艘、对方仍有多艘时翻盘获胜'},
    {'id':'untouched','name':'无伤凯旋','metric':'flawless','target':1,'tide':150,'title':'collection_untouched','description':'整局从未沉过船并获胜'},
    {'id':'blitz','name':'闪电战','metric':'blitz','target':1,'tide':100,'description':'在第 5 大回合内获胜（含第 5 回合）'},
    {'id':'versatile','name':'万金油','metric':'winning_cards','target':24,'tide':100,'description':'24 种不同的卡各在胜利对局中打出过'},
    {'id':'all_cards','name':'万象精通','metric':'winning_cards','target':48,'tide':300,'title':'collection_all_cards','description':'全部 48 种卡各在胜利对局中打出过'},
    {'id':'first_glow','name':'初识光芒','metric':'mastery','target':10,'tide':50,'description':'任意一张卡达到 10 次熟练出牌'},
)


@lru_cache(maxsize=1)
def cards() -> tuple[dict, ...]:
    """卡名归并同名记录，沿用卡表顺序；不存在第二份手写卡目录。"""
    rows = json.loads((Path(__file__).parent/'magic/data/magic_card.json').read_text(encoding='utf-8'))
    unique = {}
    for row in rows:
        if row.get('name'):
            unique.setdefault(row['name'], row)
    return tuple(unique.values())


def mastery_title_id(name: str) -> str:
    return 'card_mastery_' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:12]


def title_entries() -> list[dict]:
    entries = [
        {'id':'collection_complete','name':'全图鉴','desc':'四十八张卡，都是亲手点亮的航迹','requirement':'点亮全部 48 种卡'},
        {'id':'collection_commander','name':'舰队统帅','desc':'三百次胜利锻造的指挥官','requirement':'完成成就「舰队统帅」'},
        {'id':'collection_last_ship','name':'孤舰不灭','desc':'最后一艘船也能驶回胜利的港湾','requirement':'完成成就「孤舰翻盘」'},
        {'id':'collection_untouched','name':'无伤凯旋','desc':'一舰未损，满载而归','requirement':'完成成就「无伤凯旋」'},
        {'id':'collection_all_cards','name':'万象精通','desc':'四十八种牌路都写过胜利','requirement':'完成成就「万象精通」'},
    ]
    return entries + [
        {'id':mastery_title_id(c['name']), 'name':c['name']+'宗师',
         'desc':'让这张牌成为你的海上传奇', 'requirement':f'在匹配或排位打出【{c["name"]}】500 次'}
        for c in cards()
    ]


def unlocked_tier(uses: int) -> int:
    return sum(int(uses) >= threshold for threshold in THRESHOLDS)


def achievement_view(state: dict, rows: list[dict], claimed: set[str]) -> list[dict]:
    metrics = {**state, 'winning_cards':sum(int(c.get('wins',0))>0 for c in rows),
               'mastery':max((int(c.get('uses',0)) for c in rows),default=0)}
    return [{**item, 'current':min(int(item['target']),int(metrics.get(item['metric'],0))),
             'unlocked':item['id'] in claimed} for item in ACHIEVEMENTS]


def observe(room) -> None:
    """在真实变更提交点采样，复活不能抹掉本局曾发生的沉船。"""
    if not room.match_started_at:
        return
    for pid, player in room.players.items():
        facts = room.collection_facts.setdefault(pid,{})
        alive = int(player.remaining_ships or 0)
        if 'initial_alive' not in facts and alive > 0:
            facts['initial_alive'] = alive
        if alive < facts.get('initial_alive',alive):
            facts['lost_ship'] = True
        if any(len(ship.hits)>=len(ship.positions)>0 for ship in player.ships) or player.sunken_ships or player.permanently_destroyed_ships:
            facts['lost_ship'] = True
        opponent = room.players.get(room.opponent_of(pid))
        if alive == 1 and opponent and opponent.remaining_ships > 1:
            facts['comeback'] = True


def note_play(room, player_id: str, name: str) -> None:
    """仅在合法支付并入链后调用，失败请求不经过这里。"""
    if room.settled or name not in {c['name'] for c in cards()}:
        return
    observe(room)
    facts = room.collection_facts.setdefault(player_id,{})
    plays = facts.setdefault('plays',{})
    plays[name] = plays.get(name,0)+1
    if len(room.chain)==1:
        room.collection_chain_id += 1
    depth = len(room.chain)
    for pid in {player_id, *(item.player_id for item in room.chain)}:
        participant = room.collection_facts.setdefault(pid,{})
        participant['chain'] = max(depth,participant.get('chain',0))


def note_negation(room, player_id: str) -> None:
    facts = room.collection_facts.setdefault(player_id,{})
    broken = facts.setdefault('broken_chains',[])
    if room.collection_chain_id not in broken:
        broken.append(room.collection_chain_id)
