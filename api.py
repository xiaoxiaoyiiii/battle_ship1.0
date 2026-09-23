# 允许上传的头像文件类型
import json
import os
import re
import secrets
import time

from flask import (Flask, session, jsonify, request, render_template, redirect,
                   url_for, flash, send_file, current_app)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import db
import achievements
import anticheat
import dm
import leveling
import profile_spec
import changelog
import quick_chat
import ranks
import suspicion
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

# 好友上限与申请频率（社交批）。**定义在这里而不是写死在函数里**：
# `GET /api/friends` 要把它们放进 `limits` 下发给前端，前端拿它显示"还可以再加 N 位"
# 并提前把按钮灰掉；写死在函数体里就会出现"前端文案里的 50 和服务端判的 50
# 是两次手抄"，改一处必然漂移（本项目在段位曲线上栽过同形状的坑）。
MAX_FRIENDS = 50                  # 好友数上限（accepted 计数）
FRIEND_REQUESTS_PER_HOUR = 10     # 每小时可发出的好友申请数（只数 pending）
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
    # 段位（user_rank）—— 段位解锁的称号/头像框/名片底色全靠它判。
    # ⚠️ **这一行曾经漏了**：`profile_spec.unlock_context` 对缺失的 `rank_tier`
    #    一律按 0（二级水手）算，于是所有"段位达到 X"的外观**永远解不开**，
    #    而接口、前端、测试全都不报错 —— 表现是"段位到了但奖励看不到"。
    #    改这一段时注意：本函数同时供给 `catalog`（解锁标志）与 `validate_payload`
    #    （保存校验），所以只在这里注入一次，别在别处再算一份。
    try:
        row = db.get_user_rank_row(uid) or {}
        stats['rank_tier'] = ranks.points_tier_index(row.get('points') or 0)
    except Exception:                                             # noqa: BLE001
        stats['rank_tier'] = 0
    # 特权（`user_perks` 表）：持有"外观全解锁"就注入标记，`profile_spec` 认它即全解锁。
    # ⚠️ 必须放在**这一个**函数里 —— 它同时被"自己的名片（catalog 的 unlocked 标志）"
    # 和"保存校验（validate_payload）"用到；分散注入必然漂移（第 2 批的教训）。
    try:
        if db.has_user_perk(uid, profile_spec.PERK_UNLOCK_ALL):
            stats[profile_spec.UNLOCK_ALL_FLAG] = True
    except Exception:
        pass
    return stats


def _name_style(uid):
    """名字样式。空字符串 = 普通；`rainbow` = 彩虹渐变（特权）。

    这是**下发给别人**的字段：别人看你的名片/排行榜时也要能看到彩虹名字，
    所以它必须进公开 payload，而不是只发给自己。
    """
    try:
        if uid and db.has_user_perk(uid, profile_spec.PERK_RAINBOW_NAME):
            return 'rainbow'
    except Exception:
        pass
    return ''


def _level_cap(uid):
    """等级上限：持 `level_101` 特权的账号 101，其余 100。"""
    try:
        if uid and db.has_user_perk(uid, profile_spec.PERK_LEVEL_101):
            return leveling.LEVEL_101
    except Exception:
        pass
    return leveling.MAX_LEVEL


def level_view_for(uid, xp=None):
    """某人的等级视图（经验 + 等级 + 本级进度）。

    **一处组装**：`/api/profile`、`/user_stats`、`/api/leaderboard` 都调它，
    避免"三处各算一遍等级"（第 2 批的教训：同一件事两份实现必然漂移）。
    """
    if xp is None:
        xp = db.get_user_xp(uid)
    return leveling.level_view(xp, _level_cap(uid))


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


# ---------------------------------------------------------------------------
# 段位（2026-09-17/18 段位批）
# ---------------------------------------------------------------------------
# 规则全在 `ranks.py`（纯模块、一份实现），`db` 层只管存 points —— 接口这里**只组装**：
# 读行 → 补两个名次 → 交给 `ranks.rank_view()`。绝不在这里重算段位 / 小级 / 文案
# （"同一个业务判断有两份实现就一定会漂移"，CLAUDE.md §11 通用教训二）。
#
# ⚠️ **只读，绝不写库**：`is_admiral` 的落库由结算侧（server 的结算路径）负责；
#    接口层写一次，"动态晋升"就变成"看谁访问得多"了。
# ⚠️ 两个"排名"别混（docs/RANKED_2026_09_17.md §1）：
#    · `server_rank`       —— 全服名次，只用于**展示**（船长/大舰长文案里的 `#N`）；
#    · `captain_pool_rank` —— 船长池内名次，只用于**大舰长晋升判定**。
#    另外 `db.get_rank_position`（段位名次）与 `db.get_user_rank`（战绩榜名次，按 wins）
#    是两回事，名字刻意错开，别拿错。


def _users_brief_map(uids):
    """批量取 `{uid: {'username', 'avatar'}}` —— 榜页 100 行不能逐行查库。

    `db` 层没有现成的批量 users 读（`get_leaderboard` 是另一张榜的整表扫，
    `get_user` 是单行），所以这里直接读一条**参数化**的 `IN (...)`：
    只 SELECT `id, username, avatar` 三列，**绝不整行读**（`users` 里有
    `password_hash` / `token`，凭证一旦进了响应就是安全事故）。

    读失败返回空 map → 榜上用户名/头像落成空串、页面照常出（降级而不是 500，
    与 `_card_speeds` / `_safe_read` 同一套口径）。
    """
    ids = [str(u) for u in (uids or []) if u]
    if not ids:
        return {}
    try:
        # `db.db` 是 db 模块里的单例（`Database()`），与各 DAO 共用同一条 sqlite
        # 连接（`row_factory = sqlite3.Row`，所以这里能按列名取值）。
        conn = getattr(getattr(db, 'db', None), 'conn', None)
        if conn is None:
            return {}
        marks = ','.join('?' for _ in ids)
        cursor = conn.cursor()
        rows = cursor.execute(
            f'SELECT id, username, avatar FROM users WHERE id IN ({marks})', ids).fetchall()
        cursor.close()
        return {str(r['id']): {'username': r['username'] or '', 'avatar': r['avatar'] or ''}
                for r in rows if r['id']}
    except Exception as e:      # noqa: BLE001 —— 展示层读不到不该把整张榜打成 500
        print(f'[ranked] 批量读取用户名/头像失败，榜上按空串处理: {e}')
        return {}


