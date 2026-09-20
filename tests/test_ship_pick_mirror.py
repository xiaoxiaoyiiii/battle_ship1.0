# -*- coding: utf-8 -*-
"""前端「选船优先级」镜像表必须与服务端逐项一致。

`static/game.js` 里的三张表是 server.py 的**只读镜像**，用途只有两个：
提前把被挡的卡置灰、把 reason 翻成中文名。真正的放行/拒绝一律由服务端裁决
（`_ship_pick_blocked_reason`）。

⚠️ 但"只读镜像"照样会漂移 —— 实测：命运骰子只在服务端 `_SHIP_PICK_CARDS` /
`SHIP_PICK_PRIORITY` 登记了，前端 `SHIP_PICK_CARD_NAMES` 漏了。
后果是**有待选时命运骰子不置灰**，玩家点下去才被服务端拒。
服务端裁决仍然正确 → 不报任何错 → 只能靠人眼发现（CLAUDE.md 教训 #1）。

所以把镜像钉死：新增选船类效果时，改一边不改另一边**必须红**。
"""
import io
import os
import re

import server

GAME_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'game.js')

# `key: 12` / `key: 'value'` / `'中文键': 'value'`
_ENTRY = re.compile(
    r"""^\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_$][\w$]*))\s*:\s*('([^']*)'|-?\d+)\s*,?\s*$""",
    re.M)


def _game_js():
    with io.open(GAME_JS, encoding='utf-8') as f:
        return f.read()


def _js_object(src, name):
    """取 `const NAME = { ... };` 的键值对；值为引号串时去掉引号，数字转 int。"""
    m = re.search(r'const\s+' + re.escape(name) + r'\s*=\s*\{(.*?)\}\s*;', src, re.S)
    assert m, 'game.js 里找不到 `const %s = { ... };`' % name
    out = {}
    for km in _ENTRY.finditer(m.group(1)):
        key = km.group(1) or km.group(2) or km.group(3)
        raw = km.group(4)
        out[key] = km.group(5) if raw.startswith("'") else int(raw)
    assert out, 'game.js 的 %s 解析为空（格式变了？）' % name
    return out


def test_card_name_to_reason_matches_server():
    """卡名 → reason 两张表必须完全相同。"""
    js = _js_object(_game_js(), 'SHIP_PICK_CARD_NAMES')
    py = dict(server._SHIP_PICK_CARDS)
    assert js == py, (
        '前端 SHIP_PICK_CARD_NAMES 与服务端 _SHIP_PICK_CARDS 不一致\n'
        '  只在服务端: %s\n  只在前端:   %s\n  值不同:     %s' % (
            sorted(set(py) - set(js)), sorted(set(js) - set(py)),
            {k: (js[k], py[k]) for k in set(js) & set(py) if js[k] != py[k]}))


def test_priorities_match_server_for_every_card_reason():
    """每张「打出去会触发选船」的卡，它的 reason 优先级两边必须一致。"""
    js = _js_object(_game_js(), 'SHIP_PICK_PRIORITIES')
    py = dict(server.SHIP_PICK_PRIORITY)
    bad = {}
    for reason in set(server._SHIP_PICK_CARDS.values()):
        if js.get(reason) != py.get(reason):
            bad[reason] = {'frontend': js.get(reason), 'server': py.get(reason)}
    assert not bad, (
        '这些 reason 的优先级前端镜像与服务端不一致（前端漏登记会让卡不置灰）: %s' % bad)


def test_priority_tables_have_no_frontend_only_entries():
    """前端不许有服务端没有的 reason —— 那份判据会凭空虚高/虚低。"""
    js = _js_object(_game_js(), 'SHIP_PICK_PRIORITIES')
    py = dict(server.SHIP_PICK_PRIORITY)
    only_front = sorted(set(js) - set(py))
    assert not only_front, '前端多出服务端没有的 reason: %s' % only_front
    mismatch = {k: (js[k], py[k]) for k in set(js) & set(py) if js[k] != py[k]}
    assert not mismatch, '两边优先级数值不同: %s' % mismatch


def test_reason_labels_match_server():
    """reason → 中文名也必须一致，否则玩家看到的提示会漏名字。"""
    js = _js_object(_game_js(), 'SACRIFICE_LABELS')
    py = dict(server._SHIP_PICK_LABELS)
    assert js == py, (
        '前端 SACRIFICE_LABELS 与服务端 _SHIP_PICK_LABELS 不一致\n'
        '  只在服务端: %s\n  只在前端:   %s\n  值不同:     %s' % (
            sorted(set(py) - set(js)), sorted(set(js) - set(py)),
            {k: (js[k], py[k]) for k in set(js) & set(py) if js[k] != py[k]}))


def test_every_playable_card_is_documented_in_magic_cards():
    """能触发选船的卡必须真的存在于卡表里（防止登记了不存在的卡名）。"""
    import json
    path = os.path.join(os.path.dirname(GAME_JS), 'magic_card.json')
    with io.open(path, encoding='utf-8') as f:
        names = {c['name'] for c in json.load(f)}
    missing = sorted(set(server._SHIP_PICK_CARDS) - names)
    assert not missing, '这些卡名不在 magic_card.json 里: %s' % missing
