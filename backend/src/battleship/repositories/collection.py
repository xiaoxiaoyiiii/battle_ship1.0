"""新图鉴数据均在调用方结算事务内写入。"""
import json
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from .models import CollectionCard, CollectionProgress, CollectionSettlement, TideAshLedger, UserCosmeticReward


class CollectionRepository:
    def __init__(self, session):
        self.session=session

    def cards(self,user_id):
        rows=self.session.scalars(select(CollectionCard).where(CollectionCard.user_id==user_id))
        return {r.card_name:{'lit':bool(r.lit),'uses':r.uses,'wins':r.wins,'selected_tier':r.selected_tier} for r in rows}

    def add_card(self,user_id,name,uses=0,won=False):
        self.session.execute(insert(CollectionCard).values(user_id=user_id,card_name=name,lit=1,
            uses=int(uses),wins=int(won),selected_tier=0).on_conflict_do_update(
                index_elements=['user_id','card_name'],set_={'lit':1,
                    'uses':CollectionCard.uses+int(uses),'wins':CollectionCard.wins+int(won)}))

    def select(self,user_id,name,tier):
        row=self.session.get(CollectionCard,(user_id,name))
        if row is not None:
            row.selected_tier=tier

    def state(self,user_id):
        row=self.session.get(CollectionProgress,user_id)
        return json.loads(row.state) if row else {}

    def save_state(self,user_id,state):
        raw=json.dumps(state,ensure_ascii=False,separators=(',',':'))
        self.session.execute(insert(CollectionProgress).values(user_id=user_id,state=raw)
            .on_conflict_do_update(index_elements=['user_id'],set_={'state':raw}))

    def begin_once(self,user_id,source_id):
        return bool(self.session.execute(insert(CollectionSettlement).values(user_id=user_id,source_id=source_id)
            .on_conflict_do_nothing(index_elements=['user_id','source_id'])).rowcount)

    def claimed(self,user_id,kind):
        return set(self.session.scalars(select(TideAshLedger.source_id).where(
            TideAshLedger.user_id==user_id,TideAshLedger.source_kind==kind)))

    def grant_title(self,user_id,title_id,now):
        self.session.execute(insert(UserCosmeticReward).values(user_id=user_id,kind='title',reward_id=title_id,
            source_track='collection',granted_at=now).on_conflict_do_nothing(index_elements=['user_id','kind','reward_id']))
