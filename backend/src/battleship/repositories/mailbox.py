"""邮件持久化；领取状态与附件入账由同一事务提交。"""
import json
import uuid
from sqlalchemy import select, update, or_
from sqlalchemy.dialects.sqlite import insert
from .models import PlayerMail, MailDispatch, User, UserXp, UserRank, UserCosmeticReward


class MailboxRepository:
    def __init__(self,session):
        self.session=session

    def recipients(self):
        return [dict(r._mapping) for r in self.session.execute(select(
            User.id,User.created_at,UserXp.xp,UserRank.points,UserRank.is_admiral,
        ).outerjoin(UserXp,User.id==UserXp.user_id).outerjoin(UserRank,User.id==UserRank.user_id))]

    def dispatch_once(self, key, actor, digest, now):
        result=self.session.execute(insert(MailDispatch).values(
            source_key=key,actor=actor,payload_hash=digest,created_at=now,
        ).on_conflict_do_nothing(index_elements=['source_key']))
        if not result.rowcount:
            previous=self.session.get(MailDispatch,key)
            if previous.payload_hash!=digest or previous.actor!=actor:
                raise ValueError('发送编号已经用于另一封邮件')
        return bool(result.rowcount)

    def deliver(self,uid,key,title,body,attachments,now,expires,attachment_expires):
        result=self.session.execute(insert(PlayerMail).values(
            id=uuid.uuid4().hex,user_id=uid,source_key=key,title=title,body=body,
            attachments=json.dumps(attachments,ensure_ascii=False),created_at=now,
            expires_at=expires,attachment_expires_at=attachment_expires,
        ).on_conflict_do_nothing(index_elements=['user_id','source_key']))
        return bool(result.rowcount)

    @staticmethod
    def visible(now):
        return (PlayerMail.deleted_at.is_(None),or_(
            (PlayerMail.claimed_at.is_(None)) & (PlayerMail.expires_at>now),
            PlayerMail.claimed_at+7*86400>now))

    def list(self,uid,now):
        return self.session.scalars(select(PlayerMail).where(PlayerMail.user_id==uid,
            *self.visible(now)).order_by(PlayerMail.created_at.desc(),PlayerMail.id)).all()

    def get(self,uid,mid,now):
        return self.session.scalar(select(PlayerMail).where(PlayerMail.user_id==uid,
            PlayerMail.id==mid,*self.visible(now)))

    def claim_once(self,uid,mid,now):
        return bool(self.session.execute(update(PlayerMail).where(
            PlayerMail.user_id==uid,PlayerMail.id==mid,PlayerMail.deleted_at.is_(None),
            PlayerMail.claimed_at.is_(None),PlayerMail.expires_at>now,
            PlayerMail.attachment_expires_at>now,
        ).values(claimed_at=now,read_at=now)).rowcount)

    def grant_cosmetic(self,uid,kind,rid,now):
        self.session.execute(insert(UserCosmeticReward).values(user_id=uid,kind=kind,
            reward_id=rid,source_track='mail',granted_at=now,
        ).on_conflict_do_nothing(index_elements=['user_id','kind','reward_id']))
