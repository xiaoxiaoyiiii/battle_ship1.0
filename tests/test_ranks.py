# -*- coding: utf-8 -*-
r"""段位系统（段位批 A 票）回归测试：`ranks.py` 段位数学 + `db.py` 段位存取 + 名片开关。

分四块：
  1. `ranks.py` 的段位表 / 分数换算 / 视图文案（纯函数，不碰库）
  2. 大舰长晋升的三个条件（含"船长池不足 50 人不产生大舰长"这条护栏）
  3. `db.user_rank` 的读写：0 分封底、加减分、榜序、名次、船长池
  4. `profile_spec` 的 10 字段契约（多了 `show_rank`）与段位解锁的外观

⚠️ 跑测试必须重定向临时目录（本机 `%LOCALAPPDATA%\Temp\pytest-of-Administrator`
的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP; python -m pytest tests/ -q
"""
import json
import re
import uuid

import pytest

import api
import db as db_module
import profile_spec
import ranks


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------
def _uid():
    """建一个真账号（`user_rank` 只按 user_id 关联，但建号能让 join 类断言也能用）。"""
    username = 'rk' + uuid.uuid4().hex[:10]
    uid = db_module.create_user(username, 'x')
    assert uid, '建号失败'
    return uid, username


# ===========================================================================
# 1. 段位表与分数换算
# ===========================================================================


















# ===========================================================================
# 2. 大舰长晋升
# ===========================================================================




def test_admiral_blocked_when_pool_too_small():
    """⚠️ 护栏：船长池不足 50 人时不产生大舰长。

    没有这条，今天这个玩家基数下**人人都是大舰长**（池子里就 3 个人，
    人人排名 ≤ 50）。作者要的是"最高段位"，不是"注册即送"。
    """
    ok, why = ranks.can_promote_to_admiral(2400, 1, ranks.ADMIRAL_MIN_CAPTAINS - 1)
    assert ok is False and '50' in why
    assert ranks.ADMIRAL_MIN_CAPTAINS == 50
    assert ranks.ADMIRAL_STICKY is False      # 默认动态：条件不满足会掉回船长










# ===========================================================================
# 3. db.user_rank
# ===========================================================================




























# ===========================================================================
# 4. profile_spec：11 字段契约 + 段位解锁外观
# ===========================================================================


def _full_payload(**over):
    body = {'title_id': 'rookie', 'tags': [], 'status_text': '', 'frame_id': 'none',
            'card_bg_id': 'deep', 'show_stats': 1, 'show_fav_cards': 1,
            'show_history': 0, 'show_guestbook': 1, 'show_rank': 1, 'friend_requests_open': 1}
    body.update(over)
    return body






def test_validate_rejects_locked_rank_cosmetic():
    """段位没到就选不了 —— **服务端裁决**（前端灰掉不算数）。"""
    _, errors = profile_spec.validate_payload(
        _full_payload(title_id='sea_emperor'), {'wins': 0, 'rank_tier': 3})
    assert errors and '未解锁的称号' in errors[0]
    _, errors = profile_spec.validate_payload(
        _full_payload(frame_id='king_aura'), {'wins': 0, 'rank_tier': 7})
    assert errors and '未解锁的头像框' in errors[0]
    fields, errors = profile_spec.validate_payload(
        _full_payload(frame_id='king_aura'), {'wins': 0, 'rank_tier': 8})
    assert errors == [] and fields['frame_id'] == 'king_aura'












# ===========================================================================
# 5. 前端契约：图标文件与脚本加载顺序
# ===========================================================================
def _static_text(name):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'static', name), encoding='utf-8') as f:
        return f.read()




def _icon_primitive_counts():
    """数每个段位图标画了几个图形（把 STAR 变量展开后再数）。

    ⚠️ 不能只数字面量：三副~大副的星是一个 `STAR` 变量引用，
    直接正则会把"星 + 一道杠"数成 1 个图形，于是"越高级越复杂"这条
    会被误判成失败（第一版就是这么假的）。
    """
    js = _static_text('rank_icons.js')
    star = re.search(r"var STAR = '([^']+)'", js)
    assert star, '找不到 STAR 常量'
    body = js.split('var RANK_ICONS = {', 1)[1].split('\n    };', 1)[0]
    counts = {}
    for chunk in re.split(r'\n\s{8}(?=\w+:)', body):
        m = re.match(r'\s*(\w+):', chunk)
        if not m or m.group(1) not in [t['id'] for t in ranks.TIERS]:
            continue
        expanded = chunk.replace('STAR', star.group(1))
        counts[m.group(1)] = len(re.findall(r'<(?:path|circle|rect|g)\b', expanded))
    return counts








# ===========================================================================
# 6. 段位奖励的"实装"守卫（2026-09-18 补：这两条各自对应一个真 bug）
# ===========================================================================
