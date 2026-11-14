"""收藏进度、自动奖励与所选光效；账号身份不从客户端参数取得。"""
from ..domain import collection as rules
from ..domain.skins import SKINS, SKINS_BY_ID, public_skin_id
from .gacha import SkinHttpError
import time


class CollectionService:
    def __init__(self,database):
        self.database=database

    def view(self,user_id):
        with self.database.unit_of_work() as u:
            if not user_id or not u.users.get(user_id):
                return None
            saved=u.collection.cards(user_id)
            owned_skins=u.skins.owned_ids(user_id)
            selections=u.skins.selections(user_id)
            rows=[]
            for card in rules.cards():
                progress=saved.get(card['name'],{'lit':False,'uses':0,'wins':0,'selected_tier':0})
                tier=rules.unlocked_tier(progress['uses'])
                next_target=rules.THRESHOLDS[tier] if tier<len(rules.THRESHOLDS) else None
                catalog=[s for s in SKINS if s.card_name==card['name']]
                card_owned=[s.skin_id for s in catalog if s.skin_id in owned_skins]
                selected=selections.get(card['name'])
                if public_skin_id(selected, card['name']) not in owned_skins:
                    selected='default'
                else:
                    selected=public_skin_id(selected, card['name'])
                rows.append({**card,**progress,'unlocked_tier':tier,
                    'selected_tier':min(tier,progress['selected_tier']),
                    'next_target':next_target,'remaining':max(0,next_target-progress['uses']) if next_target else 0,
                    'chain_description':('可在合法连锁窗口用来响应；仍须满足卡面时点、场地和封锁条件。'
                        if card.get('speed')==3 else '不能作为连锁响应牌；主动发动后，对手可用合法的速阶 3 卡响应。发动时点以卡面为准。'),
                    'skins':[{'skin_id':s.skin_id,'card_key':s.card_key,'tier':s.tier,'owned':s.skin_id in owned_skins} for s in catalog],
                    'owned_skins':card_owned,
                    'selected_skin':selected or 'default'})
            lit=sum(c['lit'] for c in rows)
            milestones=u.collection.claimed(user_id,'collection_milestone')
            return {'cards':rows,'lit_count':lit,'total':len(rows),'balance':u.tide_ash.balance(user_id),
                'shards':u.skins.shard_balance(user_id),
                'thresholds':list(rules.THRESHOLDS),
                'milestones':[{'target':n,'tide':t,'claimed':str(n) in milestones} for n,t in rules.MILESTONES],
                'achievements':rules.achievement_view(u.collection.state(user_id),rows,
                    u.collection.claimed(user_id,'collection_achievement'))}

    def selected_tier(self,user_id,name):
        if not user_id:
            return 0
        with self.database.unit_of_work() as u:
            card=u.collection.cards(user_id).get(name,{})
            return min(int(card.get('selected_tier',0)),rules.unlocked_tier(card.get('uses',0)))

    def selected_skin(self,user_id,name):
        if not user_id:
            return None
        with self.database.unit_of_work() as u:
            if not u.users.get(user_id):
                return None
            skin_id=u.skins.selected_skin(user_id,name)
            if public_skin_id(skin_id, name) and skin_id in u.skins.owned_ids(user_id):
                return skin_id
            return None

    def select_skin(self,user_id,name,skin, *, now=None):
        now = int(time.time()) if now is None else int(now)
        if not isinstance(name,str) or name not in {c['name'] for c in rules.cards()}:
            raise SkinHttpError(400,'unknown_card','未知的卡牌','card_name')
        if not isinstance(skin,str):
            raise SkinHttpError(400,'unknown_skin','请选择默认卡面或已拥有的皮肤','skin')
        if skin != 'default' and skin not in SKINS_BY_ID:
            raise SkinHttpError(400,'unknown_skin','未知的皮肤','skin')
        if skin != 'default' and SKINS_BY_ID[skin].card_name != name:
            raise SkinHttpError(400,'skin_card_mismatch','这件皮肤不属于这张卡','skin')
        with self.database.unit_of_work() as u:
            if not user_id or not u.users.get(user_id):
                raise SkinHttpError(401,'unauthorized','未登录','session')
            if skin == 'default':
                u.skins.clear_selection(user_id,name)
                return {'ok':True,'card_name':name,'selected_skin':'default'}
            if skin not in u.skins.owned_ids(user_id):
                raise SkinHttpError(409,'skin_not_owned','尚未拥有这件皮肤','skin')
            u.skins.set_selection(user_id,name,skin,now=now)
            return {'ok':True,'card_name':name,'selected_skin':skin}

    def select(self,user_id,name,tier):
        if type(tier) is not int or tier not in range(5) or not isinstance(name,str) or name not in {c['name'] for c in rules.cards()}:
            return {'ok':False,'error':'请选择有效的卡牌和光效档位'}
        with self.database.unit_of_work() as u:
            if not user_id or not u.users.get(user_id):
                return {'ok':False,'error':'请先登录'}
            u.tide_ash.lock(user_id)
            card=u.collection.cards(user_id).get(name,{})
            if tier>rules.unlocked_tier(card.get('uses',0)):
                return {'ok':False,'error':'这档光效还没有解锁'}
            u.collection.select(user_id,name,tier)
            return {'ok':True,'selected_tier':tier}

    def settlement_hook(self,room,u,context):
        facts=context.facts
        if room.admin_test or not facts.rewards_eligible or facts.mode not in ('casual','ranked','ai'):
            return
        rules.observe(room)
        real=facts.mode in ('casual','ranked') and not room.is_ai_room
        # 本人必须有注册账号；匹配来的真人游客不改变本局的模式口径。
        for pid,player in room.players.items():
            if player.registered and player.user_id and not pid.startswith('ai-') and u.users.get(player.user_id):
                self._settle(u,player.user_id,str(context.match_id),room.collection_facts.get(pid,{}),
                    real=bool(real),won=pid==facts.winner_id,round_no=room.round,now=context.timestamp)

    def settle_challenge(self,room,u,*,now):
        if room.admin_test:
            return
        uid=room.daily_challenge['user_id']
        if not u.users.get(uid):
            return
        pid=next((pid for pid,p in room.players.items() if p.user_id==uid),None)
        if pid:
            self._settle(u,uid,'daily:'+room.id,room.collection_facts.get(pid,{}),real=False,won=False,
                round_no=room.round,now=now)

    def _settle(self,u,uid,source,facts,*,real,won,round_no,now):
        u.tide_ash.lock(uid,now=now)
        if not u.collection.begin_once(uid,source):
            return
        names={c['name'] for c in rules.cards()}
        for name,count in facts.get('plays',{}).items():
            if name in names and type(count) is int and count>0:
                u.collection.add_card(uid,name,count if real else 0,bool(real and won))
                u.tide_ash.apply_once(uid,'collection_card',name,10,now=now)
        cards=list(u.collection.cards(uid).items())
        lit=sum(c['lit'] for _,c in cards)
        for target,tide in rules.MILESTONES:
            if lit>=target:
                u.tide_ash.apply_once(uid,'collection_milestone',str(target),tide,now=now)
                if target==48:
                    u.collection.grant_title(uid,'collection_complete',now)
        if not real:
            return
        state=u.collection.state(uid)
        state['matches']=state.get('matches',0)+1
        state['wins']=state.get('wins',0)+int(won)
        state['streak']=state.get('streak',0)+1 if won else 0
        state['best_streak']=max(state.get('best_streak',0),state['streak'])
        state['negations']=max(state.get('negations',0),len(facts.get('broken_chains',[])))
        if won:
            state['chain']=max(state.get('chain',0),facts.get('chain',0))
            for key,value in (('comeback',facts.get('comeback',False)),
                              ('flawless',not facts.get('lost_ship',False)),('blitz',1<=round_no<=5)):
                state[key]=max(state.get(key,0),int(value))
        u.collection.save_state(uid,state)
        for name,card in cards:
            if card['uses']>=500:
                u.collection.grant_title(uid,rules.mastery_title_id(name),now)
        for item in rules.achievement_view(state,[card for _,card in cards],set()):
            if item['current']>=item['target']:
                u.tide_ash.apply_once(uid,'collection_achievement',item['id'],item['tide'],now=now)
                if item.get('title'):
                    u.collection.grant_title(uid,item['title'],now)
