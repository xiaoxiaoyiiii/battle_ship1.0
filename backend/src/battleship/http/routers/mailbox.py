"""玩家邮件与管理员投信接口。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from ...services.mailbox import MailboxService
from ..deps import require_user, require_admin

router=APIRouter(tags=['mailbox'])


@router.get('/api/admin/mailbox/catalog')
def mail_catalog(actor:str=Depends(require_admin)):
    from ...services.mailbox import CATALOGS
    return {'items':[{'kind':kind,'reward_id':r['id'],'name':r['name']}
                     for kind,items in CATALOGS.items() for r in items if r['id']!='none']}


@router.get('/api/mailbox')
def mailbox(request:Request,user_id:str=Depends(require_user)):
    return MailboxService(request.app.state.database).list(user_id)


@router.post('/api/mailbox/{mail_id}/{action}')
def change_mail(mail_id:str,action:str,request:Request,user_id:str=Depends(require_user)):
    service=MailboxService(request.app.state.database)
    if action not in ('claim','read','delete'):
        return JSONResponse({'ok':False,'reason':'未知邮件操作'},status_code=404)
    result=getattr(service,action)(user_id,mail_id)
    return JSONResponse(result,status_code=200 if result['ok'] else 409)


@router.post('/api/admin/mailbox/send')
async def send_mail(request:Request,actor:str=Depends(require_admin)):
    try:
        payload=await request.json()
        if not isinstance(payload,dict): raise ValueError('请求体须为对象')
        result=MailboxService(request.app.state.database).send(actor=actor,
            title=payload.get('title'),body=payload.get('body'),attachments=payload.get('attachments',[]),
            audience=payload.get('audience'),source_key=payload.get('source_key'))
    except (ValueError,TypeError) as exc:
        return JSONResponse({'ok':False,'reason':str(exc)},status_code=400)
    return result


@router.get('/api/activity-calendar')
def activity_calendar(request:Request):
    from ...services.ranked_seasons import RankedSeasonService
    service=RankedSeasonService(request.app.state.database)
    current=service.current()
    with request.app.state.database.unit_of_work() as uow:
        seasons=uow.ranked_seasons.seasons()
    return {'current_season_id':current['id'] if current else None,'seasons':seasons,
        'recurring':[{'name':'每日战术残局','schedule':'每天 00:00（沪时）更新'},
                     {'name':'每周突变','schedule':'每周更新；休闲匹配可体验'}]}