def rank_view_for(uid, server_rank=None, captain_pool_rank=None, is_admiral=None,
                  pool_map=None, pool_size=None):
    """把某人的排位积分换算成段位视图（`ranks.rank_view` 的原样返回）。

    `server_rank` / `captain_pool_rank` / `is_admiral` 都可以由调用方**算好后传进来**：
    段位榜一页最多 200 行，逐行去查船长池（`captains_ordered` 一次返回 500 行）
    等于白打 200 次重查询 —— 榜那边算**一次** `pool_map` / `pool_size` 批量传进来即可。

    · `server_rank` 缺省时用 `db.get_rank_position(uid)`；`0` = 没打过排位 → 传 `None`
      （否则文案会变成 `#0`，作者明确要求不许出现）；
    · `captain_pool_rank` 缺省时：**只在该玩家积分 ≥ `ranks.CAPTAIN_FLOOR` 时**
      才去船长池找自己的 `pool_position`，否则 `None`（不够船长段本来就没有池内名次）；
    · `is_admiral` 缺省时按 `ranks.is_admiral(row, 池内名次, 池子人数)` 现算，
      池子人数 = `db.count_rank_at_least(ranks.CAPTAIN_FLOOR)`；
      积分还没到船长段时连这次 COUNT 都省掉（判据第一关就不过，池子人数无关紧要）。

    **只读、绝不写库。**
    """
    row = _safe_read(lambda: db.get_user_rank_row(uid), None, 'user_rank 段位行')
    row = row if isinstance(row, dict) else {}
    points = ranks.normalize_points(row.get('points'))

    if server_rank is None:
        pos = _safe_read(lambda: db.get_rank_position(uid), 0, 'rank_position 段位名次')
        try:
            pos = int(pos or 0)
        except (TypeError, ValueError):
            pos = 0
        server_rank = pos or None       # 0 = 没打过排位 → None

    if captain_pool_rank is None and points >= ranks.CAPTAIN_FLOOR:
        if pool_map is not None:
            captain_pool_rank = pool_map.get(str(uid))
        else:
            pool = _safe_read(lambda: db.captains_ordered(limit=500), [], 'captains 船长池')
            for entry in (pool or []):
                if str(entry.get('user_id')) == str(uid):
                    captain_pool_rank = entry.get('pool_position')
                    break

    if is_admiral is None:
        if points < ranks.CAPTAIN_FLOOR:
            is_admiral = False
        else:
            if pool_size is None:
                pool_size = _safe_read(
                    lambda: db.count_rank_at_least(ranks.CAPTAIN_FLOOR), 0,
                    'captain_pool_size 船长池人数')
            is_admiral = bool(ranks.is_admiral(row, captain_pool_rank, pool_size))

    return ranks.rank_view(points, is_admiral=bool(is_admiral),
                           server_rank=server_rank, captain_pool_rank=captain_pool_rank)


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
    # ★ 2026-09-20：存储的外观要按**当前**解锁状态过滤（掉段/被回滚分数的会回落默认）。
    #    以前这里原样下发存储值，而写路径却会拒绝失效项 —— 一条规则两处不一致。
    _tid, _fid, _bid = profile_spec.effective_equipped(
        stats, extra.get('title_id'), extra.get('frame_id'), extra.get('card_bg_id'))
    profile.update({
        'rank': rank,
        'name_style': _name_style(uid),
        'level_info': level_view_for(uid),
        'title_id': _tid,
        'tags': extra.get('tags') or [],
        'status_text': extra.get('status_text') or '',
        'frame_id': _fid,
        'card_bg_id': _bid,
        'show_stats': int(extra.get('show_stats') or 0),
        'show_fav_cards': int(extra.get('show_fav_cards') or 0),
        'show_history': int(extra.get('show_history') or 0),
        # 留言板开关（第 3 批）：第 4 个展示开关，与另外三个同进同出 ——
        # 编辑面拿它初始化 `#profile-show-guestbook` 复选框。
        'show_guestbook': int(extra.get('show_guestbook') if extra.get('show_guestbook') is not None else 1),
        # 段位开关（段位批）：第 5 个展示开关，同样同进同出（保存载荷 9 → 10 字段）。
        # 编辑面拿它初始化 `#profile-show-rank` 复选框。
        'show_rank': int(extra.get('show_rank') if extra.get('show_rank') is not None else 1),
        # 好友申请开关（好友批，决策④的"设置里可关"）：走同一条保存通道，
        # 但**只下发给本人**（不进 `public_stats`）—— 别人不需要知道"这个人关掉了申请"，
        # 点下去由服务端回一句中文原因就够了。
        'friend_requests_open': int(
            extra.get('friend_requests_open') if extra.get('friend_requests_open') is not None else 1),
        # 段位视图（`ranks.rank_view` 的原样返回）：**自己视角恒下发**。
        # 自己的段位自己当然看得到 —— 那个开关管的是"别人能不能看"，
        # 要是连自己都被开关挡住，"我的段位"就没了（第 1 批 `show_stats` 的教训）。
        'rank_info': rank_view_for(uid),
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


# ---------------------------------------------------------------------------
# 实时观战（第 2 批）：允许他人观战我的对局 —— 全局设置，**默认开**
# ---------------------------------------------------------------------------
# 存哪：`user_profile.allow_spectate`（老表加列，`db._migrate_schema` 判存在再 ALTER），
#       默认 1 = 允许。读/写都只看这一列。
#
# ⚠️ **刻意不并进 `POST /api/profile/card`**：那条是"整行语义、缺的键用默认值补齐"，
#    而本批不动前端 —— 名片保存请求里不会带这个字段，并进去等于"玩家每存一次名片，
#    观战开关就被静默改回允许"。所以这里给一对**只动这一列**的专用接口。
#    守卫：tests/test_spectate_batch2.py::test_saving_profile_card_does_not_reset_spectate_switch
@app.route('/api/spectate/setting', methods=['GET'])
def get_spectate_setting():
    """读「允许他人观战我的对局」。

    未登录 401 —— 这个开关是**账号级私有设置**，游客没有它
    （游客的对局也进不了观战：`server._spectate_seat_allow` 对无账号座位返回 None）。
    """
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401
    value = db.get_allow_spectate(uid)
    if value is None:
        # 读不到 → 如实说"不知道"，**绝不许**谎报成"允许"（教训 #21）
        return jsonify({'success': False, 'error': '暂时无法读取设置，请稍后重试'}), 503
    return jsonify({'success': True, 'allow_spectate': bool(value)})


@app.route('/api/spectate/setting', methods=['POST'])
def save_spectate_setting():
    """写「允许他人观战我的对局」。请求体：`{'allow_spectate': true|false}`。

    ⚠️ 字段缺失/类型不对一律 **400 带原因**（教训 #32：不许静默当默认值处理 ——
       那会让"我明明关掉了"和"请求没生效"分不出来）。
    """
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if not db.get_user(uid=uid):
        return jsonify({'success': False, 'error': '账号不存在'}), 401

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict() if request.form else None
    if not isinstance(payload, dict) or 'allow_spectate' not in payload:
        return jsonify({'success': False, 'error': '请求体必须带 allow_spectate'}), 400

    raw = payload.get('allow_spectate')
    if isinstance(raw, bool):
        on = raw
    elif isinstance(raw, (int, str)) and str(raw) in ('0', '1'):
        on = str(raw) == '1'
    elif isinstance(raw, str) and raw.strip().lower() in ('true', 'false', 'on', 'off'):
        on = raw.strip().lower() in ('true', 'on')
    else:
        return jsonify({'success': False, 'error': 'allow_spectate 必须是布尔值'}), 400

    if not db.set_allow_spectate(uid, on):
        return jsonify({'success': False, 'error': '保存失败，请稍后重试'}), 500
    return jsonify({'success': True, 'allow_spectate': on})


# ---------------------------------------------------------------------------
# 对局回放（2026-09-23 回放批 §5/§6）
# ---------------------------------------------------------------------------
# 三条铁律（契约 §5「绝不做」，三条都写成源码级守卫，见 tests/test_replay_guards.py）：
#   · 本段代码**不发任何 socket 事件**（`emit(` / `socketio` 一个字都不许出现）——
#     回放数据里有双方船位，一旦 emit 进对局房间就是灾难级泄露；
#   · 回放相关的键**永不进 `SPECTATE_EVENTS`**；
#   · `_build_spectate_snapshot` **永不读回放表**。
#
# 读权限（契约 §5）：能看你战绩的人都能看 ——
#   · 请求者是该局参与者（`winner_user_id` / `loser_user_id` == 自己），**或**
#   · 该局某个真实参与者 `show_history = 1`（实测默认 0 = 不公开 ⇒ 默认只有双方能看到）。
# **假设 A1**：回放接口**要求登录**（游客 401）。观战已是"只限登录用户"，
#   回放比观战敏感得多（它泄露船位），不给匿名抓取留口子。
import replay as replay_module      # 纯模块：记录器 + 打包（不 import server，见其 docstring）


def _replay_participant_ids(row):
    """一条回放行里的两个真实参与者 uid（可能为空）。"""
    return [u for u in (row.get('winner_user_id'), row.get('loser_user_id')) if u]


def _replay_show_history(uid):
    """该账号有没有公开战绩历史（`user_profile.show_history`，实测默认 0 = 不公开）。

    读不到（uid 空 / 库异常）一律按 **0 = 不公开** —— 这个判据是**放行**用的，
    失败方向必须朝"拒"（隐私开关方向一律朝安全那一侧兜，教训 #21）。
    """
    if not uid:
        return 0
    try:
        extra = db.get_user_profile_extra(uid) or {}
    except Exception as e:              # noqa: BLE001
        print(f'[replay] 读取 show_history 失败（按不公开处理）: uid={uid} -> {e}')
        return 0
    try:
        return int(extra.get('show_history') or 0)
    except (TypeError, ValueError):
        return 0


def _replay_read_allowed(match_id, viewer_uid):
    """这条回放该不该给 `viewer_uid` 看。返回 `(ok, payload, row, you_are, reason)`。

    `ok=False` 时 `reason` 是给玩家看的一句话（**失败必须带原因**，教训 #32）。

    ⚠️ **权限**只看 `match_replays` 的两列（参与者 / `show_history`），
       与 `you_are` **分开**：后者是"你是哪块棋盘"的展示口径，读的是 blob 里的
       `seats`（按入座顺序记的 `uid → p1/p2`）。两者混用会让"胜者就是 p1"这种
       巧合偷偷变成权限判据（作者实报的 `（你）` 标到对面就是从这个混淆长出来的）。
    """
    row = db.get_match_replay(match_id)
    if not row:
        return False, None, None, None, '这局没有可回放的行动'
    # 体积/版本/解析都还没校验，这里只需要 `seats`：读一次 blob，失败就当没有
    # （**不删**这条 —— 校验与报错是 `get_match_replay` 接口的职责，这里只做鉴权）。
    payload = None
    try:
        payload = json.loads(row.get('replay') or '{}')
        payload = payload if isinstance(payload, dict) else None
    except Exception:                   # noqa: BLE001
        payload = None
    mine = replay_module.you_are(payload, row, viewer_uid)
    if mine:
        return True, payload, row, mine, ''
    # 非参与者：只要任一真实参与者公开了战绩，就跟着能看（契约 §5）
    for uid in _replay_participant_ids(row):
        if _replay_show_history(uid):
            return True, payload, row, None, ''
    return False, payload, row, None, '你没有权限查看这一局的回放'


@app.route('/api/replay/setting', methods=['GET'])
def get_replay_setting():
    """读「允许保留我的对局回放」。状态**只来自服务端**（契约 §5）。"""
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401
    value = db.get_allow_replay(uid)
    if value is None:
        # 读不到 → 如实说"不知道"，**绝不许**谎报成"允许"（教训 #21）
        return jsonify({'success': False, 'error': '暂时无法读取设置，请稍后重试'}), 503
    return jsonify({'success': True, 'allow_replay': bool(value)})


@app.route('/api/replay/setting', methods=['POST'])
def save_replay_setting():
    """写「允许保留我的对局回放」。请求体：`{'allow_replay': true|false}`。

    ⚠️ 字段缺失/类型不对一律 **400 带原因**（教训 #32：不许静默当默认值处理）。
    ⚠️ 与观战开关**同语义**：任一方关掉 ⇒ **这一局就不留回放**（契约 §5）——
       判定在 `server._replay_allowed_for_match`，本接口只负责存这一个布尔。
    """
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401
    if not db.get_user(uid=uid):
        return jsonify({'success': False, 'error': '账号不存在'}), 401

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict() if request.form else None
    if not isinstance(payload, dict) or 'allow_replay' not in payload:
        return jsonify({'success': False, 'error': '请求体必须带 allow_replay'}), 400

    raw = payload.get('allow_replay')
    if isinstance(raw, bool):
        on = raw
    elif isinstance(raw, (int, str)) and str(raw) in ('0', '1'):
        on = str(raw) == '1'
    elif isinstance(raw, str) and raw.strip().lower() in ('true', 'false', 'on', 'off'):
        on = raw.strip().lower() in ('true', 'on')
    else:
        return jsonify({'success': False, 'error': 'allow_replay 必须是布尔值'}), 400

    if not db.set_allow_replay(uid, on):
        return jsonify({'success': False, 'error': '保存失败，请稍后重试'}), 500
    return jsonify({'success': True, 'allow_replay': on})


@app.route('/api/replay/<match_id>', methods=['GET'])
def get_match_replay(match_id):
    """读一条回放：`{success, replay, you_are}`（`you_are` ∈ `p1`/`p2`/None）。

    ⚠️ **绝不下发任何 user_id**（契约 §6）：`you_are` 由服务端算好，
       它就是"你是两块棋盘里的哪一块"。
    ⚠️ 读的时候**只读一条**、**有 512 KB 硬上限**、**解析失败明确报错 + 打日志 +
       顺手删掉这条坏回放**（契约 §1/§6：绝不静默返回空）。
    """
    uid = session.get('user_id')
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401          # 假设 A1

    allowed, _payload_for_seats, row, you_are, reason = _replay_read_allowed(match_id, uid)
    # ⚠️ 鉴权段解析出来的那份**只用来看 `seats`**，到这里一律丢掉、下面重新解析：
    #    它是**超限校验之前**读的，不许拿它当"体积合法"的证据（契约 §1 的 512 KB 硬上限）。
    del _payload_for_seats
    if row is None:
        return jsonify({'success': False, 'error': reason}), 404
    if not allowed:
        return jsonify({'success': False, 'error': reason}), 403

    # ① 体积上限：**先看 `bytes` 列**（不必把 blob 读进内存再判）
    try:
        size = int(row.get('bytes') or 0)
    except (TypeError, ValueError):
        size = 0
    if size > replay_module.MAX_REPLAY_BYTES:
        print(f'[replay] 回放 blob 超限，已拒收: match_id={match_id}, bytes={size}')
        return jsonify({'success': False,
                        'error': '这条回放数据异常（体积超限），已拒绝加载'}), 500

    blob = row.get('replay') or ''
    if len(blob.encode('utf-8')) > replay_module.MAX_REPLAY_BYTES:
        print(f'[replay] 回放 blob 超限（实际字节），已拒收: match_id={match_id}')
        return jsonify({'success': False,
                        'error': '这条回放数据异常（体积超限），已拒绝加载'}), 500

    # ② 解析：失败**明确报错 + 打日志 + 删掉这条坏回放**（教训 #32：不许静默）
    try:
        payload = json.loads(blob)
    except Exception as e:              # noqa: BLE001
        print(f'[replay] 回放解析失败，已删除这条坏回放: match_id={match_id} -> {e}')
        db.delete_match_replay(match_id)
        return jsonify({'success': False, 'error': '这条回放已损坏，无法回放'}), 500
    if not isinstance(payload, dict):
        print(f'[replay] 回放不是 JSON 对象，已删除: match_id={match_id}')
        db.delete_match_replay(match_id)
        return jsonify({'success': False, 'error': '这条回放已损坏，无法回放'}), 500

    # ③ 版本：对不上 ⇒ 明确报错（**不删**：将来可能有人读得懂旧版本）
    if int(payload.get('version') or 0) != replay_module.REPLAY_VERSION:
        print(f'[replay] 回放版本不认识: match_id={match_id}, '
              f'version={payload.get("version")!r}')
        return jsonify({'success': False, 'error': '这条回放的格式版本不支持'}), 409

    return jsonify({'success': True, 'replay': payload, 'you_are': you_are})


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
    # ★ 2026-09-20：别人视角同样要按**当前**解锁状态过滤（与 `build_own_profile` 同一份判据）。
    #    漏了这里 = "别人能看到你无权拥有的外观"，比自视角显示更糟（那是公开可见的）。
    _stats_for_unlock = _profile_unlock_stats(stats['id'], stats)
    _tid, _fid, _bid = profile_spec.effective_equipped(
        _stats_for_unlock, extra.get('title_id'),
        extra.get('frame_id'), extra.get('card_bg_id'))
    title_id = _tid
    public_stats['title_id'] = title_id
    public_stats['title_name'] = profile_spec.title_name(title_id)
    public_stats['tags'] = extra.get('tags') or []
    # 标签的**中文名**也一并下发。
    # 为什么多发这一份：前端有两处要用标签名（名片、匹配成功的等待界面），
    # 而"id → 名字"的映射在服务端本来就是权威的（`profile_spec.tag_name`）。
    # ⚠️ 前端那份映射函数当时声明在**某个函数作用域里**，模块级代码调不到
    #    （同 PROFILE_BADGE_GLYPH 那个坑，2026-09-17 一天里踩了两次）——
    #    直接让服务端把名字给出来，前端就不必再去够那个作用域。
    public_stats['tag_names'] = [profile_spec.tag_name(t) for t in (extra.get('tags') or [])]
    public_stats['status_text'] = extra.get('status_text') or ''
    public_stats['frame_id'] = _fid
    public_stats['card_bg_id'] = _bid
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
    # 段位开关（段位批）：**别人视角也要下发** —— 前端靠它决定
    # 名片/匹配界面画不画段位。老行由 DEFAULT 1 兜底，缺值按公开。
    # ⚠️ 注意它只控制"**展示**要不要画"，不影响段位榜 —— 榜上的人照样在榜上
    #    （榜是公共竞技数据，不是个人名片的一部分）。
    public_stats['show_rank'] = int(
        extra.get('show_rank') if extra.get('show_rank') is not None else 1)

    # 段位（段位批）：开关本身已经下发（上面那行），这里按「本人 or 公开」决定明细。
    # ⚠️ 不给**空 dict** —— 前端拿到空 dict 会画出「二级水手Ⅰ 0分」这种**假**信息，
    #    `None` 才是"对方未公开段位"这个明确语义（契约 §5.1）。
    # ⚠️ 未公开时 `points` / `server_rank` / `captain_pool_rank` 一个都不下发
    #    （不给 `None` 占位，干脆不放这几个键）。
    # ⚠️ **只有服务端拦得住**：前端断言会假绿（第 3 批的硬教训），
    #    所以测试里必须**以别人的身份直接读接口**断言 `rank_info is None`。
    viewer = session.get('user_id')
    is_self = bool(viewer) and viewer == stats['id']
    if is_self or public_stats['show_rank']:
        public_stats['rank_info'] = rank_view_for(stats['id'])
    else:
        public_stats['rank_info'] = None

    # 点赞 / 送花 / 留言板（第 3 批）：查看面两个视角共用一份互动数据。
    # ⚠️ 计数与"我的状态"**始终可见**，不受 `show_guestbook` 影响 ——
    # 那是"人气"不是"内容"（计划 §3.4）。留言列表本身由
    # `GET /api/profile/messages` 下发（它另做隐私过滤），这里不重复带。
    view = _reaction_view(stats['id'], session.get('user_id'))
    public_stats['counts'] = view['counts']
    public_stats['mine'] = view['mine']
    # 名字样式（特权外观）：**必须下发给别人**，否则彩虹名字只有本人在自己名片里看得到。
    public_stats['name_style'] = _name_style(stats['id'])
    # 等级 / 经验：别人看你的名片也要看到等级与经验条（与"看自己"同一份视图）
    public_stats['level_info'] = level_view_for(stats['id'])

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
    # `viewer` / `is_self` 复用上面段位那一段算好的（同一份口径只算一次，
    # 免得两处各判一次后漂移）。
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
    # 名字样式（特权外观）批量补上：一页最多 100 行，逐行查会打 100 次库 ——
    # 用 `get_perks_map` 一条 SQL 取完。没有特权的行给空串（前端按空串走普通样式）。
    try:
        perks = db.get_perks_map([r.get('id') for r in (rows or [])])
        xps = db.get_xp_map([r.get('id') for r in (rows or [])])
        rainbow = profile_spec.PERK_RAINBOW_NAME
        lvl101 = profile_spec.PERK_LEVEL_101
        for row in rows or []:
            rid = str(row.get('id'))
            pset = perks.get(rid) or set()
            row['name_style'] = 'rainbow' if rainbow in pset else ''
            # 等级也跟着排行榜走（经验同样批量取，别逐行查库）
            row['level'] = leveling.level_view(
                xps.get(rid, 0),
                leveling.LEVEL_101 if lvl101 in pset else leveling.MAX_LEVEL)['level']
    except Exception:
        for row in rows or []:
            row.setdefault('name_style', '')
            row.setdefault('level', 1)
    return jsonify(rows)


# 段位榜（公开只读，**匿名可访问** —— 与战绩榜 `/api/leaderboard` 同类）
@app.route('/api/ranked_leaderboard')
def api_ranked_leaderboard():
    """段位榜一页：`{leaderboard, total, constants}`。

    三条口径（docs/RANKED_2026_09_17.md §5）：

    1. **只列库里有排位记录的账号**（`db.ranked_leaderboard` 已保证）：没打过排位的
       账号不该以「二级水手Ⅰ 0分」占满榜尾（与战绩榜"只统计真打过一局的"同一条）；
    2. **不理会 `show_rank`**：榜是公共竞技数据，玩家关掉"段位公开"之后**仍然在榜上**
       —— 这是产品裁决，不是漏了过滤（开关只管个人信息里那块）。同时这里**不下发**
       任何名片隐私字段，段位榜与名片是两码事；
    3. **批量**：一页最多 200 行，用户名/头像一条 `IN (...)` 取完，船长池与池子人数
       各算一次（逐行查 = 200 次重查询）。
    """
    try:
        limit = int(request.args.get('limit', 100))
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 200))         # 越界夹住：limit=9999 → 200，limit=0 → 1
    try:
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)

    rows = _safe_read(lambda: db.ranked_leaderboard(limit, offset), [],
                      'ranked_leaderboard 段位榜')
    rows = rows if isinstance(rows, list) else []

    # 用户名 / 头像：**批量**取（一页 200 行别逐行查库），查不到就是空串。
    briefs = _users_brief_map([r.get('user_id') for r in rows])

    # 船长池与池子人数：只在**这一页真的有人够到船长段**时才查，
    # 而且只查一次，然后由 `rank_view_for(..., pool_map=, pool_size=)` 批量复用。
    pool_map, pool_size = None, None
    if any(int(r.get('points') or 0) >= ranks.CAPTAIN_FLOOR for r in rows):
        pool_map = {}
        for entry in (_safe_read(lambda: db.captains_ordered(limit=500), [],
                                 'captains 船长池') or []):
            pool_map[str(entry.get('user_id'))] = entry.get('pool_position')
        pool_size = _safe_read(
            lambda: db.count_rank_at_least(ranks.CAPTAIN_FLOOR), 0,
            'captain_pool_size 船长池人数')

    leaderboard = []
    for row in rows:
        uid = str(row.get('user_id') or '')
        brief = briefs.get(uid) or {}
        entry = {
            'user_id': uid,
            'username': brief.get('username') or '',
            'avatar': brief.get('avatar') or '',
            'points': int(row.get('points') or 0),
            'ranked_wins': int(row.get('ranked_wins') or 0),
            'ranked_losses': int(row.get('ranked_losses') or 0),
            # 全服名次由 db 算好（1 起）。它与 `server_rank` 是同一个数：
            # `ranked_leaderboard` 的 position 与 `get_rank_position` 的 COUNT(*)
            # 用的是**同一条排序口径**（points DESC, updated_at ASC, user_id ASC），
            # 传进来就能省掉每行一次 COUNT。
            'position': int(row.get('position') or 0),
        }
        entry.update(rank_view_for(uid, server_rank=(int(row.get('position') or 0) or None),
                                   pool_map=pool_map, pool_size=pool_size))
        leaderboard.append(entry)

    return jsonify({
        'leaderboard': leaderboard,
        # 库里有排位记录的账号总数（不是注册用户数）
        'total': int(_safe_read(lambda: db.count_rank_at_least(0), 0, 'ranked_total') or 0),
        # 规则快照：前端画进度条/写文案不用猜（`ranks.constants()` 是唯一一份）
        'constants': ranks.constants(),
    })


