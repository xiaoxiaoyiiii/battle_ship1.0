"""契约 Schema 的 HTTP 出口：前端可按 ETag/哈希做比对。"""

from __future__ import annotations

from fastapi import APIRouter, Response

from ...contracts.export_schema import schema_document

router = APIRouter(tags=["contracts"])


@router.get("/api/contracts/schema")
def contract_schema(response: Response):
    document = schema_document()
    response.headers["ETag"] = f'"{document["hash"]}"'
    response.headers["Cache-Control"] = "no-cache"
    return document
