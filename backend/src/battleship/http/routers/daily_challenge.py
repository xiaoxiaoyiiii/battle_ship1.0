"""每日挑战只读入口，不向客户端返回双方船位、手牌或私有牌堆。"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from ..session import read_session, session_user_id

router = APIRouter(tags=['daily-challenge'])


@router.get('/api/daily-challenge')
def daily_challenge(request: Request):
    uid = session_user_id(read_session(request))
    return JSONResponse(request.app.state.daily_challenges.view(uid), headers={'Cache-Control': 'no-store'})