# 段位规则快照（公开只读，**匿名可访问** —— 帮助页要在没登录时也能看段位介绍）
@app.route('/api/rank_constants')
def api_rank_constants():
    """`ranks.constants()` 的原样下发（段位表 / 起始分 / 计分表 / 大舰长晋升条件）。

    只给帮助页与结算面板**读**，没有任何用户数据，所以不要求登录
    （与 `/api/leaderboard` / `/api/ranked_leaderboard` 同类）。

    ⚠️ **读失败要给降级，不许 500**：这是纯展示层的数据，一次读失败不该让
    帮助页整体打不开。但是也**不许编一份数字顶上** —— 前端收到空的 `scoring`
    会显示「计分规则暂不可用」而不是显示一份假的计分表（本项目通用教训二：
    帮助里写 +20、代码里是 +25 这种漂移不报错，只是让帮助变成谎话）。
    """
    try:
        data = ranks.constants()
    except Exception as e:      # noqa: BLE001 —— 展示层读不到就给空壳，别把帮助页打成 500
        print(f'[ranks] 读取段位规则快照失败，按空壳处理: {e}')
        return jsonify({'error': '段位规则暂不可用', 'scoring': {}}), 200
    if not isinstance(data, dict):
        # 契约是 dict；真出现别的形状也按空壳走，不把异常抛给前端
        print(f'[ranks] 段位规则快照形状异常（{type(data).__name__}），按空壳处理')
        return jsonify({'error': '段位规则暂不可用', 'scoring': {}}), 200
    return jsonify(data)


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


