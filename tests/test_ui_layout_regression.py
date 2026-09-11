# -*- coding: utf-8 -*-
"""issue #1 回归测试：弹窗 / 浮窗必须相对【视口】定位。

根因：按 CSS 规范，带 filter / backdrop-filter / transform / perspective /
contain / will-change 的元素会成为其 position:fixed 后代的【包含块】。
`.game-container` 是所有模态弹窗与浮窗的祖先，一旦它自己带上这类属性，
`.modal-overlay { position: fixed; width: 100%; height: 100% }` 就会按容器
（max-width:1000px）而不是视口计算尺寸 —— 表现为遮罩只盖住屏幕中间一列、
右侧聊天浮窗贴不到视口边缘，即 issue #1「不能正常地利用整个屏幕」。

本测试是纯静态检查（不依赖浏览器），用于防止这类属性被重新写回
`.game-container`（包括媒体查询里的同名规则块）。
"""
import re
from pathlib import Path

CSS_PATH = Path(__file__).resolve().parents[1] / 'static' / 'style.css'
CSS = CSS_PATH.read_text(encoding='utf-8')

# 会让元素成为 position:fixed 后代包含块的声明（正则, 人类可读名）
CONTAINING_BLOCK_TRAPS = (
    (r'backdrop-filter\s*:', 'backdrop-filter'),
    (r'(?<![\w-])filter\s*:', 'filter'),
    (r'(?<![\w-])transform\s*:', 'transform'),
    (r'(?<![\w-])perspective\s*:', 'perspective'),
    (r'(?<![\w-])contain\s*:\s*(?:paint|layout|strict|content)', 'contain'),
    (r'will-change\s*:[^;}]*\b(?:transform|filter|perspective)\b', 'will-change'),
)


def _strip_comments(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def _declarations(css, selector):
    """选择器【全部】规则块声明合并后的文本（已去注释）。

    同一选择器可能在媒体查询里再次出现，必须全部纳入检查，
    不能只取第一个或最后一个块。
    """
    blocks = re.findall(re.escape(selector) + r'\s*\{([^}]*)\}', _strip_comments(css))
    assert blocks, '在 static/style.css 中未找到规则块: %s' % selector
    return '\n'.join(_strip_comments(b) for b in blocks)


def test_game_container_is_not_a_containing_block_for_fixed_descendants():
    decls = _declarations(CSS, '.game-container')
    hits = [name for pattern, name in CONTAINING_BLOCK_TRAPS
            if re.search(pattern, decls)]
    assert not hits, (
        '.game-container 上出现了 %s —— 它会让所有 position:fixed 后代'
        '（.modal-overlay / .log-container / .in-game-chat-container 等）'
        '改以容器为包含块，弹窗遮罩将无法铺满视口（issue #1）。'
        '毛玻璃请写在 .game-container::before 上。' % '、'.join(hits)
    )


def test_modal_overlay_still_fills_viewport():
    """遮罩本身仍须是铺满视口的 fixed 层（防止有人改它来绕过上面那条）。"""
    decls = _declarations(CSS, '.modal-overlay')
    assert re.search(r'position\s*:\s*fixed', decls), '.modal-overlay 必须是 position: fixed'
    assert re.search(r'width\s*:\s*100%', decls), '.modal-overlay 必须 width: 100%'
    assert re.search(r'height\s*:\s*100%', decls), '.modal-overlay 必须 height: 100%'


def test_frosted_glass_layer_has_no_fixed_descendants():
    """毛玻璃层必须是伪元素（::before 不会有 position:fixed 后代）。"""
    decls = _declarations(CSS, '.game-container::before')
    assert 'backdrop-filter' in decls, '.game-container::before 应保留毛玻璃效果'
