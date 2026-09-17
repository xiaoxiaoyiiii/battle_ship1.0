# 允许上传的头像文件类型
import json
import os
import re
import secrets
import time

from flask import (Flask, session, jsonify, request, render_template, redirect,
                   url_for, flash, send_file)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import db
import achievements
import profile_spec
import quick_chat
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

# ---------------------------------------------------------------------------
# 个人信息名片（2026-09-17 第 1 批）
# ---------------------------------------------------------------------------
# 两个"人"要分清：
#   · 自己的名片（GET /api/profile, POST /api/profile/card）—— 完整个性字段 + 池子
#   · 别人看到的名片（GET /user_stats）—— 公开字段 + 隐私过滤
# 解锁判定只在服务端做（profile_spec 是唯一的一份规则），前端拿 catalog 只是为了
# 把未解锁项灰掉并写出解锁条件。

_CARD_SPEEDS = None


def _card_speeds():
    """卡名 → 速阶。卡表读失败就全给 0，不影响名片下发。"""
    global _CARD_SPEEDS
    if _CARD_SPEEDS is None:
        table = {}
        try:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'static', 'magic_card.json')
            with open(path, 'r', encoding='utf-8') as f:
                cards = json.load(f)
            for card in cards:
                if isinstance(card, dict) and card.get('name'):
                    table[card['name']] = int(card.get('speed') or 0)
        except Exception as e:      # noqa: BLE001 —— 名片不能因为卡表坏了就 500
            print(f'[profile] 读取卡表失败，速阶按 0 处理: {e}')
        _CARD_SPEEDS = table
    return _CARD_SPEEDS


def _profile_unlock_stats(uid, user=None):
    """解锁判定用的 stats：现有字段 + 个人累计出牌（新表汇总）。"""
    user = user if user is not None else (db.get_user(uid=uid) or {})
    stats = {k: user.get(k) for k in
             ('wins', 'losses', 'longest_streak', 'current_streak', 'created_at')}
    stats['card_uses_total'] = db.get_user_card_uses_total(uid)
    return stats


def _fav_cards(uid, limit=3):
    """最爱用的卡：卡名 + 速阶（取自卡表，查不到给 0）+ 使用次数。"""
    speeds = _card_speeds()
    result = []
    for row in db.get_user_card_usage(uid, limit):
        name = row.get('name') or ''
        result.append({'name': name, 'speed': speeds.get(name, 0),
                       'uses': int(row.get('uses') or 0)})
    return result


# ---------------------------------------------------------------------------
# 点赞 / 送花 / 留言板（2026-09-17 第 3 批 D 票）
# ---------------------------------------------------------------------------
# 冻结契约见 `docs/BATCH_2_3_4_PLAN.md` §3.3。四个接口：
#   POST /api/profile/like          点 / 取消 赞与送花
#   GET  /api/profile/messages      留言列表（游标分页）
#   POST /api/profile/message       发留言
#   POST /api/profile/message/delete 删留言（本人或主人）
#
# ⚠️ **所有校验都在服务端**（第 1 批的教训：只在前端灰掉等于没校验）。
# 前端拿到的 `can_delete` / `mine` 都是服务端算好的**结论**，不是"你自己判断"。

# `kind` 白名单。用元组而非集合，报错文案里的顺序才稳定。
_REACTION_KINDS = ('like', 'flower')
_MESSAGE_MAX_LEN = 100          # 单条留言字数上限（计划 §3.2）
_MESSAGE_DAILY_LIMIT = 20       # 每人对同一人每天 ≤ 20 条（计划 §3.3）
_MESSAGE_DEFAULT_LIMIT = 20     # 留言列表默认每页条数
_MESSAGE_MAX_LIMIT = 50         # 留言列表单页上限（防止一次拉全表）

# 需要清掉的控制字符：C0（含 \x00-\x1f）与 C1（\x7f-\x9f）。
# 换行 / 制表符**保留** —— 留言是多行文本框，把换行也吃掉会让排版塌掉。
# 用正则而不是 `str.strip`：控制字符可能夹在文本中间（`abc\x00def`），
# 只去首尾等于没去，前端渲染时可能把后面的内容吃掉。
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')