@app.route('/api/changelog', methods=['GET'])
def api_changelog():
    """更新公告（公开只读，**不要求登录**）。

    为什么公开：登录页上的人也该看得到"这次改了什么"，而这里全是静态文案、
    没有任何用户数据（与 `/api/quick_chat`、`/api/leaderboard` 同类）。

    ⚠️ 文案的唯一来源是 `changelog.py` —— 前端只渲染，**不许在 `game.js` 里再抄一份**
    （本仓库栽过"同一份内容两份实现必然漂移"）。
    `latest` 是给前端判断"有没有新公告"用的（与 `localStorage` 里存的时间比对）。
    """
    limit = request.args.get('limit', default=10, type=int)
    return jsonify({'status': 'ok', **changelog.view(limit)})


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


# ---------------------------------------------------------------------------
# 好友（社交批）
# ---------------------------------------------------------------------------
# 六个接口，契约冻结（另一个智能体与前端按同一份写，**名字一个都不能改**）：
#   GET  /api/friends           好友 / 收到的申请 / 发出的申请 + 上限 + 计数
#   POST /api/friends/request   {username}
#   POST /api/friends/respond   {username, accept}
#   POST /api/friends/remove    {username}
#   POST /api/friends/block     {username}
#   POST /api/friends/invite    {username}  建房 + 推给对方
#
# 三条贯穿全篇的规矩：
# 1. **全部要求登录**（未登录 401 `{'error':'未登录'}`）。好友是私密数据，
#    连"某人有没有好友"都不该匿名看到。
# 2. **只下发白名单字段**。本项目有一条硬教训：接口整行下发会泄露
#    `password_hash` / `token`（`users` 表里就有这两列）。所以这里
#    `username`/`avatar` 一律走 `_users_brief_map`（只 SELECT 三列），
#    `level`/`rank_label` 走现成的单份实现（`level_view_for` / `rank_view_for`），
#    **绝不**把 user dict 铺进响应。
# 3. **上限与限流在接口层判**（DAO 只管写库）：要下发常量、要回 400/429。
#
# ⚠️ 为什么这里**不** `import server`（哪怕在函数里也不行）：
#    `server.py` 是 `from api import app` —— 一旦 `api` 顶部 import `server`
#    就是**循环导入**（`server` 还没跑完 `app` 那一句，`api` 就来要 `room_manager`）。
#    邀请接口要"建房 + 推送给对方"，两条都不需要 `server`：
#      · 建房 → 函数内延迟导入 `server.room_manager.create_room()`（见 `_friend_new_room`）；
#      · 推送 → `current_app.extensions['socketio']`（`SocketIO(app)` 自己注册的）。
#    详见 `_friend_socketio` 与 `_friend_new_room` 的注释。


def _int_or_zero(raw):
    """把 DAO 回来的计数收敛成 `int`（`None` / 非数字一律 0）。

    为什么需要：统计类 DAO 失败时返回 0、但**打桩/降级路径**可能给出 None；
    `None` 直接进 jsonify 会变成 JSON `null`，前端 `unread > 0` 判真值时
    会静默走错分支（本项目"取数函数兜底值当判据"踩过同形状）。
    """
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _friend_level(uid):
    """等级（数字）。读不到按 1 级 —— 用**现有唯一一份**实现，不在这里重算曲线。"""
    view = _safe_read(lambda: level_view_for(uid), {}, '好友等级视图')
    view = view if isinstance(view, dict) else {}
    try:
        return int(view.get('level') or 1)
    except (TypeError, ValueError):
        return 1


def _friend_rank_label(uid):
    """段位文案（`船长Ⅲ 0分 #3` 这种）。读不到给空串。

    ⚠️ 文案**只在 `ranks.py` 里拼**（`rank_view_for` → `ranks.rank_view`），
    这里绝不自己拼"X 段" —— 两处各拼一份必然漂移（段位批的明文规矩）。
    """
    view = _safe_read(lambda: rank_view_for(uid), {}, '好友段位视图')
    view = view if isinstance(view, dict) else {}
    return str(view.get('label') or '')


def _presence_module():
    """拿到 `presence` 模块；拿不到返回 None。

    ⚠️ `presence.py` 是**同批另一个智能体**创建的纯内存模块（只认 uid，
    不 import `server`），存在的唯一目的就是让 `api.py` 能回答"谁在线/在局中"
    **而不去 import `server`**（那会循环导入 —— `server.py` 里是 `from api import app`）。

    所以这里的降级必须彻底：模块还没落地（并行开发期）或它自己炸了，
    一律当"全员离线"，**绝不允许把 `GET /api/friends` 打成 500** ——
    在线状态只是列表上的一个小绿点，丢了不影响好友列表本身。
    逐个函数再包一层 try：模块在但某个函数还没实现（并行开发中途）也要兜住。
    """
    try:
        import presence                          # noqa: PLC0415 —— 放在函数里是有意的
        return presence
    except Exception as e:      # noqa: BLE001 —— 没落地/炸了都按"离线"处理
        print(f'[friends] presence 模块不可用，在线状态按离线处理: {e}')
        return None


def _friend_presence_view(uids):
    """批量算在线/在局中 → `({uid: bool}, {uid: bool})`。

    分两次问 `presence`（`online_uids()` 一次拿全量集合，比逐个 `is_online`
    省 N 次调用）；任一步失败就整体退化成"全离线"，不做半真半假的混合。
    """
    online, in_game = {}, {}
    wanted = [str(u) for u in (uids or []) if u]
    if not wanted:
        return online, in_game
    module = _presence_module()
    if module is None:
        return online, in_game
    online_set = set()
    try:
        online_set = {str(u) for u in (module.online_uids() or [])}
    except Exception as e:      # noqa: BLE001
        print(f'[friends] presence.online_uids() 失败，按离线处理: {e}')
    for uid in wanted:
        online[uid] = uid in online_set
        try:
            in_game[uid] = bool(module.is_in_game(uid)) if uid in online_set else False
        except Exception as e:      # noqa: BLE001
            print(f'[friends] presence.is_in_game({uid}) 失败，按 False 处理: {e}')
            in_game[uid] = False
    return online, in_game


# ---------------------------------------------------------------------------
# 好友功能的"实时推送 / 建房"由 server.py 在 import 期注入（见 server.py 末尾）。
#
# ⚠️⚠️ **这里绝对不能 `import server`**（曾经就是那么写的，踩了个大坑）：
#   应用是用 `python server.py` 启动的，那时本模块名是 **`__main__`**，而
#   `import server` 会**把整个 server.py 再执行一遍**、得到**另一个模块对象**。
#   于是：
#     · 那份 `socketio` 不是正在服务的那个 → 事件 emit 出去**静默丢弃**
#       （表现："接口回 sent/ok，对方什么也没收到"，且服务端零报错）；
#     · 那份 `room_manager` 建的房在真进程里**根本不存在** → 邀请的 room_id 是野的；
#     · 生产是 `run_prod.py` 启动的，模块名又是正常的 `server` →
#       **本地坏、线上好**（或反之），属于最难查的一类环境相关 bug。
#   注入之后，两份实现都不需要了：推送与建房仍然各只有 server.py 里那一份。
# ---------------------------------------------------------------------------
_FRIEND_BACKEND_MODULE = None


