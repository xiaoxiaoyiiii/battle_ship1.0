"""仅按签名会话查询本人任务，不接收客户端进度写入。"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from ..session import read_session, session_user_id
from ...services.tasks import task_view
router = APIRouter(tags=['tasks'])

@router.get('/api/tasks')
def get_tasks(request: Request):
    body = task_view(request.app.state.database, session_user_id(read_session(request)))
    return JSONResponse(body, headers={'Cache-Control': 'no-store'})
