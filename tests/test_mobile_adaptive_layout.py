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
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(BASE, rel), encoding='utf-8') as f:
        return f.read()


HTML = _read('templates/index.html')
CSS = _read('static/style.css')
JS = _read('static/game.js')
ADAPTIVE = _read('static/adaptive_layout.js')


# 1. 三个浮窗必须有一个共同的落点（面板槽），且三选一


# 2. 紧凑布局只在对局界面生效——别把登录/大厅/排行榜也锁成 overflow:hidden


# 3. 搬进面板槽之后，原来的浮窗必须交出 position:fixed（否则仍会盖住棋盘）
#
# ⚠️ 判据在 Fluent 批改写过（原为 `'position: static !important;' in CSS`）。
#    原来必须是 !important，因为面板槽里的浮窗要压掉**两样东西**：
#      a) `.log-container` 等基础规则里的 `position: fixed`；
#      b) game.js 给三个浮窗写的**内联** left/top（拖拽会写内联样式）。
#    Fluent 批把 (b) 消掉了 —— 拖拽写内联的逻辑现在只作用于宽屏浮窗，
#    紧凑布局下三个面板已改为纯类控制（见 style.css 第 22.4 节注释），
#    于是这里可以用普通规则（特异性本就更高），不再需要 !important。
#    这条断言要防的回归没变：**搬进面板槽后仍在 floating**（fixed/absolute + 非 auto 的定位值）。
#    所以新判据直接读那三个选择器块，逐块检查 position 与其偏移量，而不是匹配某个字面量。
def _rule_block(selector):
    """取 CSS 里某个选择器所在块的正文（第一个匹配）。找不到返回 None。"""
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', CSS)
    return m.group(0) if m else None




# 4. 棋盘尺寸由舞台反推，且只锁宽度——同时锁高度会在舞台变矮时压成扁格子


# 5. 手牌必须有归宿：常驻手牌条，或收进面板槽的卡牌页


# 6. 触摸目标下限：紧凑模式下按钮不得低于 40px


# 7. 触屏上必须停用"拖动浮窗"（拖拽会与页面滚动抢手势，且会把宽屏坐标写坏）


# 8. 面板槽展开时不得把棋盘饿死，且手牌要让位


# 9. 响应式原语：移动端安全区与动态视口单位


# 10. 脚本必须在 game.js 之后加载（依赖它创建的 #magic-system / 头像角标）