def register_friend_backend(module, **names):
    """由 `server.py` 在 import 期把**它自己那个模块对象**交过来（见模块顶部说明）。

    ⚠️ 只存模块、**不存函数对象**：推送/建房函数在调用那一刻按名字现取。
    存函数对象会在 import 期就把 `server.push_friend_invite` 绑死，
    `monkeypatch.setattr(server, 'push_friend_invite', ...)` 这类打桩**全部被架空**
    —— 测试静默打到空处还会是绿的。

    `**names` 是**能力清单**（`server.py` 那边写成 `push_friend_message='push_friend_message'`）。
    它**不改"按名字现取"这条机制**，只做一件事：**在 import 期把清单里缺失的名字喊出来**。
    为什么值得加 —— `_friend_backend(name)` 拿不到函数时只 print 一句就返回 None，
    调用方于是静默失败（接口照回 ok、对方什么也没收到）；而这类"功能看着有、
    其实永远不触发"的坑**在 pytest 里测不到**（pytest 里 server 就叫 `server`，
    一切正常），只有服务启动那一眼能看出来。
    """
    global _FRIEND_BACKEND_MODULE
    if module is None:
        print('[friends] 注入的后端模块是 None，忽略')
        return False
    _FRIEND_BACKEND_MODULE = module
    for key, fn_name in sorted(names.items()):
        if not callable(getattr(module, fn_name, None)):
            print(f'[friends] 清单里的 {key} 在后端模块里不存在（该能力会静默失效）: {fn_name}')
    return True


def _friend_backend(name):
    """按名字取后端能力（实时推送 / 建房）；没注入或名字不存在都返回 `None`。"""
    module = _FRIEND_BACKEND_MODULE
    if module is None:
        return None
    fn = getattr(module, name, None)
    return fn if callable(fn) else None


def _push_friend_event(func_name, *args):
    """把好友类实时事件交给注入进来的推送函数（**实时只有一份实现**）。

    返回 `True` = 真的推出去了；`False` = 对方离线 / 后端没注入 / 抛异常。
    调用方**必须**据此决定要不要回 `ok` —— socket.io 对不存在的房间是**静默丢弃**，
    在这里"乐观地回 ok"就会造出"接口说成功、对方什么也没收到"的假成功。
    """
    fn = _friend_backend(func_name)
    if fn is None:
        print(f'[friends] 后端没有 {func_name}（server 没起来？），推送失败')
        return False
    try:
        return bool(fn(*args))
    except Exception as e:      # noqa: BLE001 —— 推送失败只记日志，绝不把请求打成 500
        print(f'[friends] {func_name} 推送失败: {e}')
        return False


def _my_friend_identity(uid):
    """推送事件里要带的"我是谁"（用户名 + 头像）。

    只取两个展示字段；**绝不**把 user dict 整个铺进 payload（`users` 表有凭证列）。
    """
    username = ''
    avatar = ''
    try:
        username = str(session.get('username') or '')
    except Exception:           # noqa: BLE001 —— 无请求上下文时拿不到就留空
        username = ''
    try:
        avatar = str((db.get_user(uid=uid) or {}).get('avatar') or '')
    except Exception as e:      # noqa: BLE001
        print(f'[friends] 读取头像失败，按空处理: {e}')
    return username, avatar


def _friend_invite_targets(uid):
    """把邀请事件推给某个 uid 的**所有连接**。

    返回 `None` 表示"推不出去"（对方离线 / `presence` 不可用），调用方据此
    返回 `{'status':'error','error':'对方不在线'}` —— **不硬编一个 sid**：
    编出来的 sid 发出去是**静默丢弃**（socket.io 对不存在的房间不报错），
    表现就是"接口说成功、对方什么也没收到"，这是最难查的一类假成功。

    `presence.sids_of(uid)` 是契约里**可选**的能力（另一个智能体不一定提供），
    所以有就用、没有就用 uid 当房间名发给 `presence` 侧；两者都拿不到就是离线。
    """
    module = _presence_module()
    if module is None:
        return None
    try:
        if not module.is_online(uid):
            return None
    except Exception as e:      # noqa: BLE001 —— 判断不了就当离线，宁可回 error
        print(f'[friends] presence.is_online({uid}) 失败，按离线处理: {e}')
        return None
    sids_of = getattr(module, 'sids_of', None)
    if not callable(sids_of):
        return None
    try:
        sids = [str(s) for s in (sids_of(uid) or []) if s]
    except Exception as e:      # noqa: BLE001
        print(f'[friends] presence.sids_of({uid}) 失败，按离线处理: {e}')
        return None
    if not sids:
        return None
    return sids


def _friend_new_room():
    """建一个自定义房，返回 room_id（失败返回 ''）。

    建房能力由 `server.py` 注入（`register_friend_backend`）—— **不要在这里 import
    server**，理由见本文件顶部那段注释（`__main__` 与 `server` 会是两个模块对象）。

    ⚠️ 复用 `room_manager.create_room()`（**不重写一份建房逻辑**）：房间的
    `ranked=False`、清理、宽限计时等口径全在那一个地方，自建一个 GameRoom
    必然漏掉其中几条。`create_room()` 只碰 `uuid` 与 `self.rooms`，不读
    `session` / `request`，所以在 HTTP 请求里调用是安全的（对比
    `handle_create_room` 那个 socket 事件：它要 `request.sid` 才能把自己入座，
    在 HTTP 里**不能**直接复用）。
    """
    fn = _friend_backend('create_custom_room_for_invite')
    if fn is None:
        print('[friends] 后端没有 create_custom_room_for_invite（server 没起来？），无法建房')
        return ''
    try:
        return str(fn() or '')
    except Exception as e:      # noqa: BLE001 —— 建房失败只记日志，接口回 error 不 500
        print(f'[friends] 建房失败: {e}')
        return ''


def build_friends_payload(uid):
    """`GET /api/friends` 的响应体（**唯一一份组装实现**）。

    形状冻结：
      `friends`  [{'user_id','username','avatar','level','rank_label','online','in_game','unread'}]
      `incoming` / `outgoing`  [{'user_id','username','avatar','created_at'}]
      `limits`   {'max_friends': 50, 'requests_per_hour': 10}
      `counts`   {'friends': N, 'incoming': N, 'unread_total': N}
    """
    friend_rows = db.list_friends(uid) or []
    incoming_rows = db.list_incoming_requests(uid) or []
    outgoing_rows = db.list_outgoing_requests(uid) or []

    # 一次把所有涉及的 uid 的 username/avatar 查出来（只 SELECT 三列的批量读）。
    # 好友列表最多 50 行，逐行 db.get_user 就是 50 次查询，还会把
    # password_hash 读进内存 —— 用 _users_brief_map 一次搞定且不碰凭证列。
    all_uids = [str(r.get('user_id') or '') for r in friend_rows]
    all_uids += [str(r.get('user_id') or '') for r in incoming_rows]
    all_uids += [str(r.get('user_id') or '') for r in outgoing_rows]
    brief = _safe_read(lambda: _users_brief_map(all_uids), {}, '好友用户名/头像')
    brief = brief if isinstance(brief, dict) else {}

    online_map, in_game_map = _friend_presence_view(all_uids)

    # 未读私聊：**一条 GROUP BY 拿全**（`db.unread_by_friend`），不逐行 count。
    # ⚠️ 未读**只进 friend 行与 unread_total**，绝不混进 `counts.incoming` ——
    #    入口红点的契约是"待确认好友申请数"，被 `friends_check` T8b 钉着；
    #    把未读并进去会让"红点=申请数"那条既有断言失真（契约 §1 明文）。
    unread_map = db.unread_by_friend(uid)
    unread_map = unread_map if isinstance(unread_map, dict) else {}

    friends = []
    for row in friend_rows:
        other = str(row.get('user_id') or '')
        if not other:
            continue
        info = brief.get(other) or {}
        friends.append({
            'user_id': other,
            'username': info.get('username') or '',
            'avatar': info.get('avatar') or '',
            'level': _friend_level(other),
            'rank_label': _friend_rank_label(other),
            'online': bool(online_map.get(other)),
            'in_game': bool(in_game_map.get(other)),
            # 未读数是**服务端算好的事实**（前端不许自己数组加减，契约 §5 前端纪律）
            'unread': _int_or_zero(unread_map.get(other)),
        })

    # 排序：在线在前 → 在局中在后 → 用户名。
    # `in_game` 排在**后面**（不在局中的更靠前）：好友都在线时，先把"闲着能一起打"
    # 的排上来才有用。用户名用 `lower()` 比较，免得大小写把同一批人拆成两段；
    # 最后再带上 user_id 兜底 —— 同名（或都读不到用户名）时排序必须**稳定**，
    # 否则每次刷新列表顺序都在抖。
    friends.sort(key=lambda f: (not f['online'], f['in_game'],
                                (f['username'] or '').lower(), f['user_id']))

    def _brief_list(rows):
        out = []
        for row in rows:
            other = str(row.get('user_id') or '')
            if not other:
                continue
            info = brief.get(other) or {}
            out.append({
                'user_id': other,
                'username': info.get('username') or '',
                'avatar': info.get('avatar') or '',
                'created_at': int(row.get('created_at') or 0),
            })
        return out

    return {
        'friends': friends,
        'incoming': _brief_list(incoming_rows),
        'outgoing': _brief_list(outgoing_rows),
        'limits': {'max_friends': MAX_FRIENDS,
                   'requests_per_hour': FRIEND_REQUESTS_PER_HOUR},
        'counts': {'friends': len(friends),
                   'incoming': len(incoming_rows),
                   # 未读私聊总数（**入口红点不读它**，见上面的注释与契约 §1）。
                   # 用 `count_unread_messages` 而不是把上面那些 unread 加起来：
                   # 加起来只覆盖**还是好友**的人，而解除好友之后未读仍在库里，
                   # 两个数字会悄悄对不上（这是同一件事的两份算法）。
                   'unread_total': _int_or_zero(db.count_unread_messages(uid))},
    }


