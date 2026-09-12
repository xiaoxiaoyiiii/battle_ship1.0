# -*- coding: utf-8 -*-
"""移动端自适应布局（紧凑模式）的回归测试。

背景（2026-09-12 实测）：对局界面原本是"桌面多浮窗"范式——日志、局内聊天、
卡牌预览三个 position:fixed 窗口盖在一条长文档上。压到手机上实测到：
  · 棋盘完全在首屏之外（320~430px 宽视口下可见比例 0%）
  · 日志窗 ∩ 魔法卡预览 = 273x181，聊天窗 ∩ 阶段卡 = 337x123
  · 两个半透明毛玻璃互相采样，截图里糊成一片
  · 手牌（#magic-system）被追加在 #game-screen 末尾，落在 y≈1577，够不着
  · 300x… 下滚到棋盘后 36/36 个格子被固定浮窗盖住

修复方式见 static/style.css 第 22 节 + static/adaptive_layout.js：
按【可用空间】而不是设备类型选布局，紧凑模式下改成一屏网格，
三个浮窗搬进 #aux-dock 三选一，棋盘尺寸由舞台反推。

这些断言保护的是这次修复的"前端契约"，改回去就会红。
端到端的不变量由 tools/ui_layout_check.mjs 在 6 个视口上验证
（棋盘零遮挡 / 零纵向滚动 / 面板零叠压 / 触摸目标 / 手牌够得着）。
"""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(BASE, rel), encoding='utf-8') as f:
        return f.read()


HTML = _read('templates/index.html')
CSS = _read('static/style.css')
JS = _read('static/game.js')
ADAPTIVE = _read('static/adaptive_layout.js')


# 1. 三个浮窗必须有一个共同的落点（面板槽），且三选一
def test_aux_dock_exists_with_three_panels():
    assert 'id="aux-dock"' in HTML
    for panel in ('card', 'log', 'chat'):
        assert 'data-dock-panel="%s"' % panel in HTML, panel
        assert 'data-dock-tab="%s"' % panel in HTML, panel
    # 三选一：同一时刻只有一个面板可见
    assert '#aux-dock[data-tab="card"] .dock-panel[data-dock-panel="card"]' in CSS
    assert '#aux-dock[data-tab="log"] .dock-panel[data-dock-panel="log"]' in CSS
    assert '#aux-dock[data-tab="chat"] .dock-panel[data-dock-panel="chat"]' in CSS
    # 收起时不占高度
    assert '#aux-dock[data-open="false"] .dock-body' in CSS


# 2. 紧凑布局只在对局界面生效——别把登录/大厅/排行榜也锁成 overflow:hidden
def test_compact_layout_scoped_to_game_screen():
    assert 'body.layout-compact.layout-ingame' in CSS
    assert "body.classList.toggle('layout-ingame'" in ADAPTIVE
    # 一屏网格：内容区是 grid 且高度锁死，页面本身不滚动
    assert 'grid-template-rows: auto auto minmax(0, 1fr) auto auto' in CSS
    assert 'height: var(--stage-vh, 100dvh)' in CSS


# 3. 搬进面板槽之后，原来的浮窗必须交出 position:fixed（否则仍会盖住棋盘）
def test_docked_panels_lose_position_fixed():
    assert '.dock-panel .log-container' in CSS
    assert '.dock-panel #in-game-chat-container' in CSS
    assert '.dock-panel #magic-card-preview' in CSS
    # 用 fixed 的 !important 覆盖内联 left/top（拖拽功能会写内联样式）
    assert 'position: static !important;' in CSS


# 4. 棋盘尺寸由舞台反推，且只锁宽度——同时锁高度会在舞台变矮时压成扁格子
def test_board_sized_from_stage_only_width_locked():
    assert '--board-size' in CSS
    assert 'width: var(--board-size, 240px)' in CSS
    assert 'height: auto;' in CSS
    assert "setProperty('--board-size'" in ADAPTIVE
    # 放不下两块时切成切换模式
    assert "mode = 'tabs'" in ADAPTIVE
    assert 'data-boards="tabs"' in CSS
    assert 'id="board-tabs"' in HTML


# 5. 手牌必须有归宿：常驻手牌条，或收进面板槽的卡牌页
def test_magic_system_is_placed_by_layout():
    assert "#magic-system" in ADAPTIVE
    assert "hand-empty" in ADAPTIVE
    assert 'body.layout-compact.layout-ingame #magic-system.hand-empty { display: none; }' in CSS
    # 横屏（矮屏）把常驻手牌条收进面板槽，高度让给棋盘
    assert 'grid-column: 1; grid-row: 1 / span 3;' in CSS


# 6. 触摸目标下限：紧凑模式下按钮不得低于 40px
def test_touch_targets_are_at_least_40px():
    assert 'min-height: 40px;      /* 触摸目标下限 */' in CSS or 'min-height: 40px' in CSS
    for sel in ('.phase-btn', '.surrender-btn', '.dock-tab', '.board-tab'):
        assert sel in CSS
    assert 'min-height: 40px' in CSS


# 7. 触屏上必须停用"拖动浮窗"（拖拽会与页面滚动抢手势，且会把宽屏坐标写坏）
def test_drag_disabled_in_compact():
    assert 'window.__adaptiveDragDisabled' in ADAPTIVE
    # 两个拖拽工厂都要在开始时退出
    assert JS.count('if (window.__adaptiveDragDisabled) return;') >= 2
    # resize 回写同样要跳过：紧凑模式下 rect 是流内位置，回写会污染宽屏坐标
    assert 'if (window.__adaptiveDragDisabled) return;\n        const r = el.getBoundingClientRect();' in JS


# 8. 面板槽展开时不得把棋盘饿死，且手牌要让位
def test_dock_open_keeps_board_usable():
    assert 'clampDockHeight' in ADAPTIVE
    assert "'--dock-max'" in ADAPTIVE
    assert 'max-height: var(--dock-max, 60dvh)' in CSS
    # 展开时手牌收进卡牌页，高度留给棋盘
    assert "dock.dataset.open === 'true'" in ADAPTIVE


# 9. 响应式原语：移动端安全区与动态视口单位
def test_mobile_viewport_primitives():
    assert 'env(safe-area-inset-bottom' in CSS
    assert '100dvh' in CSS
    assert 'visualViewport' in ADAPTIVE


# 10. 脚本必须在 game.js 之后加载（依赖它创建的 #magic-system / 头像角标）
def test_adaptive_script_loaded_after_game_js():
    assert HTML.index('/static/game.js') < HTML.index('/static/adaptive_layout.js')
