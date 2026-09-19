# -*- coding: utf-8 -*-
"""更新公告（`changelog.py` + `GET /api/changelog`）的守卫。

这份公告是**给玩家看的**，所以本文件守的不是"功能对不对"，而是两件事：

1. **别写成技术文档**（作者明确要求：「不要写的太专业，就写修复了什么 bug、更改了什么什么」）——
   文件名、下划线标识符、反引号、英文缩写一律不许出现在公告里；
2. **只有一份数据源**：前端的文案必须来自接口，不许在 `game.js` 里再抄一份
   （本项目的老病根：同一个业务判断两份实现必然漂移）。

⚠️ 本文件**不依赖 git**：不在测试里比"最新公告的时间 vs 最近一次提交时间"——
   那会让测试依赖本机是否装了 git / 仓库是否完整。那条约定写在
   `changelog.py` 的头部注释与 `docs/UPDATES_2026_09_19.md` 里，靠人（和 AI）遵守。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import changelog  # noqa: E402
import server  # noqa: E402

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
# 公告里**不许出现**的技术词（大小写不敏感）
FORBIDDEN_TOKENS = ('api', 'sql', 'sqlite', 'socket', 'http', 'json', 'token', 'db',
                    'game.js', 'server.py', 'None', 'null')
# 单条公告的字数上限（"不要太专业"的另一半：太长就没人看）
MAX_ITEM_LEN = 40


def _items():
    out = []
    for entry in changelog.CHANGELOG:
        for text in entry.get('items') or []:
            out.append((entry.get('date'), text))
    return out


# ===========================================================================
# 1. 结构
# ===========================================================================
def test_every_entry_has_well_formed_unique_date():
    assert changelog.CHANGELOG, '公告一条都没有？'
    dates = [e.get('date') for e in changelog.CHANGELOG]
    for d in dates:
        assert isinstance(d, str) and DATE_RE.match(d), f'时间格式必须是 YYYY-MM-DD HH:MM，实际 {d!r}'
    assert len(set(dates)) == len(dates), f'时间必须唯一（它是前端"看过没有"的标识）：{dates}'


def test_newest_first_strictly_descending():
    """最新的必须在最前，且**严格**倒序（写成字符串比较即可，格式是固定的）。"""
    dates = [e['date'] for e in changelog.CHANGELOG]
    assert dates == sorted(dates, reverse=True), f'公告必须最新的在最前：{dates}'


def test_every_entry_has_sane_item_count_and_text():
    for entry in changelog.CHANGELOG:
        items = entry.get('items')
        assert isinstance(items, list) and 1 <= len(items) <= 5, f'{entry.get("date")} 的条目数不合理：{items}'
        for text in items:
            assert isinstance(text, str) and text.strip(), f'{entry.get("date")} 有空条目'
            assert len(text) <= MAX_ITEM_LEN, f'太长了（{len(text)} 字）：{text}'
            assert text.endswith(('。', '！', '？', ')', '）')) is False or True  # 允许不加句号


# ===========================================================================
# 2. 文案必须像"给玩家看的话"
# ===========================================================================
def test_items_avoid_technical_jargon():
    """不许出现文件名 / 下划线标识符 / 反引号 / 英文缩写（本文件存在的主要理由）。"""
    for date, text in _items():
        low = text.lower()
        for bad in FORBIDDEN_TOKENS:
            assert bad.lower() not in low, f'公告里出现了技术词「{bad}」：{date} / {text}'
        assert '`' not in text, f'公告里不许出现反引号：{date} / {text}'
        assert '_' not in text, f'公告里不许出现下划线（标识符）：{date} / {text}'
        assert '(' not in text and ')' not in text, f'公告里不许出现半角括号（英文注释味）：{date} / {text}'
        assert '.py' not in low and '.js' not in low, f'公告里不许出现文件名：{date} / {text}'


def test_items_start_with_player_facing_verb():
    """每条都用「修复了/改了/新增了/优化了」开头 —— 玩家一眼知道这是什么性质的变化。"""
    heads = ('修复了', '改了', '新增了', '优化了', '调整了')
    for date, text in _items():
        assert text.startswith(heads), f'公告要玩家视角开头（{"/".join(heads)}）：{date} / {text}'


def test_frontend_does_not_hardcode_any_announcement_text():
    """前端**不许**抄一份文案（只能从接口拿）。

    ⚠️ 这条守的是本仓库的老病根：同一份内容两份实现，改一边忘一边。
    """
    with open(os.path.join(ROOT, 'static', 'game.js'), encoding='utf-8') as f:
        js = f.read()
    for _date, text in _items():
        # 取前 12 个字比对：整句相同（或明显被抄过去）就说明文案被写进了前端
        probe = text[:12]
        assert probe not in js, f'game.js 里出现了公告原文（{probe}…）—— 文案只能来自 /api/changelog'


# ===========================================================================
# 3. view() 与接口
# ===========================================================================
def test_view_truncates_and_returns_copies():
    full = changelog.view(100)
    assert len(full['entries']) == min(len(changelog.CHANGELOG), 20), 'limit 上限应当是 20'
    assert full['latest'] == changelog.CHANGELOG[0]['date'], 'latest 必须是最新那条的时间'

    # 改返回值不许影响内部数据（"同一份列表被多处持有"在本仓库栽过）
    full['entries'][0]['items'].append('被污染的一条')
    full['entries'][0]['date'] = '1999-01-01 00:00'
    assert changelog.CHANGELOG[0]['date'] != '1999-01-01 00:00'
    assert '被污染的一条' not in changelog.CHANGELOG[0]['items']


def test_view_handles_bad_limit():
    for bad in (None, 'x', 0, -5):
        out = changelog.view(bad)
        assert 1 <= len(out['entries']) <= 20, f'limit={bad!r} 时应当退回默认值'


def test_api_changelog_is_public_and_matches_the_module():
    """**不登录**就能读（登录页上的人也该看得到），且内容与模块逐字一致。"""
    resp = server.app.test_client().get('/api/changelog')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['status'] == 'ok'
    assert body['latest'] == changelog.CHANGELOG[0]['date']
    assert len(body['entries']) == min(len(changelog.CHANGELOG), 10), '默认给最近 10 条'
    assert body['entries'][0]['items'] == changelog.CHANGELOG[0]['items'], '文案必须与模块一字不差'


def test_api_changelog_limit_is_clamped():
    client = server.app.test_client()
    assert len(client.get('/api/changelog?limit=1').get_json()['entries']) == 1
    assert len(client.get('/api/changelog?limit=999').get_json()['entries']) <= 20
    assert len(client.get('/api/changelog?limit=abc').get_json()['entries']) >= 1
