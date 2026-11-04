"""已抽中提醒的账号申请当天唯一展示机会。"""
from fastapi import APIRouter, Depends, Request

from ...services.support import SupportService
from ..deps import require_user

router = APIRouter(tags=['support'])


@router.post('/api/support/prompt')
def claim_support_prompt(request: Request, user_id: str = Depends(require_user)):
    return {'show': SupportService(request.app.state.database).claim(user_id)}
