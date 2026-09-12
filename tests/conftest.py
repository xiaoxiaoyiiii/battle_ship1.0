# -*- coding: utf-8 -*-
"""测试全局配置。

【为什么需要这个文件】
server.py 里的 `db` 是绑定 `data/battleship.db` 的全局单例，而若干卡牌结算
路径（回光返照等）会真实调用 `db.record_match`。此前直接在仓库里跑
`pytest tests/ -q`，每跑一次都会往**正式库**写几条假对局：
实测量级是「一次全套测试 +5 行 matches/match_logs」，库里已沉淀出数百条
winner_id 为 u1/p1/p2 之类的测试记录（会污染排行榜与战绩查询）。

pytest 会先导入 conftest.py 再收集测试模块，因此在导入 server 之前把
`BATTLESHIP_DB_PATH` 指向临时目录即可完全隔离，仓库里的数据库不再被写。
"""
import os
import pathlib
import tempfile

_TMP_DIR = pathlib.Path(tempfile.mkdtemp(prefix='battleship-test-db-'))
os.environ.setdefault('BATTLESHIP_DB_PATH', str(_TMP_DIR / 'battleship.db'))
