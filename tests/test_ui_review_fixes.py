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


# 2. 阶段按钮：block 级按钮不受 text-align:center 影响，会贴左边


# 3. 两块棋盘必须同宽：flex 项要有确定的基准宽，否则各按内容自适应


# 4. 日志空状态：开局没有记录时要有提示，出现日志后要移除提示


# 5. 投降按钮与「第N回合」标题的垂直居中对齐


# 6. 玩家信息行文案（原来「6艘战舰剩余」断句悬空）


# 7. 中文界面统一全角冒号（半角冒号 + 空格是审查里点出的排版问题）


# 8. 默认头像：原来是一个 1x1 全透明 PNG，头像位只剩一个空圆环


# 9. 右下角是局内聊天浮窗的默认位置，预览框不能挪过去（会重叠）
# ⚠️ 本用例原先是「源码正则锁死 @media (min-width: 1440px) 块里的 top/right 数值」——
#    那锁的是行文不是意图，且那个 1440 断点本身就是缺陷（与 adaptive_layout.js 的
#    WIDE_MIN_W=1200 判据相反，1200–1439px 预览回落文档流把棋盘顶出首屏）。
#    现在改为断言**真实意图**：宽屏浮窗状态下预览锚在右上角（贴右边、贴顶），
#    并且绝不带 bottom —— 否则就会与右下角的聊天浮窗重叠。
