# -*- coding: utf-8 -*-
"""把 `templates/index.html` 渲染成一份**不需要服务端**的静态页面，供前端回归工具加载。

复用真正的模板 + 真正的 `static/*.js`（不手抄 DOM），只是把 Jinja 变量按游客态填好。
socket.io 由工具在页面里打桩，所以这个页面不会真的连服务端。

用法（项目根目录）：python tools/render_index_snapshot.py
输出：.tmp/index_snapshot.html
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# 必须先隔离数据库：import api 会在 import 期建表，别往正式库写东西
os.environ.setdefault('BATTLESHIP_DB_PATH',
                      os.path.join(ROOT, '.tmp', 'render_snapshot.db'))

from api import app, _inject_asset_version    # noqa: E402  (import 顺序有意为之)


def main():
    out = os.path.join(ROOT, '.tmp', 'index_snapshot.html')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    # asset_v() 是 context_processor 提供的，不经过 request 就得手动并进去
    app.jinja_env.globals.update(_inject_asset_version())
    with app.test_request_context('/'):   # 模板里有 get_flashed_messages()，需要 request 上下文
        html = app.jinja_env.get_template('index.html').render(username=None)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print('wrote', out, len(html), 'bytes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
