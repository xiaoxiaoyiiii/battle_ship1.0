# 允许上传的头像文件类型
import os
import secrets
import time

from flask import (Flask, session, jsonify, request, render_template, redirect,
                   url_for, flash, send_file)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import db
import wallpaper

ALLOWED_AVATAR_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
# 头像魔数校验：只信任真实图片内容，而不是客户端声明的扩展名
AVATAR_MAGIC_PREFIXES = (
    b'\x89PNG\r\n\x1a\n',   # PNG
    b'\xff\xd8\xff',        # JPEG
    b'GIF87a',              # GIF87a
    b'GIF89a',              # GIF89a
)
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB
AVATAR_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'avatars')
os.makedirs(AVATAR_UPLOAD_FOLDER, exist_ok=True)
app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'),
            template_folder=os.path.join(os.path.dirname(__file__), 'templates'))


@app.context_processor
def _inject_asset_version():
    """给模板提供 asset_v()：静态资源加 mtime 版本号。

    为什么需要：index.html 里写死了 `/static/game.js`（没有版本号），
    浏览器在【页面不刷新】时根本不会重新拉这个文件 —— 服务端换了代码，
    玩家那边仍在跑旧 JS，表现就是"功能明明上线了却看不到"。
    实测踩过：优先权询问上线后玩家反馈"时点没有出现"，
    而本地/线上分层测试全绿，就是因为对方页面挂着旧的 game.js。

    带上 `?v=<mtime>` 之后，文件一变 URL 就变，浏览器必然重新下载。
    """
    static_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

    def asset_v(rel_path: str) -> str:
        try:
            return str(int(os.path.getmtime(os.path.join(static_root, rel_path))))
        except OSError:
            return '0'

    return {'asset_v': asset_v}

# SECRET_KEY 从环境变量注入；未配置时使用一次性随机值（重启后 session 失效，
# 属可接受的降级，避免源码中硬编码的密钥被用于伪造登录态）。
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
# 上传体积上限，防止超大文件耗尽磁盘
app.config['MAX_CONTENT_LENGTH'] = MAX_AVATAR_SIZE
# Cookie 安全属性：禁止 JS 读取 + 限制跨站携带
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# 简易限流：同一 IP 在窗口期内对登录/注册/改密的尝试次数上限
_LOGIN_WINDOW = 60          # 窗口（秒）
_LOGIN_MAX_ATTEMPTS = 10    # 窗口内最大尝试次数
_login_attempts: dict = {}


def _rate_limited(scope: str) -> bool:
    """返回 True 表示当前请求应被拒绝（超过尝试上限）。"""
    ip = request.remote_addr or 'unknown'
    now = time.time()
    key = f"{scope}:{ip}"
    # 顺带清理过期 key，避免内存无限增长
    if len(_login_attempts) > 5000:
        for k in [k for k, v in _login_attempts.items() if not v or now - v[-1] > _LOGIN_WINDOW]:
            _login_attempts.pop(k, None)
    recent = [t for t in _login_attempts.get(key, []) if now - t < _LOGIN_WINDOW]
    recent.append(now)
    _login_attempts[key] = recent
    return len(recent) > _LOGIN_MAX_ATTEMPTS

# 获取用户个性化信息
@app.route('/api/profile', methods=['GET'])
def get_profile():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': '未登录'}), 401
    profile = db.get_user_profile(uid)
    return jsonify({'profile': profile})


# 修改签名
@app.route('/api/profile/signature', methods=['POST'])
def update_signature():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': '未登录'}), 401
    signature = request.form.get('signature', '')
    ok = db.update_user_signature(uid, signature)
    return jsonify({'success': ok})


# 上传头像
@app.route('/api/profile/avatar', methods=['POST'])
def upload_avatar():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': '未登录'}), 401
    if 'avatar' not in request.files:
        return jsonify({'error': '未选择文件'}), 400
    file = request.files['avatar']
    if file.filename == '' or '.' not in file.filename:
        return jsonify({'error': '文件类型不支持'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        return jsonify({'error': '文件类型不支持'}), 400
    # 校验真实文件头（防止改扩展名上传任意内容）
    head = file.stream.read(8)
    file.stream.seek(0)
    if not any(head.startswith(prefix) for prefix in AVATAR_MAGIC_PREFIXES):
        return jsonify({'error': '文件内容不是有效的图片'}), 400
    # 校验体积（MAX_CONTENT_LENGTH 已在框架层拦截超大请求，这里再兜底一次）
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > MAX_AVATAR_SIZE:
        return jsonify({'error': '图片不能超过 2MB'}), 400
    filename = secure_filename(f"{uid}_avatar.{ext}")
    save_path = os.path.join(AVATAR_UPLOAD_FOLDER, filename)
    file.save(save_path)
    avatar_url = f"/static/avatars/{filename}"
    ok = db.update_user_avatar(uid, avatar_url)
    return jsonify({'success': ok, 'avatar': avatar_url})


# 更改密码
@app.route('/api/change_password', methods=['POST'])
def change_password():
    """更改当前用户密码"""
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'msg': '未登录'}), 401
    if _rate_limited('change_password'):
        return jsonify({'success': False, 'msg': '操作过于频繁，请稍后再试'}), 429
    old_password = request.form.get('old_password', '')
    new_password = request.form.get('new_password', '')
    if not old_password or not new_password:
        return jsonify({'success': False, 'msg': '请填写原密码和新密码'}), 400
    user = db.get_user(uid=uid)
    if not user or not check_password_hash(user['password_hash'], old_password):
        return jsonify({'success': False, 'msg': '原密码错误'}), 403
    if len(new_password) < 6:
        return jsonify({'success': False, 'msg': '新密码长度至少6位'}), 400
    new_hash = generate_password_hash(new_password)
    ok = db.update_user_password(uid, new_hash)
    return jsonify({'success': ok, 'msg': '密码修改成功' if ok else '修改失败'})


