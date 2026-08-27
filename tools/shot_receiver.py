# -*- coding: utf-8 -*-
"""临时接收端点：接收浏览器 POST 的截图 dataURL 并落盘。"""
import base64
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = os.path.join(os.path.dirname(__file__), '..', 'tests', 'screenshots', 'shot_fixed_ai_room.jpg')


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n).decode('utf-8', errors='ignore')
        if ',' in body:
            body = body.split(',', 1)[1]
        data = base64.b64decode(body, validate=False)
        os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
        with open(OUT, 'wb') as f:
            f.write(data)
        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(b'OK')
        print(f'saved {os.path.abspath(OUT)} ({len(data)} bytes)', flush=True)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    srv = HTTPServer(('127.0.0.1', 8123), Handler)
    print('receiver on http://127.0.0.1:8123', flush=True)
    srv.handle_request()  # 只处理一次请求后退出
    srv.handle_request()  # 兼容预检 + 正式请求
    print('done', flush=True)
