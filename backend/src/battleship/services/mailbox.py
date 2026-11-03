"""玩家邮箱、运营投递和附件领取用例。"""
import hashlib
import json
import time
from ..domain.progression import profile_spec
from ..infra.logging import get_logger

logger=get_logger('mailbox')
DAY=86400
CATALOGS={
    'title': profile_spec.TITLES, 'frame': profile_spec.FRAMES,
    'card_bg': profile_spec.CARD_BGS, 'profile_bg': profile_spec.PROFILE_BGS,
    'pointer': profile_spec.POINTER_EFFECTS, 'title_fx': profile_spec.TITLE_EFFECTS,
}


def validate_attachments(items):
    if not isinstance(items,list) or len(items)>10:
        raise ValueError('附件最多 10 项')
    result=[]
    for item in items:
        if not isinstance(item,dict):
            raise ValueError('附件格式错误')
        kind=item.get('kind')
        if kind=='tide_ash':
            amount=item.get('amount')
            if type(amount) is not int or not 1<=amount<=100000:
                raise ValueError('徽记数量须为 1～100000 的整数')
            result.append({'kind':kind,'amount':amount})
        elif kind in CATALOGS:
            rid=item.get('reward_id')
            resource=next((r for r in CATALOGS[kind] if r['id']==rid),None)
            if resource is None:
                raise ValueError('外观或称号不存在')
            result.append({'kind':kind,'reward_id':rid,'name':resource['name']})
        else:
            raise ValueError('不支持的附件类型')
    return result


def project(row,now):
    attachments=json.loads(row.attachments)
    return dict(id=row.id,title=row.title,body=row.body,attachments=attachments,
        created_at=row.created_at,expires_at=row.expires_at,
        attachment_expires_at=row.attachment_expires_at,read_at=row.read_at,
        claimed_at=row.claimed_at,unread=row.read_at is None,
        can_claim=bool(attachments and row.claimed_at is None and row.attachment_expires_at>now),
        can_delete=not attachments or row.claimed_at is not None or row.attachment_expires_at<=now)


