"""管理员 F8 控制台与运营联系入口。"""
import re
import time
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from ...infra.ratelimit import client_key
from ...services.admin_console import catalog
from ..deps import require_admin
from ..session import read_session, session_user_id

router = APIRouter(tags=['admin-console'])


def same_origin_json(request):
    origin = request.headers.get('origin')
    return 'application/json' in request.headers.get('content-type', '') and (
        not origin or origin.rstrip('/') == str(request.base_url).rstrip('/'))


@router.get('/api/admin/console')
def console_catalog(request: Request, actor: str = Depends(require_admin)):
    return catalog(request.app.state.magic)


@router.post('/api/admin/console')
async def console_command(request: Request, actor: str = Depends(require_admin)):
    if not same_origin_json(request):
        return JSONResponse({'status': 'error', 'message': '仅支持本站 JSON 请求'}, status_code=403)
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('请求体必须为对象')
        return await request.app.state.admin_console.execute(actor, payload.get('room_id'),
                                                            payload.get('action'), payload.get('params', {}))
    except PermissionError as error:
        return JSONResponse({'status': 'error', 'message': str(error)}, status_code=403)
    except (ValueError, TypeError) as error:
        return JSONResponse({'status': 'error', 'message': str(error)}, status_code=400)


@router.post('/api/operator-contact')
async def operator_contact(request: Request):
    if not same_origin_json(request):
        return JSONResponse({'ok': False, 'reason': '仅支持本站 JSON 请求'}, status_code=403)
    limiter = request.app.state.rate_limiter
    if limiter and limiter.hit('operator-contact', client_key(request)):
        return JSONResponse({'ok': False, 'reason': '提交过于频繁，请稍后重试'}, status_code=429)
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('请求体必须为对象')
        key = payload.get('request_id')
        message = payload.get('message')
        subject = payload.get('subject')
        contact = payload.get('contact', '')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key):
            raise ValueError('缺少有效请求编号')
        if not isinstance(message, str) or not 5 <= len(message.strip()) <= 2000:
            raise ValueError('请填写 5～2000 字的具体说明')
        subjects = {'privacy': '隐私与账号申请', 'bug': '问题反馈', 'appeal': '申诉', 'other': '联系运营'}
        if subject not in subjects:
            raise ValueError('请选择联系事项')
        if not isinstance(contact, str) or len(contact) > 150:
            raise ValueError('联系方式过长')
        uid = session_user_id(read_session(request))
        if not uid and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', contact):
            raise ValueError('未登录时请留下可回复的邮箱')
        admins = request.app.state.settings.debug_admin_user_ids
        if len(admins) != 1:
            return JSONResponse({'ok': False, 'reason': '运营联系暂不可用，请稍后重试'}, status_code=503)
        admin = next(iter(admins))
        if not request.app.state.auth.is_admin(admin):
            return JSONResponse({'ok': False, 'reason': '运营联系暂不可用，请稍后重试'}, status_code=503)
        now = int(time.time())
        with request.app.state.database.unit_of_work() as uow:
            uow.mailbox.deliver(admin, f'contact:{uid or "visitor"}:{key}', subjects[subject],
                f'请求编号：{key}\n账号 ID：{uid or "未登录，需先核验身份"}\n回复渠道：{contact or "站内邮箱"}\n\n{message.strip()}',
                [], now, now + 30 * 86400, now + 30 * 86400)
        return {'ok': True, 'request_id': key, 'message': '已投递运营邮箱，请保留请求编号'}
    except (ValueError, TypeError) as error:
        return JSONResponse({'ok': False, 'reason': str(error)}, status_code=400)
