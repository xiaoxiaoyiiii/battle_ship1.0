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

@pytest.mark.parametrize('head,expected', [
    (MP4_HEAD, 'video'),
    (WEBM_HEAD, 'video'),
    (PNG_HEAD, 'image'),
    (JPG_HEAD, 'image'),
    (GIF_HEAD, 'image'),
    (HTML_HEAD, None),
    (PKG_HEAD, None),
    (b'', None),
    (b'short', None),
])
def test_probe_kind_by_magic_bytes(tmp_path, head, expected):
    path = tmp_path / 'probe.bin'
    path.write_bytes(head)
    assert wallpaper.probe_kind(str(path)) == expected


def test_probe_kind_missing_file():
    assert wallpaper.probe_kind('D:/definitely/not/here.mp4') is None


def test_webp_is_image_but_webm_is_video(tmp_path):
    webp = tmp_path / 'a.webp'
    webp.write_bytes(b'RIFF' + b'\x00' * 4 + b'WEBP' + b'\x00' * 16)
    webm = tmp_path / 'b.webm'
    webm.write_bytes(b'RIFF' + b'\x00' * 4 + b'WEBM' + b'\x00' * 16)
    assert wallpaper.probe_kind(str(webp)) == 'image'
    assert wallpaper.probe_kind(str(webm)) == 'video'


# ---------- 单个壁纸目录的解析 ----------

def test_video_wallpaper_supported(lib):
    make_folder(lib, '111', {'type': 'video', 'title': '深海之城', 'file': 'wall.mp4'}, {'wall.mp4': MP4_HEAD})
    item = only(wallpaper.scan(force=True)['items'], '深海之城')
    assert item['supported'] is True
    assert item['kind'] == 'video'
    assert item['reason'] == ''
    assert item['media_url'].startswith('/api/wallpaper/media/' + item['id'])
    assert item['preview_url'].startswith('/api/wallpaper/preview/' + item['id'])
    assert wallpaper.get_media(item['id'])['media'].endswith('wall.mp4')


def test_media_url_carries_mtime_as_cache_buster(lib, tmp_path):
    """同一路径的壁纸文件被原地替换后，地址必须变 —— 否则浏览器会拿缓存里的旧图。"""
    import os
    folder = make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    first = only(wallpaper.scan(force=True)['items'], '甲')['media_url']
    media = folder / 'a.mp4'
    os.utime(str(media), (1_600_000_000, 1_600_000_000 + 60))
    second = only(wallpaper.scan(force=True)['items'], '甲')['media_url']
    assert first != second
    assert second.endswith('?v=' + str(int(media.stat().st_mtime)))


def test_image_wallpaper_supported(lib):
    make_folder(lib, '222', {'type': 'image', 'title': '静物', 'file': 'a.png'}, {'a.png': PNG_HEAD})
    item = only(wallpaper.scan(force=True)['items'], '静物')
    assert item['supported'] is True and item['kind'] == 'image'


def test_mkv_is_rejected_with_reason(lib):
    """浏览器播不了 mkv：必须明确标成不可用，而不是让玩家对着黑屏猜。"""
    make_folder(lib, '333', {'type': 'video', 'title': '星空', 'file': 'a.mkv'}, {'a.mkv': WEBM_HEAD})
    item = only(wallpaper.scan(force=True)['items'], '星空')
    assert item['supported'] is False
    assert '.mkv' in item['reason']
    assert item['media_url'] == ''
    # 不能播的条目不该进注册表，否则等于开了个取任意文件的接口
    assert wallpaper.get_media(item['id']) is None


def test_scene_wallpaper_not_mistaken_for_its_preview(lib):
    """场景型壁纸目录里有 preview.jpg，绝不能被当成"能播的壁纸"。"""
    make_folder(lib, '444', {'type': 'scene', 'title': '樱花场景', 'file': 'scene.pkg'}, {'scene.pkg': PKG_HEAD})
    item = only(wallpaper.scan(force=True)['items'], '樱花场景')
    assert item['supported'] is False
    assert '场景' in item['reason']
    assert wallpaper.get_media(item['id']) is None


