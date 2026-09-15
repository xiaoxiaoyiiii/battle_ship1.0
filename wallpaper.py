# -*- coding: utf-8 -*-
"""本机壁纸接入：Wallpaper Engine 创意工坊 + 任意本地媒体文件。

【它解决什么】
玩家希望把 Wallpaper Engine 里买的动态壁纸当游戏背景。创意工坊的壁纸
就躺在磁盘上，但网页拿不到；这里让服务端去**读磁盘**，把可播放的那一个
文件挑出来，注册成一个 id，前端用 `<video>/<img>` 指过去即可。

【三条导入通道，能力与限制各不相同】
1. 扫描创意工坊（本机可用）：自动定位 Steam 库 → `workshop/content/431960/*`
2. 粘贴路径（本机可用）：直接给文件夹或文件路径，服务端自己读
3. 直链（任何环境可用）：前端直接把 `<video src>` 指到网络地址，不经服务端

【为什么扫描要限制在本机（回环地址）】
"列出这台机器装了什么壁纸"本身就是在暴露本机信息，远端访客没有理由拿到。
`import_path` 更是直接由用户指定文件路径 —— 虽然加了回环 + 自定义请求头
两道门，仍然只应在本机运行场景下开放。

【为什么媒体文件本身不限制回环】
id 是**路径的 sha1 前 14 位**，不可枚举；注册只可能发生在回环请求里。
因此局域网/远端访问同一台服务器时，之前导出的壁纸仍然能正常播放，
不会出现"本机能看、手机看不了"的割裂。

【为什么单独一个模块】
扫描与解析是纯函数（给目录 → 给一份清单），和 Flask 路由分开后，测试可以
直接喂临时目录断言结果，不必伪造一套 Steam 安装环境。
"""
import hashlib
import json
import os
import time

# Wallpaper Engine 在 Steam 上的 AppID，创意工坊内容固定放这个目录
WALLPAPER_ENGINE_APP_ID = '431960'

# 扫描结果缓存（秒）：设置面板反复打开时不必每次都遍历磁盘
_SCAN_TTL = 20

# 扩展名 → 媒体类别
MEDIA_EXT = {
    '.mp4': 'video', '.webm': 'video', '.m4v': 'video', '.ogv': 'video',
    '.mov': 'video', '.mkv': 'video', '.avi': 'video',
    '.gif': 'image', '.apng': 'image', '.png': 'image', '.jpg': 'image',
    '.jpeg': 'image', '.webp': 'image', '.bmp': 'image',
}

# 浏览器能直接播的视频容器。.mov/.mkv/.avi 里装的多半是浏览器解不了的编码，
# 与其让玩家对着黑屏猜，不如明确标成"不支持"并说明原因。
PLAYABLE_VIDEO_EXT = {'.mp4', '.webm', '.m4v', '.ogv'}

PREVIEW_EXT = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')

MIME = {
    '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.webm': 'video/webm',
    '.ogv': 'video/ogg', '.mov': 'video/quicktime', '.mkv': 'video/x-matroska',
    '.avi': 'video/x-msvideo',
    '.gif': 'image/gif', '.apng': 'image/apng', '.png': 'image/png',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
    '.bmp': 'image/bmp',
}

# id → {'media': 绝对路径, 'preview': 绝对路径|None, 'kind': 'video'|'image', 'source': 'steam'|'local'}
_registry: dict = {}
# 上次扫描结果
_scan_cache = {'ts': 0.0, 'data': None}


def _real(path: str) -> str:
    try:
        return os.path.realpath(os.path.abspath(path))
    except (OSError, ValueError):
        return path


def make_id(path: str) -> str:
    """由路径推导稳定 id。同一台机器上同一文件永远是同一个 id，
    前端存进 localStorage 的地址因此在重启后依然有效。"""
    return 'w' + hashlib.sha1(_real(path).encode('utf-8', 'replace')).hexdigest()[:14]


def probe_kind(path: str):
    """读文件头判断真实媒体类别；不是图片/视频就返回 None。

    只信内容不信扩展名 —— 改个后缀就能让服务端把任意文件当壁纸播出去，
    那不是我们想要的能力。
    """
    try:
        with open(path, 'rb') as fh:
            head = fh.read(32)
    except OSError:
        return None
    if len(head) < 12:
        return None
    # ISO BMFF（mp4 / m4v / mov）：4 字节长度 + 'ftyp'
    if head[4:8] == b'ftyp':
        return 'video'
    # Matroska / WebM
    if head[:4] == b'\x1a\x45\xdf\xa3':
        return 'video'
    # RIFF 容器：WEBP 是图片，WEBM 是视频
    if head[:4] == b'RIFF':
        if head[8:12] == b'WEBP':
            return 'image'
        if head[8:12] == b'WEBM':
            return 'video'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image'
    if head.startswith(b'\xff\xd8\xff'):
        return 'image'
    if head.startswith(b'GIF87a') or head.startswith(b'GIF89a'):
        return 'image'
    if head.startswith(b'BM'):
        return 'image'
    return None