def _target_user(payload_or_args, key='username'):
    """按用户名找目标账号，返回 `(user_dict 或 None, 错误响应 或 None)`。

    「目标不存在 → 404，不要静默成功」（计划 §3.3）—— 静默成功最坑：
    玩家给一个不存在的名字点了赞，界面显示成功，其实什么都没写。
    """
    raw = ''
    try:
        raw = payload_or_args.get(key) or ''
    except AttributeError:
        raw = ''
    username = str(raw).strip()
    if not username:
        return None, (jsonify({'success': False, 'error': '缺少 username 参数'}), 400)
    user = db.get_user(username=username)
    if not user:
        return None, (jsonify({'success': False, 'error': f'账号不存在：{username}'}), 404)
    return user, None


def _reaction_view(target_uid, viewer_uid):
    """互动数据（计数 + 我的状态）。计数**始终可见**，与留言板开关无关。"""
    counts = db.get_profile_reaction_counts(target_uid) or {}
    mine = db.get_my_reactions(viewer_uid or '', target_uid) or {}
    return {
        'counts': {'like': int(counts.get('like') or 0),
                   'flower': int(counts.get('flower') or 0)},
        'mine': {'like': bool(mine.get('like')), 'flower': bool(mine.get('flower'))},
    }


def _public_message(msg, viewer_uid, owner_uid):
    """一条留言 → 下发形状（**白名单**）+ 服务端算好的 `can_delete`。

    ⚠️ `can_delete` 必须服务端算（计划 §3.3）：前端按它显示按钮，
    权限规则只此一份 —— 前端自己判就会出现"按钮在但点了 403"或更糟的
    "别人能删"。规则 = **留言本人 或 页面主人**。
    同时剥掉 db 层带过来的内部键（`_to_user_id` / `_deleted`）。
    """
    from_uid = msg.get('from_uid') or ''
    return {
        'id': int(msg.get('id') or 0),
        'from_name': msg.get('from_name') or '匿名',
        'content': msg.get('content') or '',
        'created_at': int(msg.get('created_at') or 0),
        'can_delete': bool(viewer_uid) and (viewer_uid == from_uid or viewer_uid == owner_uid),
    }


def _clean_message_content(raw) -> str:
    """留言内容归一化：去控制字符 + 去首尾空白（计划 §3.2）。

    长度**不在这里截断** —— 超长要明确 400（"不是静默丢弃"），
    截断会让玩家以为发成功了、内容却被砍掉半句。
    """
    text = '' if raw is None else str(raw)
    return _CONTROL_CHARS_RE.sub('', text).strip()


def _day_start_ts(now=None) -> int:
    """今天 00:00 的时间戳（本地时区，与玩家感知的"今天"一致）。

    「每人对同一人每天 ≤ 20 条」需要一个窗口起点。用本地零点而不是
    "最近 24 小时"：玩家在午夜前后各发 20 条时，用滚动窗口会被拒得莫名其妙。
    """
    now = time.time() if now is None else now
    lt = time.localtime(now)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))


def _get_json_payload():
    """请求体归一化：JSON 优先，退回复表单；两者都不是返回 None。"""
    payload = request.get_json(silent=True)
    if payload is None and request.form:
        payload = request.form.to_dict()
    return payload if isinstance(payload, dict) else None


# 点赞 / 送花（on=true 点、on=false 取消）
@app.route('/api/profile/like', methods=['POST'])
def profile_like():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401

    payload = _get_json_payload()
    if payload is None:
        return jsonify({'success': False, 'error': '请求体必须是 JSON 对象'}), 400

    target, err = _target_user(payload)
    if err:
        return err

    # 不能给自己点赞 / 送花（计划 §3.3）。这里必须由服务端拦：前端只是把按钮灰掉。
    if target['id'] == uid:
        return jsonify({'success': False, 'error': '不能给自己点赞或送花'}), 400

    kind = str(payload.get('kind') or '').strip()
    if kind not in _REACTION_KINDS:
        return jsonify({'success': False,
                        'error': f'kind 必须是 {"/".join(_REACTION_KINDS)} 之一'}), 400

    on = payload.get('on', True)
    # `on` 归一化为 bool：接受 true/false、1/0、"1"/"0"/"true"/"false"。
    # 其他值（含 None）一律当"取消"，避免把垃圾输入当成"点赞"。
    if isinstance(on, str):
        on = on.strip().lower() in ('1', 'true', 'yes', 'on')
    else:
        on = bool(on)

    if not db.set_profile_reaction(uid, target['id'], kind, on):
        return jsonify({'success': False, 'error': '操作失败，请稍后重试'}), 500

    # 响应**回读计数**而不是本地加减：并发下本地 +1 会算错，
    # 而且回读天然幂等（重复点同一下，计数不变）。
    view = _reaction_view(target['id'], uid)
    return jsonify({'success': True, 'counts': view['counts'], 'mine': view['mine']})


