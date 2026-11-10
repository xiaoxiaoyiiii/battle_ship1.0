"""图鉴只读取当前账号，档位由服务端按熟练记录验证。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from ..deps import require_user
from ..errors import api_error

router=APIRouter(tags=['collection'])


@router.get('/api/collection')
def get_collection(request:Request,user_id:str=Depends(require_user)):
    body=request.app.state.collection.view(user_id)
    if body is None:
        raise api_error(401,'unauthorized','请先登录','session')
    return JSONResponse(body,headers={'Cache-Control':'no-store'})


@router.post('/api/collection/mastery')
async def select_mastery(request:Request,user_id:str=Depends(require_user)):
    try:
        data=await request.json()
    except ValueError:
        data=None
    if not isinstance(data,dict):
        raise api_error(400,'invalid_payload','请选择卡牌和光效档位','body')
    body=request.app.state.collection.select(user_id,data.get('card_name'),data.get('tier'))
    return JSONResponse(body,status_code=200 if body['ok'] else 400,headers={'Cache-Control':'no-store'})
