# -*- coding: utf-8 -*-
"""移除已修复缺陷对应的 @pytest.mark.xfail 标记（缺陷已修复，用例应直接通过）。"""
import io

FILES = [
    r'd:\develop\battle_ship1.0\tests\test_all_magic_cards.py',
    r'd:\develop\battle_ship1.0\tests\test_magic_resolution_flows.py',
]

total = 0
for path in FILES:
    lines = io.open(path, encoding='utf-8').read().splitlines(keepends=True)
    out = []
    i = 0
    removed = 0
    while i < len(lines):
        if lines[i].lstrip().startswith('@pytest.mark.xfail'):
            # 跳过整个装饰器（直到以 ) 结尾的行）
            while i < len(lines):
                ended = lines[i].rstrip().endswith(')')
                i += 1
                if ended:
                    break
            removed += 1
            continue
        out.append(lines[i])
        i += 1
    io.open(path, 'w', encoding='utf-8', newline='').write(''.join(out))
    total += removed
    print(f'{path}: removed {removed}')
print('total removed:', total)
