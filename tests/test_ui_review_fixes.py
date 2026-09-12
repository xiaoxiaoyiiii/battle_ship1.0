# -*- coding: utf-8 -*-
"""截图审查修复批的回归测试（2026-09-12 UI 审查）。

这些用例保护的是「前端契约」：HTML / CSS / JS 三处必须同时成立，
否则界面会退回审查中实测到的缺陷（空白状态条、阶段按钮错位、
两块棋盘一大一小、日志框一片空白、投降按钮错位……）。

每个断言都对应一次真实修复，改回去就会红。
"""
import os
import re
import struct

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(BASE, rel), encoding='utf-8') as f:
        return f.read()


HTML = _read('templates/index.html')
CSS = _read('static/style.css')
JS = _read('static/game.js')


# 1. 效果状态条：没有激活效果时不能渲染成一条空白横条
def test_effect_status_bar_hidden_by_default():
    assert 'id="effect-status-bar" class="effect-status-bar hidden"' in HTML
    # 全局 .hidden 必须是 display:none（否则容器仍会画出 padding + border）
    assert re.search(r'\.hidden\s*\{\s*display:\s*none', CSS)
    # JS 必须在初始化时同步容器显隐
    assert 'initEffectStatusBarSync' in JS
    assert 'initEffectStatusBarSync();' in JS
    # 两个子项默认隐藏
    assert 'class="status-item hidden" id="reinforcement-status"' in HTML
    assert 'class="status-item hidden" id="holy-heart-status"' in HTML


# 2. 阶段按钮：block 级按钮不受 text-align:center 影响，会贴左边
def test_phase_buttons_use_inline_block():
    assert "enterBattleBtn.style.display = 'inline-block';" in JS
    assert "enterEndBtn.style.display = 'inline-block';" in JS
    assert "endTurnBtn.style.display = 'inline-block';" in JS
    for name in ('enterBattleBtn', 'enterEndBtn', 'endTurnBtn'):
        assert "%s.style.display = 'block';" % name not in JS
    assert 'text-align: center;' in CSS.split('#turn-indicator {')[1].split('}')[0]


# 3. 两块棋盘必须同宽：flex 项要有确定的基准宽，否则各按内容自适应
def test_board_wrappers_have_fixed_flex_basis():
    m = re.search(r'\.board-wrapper\s*\{([^}]*)\}', CSS)
    assert m, '.board-wrapper 规则丢失'
    body = m.group(1)
    assert 'flex: 0 1 340px' in body
    assert '.board {' in CSS and 'max-width: 340px' in CSS


# 4. 日志空状态：开局没有记录时要有提示，出现日志后要移除提示
def test_game_log_empty_state():
    assert '.log-empty' in CSS
    assert 'GAME_LOG_EMPTY_HTML' in JS
    assert 'function ensureGameLogEmptyState' in JS
    assert "if (screen && screen.id === 'game-screen') ensureGameLogEmptyState();" in JS
    # addGameLog 必须先移除占位，否则占位会一直挂在日志顶部
    add_log = JS.split('function addGameLog(')[1].split('\n}')[0]
    assert "querySelector('.log-empty')" in add_log
    # clearGameLogs 不能只清空（否则日志框是一片空白）
    clear_logs = JS.split('function clearGameLogs(')[1].split('\n}')[0]
    assert 'GAME_LOG_EMPTY_HTML' in clear_logs


# 5. 投降按钮与「第N回合」标题的垂直居中对齐
def test_surrender_button_vertical_alignment():
    inner = CSS.split('.turn-indicator-inner {')[1].split('}')[0]
    assert 'align-items: center' in inner
    assert re.search(r'\.turn-indicator-inner h2\s*\{\s*margin-bottom:\s*0', CSS)


# 6. 玩家信息行文案（原来「6艘战舰剩余」断句悬空）
def test_player_info_ship_count_wording():
    assert '你：剩余 <span id="your-ships">6</span> 艘战舰' in HTML
    assert '对手：剩余 <span id="opponent-ships">6</span> 艘战舰' in HTML
    assert '艘战舰剩余' not in HTML


# 7. 中文界面统一全角冒号（半角冒号 + 空格是审查里点出的排版问题）
def test_game_screen_uses_fullwidth_colons():
    for text in ('当前阶段：', '当前回合：', '剩余攻击次数：', '当前生效的场地魔法：',
                 '速阶：', '类型：', '效果描述：'):
        assert text in HTML, '%s 未使用全角冒号' % text
    # game.js 里动态拼的几处（手牌速阶、场地魔法、连锁倒计时）
    for text in ('速阶：', '当前生效的场地魔法：', '剩余时间：'):
        assert text in JS, 'game.js 缺少 %s' % text
    assert '当前生效的场地魔法: ' not in JS
    assert '速阶: ' not in JS


# 8. 默认头像：原来是一个 1x1 全透明 PNG，头像位只剩一个空圆环
def test_default_avatar_is_visible_placeholder():
    path = os.path.join(BASE, 'static', 'avatars', 'default.png')
    with open(path, 'rb') as f:
        data = f.read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    width, height = struct.unpack('>II', data[16:24])
    assert width >= 64 and height >= 64, '默认头像仍是 %dx%d 占位' % (width, height)


# 9. 右下角是局内聊天浮窗的默认位置，预览框不能挪过去（会重叠）
def test_magic_preview_panel_keeps_top_right_anchor():
    chat = CSS.split('.in-game-chat-container {')[1].split('}')[0]
    assert 'right: 24px' in chat and 'bottom: 24px' in chat
    panel = CSS.split('@media (min-width: 1440px)')[1].split('}')[0]
    assert 'top: 80px' in panel
    assert 'bottom: 24px' not in panel
