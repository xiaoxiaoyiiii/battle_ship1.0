#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AC6 的重复选择器收敛：合并「同一上下文里被重复定义、靠源码顺序压制」的规则块。

判据（宁可少合，绝不改语义）：
  对同一 (at-rule 上下文, 选择器) 的相邻两次出现 A、B：
  只有当 A 与 B **之间**、同一上下文里没有任何规则声明过 {A、B 声明的属性}
  时，才把 B 的声明并进 A 末尾再删除 B 的空壳。
  —— 若中间确有同名属性声明，那正是"靠顺序压制"，语义依赖顺序，必须人工看，**不自动化**。

⚠️ @keyframes / @font-face 等非选择器 at-rule 内部的块一律跳过。

用法：
    python tools/fluent_dedupe_css.py            # 预览
    python tools/fluent_dedupe_css.py --write     # 写回
"""
import collections
import re
import sys

PATH = 'static/style.css'
SENTINEL = '@@TOKENS-END@@'
SKIP_AT = ('@keyframes', '@-webkit-keyframes', '@-moz-keyframes', '@font-face', '@supports')


def find_sentinel(lines):
    for i, l in enumerate(lines):
        if l.strip().startswith('/*') and SENTINEL in l:
            return i
    raise SystemExit('找不到哨兵')


def parse(text, base):
    """返回正文里的规则块列表。

    每项: {ctx, sel, head_line, body_start, body_end, brace_line}
      head_line/brace_line 都是 1-based 行号；body 是 head_line+1 .. brace_line-1。
    """
    lines = text.split('\n')
    rules = []
    ctx = []          # at-rule 栈
    pending_head = None
    pending_ctx = None
    buf = ''
    start_line = 1
    for ln in range(base, len(lines) + 1):
        raw_line = lines[ln - 1]
        code = raw_line
        # 逐字符找 { } ;（注释里的不算）
        i = 0
        while i < len(code):
            ch = code[i]
            if ch == '{':
                head = ' '.join(buf.split())
                buf = ''
                if head.startswith('@'):
                    ctx.append(head)
                    rules.append({'ctx': tuple(ctx), 'sel': head, 'is_at': True,
                                  'head_line': start_line, 'body_start': ln + 1, 'brace_line': None})
                else:
                    rules.append({'ctx': tuple(ctx), 'sel': head, 'is_at': False,
                                  'head_line': start_line, 'body_start': ln + 1, 'brace_line': None})
                start_line = ln
            elif ch == '}':
                # 收尾：最近的未闭合块
                for r in reversed(rules):
                    if r['brace_line'] is None:
                        r['brace_line'] = ln
                        if r['is_at'] and ctx:
                            ctx.pop()
                        break
                buf = ''
                start_line = ln
            elif ch == ';':
                buf = ''
                start_line = ln
            else:
                buf += ch
            i += 1
    return lines, rules


def body_of(lines, r):
    if r['brace_line'] is None:
        return ''
    return '\n'.join(lines[r['body_start'] - 1:r['brace_line'] - 1])


def props(txt):
    out = set()
    for d in txt.split(';'):
        if ':' in d:
            out.add(d.split(':', 1)[0].strip().lower())
    return out


def specificity(sel):
    """粗算选择器特异性 (a,b,c)：a=id 数, b=类/属性/伪类 数, c=元素/伪元素 数。

    只用于「谁压得过谁」的**比较**，不需要绝对精确。
    保守取向：算不准时宁可**高估**中间规则的特异性 → 更少合并 → 更安全。
    """
    sel = re.sub(r'\s*[>+~]\s*', ' ', sel)
    a = len(re.findall(r'#[\w-]+', sel))
    b = (len(re.findall(r'\.[\w-]+', sel)) + len(re.findall(r'\[[^\]]*\]', sel))
         + len(re.findall(r'(?<!:):(?!:)[\w-]+', sel)))
    b -= len(re.findall(r'::[\w-]+', sel))          # 伪元素算元素级
    c = (len(re.findall(r'(?<![\w.\-#:])([a-zA-Z][\w-]*)', sel))
         + len(re.findall(r'::[\w-]+', sel)))
    return (a, b, c)


def main():
    write = '--write' in sys.argv
    raw = open(PATH, encoding='utf-8', newline='').read()
    text = raw.replace('\r\n', '\n')
    lines = text.split('\n')
    si = find_sentinel(lines)
    base = si + 2

    all_lines, rules = parse(text, base)
    leaf = [r for r in rules
            if not r['is_at'] and r['brace_line'] is not None
            and not any(c.startswith(SKIP_AT) for c in r['ctx'])]

    # 展开逗号选择器：组 key = (at-rule 上下文, 单个选择器)
    by_key = collections.defaultdict(list)
    for r in leaf:
        for part in r['sel'].split(','):
            p = ' '.join(part.split())
            if not p or re.match(r'^(\d+%|from|to)', p):
                continue
            by_key[(r['ctx'], p)].append(r)

    # 判据：只有当 A、B 之间**存在能被 B 覆盖结果逆转的规则**时才算冲突。
    #
    # 精确条件（级联语义）：A、B 之间某条规则 R 能覆盖 A，当且仅当
    #   specificity(R) >= specificity(A)     （R 在 A 之后，比较同级的靠顺序）
    # 若 R 的特异性低于 A，它根本改不动 A，B 合过去也不会改变结果 —— 这种情况**可以合**。
    #
    # 冲突只发生在：R 的特异性 >= A 的，且 R 声明了 B 也声明的属性。
    # 那时合并前 B 会赢过 R（B 更靠后），合并后 A 拿到了 B 的值、仍输给 R → 结果改变。
    #
    # ⚠️ 这条判据是**保守的**：只要中间规则可能覆盖，就宁可跳过等人看。
    # ⚠️ 只合并**单选择器**的规则块。多选择器块（如 `.a, .b { … }`）不能当 A 或 B：
    #    把它的声明并到别处、或把别处的声明并进来，都会顺带改变它**其它选择器**的样式。
    #    另一个必须防的坑：同一条多选择器规则会同时出现在多个 by_key 组里，
    #    不去重就会对同一个 B 重复删除 → 文件结构被吃坏（本项目实测踩过）。
    merges, blocked = [], []
    seen_pairs = set()
    for key, group in by_key.items():
        if len(group) < 2 or ',' in key[1] or ',' in key[0]:
            continue
        group = sorted(group, key=lambda r: r['head_line'])
        for a, b in zip(group, group[1:]):
            if ',' in a['sel'] or ',' in b['sel']:
                continue
            pair = (a['head_line'], b['head_line'])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            pb = props(body_of(all_lines, b))
            if not pb:
                blocked.append((key, a, b))
                continue
            spec_a = specificity(a['sel'])
            conflict = False
            for r in leaf:
                if r['ctx'] != a['ctx'] or r is a or r is b:
                    continue
                if not (a['brace_line'] < r['head_line'] < b['head_line']):
                    continue
                if specificity(r['sel']) < spec_a:
                    continue              # 这条压不过 A，合并不受影响
                if props(body_of(all_lines, r)) & pb:
                    conflict = True
                    break
            (blocked if conflict else merges).append((key, a, b))

    print('同一上下文重复组: %d 个选择器；可安全合并 %d 对，需人工判断 %d 对'
          % (sum(1 for k, v in by_key.items() if len(v) > 1), len(merges), len(blocked)))
    if not write:
        for (k, a, b) in merges[:30]:
            print('  %-52s L%d + L%d' % (k[1][:52], a['head_line'], b['head_line']))
        print('  ...（预览，未写回）')
        return

    # 执行策略：**按行号从大到小**处理每一对 (A, B)。
    # 因为 A 在 B 之前，先处理行号更大的 B —— 此时 B 自身的行号还没被前面的插入动过
    # （插入发生在更小的行号处，只影响 A 之后、B 之前的内容，而 A、B 之间没有插入）。
    # 关键顺序：先把 B 的声明插到 A 的 '}' 之前（A 在 B 前面，A 的行号不受影响），
    # 然后删除 B 的整块 —— 删除时 B 的行号因为刚才那次插入已经**下移了插入行数**，
    # 所以要先算好偏移再删。
    ops = sorted(((a, b) for (k, a, b) in merges), key=lambda t: t[1]['head_line'], reverse=True)
    merged = 0
    for (a, b) in ops:
        ins = [l for l in body_of(lines, b).split('\n') if l.strip()]
        n_ins = len(ins) + 1        # +1 是那行注释
        at = a['brace_line'] - 1    # A 的 '}' 所在行（0-based）
        lines[at:at] = ['    /* 合并自原第 %d 行的重复定义 */' % b['head_line']] + ins
        # B 的行号整体下移 n_ins（因为插入点在 B 之前）
        s = b['head_line'] - 1 + n_ins
        e = b['brace_line'] - 1 + n_ins
        del lines[s:e + 1]
        merged += 1

    out = '\n'.join(lines)

    # 写回前自检：括号必须平衡，否则**不要落盘**（宁可什么都不做也不能写坏文件）。
    # 本项目实测踩过：一次删除错位的合并把 5 个块的花括号吃掉，
    # 表现为「文件能读、CSS 从某处起整段失效」，而 pytest 照样全绿。
    noc = re.sub(r'/\*[\s\S]*?\*/', '', out)
    if noc.count('{') != noc.count('}'):
        raise SystemExit('自检失败：合并后花括号不平衡（{%d}/}%d），未写回。'
                         % (noc.count('{'), noc.count('}')))
    open(PATH, 'w', encoding='utf-8', newline='').write(out.replace('\n', '\r\n'))
    print('已写回 %s：合并 %d 对（原空块随 B 一起删除）' % (PATH, merged))


if __name__ == '__main__':
    main()