# ---------- Steam 库定位 ----------

def _vdf_library_paths(vdf_path: str):
    """从 libraryfolders.vdf 里抠出所有库路径。

    VDF 是 Valve 的私有格式，这里不做完整解析：目标行固定形如
        "path"      "D:\\SteamLibrary"
    用逐行扫描足够稳，也不会被格式演进打脸。
    """
    out = []
    try:
        with open(vdf_path, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                line = line.strip()
                if not line.lower().startswith('"path"'):
                    continue
                parts = line.split('"')
                # '"path"  "值"' → ['', 'path', '  ', '值', '']
                if len(parts) >= 4 and parts[3].strip():
                    out.append(parts[3].strip().replace('\\\\', os.sep))
    except OSError:
        pass
    return out


def _windows_steam_roots():
    """Windows：从注册表拿 Steam 安装目录。"""
    roots = []
    try:
        import winreg
    except ImportError:
        return roots
    candidates = (
        (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', ('SteamPath', 'InstallPath')),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', ('InstallPath',)),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', ('InstallPath',)),
    )
    for hive, key, names in candidates:
        try:
            with winreg.OpenKey(hive, key) as handle:
                for name in names:
                    try:
                        value = winreg.QueryValueEx(handle, name)[0]
                    except OSError:
                        continue
                    if value:
                        roots.append(str(value))
        except OSError:
            continue
    return roots


def _guess_steam_roots():
    """不查注册表时的兜底猜测（也覆盖 Linux / macOS）。"""
    guesses = []
    for var in ('ProgramFiles(x86)', 'ProgramFiles', 'ProgramW6432'):
        base = os.environ.get(var)
        if base:
            guesses.append(os.path.join(base, 'Steam'))
    home = os.path.expanduser('~')
    guesses += [
        os.path.join(home, '.steam', 'steam'),
        os.path.join(home, '.local', 'share', 'Steam'),
        os.path.join(home, 'Library', 'Application Support', 'Steam'),
    ]
    return guesses


def steam_roots():
    """所有 Steam 根目录（去重、保序、只保留真实存在的）。"""
    seen, out = set(), []
    for root in _windows_steam_roots() + _guess_steam_roots():
        if not root:
            continue
        real = _real(root)
        if real in seen or not os.path.isdir(real):
            continue
        seen.add(real)
        out.append(real)
    return out


def workshop_dirs():
    """Wallpaper Engine 创意工坊内容目录列表。

    环境变量 `BATTLESHIP_WALLPAPER_DIR`（多个用 `;` / `:` 分隔）可覆盖 ——
    既是给壁纸放在非 Steam 目录的玩家的出口，也是测试注入临时目录的钩子。
    """
    override = os.environ.get('BATTLESHIP_WALLPAPER_DIR') or os.environ.get('BATTLESHIP_WALLPAPER_DIRS')
    if override:
        out = []
        for chunk in override.split(os.pathsep):
            chunk = chunk.strip().strip('"')
            if chunk and os.path.isdir(chunk):
                out.append(_real(chunk))
        return out
    seen, out = set(), []
    for root in steam_roots():
        steamapps = [os.path.join(root, 'steamapps')]
        for lib in _vdf_library_paths(os.path.join(root, 'steamapps', 'libraryfolders.vdf')):
            steamapps.append(os.path.join(lib, 'steamapps'))
        for base in steamapps:
            target = os.path.join(base, 'workshop', 'content', WALLPAPER_ENGINE_APP_ID)
            real = _real(target)
            if real in seen or not os.path.isdir(real):
                continue
            seen.add(real)
            out.append(real)
    return out


# ---------- 单个壁纸的描述 ----------

def _join_inside(folder: str, rel: str):
    """把 project.json 里的相对路径拼进壁纸目录，并拒绝越界。"""
    if not rel:
        return None
    rel = rel.replace('\\', os.sep).replace('/', os.sep)
    target = _real(os.path.join(folder, rel))
    root = _real(folder)
    if target != root and not target.startswith(root + os.sep):
        return None
    return target if os.path.isfile(target) else None


def _largest_media(folder: str, skip=None):
    """目录里最大的媒体文件（创意工坊壁纸通常只有一两个媒体文件）。

    ⚠️ 必须把 `preview.*` 排除掉：创意工坊每张壁纸都带一张预览图，而场景型 /
    网页型壁纸的 `file` 字段指向 scene.pkg / index.html —— 一旦兜底逻辑把
    preview.jpg 当成"壁纸本体"，就会把**不能播的壁纸报成能播**，玩家点上去
    只会得到一张静态缩略图冒充壁纸。
    """
    skip = skip or set()
    best, best_size = None, -1
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if name in skip or name.lower().startswith('preview'):
            continue
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in MEDIA_EXT:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > best_size:
            best, best_size = path, size
    return best


def _read_project(folder: str):
    """读 Wallpaper Engine 的 project.json；坏文件按"没有"处理。"""
    path = os.path.join(folder, 'project.json')
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_preview(folder: str, meta: dict, media: str, kind: str):
    names = []
    declared = str(meta.get('preview') or '').strip()
    if declared:
        names.append(declared)
    names += ['preview.jpg', 'preview.jpeg', 'preview.png', 'preview.gif', 'preview.webp', 'preview.bmp']
    for name in names:
        path = _join_inside(folder, name)
        if path and os.path.splitext(path)[1].lower() in PREVIEW_EXT:
            return path
    # 图片型壁纸就拿自己当缩略图
    if kind == 'image' and media:
        return media
    return None


def _media_url(item_id: str, path: str) -> str:
    """媒体/缩略图地址带上文件 mtime 作为版本号。

    为什么必须带：id 是"路径"的哈希，所以玩家把同一个壁纸文件**原地替换**之后，
    地址一个字符都没变 —— 浏览器会拿 max-age=3600 里的旧副本，玩家会觉得
    "我明明换了壁纸，怎么还是老样子"。把 mtime 挂上去，文件一变地址就变。
    """
    return '/api/wallpaper/media/%s?v=%d' % (item_id, _mtime(path))


def _preview_url(item_id: str, path: str) -> str:
    return '/api/wallpaper/preview/%s?v=%d' % (item_id, _mtime(path))


def _mtime(path: str) -> int:
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0


def describe_folder(folder: str, wid: str = None):
    """把一个壁纸目录解析成一份描述（可直接下发给前端）。

    返回的 `supported=False` 一定带 `reason`：玩家需要知道"为什么这张不能用"，
    而不是看到一张点不动的卡片。
    """
    folder = _real(folder)
    if not os.path.isdir(folder):
        return None
    wid = wid or os.path.basename(folder)
    meta = _read_project(folder)
    wtype = str(meta.get('type') or '').strip().lower()
    title = str(meta.get('title') or '').strip() or wid

    media = _join_inside(folder, str(meta.get('file') or '').strip())
    if media and os.path.splitext(media)[1].lower() not in MEDIA_EXT:
        media = None
    if not media:
        declared_preview = str(meta.get('preview') or '').strip()
        media = _largest_media(folder, skip={declared_preview} if declared_preview else None)

    kind, reason = '', ''
    if media:
        ext = os.path.splitext(media)[1].lower()
        kind = probe_kind(media) or MEDIA_EXT.get(ext, '')
        if not kind:
            reason = '这个文件的内容不是图片或视频'
        elif kind == 'video' and ext not in PLAYABLE_VIDEO_EXT:
            reason = '浏览器播不了 %s 格式的视频，建议在 Wallpaper Engine 里换一张 mp4 / webm 壁纸' % ext
    elif wtype == 'scene' or os.path.isfile(os.path.join(folder, 'scene.pkg')):
        reason = '场景型壁纸（scene.pkg）要靠 Wallpaper Engine 实时渲染，网页里没法播放'
    elif wtype == 'web' or os.path.isfile(os.path.join(folder, 'index.html')):
        reason = '网页型壁纸是一整套本地网页，出于安全考虑没有内嵌'
    else:
        reason = '这个目录里没有可播放的图片或视频'

    supported = bool(media) and kind in ('video', 'image') and not reason
    if not supported and not reason:
        reason = '这张壁纸无法在网页里播放'

    item_id = make_id(folder)
    # 只有真的能播的才进注册表：不能播的条目留着也没有取文件的理由
    preview = None
    if supported:
        preview = _find_preview(folder, meta, media, kind)
        _registry[item_id] = {
            'media': _real(media),
            'preview': _real(preview) if preview else None,
            'kind': kind,
            'source': 'steam',
        }

    size = 0
    if media:
        try:
            size = os.path.getsize(media)
        except OSError:
            size = 0

    return {
        'id': item_id,
        'title': title,
        'type': wtype or (kind or 'unknown'),
        'kind': kind,
        'supported': supported,
        'reason': reason,
        'size': size,
        'folder': os.path.basename(folder),
        'source': 'steam',
        'media_url': _media_url(item_id, media) if supported else '',
        'preview_url': _preview_url(item_id, preview) if (supported and preview) else '',
    }


def describe_file(path: str):
    """把一个媒体文件解析成一份描述（粘贴路径 / 本机文件用）。"""
    path = _real(path)
    if not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext not in MEDIA_EXT:
        return None
    kind = probe_kind(path)
    if not kind:
        return None
    reason = ''
    if kind == 'video' and ext not in PLAYABLE_VIDEO_EXT:
        reason = '浏览器播不了 %s 格式的视频，建议用 mp4 / webm' % ext
    supported = not reason
    item_id = make_id(path)
    if supported:
        _registry[item_id] = {
            'media': path,
            'preview': path if kind == 'image' else None,
            'kind': kind,
            'source': 'local',
        }
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {
        'id': item_id,
        'title': os.path.basename(path),
        'type': kind,
        'kind': kind,
        'supported': supported,
        'reason': reason,
        'size': size,
        'folder': os.path.dirname(path),
        'source': 'local',
        'media_url': _media_url(item_id, path) if supported else '',
        'preview_url': _preview_url(item_id, path) if (supported and kind == 'image') else '',
    }


# ---------- 扫描与导入 ----------

def scan(force: bool = False):
    """扫描所有创意工坊目录，返回 `{'dirs': [...], 'items': [...]}`。"""
    now = time.time()
    cached = _scan_cache['data']
    if not force and cached is not None and now - _scan_cache['ts'] < _SCAN_TTL:
        return cached

    dirs = workshop_dirs()
    items = []
    seen = set()
    for base in dirs:
        # 目录自己就带 project.json → 说明玩家把 BATTLESHIP_WALLPAPER_DIR 直接
        # 指到了某一张壁纸目录上，那就把它本身也算一张（否则会返回空列表，
        # 让人以为"扫描坏了"）。
        if os.path.isfile(os.path.join(base, 'project.json')):
            own = describe_folder(base)
            if own:
                seen.add(own['id'])
                items.append(own)
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            folder = os.path.join(base, name)
            if not os.path.isdir(folder):
                continue
            item = describe_folder(folder, name)
            if not item or item['id'] in seen:
                continue
            seen.add(item['id'])
            items.append(item)
    # 能用的排前面，其余按标题
    items.sort(key=lambda it: (not it['supported'], it['title'].lower()))

    data = {'dirs': dirs, 'items': items}
    _scan_cache['ts'] = now
    _scan_cache['data'] = data
    return data


def import_path(raw_path: str):
    """按用户给的路径导入：可以是壁纸文件夹、装着一堆壁纸的父目录、或单个媒体文件。"""
    if not raw_path or not str(raw_path).strip():
        return {'ok': False, 'error': '请填写路径', 'items': []}
    raw = str(raw_path).strip().strip('"').strip("'")
    path = _real(os.path.expandvars(os.path.expanduser(raw)))

    if not os.path.exists(path):
        return {'ok': False, 'error': '路径不存在：%s' % raw, 'items': []}

    if os.path.isfile(path):
        item = describe_file(path)
        if not item:
            return {'ok': False, 'error': '这不是可播放的图片或视频文件（支持 mp4 / webm / gif / png / jpg / webp）', 'items': []}
        return {'ok': True, 'error': '', 'items': [item]}

    items = []
    # 先看这个目录自己是不是一张壁纸
    own = describe_folder(path)
    if own and own['supported']:
        items.append(own)

    # 再往下看一层：玩家常常直接粘贴 .../workshop/content/431960
    try:
        names = sorted(os.listdir(path))
    except OSError:
        names = []
    seen = {it['id'] for it in items}
    for name in names:
        sub = os.path.join(path, name)
        if not os.path.isdir(sub):
            continue
        item = describe_folder(sub, name)
        if item and item['id'] not in seen:
            seen.add(item['id'])
            items.append(item)

    if not items:
        return {'ok': False, 'error': '这个目录里没有找到可播放的壁纸（可能是场景型壁纸，或还没下载完）', 'items': []}
    items.sort(key=lambda it: (not it['supported'], it['title'].lower()))
    return {'ok': True, 'error': '', 'items': items}


def get_media(wid: str):
    """取注册表里的媒体条目；未注册一律 None（绝不按用户输入拼路径）。"""
    return _registry.get(wid)


def get_preview(wid: str):
    entry = _registry.get(wid)
    if not entry or not entry.get('preview'):
        return None
    return entry


def mime_for(path: str) -> str:
    return MIME.get(os.path.splitext(path)[1].lower(), 'application/octet-stream')


def clear_cache():
    """测试与"手动刷新"用。"""
    _scan_cache['ts'] = 0.0
    _scan_cache['data'] = None
    _registry.clear()
