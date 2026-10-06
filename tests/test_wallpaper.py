# -*- coding: utf-8 -*-
"""动态壁纸（Wallpaper Engine 接入）回归。

覆盖两件容易出错的事：
1. **"能不能播"的判断**。创意工坊里 video / scene / web 三种壁纸混在一起，
   每个目录还都带一张 preview.jpg。兜底逻辑一旦把预览图当成壁纸本体，
   玩家点到的就是"一张静止的缩略图冒充动态壁纸"——不报错、但完全是错的。
2. **边界**。扫描与按路径导入会读磁盘，必须只对本机开放；而媒体下发用的
   id 是注册表里的键，绝不能拿 URL 里的字符串去拼路径。
"""
import json

import pytest

import server
import wallpaper

MP4_HEAD = b'\x00\x00\x00\x18ftypisom' + b'\x00' * 64
WEBM_HEAD = b'\x1a\x45\xdf\xa3' + b'\x00' * 64
PNG_HEAD = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPG_HEAD = b'\xff\xd8\xff\xe0' + b'\x00' * 64
GIF_HEAD = b'GIF89a' + b'\x00' * 64
PKG_HEAD = b'PK\x03\x04' + b'\x00' * 64
HTML_HEAD = b'<html><body>hi</body></html>' + b'\x00' * 8


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """造一个假的创意工坊目录树，并把扫描指到它上面。"""
    root = tmp_path / 'workshop'
    root.mkdir()
    monkeypatch.setenv('BATTLESHIP_WALLPAPER_DIR', str(root))
    wallpaper.clear_cache()
    yield root
    wallpaper.clear_cache()


def make_folder(root, name, meta=None, files=None, preview=True):
    folder = root / name
    folder.mkdir()
    if meta is not None:
        (folder / 'project.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
    for filename, data in (files or {}).items():
        (folder / filename).write_bytes(data)
    if preview:
        (folder / 'preview.jpg').write_bytes(JPG_HEAD)
    return folder


def only(items, title):
    got = [it for it in items if it['title'] == title]
    assert got, '没有找到标题为 %s 的条目：%s' % (title, [it['title'] for it in items])
    return got[0]


# ---------- 文件内容识别（只信魔数，不信扩展名） ----------







# ---------- 单个壁纸目录的解析 ----------





















# ---------- 扫描整体行为 ----------









# ---------- 按路径导入 ----------















# ---------- HTTP 路由 ----------

@pytest.fixture
def client():
    server.app.config['TESTING'] = True
    return server.app.test_client()






def test_api_wallpapers_blocked_for_remote_client(lib, client):
    """远端访客不该知道这台机器上装了什么壁纸。"""
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    res = client.get('/api/wallpapers', environ_base={'REMOTE_ADDR': '8.8.8.8'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['available'] is False and data['items'] == []
    assert '本机' in data['reason']




















def test_media_route_rejects_path_traversal(client):
    """就算有人把路径塞进 URL，也只是查不到注册表条目。"""
    assert client.get('/api/wallpaper/media/..%2F..%2Fetc%2Fpasswd').status_code == 404
    assert client.get('/api/wallpaper/media/D:%5CWindows%5Cwin.ini').status_code == 404