def _payload_bool(raw, default=False):
    """把 JSON/表单里的"布尔"归一化。

    前端可能发 `true` / `"true"` / `1` / `"1"`（`request.form` 一路全是字符串）。
    分不出真假时给 `default`：`respond` 的 `accept` 缺省必须落成 **False**——
    把拿不准的输入当"接受"是最坏的方向（一个畸形请求就能让别人白加你好友）。
    """
    if raw is None:
        return default
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in ('1', 'true', 'yes', 'on'):
            return True
        if text in ('0', 'false', 'no', 'off', ''):
            return False
        return default
    return bool(raw)


def _friends_require_login():
    """统一的登录门禁：未登录返回 `(None, 401 响应)`，已登录返回 `(uid, None)`。

    ⚠️ 返回体逐字是 `{'error': '未登录'}`（契约冻结）—— 不要顺手加 `success`
    或换文案，前端与另一个智能体的测试都按这个键取值。
    """
    uid = session.get('user_id')
    if not uid:
        return None, (jsonify({'error': '未登录'}), 401)
    return uid, None


@app.route('/api/friends', methods=['GET'])
def api_friends_list():
    """我的好友 + 收到的申请 + 发出的申请 + 上限 + 计数。"""
    uid, err = _friends_require_login()
    if err:
        return err
    return jsonify(build_friends_payload(uid))


@app.route('/api/friends/request', methods=['POST'])
def api_friend_request():
    """发起好友申请。

    401 未登录 ｜ 404 账号不存在 ｜ 400 自己加自己 / 好友已满 ｜ 429 申请太频繁
    200 `{'status': ...}`（status 的取值由 DAO 给，接口不重写这套判断）
    """
    uid, err = _friends_require_login()
    if err:
        return err

    payload = _get_json_payload() or {}
    target, err = _target_user(payload)
    if err:
        return err

    # 「不能加自己」在 DAO 里也有（`send_friend_request` 返回 'self'），
    # 但这里先回 400：契约里 `status='self'` 也要能拿到，两条路都留着 ——
    # 走 400 是给"接口调用方"的明确信号，走 'self' 是给 DAO 直调方的。
    if str(target['id']) == str(uid):
        return jsonify({'status': 'self'}), 400

    # 对方关掉了"允许他人加我好友"（设置里的开关，默认开）→ 明确拒绝。
    # ⚠️ 必须显式判 `== 0`：`get_user_profile_extra` 是**带兜底的取数函数**
    #    （没记录时给默认值 1），拿"取不到"当"关着"正是本项目踩过的
    #    "会兜底的取数函数当门禁"那一类。
    target_extra = db.get_user_profile_extra(target['id']) or {}
    target_open = target_extra.get('friend_requests_open')
    if int(target_open if target_open is not None else 1) == 0:
        return jsonify({'status': 'error', 'error': '对方暂时不接受好友申请'}), 403

    # 好友数上限：**用 `count_friends` 判，不数 `friends` 列表长度** ——
    # `GET /api/friends` 那一份是"组装+排序"后的结果，拿它当判据等于
    # "取数函数当门禁"（本项目栽过：会兜底的取数函数恒非 0 → 门禁失效）。
    if int(db.count_friends(uid) or 0) >= MAX_FRIENDS:
        return jsonify({'error': '好友数量已达上限'}), 400

    # 限流：只看**我发出的 pending**（被接受/拉黑的不再占配额）。
    since = int(time.time()) - 3600
    if int(db.count_requests_since(uid, since) or 0) >= FRIEND_REQUESTS_PER_HOUR:
        return jsonify({'error': '申请太频繁，请稍后再试'}), 429

    status = db.send_friend_request(uid, target['id'])
    # ⚠️ **写库成功之后必须推事件** —— 否则对方在线也看不到任何提示，
    #    只能等他自己去翻好友面板（前端那个 `friend_request` 处理函数会是死代码）。
    if status == 'sent':
        username, avatar = _my_friend_identity(uid)
        _push_friend_event('push_friend_request', target['id'], uid, username, avatar)
    if status == 'blocked':
        # 拉黑关系：`status` 只说"不成"，前端 `apiReason()` 只认 error/message ——
        # 不带原因的话页面只能弹一句通用文案（实测：body 只有 status → 兜不到原因）。
        # ⚠️ 文案**不区分方向**（谁拉黑了谁）：服务端有意不告诉客户端这件事。
        return jsonify({'status': status, 'error': '暂时无法向该玩家发送好友申请'})
    return jsonify({'status': status})


@app.route('/api/friends/respond', methods=['POST'])
def api_friend_respond():
    """回应好友申请。

    `accept=false`（拒绝）= 删掉那条 `对方 → 我` 的 pending，**不是**拉黑：
    拒绝之后对方还能再申请（拉黑是另一个接口的事）。
    重复接受是**幂等**的（DAO 认已存在的 accepted 边）。
    """
    uid, err = _friends_require_login()
    if err:
        return err

    payload = _get_json_payload() or {}
    target, err = _target_user(payload)
    if err:
        return err

    if _payload_bool(payload.get('accept'), default=False):
        if not db.accept_friend_request(uid, target['id']):
            return jsonify({'status': 'error'})
        # 同上：接受之后要主动告诉**发起人**（他可能正开着页面等）。
        username, avatar = _my_friend_identity(uid)
        _push_friend_event('push_friend_accepted', target['id'], uid, username, avatar)
        return jsonify({'status': 'accepted'})
    # 拒绝 = 删掉待处理的申请（两向都清，避免"我拒绝了他、他那边的 pending 还在"）。
    # ⚠️ 不能复用 `remove_friend`：那个只删 **accepted** 边，对 pending 是空操作 ——
    # 用了就会"接口回 declined、申请还在"，对方列表里那条申请永远不会消失。
    if not db.remove_friend_request(uid, target['id']):
        return jsonify({'status': 'error'})
    return jsonify({'status': 'declined'})


@app.route('/api/friends/remove', methods=['POST'])
def api_friend_remove():
    """删除好友（双向）。幂等：本来就不是好友也返回 ok。"""
    uid, err = _friends_require_login()
    if err:
        return err

    payload = _get_json_payload() or {}
    target, err = _target_user(payload)
    if err:
        return err

    if str(target['id']) == str(uid):
        return jsonify({'status': 'error', 'error': '不能删除自己'}), 400
    if not db.remove_friend(uid, target['id']):
        return jsonify({'status': 'error'})
    return jsonify({'status': 'ok'})


@app.route('/api/friends/block', methods=['POST'])
def api_friend_block():
    """拉黑：两向 pending/accepted 清掉，写一条 `我 → 他` 的 blocked。幂等。"""
    uid, err = _friends_require_login()
    if err:
        return err

    payload = _get_json_payload() or {}
    target, err = _target_user(payload)
    if err:
        return err

    if str(target['id']) == str(uid):
        return jsonify({'status': 'error', 'error': '不能拉黑自己'}), 400
    if not db.block_user(uid, target['id']):
        return jsonify({'status': 'error'})
    return jsonify({'status': 'ok'})


@app.route('/api/friends/invite', methods=['POST'])
def api_friend_invite():
    """邀请在线好友开一局自定义房：建房 + 把房间号推给对方。

    ⚠️ 这里**不做"是不是好友"的校验**是有意的：邀请是对局行为、不是社交关系
    变更，而且自定义房本来就能用房间号邀请任何在线的人。加上好友校验会让
    "刚删了好友还想再拉一把"变成死路，收益也不存在。
    """
    uid, err = _friends_require_login()
    if err:
        return err

    payload = _get_json_payload() or {}
    target, err = _target_user(payload)
    if err:
        return err

    other = str(target['id'])
    if other == str(uid):
        return jsonify({'status': 'error', 'error': '不能邀请自己'}), 400

    # ⚠️ 发起方**自己不能正在局中**：邀战会把**发起方也带进这间新房**
    #    （前端 `sendFriendInvite` 成功后调 `joinRoomById`；否则房里永远只有对方一人、
    #    开不了局）。局中再进一间会把自己那局搞乱，所以先拦一道。
    #    判据走 `presence`；取不到 presence 就**放行**（不硬拦，宁可少拦也不错拦）。
    pres = _presence_module()
    if pres is not None:
        try:
            if pres.is_in_game(uid):
                return jsonify({'status': 'error', 'error': '你正在对局中，结束这局再邀战'}), 409
        except Exception:                                            # noqa: BLE001
            pass

    # 先判在线，再建房 —— 顺序不能反：反了会给离线好友房间里留一堆僵尸房。
    if not _friend_invite_targets(other):
        return jsonify({'status': 'error', 'error': '对方不在线'})

    room_id = _friend_new_room()
    if not room_id:
        return jsonify({'status': 'error', 'error': '建房失败，请稍后再试'})

    username, _avatar = _my_friend_identity(uid)
    # ⚠️ **推送只有一份实现**：走 `server.push_friend_invite`（那里读 `server.socketio`
    #    并逐 sid 发，多标签页都收得到）。本文件不再自己 emit —— 两份实现必然漂移。
    if not _push_friend_event('push_friend_invite', other, room_id, uid, username):
        return jsonify({'status': 'error', 'error': '推送失败，请稍后再试'})

    return jsonify({'status': 'ok', 'room_id': room_id})