@app.route('/user_stats', methods=['GET'])
def user_stats_view():
    """查询个人战绩，支持通过 username 查询或当前登录用户。"""
    username = request.args.get('username')
    try:
        limit = int(request.args.get('limit', 20) or 20)
    except (TypeError, ValueError):
        limit = 20
    if username:
        stats = db.get_user(username=username)
    else:
        uid = session.get('user_id')
        if not uid:
            return jsonify({'error': '未登录'}), 401
        stats = db.get_user(uid=uid)
    if not stats:
        # 用户不存在（如游客查询对手）时返回空战绩，避免前端轮询404
        return jsonify({'stats': None, 'history': []})
    # 安全：只下发展示所需字段。db.get_user 是 SELECT *，直接返回会泄露
    # password_hash（可离线爆破）与 token（账号接管），且本接口无需登录即可调用。
    public_fields = ('id', 'username', 'wins', 'losses', 'current_streak',
                     'longest_streak', 'created_at', 'signature', 'avatar')
    public_stats = {k: stats[k] for k in public_fields if k in stats}
    history = db.get_match_history(stats['id'], limit)
    return jsonify({'stats': public_stats, 'history': history})
@app.route('/')
def index():
    # 渲染主页面并传递登录信息
    return render_template('index.html', username=session.get('username'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if _rate_limited('register'):
            flash('操作过于频繁，请稍后再试')
            return redirect(url_for('register'))
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))
        # 与 db.create_user 的存储层校验保持一致，提前给出精确原因
        if len(username) < 3:
            flash('用户名长度至少 3 位')
            return redirect(url_for('register'))
        if not all(c.isalnum() or c in '._-' for c in username):
            flash('用户名只能包含字母、数字、点、下划线和短横线')
            return redirect(url_for('register'))
        if len(password) < 6:
            flash('密码长度至少 6 位')
            return redirect(url_for('register'))
        if db.get_user(username=username):
            flash('用户名已存在')
            return redirect(url_for('register'))
        pw_hash = generate_password_hash(password)
        uid = db.create_user(username, pw_hash)
        if uid:
            session['user_id'] = uid
            session['username'] = username
            flash('注册成功')
            return redirect(url_for('index'))
        else:
            flash('注册失败')
            return redirect(url_for('register'))
    # SPA: 返回主页面，前端负责显示注册表单/提示
    return render_template('index.html', username=session.get('username'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if _rate_limited('login'):
            flash('操作过于频繁，请稍后再试')
            return redirect(url_for('login'))
        username = request.form.get('username')
        password = request.form.get('password')
        user = db.get_user(username=username)
        if not user or not check_password_hash(user['password_hash'], password):
            flash('用户名或密码错误')
            return redirect(url_for('login'))
        session['user_id'] = user['id']
        session['username'] = user['username']
        flash('登录成功')
        return redirect(url_for('index'))
    # SPA: 返回主页面，前端负责显示登录表单/提示
    return render_template('index.html', username=session.get('username'))


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('已退出登录')
    return redirect(url_for('index'))


@app.route('/leaderboard')
def leaderboard():
    # SPA entry point for leaderboard view
    return render_template('index.html', username=session.get('username'))


@app.route('/api/leaderboard')
def api_leaderboard():
    # 支持分页：此前硬编码 100，?limit= 被完全忽略
    # （实测 /api/leaderboard?limit=2 仍返回全部行）。
    try:
        limit = int(request.args.get('limit', 100))
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 100))
    rows = db.get_leaderboard(limit)
    return jsonify(rows)


@app.route('/api/card_usage')
def api_card_usage():
    """卡牌使用次数（公开只读）。图鉴用它显示"这张卡有多常用"。"""
    usage = db.get_card_usage()
    return jsonify({'usage': usage, 'total': sum(int(v or 0) for v in usage.values())})