def test_web_wallpaper_reported_as_unsupported(lib):
    make_folder(lib, '555', {'type': 'web', 'title': '网页壁纸', 'file': 'index.html'}, {'index.html': HTML_HEAD})
    item = only(wallpaper.scan(force=True)['items'], '网页壁纸')
    assert item['supported'] is False
    assert '网页' in item['reason']


def test_folder_without_project_json_falls_back_to_largest_media(lib):
    folder = lib / '666'
    folder.mkdir()
    (folder / 'small.mp4').write_bytes(MP4_HEAD)
    (folder / 'big.webm').write_bytes(WEBM_HEAD + b'\x00' * 500)
    item = only(wallpaper.scan(force=True)['items'], '666')
    assert item['supported'] is True
    assert wallpaper.get_media(item['id'])['media'].endswith('big.webm')


def test_project_file_escaping_folder_is_ignored(lib):
    """project.json 里写 ../../ 想读目录外的文件：必须被拒（这里退回目录内最大的媒体）。"""
    make_folder(lib, '777',
                {'type': 'video', 'title': '越界', 'file': '../../secret.mp4'},
                {'ok.mp4': MP4_HEAD})
    item = only(wallpaper.scan(force=True)['items'], '越界')
    assert item['supported'] is True
    assert wallpaper.get_media(item['id'])['media'].endswith('ok.mp4')


