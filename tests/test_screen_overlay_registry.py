"""屏/浮层清单漂移的回归测试（2026-09-19）。

背景——三个真实缺陷，都属于同一个形状：**同一份清单被手抄了多份，某一份漏项**。
它们都**不报错**，只是点了没反应：

1. `#lobby-screen` 被加上 `hidden` 后再也没人摘掉。`.hidden{display:none !important}`
   压过 `.screen.active` → 进过一局之后，点「游戏大厅」能加上 active，页面却一片空白。
2. `game_state` / `reset_gameboard` 里各手抄一份"隐藏所有屏"的清单，两份都漏了
   `lobbyScreen` / `leaderboardScreen` → 在大厅点人机对战会两个屏同时可见。
3. `closeOverlaysExcept` 的清单只写 6 个 id，而 index.html 有 9 个 `.modal-overlay`
   → 漏掉的登录/注册/弃牌堆浮层不参与互斥，会被后开的面板压住。

根治方式：清单只留一份（`hideAllScreens()` / 按 `.modal-overlay` 类名取）。
下面这些用例锁的就是"不许再手抄"。
"""
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(BASE, rel), encoding='utf-8') as f:
        return f.read()


JS = _read('static/game.js')
HTML = _read('templates/index.html')


def _screen_ids():
    """index.html 里所有 .screen 元素的 id。"""
    return re.findall(r'id="([a-z0-9-]+-screen)"[^>]*class="screen', HTML)


def _screen_var(sid):
    """lobby-screen -> lobbyScreen。"""
    parts = sid.replace('-screen', '').split('-')
    return parts[0] + ''.join(p.capitalize() for p in parts[1:]) + 'Screen'


# 1. 一个屏都不许被加上 hidden（单向锁死：全仓没有任何地方摘掉它）
def test_no_screen_ever_gets_hidden_class():
    ids = _screen_ids()
    assert ids, 'index.html 里没找到 .screen 元素，测试本身失效'
    for sid in ids:
        var = _screen_var(sid)
        pat = re.escape(var) + r"\.classList\.add\(['\"]hidden['\"]\)"
        assert not re.search(pat, JS), (
            '屏 %s 被加上了 hidden —— 它永远不会被摘掉，会把该屏永久锁成空白' % sid)
    # 也不许用 getElementById(...).classList.add('hidden') 绕过去
    loose = (r"getElementById\(['\"]([a-z0-9-]+-screen)['\"]\)"
             r"[^\n]{0,60}classList\.add\(['\"]hidden")
    assert not re.search(loose, JS), '有屏通过 getElementById 被加上了 hidden'


# 2. "隐藏所有屏"只能有一份实现，且调用点不许再手抄
def test_only_one_place_hides_all_screens():
    assert 'function hideAllScreens' in JS, '缺少唯一的 hideAllScreens()'
    assert re.search(r'function switchScreen\(screen\) \{\s*hideAllScreens\(\)', JS), (
        'switchScreen 必须先 hideAllScreens()，否则屏之间不互斥')


def test_manual_screen_clearing_lists_are_gone():
    # 连续 3 行以上裸写 classList.remove('active') = 又手抄了一份
    pat = (r"(?:^|\n)"
           r"(?:[ \t]*\w+Screen\.classList\.remove\('active'\);[ \t]*\n){3,}")
    runs = re.findall(pat, JS)
    assert not runs, '发现了手抄的隐藏屏清单 %d 处；请改用 hideAllScreens()' % len(runs)


# 3. 浮层互斥必须覆盖 HTML 里全部 .modal-overlay，不能再手抄 id 清单
def test_overlay_mutex_covers_every_modal_overlay():
    in_html = set(re.findall(r'id="([a-z0-9-]+)"[^>]*class="modal-overlay', HTML))
    assert len(in_html) >= 9, 'index.html 里 .modal-overlay 数量异常：%d' % len(in_html)
    body = JS.split('function closeOverlaysExcept')[1].split('window.closeOverlaysExcept')[0]
    assert "querySelectorAll('.modal-overlay')" in body, (
        'closeOverlaysExcept 应按类名取，而不是手抄 id 清单')
    assert 'const ids = [' not in body, '又出现了手抄的 id 数组'


def test_overlay_mutex_has_no_stale_hardcoded_pair():
    body = JS.split('function closeOverlaysExcept')[1].split('window.closeOverlaysExcept')[0]
    assert 'opponent-stats-modal' not in body, '旧的硬编码清单还在'
