# -*- coding: utf-8 -*-
"""从浏览器子代理的会话转录中提取截图 dataURL 并落盘。"""
import base64
import json
import os
import re
import sys

TRANSCRIPTS = [
    r"C:\Users\Administrator\.qoder-cn\projects\d-develop-battle_ship1.0\transcript\task-7c45d887a30c45cb9a4d.session.execution.jsonl",
    r"C:\Users\Administrator\.qoder-cn\projects\d-develop-battle_ship1.0\transcript\0642640b-7328-4728-b263-de42e92529a0.jsonl",
]
OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'tests', 'screenshots')
os.makedirs(OUT_DIR, exist_ok=True)

saved = []
seen_sizes = set()
for path in TRANSCRIPTS:
    if not os.path.exists(path):
        print(f'转录不存在: {path}')
        continue
    text = open(path, encoding='utf-8', errors='ignore').read()
    for m in re.finditer(r'data:image/(jpeg|png);base64,([A-Za-z0-9+/=]{2000,})', text):
        b64 = m.group(2)
        # 去除可能混入的 JSON 转义
        b64 = b64.replace('\\n', '').replace('\\', '')
        b64 = b64[: len(b64) // 4 * 4]
        try:
            data = base64.b64decode(b64, validate=False)
        except Exception as e:
            print(f'解码失败: {e}')
            continue
        if len(data) < 1024 or len(data) in seen_sizes:
            continue
        seen_sizes.add(len(data))
        out = os.path.abspath(os.path.join(OUT_DIR, f'shot_{len(saved) + 1}.jpg'))
        with open(out, 'wb') as f:
            f.write(data)
        saved.append(out)
        print(f'已保存 {out} ({len(data)} bytes)')

sys.exit(0 if saved else 1)
