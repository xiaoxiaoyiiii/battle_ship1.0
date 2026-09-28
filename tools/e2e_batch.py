#!/usr/bin/env python3
"""批量跑 tools/*.mjs 的 e2e 检查，多分片并行。

为什么要它：
  * 49 个无头浏览器工具，逐个手动 `<起服务; 跑; kill>` 太慢；
  * **每个工具都不自带 profile 预清理** —— 残留的无头进程会让新的浏览器
    "静默起不来"（CLAUDE.md §11.15 记过），所以批跑器必须在每次运行前
    删掉该工具的 profile 目录并杀掉占用它的残留进程；
  * 单个工具失败不能让整批停摆 —— 需要逐个记 rc 与耗时。

分片：每片一个独立端口 + 独立 SQLite 库 + 独立 CORS 来源。
⚠️ 分片数不要开太大：部分工具会各自拉起"第二个玩家"python 子进程配合
（ranked_check / friends_check / lobby_check …），同一台机器上并发抢 CPU
会让计时类的断言（音效、动画）抖动。

用法：
    python tools/e2e_batch.py                       # 全部，4 分片
    python tools/e2e_batch.py --shards 6
    python tools/e2e_batch.py --only ui_layout_check,hand_play_check
    python tools/e2e_batch.py --skip repro_hand_blank,diag_bomb_alert
    python tools/e2e_batch.py --list
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'tools'
TMP = ROOT / '.tmp'

# 只做静态分析、不需要服务端的工具（都不启动浏览器）
NO_BROWSER = {
    'dom_contract_check',        # 纯源码/模板对账
    'fluent_css_metrics',        # 纯 CSS 度量
}

# 名字里带 repro_/diag_ 的是**复现脚本**，不是回归检查（失败不代表回归）
REPRO_PREFIX = ('repro_', 'diag_')


def discover():
    names = sorted(p.stem for p in TOOLS.glob('*.mjs'))
    return [n for n in names if n not in NO_BROWSER]


def profile_dirs(tool):
    """从工具源码里抠出它用的 profile 目录名，用于跑前清理。"""
    src = (TOOLS / f'{tool}.mjs').read_text(encoding='utf-8', errors='replace')
    found = set()
    for m in re.finditer(r"""['"]([A-Za-z0-9_]*profile[A-Za-z0-9_]*)['"]""", src):
        found.add(m.group(1))
    # 形如 path.join(TMP, 'xxx_profile')
    for m in re.finditer(r"""path\.join\([^,]+,\s*['"]([^'"]+)['"]\)""", src):
        if 'profile' in m.group(1):
            found.add(m.group(1))
    return found


def clean_profiles(tool, kill_tasks):
    """删掉该工具的 profile 目录；顺带杀掉仍占用它的 msedge 残留进程。"""
    removed = []
    for name in profile_dirs(tool):
        for base in (pathlib.Path('C:/Windows/Temp'), TMP, pathlib.Path(tempfile.gettempdir())):
            d = base / name
            if d.exists():
                try:
                    shutil.rmtree(d, ignore_errors=True)
                    removed.append(str(d))
                except OSError:
                    pass
    return removed


def kill_stale_edge(port):
    """无头 Edge 残留在该调试端口上时，新的浏览器会静默起不来 —— 先清掉。"""
    try:
        out = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True,
                             text=True, timeout=20).stdout
    except Exception:
        return
    pids = set()
    for line in out.splitlines():
        if f':{port}' in line and 'LISTENING' in line:
            parts = line.split()
            if parts:
                pids.add(parts[-1])
    for pid in pids:
        subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)


def wait_server(port, timeout=90):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/online_count', timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


