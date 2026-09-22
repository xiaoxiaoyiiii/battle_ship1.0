#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""令牌化 pass 3：把 `rgba(var(--X-rgb), a)` 这种「变量 + 半透明」的写法也收进令牌区。

为什么值得做：`rgba(var(--danger-rgb), 0.1)` 虽然色相已经走了令牌，但**透明度仍然散在正文里** ——
想统一调「所有红色提示底的浓度」还是得改几十处。收紧之后：
    正文:  background: var(--alpha-danger-10);
    令牌区: --alpha-danger-10: rgba(var(--danger-rgb), 0.1);
色相与浓度都集中在令牌区，正文只剩语义名。

顺带把 pass 2（tools/fluent_tokenize_deco.py）插入的 `--deco-*` 定义块**从正文移到令牌区**：
那是定义，不是使用；留在正文里既让 AC6 的计数虚高，也破坏了「令牌区 = 唯一的颜色来源」这条规矩。

用法：
    python tools/fluent_tokenize_alpha.py            # 预览
    python tools/fluent_tokenize_alpha.py --write     # 写回
"""
import collections
import re
import sys

PATH = 'static/style.css'
SENTINEL = '@@TOKENS-END@@'
DECO_HEADER = '/* ---------- 6. 一次性装饰色（pass 2 机械提取） ----------'


def find_sentinel_line(lines):
    for i, line in enumerate(lines):
        if line.strip().startswith('/*') and SENTINEL in line:
            return i
    raise SystemExit('找不到令牌区哨兵')


def split_regions(lines):
    """返回 (token_region_lines, body_lines) —— 都不含哨兵行本身。"""
    i = find_sentinel_line(lines)
    return lines[:i], lines[i + 1:]


def move_deco_block(token_lines, body_lines):
    """把正文里的 --deco-* 定义块搬进令牌区（哨兵之前）。"""
    starts = [i for i, l in enumerate(body_lines) if l.startswith(DECO_HEADER)]
    if not starts:
        return token_lines, body_lines, 0
    moved = 0
    for s in reversed(starts):
        # 块 = 从注释头到与之配对的 '}' 行（定义块内不含嵌套花括号）
        e = s
        while e < len(body_lines) and body_lines[e].rstrip() != '}':
            e += 1
        block = body_lines[s:e + 1]
        moved += len(block)
        del body_lines[s:e + 1]
        while body_lines and body_lines[s:s + 1] and body_lines[s].strip() == '':
            del body_lines[s]
        token_lines = token_lines + [''] + block
    # 令牌区末尾补一个空行，保持可读
    while token_lines and token_lines[-1].strip() == '':
        token_lines.pop()
    token_lines.append('')
    return token_lines, body_lines, moved


def main():
    write = '--write' in sys.argv
    raw = open(PATH, encoding='utf-8', newline='').read()
    text = raw.replace('\r\n', '\n')
    lines = text.split('\n')
    token_lines, body_lines = split_regions(lines)

    token_lines, body_lines, moved = move_deco_block(token_lines, body_lines)
    body = '\n'.join(body_lines)

    # ---------- 收集 rgba(var(--X-rgb), a) ----------
    pat = re.compile(r'rgba\(\s*var\(\s*(--[a-z0-9-]+?)\s*\)\s*,\s*([\d.]+)\s*\)')
    # ---------- 收集 rgba(var(--X-rgb), a) ----------
    # 也认 `rgba(var(--primary-rgb, 21, 101, 192), a)` 这种带 fallback 的旧写法：
    # fallback 是历史遗留的保护性写法，令牌层已经保证 --primary-rgb 一定有值，
    # 这里连同 fallback 一起换成令牌（否则 fallback 里的裸数字会留在正文里）。
    pat = re.compile(r'rgba\(\s*var\(\s*(--[a-z0-9-]+?)\s*(?:,\s*[^()]*?)?\)\s*,\s*([\d.]+)\s*\)')
    combos = collections.Counter()
    for m in pat.finditer(body):
        combos[(m.group(1), m.group(2))] += 1

    # 命名：--alpha-<去掉前缀与 -rgb 的名字>-<透明度两位>
    names = {}
    for (var, a) in combos:
        base = re.sub(r'-rgb$', '', var.lstrip('-'))
        dec = str(a).split('.')[-1].ljust(2, '0')
        names[(var, a)] = '--alpha-%s-%s' % (base, dec)

    def repl(m):
        key = (m.group(1), m.group(2))
        return 'var(%s)' % names[key]

    body, n = pat.subn(repl, body)
    body_lines = body.split('\n')

    # ---------- 生成定义块 ----------
    block = ['/* ---------- 7. 透明度令牌：把「色相 + 浓度」都收进令牌区 ----------',
             '   正文里不再出现 rgba(var(--x-rgb), a) —— 统一写成 var(--alpha-<名字>-<浓度>)。',
             '   要统一调某一类提示底的浓淡，改这里一处即可。',
             '   ⚠️ 这些令牌引用的是 --x-rgb，而 --x-rgb 本身是**主题相关**的，',
             '      所以同一个令牌在浅色/深色下自动得到正确的颜色。 */',
             ':root {']
    for (var, a), nm in sorted(names.items(), key=lambda kv: kv[1]):
        block.append('    %s: rgba(var(%s), %s);' % (nm, var, a))
    block.append('}')
    block.append('')

    token_lines = token_lines + block
    out = '\n'.join(token_lines + [lines[find_sentinel_line(lines)]] + body_lines)
    # 上面用 lines[...] 取回哨兵行原文（含注释）

    if write:
        open(PATH, 'w', encoding='utf-8', newline='').write(out.replace('\n', '\r\n'))
        print('已写回 %s' % PATH)
    else:
        print('预览模式（未写回）')
    print('搬移 --deco-* 定义行: %d' % moved)
    print('rgba(var(--x-rgb), a) -> 令牌: %d 处，定义 %d 个令牌' % (n, len(names)))


if __name__ == '__main__':
    main()
