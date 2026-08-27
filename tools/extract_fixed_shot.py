# -*- coding: utf-8 -*-
"""从浏览器子代理转录中提取修复后界面的截图 dataURL 并落盘。"""
import base64
import io
import os
import re

TRANSCRIPT = r"C:\Users\Administrator\.qoder-cn\projects\d-develop-battle_ship1.0\transcript\task-7c45d887a30c45cb9a4d.session.execution.jsonl"
OUT = r"d:\develop\battle_ship1.0\tests\screenshots\shot_fixed_ai_room.jpg"

text = io.open(TRANSCRIPT, encoding='utf-8', errors='ignore').read()
# 取最后一处（最新一次渲染）完整 dataURL
matches = list(re.finditer(r'data:image/(jpeg|png);base64,([A-Za-z0-9+/=]{2000,})', text))
print(f'found {len(matches)} dataURLs')
assert matches, 'no dataURL found'
b64 = matches[-1].group(2)
data = base64.b64decode(b64, validate=False)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'wb') as f:
    f.write(data)
print(f'saved {OUT} ({len(data)} bytes)')
