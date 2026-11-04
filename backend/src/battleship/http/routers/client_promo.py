"""客户端下载提示弹窗的服务端账号维度每日去重。"""

from fastapi import APIRouter, Depends, Request

from ...services.client_promo import ClientPromoService
from ..deps import require_user

router = APIRouter(tags=["client-promo"])


@router.post("/api/client/promo/prompt")
def claim_client_promo(request: Request, user_id: str = Depends(require_user)):
    service = ClientPromoService(request.app.state.database)
    return {"show": service.claim_promo_day(user_id)}
