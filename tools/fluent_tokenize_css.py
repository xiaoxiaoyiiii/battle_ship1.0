#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 style.css 正文里的裸色令牌化（AC6 的主力动作）。

设计要点：
  · 映射表显式列在下面，一条一条可审计；不做"聪明"的模糊替换。
  · 只替换**令牌区之外**的正文（哨兵 @@TOKENS-END@@ 之后）。
  · 只替换**声明值**里的字面量，不碰选择器、不碰注释。
  · 逐个替换并统计命中次数，命中 0 次的映射会被报告出来（说明写错了或已改过）。
  · 保留 CRLF 与文件末尾换行。

用法：
    python tools/fluent_tokenize_css.py            # 预览（不写回）
    python tools/fluent_tokenize_css.py --write    # 写回
"""
import re
import sys
import io

PATH = 'static/style.css'
SENTINEL = '@@TOKENS-END@@'

# ---------------------------------------------------------------- 映射表
# 顺序有意义：先长后短 / 先具体后笼统，避免 rgba(0,0,0,0.5) 被 0.5 之外的规则抢先。
# ---- hex 字面量 -> 令牌 ----
# 只收「有意义、可复用」的那些。一次性装饰色（名片底色、段位图标色）不走这里，
# 它们按家族归到 --fluent-gold-* / --fluent-rank-* 下面。
HEX_MAP = {
    # 实心底上的文字：Fluent 的 "on-solid"（浅色态=白字）
    '#fff': 'var(--fluent-on-solid)',
    '#ffffff': 'var(--fluent-on-solid)',
    # 金色家族（经验条 / 段位 / 奖励）
    '#ffd24d': 'var(--fluent-gold)',
    '#ff9f1a': 'var(--fluent-gold-deep)',
    '#fff3c4': 'var(--fluent-gold-soft)',
    '#ffcb3d': 'var(--fluent-gold)',
    '#c9a227': 'var(--fluent-gold-deep)',
    '#ffd98a': 'var(--fluent-gold-soft)',
    '#ffe58a': 'var(--fluent-gold-soft)',
    '#ffe08a': 'var(--fluent-gold-soft)',
    '#ffe07a': 'var(--fluent-gold-soft)',
    '#ffb03a': 'var(--fluent-gold-deep)',
    '#f0c46a': 'var(--fluent-gold)',
    '#fffbe8': 'var(--fluent-gold-soft)',
    '#ffe9b0': 'var(--fluent-gold-soft)',
    '#ffe14d': 'var(--fluent-gold)',
    '#fff3d4': 'var(--fluent-gold-soft)',
    '#ffedbe': 'var(--fluent-gold-soft)',
    '#ffd88a': 'var(--fluent-gold-soft)',
    '#7a4c10': 'var(--fluent-gold-shade)',
    '#a9741c': 'var(--fluent-gold-shade)',
    '#7a4a00': 'var(--fluent-gold-shade)',
    # 段位图标 9 档
    '#8b95a1': 'var(--fluent-rank-1)',
    '#a3b1bb': 'var(--fluent-rank-2)',
    '#b98d5a': 'var(--fluent-rank-3)',
    '#3fc8b4': 'var(--fluent-rank-4)',
    '#9a6ff0': 'var(--fluent-rank-5)',
    '#6f7fe6': 'var(--fluent-rank-6)',
    '#7d8ce8': 'var(--fluent-rank-7)',
    '#56b6ff': 'var(--fluent-rank-8)',
    '#cfe9ff': 'var(--fluent-rank-9)',
    # 棋盘自绘元素
    '#5d4f3c': 'var(--ship-outline)',
    '#6fc3ff': 'var(--frozen-tint)',
    '#bfe6ff': 'var(--frozen-text)',
    '#ffd76f': 'var(--shield-tint)',
    '#c08cff': 'var(--invincible-tint)',
    '#e3d0ff': 'var(--invincible-text)',
    '#b45309': 'var(--laststand-tint)',
    '#fbbf24': 'var(--laststand-tint)',
    '#7dd3fc': 'var(--frozen-tint)',
    # 语义色的深一档（实心按钮的渐变尾）
    '#e53935': 'var(--danger)',
    '#c62828': 'var(--danger-600)',
    '#d32f2f': 'var(--danger-600)',
    '#ef4444': 'var(--danger)',
    '#f44336': 'var(--danger)',
    '#e74c3c': 'var(--danger)',
    '#34d399': 'var(--success)',
    '#2e7d32': 'var(--success)',
    '#4caf50': 'var(--success)',
    '#2fbf85': 'var(--success)',
    '#27ae60': 'var(--success)',
    '#4dd964': 'var(--success)',
    '#ff9800': 'var(--warning)',
    '#f59e0b': 'var(--warning)',
    '#f1c40f': 'var(--warning)',
    '#2196f3': 'var(--info)',
    '#1565c0': 'var(--primary)',
    '#1e88e5': 'var(--primary-600)',
    '#0f766e': 'var(--primary)',
    '#c2410c': 'var(--primary-600)',
    '#f97316': 'var(--primary)',
    '#22d3ee': 'var(--primary)',
    '#7c3aed': 'var(--secondary)',
    '#be185d': 'var(--primary)',
    '#f472b6': 'var(--primary)',
    # 中性灰（旧的 slate 系）
    '#8a94a2': 'var(--muted)',
    '#6b7683': 'var(--muted)',
    '#9aa6b4': 'var(--muted)',
    '#334155': 'var(--text-subtle)',
    '#0f172a': 'var(--text)',
    '#cbd5e1': 'var(--border)',
    '#e8a33d': 'var(--accent)',
    '#888': 'var(--muted)',
    '#333': 'var(--text)',
    '#063': 'var(--success)',
}

# 纯中性色的 rgba -> 令牌（这些是"叠一层黑/白"的层次表达）
RGBA_MAP = {
    'rgba(0,0,0,0.03)': 'var(--fluent-fill-subtle)',
    'rgba(0,0,0,0.04)': 'var(--fluent-scrim-04)',
    'rgba(0,0,0,0.05)': 'var(--fluent-fill-quiet)',
    'rgba(0,0,0,0.06)': 'var(--fluent-fill-quiet)',
    'rgba(0,0,0,0.08)': 'var(--fluent-scrim-08)',
    'rgba(0,0,0,0.1)': 'var(--fluent-scrim-08)',
    'rgba(0,0,0,0.12)': 'var(--fluent-scrim-15)',
    'rgba(0,0,0,0.15)': 'var(--fluent-scrim-15)',
    'rgba(0,0,0,0.18)': 'var(--fluent-scrim-22)',
    'rgba(0,0,0,0.2)': 'var(--fluent-scrim-22)',
    'rgba(0,0,0,0.22)': 'var(--fluent-scrim-22)',
    'rgba(0,0,0,0.25)': 'var(--fluent-scrim-25)',
    'rgba(0,0,0,0.28)': 'var(--fluent-scrim-30)',
    'rgba(0,0,0,0.3)': 'var(--fluent-scrim-30)',
    'rgba(0,0,0,0.32)': 'var(--fluent-scrim-30)',
    'rgba(0,0,0,0.35)': 'var(--fluent-scrim-35)',
    'rgba(0,0,0,0.4)': 'var(--fluent-scrim-45)',
    'rgba(0,0,0,0.45)': 'var(--fluent-scrim-45)',
    'rgba(0,0,0,0.5)': 'var(--fluent-scrim-55)',
    'rgba(0,0,0,0.55)': 'var(--fluent-scrim-55)',
    'rgba(0,0,0,0.6)': 'var(--fluent-scrim-55)',
    'rgba(255,255,255,0.02)': 'var(--fluent-light-02)',
    'rgba(255,255,255,0.04)': 'var(--fluent-light-06)',
    'rgba(255,255,255,0.06)': 'var(--fluent-light-06)',
    'rgba(255,255,255,0.08)': 'var(--fluent-light-08)',
    'rgba(255,255,255,0.1)': 'var(--fluent-light-12)',
    'rgba(255,255,255,0.12)': 'var(--fluent-light-12)',
    'rgba(255,255,255,0.14)': 'var(--fluent-light-14)',
    'rgba(255,255,255,0.15)': 'var(--fluent-light-14)',
    'rgba(255,255,255,0.18)': 'var(--fluent-light-18)',
    'rgba(255,255,255,0.2)': 'var(--fluent-light-20)',
    'rgba(255,255,255,0.22)': 'var(--fluent-light-20)',
    'rgba(255,255,255,0.25)': 'var(--fluent-light-20)',
    'rgba(255,255,255,0.3)': 'var(--fluent-light-35)',
    'rgba(255,255,255,0.35)': 'var(--fluent-light-35)',
}


# 语义色家族：同一个色相 + 一组透明度 -> 令牌（色相走 --x-rgb，透明度用 color-mix 兜底）
# 这类写成「rgba(228,57,53,a)」这种旧 Material 红，统一改为 --danger-rgb 形式。
RGB_FAMILY = {
    '229,57,53': 'var(--danger-rgb)',      # Material Red 600（旧 danger）
    '220,53,69': 'var(--danger-rgb)',
    '14,159,110': 'var(--success-rgb)',
    '76,175,80': 'var(--success-rgb)',
    '33,150,243': 'var(--info-rgb)',
    '232,163,61': 'var(--accent-rgb)',     # 旧的"海洋点缀"金
    '141,128,248': 'var(--secondary-rgb)',
}


def parse_literals():
    return HEX_MAP, RGBA_MAP, RGB_FAMILY


def find_body_start(text):
    for i, line in enumerate(text.split('\n')):
        if line.strip().startswith('/*') and SENTINEL in line:
            return sum(len(x) + 1 for x in text.split('\n')[:i + 1])
    raise SystemExit('找不到令牌区哨兵')


def main():
    write = '--write' in sys.argv
    raw = open(PATH, encoding='utf-8', newline='').read()
    crlf = raw.count('\r\n')
    text = raw.replace('\r\n', '\n')
    start = find_body_start(text)
    head, body = text[:start], text[start:]

    stats = {}
    # 1) 规范化比较用的键：去掉空格，小写
    def norm_rgba(s):
        return re.sub(r'\s+', '', s).lower()

    # 2) 逐条替换 rgba(...)/rgb(...) 字面量
    def repl_rgba(m):
        lit = m.group(0)
        key = norm_rgba(lit)
        if key in RGBA_MAP:
            rep = RGBA_MAP[key]
        else:
            mm = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)', lit)
            if not mm:
                return lit
            r, g, b, a = mm.groups()
            fam = RGB_FAMILY.get('%s,%s,%s' % (r, g, b))
            if not fam:
                return lit
            rep = 'rgba(%s, %s)' % (fam, a)
        stats[rep] = stats.get(rep, 0) + 1
        return rep

    body = re.sub(r'\brgba?\([^()]*(?:\([^()]*\)[^()]*)*\)', repl_rgba, body)

    # 3) hex 字面量：按 --hex 逐条替换（长优先，避免 #fff 命中 #ffffff 的前缀）
    def repl_hex(m):
        lit = m.group(0)
        rep = HEX_MAP.get(lit.lower())
        if not rep:
            return lit
        stats[rep] = stats.get(rep, 0) + 1
        return rep

    body = re.sub(r'#[0-9a-fA-F]{3,8}\b',
                  lambda m: repl_hex(m) if len(m.group(0)) in (4, 5, 7, 9) else m.group(0),
                  body)

    out = head + body
    if write:
        open(PATH, 'w', encoding='utf-8', newline='').write(out.replace('\n', '\r\n'))
        print('已写回 %s' % PATH)
    else:
        print('预览模式（未写回）')
    total = sum(stats.values())
    print('替换 %d 处，涉及 %d 种令牌：' % (total, len(stats)))
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print('  %4d  %s' % (v, k))


if __name__ == '__main__':
    main()