def test_title_falls_back_to_folder_name(lib):
    make_folder(lib, '888', {'type': 'video', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    item = only(wallpaper.scan(force=True)['items'], '888')
    assert item['id'].startswith('w')


def test_broken_project_json_does_not_crash(lib):
    folder = lib / '999'
    folder.mkdir()
    (folder / 'project.json').write_text('{ not json at all', encoding='utf-8')
    (folder / 'a.mp4').write_bytes(MP4_HEAD)
    items = wallpaper.scan(force=True)['items']
    assert only(items, '999')['supported'] is True


# ---------- 扫描整体行为 ----------

def test_scan_puts_usable_first_and_dedupes(lib):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    make_folder(lib, '222', {'type': 'video', 'title': '乙', 'file': 'b.mkv'}, {'b.mkv': WEBM_HEAD})
    items = wallpaper.scan(force=True)['items']
    assert [it['title'] for it in items] == ['甲', '乙']
    assert len({it['id'] for it in items}) == len(items)


def test_scan_result_is_cached_until_forced(lib):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    assert len(wallpaper.scan(force=True)['items']) == 1
    make_folder(lib, '222', {'type': 'video', 'title': '乙', 'file': 'b.mp4'}, {'b.mp4': MP4_HEAD})
    assert len(wallpaper.scan()['items']) == 1          # 命中缓存
    assert len(wallpaper.scan(force=True)['items']) == 2  # 强制刷新


def test_env_dir_pointing_at_single_wallpaper_folder(lib):
    """玩家把配置直接指到某一张壁纸目录上时也要能扫出来，而不是空列表。"""
    import os
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    os.environ['BATTLESHIP_WALLPAPER_DIR'] = str(lib / '111')
    wallpaper.clear_cache()
    try:
        items = wallpaper.scan(force=True)['items']
        assert [it['title'] for it in items] == ['甲']
    finally:
        os.environ['BATTLESHIP_WALLPAPER_DIR'] = str(lib)
        wallpaper.clear_cache()


def test_workshop_dirs_ignores_missing_override(monkeypatch):
    monkeypatch.setenv('BATTLESHIP_WALLPAPER_DIR', 'D:/definitely/not/here')
    assert wallpaper.workshop_dirs() == []


# ---------- 按路径导入 ----------

def test_import_path_single_file(lib, tmp_path):
    import os
    media = tmp_path / 'mine.mp4'
    media.write_bytes(MP4_HEAD)
    result = wallpaper.import_path(str(media))
    assert result['ok'] is True
    assert result['items'][0]['kind'] == 'video'
    # 注册表里存的是 realpath（临时目录常带符号链接，不能拿原串直接比）
    assert wallpaper.get_media(result['items'][0]['id'])['media'] == os.path.realpath(str(media))


def test_import_path_parent_directory(lib):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    make_folder(lib, '222', {'type': 'video', 'title': '乙', 'file': 'b.mp4'}, {'b.mp4': MP4_HEAD})
    result = wallpaper.import_path(str(lib))
    assert result['ok'] is True
    assert sorted(it['title'] for it in result['items']) == ['乙', '甲']


def test_import_path_missing(tmp_path):
    result = wallpaper.import_path(str(tmp_path / 'nope'))
    assert result['ok'] is False
    assert '不存在' in result['error']


def test_import_path_non_media_file(tmp_path):
    txt = tmp_path / 'note.txt'
    txt.write_text('hello', encoding='utf-8')
    assert wallpaper.import_path(str(txt))['ok'] is False


def test_import_path_empty():
    assert wallpaper.import_path('')['ok'] is False
    assert wallpaper.import_path('   ')['ok'] is False


def test_import_path_quoted_path(lib, tmp_path):
    """从资源管理器复制路径会带引号，要能吃掉。"""
    media = tmp_path / 'quoted.mp4'
    media.write_bytes(MP4_HEAD)
    assert wallpaper.import_path('"%s"' % media)['ok'] is True


def test_import_path_directory_without_media(lib, tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    result = wallpaper.import_path(str(empty))
    assert result['ok'] is False
    assert result['items'] == []


# ---------- HTTP 路由 ----------

@pytest.fixture
def client():
    server.app.config['TESTING'] = True
    return server.app.test_client()


def test_api_wallpapers_lists_items(lib, client):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    res = client.get('/api/wallpapers?refresh=1')
    assert res.status_code == 200
    data = res.get_json()
    assert data['available'] is True and data['dirs'] == 1
    assert [it['title'] for it in data['items']] == ['甲']


def test_api_wallpapers_without_library_explains_why(client, monkeypatch, tmp_path):
    monkeypatch.setenv('BATTLESHIP_WALLPAPER_DIR', str(tmp_path / 'nothing'))
    wallpaper.clear_cache()
    data = client.get('/api/wallpapers?refresh=1').get_json()
    assert data['available'] is True and data['items'] == []
    assert '创意工坊' in data['reason']


def test_api_wallpapers_blocked_for_remote_client(lib, client):
    """远端访客不该知道这台机器上装了什么壁纸。"""
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    res = client.get('/api/wallpapers', environ_base={'REMOTE_ADDR': '8.8.8.8'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['available'] is False and data['items'] == []
    assert '本机' in data['reason']


def test_allow_remote_env_opens_scan(monkeypatch, lib, client):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    monkeypatch.setenv('BATTLESHIP_WALLPAPER_ALLOW_REMOTE', '1')
    data = client.get('/api/wallpapers', environ_base={'REMOTE_ADDR': '8.8.8.8'}).get_json()
    assert data['available'] is True and len(data['items']) == 1


def test_scan_path_needs_custom_header(lib, client):
    """自定义头会让跨站请求触发预检，本站没有任何 CORS 放行头 —— 于是别的网页
    无法借用户的浏览器读本机文件。"""
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    res = client.post('/api/wallpaper/scan_path', json={'path': str(lib)})
    assert res.status_code == 403


def test_scan_path_ok_with_header(lib, client):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    res = client.post('/api/wallpaper/scan_path', json={'path': str(lib)},
                      headers={'X-Battleship-Wallpaper': '1'})
    assert res.status_code == 200
    assert res.get_json()['success'] is True
    assert res.get_json()['items'][0]['title'] == '甲'


def test_scan_path_blocked_for_remote_client(lib, client):
    res = client.post('/api/wallpaper/scan_path', json={'path': str(lib)},
                      headers={'X-Battleship-Wallpaper': '1'},
                      environ_base={'REMOTE_ADDR': '8.8.8.8'})
    assert res.status_code == 403


def test_scan_path_missing(tmp_path, client):
    res = client.post('/api/wallpaper/scan_path', json={'path': str(tmp_path / 'nope')},
                      headers={'X-Battleship-Wallpaper': '1'})
    assert res.status_code == 400
    assert res.get_json()['success'] is False


def test_media_route_serves_registered_file(lib, client):
    """按列表里给的那个地址（带 ?v= 版本号）去取，必须能取到。"""
    folder = make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    item = client.get('/api/wallpapers?refresh=1').get_json()['items'][0]
    res = client.get(item['media_url'])
    assert res.status_code == 200
    assert res.headers['Content-Type'].startswith('video/mp4')
    assert res.data == (folder / 'a.mp4').read_bytes()


def test_media_route_accepts_bare_id(lib, client):
    """不带版本号的老地址也要继续能用（玩家 localStorage 里存着旧地址）。"""
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    wid = client.get('/api/wallpapers?refresh=1').get_json()['items'][0]['id']
    assert client.get('/api/wallpaper/media/' + wid).status_code == 200


def test_media_route_supports_range_for_video_seeking(lib, client):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    item = client.get('/api/wallpapers?refresh=1').get_json()['items'][0]
    res = client.get(item['media_url'], headers={'Range': 'bytes=0-15'})
    assert res.status_code == 206
    assert len(res.data) == 16
    assert res.headers['Content-Range'].startswith('bytes 0-15/')


def test_media_route_rejects_unknown_id(client):
    assert client.get('/api/wallpaper/media/wdeadbeef').status_code == 404


def test_media_route_rejects_path_traversal(client):
    """就算有人把路径塞进 URL，也只是查不到注册表条目。"""
    assert client.get('/api/wallpaper/media/..%2F..%2Fetc%2Fpasswd').status_code == 404
    assert client.get('/api/wallpaper/media/D:%5CWindows%5Cwin.ini').status_code == 404


def test_preview_route(lib, client):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    wid = client.get('/api/wallpapers?refresh=1').get_json()['items'][0]['id']
    res = client.get('/api/wallpaper/preview/' + wid)
    assert res.status_code == 200
    assert res.headers['Content-Type'] == 'image/jpeg'


def test_preview_route_404_when_absent(lib, client):
    make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD}, preview=False)
    wid = client.get('/api/wallpapers?refresh=1').get_json()['items'][0]['id']
    assert client.get('/api/wallpaper/preview/' + wid).status_code == 404


def test_media_route_404_after_file_removed(lib, client):
    folder = make_folder(lib, '111', {'type': 'video', 'title': '甲', 'file': 'a.mp4'}, {'a.mp4': MP4_HEAD})
    wid = client.get('/api/wallpapers?refresh=1').get_json()['items'][0]['id']
    (folder / 'a.mp4').unlink()
    assert client.get('/api/wallpaper/media/' + wid).status_code == 404


def test_mime_for_unknown_extension():
    assert wallpaper.mime_for('x.weird') == 'application/octet-stream'
    assert wallpaper.mime_for('x.MP4') == 'video/mp4'


def test_index_page_includes_wallpaper_layer(client):
    """模板必须真的带上壁纸层与脚本，否则功能上线了但页面里什么都没有。"""
    html = client.get('/').get_data(as_text=True)
    assert 'id="wallpaper-layer"' in html
    assert 'id="wallpaper-video"' in html
    assert 'wallpaper.js' in html
    assert 'id="wp-scan"' in html
