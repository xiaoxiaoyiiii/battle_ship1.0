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

# ── 连锁结算前的展示停留（`server.CHAIN_DISPLAY_DELAY_SECONDS`）：整个 pytest 会话置 0 ──
#
# 为什么必须在**导入 server 之前**就把它关掉：那 1.2 秒是**结算前**的停留
# （`_advance_chain_window` 里"双方都接不了 ⇒ 结算"那条路径），而绝大多数既有用例
# 假设"结算在同一个栈帧里发生"（`room.chain == []` 紧接着断言）。默认开着的话，
# 几千条用例要么变慢、要么一起红 —— 而它们测的其实是"结算发生了"这件事本身。
#
# 关掉之后行为与改动前**逐字节一致**（`_finish_chain` 走回原来那一行
# `resolve_chain(room)`），所以既有用例一个都不用改：
#   · 想验"延迟真的发生"的用例 → `tests/test_chain_display_delay.py`
#     （它自己用 monkeypatch 把常量开回 1.2）；
#   · `tests/test_chain_display_delay.py::test_delay_is_off_for_the_whole_suite`
#     守着这一行 —— 谁把它删掉，那条用例就红。
#
# 走环境变量而不是 import server 改常量：本文件**必须**在 server 被导入之前生效
# （与上面的 `BATTLESHIP_DB_PATH` 同一个理由），而 server.py 里那一个常量读的
# 就是它 —— 全项目仍然只有一处定义。
os.environ.setdefault('CHAIN_DISPLAY_DELAY_SECONDS', '0')
