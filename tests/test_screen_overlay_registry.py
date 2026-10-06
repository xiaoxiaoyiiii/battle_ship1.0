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


# 2. "隐藏所有屏"只能有一份实现，且调用点不许再手抄




# 3. 浮层互斥必须覆盖 HTML 里全部 .modal-overlay，不能再手抄 id 清单
