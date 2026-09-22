#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""令牌化 pass 2：把正文里剩下的**彩色** rgba/rgb 字面量提取成令牌。

与 pass 1（tools/fluent_tokenize_css.py）的分工：
  pass 1 处理「有明确语义」的裸值（中性叠层、金色家族、段位色、棋盘元素、语义色家族）。
  pass 2 处理剩下的**一次性装饰色**：它们大多是历史分区里逐块调出来的
        半透明叠加色（护盾/冰冻/优先权面板/名牌底色……）。

做法：按「色相 + 透明度」聚合命名成 `--deco-<hue>-a<alpha>`，集中定义在令牌区的一次
`HTMLDARK/ROOT` 块里。这样：
  · 正文里不再出现裸 rgba（AC6 可判定），
  · 想统一调「所有半透明蓝叠加」只需改一个令牌，
  · 且**行为与改动前逐位等价**（每个令牌的值就是原来那个字面量）—— 换皮不能偷偷改语义。

⚠️ 这些是「保真搬运」，不是「重新设计」。真正需要按 Fluent 语义重调的部分在
   style.css 的组件层里手写（如按钮/输入/对话框），不走本脚本。

用法：
    python tools/fluent_tokenize_deco.py            # 预览
    python tools/fluent_tokenize_deco.py --write     # 写回（含插入令牌定义块）
