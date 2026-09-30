#!/usr/bin/env python3
"""静态校验 static/style.css 的块结构，专抓历史 `fluent_dedupe_css.py` 吃花括号留下的坏块。

为什么必须静态抓：CSS 的一条规则少了收尾 `}`，**它后面的所有规则会被整段丢弃**
（样式变成 0px 圆角 / fallback 底色），而 CSS 解析器**不报错**、页面**不白屏**、
`node --check` 更是管不到 CSS —— 只能靠源码级断言。

做法：块栈解析（不是数括号）。每个 `{` 压栈一个块，记录它的**起始行**与**选择器文本**；
每个 `}` 弹栈。于是：

  * EOF 时栈非空 → 这些块缺收尾 `}`，直接报出选择器与起始行；
  * `}` 落在空栈上 → 多出来的 `}`；
  * 块身里又出现 `{` → 说明上一条规则没关，下一条选择器被当成声明文本吞了。

用法：python tools/fluent_css_lint.py [--quiet] [--file <css> ...]
      不给 --file 时按 DEFAULT_FILES 全量检查（style.css + C+ 十屏那一层）。
退出码 1 表示发现坏块。
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = ROOT / 'static' / 'style.css'
# 2026-09-29：把 C+ 十屏那一层也纳进来。它同样是"少个 `}` 就整段静默失效"的
# 手写 CSS，而且规则比 style.css 更挤（两千多行覆盖层），没有理由只查主文件。
DEFAULT_FILES = [ROOT / 'static' / 'style.css', ROOT / 'static' / 'arena_screens.css']


def strip_comments(text: str) -> str:
    """去掉 /* */ 但逐字符保留换行，行号才不会漂。"""
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


def lint(path=CSS):
    text = strip_comments(path.read_text(encoding='utf-8'))
    problems = []
    stack = []          # [(start_line, selector, is_at_rule)]
    pending = []        # 当前块的选择器文本
    line = 1

    for ch in text:
        if ch == '\n':
            line += 1
        elif ch == '{':
            sel = ' '.join(''.join(pending).split())
            is_at = sel.startswith('@')
            if stack and not stack[-1][2]:
                problems.append({
                    'kind': 'swallowed',
                    'line': line,
                    'detail': ('块身里出现 `{`，说明上一条规则没收尾 —— 第 %d 行的 `%s` '
                               '被当成声明吞掉了；本块选择器 `%s`'
                               % (stack[-1][0], stack[-1][1][:70], sel[:70])),
                })
            stack.append((line, sel or '(匿名)', is_at))
            pending = []
        elif ch == '}':
            if not stack:
                problems.append({
                    'kind': 'stray-close',
                    'line': line,
                    'detail': '多出来的 `}`（空栈上关闭，前面某条规则已提前闭合）',
                })
            else:
                stack.pop()
            pending = []
        else:
            pending.append(ch)

    for start, sel, _is_at in stack:
        problems.append({
            'kind': 'unclosed',
            'line': start,
            'detail': '规则缺收尾 `}`：`%s`（第 %d 行开始）—— 它之后的规则会全部被丢弃'
                      % (sel[:90], start),
        })
    return problems


def main(argv):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    quiet = '--quiet' in argv
    files = [pathlib.Path(a) for i, a in enumerate(argv)
             if i > 0 and argv[i - 1] == '--file']
    if not files:
        files = DEFAULT_FILES
    bad = 0
    for path in files:
        if not path.exists():
            print('%s 不存在' % path)
            bad += 1
            continue
        problems = lint(path)
        if not problems:
            if not quiet:
                print('%s 块结构 OK（无缺花括号 / 无多余花括号 / 无畸形嵌套）'
                      % path.relative_to(ROOT) if path.is_absolute() else path)
            continue
        bad += 1
        print('%s 发现 %d 处块结构问题：' % (path, len(problems)))
        for p in problems:
            print('  [%s] 第 %s 行 — %s' % (p['kind'], p['line'], p['detail']))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