# ---------------------------------------------------------------------------
# 好友私聊（2026-09-19 私聊批）
# ---------------------------------------------------------------------------
# 三个接口，契约冻结（前端与端到端工具按同一份写，**名字与字段一个都不能改**）：
#   GET  /api/friends/messages?username=<name>&limit=50&before=<id>   取会话（最新的在后）
#   POST /api/friends/messages  {username, body}                      发一条
#   POST /api/friends/messages/read  {username}                       把某人发来的标已读
#
# 四条贯穿全篇的规矩（与好友那六个接口同一套）：
# 1. **全部要求登录**（401 `{'error':'未登录'}`）—— 私聊内容是私密数据。
# 2. **只下发白名单字段**（见 `_public_dm_message`），绝不整行 `SELECT *` 铺给前端。
# 3. **规则只有一份实现**：长度 / 频率 / 时间格式全在 `dm.py`，这里只组装。
# 4. **业务校验在接口层**（好友关系、空/超长、频率），DAO 只管写库。
#
# ⚠️ 时间**只下发 `stamp`**，不让前端拿 `created_at` 自己算 —— 契约 §3 明文：
#    `stamp` 的唯一实现在 `dm.py`，前端只渲染。两份格式化必然漂移（本项目的
#    "同一规则两份实现"老病根），而且跨年那条规则一旦漂移，用户翻旧记录会看到错年份。

# 取会话时默认一次给多少条（契约 §4：默认最近 50 条）。
DM_PAGE_SIZE = dm.PAGE_SIZE
# 单页上限：前端传再大的 limit 也只给这么多 —— 聊天记录永久保留，
# 不设上限的话 `?limit=100000` 就是一次把整个会话塞进内存（单请求打垮服务）。
DM_MAX_PAGE_SIZE = dm.MAX_PAGE_SIZE


def _public_dm_message(row, me_uid):
    """一条私聊 → **下发形状**（唯一一份组装实现）。字段逐字来自契约 §4。

    `mine` 由**服务端**按当前视角算：前端拿它决定 `.dm-row[data-mine]` 的左右对齐。
    让前端自己比较 `from_uid == 我的 uid` 看似也行，但那需要前端知道"我的 uid"
    （契约里从头到尾没下发过自己的 uid），所以这个判断只能在这里做。

    返回的 dict **刻意带上 `from_uid` / `to_uid`**（契约的 GET/POST 形状里有它们）：
    前端目前用不到，但"谁发给谁"是这段会话的基本事实，且验接口时不用再去猜。
    """
    return {
        'id': _int_or_zero(row.get('id')),
        'from_uid': str(row.get('from_uid') or ''),
        'to_uid': str(row.get('to_uid') or ''),
        'body': str(row.get('body') or ''),
        'created_at': _int_or_zero(row.get('created_at')),
        # ⚠️ `stamp` 必须**现算**（`dm.stamp` 是唯一实现）：库里只存 `created_at`
        #    （契约 §2 的表结构就是这两列），把 stamp 也存一列就是同一事实两份真相，
        #    而"跨年"与否还取决于**看的人此刻是哪一年**，本来就不该落库。
        'stamp': dm.stamp(row.get('created_at')),
        'mine': str(row.get('from_uid') or '') == str(me_uid or ''),
    }


def _dm_target(payload_or_args, uid):
    """私聊的统一前置：登录已验 → 找目标 → **必须是好友**。

    返回 `(target_user, 错误响应)`，与 `_target_user` 同形，便于调用方一行早退。

    三条拒绝（契约 §4 的错误码）：
      · 404 账号不存在（`_target_user` 已给，且带中文原因）；
      · 400 不能和自己私聊（自己给自己发消息没有意义，而且未读计数会自己给自己涨）；
      · 403 **不是好友 / 已被拉黑** —— 用 `get_friend_relation` 判，只有 `'friends'` 放行。

    ⚠️ `blocked_me` / `blocked_by_me` 一律 403，且**文案不区分方向**：
    告诉客户端"你被我拉黑了"等于把拉黑这件事回传给被拉黑的人（他会换号继续骚扰），
    "是我拉黑的对方"也不该由这个接口泄露。所以两边给同一句话
    （与 `api_friend_request` 里那句 `'暂时无法向该玩家发送好友申请'` 同一口径）。
    """
    target, err = _target_user(payload_or_args)
    if err:
        return None, err
    other = str(target['id'])
    if other == str(uid):
        return None, (jsonify({'status': 'error', 'error': '不能和自己私聊'}), 400)
    if db.get_friend_relation(uid, other) != 'friends':
        return None, (jsonify({'status': 'error', 'error': '你们还不是好友，无法私聊'}), 403)
    return target, None


@app.route('/api/friends/messages', methods=['GET'])
def api_friend_messages():
    """取与某人的一段会话（**两个方向合成同一条会话**，最新的在后）。

    `?before=<id>` 往更早翻页（游标分页，契约 §1）。
    响应：`{'status':'ok','has_more':bool,'messages':[...]}`。
    """
    uid, err = _friends_require_login()
    if err:
        return err

    target, err = _dm_target(request.args, uid)
    if err:
        return err

    try:
        limit = int(request.args.get('limit') or DM_PAGE_SIZE)
    except (TypeError, ValueError):
        limit = DM_PAGE_SIZE
    limit = max(1, min(limit, DM_MAX_PAGE_SIZE))

    try:
        before_id = request.args.get('before')
        before_id = int(before_id) if before_id not in (None, '') else None
    except (TypeError, ValueError):
        # 坏游标当"没给游标"（= 取最新一页），不要 400：前端拼错 URL 时
        # 用户看到的是"最新消息"而不是一个报错框，代价只是多点一次「加载更早」。
        before_id = None

    rows = db.list_friend_messages(uid, target['id'], limit, before_id)
    messages = [_public_dm_message(r, uid) for r in (rows or [])]

    # `has_more` 由**库**回答"还有没有更早的"，不是"这页取满了就推断还有"：
    # 后者在"恰好剩 limit 条"时会给出 True，前端于是显示一个点了没反应的按钮
    # （本项目栽过"看着有、其实永远不触发"的同形状）。
    # 游标取本页**最早那条**的 id：没有更早的（本页为空）时给 0，问题自然为假。
    oldest = messages[0]['id'] if messages else 0
    has_more = bool(oldest) and bool(db.has_more_friend_messages(uid, target['id'], oldest))

    return jsonify({'status': 'ok', 'has_more': has_more, 'messages': messages})


@app.route('/api/friends/messages', methods=['POST'])
def api_friend_message_send():
    """发一条私聊。

    401 未登录 ｜ 404 账号不存在 ｜ 403 不是好友或已被拉黑 ｜
    400 空消息 / 超长（点名"最多 300 字"）｜ 429 发得太频繁
    200 `{'status':'ok','message':{…}}`

    ⚠️ 正文归一化**只做一次**（`dm.normalize_body`）：先归一化再判长度。
    顺序反了的话，`'  '`（纯空白 + 一个换行）会先通过长度检查、归一化后成空串，
    库里就多了一条"空白消息"（前端渲染成一行空气）。同理，
    `'\n' * 400` 归一化后是空串 → 400「消息不能为空」，而不是"超长"。
    """
    uid, err = _friends_require_login()
    if err:
        return err

    payload = _get_json_payload() or {}
    target, err = _dm_target(payload, uid)
    if err:
        return err

    body = dm.normalize_body(payload.get('body'))
    reason = dm.body_error(body)
    if reason:
        return jsonify({'status': 'error', 'error': reason}), 400

    # 频率：数**最近一分钟我真的发出去的**条数（`db` 里的真实行数就是账本）。
    # ⚠️ 为什么不用进程级全局 dict：那份账会把所有人串成一条队列（甲刷屏、乙被 429），
    #    多 worker 下还各存一份、与服务事实对不上。用库里的行数则天然按发送者隔离、
    #    重启不丢，且与"消息真的落库了"是同一件事 —— 被拒的那条不占配额。
    since = int(time.time()) - dm.RATE_WINDOW_SECONDS
    if int(db.count_friend_messages_since(uid, since) or 0) >= dm.PER_MINUTE:
        return jsonify({'status': 'error',
                        'error': f'发得太频繁了，每分钟最多 {dm.PER_MINUTE} 条'}), 429

    row = db.add_friend_message(uid, target['id'], body)
    if not row:
        # 写失败只回 500，**不乐观地回 ok** —— 回 ok 的话前端会拿一条库里
        # 根本不存在的消息渲染出来，刷新就消失（"接口说成功、其实什么都没发生"）。
        return jsonify({'status': 'error', 'error': '发送失败，请稍后重试'}), 500

    message = _public_dm_message(row, uid)

    # 推给收件人的**每一张标签页**（多标签页每张都要收到）。走注入的
    # `server.push_friend_message`（**推送只有一份实现**，见本文件顶部那段注释）。
    # ⚠️ 与"邀战"不同：推送失败**照样回 ok** —— 消息已经落库，对方下次打开会话
    #    就拉到了。回 error 会让发送方以为没发出去、然后重发一遍（重复消息）。
    # ⚠️ payload 里额外带 `from_username` / `from_avatar`（契约 §4 的 socket 形状），
    #    让没打开会话的收件人也能直接弹一句"小红：在吗"。
    # ⚠️ 用 `dm.push_payload` **裁成推送形状**再交出去：接口自己那份 `message`
    #    带 `mine` / `to_uid`（发送方视角的字段），整份推过去等于把视角字段漏给
    #    收件人 —— 而且以后往接口 dict 里加内部键就会顺手发出去。字段清单只有
    #    `dm.PUSH_PAYLOAD_KEYS` 一份（`server.push_friend_message` 也走同一个函数）。
    username, avatar = _my_friend_identity(uid)
    push_payload = dict(message, from_username=username, from_avatar=avatar)
    _push_friend_event('push_friend_message', target['id'], dm.push_payload(push_payload))

    return jsonify({'status': 'ok', 'message': message})


@app.route('/api/friends/messages/read', methods=['POST'])
def api_friend_messages_read():
    """把**某人发给我的**全部未读标为已读，返回本次标记的条数。

    响应：`{'status':'ok','read':N}`。幂等：重复调用返回 0。
    ⚠️ 这个接口**与入口红点无关**：红点仍是"待确认好友申请数"（契约 §1），
    未读只在好友行内（`unread`）与 `counts.unread_total` 体现。
    """
    uid, err = _friends_require_login()
    if err:
        return err

    payload = _get_json_payload() or {}
    target, err = _dm_target(payload, uid)
    if err:
        return err

    marked = db.mark_friend_messages_read(uid, target['id'])
    return jsonify({'status': 'ok', 'read': _int_or_zero(marked)})