"""
import collections
import colorsys
import re
import sys

PATH = 'static/style.css'
SENTINEL = '@@TOKENS-END@@'

HUES = [('red', 0), ('orange', 25), ('amber', 45), ('yellow', 58), ('lime', 80),
        ('green', 120), ('teal', 170), ('cyan', 188), ('sky', 200), ('blue', 218),
        ('indigo', 240), ('violet', 262), ('purple', 285), ('magenta', 310),
        ('pink', 335), ('rose', 350)]

# 人工覆盖：这些是"有名字"的装饰色，用语义名而不是 hue+alpha，便于后面调主题。
SEMANTIC = {
    'rgba(111,195,255,0.55)': '--deco-frozen-edge',
    'rgba(255,215,111,0.55)': '--deco-shield-edge',
    'rgba(192,140,255,0.55)': '--deco-invincible-edge',
    'rgba(255,235,59,0.45)': '--deco-revealed-tint',
    'rgba(56,189,248,0.22)': '--deco-shieldbroken-fill',
    'rgba(56,189,248,0.85)': '--deco-shieldbroken-line',
    'rgba(56,189,248,0.9)': '--deco-shieldbroken-text',
    'rgba(255,196,0,0.9)': '--deco-laststand-line',
    'rgba(255,196,0,0.95)': '--deco-laststand-strong',
    'rgba(255,196,0,0.20)': '--deco-laststand-fill',
    'rgba(255,196,0,0.06)': '--deco-laststand-faint',
    'rgba(96,165,250,0.9)': '--deco-frozenarea-line',
    'rgba(96,165,250,0.55)': '--deco-frozenarea-edge',
    'rgba(96,165,250,0.22)': '--deco-frozenarea-fill',
    'rgba(96,165,250,0.05)': '--deco-frozenarea-faint',
    'rgba(147,197,253,0.85)': '--deco-frozenarea-line-dark',
    'rgba(147,197,253,0.20)': '--deco-frozenarea-fill-dark',
    'rgba(147,197,253,0.04)': '--deco-frozenarea-faint-dark',
    'rgba(16,185,129,0.95)': '--deco-heal-strong',
    'rgba(16,185,129,0.5)': '--deco-heal-mid',
    'rgba(16,185,129,0.20)': '--deco-heal-fill',
    'rgba(16,185,129,0.05)': '--deco-heal-faint',
    'rgba(52,211,153,0.9)': '--deco-heal-line-dark',
    'rgba(52,211,153,0.18)': '--deco-heal-fill-dark',
    'rgba(52,211,153,0.04)': '--deco-heal-faint-dark',
    'rgba(6,18,34,0.38)': '--deco-priority-panel',
    'rgba(6,18,34,0.1)': '--deco-priority-card-edge',
    'rgba(6,18,34,0.22)': '--deco-priority-btn',
    'rgba(6,18,34,0.3)': '--deco-priority-btn-hover',
    'rgba(38,52,70,0.95)': '--deco-priority-card-dark',
    'rgba(28,40,56,0.92)': '--deco-priority-soft-dark',
    'rgba(226,236,248,0.78)': '--deco-priority-hint-dark',
    'rgba(10,20,35,0.45)': '--deco-prompt-scrim',
    'rgba(124,58,237,0.95)': '--deco-holy-strong',
    'rgba(124,58,237,0.3)': '--deco-holy-fill',
    'rgba(255,99,71,0.18)': '--deco-log-attack',
    'rgba(158,158,158,0.20)': '--deco-log-info',
    'rgba(30,30,30,0.6)': '--deco-blocked-cell',
    'rgba(20,20,20,0.75)': '--deco-shenwei-hole',
    'rgba(120,120,120,0.4)': '--deco-blocked-cell-soft',
    'rgba(18,30,44,0.97)': '--deco-chat-panel-dark',
    'rgba(20,32,46,0.9)': '--deco-chat-toast-dark',
    'rgba(27,150,60,1)': '--deco-pick-selected',
    'rgba(156,39,176,0.55)': '--deco-sacrificed',
    'rgba(46,204,113,0.95)': '--deco-msg-success',
    'rgba(241,196,15,0.95)': '--deco-msg-warning',
    'rgba(231,76,60,0.95)': '--deco-msg-error',
    'rgba(255,152,0,0.75)': '--deco-timing-off-strong',
    'rgba(128,128,128,0.5)': '--deco-disabled-scrim',
    'rgba(22,32,46,0.92)': '--deco-priority-panel-dark',
}


def hue_name(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if s < 0.18:
        return 'slate'
    deg = h * 360
    best = min(HUES, key=lambda hn: min(abs(deg - hn[1]), 360 - abs(deg - hn[1])))
    return best[0]


def norm(lit):
    m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)', lit)
    if not m:
        return None
    r, g, b, a = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    return r, g, b, a


def find_body_start(text):
    for i, line in enumerate(text.split('\n')):
        if line.strip().startswith('/*') and SENTINEL in line:
            return sum(len(x) + 1 for x in text.split('\n')[:i + 1])
    raise SystemExit('找不到令牌区哨兵')


def main():
    write = '--write' in sys.argv
    raw = open(PATH, encoding='utf-8', newline='').read()
    text = raw.replace('\r\n', '\n')
    start = find_body_start(text)
    head, body = text[:start], text[start:]
    body_c = re.sub(r'/\*[\s\S]*?\*/', lambda m: ' ' * len(m.group(0)), body)

    # ---------- 1. 收集正文里剩下的彩色字面量 ----------
    lits = collections.Counter()
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', body_c):
        for d in m.group(2).split(';'):
            if ':' not in d:
                continue
            for lit in re.findall(r'rgba?\([^()]*(?:\([^()]*\)[^()]*)*\)', d.split(':', 1)[1]):
                if re.match(r'^rgba?\(\s*var\(', lit):
                    continue
                parsed = norm(lit)
                if not parsed:
                    continue                      # 不是纯数字形式，跳过
                if parsed[:3] in ((0, 0, 0), (255, 255, 255)):
                    continue                      # 中性色归 pass 1 处理
                lits[re.sub(r'\s+', '', lit)] += 1
    # 还要保号：把 rgb(a) 里带空格的形式统一成无空格键
    lits = collections.Counter({re.sub(r'\s+', '', k): v for k, v in lits.items()})

    # ---------- 2. 命名 ----------
    names, used = {}, collections.Counter()
    for lit in sorted(lits, key=lambda k: (-lits[k], k)):
        p = norm(lit)
        r, g, b, a = p
        if lit in SEMANTIC:
            names[lit] = SEMANTIC[lit]
            continue
        hn = hue_name(r, g, b)
        atag = ('a' + a.replace('0.', '').replace('.', '')).replace('a1', 'a100') if a == '1' else 'a' + a.replace('0.', '').replace('.', '')
        nm = '--deco-%s-%s' % (hn, atag)
        while nm in names.values():
            used[nm] += 1
            nm = '--deco-%s-%s-%d' % (hn, atag, used[nm])
        names[lit] = nm

    # ---------- 3. 替换 ----------
    hits = collections.Counter()

    def repl(m):
        lit = m.group(0)
        key = re.sub(r'\s+', '', lit)
        nm = names.get(key)
        if not nm:
            return lit
        hits[nm] += 1
        return 'var(%s)' % nm

    body_new = re.sub(r'\brgba?\([^()]*(?:\([^()]*\)[^()]*)*\)', repl, body)
    # 上面会把 var(--x, rgba(...)) 里的 fallback 也换掉 —— 这是想要的（fallback 也令牌化）

    # ---------- 4. 生成令牌定义块 ----------
    lines = ['/* ---------- 6. 一次性装饰色（pass 2 机械提取） ----------',
             '   历史分区里逐块调出来的半透明叠加色，按「色相 + 透明度」聚合。',
             '   每个令牌的值都与提取前的字面量**逐位相同** —— 这一步只做集中管理，',
             '   不重新设计。要统一调某一类叠加色（例如所有半透明蓝）改这里即可。 */',
             ':root {']
    for lit in sorted(names, key=lambda k: names[k]):
        # 还原成带空格的规范写法，便于阅读
        r, g, b, a = norm(lit)
        lines.append('    %s: rgba(%d, %d, %d, %s);' % (names[lit], r, g, b, a))
    lines.append('}')
    lines.append('')
    block = '\n'.join(lines)

    out = head + block + body_new
    if write:
        open(PATH, 'w', encoding='utf-8', newline='').write(out.replace('\n', '\r\n'))
        print('已写回 %s（插入 %d 个令牌定义）' % (PATH, len(names)))
    else:
        print('预览模式（未写回）')
    print('替换 %d 处，定义 %d 个令牌' % (sum(hits.values()), len(names)))
    # 未命中的令牌（定义了却一处也没替换到）说明映射写错了或已被前一步换掉。
    print('未命中的令牌（应为空）：', sorted({names[k] for k in names} - set(hits)))


if __name__ == '__main__':
    main()
