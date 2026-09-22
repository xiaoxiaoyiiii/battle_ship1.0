#!/usr/bin/env python3
"""对照 git 基线，找出「基线里的选择器分量在当前文件里完全找不到」的规则。

`tools/fluent_dedupe_css.py` 历史版本会**连规则一起吃掉**（已实测踩到 6 处），
表现是样式静默丢失。但去重脚本也会**合法合并**：把若干条同声明的规则的选择器
拼成一个组（`A {x}` + `B {x}` → `A, B {x}`），于是整串选择器 `A` 会「找不到」
而实际声明仍在。

所以判据是**选择器分量**：把每个选择器组按逗号拆开，看 `A` 这个分量是否仍出现
在当前的*任意*选择器组里。找不到才算真丢。

用法：
    python tools/fluent_css_diff_vs_head.py [--rev d139bf0] [--limit 80]
"""
import re
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = ROOT / 'static' / 'style.css'

# Fluent 化过程中**有意删除**的装饰性规则（流光/扫光/渐变文字等）。
INTENTIONAL = re.compile(
    r'@keyframes (btnSheen|cardSheen|titleFlow|rankGoldFlow|nameRainbowFlow)\b'
    r'|::after$|\.magic-card:hover::after',
)


def strip_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(''.join('\n' if c == '\n' else ' ' for c in text[i:j]))
            i = j
        else:
            out.append(text[i])
            i += 1
    return ''.join(out)


def selector_groups(text: str):
    """返回所有 `{` 之前的选择器组文本（已去注释、压空白）。"""
    text = strip_comments(text)
    out = []
    buf = []
    depth = 0
    for ch in text:
        if ch == '\n':
            buf.append(' ')
        elif ch == '{':
            sel = ' '.join(''.join(buf).split())
            if sel:
                out.append(sel)
            buf = []
            depth += 1
        elif ch == '}':
            buf = []
            depth = max(0, depth - 1)
        elif ch == ';' and depth > 0:
            buf = []
        else:
            buf.append(ch)
    return out


def components(groups):
    comps = set()
    for g in groups:
        for part in g.split(','):
            p = re.sub(r'\s+', ' ', part).strip()
            if p:
                comps.add(p)
    return comps


def main(argv):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    rev = argv[argv.index('--rev') + 1] if '--rev' in argv else 'HEAD'
    limit = int(argv[argv.index('--limit') + 1]) if '--limit' in argv else 80

    base = subprocess.run(['git', 'show', f'{rev}:static/style.css'], cwd=str(ROOT),
                          capture_output=True).stdout.decode('utf-8', 'replace')
    cur = CSS.read_text(encoding='utf-8')

    base_comps = components(selector_groups(base))
    cur_comps = components(selector_groups(cur))

    missing = sorted(base_comps - cur_comps)
    real = [m for m in missing if not INTENTIONAL.search(m)]
    intentional = [m for m in missing if INTENTIONAL.search(m)]

    print('基线 %s：选择器分量 %d 个，当前 %d 个' % (rev, len(base_comps), len(cur_comps)))
    print('缺失 %d 个 —— 其中有意的装饰性删除 %d 个' % (len(missing), len(intentional)))
    print()
    print('=== 需要人工确认的缺失 %d 个 ===' % len(real))
    for s in real[:limit]:
        print('  -', s[:150])
    if len(real) > limit:
        print('  …还有 %d 个' % (len(real) - limit))
    if intentional:
        print()
        print('=== 有意删除（Fluent 化去装饰） %d 个 ===' % len(intentional))
        for s in intentional[:limit]:
            print('  x', s[:110])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