# ===========================================================================
# 反作弊管理后台（2026-09-20）
#
# 定位：**只给你（站长）用**的运营面板。可以看全服嫌疑度、逐个玩家查战绩与违规记录、
#       手动解封/加封。
#
# ⚠️ 三重安全约束（缺一条都是事故）：
#   ① **管理员白名单**：复用既有的 `DEBUG_ADMIN_USER_IDS`（由 server.py 注入），
#      **不新造一套管理员概念** —— 两套管理员概念必然漂移（本项目老病根）。
#   ② **写操作必须带 actor**：每次干预都记"谁做的"，可审计。
#   ③ **绝不泄露给普通玩家**：所有接口都先过 `_admin_required()`，
#      非管理员一律 403，且**不区分"不存在"与"无权限"**（不泄露账号是否存在）。
# ===========================================================================
def _admin_backend(name):
    """取 server.py 注入的后端能力（按名字现取，与好友那套同一机制）。

    ⚠️ `api.py` **不能 import server**（`python server.py` 时模块名是 `__main__`，
    import 会再执行一遍成另一个模块对象 —— 见 CLAUDE.md 第 19 条）。
    """
    return _friend_backend(name)


def _admin_allowed_uids() -> set:
    """管理员白名单（server 注入；取不到就当空 = 谁都不是管理员）。"""
    try:
        fn = _admin_backend('_admin_user_ids_for_api')
        if callable(fn):
            return set(fn() or ())
    except Exception:
        pass
    return set()


def _admin_required():
    """返回 `(uid, None)` 或 `(None, 响应)`。**唯一的管理员门禁入口**。"""
    uid = session.get('user_id')
    if not uid:
        return None, (jsonify({'success': False, 'error': '未登录'}), 401)
    allowed = _admin_allowed_uids()
    if not allowed or str(uid) not in {str(x) for x in allowed}:
        # ⚠️ 白名单为空 = **谁都不是管理员**（默认安全）。
        #    不能写成"空就放行" —— 那等于线上没有管理员配置时门户大开。
        return None, (jsonify({'success': False, 'error': '无权访问'}), 403)
    return uid, None


def _suspicion_matches_for_api(uid: str) -> list:
    """取某人的对局嫌疑度明细并折算 age_days（与 server 侧同口径）。

    ⚠️ 时间必须**在调用时**算，不能存库（见 server._suspicion_matches_for 的注释）。
    """
    try:
        rows = db.get_match_suspicion(uid)
    except Exception:
        return []
    now = time.time()
    out = []
    for r in rows or ():
        try:
            age = max(0.0, (now - float(r.get('created_at') or now)) / 86400.0)
        except (TypeError, ValueError):
            age = 0.0
        out.append({'score': r.get('score'), 'age_days': age})
    return out


def _admin_player_report(uid: str) -> dict:
    """组装一个玩家的完整反作弊报告（嫌疑度 + 封禁 + 战绩 + 违规记录）。"""
    user = db.get_user(uid=uid) or {}
    username = user.get('username') or '(已删除)'
    matches = _suspicion_matches_for_api(uid)
    override = db.get_anticheat_override(uid)
    report = suspicion.build_report(uid, matches, override=override, username=username)

    # 违规记录：可疑对局明细（只有 ≥record 档才有）
    flags = []
    try:
        for f in db.get_anticheat_flags(500):
            if f.get('match_id'):
                flags.append({
                    'match_id': f.get('match_id'),
                    'rule': f.get('rule'),
                    'severity': f.get('severity'),
                    'detail': f.get('detail'),
                    'created_at': f.get('created_at'),
                })
    except Exception:
        pass

    # 干预历史（谁在什么时候解过封）
    try:
        history = db.get_anticheat_override_history(uid, 50)
    except Exception:
        history = []

    # 战绩（复用既有口径：wins/losses + 排位）
    wins = int(user.get('wins') or 0)
    losses = int(user.get('losses') or 0)
    rank_row = {}
    try:
        rank_row = db.get_user_rank_row(uid) or {}
    except Exception:
        rank_row = {}

    report['stats'] = {
        'wins': wins,
        'losses': losses,
        'win_rate': round(wins / (wins + losses), 3) if (wins + losses) else 0.0,
        'rank_points': int(rank_row.get('points') or 0),
        'ranked_wins': int(rank_row.get('ranked_wins') or 0),
        'ranked_losses': int(rank_row.get('ranked_losses') or 0),
    }
    # 只看**属于这个人**的违规局（`anticheat_flags` 是按对局存的，没有 user_id）
    report['flagged_matches'] = [f for f in flags
                                 if f.get('match_id') in
                                 {m.get('match_id') for m in _match_ids_for(uid)}][:100]
    report['override_history'] = [
        {'level': h.get('level'), 'cleared': bool(h.get('cleared')),
         'reason': h.get('reason'), 'actor': h.get('actor'),
         'created_at': h.get('created_at')}
        for h in (history or [])
    ]
    return report


def _match_ids_for(uid: str) -> list:
    """该用户参与过的对局 id（用于把违规记录过滤到本人）。"""
    try:
        rows = db.get_match_suspicion(uid, 2000)
    except Exception:
        return []
    out = []
    for r in rows or ():
        mid = str(r.get('match_id') or '')
        # `match_suspicion.match_id` 存的是 `'{match_id}:{user_id}'`（表主键去重口径）
        out.append({'match_id': mid.split(':', 1)[0] if ':' in mid else mid})
    return out


@app.route('/api/admin/suspicion', methods=['GET'])
def admin_suspicion_list():
    """全服嫌疑度列表（按累计嫌疑度降序）。

    查询参数：`?limit=200`（1~2000）
    响应：`{'success':True,'players':[...],'levels':{...}}`
    """
    _, err = _admin_required()
    if err:
        return err

    try:
        limit = int(request.args.get('limit') or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 2000))

    totals = db.get_all_suspicion_totals(limit)
    players = []
    for row in totals or ():
        uid = row.get('user_id')
        if not uid:
            continue
        try:
            matches = _suspicion_matches_for_api(uid)
            override = db.get_anticheat_override(uid)
            rep = suspicion.build_report(uid, matches, override=override,
                                         username=row.get('username'))
            players.append(rep)
        except Exception:
            continue

    # 只看有嫌疑的（0 分的不必占据列表），但保留全量计数供参考
    players.sort(key=lambda p: p.get('suspicion') or 0, reverse=True)
    return jsonify({
        'success': True,
        'players': players,
        'total': len(totals or ()),
        'levels': {str(k): v for k, v in suspicion.LEVEL_NAMES.items()},
        'thresholds': {str(lv): th for th, lv in suspicion.LEVEL_THRESHOLDS},
    })


@app.route('/api/admin/player/<uid>', methods=['GET'])
def admin_player_detail(uid):
    """单个玩家的完整报告：嫌疑度 / 封禁等级 / 战绩 / 违规记录 / 干预历史。

    ★ 这就是"点头像快速查询"要调的那个接口。
    """
    _, err = _admin_required()
    if err:
        return err
    if not uid:
        return jsonify({'success': False, 'error': '缺少用户 ID'}), 400
    try:
        return jsonify({'success': True, 'player': _admin_player_report(uid)})
    except Exception as e:
        return jsonify({'success': False, 'error': f'读取失败: {e}'}), 500


@app.route('/api/admin/player/<uid>/override', methods=['POST'])
def admin_player_override(uid):
    """管理员手动干预：解封 / 指定等级。

    body：`{'cleared': true, 'reason': '误判'}` 或 `{'level': 2, 'reason': '确认刷分'}`
    ⚠️ 每次干预**追加**一条记录（不覆盖历史），`actor` 由服务端填当前管理员 uid。
    """
    actor, err = _admin_required()
    if err:
        return err
    if not uid:
        return jsonify({'success': False, 'error': '缺少用户 ID'}), 400

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form.to_dict() if request.form else None
    if not isinstance(payload, dict):
        return jsonify({'success': False, 'error': '请求体必须是 JSON 对象'}), 400

    cleared = bool(payload.get('cleared'))
    level = payload.get('level')
    reason = str(payload.get('reason') or '').strip()[:500]

    if not cleared:
        if level is None:
            return jsonify({'success': False, 'error': '必须给 cleared 或 level'}), 400
        try:
            level = int(level)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'level 必须是整数'}), 400
        if not (0 <= level <= suspicion.LEVEL_NO_ROOM):
            return jsonify({'success': False,
                            'error': f'level 必须在 0~{suspicion.LEVEL_NO_ROOM} 之间'}), 400

    ok = db.set_anticheat_override(uid, level=level, cleared=cleared,
                                   reason=reason, actor=str(actor))
    if not ok:
        return jsonify({'success': False, 'error': '写入失败'}), 500

    # 返回干预后的最新状态，前端不必再拉一次
    try:
        after = _admin_player_report(uid)
    except Exception:
        after = None
    return jsonify({'success': True, 'player': after})


@app.route('/api/admin/player/<uid>/history', methods=['GET'])
def admin_player_history(uid):
    """某玩家的干预历史（审计用）。"""
    _, err = _admin_required()
    if err:
        return err
    try:
        rows = db.get_anticheat_override_history(uid, 100)
    except Exception:
        rows = []
    return jsonify({'success': True, 'history': [
        {'level': h.get('level'), 'cleared': bool(h.get('cleared')),
         'reason': h.get('reason'), 'actor': h.get('actor'),
         'created_at': h.get('created_at')} for h in (rows or [])]})


@app.route('/api/admin/me', methods=['GET'])
def admin_me():
    """当前登录者是不是管理员（前端据此显示/隐藏入口）。"""
    uid = session.get('user_id')
    allowed = _admin_allowed_uids()
    is_admin = bool(uid) and str(uid) in {str(x) for x in allowed}
    return jsonify({'success': True, 'is_admin': is_admin})