class Shard:
    """一个分片 = 一个服务端 + 一串工具，串行执行。"""

    def __init__(self, index, port, tools, timeout):
        self.index = index
        self.port = port
        self.tools = tools
        self.timeout = timeout
        self.proc = None
        self.results = []

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}/'

    def start_server(self):
        db = TMP / f'e2e_shard{self.index}.db'
        for suffix in ('', '-wal', '-shm'):
            p = pathlib.Path(str(db) + suffix)
            if p.exists():
                p.unlink()
        log = open(TMP / f'e2e_shard{self.index}.log', 'wb')
        env = dict(os.environ)
        env['BATTLESHIP_DB_PATH'] = str(db)
        env['CORS_ORIGINS'] = f'http://127.0.0.1:{self.port}'
        env['PORT'] = str(self.port)
        env['PYTHONIOENCODING'] = 'utf-8'
        self.proc = subprocess.Popen([sys.executable, 'server.py'], cwd=str(ROOT),
                                     stdout=log, stderr=subprocess.STDOUT, env=env)
        if not wait_server(self.port, timeout=120):
            raise RuntimeError(f'分片 {self.index}: 服务端在 {self.port} 起不来（见 .tmp/e2e_shard{self.index}.log）')

    def stop_server(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def run(self):
        try:
            self.start_server()
        except Exception as e:
            for t in self.tools:
                self.results.append({'tool': t, 'rc': 99, 'sec': 0.0, 'note': str(e)})
            return self.results

        for tool in self.tools:
            kill_stale_edge(self._debug_port(tool))
            clean_profiles(tool, True)
            t0 = time.time()
            try:
                p = subprocess.run(['node', f'tools/{tool}.mjs', '--url', self.url],
                                   cwd=str(ROOT), capture_output=True, text=True,
                                   timeout=self.timeout, encoding='utf-8', errors='replace')
                rc, note = p.returncode, ''
                # rc=2 多为"用法错误"；把首行错误带回来便于定位
                if rc not in (0,):
                    tail = [l for l in (p.stdout or '').splitlines() if l.strip()]
                    fails = [l for l in tail if l.startswith('FAIL') or '结果:' in l]
                    note = ' | '.join((fails or tail[-2:])[:3])[:400]
            except subprocess.TimeoutExpired:
                rc, note = 98, f'超时 >{self.timeout}s'
            self.results.append({'tool': tool, 'rc': rc, 'sec': round(time.time() - t0, 1), 'note': note})
            status = 'ok' if rc == 0 else f'rc={rc}'
            print(f'  [S{self.index}] {tool:<34} {status:<7} {self.results[-1]["sec"]}s', flush=True)
        self.stop_server()
        return self.results

    @staticmethod
    def _debug_port(tool):
        """工具用的 CDP 端口，用于清理残留监听进程。"""
        src = (TOOLS / f'{tool}.mjs').read_text(encoding='utf-8', errors='replace')
        m = re.search(r'const\s+PORT\s*=\s*(\d+)', src)
        return int(m.group(1)) if m else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shards', type=int, default=4)
    ap.add_argument('--only', default='')
    ap.add_argument('--skip', default='')
    ap.add_argument('--timeout', type=int, default=420)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--json', default='')
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    tools = discover()
    if args.list:
        for i, t in enumerate(tools):
            kind = 'REPRO' if t.startswith(REPRO_PREFIX) else 'check'
            print(f'{i:>2}  {kind:<6} {t}')
        return 0
    if args.only:
        want = [s.strip() for s in args.only.split(',') if s.strip()]
        tools = [t for t in tools if t in want]
    if args.skip:
        drop = {s.strip() for s in args.skip.split(',') if s.strip()}
        tools = [t for t in tools if t not in drop]

    # 把慢的/重量级的先排进去，让分片尽量同时结束
    order = sorted(tools, key=lambda t: (not t.startswith(('ui_layout_check', 'lobby_check',
                                                          'recent_opponent_check', 'ranked_check',
                                                          'friends_check', 'fluent_style_check')), t))
    shards = [[] for _ in range(max(1, args.shards))]
    for i, t in enumerate(order):
        shards[i % len(shards)].append(t)

    print(f'e2e 批跑：{len(tools)} 个工具 / {len(shards)} 分片 / 每片独立库与端口')
    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=len(shards)) as ex:
        futures = [ex.submit(Shard(i, 5200 + i, sh, args.timeout).run)
                   for i, sh in enumerate(shards) if sh]
        for f in futures:
            results.extend(f.result())

    elapsed = round(time.time() - t0, 1)
    ok = [r for r in results if r['rc'] == 0]
    bad = [r for r in results if r['rc'] != 0]
    checks_bad = [r for r in bad if not r['tool'].startswith(REPRO_PREFIX)]

    print()
    print('=' * 74)
    print(f'总计 {len(results)}：通过 {len(ok)} / 失败 {len(bad)}（其中回归检查失败 {len(checks_bad)}）  耗时 {elapsed}s')
    if bad:
        print('-' * 74)
        for r in sorted(bad, key=lambda r: r['tool']):
            kind = 'REPRO' if r['tool'].startswith(REPRO_PREFIX) else 'CHECK'
            print(f'  [{kind}] {r["tool"]}  rc={r["rc"]}  {r["sec"]}s')
            if r['note']:
                print(f'          {r["note"]}')
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                           encoding='utf-8')
        print(f'详情已写入 {args.json}')
    return 1 if checks_bad else 0


if __name__ == '__main__':
    sys.exit(main())