class MailboxService:
    def __init__(self,database):
        self.database=database

    def list(self,uid,*,now=None):
        from .ranked_seasons import RankedSeasonService
        now=int(time.time()) if now is None else int(now)
        with self.database.unit_of_work() as uow:
            RankedSeasonService(self.database).sync(uow,now=now)
            items=[project(r,now) for r in uow.mailbox.list(uid,now)]
        return {'items':items,'unclaimed_count':sum(i['can_claim'] for i in items),
                'unread_count':sum(i['unread'] for i in items)}

    def send(self,*,actor,title,body,attachments,audience,source_key,now=None):
        now=int(time.time()) if now is None else int(now)
        title=str(title or '').strip()
        body=str(body or '').strip()
        if not title or len(title)>80 or not body or len(body)>5000:
            raise ValueError('请填写标题（最多 80 字）和正文（最多 5000 字）')
        if not isinstance(source_key,str) or not 1<=len(source_key)<=100:
            raise ValueError('缺少有效的发送编号')
        attachments=validate_attachments(attachments)
        if not isinstance(audience,dict) or audience.get('kind') not in ('all','single','condition'):
            raise ValueError('请选择收件范围')
        conditions=set(audience)-{'kind'}
        allowed={'min_rank_tier','max_rank_tier','min_level','max_level'}
        if audience['kind']=='condition':
            if not conditions or conditions-allowed:
                raise ValueError('条件群发需指定段位或等级范围')
            for key in conditions:
                ceiling=8 if 'tier' in key else 101
                if type(audience[key]) is not int or not 0<=audience[key]<=ceiling:
                    raise ValueError('群发条件超出范围')
            for lower,upper in [('min_rank_tier','max_rank_tier'),('min_level','max_level')]:
                if audience.get(lower,0)>audience.get(upper,101):
                    raise ValueError('条件下限不能高于上限')
        elif conditions-({'user_id'} if audience['kind']=='single' else set()):
            raise ValueError('收件范围包含未知条件')
        digest=hashlib.sha256(json.dumps([title,body,attachments,audience],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.database.unit_of_work() as uow:
            # 此写入先取得锁，重复请求不会重新展开群发收件人。
            if not uow.mailbox.dispatch_once(f'admin:{actor}:{source_key}',actor,digest,now):
                return {'ok':True,'delivered':0,'already_sent':True}
            recipients=uow.mailbox.recipients()
            if audience['kind']=='single':
                recipients=[r for r in recipients if r['id']==audience.get('user_id')]
                if not recipients:
                    raise ValueError('收件人不存在')
            elif audience['kind']=='condition':
                from .progression import ProgressionService
                progression=ProgressionService()
                selected=[]
                for r in recipients:
                    tier=progression.rank_view_for(uow,r['id'])['tier_index']
                    level=progression.level_view_for(uow,r['id'],xp=r['xp'] or 0)['level']
                    if (audience.get('min_rank_tier',0)<=tier<=audience.get('max_rank_tier',8)
                        and audience.get('min_level',0)<=level<=audience.get('max_level',101)):
                        selected.append(r)
                recipients=selected
            delivered=sum(uow.mailbox.deliver(r['id'],f'admin:{actor}:{source_key}',title,body,
                attachments,now,now+30*DAY,now+30*DAY) for r in recipients)
        logger.info('运营邮件已投递',extra={'actor':actor,'recipients':delivered,'source_key':source_key})
        return {'ok':True,'delivered':delivered,'already_sent':False}

    def claim(self,uid,mid,*,now=None):
        now=int(time.time()) if now is None else int(now)
        try:
            with self.database.unit_of_work() as uow:
                uow.tide_ash.lock(uid,now=now)
                row=uow.mailbox.get(uid,mid,now)
                if row is None:
                    result={'ok':False,'reason':'邮件不存在或已过期'}
                elif row.claimed_at is not None:
                    return {'ok':True,'already_claimed':True,'balance':uow.tide_ash.balance(uid)}
                elif row.attachment_expires_at<=now:
                    result={'ok':False,'reason':'附件已过领取期限'}
                elif not json.loads(row.attachments):
                    result={'ok':False,'reason':'该邮件没有附件'}
                elif not uow.mailbox.claim_once(uid,mid,now):
                    result={'ok':False,'reason':'邮件不可领取'}
                else:
                    for i,item in enumerate(validate_attachments(json.loads(row.attachments))):
                        if item['kind']=='tide_ash':
                            if not uow.tide_ash.apply_once(uid,'mail_reward',f'{mid}:{i}',item['amount'],now=now):
                                raise RuntimeError('邮件附件流水冲突')
                        else:
                            uow.mailbox.grant_cosmetic(uid,item['kind'],item['reward_id'],now)
                    return {'ok':True,'already_claimed':False,'balance':uow.tide_ash.balance(uid)}
            logger.warning('邮件领取失败',extra={'user_id':uid,'mail_id':mid,'reason':result['reason']})
            return result
        except Exception:
            logger.exception('邮件附件事务回滚',extra={'user_id':uid,'mail_id':mid})
            raise

    def read(self,uid,mid,*,now=None):
        now=int(time.time()) if now is None else int(now)
        with self.database.unit_of_work() as uow:
            row=uow.mailbox.get(uid,mid,now)
            if row is None: return {'ok':False,'reason':'邮件不存在或已过期'}
            row.read_at=row.read_at or now
        return {'ok':True}

    def delete(self,uid,mid,*,now=None):
        now=int(time.time()) if now is None else int(now)
        with self.database.unit_of_work() as uow:
            row=uow.mailbox.get(uid,mid,now)
            if row is None: return {'ok':False,'reason':'邮件不存在或已过期'}
            if not project(row,now)['can_delete']:
                return {'ok':False,'reason':'请先领取附件'}
            row.deleted_at=now
        return {'ok':True}
