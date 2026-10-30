"""Dynamic wallpaper channels (ticket #15).

Visibility is deliberately split like the legacy API:

* scanning/importing local paths is localhost-only (+ a custom header for the
  POST). A non-local request still gets HTTP 200 for /api/wallpapers with
  available=false, because the old frontend renders that explanation.
* media/preview are not localhost-gated: ids are path hashes and only reachable
  after a local scan registered them.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from ...domain.progression import wallpaper

router = APIRouter(tags=["wallpapers"])

WALLPAPER_HEADER = "X-Battleship-Wallpaper"


def _remote_blocked(request: Request) -> bool:
    if os.environ.get("BATTLESHIP_WALLPAPER_ALLOW_REMOTE") == "1":
        return False
    client = getattr(request, "client", None)
    address = (getattr(client, "host", "") or "").strip().lower()
    if not address:
        return False
    return not (
        address in ("localhost", "::1")
        or address.startswith("127.")
        or address.startswith("::ffff:127.")
    )


@router.get("/api/wallpapers")
def list_wallpapers(request: Request):
    if _remote_blocked(request):
        return JSONResponse({
            "available": False,
            "success": False,
            "items": [],
            "dirs": 0,
            "reason": "扫描本机壁纸库只在本机（localhost）访问时可用；在别的设备上请用下面的「直链」导入。",
        })
    data = wallpaper.scan(force=request.query_params.get("refresh") in ("1", "true", "yes"))
    dirs = data["dirs"]
    reason = "" if dirs else (
        "没有找到 Wallpaper Engine 的创意工坊目录"
        "（Steam 里没装过壁纸，或壁纸装在别的库）——可以往下填「壁纸文件夹」路径。"
    )
    return JSONResponse({
        "available": True,
        "success": True,
        "dirs": len(dirs),
        "reason": reason,
        "items": data["items"],
    })


@router.post("/api/wallpaper/scan_path")
async def scan_path(request: Request):
    if _remote_blocked(request):
        return JSONResponse(
            {"success": False, "items": [], "error": "按路径导入只在本机（localhost）访问时可用。"},
            status_code=403,
        )
    if request.headers.get(WALLPAPER_HEADER) != "1":
        return JSONResponse(
            {"success": False, "items": [], "error": "缺少本机校验头。"},
            status_code=403,
        )
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    result = wallpaper.import_path((payload or {}).get("path") or "")
    if not result["ok"]:
        return JSONResponse(
            {"success": False, "error": result["error"], "items": []},
            status_code=400,
        )
    return JSONResponse({"success": True, "error": "", "items": result["items"]})


@router.get("/api/wallpaper/media/{wid}")
def wallpaper_media(wid: str):
    entry = wallpaper.get_media(wid)
    if not entry:
        return JSONResponse(
            {"error": "壁纸不存在或未注册（%s）" % wid}, status_code=404
        )
    path = entry["media"]
    if not os.path.isfile(path):
        return JSONResponse({"error": "壁纸文件已不在原位置"}, status_code=404)
    return FileResponse(
        path,
        media_type=wallpaper.mime_for(path),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/api/wallpaper/preview/{wid}")
def wallpaper_preview(wid: str):
    entry = wallpaper.get_preview(wid)
    if not entry:
        return JSONResponse({"error": "没有这张壁纸的缩略图"}, status_code=404)
    path = entry["preview"]
    if not os.path.isfile(path):
        return JSONResponse({"error": "缩略图已不在原位置"}, status_code=404)
    return FileResponse(
        path,
        media_type=wallpaper.mime_for(path),
        headers={"Cache-Control": "public, max-age=3600"},
    )