# ---------------------------------------------------------------------------
# 动态壁纸（Wallpaper Engine）
# ---------------------------------------------------------------------------
# 三条通道的可见范围是刻意分开的：
#   · 扫描本机壁纸库 / 按路径导入 —— 会暴露"这台机器上有什么"，且路径由用户
#     直接指定，因此**只允许回环地址**（本机访问），另加一道自定义请求头校验：
#     自定义头会让跨站请求触发 CORS 预检，而本站没有任何 CORS 放行头，
#     于是别的网页无法借用户的浏览器读本机文件。
#   · 取媒体文件 —— id 是路径的 sha1 前 14 位，不可枚举；注册只可能发生在回环
#     请求里。不额外限制，局域网/手机访问同一台服务器时壁纸才会正常显示。
# 需要把扫描能力开放到非本机（例如自建服务器），设 BATTLESHIP_WALLPAPER_ALLOW_REMOTE=1。
WALLPAPER_HEADER = 'X-Battleship-Wallpaper'


def _wallpaper_remote_blocked() -> bool:
    """True = 本次请求不是本机发起的，扫描类接口应当拒绝。"""
    if os.environ.get('BATTLESHIP_WALLPAPER_ALLOW_REMOTE') == '1':
        return False
    addr = (request.remote_addr or '').strip().lower()
    if not addr:
        return False
    return not (addr in ('localhost', '::1') or addr.startswith('127.') or addr.startswith('::ffff:127.'))


@app.route('/api/wallpapers')
def api_wallpapers():
    """列出本机 Wallpaper Engine 创意工坊里可播放的壁纸。"""
    if _wallpaper_remote_blocked():
        # 这里故意返回 200 + available=false：前端照常渲染，直接显示一段说明，
        # 不必为一个"本来就该被拒绝"的场景写异常分支。
        return jsonify({
            'available': False, 'success': False, 'items': [], 'dirs': 0,
            'reason': '扫描本机壁纸库只在本机（localhost）访问时可用；在别的设备上请用下面的「直链」导入。',
        })
    data = wallpaper.scan(force=request.args.get('refresh') in ('1', 'true', 'yes'))
    dirs = data['dirs']
    reason = '' if dirs else ('没有找到 Wallpaper Engine 的创意工坊目录'
                              '（Steam 里没装过壁纸，或壁纸装在别的库）——可以往下填「壁纸文件夹」路径。')
    return jsonify({
        'available': True,
        'success': True,
        'dirs': len(dirs),
        'reason': reason,
        'items': data['items'],
    })


@app.route('/api/wallpaper/scan_path', methods=['POST'])
def api_wallpaper_scan_path():
    """按本机路径导入壁纸：壁纸文件夹 / 装着壁纸的父目录 / 单个媒体文件。"""
    if _wallpaper_remote_blocked():
        return jsonify({'success': False, 'items': [], 'error': '按路径导入只在本机（localhost）访问时可用。'}), 403
    if request.headers.get(WALLPAPER_HEADER) != '1':
        return jsonify({'success': False, 'items': [], 'error': '缺少本机校验头。'}), 403
    payload = request.get_json(silent=True) or {}
    result = wallpaper.import_path(payload.get('path') or '')
    if not result['ok']:
        return jsonify({'success': False, 'error': result['error'], 'items': []}), 400
    return jsonify({'success': True, 'error': '', 'items': result['items']})


@app.route('/api/wallpaper/media/<wid>')
def api_wallpaper_media(wid):
    """下发壁纸本体。conditional=True 让浏览器可以按 Range 拖动进度。"""
    entry = wallpaper.get_media(wid)
    if not entry:
        return jsonify({'error': '壁纸不存在或未注册（%s）' % wid}), 404
    path = entry['media']
    if not os.path.isfile(path):
        return jsonify({'error': '壁纸文件已不在原位置'}), 404
    return send_file(path, mimetype=wallpaper.mime_for(path),
                     conditional=True, max_age=3600)


@app.route('/api/wallpaper/preview/<wid>')
def api_wallpaper_preview(wid):
    """下发壁纸缩略图（创意工坊目录里的 preview.*）。"""
    entry = wallpaper.get_preview(wid)
    if not entry:
        return jsonify({'error': '没有这张壁纸的缩略图'}), 404
    path = entry['preview']
    if not os.path.isfile(path):
        return jsonify({'error': '缩略图已不在原位置'}), 404
    return send_file(path, mimetype=wallpaper.mime_for(path),
                     conditional=True, max_age=3600)


@app.route('/api/login', methods=['POST'])
def api_login():
    if _rate_limited('api_login'):
        return jsonify({'error': '操作过于频繁，请稍后再试'}), 429
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({'error': '用户名或密码不能为空'}), 400
    user = db.get_user(username=username)
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': '用户名或密码错误'}), 401
    token = db.get_token_by_password(username, password)
    if not token:
        return jsonify({'error': '登录失败'}), 500
    return jsonify({'token': token})