# 留言列表（游标分页）
@app.route('/api/profile/messages', methods=['GET'])
def profile_messages():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401

    target, err = _target_user(request.args)
    if err:
        return err

    try:
        limit = int(request.args.get('limit') or _MESSAGE_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = _MESSAGE_DEFAULT_LIMIT
    limit = max(1, min(limit, _MESSAGE_MAX_LIMIT))

    try:
        before_id = request.args.get('before_id')
        before_id = int(before_id) if before_id not in (None, '') else None
    except (TypeError, ValueError):
        before_id = None

    extra = db.get_user_profile_extra(target['id']) or {}
    show_guestbook = 1 if extra.get('show_guestbook') is None else int(extra.get('show_guestbook'))
    is_self = uid == target['id']

    # 隐私（计划 §3.4）：**别人视角**且主人关了留言板 → 空列表 + `guestbook_private=true`
    # （前端据此显示"该玩家未开放留言板"，而不是留白）。
    # 本人视角永远完整 —— 否则"我的留言板"就看不见自己的留言了。
    if not is_self and not show_guestbook:
        # ⚠️ 计数与"我的状态"照发：关的是**留言内容**的可见性，
        # 点赞/送花是"人气"不是"内容"，**始终可见**（§3.4 明文）。
        # 漏了这一段，前端在私密主页上会拿到 undefined 的 counts →
        # 点赞数显示成空/0，玩家以为自己收到的人气没了。
        view = _reaction_view(target['id'], uid)
        return jsonify({'success': True, 'messages': [], 'has_more': False,
                        'total': 0, 'guestbook_private': True,
                        'username': target.get('username') or '',
                        'counts': view['counts'], 'mine': view['mine']})

    page = db.list_profile_messages(target['id'], limit, before_id)
    messages = [_public_message(m, uid, target['id'])
                for m in (page.get('messages') or [])]
    view = _reaction_view(target['id'], uid)
    return jsonify({'success': True,
                    'messages': messages,
                    'has_more': bool(page.get('has_more')),
                    'total': int(page.get('total') or 0),
                    'guestbook_private': False,
                    'username': target.get('username') or '',
                    'counts': view['counts'],
                    'mine': view['mine']})


# 发留言
@app.route('/api/profile/message', methods=['POST'])
def post_profile_message():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401

    # 频率限制：复用现有的按 IP 限流（同一套窗口/上限）。
    # ⚠️ 只加在**写**接口上。GET /api/profile/messages 不限流 —— 列表是翻页读，
    # 限流会让"点两下加载更多"就吃到 429。
    if _rate_limited('profile_message'):
        return jsonify({'success': False, 'error': '留言太频繁了，请稍后再试'}), 429

    payload = _get_json_payload()
    if payload is None:
        return jsonify({'success': False, 'error': '请求体必须是 JSON 对象'}), 400

    target, err = _target_user(payload)
    if err:
        return err

    # 不能给自己留言（计划 §3.3）—— 留言板是"别人留给你"的，自嗨没有意义。
    if target['id'] == uid:
        return jsonify({'success': False, 'error': '不能给自己留言'}), 400

    content = _clean_message_content(payload.get('content'))
    if not content:
        return jsonify({'success': False, 'error': '留言内容不能为空'}), 400
    if len(content) > _MESSAGE_MAX_LEN:
        return jsonify({'success': False,
                        'error': f'留言不能超过 {_MESSAGE_MAX_LEN} 字（当前 {len(content)} 字）'}), 400

    # 每人对同一人每天上限。先于写库检查（顺序也重要：这一步比写便宜）。
    used = db.count_profile_messages_since(uid, target['id'], _day_start_ts())
    if used >= _MESSAGE_DAILY_LIMIT:
        return jsonify({'success': False,
                        'error': f'今天给同一个人最多留言 {_MESSAGE_DAILY_LIMIT} 条，'
                                 f'明天再来吧'}), 429

    me = db.get_user(uid=uid) or {}
    from_name = me.get('username') or session.get('username') or '匿名'
    msg_id = db.add_profile_message(target['id'], uid, from_name, content)
    if not msg_id:
        return jsonify({'success': False, 'error': '留言失败，请稍后重试'}), 500

    created = db.get_profile_message(msg_id)
    if not created:
        # 极端情况：写成功却读不到。回一个由入参拼出的等价形状，
        # 而不是让玩家看到"发送失败"（其实已经发出去了）。
        created = {'id': msg_id, 'from_uid': uid, 'from_name': from_name,
                   'content': content, 'created_at': int(time.time())}
    return jsonify({'success': True,
                    'message': _public_message(created, uid, target['id'])})


# 删留言（留言本人 或 页面主人，其余 403；软删保留审计）
@app.route('/api/profile/message/delete', methods=['POST'])
def delete_profile_message():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401

    payload = _get_json_payload()
    if payload is None:
        return jsonify({'success': False, 'error': '请求体必须是 JSON 对象'}), 400

    try:
        msg_id = int(payload.get('id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': '缺少有效的留言 id'}), 400

    msg = db.get_profile_message(msg_id)
    if not msg:
        return jsonify({'success': False, 'error': '留言不存在'}), 404

    # 权限 = 留言本人 或 页面主人（计划 §3.3）。两者都不是 → 403（不是 404：
    # 留言确实存在，别人删不掉这件事要说清楚）。
    owner_uid = msg.get('_to_user_id') or ''
    if uid != (msg.get('from_uid') or '') and uid != owner_uid:
        return jsonify({'success': False, 'error': '你没有权限删除这条留言'}), 403

    if not db.soft_delete_profile_message(msg_id):
        return jsonify({'success': False, 'error': '删除失败，请稍后重试'}), 500
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# 成就 / 徽章（2026-09-17 第 2 批）
# ---------------------------------------------------------------------------
# 判定规则只有一份：`achievements.evaluate()`。接口层这里只负责**凑数据**与
# **决定下发哪些**，绝不自己写 `sunk_total >= 50` 这种比较（第 1 批的教训：
# 同一个业务判断有两份实现就一定会漂移）。


def _safe_read(call, default, label):
    """读统计时兜一层：读不到就给默认值 + 打印日志。

    徽章是**展示层**，一次读库失败不该把整张名片变成 500（与 `_card_speeds` 同一套处理）。
    但也不静默 —— 日志里能看出是哪一项没读到，便于排查「怎么少了一枚徽章」。
    """
    try:
        return call()
    except Exception as e:      # noqa: BLE001 —— 统计失败不影响名片/战绩下发
        print(f'[achievements] 读取 {label} 失败，按默认值处理: {e}')
        return default


def _user_counters(uid):
    """每局累计事实（累计击沉 / 场次 / 零伤获胜 / 最快用时）。读不到给全 0。"""
    rows = _safe_read(lambda: db.get_user_counters(uid), {}, 'user_counters')
    return rows if isinstance(rows, dict) else {}


def _achievement_stats(uid, user=None, rank=None, base=None):
    """徽章判定用的 stats（`achievements.CONTEXT_KEYS` 的超集）。

    ⚠️ 组装**只有一份实现**：`db.get_achievement_stats()`（结算路径 `server._finalize_match`
    调的是同一个）。这里只做「把已经拿到的 user / rank 传下去、省一次查库」。
    两处各拼一份的话，谁漏一个键，对应判据就会静默恒假（缺字段按 0 算，不报错）。
    """
    return db.get_achievement_stats(uid, base=base, user=user, rank=rank)


def _badge_rows(uid):
    """已解锁记录 {badge_id: unlocked_at}（表里只有「首次解锁时间」这个事实）。"""
    rows = _safe_read(lambda: db.get_user_achievements(uid), {}, 'user_achievements')
    return rows if isinstance(rows, dict) else {}


def build_badge_view(uid, user=None, rank=None, unlocked_only_flag=False):
    """算一份徽章视图：`(items, badge_count)`。

    `unlocked_only_flag=True` 时只返回已解锁的（别人视角 —— 未解锁的连 id 与判据文案
    都不下发，避免暴露别人的进度）。过滤规则只写在这一处。
    """
    stats = _achievement_stats(uid, user=user, rank=rank)
    items = achievements.catalog(stats, _badge_rows(uid))
    count = achievements.count_unlocked(items)
    if unlocked_only_flag:
        items = achievements.unlocked_only(items)
    return items, count


# 自己的名片里保留的 users 字段（白名单 —— 绝不整行下发）
_PROFILE_USER_FIELDS = ('id', 'username', 'signature', 'avatar', 'wins', 'losses',
                        'current_streak', 'longest_streak', 'created_at')


def build_own_profile(uid):
    """自己的完整名片（GET 与 POST 的响应同形状）。查不到用户返回 None。"""
    user = db.get_user(uid=uid)
    if not user:
        return None
    profile = {k: user.get(k) for k in _PROFILE_USER_FIELDS}
    rank = db.get_user_rank(uid)
    stats = _profile_unlock_stats(uid, user)
    extra = db.get_user_profile_extra(uid)
    profile.update({
        'rank': rank,
        'title_id': extra.get('title_id') or '',
        'tags': extra.get('tags') or [],
        'status_text': extra.get('status_text') or '',
        'frame_id': extra.get('frame_id') or profile_spec.DEFAULT_FRAME_ID,
        'card_bg_id': extra.get('card_bg_id') or profile_spec.DEFAULT_CARD_BG_ID,
        'show_stats': int(extra.get('show_stats') or 0),
        'show_fav_cards': int(extra.get('show_fav_cards') or 0),
        'show_history': int(extra.get('show_history') or 0),
        # 留言板开关（第 3 批）：第 4 个展示开关，与另外三个同进同出 ——
        # 编辑面拿它初始化 `#profile-show-guestbook` 复选框。
        'show_guestbook': int(extra.get('show_guestbook') if extra.get('show_guestbook') is not None else 1),
        'fav_cards': _fav_cards(uid),
        'catalog': profile_spec.catalog(stats),
    })
    # 互动数据：自己的名片也要有（查看面两个视角共用一套渲染），
    # 自己看自己时 `mine` 恒为 false —— 不能给自己点赞/送花。
    view = _reaction_view(uid, uid)
    profile['counts'] = view['counts']
    profile['mine'] = view['mine']
    # 徽章：自己视角拿**全量**（含未解锁项与判据文案），前端好画灰格与"还差什么"。
    badges, badge_count = build_badge_view(uid, user=user, rank=rank)
    profile['achievements'] = badges
    profile['badge_count'] = badge_count
    return profile


# 获取用户个性化信息
@app.route('/api/profile', methods=['GET'])
def get_profile():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': '未登录'}), 401
    profile = build_own_profile(uid)
    return jsonify({'profile': profile})


# 保存个人名片（称号 / 标签 / 状态 / 边框 / 底色 / 三个展示开关）
@app.route('/api/profile/card', methods=['POST'])
def save_profile_card():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401

    user = db.get_user(uid=uid)
    if not user:
        return jsonify({'success': False, 'error': '账号不存在'}), 401

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict() if request.form else None
    if not isinstance(payload, dict):
        return jsonify({'success': False, 'error': '请求体必须是 JSON 对象'}), 400

    fields, errors = profile_spec.validate_payload(payload, _profile_unlock_stats(uid, user))
    if errors:
        # 拒绝整次保存（不做部分写入）：未解锁的称号不能因为"别的字段合法"而漏进去
        return jsonify({'success': False, 'error': '；'.join(errors)}), 400

    if not db.save_user_profile_extra(uid, fields):
        return jsonify({'success': False, 'error': '保存失败，请稍后重试'}), 500
    return jsonify({'success': True, 'profile': build_own_profile(uid)})


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
    # 新增名片字段时**继续走这份白名单**，不要图省事整行下发 —— 一旦整行下发，
    # 以后往 users 表加的任何敏感列都会自动泄露。
    public_fields = ('id', 'username', 'wins', 'losses', 'current_streak',
                     'longest_streak', 'created_at', 'signature', 'avatar')
    public_stats = {k: stats[k] for k in public_fields if k in stats}
    # 排行榜名次：个人信息面板要显示"第 N 名"（榜外账号也算得出名次）。
    # 算不出来（库异常）时给 None，前端显示占位符，不影响其余字段。
    public_stats['rank'] = db.get_user_rank(stats['id'])

    # 名片个性字段（称号 / 标签 / 状态 / 边框 / 底色 / 最爱用的卡）
    extra = db.get_user_profile_extra(stats['id'])
    title_id = extra.get('title_id') or ''
    public_stats['title_id'] = title_id
    public_stats['title_name'] = profile_spec.title_name(title_id)
    public_stats['tags'] = extra.get('tags') or []
    public_stats['status_text'] = extra.get('status_text') or ''
    public_stats['frame_id'] = extra.get('frame_id') or profile_spec.DEFAULT_FRAME_ID
    public_stats['card_bg_id'] = extra.get('card_bg_id') or profile_spec.DEFAULT_CARD_BG_ID
    public_stats['fav_cards'] = _fav_cards(stats['id'], 3)
    # 三个展示开关**一起下发**（计划 §2.5，2026-09-17 裁决补上后两个）。
    # 语义统一：0 = 该区块对所有人隐藏（包括自己），1 = 可见，由前端按标志位决定画不画。
    # ⚠️ 只下发 show_history 会让"看别人"这条路径读到 undefined → 前端按默认值当成"显示"
    # → 玩家关掉的开关在别人眼里完全无效（假控件）。三个必须同进同出。
    public_stats['show_stats'] = int(extra.get('show_stats') or 0)
    public_stats['show_fav_cards'] = int(extra.get('show_fav_cards') or 0)
    public_stats['show_history'] = int(extra.get('show_history') or 0)
    # 留言板开关（第 3 批）：**别人视角也要下发** —— 前端靠它决定
    # 「显示留言」还是「该玩家未开放留言板」。老行由 DEFAULT 1 兜底，缺值按公开。
    public_stats['show_guestbook'] = int(
        extra.get('show_guestbook') if extra.get('show_guestbook') is not None else 1)

    # 点赞 / 送花 / 留言板（第 3 批）：查看面两个视角共用一份互动数据。
    # ⚠️ 计数与"我的状态"**始终可见**，不受 `show_guestbook` 影响 ——
    # 那是"人气"不是"内容"（计划 §3.4）。留言列表本身由
    # `GET /api/profile/messages` 下发（它另做隐私过滤），这里不重复带。
    view = _reaction_view(stats['id'], session.get('user_id'))
    public_stats['counts'] = view['counts']
    public_stats['mine'] = view['mine']

    # 徽章：**他人视角只下发已解锁的**（计划 §2.4）。
    # 未解锁项的 id 与判据文案都不发 —— 否则别人能看出"他还差几场拿十连胜"，
    # 那是把别人的进度泄露出去。总数照给，前端才能显示「3 / 12」。
    badge_items, badge_count = build_badge_view(
        stats['id'], user=stats, rank=public_stats['rank'], unlocked_only_flag=True)
    public_stats['achievements'] = badge_items
    public_stats['badge_count'] = badge_count

    # 隐私：对局历史默认不公开（show_history=0）。**本人永远完整** —— 否则
    # 「我的对局记录」这个功能就作废了。未登录访问他人主页 = 他人视角。
    # （只有 history 由服务端过滤数据；战绩亮点 / 最爱用的卡是"标志位 + 数据都发"，
    #   因为那两个区块的数据本身不算隐私，隐藏与否交给前端按同一个标志位判断。）
    viewer = session.get('user_id')
    is_self = bool(viewer) and viewer == stats['id']
    if is_self or public_stats['show_history']:
        history = db.get_match_history(stats['id'], limit)
    else:
        history = []
    return jsonify({'stats': public_stats, 'history': history})


# 徽章图鉴（自己视角：全部 12 枚 + 是否解锁 + 判据文案 + 首次解锁时间）
@app.route('/api/achievements', methods=['GET'])
def achievements_view():
    uid = session.get('user_id')
    if not uid:
        return jsonify({'error': '未登录'}), 401
    user = db.get_user(uid=uid)
    if not user:
        return jsonify({'error': '账号不存在'}), 401
    # 判据在 achievements.evaluate() 里只有一份；这里只是把它算出来下发。
    items, count = build_badge_view(uid, user=user)
    return jsonify({'achievements': items, 'badge_count': count})


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


@app.route('/api/quick_chat', methods=['GET'])
def api_quick_chat():
    """局内快捷语表（公开只读，**不要求登录**）。

    游客也能对局，而这里全是静态文案、没有任何用户数据 —— 与
    `/api/leaderboard` 同类，加 401 只会让游客的对局面板空着。
    文案的唯一来源是 `quick_chat.py`（socket 事件 `quick_chat` 用的是同一份），
    前端只负责渲染，不许在 `game.js` 里再抄一份文案。
    """
    return jsonify({
        'success': True,
        'groups': list(quick_chat.GROUPS),
        'items': quick_chat.catalog(),
    })


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




