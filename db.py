import json
import sqlite3
import time
import uuid
import logging
import threading
import os
from pathlib import Path
from werkzeug.security import check_password_hash

# 段位门槛（船长段起始分）只在 `ranks.py` 定义一处；本层只读它，不重写常量。
# `ranks.py` 是纯模块（只依赖 stdlib），所以 db → ranks 这条依赖没有环。
import ranks

# 配置日志（先确保数据目录存在，避免全新环境 import 失败）
_DATA_DIR = Path(__file__).parent / 'data'
_DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_DATA_DIR / 'db.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('database')

# 留言开关的列定义（第 3 批 D 票）。`user_profile` 是第 1 批建的表，生产库里**已经有数据**，
# 而本项目没有 ALTER / 迁移机制 —— 所以 `CREATE TABLE IF NOT EXISTS` 加不上这一列，
# 必须走下面的 `_add_column_if_missing`（见 `Database._migrate_schema` 的说明）。
_GUESTBOOK_COLUMN = 'show_guestbook'
_GUESTBOOK_COLUMN_DDL = 'INTEGER DEFAULT 1'

# 段位开关的列定义（段位批 A 票）。同一条路：`user_profile` 生产库里已有行，
# 必须显式补列。默认 **1 = 公开**（与其它展示开关一致：默认看得见）。
_SHOW_RANK_COLUMN = 'show_rank'
_SHOW_RANK_COLUMN_DDL = 'INTEGER DEFAULT 1'


def _add_column_if_missing(cursor, table: str, column: str, ddl: str) -> bool:
    """幂等加列：PRAGMA table_info 判存在 → ALTER TABLE ADD COLUMN。

    返回 True = 【本次真的加了这一列】，False = 已经有了 / 加不上。

    **为什么必须有这个助手**：本项目只有 `CREATE TABLE IF NOT EXISTS`，没有迁移机制。
    `user_profile` 是第 1 批建的表，生产库里已经有行；对已存在的表再写一遍
    `CREATE TABLE IF NOT EXISTS` 是**空操作**，新列永远不会出现 —— 而读取端
    （`get_user_profile_extra` / `db.set_show_guestbook`）一 SELECT 这一列就会
    `no such column`，表现为**线上 500**。这正是本助手存在的原因。

    **失败只记日志、由调用方决定是否致命**：这里的每一处异常都不往外抛 ——
    `init_db()` 在 import 期就会跑（模块级 `db = Database()`），
    为了一个展示用的开关把整个进程弄崩不值得。加列失败时相关功能降级
    （留言板按"未开放"处理），其余一切照常。

    SQLite 的 `ALTER TABLE ADD COLUMN` 支持带常量默认值（`DEFAULT 1`），
    于是**老行会被自动填成 1**（= 公开，与计划 §3.4 的默认值一致），无需回填 UPDATE。

    ⚠️ 表名/列名会拼进 SQL，只接受本模块内写死的常量（绝不接受调用方传入）。
    """
    if not table.isidentifier() or not column.isidentifier():
        logger.error(f"拒绝为可疑的表/列名加列: table={table!r}, column={column!r}")
        return False
    try:
        rows = cursor.execute(f'PRAGMA table_info({table})').fetchall()
    except sqlite3.Error as e:
        logger.error(f"读取表结构失败，跳过加列: {table}.{column} -> {e}")
        return False
    if not rows:
        logger.warning(f"表不存在，跳过加列: {table}.{column}")
        return False
    # PRAGMA table_info 的列顺序是 (cid, name, type, notnull, dflt_value, pk)
    existing = {row[1] for row in rows}
    if column in existing:
        return False
    try:
        cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
    except sqlite3.Error as e:
        logger.error(f"加列失败（旧库可能被占用或列已存在）: {table}.{column} -> {e}")
        return False
    logger.info(f"已为 {table} 补上新列: {column} {ddl}")
    return True


class Database:
    def __init__(self):
        # BATTLESHIP_DB_PATH 用于把数据库指到别处（测试隔离用）。
        # 此前 pytest 直接跑在仓库里会往正式库写假对局。
        override = os.environ.get('BATTLESHIP_DB_PATH')
        self.db_path = Path(override) if override else (Path(__file__).parent / 'data' / 'battleship.db')
        self.conn = None
        self.cursor = None
        self._lock = threading.RLock()
        try:
            # 确保数据目录存在
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 建立数据库连接
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            # 提升并发健壮性：WAL 模式 + busy_timeout，减少多线程 "database is locked"
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA busy_timeout=5000')
            self.cursor = self.conn.cursor()
            
            # 初始化数据库
            self.init_db()
            logger.info(f"数据库连接成功: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"数据库连接或初始化失败: {e}")
            # 尝试关闭连接
            self.close()
            raise
        except Exception as e:
            logger.error(f"数据库初始化过程中发生未知错误: {e}")
            # 尝试关闭连接
            self.close()
            raise
    
    def init_db(self):
        try:
            # 创建用户表
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS users
                  (
                      id             TEXT PRIMARY KEY,
                      username       TEXT UNIQUE,
                      password_hash  TEXT,
                      wins           INTEGER DEFAULT 0,
                      losses         INTEGER DEFAULT 0,
                      current_streak INTEGER DEFAULT 0,
                      longest_streak INTEGER DEFAULT 0,
                      created_at     INTEGER,
                      signature      TEXT    DEFAULT '',
                      avatar         TEXT    DEFAULT '',
                      token          TEXT    DEFAULT ''
                  )
                  ''')
            
            # 创建比赛表
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS matches
                  (
                      id        TEXT PRIMARY KEY,
                      winner_id TEXT,
                      loser_id  TEXT,
                      timestamp INTEGER
                  )
                  ''')
            
            # 创建聊天消息表
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS chat_messages
                  (
                      id        INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id   TEXT,
                      username  TEXT,
                      content   TEXT,
                      timestamp INTEGER
                  )
                  ''')
            
            # 创建活跃游戏表
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS active_games
                  (
                      user_id    TEXT PRIMARY KEY,
                      room_id    TEXT,
                      updated_at INTEGER
                  )
                  ''')
            
            # 创建比赛日志表
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS match_logs
                  (
                      match_id TEXT PRIMARY KEY,
                      logs     TEXT
                  )
                  ''')

            # 卡牌使用统计（图鉴里显示"用得多不多"，也是后续平衡调整的依据）
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS card_usage
                  (
                      card_name  TEXT PRIMARY KEY,
                      uses       INTEGER NOT NULL DEFAULT 0,
                      updated_at INTEGER
                  )
                  ''')

            # ---- 个人信息名片（2026-09-17 第 1 批）----
            # ⚠️ 本项目**没有 ALTER / 迁移机制**，只有 CREATE TABLE IF NOT EXISTS：
            # 生产库要加字段只能新建表，**不要动 users 表的列**。
            # 这两张表老库启动时自动补齐，不需要停机、不需要迁移脚本。
            # 存的全是**白名单 id**（称号/标签/边框/底色），没有自由文本 ——
            # 于是既注入不了 CSS，也伪造不了称号文字，且不需要任何审核流程。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS user_profile
                  (
                      user_id         TEXT PRIMARY KEY,
                      title_id        TEXT    DEFAULT '',
                      tags            TEXT    DEFAULT '[]',
                      status_text     TEXT    DEFAULT '',
                      frame_id        TEXT    DEFAULT 'none',
                      card_bg_id      TEXT    DEFAULT 'deep',
                      show_stats      INTEGER DEFAULT 1,
                      show_fav_cards  INTEGER DEFAULT 1,
                      show_history    INTEGER DEFAULT 0,
                      updated_at      INTEGER
                  )
                  ''')

            # 个人卡牌使用统计。card_usage 是**全局**表（主键 card_name），
            # 「最爱用的卡」必须按用户统计，所以单开一张。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS user_card_usage
                  (
                      user_id    TEXT,
                      card_name  TEXT,
                      uses       INTEGER NOT NULL DEFAULT 0,
                      updated_at INTEGER,
                      PRIMARY KEY (user_id, card_name)
                  )
                  ''')

            # ---- 徽章 / 成就（2026-09-17 第 2 批）----
            # 每局事实的累计：一次写入发生在**对局结束时**（`server._finalize_match`）。
            # 成就判据大多来自跨局累计，而 users 表只有 wins/losses/连胜，
            # 「累计击沉」「零伤获胜」「最快获胜用时」哪都没存 —— 就是这张表。
            # 同样是「只加新表、不动 users 列」，老库启动自动补齐。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS user_counters
                  (
                      user_id          TEXT PRIMARY KEY,
                      sunk_total       INTEGER DEFAULT 0,
                      matches_played   INTEGER DEFAULT 0,
                      flawless_wins    INTEGER DEFAULT 0,
                      fastest_win_sec  INTEGER DEFAULT 0,
                      updated_at       INTEGER
                  )
                  ''')

            # 已解锁的成就。判据本身可以随时用 achievements.evaluate() 重算，
            # 这张表存的是「**首次**解锁时间」：用于展示（"3 天前解锁"）、排序，
            # 以及"只进不退"（判据后来变小了也不回收）。
            # 主键 (user_id, badge_id) 让重复授予天然幂等 —— INSERT OR IGNORE 即可。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS user_achievements
                  (
                      user_id     TEXT,
                      badge_id    TEXT,
                      unlocked_at INTEGER,
                      PRIMARY KEY (user_id, badge_id)
                  )
                  ''')

            # ---- 等级 / 经验（2026-09-17 追加）----
            # ⚠️ **只存 xp，不存 level**：等级一律由 `leveling.level_from_xp()` 推出来。
            #    存两个字段迟早出现"经验涨了但等级没更新"这种对不上的状态（第 2 批
            #    "同一件事两份实现必然漂移"的教训）。主键就是 user_id，一人一行。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS user_xp
                  (
                      user_id    TEXT PRIMARY KEY,
                      xp         INTEGER NOT NULL DEFAULT 0,
                      updated_at INTEGER
                  )
                  ''')

            # ---- 特权（2026-09-17）----
            # 存放**不靠战绩解锁**的东西：外观全解锁、彩虹渐变名字等。
            # 主键 (user_id, perk) 让授予天然幂等（INSERT OR IGNORE）。
            # ⚠️ **没有自助接口**：只由运维在库里授予 —— 所以"别人不能拥有彩虹名字"
            #    是数据层保证的，而不是前端灰一下（只在前端灰掉等于没做）。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS user_perks
                  (
                      user_id    TEXT,
                      perk       TEXT,
                      granted_at INTEGER,
                      PRIMARY KEY (user_id, perk)
                  )
                  ''')

            # ---- 点赞 / 送花 / 留言板（2026-09-17 第 3 批 D 票）----
            # `profile_likes` 的主键 (from, to, kind) 让"取消再点"天然幂等：
            # 点 = INSERT OR IGNORE，取消 = DELETE。**不存计数列** ——
            # 计数一律 COUNT 出来，避免"计数与明细对不上"这类经典漂移。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS profile_likes
                  (
                      from_user_id TEXT,
                      to_user_id   TEXT,
                      kind         TEXT,
                      created_at   INTEGER,
                      PRIMARY KEY (from_user_id, to_user_id, kind)
                  )
                  ''')

            # 留言板。软删（deleted=1）保留审计：删除接口只改标志位，
            # 行还在表里，`list` 一律带 `deleted = 0` 过滤。
            # `id` 自增主键同时充当**分页游标**：按 id 倒序分页，不依赖
            # created_at（同一秒内连发多条时时间戳会并列，用它分页会跳行/重行）。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS profile_messages
                  (
                      id           INTEGER PRIMARY KEY AUTOINCREMENT,
                      to_user_id   TEXT,
                      from_user_id TEXT,
                      from_name    TEXT,
                      content      TEXT,
                      created_at   INTEGER,
                      deleted      INTEGER DEFAULT 0
                  )
                  ''')

            # ---- 段位（排位积分，段位批 A 票）----
            # 一行一人。**不存"段位等级"** —— 等级/小段位/进度全部由
            # `ranks.py` 从 `points` 现算（单一真相源，避免"分数改了段位没改"）。
            # `is_admiral` 是唯一的例外：大舰长是**动态**称号（要求全服船长数达标），
            # 达标那一刻写 1 之后**不再自动撤销**，但每次读取仍会按门槛复算 ->
            # 见 `ranks.is_admiral`。存这一列是为了"曾经当过大舰长"的审计痕迹。
            # `ranked_wins/losses` 只统计**排位对局**，与人机/自定义房无关。
            self.cursor.execute('''
                  CREATE TABLE IF NOT EXISTS user_rank
                  (
                      user_id      TEXT PRIMARY KEY,
                      points       INTEGER NOT NULL DEFAULT 0,
                      is_admiral   INTEGER NOT NULL DEFAULT 0,
                      ranked_wins  INTEGER NOT NULL DEFAULT 0,
                      ranked_losses INTEGER NOT NULL DEFAULT 0,
                      updated_at   INTEGER
                  )
                  ''')

            # ---- 加列迁移（第 3 批 D 票）----
            # `user_profile` 是第 1 批建的表，生产库已有该表（于是上面的
            # CREATE TABLE IF NOT EXISTS 对它完全无效），而本项目没有 ALTER 迁移机制。
            # 所以 `show_guestbook` 必须在这里**显式**补列：老行由
            # `DEFAULT 1`（= 公开，计划 §3.4）自动填好，不需要回填 UPDATE。
            # 幂等：第一次以后 PRAGMA 就查到列了，直接返回。
            self._migrate_schema()

            self.conn.commit()
            logger.info("数据库表创建成功")

            # 常用查询索引：避免数据增长后战绩/登录查询退化为全表扫描
            for stmt in (
                'CREATE INDEX IF NOT EXISTS idx_matches_winner ON matches(winner_id)',
                'CREATE INDEX IF NOT EXISTS idx_matches_loser ON matches(loser_id)',
                'CREATE INDEX IF NOT EXISTS idx_matches_ts ON matches(timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_users_token ON users(token)',
                'CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages(timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_card_usage_uses ON card_usage(uses DESC)',
                # 「最爱用的卡」= 按 user_id 取 uses 前 3，走这条复合索引
                'CREATE INDEX IF NOT EXISTS idx_user_card_usage_uses '
                'ON user_card_usage(user_id, uses DESC)',
                # 留言板列表 = WHERE to_user_id=? AND deleted=0 AND id<? ORDER BY id DESC，
                # 这条复合索引覆盖前三段（id 是主键，收尾排序由它兜住）
                'CREATE INDEX IF NOT EXISTS idx_profile_messages_box '
                'ON profile_messages(to_user_id, deleted, id DESC)',
                # 「每人对同一人每天 ≤ 20 条」的计数 = WHERE from=? AND to=? AND created_at 区间
                'CREATE INDEX IF NOT EXISTS idx_profile_messages_pair '
                'ON profile_messages(from_user_id, to_user_id, created_at)',
                # 点赞/送花计数 = WHERE to_user_id=? [AND kind=?]
                'CREATE INDEX IF NOT EXISTS idx_profile_likes_to '
                'ON profile_likes(to_user_id, kind)',
                # 段位榜 = ORDER BY points DESC（并列时按 updated_at 定序，
                # 让"同样分数谁先到谁在前"稳定，不随行顺序抖动）
                'CREATE INDEX IF NOT EXISTS idx_user_rank_points '
                'ON user_rank(points DESC, updated_at)',
                # 大舰长门槛要数"全服船长段的人数" = WHERE points >= 2100
                'CREATE INDEX IF NOT EXISTS idx_user_rank_points_asc '
                'ON user_rank(points)',
            ):
                try:
                    self.cursor.execute(stmt)
                except sqlite3.Error as e:
                    logger.warning(f"创建索引失败: {stmt} -> {e}")
            self.conn.commit()
            logger.info("数据库索引创建成功")
            
            # 便于直接查询的视图：match_history
            try:
                self.cursor.execute('''
                    CREATE VIEW IF NOT EXISTS match_history AS
                    SELECT m.id AS match_id,
                           m.winner_id,
                           m.loser_id,
                           m.timestamp,
                           w.username AS winner_name,
                           l.username AS loser_name,
                           ml.logs
                    FROM matches m
                    LEFT JOIN users w ON m.winner_id = w.id
                    LEFT JOIN users l ON m.loser_id = l.id
                    LEFT JOIN match_logs ml ON ml.match_id = m.id
                ''')
                self.conn.commit()
                logger.info("match_history视图创建成功")
            except sqlite3.Error as e:
                # 视图创建失败不影响核心功能
                logger.warning(f"创建match_history视图失败: {e}")
        except sqlite3.Error as e:
            logger.error(f"创建数据库表失败: {e}")
            # 回滚事务
            if self.conn:
                self.conn.rollback()
            raise
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            # 回滚事务
            if self.conn:
                self.conn.rollback()
            raise
    
    def _migrate_schema(self):
        """给**已存在的老表**补新列（本项目唯一的迁移入口，`init_db()` 里跑一次）。

        **为什么不能靠 `CREATE TABLE IF NOT EXISTS`**：那一句对已存在的表是空操作。
        `user_profile` 是第 1 批建的表，生产库里已经有行 —— 想往它上面加
        `show_guestbook`，只有 `ALTER TABLE ... ADD COLUMN` 一条路。
        写错这一步的症状是**线上 500**（读端一 SELECT 新列就 `no such column`），
        而不是启动报错，所以特意放在 `init_db()` 里、且**幂等**。

        幂等性：`_add_column_if_missing` 先用 `PRAGMA table_info` 查列，
        已经有了就直接返回 —— 每次启动多跑一次也只是一次 PRAGMA。

        失败策略：只记日志、绝不往外抛。这个方法在 import 期（模块级 `db = Database()`）
        就会执行，为了一个展示开关把进程打崩不值得；加列失败时留言板按"未开放"降级。
        """
        self._add_column_if_missing('user_profile', _GUESTBOOK_COLUMN, _GUESTBOOK_COLUMN_DDL)
        self._add_column_if_missing('user_profile', _SHOW_RANK_COLUMN, _SHOW_RANK_COLUMN_DDL)

    def _add_column_if_missing(self, table: str, column: str, ddl: str) -> bool:
        """`ALTER TABLE ADD COLUMN` 的幂等包装（见模块级 `_add_column_if_missing`）。"""
        try:
            with self._lock:
                return _add_column_if_missing(self.cursor, table, column, ddl)
        except Exception as e:      # noqa: BLE001 —— 迁移失败不许影响启动
            logger.error(f"加列迁移异常，已跳过: {table}.{column} -> {e}")
            return False

    def clear_temp_data(self):
        """重启时清空临时数据"""
        try:
            with self._lock:
                self.cursor.execute('DELETE FROM active_games')
                self.cursor.execute("UPDATE users SET token = ''")
                self.conn.commit()
            logger.info("临时数据清除成功")
        except sqlite3.Error as e:
            logger.error(f"清除临时数据失败: {e}")
            # 回滚事务
            if self.conn:
                self.conn.rollback()
        except Exception as e:
            logger.error(f"清除临时数据时发生未知错误: {e}")
            # 回滚事务
            if self.conn:
                self.conn.rollback()
    
    # users 表允许被通用更新方法写入的列白名单：
    # 列名会拼进 SQL，必须白名单化，避免调用方传入用户可控的列名造成注入。
    _ALLOWED_USER_COLUMNS = frozenset({
        'username', 'password_hash', 'signature', 'avatar', 'token',
        'wins', 'losses', 'current_streak', 'longest_streak',
    })

    def update_user(self, uid: str, **kwargs):
        """通用更新用户信息"""
        if not kwargs:
            return True

        if not uid:
            logger.warning("尝试更新用户信息但未提供用户ID")
            return False

        invalid = [k for k in kwargs if k not in self._ALLOWED_USER_COLUMNS]
        if invalid:
            logger.error(f"更新用户信息时出现非法字段: {uid}, 字段: {invalid}")
            return False

        try:
            query = 'UPDATE users SET ' + ', '.join([f"{k} = ?" for k in kwargs.keys()]) + ' WHERE id = ?'
            params = list(kwargs.values()) + [uid]
            with self._lock:
                self.cursor.execute(query, params)
                self.conn.commit()
            logger.info(f"成功更新用户信息: {uid}, 更新字段: {list(kwargs.keys())}")
            return True
        except sqlite3.IntegrityError as e:
            logger.error(f"更新用户信息时违反完整性约束: {uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except sqlite3.Error as e:
            logger.error(f"更新用户信息时发生数据库错误: {uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"更新用户信息时发生未知错误: {uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
    
    def get_user(self, uid="", username=""):
        """通用获取用户信息"""
        try:
            # 使用独立的游标避免递归使用游标错误
            cursor = self.conn.cursor()
            
            if uid:
                cursor.execute('SELECT * FROM users WHERE id = ?', (uid,))
                row = cursor.fetchone()
                logger.debug(f"根据ID查询用户: {uid}, 结果: {'找到' if row else '未找到'}")
            elif username:
                cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
                row = cursor.fetchone()
                logger.debug(f"根据用户名查询用户: {username}, 结果: {'找到' if row else '未找到'}")
            else:
                logger.warning("尝试获取用户信息但未提供ID或用户名")
                cursor.close()
                return None
            
            cursor.close()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"查询用户信息时发生数据库错误: ID={uid}, 用户名={username}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"查询用户信息时发生未知错误: ID={uid}, 用户名={username}, 错误: {e}")
            return None
    
    def get_user_by_token(self, token: str):
        """通过token获取用户信息"""
        if not token:
            logger.warning("尝试通过空token获取用户信息")
            return None
        
        try:
            # 使用独立的游标避免递归使用游标错误
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM users WHERE token = ?', (token,))
            row = cursor.fetchone()
            cursor.close()
            
            logger.debug(f"根据token查询用户: {token}, 结果: {'找到' if row else '未找到'}")
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"通过token查询用户时发生数据库错误: token={token}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"通过token查询用户时发生未知错误: token={token}, 错误: {e}")
            return None
    
    def save_active_game(self, uid: str, room_id: str):
        if not uid or not room_id:
            logger.warning(f"尝试保存活跃游戏但参数不完整: uid={uid}, room_id={room_id}")
            return False
            
        try:
            with self._lock:
                self.cursor.execute('INSERT OR REPLACE INTO active_games (user_id, room_id, updated_at) VALUES (?, ?, ?)',
                             (uid, room_id, int(time.time())))
                self.conn.commit()
            logger.debug(f"成功保存活跃游戏: uid={uid}, room_id={room_id}")
            return True
        except sqlite3.Error as e:
            logger.error(f"保存活跃游戏时发生数据库错误: uid={uid}, room_id={room_id}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"保存活跃游戏时发生未知错误: uid={uid}, room_id={room_id}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
    
    def get_active_game(self, uid: str):
        if not uid:
            logger.warning("尝试获取活跃游戏但未提供用户ID")
            return None
            
        try:
            # 使用独立的游标避免递归使用游标错误
            cursor = self.conn.cursor()
            cursor.execute('SELECT room_id FROM active_games WHERE user_id = ?', (uid,))
            row = cursor.fetchone()
            cursor.close()
            
            logger.debug(f"获取活跃游戏: uid={uid}, 结果: {'找到' if row else '未找到'}")
            return row
        except sqlite3.Error as e:
            logger.error(f"获取活跃游戏时发生数据库错误: uid={uid}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"获取活跃游戏时发生未知错误: uid={uid}, 错误: {e}")
            return None
    
    def update_user_signature(self, uid: str, signature: str):
        if not uid:
            logger.warning("尝试更新用户签名但未提供用户ID")
            return False
            
        try:
            # 确保签名长度合理（防止过长）
            safe_signature = signature[:500] if signature else ''
            with self._lock:
                self.cursor.execute('UPDATE users SET signature = ? WHERE id = ?', (safe_signature, uid))
                self.conn.commit()
            logger.info(f"成功更新用户签名: uid={uid}")
            return True
        except sqlite3.IntegrityError as e:
            logger.error(f"更新用户签名时违反完整性约束: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except sqlite3.Error as e:
            logger.error(f"更新用户签名时发生数据库错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"更新用户签名时发生未知错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
    
    def update_user_avatar(self, uid: str, avatar_path: str):
        if not uid:
            logger.warning("尝试更新用户头像但未提供用户ID")
            return False
            
        try:
            with self._lock:
                self.cursor.execute('UPDATE users SET avatar = ? WHERE id = ?', (avatar_path, uid))
                self.conn.commit()
            logger.info(f"成功更新用户头像: uid={uid}")
            return True
        except sqlite3.IntegrityError as e:
            logger.error(f"更新用户头像时违反完整性约束: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except sqlite3.Error as e:
            logger.error(f"更新用户头像时发生数据库错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"更新用户头像时发生未知错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
    
    def update_user_password(self, uid: str, password_hash: str):
        if not uid or not password_hash:
            logger.warning(f"尝试更新用户密码但参数不完整: uid={uid}, password_hash={password_hash}")
            return False
            
        try:
            with self._lock:
                self.cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, uid))
                self.conn.commit()
            logger.info(f"成功更新用户密码: uid={uid}")
            return True
        except sqlite3.IntegrityError as e:
            logger.error(f"更新用户密码时违反完整性约束: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except sqlite3.Error as e:
            logger.error(f"更新用户密码时发生数据库错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"更新用户密码时发生未知错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
    
    def get_user_profile(self, uid: str):
        if not uid:
            logger.warning("尝试获取用户资料但未提供用户ID")
            return None
            
        try:
            # 使用独立的游标避免递归使用游标错误
            cursor = self.conn.cursor()
            cursor.execute('SELECT id, username, signature, avatar FROM users WHERE id = ?', (uid,))
            row = cursor.fetchone()
            cursor.close()
            
            logger.debug(f"获取用户资料: uid={uid}, 结果: {'找到' if row else '未找到'}")
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"获取用户资料时发生数据库错误: uid={uid}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"获取用户资料时发生未知错误: uid={uid}, 错误: {e}")
            return None
    
    def add_chat_message(self, user_id: str, username: str, content: str):
        if not content:
            logger.warning("尝试添加空的聊天消息")
            return False
            
        try:
            # 确保内容长度合理，防止过长消息
            safe_content = content[:500] if content else ''
            safe_username = username[:50] if username else '匿名'
            
            with self._lock:
                self.cursor.execute('INSERT INTO chat_messages (user_id, username, content, timestamp) VALUES (?, ?, ?, ?)',
                             (user_id, safe_username, safe_content, int(time.time())))
                self.conn.commit()
            logger.debug(f"成功添加聊天消息: user_id={user_id}, username={safe_username}")
            return True
        except sqlite3.Error as e:
            logger.error(f"添加聊天消息时发生数据库错误: user_id={user_id}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"添加聊天消息时发生未知错误: user_id={user_id}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
    
    def get_chat_messages(self, limit=50):
        try:
            # 确保limit在合理范围内
            safe_limit = min(max(1, limit), 100)  # 限制在1-100之间
            # 用独立游标：共享 self.cursor 在并发（eventlet 协程）下会与写操作错位
            with self._lock:
                cursor = self.conn.cursor()
                rows = cursor.execute(
                    'SELECT * FROM chat_messages ORDER BY timestamp DESC LIMIT ?',
                    (safe_limit,)).fetchall()
                cursor.close()
            result = [dict(r) for r in rows][::-1]  # 倒序排列，最新的在最后
            logger.debug(f"获取聊天消息: limit={safe_limit}, 结果数量={len(result)}")
            return result
        except sqlite3.Error as e:
            logger.error(f"获取聊天消息时发生数据库错误: limit={limit}, 错误: {e}")
            return []
        except Exception as e:
            logger.error(f"获取聊天消息时发生未知错误: limit={limit}, 错误: {e}")
            return []
    
    def create_user(self, username: str, password_hash: str):
        if not username or not password_hash:
            logger.warning("尝试创建用户但用户名或密码哈希为空")
            return None
            
        try:
            # 验证用户名长度
            if len(username) < 3:
                logger.warning(f"用户名太短: {username}")
                return None
                
            # 验证用户名是否包含非法字符（简单验证）
            if not all(c.isalnum() or c in '._-' for c in username):
                logger.warning(f"用户名包含非法字符: {username}")
                return None
                
            uid = str(uuid.uuid4())
            with self._lock:
                self.cursor.execute('INSERT INTO users (id, username, password_hash, created_at) VALUES (?,?,?,?)',
                             (uid, username, password_hash, int(time.time())))
                self.conn.commit()
            logger.info(f"成功创建用户: username={username}, uid={uid}")
            return uid
        except sqlite3.IntegrityError as e:
            logger.error(f"创建用户时用户名重复: {username}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return None
        except sqlite3.Error as e:
            logger.error(f"创建用户时发生数据库错误: {username}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return None
        except Exception as e:
            logger.error(f"创建用户时发生未知错误: {username}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return None
    
    def record_match(self, winner_id: str, loser_id: str, logs=None, count_stats=True):
        """写入一条对局记录。

        count_stats=False 时只写历史（matches / match_logs），不更新任何用户的
        胜场、负场与连胜 —— 人机对局走这条路：打得再多也刷不了排行榜。
        """
        if not winner_id or not loser_id:
            logger.warning(f"尝试记录比赛但获胜者或失败者ID为空: winner_id={winner_id}, loser_id={loser_id}")
            return False
            
        self._lock.acquire()
        try:
            # 记录比赛结果（依赖连接隐式事务 + 末尾 commit 保证原子性，避免显式 BEGIN 冲突）
            mid = str(uuid.uuid4())
            t = int(time.time())
            self.cursor.execute('INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
                      (mid, winner_id, loser_id, t))

            # 记录局内日志（可选）
            if logs is not None:
                try:
                    logs_json = json.dumps(logs, ensure_ascii=False)
                    self.cursor.execute('INSERT OR REPLACE INTO match_logs (match_id, logs) VALUES (?, ?)', (mid, logs_json))
                    logger.debug(f"成功记录比赛日志: match_id={mid}")
                except json.JSONDecodeError as e:
                    logger.error(f"比赛日志序列化失败: match_id={mid}, 错误: {e}")
                except sqlite3.Error as e:
                    logger.error(f"保存比赛日志时发生数据库错误: match_id={mid}, 错误: {e}")
                except Exception as e:
                    logger.error(f"记录比赛日志时发生未知错误: match_id={mid}, 错误: {e}")

            # 增加胜负统计与连胜逻辑（count_stats=False 的人机对局跳过这一段）
            if count_stats:
                # 先取目前的 streak 值以便更新 longest_streak
                winner = self.cursor.execute('SELECT current_streak, longest_streak FROM users WHERE id = ?', (winner_id,)).fetchone()
                if winner:
                    new_streak = (winner['current_streak'] or 0) + 1
                    new_longest = max(new_streak, (winner['longest_streak'] or 0))
                    self.cursor.execute('UPDATE users SET wins = wins + 1, current_streak = ?, longest_streak = ? WHERE id = ?',
                              (new_streak, new_longest, winner_id))
                else:
                    # 如果用户不存在（可能是游客），仍允许插入 match 但不更新 stats
                    logger.debug(f"比赛获胜者不存在于用户表: {winner_id}")

                loser = self.cursor.execute('SELECT * FROM users WHERE id = ?', (loser_id,)).fetchone()
                if loser:
                    self.cursor.execute('UPDATE users SET losses = losses + 1, current_streak = 0 WHERE id = ?', (loser_id,))
                else:
                    # 如果用户不存在（可能是游客），仍允许插入 match 但不更新 stats
                    logger.debug(f"比赛失败者不存在于用户表: {loser_id}")
            else:
                logger.debug(f"人机对局仅记录历史，不计入战绩: match_id={mid}")

            # 提交事务
            self.conn.commit()
            logger.info(f"成功记录比赛: match_id={mid}, winner_id={winner_id}, loser_id={loser_id}")
            return True
        except sqlite3.Error as e:
            logger.error(f"记录比赛时发生数据库错误: winner_id={winner_id}, loser_id={loser_id}, 错误: {e}")
            # 回滚事务
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"记录比赛时发生未知错误: winner_id={winner_id}, loser_id={loser_id}, 错误: {e}")
            # 回滚事务
            if self.conn:
                self.conn.rollback()
            return False
        finally:
            self._lock.release()
    
    def get_match_history(self, uid: str, limit=20):
        if not uid:
            logger.warning("尝试获取比赛历史但未提供用户ID")
            return []
            
        try:
            # 确保limit在合理范围内
            safe_limit = min(max(1, limit), 100)  # 限制在1-100之间
            
            # 使用独立的游标避免递归使用游标错误
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT m.id,
                       m.winner_id,
                       m.loser_id,
                       m.timestamp,
                       w.username AS winner_name,
                       l.username AS loser_name,
                       ml.logs
                FROM matches m
                LEFT JOIN users w ON m.winner_id = w.id
                LEFT JOIN users l ON m.loser_id = l.id
                LEFT JOIN match_logs ml ON ml.match_id = m.id
                WHERE m.winner_id = ? OR m.loser_id = ?
                ORDER BY m.timestamp DESC
                LIMIT ?
            ''', (uid, uid, safe_limit))
            rows = cursor.fetchall()
            cursor.close()
            
            history = []
            for r in rows:
                logs = []
                if r['logs']:
                    try:
                        logs = json.loads(r['logs'])
                    except json.JSONDecodeError as e:
                        logger.error(f"解析比赛日志失败: match_id={r['id']}, 错误: {e}")
                        logs = []
                    except Exception as e:
                        logger.error(f"处理比赛日志时发生未知错误: match_id={r['id']}, 错误: {e}")
                        logs = []
                
                history.append({
                    'match_id': r['id'],
                    'winner_id': r['winner_id'],
                    'loser_id': r['loser_id'],
                    'timestamp': r['timestamp'],
                    'winner_name': r['winner_name'],
                    'loser_name': r['loser_name'],
                    'logs': logs
                })
                
            logger.debug(f"获取用户比赛历史: uid={uid}, 结果数量={len(history)}, limit={safe_limit}")
            return history
        except sqlite3.Error as e:
            logger.error(f"获取比赛历史时发生数据库错误: uid={uid}, limit={limit}, 错误: {e}")
            return []
        except Exception as e:
            logger.error(f"获取比赛历史时发生未知错误: uid={uid}, limit={limit}, 错误: {e}")
            return []
    
    def record_card_use(self, card_name, count=1):
        """记一次卡牌使用。失败只记日志，绝不影响对局。"""
        if not card_name:
            return False
        try:
            with self._lock:
                self.cursor.execute(
                    'INSERT INTO card_usage (card_name, uses, updated_at) VALUES (?, ?, ?) '
                    'ON CONFLICT(card_name) DO UPDATE SET uses = uses + excluded.uses, '
                    'updated_at = excluded.updated_at',
                    (str(card_name), int(count), int(time.time())))
                self.conn.commit()
            return True
        except Exception as e:
            # 统计失败绝不能影响对局流程（属性名写错 / 库被锁等一并兜住）
            logger.error(f"记录卡牌使用失败: {card_name} -> {e}")
            return False

    def get_card_usage(self):
        """全部卡牌使用次数：{卡名: 次数}。读失败返回空字典。"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT card_name, uses FROM card_usage')
            rows = cursor.fetchall()
            cursor.close()
            return {r['card_name']: r['uses'] for r in rows}
        except sqlite3.Error as e:
            logger.error(f"读取卡牌使用统计失败: {e}")
            return {}

    def _get_leaderboard(self, limit=10):
        try:
            # 确保limit在合理范围内
            safe_limit = min(max(1, limit), 100)  # 限制在1-100之间
            
            # 使用独立的游标避免递归使用游标错误
            cursor = self.conn.cursor()
            cursor.execute(
                # 过滤掉一场都没打过的账号：人机对局已不计入统计，新注册账号
                # 全是 0 胜 0 负，不过滤的话排行榜前列会被它们占满。
                'SELECT id, username, wins, losses, current_streak, longest_streak, avatar '
                'FROM users WHERE (COALESCE(wins, 0) + COALESCE(losses, 0)) > 0 '
                'ORDER BY wins DESC, longest_streak DESC LIMIT ?',
                (safe_limit,))
            rows = cursor.fetchall()
            cursor.close()
            
            result = [dict(r) for r in rows]
            logger.debug(f"获取排行榜基础数据: limit={safe_limit}, 结果数量={len(result)}")
            return result
        except sqlite3.Error as e:
            logger.error(f"获取排行榜基础数据时发生数据库错误: limit={limit}, 错误: {e}")
            return []
        except Exception as e:
            logger.error(f"获取排行榜基础数据时发生未知错误: limit={limit}, 错误: {e}")
            return []

    def get_leaderboard(self, limit=10):
        """获取排行榜 - 保持接口兼容性"""
        try:
            return self._get_leaderboard(limit)
        except Exception as e:
            logger.error(f"获取排行榜数据时发生未知错误: limit={limit}, 错误: {e}")
            return []

    def get_user_rank(self, uid: str):
        """某个账号的排行榜名次（1 起）。查不到返回 None。

        排序口径必须与 `_get_leaderboard` 完全一致（wins DESC, longest_streak DESC，
        且只统计真打过一局的账号），否则"个人信息里的名次"和排行榜页对不上。
        用 COUNT(*) 直接算严格在前的账号数，榜外账号（limit 之外）也能拿到名次 ——
        不能再靠"取前 100 名找自己"那套，那样榜外只会显示"—"。
        """
        if not uid:
            return None
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT wins, longest_streak FROM users WHERE id = ?', (uid,)).fetchone()
            if not row:
                cursor.close()
                return None
            cursor.execute(
                'SELECT COUNT(*) AS ahead FROM users '
                'WHERE (COALESCE(wins, 0) + COALESCE(losses, 0)) > 0 '
                'AND (COALESCE(wins, 0) > ? '
                '     OR (COALESCE(wins, 0) = ? AND COALESCE(longest_streak, 0) > ?))',
                (row['wins'] or 0, row['wins'] or 0, row['longest_streak'] or 0))
            ahead = cursor.fetchone()
            cursor.close()
            return int(ahead['ahead'] or 0) + 1
        except sqlite3.Error as e:
            logger.error(f"查询排行榜名次时发生数据库错误: uid={uid}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"查询排行榜名次时发生未知错误: uid={uid}, 错误: {e}")
            return None

    # ------------------------------------------------------------------
    # 个人信息名片（2026-09-17 第 1 批）
    # ------------------------------------------------------------------
    # 风格：全部「失败只记日志、返回安全默认值」—— 名片是展示层，任何一次
    # 读写失败都不该让页面或对局崩掉。
    _PROFILE_DEFAULTS = {
        'title_id': '',
        'tags': '[]',
        'status_text': '',
        'frame_id': 'none',
        'card_bg_id': 'deep',
        'show_stats': 1,
        'show_fav_cards': 1,
        'show_history': 0,      # 隐私默认：对局历史不公开
        # 留言板是否公开（第 3 批）。计划 §3.4：**默认公开**。
        # ⚠️ 这一列在第 1 批建表时不存在，由 `_migrate_schema()` 用 ALTER 补上 ——
        # 老行拿到的是 `DEFAULT 1`，与这里的默认值一致（都表示"公开"）。
        'show_guestbook': 1,
        # 段位是否公开（段位批）。**默认公开**；同样靠 `_migrate_schema()` 加列。
        'show_rank': 1,
    }

    def _profile_defaults(self, uid: str) -> dict:
        """没记录时的默认名片（**不写库**）。tags 直接给已解析的空列表。"""
        row = dict(self._PROFILE_DEFAULTS)
        row['user_id'] = uid
        row['tags'] = []
        row['updated_at'] = 0
        return row

    def get_user_profile_extra(self, uid: str) -> dict:
        """读名片个性字段。没有记录时返回默认值（不写库）。"""
        if not uid:
            return self._profile_defaults(uid)
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT title_id, tags, status_text, frame_id, card_bg_id, '
                'show_stats, show_fav_cards, show_history, show_guestbook, show_rank, updated_at '
                'FROM user_profile WHERE user_id = ?', (uid,)).fetchone()
            cursor.close()
            if not row:
                return self._profile_defaults(uid)
            data = {k: row[k] for k in row.keys()}
            data['user_id'] = uid
            data['tags'] = self._parse_tags(data.get('tags'))
            for flag in ('show_stats', 'show_fav_cards', 'show_history', 'show_guestbook', 'show_rank'):
                data[flag] = 1 if data.get(flag) is None else int(data[flag])
            data['updated_at'] = int(data.get('updated_at') or 0)
            return data
        except sqlite3.Error as e:
            logger.error(f"读取个人名片失败: uid={uid}, 错误: {e}")
            return self._profile_defaults(uid)
        except Exception as e:
            logger.error(f"读取个人名片时发生未知错误: uid={uid}, 错误: {e}")
            return self._profile_defaults(uid)

    def set_show_guestbook(self, uid: str, on) -> bool:
        """单独写入「留言板是否公开」（第 3 批）。

        ⚠️ **正常路径不走这个方法**：第 3 批的契约把 `show_guestbook` 并进了
        `POST /api/profile/card`（9 个字段全发），由 `save_user_profile_extra`
        整行写入 —— 与另外三个展示开关同一条通道（同进同出，避免"保存了没生效"）。
        这里保留一个"只改这一列"的入口，供不需要整行写入的调用方（运维脚本、
        以后的"快速开关"）使用；它**不碰其余列**，不会把名片其它字段冲掉。
        """
        if not uid:
            logger.warning("尝试保存留言板开关但未提供用户ID")
            return False
        flag = 1 if on in (1, True, '1') else 0
        try:
            with self._lock:
                self.cursor.execute(
                    'INSERT INTO user_profile (user_id, show_guestbook, updated_at) '
                    'VALUES (?, ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET '
                    'show_guestbook = excluded.show_guestbook, updated_at = excluded.updated_at',
                    (uid, flag, int(time.time())))
                self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"保存留言板开关失败: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"保存留言板开关时发生未知错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def set_show_rank(self, uid: str, on) -> bool:
        """单独写入「段位是否公开」（段位批 A 票）。

        ⚠️ 与 `set_show_guestbook` 同样的定位：**正常路径不走这里**。
        `show_rank` 并进了 `POST /api/profile/card`（10 个字段全发），由
        `save_user_profile_extra` 整行写入。这里只留一个"只改这一列"的运维入口。
        """
        if not uid:
            logger.warning("尝试保存段位开关但未提供用户ID")
            return False
        flag = 1 if on in (1, True, '1') else 0
        try:
            with self._lock:
                self.cursor.execute(
                    'INSERT INTO user_profile (user_id, show_rank, updated_at) '
                    'VALUES (?, ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET '
                    'show_rank = excluded.show_rank, updated_at = excluded.updated_at',
                    (uid, flag, int(time.time())))
                self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"保存段位开关失败: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"保存段位开关时发生未知错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    @staticmethod
    def _parse_tags(raw):
        """tags 列是 JSON 数组文本。脏数据（非数组 / 非法 JSON）一律当空。"""
        if isinstance(raw, list):
            return [str(t) for t in raw if isinstance(t, str)]
        try:
            parsed = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            logger.warning(f"名片 tags 解析失败，按空处理: {raw!r}")
            return []
        if not isinstance(parsed, list):
            return []
        return [t for t in parsed if isinstance(t, str)]

    def save_user_profile_extra(self, uid: str, fields: dict) -> bool:
        """UPSERT 写入名片字段（写操作持锁）。

        只接受 `_PROFILE_DEFAULTS` 里的列名 —— 调用方即使传了别的键也写不进去，
        避免把列名拼进 SQL。缺的键用默认值补齐（整行语义，不做部分更新）。
        """
        if not uid:
            logger.warning("尝试保存个人名片但未提供用户ID")
            return False
        fields = fields if isinstance(fields, dict) else {}
        row = dict(self._PROFILE_DEFAULTS)
        for key in self._PROFILE_DEFAULTS:
            if key in fields:
                row[key] = fields[key]
        # tags 列表 → JSON 文本；非法结构一律落成 '[]'
        tags = row.get('tags')
        row['tags'] = json.dumps([t for t in tags if isinstance(t, str)],
                                 ensure_ascii=False) if isinstance(tags, list) else '[]'
        for flag in ('show_stats', 'show_fav_cards', 'show_history', 'show_guestbook', 'show_rank'):
            row[flag] = 1 if row[flag] in (1, True, '1') else 0
        try:
            with self._lock:
                self.cursor.execute(
                    'INSERT INTO user_profile '
                    '(user_id, title_id, tags, status_text, frame_id, card_bg_id, '
                    ' show_stats, show_fav_cards, show_history, show_guestbook, show_rank, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET '
                    'title_id = excluded.title_id, tags = excluded.tags, '
                    'status_text = excluded.status_text, frame_id = excluded.frame_id, '
                    'card_bg_id = excluded.card_bg_id, show_stats = excluded.show_stats, '
                    'show_fav_cards = excluded.show_fav_cards, '
                    'show_history = excluded.show_history, '
                    'show_guestbook = excluded.show_guestbook, '
                    'show_rank = excluded.show_rank, '
                    'updated_at = excluded.updated_at',
                    (uid, str(row['title_id'] or ''), row['tags'],
                     str(row['status_text'] or ''), str(row['frame_id'] or 'none'),
                     str(row['card_bg_id'] or 'deep'), row['show_stats'],
                     row['show_fav_cards'], row['show_history'], row['show_guestbook'],
                     row['show_rank'],
                     int(time.time())))
                self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"保存个人名片失败: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"保存个人名片时发生未知错误: uid={uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def record_user_card_use(self, uid: str, card_name: str, count: int = 1) -> bool:
        """某个账号打出某张卡的次数 +count。失败只记日志，绝不影响对局。"""
        if not uid or not card_name:
            return False
        try:
            with self._lock:
                self.cursor.execute(
                    'INSERT INTO user_card_usage (user_id, card_name, uses, updated_at) '
                    'VALUES (?, ?, ?, ?) '
                    'ON CONFLICT(user_id, card_name) DO UPDATE SET '
                    'uses = uses + excluded.uses, updated_at = excluded.updated_at',
                    (str(uid), str(card_name), int(count), int(time.time())))
                self.conn.commit()
            return True
        except Exception as e:
            # 与全局 card_usage 同一口径：统计失败绝不能影响对局流程
            logger.error(f"记录个人卡牌使用失败: uid={uid}, {card_name} -> {e}")
            return False

    def get_user_card_usage(self, uid: str, limit: int = 3) -> list:
        """某人最常用的卡：[{"name","uses"}]，按 uses DESC（并列时按卡名稳定排序）。"""
        if not uid:
            return []
        try:
            safe_limit = min(max(1, int(limit)), 20)
        except (TypeError, ValueError):
            safe_limit = 3
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'SELECT card_name, uses FROM user_card_usage WHERE user_id = ? '
                'ORDER BY uses DESC, card_name ASC LIMIT ?', (uid, safe_limit))
            rows = cursor.fetchall()
            cursor.close()
            return [{'name': r['card_name'], 'uses': int(r['uses'] or 0)} for r in rows]
        except sqlite3.Error as e:
            logger.error(f"读取个人卡牌统计失败: uid={uid}, 错误: {e}")
            return []
        except Exception as e:
            logger.error(f"读取个人卡牌统计时发生未知错误: uid={uid}, 错误: {e}")
            return []

    def get_user_card_uses_total(self, uid: str) -> int:
        """个人累计出牌次数（称号「卡牌大师」的判据）。读失败返回 0。"""
        if not uid:
            return 0
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT COALESCE(SUM(uses), 0) AS total FROM user_card_usage '
                'WHERE user_id = ?', (uid,)).fetchone()
            cursor.close()
            return int(row['total'] or 0) if row else 0
        except sqlite3.Error as e:
            logger.error(f"读取个人累计出牌失败: uid={uid}, 错误: {e}")
            return 0
        except Exception as e:
            logger.error(f"读取个人累计出牌时发生未知错误: uid={uid}, 错误: {e}")
            return 0

    # ------------------------------------------------------------------
    # 徽章 / 成就（2026-09-17 第 2 批）
    # ------------------------------------------------------------------
    # 同样沿用第 1 批的风格：读失败返回安全默认值、写失败只记日志返回 False ——
    # 统计是"附带的"，绝不允许它把对局结算搞崩。
    #
    # 契约见 docs/BATCH_2_3_4_PLAN.md §2.2.1（A 票实现，B/C 票按此调用）：
    #   get_user_counters / bump_user_counters / get_user_achievements /
    #   grant_user_achievements / get_distinct_cards_used
    _COUNTER_DEFAULTS = {
        'sunk_total': 0,
        'matches_played': 0,
        'flawless_wins': 0,
        'fastest_win_sec': 0,
    }
    # 可累加的列（fastest_win_sec 是「取最小非零」，单独处理，不在这里）
    _COUNTER_ADD_FIELDS = ('sunk_total', 'matches_played', 'flawless_wins')

    def _counters_defaults(self, uid: str) -> dict:
        """没记录时的默认计数（**不写库**）—— 与 user_profile 的做法一致。"""
        row = dict(self._COUNTER_DEFAULTS)
        row['user_id'] = uid
        row['updated_at'] = 0
        return row

    def get_user_counters(self, uid: str) -> dict:
        """读每局累计计数。没有记录时返回全 0 默认值（不写库）。"""
        if not uid:
            return self._counters_defaults(uid)
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT sunk_total, matches_played, flawless_wins, '
                'fastest_win_sec, updated_at FROM user_counters WHERE user_id = ?',
                (uid,)).fetchone()
            cursor.close()
            if not row:
                return self._counters_defaults(uid)
            data = {k: row[k] for k in row.keys()}
            data['user_id'] = uid
            # 老行可能是 NULL（列有 DEFAULT 但显式写过 NULL），统一夹成非负整数
            for key in self._COUNTER_DEFAULTS:
                data[key] = max(0, int(data.get(key) or 0))
            data['updated_at'] = int(data.get('updated_at') or 0)
            return data
        except sqlite3.Error as e:
            logger.error(f"读取每局计数失败: uid={uid}, 错误: {e}")
            return self._counters_defaults(uid)
        except Exception as e:
            logger.error(f"读取每局计数时发生未知错误: uid={uid}, 错误: {e}")
            return self._counters_defaults(uid)

    def bump_user_counters(self, uid: str, **deltas) -> bool:
        """累加式更新每局计数（UPSERT，写操作持锁）。只在 `_finalize_match` 里调。

        · `sunk_total` / `matches_played` / `flawless_wins`：**加** delta（只接受非负整数；
          负数视为调用方 bug，记日志后忽略 —— 统计只增不减，否则负数会静默倒扣徽章进度）。
        · `fastest_win_sec`：**取最小非零**。0 / None / 负数一律表示"这一局没有可信用时
          （或该玩家没赢）"，不参与比较 —— 否则第一次写入的 0 会永远压死后面的真实用时，
          「闪电战」就再也解不开了。

        没有任何可写的 delta 时返回 True（"无事可做"不是失败）。
        """
        if not uid:
            logger.warning("尝试累加每局计数但未提供用户ID")
            return False

        unknown = [k for k in deltas if k not in self._COUNTER_DEFAULTS]
        if unknown:
            # 不抛异常：调用方多传了键不该让整局结算失败，但必须留下痕迹
            logger.warning(f"累加每局计数收到未知字段（已忽略）: uid={uid}, keys={unknown}")

        adds = {}
        for key in self._COUNTER_ADD_FIELDS:
            if key not in deltas:
                continue
            raw = deltas[key]
            if raw is None:
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                logger.warning(f"每局计数 {key} 不是整数（已忽略）: uid={uid}, value={raw!r}")
                continue
            if value < 0:
                logger.warning(f"每局计数 {key} 收到负数（已忽略）: uid={uid}, value={value}")
                continue
            if value:
                adds[key] = value

        fastest = 0
        if 'fastest_win_sec' in deltas and deltas['fastest_win_sec'] is not None:
            try:
                candidate = int(deltas['fastest_win_sec'])
            except (TypeError, ValueError):
                logger.warning(f"最快获胜用时不是整数（已忽略）: uid={uid}, value={deltas['fastest_win_sec']!r}")
                candidate = 0
            fastest = candidate if candidate > 0 else 0

        if not adds and not fastest:
            return True

        try:
            with self._lock:
                self.cursor.execute(
                    'INSERT INTO user_counters '
                    '(user_id, sunk_total, matches_played, flawless_wins, fastest_win_sec, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET '
                    'sunk_total = COALESCE(user_counters.sunk_total, 0) + excluded.sunk_total, '
                    'matches_played = COALESCE(user_counters.matches_played, 0) + excluded.matches_played, '
                    'flawless_wins = COALESCE(user_counters.flawless_wins, 0) + excluded.flawless_wins, '
                    # 取最小非零：0 表示"还没有/本次没有"，不覆盖已有值
                    'fastest_win_sec = CASE '
                    '    WHEN excluded.fastest_win_sec = 0 '
                    '        THEN COALESCE(user_counters.fastest_win_sec, 0) '
                    '    WHEN COALESCE(user_counters.fastest_win_sec, 0) = 0 '
                    '        THEN excluded.fastest_win_sec '
                    '    WHEN excluded.fastest_win_sec < user_counters.fastest_win_sec '
                    '        THEN excluded.fastest_win_sec '
                    '    ELSE user_counters.fastest_win_sec END, '
                    'updated_at = excluded.updated_at',
                    (uid, adds.get('sunk_total', 0), adds.get('matches_played', 0),
                     adds.get('flawless_wins', 0), fastest, int(time.time())))
                self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"累加每局计数失败: uid={uid}, 错误: {e}")
            try:
                if self.conn:
                    self.conn.rollback()
            except Exception:
                pass
            return False
        except Exception as e:
            logger.error(f"累加每局计数时发生未知错误: uid={uid}, 错误: {e}")
            try:
                if self.conn:
                    self.conn.rollback()
            except Exception:
                pass
            return False

    # ------------------------------------------------------------------
    # 等级 / 经验（user_xp）
    # 与其它 DAO 同一风格：读失败返回 0/空、写失败返回 False，绝不抛。
    # ------------------------------------------------------------------
    def get_user_xp(self, uid: str) -> int:
        """累计经验。没有记录 = 0（不写库）。"""
        if not uid:
            return 0
        try:
            cursor = self.conn.cursor()
            row = cursor.execute('SELECT xp FROM user_xp WHERE user_id = ?', (uid,)).fetchone()
            cursor.close()
            return max(0, int(row['xp'])) if row else 0
        except sqlite3.Error as e:
            logger.error(f"读取经验失败: uid={uid}, 错误: {e}")
            return 0
        except Exception as e:
            logger.error(f"读取经验时发生未知错误: uid={uid}, 错误: {e}")
            return 0

    def get_xp_map(self, uids) -> dict:
        """批量 `{uid: xp}`（排行榜一页 100 行，逐行查会打 100 次库）。"""
        ids = [str(u) for u in (uids or []) if u]
        if not ids:
            return {}
        try:
            marks = ','.join('?' for _ in ids)
            cursor = self.conn.cursor()
            rows = cursor.execute(
                f'SELECT user_id, xp FROM user_xp WHERE user_id IN ({marks})', ids).fetchall()
            cursor.close()
            return {str(r['user_id']): max(0, int(r['xp'] or 0)) for r in rows if r['user_id']}
        except sqlite3.Error as e:
            logger.error(f"批量读取经验失败: 错误: {e}")
            return {}
        except Exception as e:
            logger.error(f"批量读取经验时发生未知错误: 错误: {e}")
            return {}

    def add_user_xp(self, uid: str, delta: int) -> int:
        """给用户加经验，返回**加完之后**的累计值。

        · `delta <= 0` 直接返回当前值（不做减法 —— 经验只增不减，避免误传负数把玩家打回原形）；
        · 用 UPSERT，第一次写就建行；
        · 写失败返回当前值（调用方据此决定要不要播动画）。
        """
        if not uid:
            return 0
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            return self.get_user_xp(uid)
        if delta <= 0:
            return self.get_user_xp(uid)
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    'INSERT INTO user_xp (user_id, xp, updated_at) VALUES (?, ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET xp = xp + excluded.xp, updated_at = excluded.updated_at',
                    (uid, delta, int(time.time())))
                self.conn.commit()
                row = cursor.execute('SELECT xp FROM user_xp WHERE user_id = ?', (uid,)).fetchone()
                cursor.close()
            return max(0, int(row['xp'])) if row else delta
        except sqlite3.Error as e:
            logger.error(f"增加经验失败: uid={uid}, delta={delta}, 错误: {e}")
            return self.get_user_xp(uid)
        except Exception as e:
            logger.error(f"增加经验时发生未知错误: uid={uid}, 错误: {e}")
            return self.get_user_xp(uid)

    def set_user_xp(self, uid: str, xp: int) -> bool:
        """直接设置累计经验（运维用，例如给某个账号定级）。"""
        if not uid:
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    'INSERT INTO user_xp (user_id, xp, updated_at) VALUES (?, ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET xp = excluded.xp, updated_at = excluded.updated_at',
                    (uid, max(0, int(xp)), int(time.time())))
                self.conn.commit()
                cursor.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"设置经验失败: uid={uid}, 错误: {e}")
            return False
        except Exception as e:
            logger.error(f"设置经验时发生未知错误: uid={uid}, 错误: {e}")
            return False

    # ------------------------------------------------------------------
    # 段位（user_rank）：排位积分
    #
    # 分工：**本层只存 `points`，不算段位**。等级 / 小段位 / 进度条 / 升级判定
    # 全部由 `ranks.py` 从 `points` 现算 —— 与 `leveling.py` 同一条规矩。
    # 存一份"段位名"就会出现"分数改了段位没改"的漂移，所以不存。
    #
    # 排序口径（全服名次、段位榜、船长池名次三处共用，必须一致）：
    #     points DESC, COALESCE(updated_at,0) ASC, user_id ASC
    # 后两段是**定序用的**：同分时"先到的排前面"稳定，不会随查询计划抖动
    # （否则同分玩家的 #60 / #61 会来回跳，看着像 bug）。
    # ------------------------------------------------------------------
    _RANK_ORDER_BY = ('ORDER BY points DESC, COALESCE(updated_at, 0) ASC, user_id ASC')

    @staticmethod
    def _rank_row_dict(row) -> dict:
        """把一行 `user_rank` 收敛成纯 dict（不把 sqlite3.Row 漏给调用方）。"""
        if not row:
            return {'points': 0, 'is_admiral': 0, 'ranked_wins': 0,
                    'ranked_losses': 0, 'updated_at': 0}
        return {
            'points': max(0, int(row['points'] or 0)),
            'is_admiral': 1 if row['is_admiral'] else 0,
            'ranked_wins': max(0, int(row['ranked_wins'] or 0)),
            'ranked_losses': max(0, int(row['ranked_losses'] or 0)),
            'updated_at': int(row['updated_at'] or 0),
        }

    def get_user_rank_row(self, uid: str) -> dict:
        """某人的排位积分行。**没有记录就返回全 0 的默认行**（不写库）。

        ⚠️ 返回默认行而不是 None：调用方（api / server）一律拿 dict 用，
        让"没打过排位"与"打过但 0 分"走同一条渲染路径 —— 段位要显示成
        「二级水手Ⅰ 0分」而不是空白。
        """
        if not uid:
            return self._rank_row_dict(None)
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT points, is_admiral, ranked_wins, ranked_losses, updated_at '
                'FROM user_rank WHERE user_id = ?', (uid,)).fetchone()
            cursor.close()
            return self._rank_row_dict(row)
        except sqlite3.Error as e:
            logger.error(f"读取段位失败: uid={uid}, 错误: {e}")
            return self._rank_row_dict(None)
        except Exception as e:
            logger.error(f"读取段位时发生未知错误: uid={uid}, 错误: {e}")
            return self._rank_row_dict(None)

    def get_rank_map(self, uids) -> dict:
        """批量 `{uid: rank_row}`（排行榜一页 100 行，逐行查会打 100 次库）。

        ⚠️ 只返回**库里有行**的账号 —— 与 `get_user_rank_row` 的"返回默认行"
        策略相反，这是有意的：调用方拿它给一页列表补数据，没行的地方
        用 `_rank_row_dict(None)` 兜底即可；如果这里给每个 uid 都塞默认行，
        调用方就分不清"真的 0 分"和"根本没打过排位"了。
        """
        ids = [str(u) for u in (uids or []) if u]
        if not ids:
            return {}
        try:
            marks = ','.join('?' for _ in ids)
            cursor = self.conn.cursor()
            rows = cursor.execute(
                'SELECT user_id, points, is_admiral, ranked_wins, ranked_losses, updated_at '
                f'FROM user_rank WHERE user_id IN ({marks})', ids).fetchall()
            cursor.close()
            return {str(r['user_id']): self._rank_row_dict(r) for r in rows if r['user_id']}
        except sqlite3.Error as e:
            logger.error(f"批量读取段位失败: 错误: {e}")
            return {}
        except Exception as e:
            logger.error(f"批量读取段位时发生未知错误: 错误: {e}")
            return {}

    def add_rank_points(self, uid: str, delta: int, is_admiral=None) -> dict:
        """加/减排位积分，返回**写完之后**的整行。

        · 底分由 SQL 的 `MAX(0, ...)` 兜住（0 分封底，不出现负分）；
        · `is_admiral=None` 表示"不动这一列"，传 1/0 则显式改写；
        · 用 UPSERT，第一次写就建行；
        · 写失败返回**读出来的当前行**（调用方据此播动画，不会播成假数据）。
        """
        if not uid:
            return self._rank_row_dict(None)
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            return self.get_user_rank_row(uid)
        try:
            with self._lock:
                cursor = self.conn.cursor()
                # ⚠️ 这里必须**绑两次 delta**：VALUES 里那个是给"首次建行"用的
                # （封底 MAX(0, ?)），ON CONFLICT 里那个才是真正参与累加的原始值。
                # 只用前者会踩一个很隐蔽的坑：`excluded.points` 已经被夹成 0，
                # 于是 `user_rank.points + excluded.points` 等于**没减分**
                # （实测：20 分输一局仍是 20 分，只有胜负场次在涨）。
                cursor.execute(
                    'INSERT INTO user_rank (user_id, points, is_admiral, ranked_wins, '
                    'ranked_losses, updated_at) VALUES (?, MAX(0, ?), ?, ?, ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET '
                    'points = MAX(0, user_rank.points + ?), '
                    'is_admiral = COALESCE(?, user_rank.is_admiral), '
                    'ranked_wins = user_rank.ranked_wins + excluded.ranked_wins, '
                    'ranked_losses = user_rank.ranked_losses + excluded.ranked_losses, '
                    'updated_at = excluded.updated_at',
                    (uid, delta,
                     1 if is_admiral else 0,
                     1 if delta > 0 else 0,
                     1 if delta < 0 else 0,
                     int(time.time()),
                     delta,
                     None if is_admiral is None else (1 if is_admiral else 0)))
                self.conn.commit()
                row = cursor.execute(
                    'SELECT points, is_admiral, ranked_wins, ranked_losses, updated_at '
                    'FROM user_rank WHERE user_id = ?', (uid,)).fetchone()
                cursor.close()
            return self._rank_row_dict(row)
        except sqlite3.Error as e:
            logger.error(f"增减段位积分失败: uid={uid}, delta={delta}, 错误: {e}")
            return self.get_user_rank_row(uid)
        except Exception as e:
            logger.error(f"增减段位积分时发生未知错误: uid={uid}, 错误: {e}")
            return self.get_user_rank_row(uid)

    def set_rank_points(self, uid: str, points: int, is_admiral=None) -> bool:
        """直接设置排位积分（运维用 / 测试用）。只改 points，不动胜负场次。"""
        if not uid:
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    'INSERT INTO user_rank (user_id, points, is_admiral, updated_at) '
                    'VALUES (?, MAX(0, ?), ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET '
                    'points = MAX(0, excluded.points), '
                    'is_admiral = COALESCE(?, user_rank.is_admiral), '
                    'updated_at = excluded.updated_at',
                    (uid, int(points), 1 if is_admiral else 0, int(time.time()),
                     None if is_admiral is None else (1 if is_admiral else 0)))
                self.conn.commit()
                cursor.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"设置段位积分失败: uid={uid}, 错误: {e}")
            return False
        except Exception as e:
            logger.error(f"设置段位积分时发生未知错误: uid={uid}, 错误: {e}")
            return False

    def ranked_leaderboard(self, limit: int = 100, offset: int = 0) -> list:
        """段位榜一页：按积分倒序，返回 `[{user_id, points, is_admiral, ...}]`。

        ⚠️ **只列"打过排位"的账号**（表里有行才在榜上）。这与战绩排行榜
        「只统计真打过一局的账号」是同一条口径 —— 否则全站注册用户都会
        以「二级水手Ⅰ 0分」占据榜尾。
        """
        try:
            limit = max(1, min(int(limit), 200))
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            limit, offset = 100, 0
        try:
            cursor = self.conn.cursor()
            rows = cursor.execute(
                'SELECT user_id, points, is_admiral, ranked_wins, ranked_losses, updated_at '
                f'FROM user_rank {self._RANK_ORDER_BY} LIMIT ? OFFSET ?',
                (limit, offset)).fetchall()
            cursor.close()
            out = []
            for i, r in enumerate(rows):
                item = self._rank_row_dict(r)
                item['user_id'] = str(r['user_id'])
                item['position'] = offset + i + 1
                out.append(item)
            return out
        except sqlite3.Error as e:
            logger.error(f"读取段位榜失败: 错误: {e}")
            return []
        except Exception as e:
            logger.error(f"读取段位榜时发生未知错误: 错误: {e}")
            return []

    def count_rank_at_least(self, points: int) -> int:
        """积分 ≥ 门槛的账号数（大舰长门槛要数"全服船长段有多少人"）。"""
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT COUNT(*) AS n FROM user_rank WHERE points >= ?',
                (max(0, int(points)),)).fetchone()
            cursor.close()
            return int(row['n'] or 0)
        except (sqlite3.Error, TypeError, ValueError) as e:
            logger.error(f"统计段位人数失败: 错误: {e}")
            return 0
        except Exception as e:
            logger.error(f"统计段位人数时发生未知错误: 错误: {e}")
            return 0

    def captains_ordered(self, limit: int = 60) -> list:
        """「船长池」：积分 ≥ 船长门槛的账号，按同一排序口径取前 N。

        大舰长升级判定看的是**这张池子里的名次**，而不是全服名次
        （见 `ranks.can_promote_to_admiral`）—— 两个名次是两回事：
        池名次用于判定，全服名次用于展示。
        """
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit = 60
        try:
            cursor = self.conn.cursor()
            rows = cursor.execute(
                'SELECT user_id, points, is_admiral, ranked_wins, ranked_losses, updated_at '
                f'FROM user_rank WHERE points >= ? {self._RANK_ORDER_BY} LIMIT ?',
                (max(0, int(ranks.CAPTAIN_FLOOR)), limit)).fetchall()
            cursor.close()
            out = []
            for i, r in enumerate(rows):
                item = self._rank_row_dict(r)
                item['user_id'] = str(r['user_id'])
                item['pool_position'] = i + 1
                out.append(item)
            return out
        except sqlite3.Error as e:
            logger.error(f"读取船长池失败: 错误: {e}")
            return []
        except Exception as e:
            logger.error(f"读取船长池时发生未知错误: 错误: {e}")
            return []

    def get_rank_position(self, uid: str) -> int:
        """某人的**全服段位名次**（1 起）。没打过排位返回 0。

        ⚠️ 与 `get_user_rank`（战绩榜名次，按 wins）**不是一回事**，
        名字刻意错开以免调用方拿错。排序口径与 `ranked_leaderboard` 一致，
        用 COUNT(*) 直接算严格在前的行数 —— 榜外账号（100 名之后）也能拿到名次。
        """
        if not uid:
            return 0
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT points, COALESCE(updated_at, 0) AS ts, user_id FROM user_rank '
                'WHERE user_id = ?', (uid,)).fetchone()
            if not row:
                cursor.close()
                return 0
            ahead = cursor.execute(
                'SELECT COUNT(*) AS n FROM user_rank WHERE '
                'points > ? OR (points = ? AND '
                '(COALESCE(updated_at, 0) < ? OR (COALESCE(updated_at, 0) = ? AND user_id < ?)))',
                (row['points'], row['points'], row['ts'], row['ts'], row['user_id'])).fetchone()
            cursor.close()
            return int(ahead['n'] or 0) + 1
        except sqlite3.Error as e:
            logger.error(f"读取段位名次失败: uid={uid}, 错误: {e}")
            return 0
        except Exception as e:
            logger.error(f"读取段位名次时发生未知错误: uid={uid}, 错误: {e}")
            return 0

    def get_rank_position_map(self, uids) -> dict:
        """批量 `{uid: 全服段位名次}`（段位榜一页要用）。没行 / 失败的不出现在结果里。"""
        ids = [str(u) for u in (uids or []) if u]
        if not ids:
            return {}
        out = {}
        for uid in ids:
            pos = self.get_rank_position(uid)
            if pos > 0:
                out[uid] = pos
        return out

    # ------------------------------------------------------------------
    # 特权（user_perks）：外观全解锁 / 彩虹名字 …
    # 与其它 DAO 同一风格：读失败返回空值、写失败返回 False，绝不抛。
    # ------------------------------------------------------------------
    def list_user_perks(self, uid: str) -> set:
        """该账号持有的特权集合。读不到就是空集合（等价于没有特权）。"""
        if not uid:
            return set()
        try:
            cursor = self.conn.cursor()
            rows = cursor.execute('SELECT perk FROM user_perks WHERE user_id = ?', (uid,)).fetchall()
            cursor.close()
            return {str(r['perk']) for r in rows if r['perk']}
        except sqlite3.Error as e:
            logger.error(f"读取特权失败: uid={uid}, 错误: {e}")
            return set()
        except Exception as e:
            logger.error(f"读取特权时发生未知错误: uid={uid}, 错误: {e}")
            return set()

    def get_perks_map(self, uids) -> dict:
        """批量取 `{uid: set(perk)}`。

        排行榜一页 100 行，逐行查会打 100 次库 —— 这里一条 SQL 取完
        （`IN (...)` 参数化，不拼字符串）。
        """
        ids = [str(u) for u in (uids or []) if u]
        if not ids:
            return {}
        try:
            marks = ','.join('?' for _ in ids)
            cursor = self.conn.cursor()
            rows = cursor.execute(
                f'SELECT user_id, perk FROM user_perks WHERE user_id IN ({marks})', ids).fetchall()
            cursor.close()
            out = {}
            for r in rows:
                if r['user_id'] and r['perk']:
                    out.setdefault(str(r['user_id']), set()).add(str(r['perk']))
            return out
        except sqlite3.Error as e:
            logger.error(f"批量读取特权失败: 错误: {e}")
            return {}
        except Exception as e:
            logger.error(f"批量读取特权时发生未知错误: 错误: {e}")
            return {}

    def has_user_perk(self, uid: str, perk: str) -> bool:
        """该账号是否持有某个特权。"""
        return str(perk or '') in self.list_user_perks(uid)

    def grant_user_perk(self, uid: str, perk: str) -> bool:
        """授予特权（幂等）。成功或本来就有都返回 True。"""
        perk = str(perk or '').strip()
        if not uid or not perk:
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    'INSERT OR IGNORE INTO user_perks (user_id, perk, granted_at) VALUES (?, ?, ?)',
                    (uid, perk, int(time.time())))
                self.conn.commit()
                cursor.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"授予特权失败: uid={uid}, perk={perk}, 错误: {e}")
            return False
        except Exception as e:
            logger.error(f"授予特权时发生未知错误: uid={uid}, perk={perk}, 错误: {e}")
            return False

    def revoke_user_perk(self, uid: str, perk: str) -> bool:
        """收回特权（运维用；幂等）。"""
        perk = str(perk or '').strip()
        if not uid or not perk:
            return False
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute('DELETE FROM user_perks WHERE user_id = ? AND perk = ?', (uid, perk))
                self.conn.commit()
                cursor.close()
            return True
        except sqlite3.Error as e:
            logger.error(f"收回特权失败: uid={uid}, perk={perk}, 错误: {e}")
            return False

    def get_user_achievements(self, uid: str) -> dict:
        """已解锁的徽章 `{badge_id: unlocked_at}`。读失败返回空字典。"""
        if not uid:
            return {}
        try:
            cursor = self.conn.cursor()
            rows = cursor.execute(
                'SELECT badge_id, unlocked_at FROM user_achievements WHERE user_id = ?',
                (uid,)).fetchall()
            cursor.close()
            return {r['badge_id']: max(0, int(r['unlocked_at'] or 0)) for r in rows if r['badge_id']}
        except sqlite3.Error as e:
            logger.error(f"读取已解锁徽章失败: uid={uid}, 错误: {e}")
            return {}
        except Exception as e:
            logger.error(f"读取已解锁徽章时发生未知错误: uid={uid}, 错误: {e}")
            return {}

    def grant_user_achievements(self, uid: str, badge_ids) -> list:
        """授予徽章，**只写入本次新增的**，返回新增的 id 列表（用于播报）。

        幂等：主键 (user_id, badge_id) + INSERT OR IGNORE，重复授予不会重复插入、
        也不会刷新首解时间（"只进不退"）。逐条判断 rowcount 而不是看总行数 ——
        这样返回值精确等于"这一局新解锁的"，播报不会把老徽章再念一遍。
        """
        if not uid:
            return []
        try:
            candidates = list(badge_ids or [])
        except TypeError:
            logger.warning(f"授予徽章收到不可迭代的 badge_ids: uid={uid}, value={badge_ids!r}")
            return []

        granted = []
        seen = set()
        now = int(time.time())
        try:
            with self._lock:
                for raw in candidates:
                    badge_id = str(raw or '').strip()
                    if not badge_id or badge_id in seen:
                        continue
                    seen.add(badge_id)
                    self.cursor.execute(
                        'INSERT OR IGNORE INTO user_achievements '
                        '(user_id, badge_id, unlocked_at) VALUES (?, ?, ?)',
                        (uid, badge_id, now))
                    if self.cursor.rowcount == 1:
                        granted.append(badge_id)
                self.conn.commit()
            return granted
        except sqlite3.Error as e:
            logger.error(f"授予徽章失败: uid={uid}, 错误: {e}")
            try:
                if self.conn:
                    self.conn.rollback()
            except Exception:
                pass
            return []
        except Exception as e:
            logger.error(f"授予徽章时发生未知错误: uid={uid}, 错误: {e}")
            try:
                if self.conn:
                    self.conn.rollback()
            except Exception:
                pass
            return []

    def get_distinct_cards_used(self, uid: str) -> int:
        """该用户用过多少张**不同**的卡（徽章「全能选手」的判据）。读失败返回 0。"""
        if not uid:
            return 0
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT COUNT(DISTINCT card_name) AS n FROM user_card_usage WHERE user_id = ?',
                (uid,)).fetchone()
            cursor.close()
            return int(row['n'] or 0) if row else 0
        except sqlite3.Error as e:
            logger.error(f"读取出卡种类数失败: uid={uid}, 错误: {e}")
            return 0
        except Exception as e:
            logger.error(f"读取出卡种类数时发生未知错误: uid={uid}, 错误: {e}")
            return 0

    # ------------------------------------------------------------------
    # 点赞 / 送花 / 留言板（2026-09-17 第 3 批 D 票）
    # ------------------------------------------------------------------
    # 契约见 `docs/BATCH_2_3_4_PLAN.md` §3.1 / §3.3。
    #
    # 风格与第 1、2 批一致：**失败只记日志、返回安全默认值**。
    # 互动是展示层，一次读库失败不该把名片/留言板变成 500。
    #
    # ⚠️ 每个 DAO 都必须有对应的**模块级包装函数**（文件末尾）——本项目的测试
    # 与调用方都按模块级名字打桩，只在类里实现会让打桩被绕过（第 2 批踩过：
    # `self.xxx` 读真库 → 假红）。
    _REACTION_KINDS = ('like', 'flower')

    def _empty_reaction_counts(self) -> dict:
        """没有互动时的计数（**不写库**）。"""
        return {'like': 0, 'flower': 0}

    def set_profile_reaction(self, from_uid: str, to_uid: str, kind: str, on) -> bool:
        """点赞 / 送花：`on=True` 幂等新增、`on=False` 幂等取消。返回是否成功。

        · 主键 (from, to, kind) 保证「重复点同一张」不会点出两条（`INSERT OR IGNORE`）。
        · 取消一个不存在的反应也返回 True —— 取消是幂等的，"本来就没有"不是失败。
        · ⚠️ 这里**不校验**"不能给自己点赞/送花"、kind 白名单、目标是否存在：
          那些是**服务端裁决**，由 `api.py` 统一做（本函数只负责写库），
          这样校验规则只有一份，不会出现"接口放行、DAO 拦下"这种两份漂移。
        """
        if not from_uid or not to_uid or not kind:
            logger.warning(f"点赞/送花参数不完整（已忽略）: from={from_uid!r}, to={to_uid!r}, kind={kind!r}")
            return False
        try:
            with self._lock:
                if on:
                    self.cursor.execute(
                        'INSERT OR IGNORE INTO profile_likes '
                        '(from_user_id, to_user_id, kind, created_at) VALUES (?, ?, ?, ?)',
                        (str(from_uid), str(to_uid), str(kind), int(time.time())))
                else:
                    self.cursor.execute(
                        'DELETE FROM profile_likes '
                        'WHERE from_user_id = ? AND to_user_id = ? AND kind = ?',
                        (str(from_uid), str(to_uid), str(kind)))
                self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"写入点赞/送花失败: from={from_uid}, to={to_uid}, kind={kind} -> {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"写入点赞/送花时发生未知错误: from={from_uid}, to={to_uid} -> {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def get_profile_reaction_counts(self, uid: str) -> dict:
        """某人收到的点赞 / 送花计数 → `{'like': N, 'flower': M}`。

        计数是"人气"而不是"内容"，**始终可见**（计划 §3.3）—— 所以接口层
        不因为 `show_guestbook=0` 就把它藏起来。读失败返回全 0。
        """
        counts = self._empty_reaction_counts()
        if not uid:
            return counts
        try:
            cursor = self.conn.cursor()
            rows = cursor.execute(
                'SELECT kind, COUNT(*) AS n FROM profile_likes '
                'WHERE to_user_id = ? GROUP BY kind', (uid,)).fetchall()
            cursor.close()
            for row in rows:
                if row['kind'] in counts:
                    counts[row['kind']] = int(row['n'] or 0)
            return counts
        except sqlite3.Error as e:
            logger.error(f"读取点赞/送花计数失败: uid={uid}, 错误: {e}")
            return counts
        except Exception as e:
            logger.error(f"读取点赞/送花计数时发生未知错误: uid={uid}, 错误: {e}")
            return counts

    def get_my_reactions(self, from_uid: str, to_uid: str) -> dict:
        """我（`from_uid`）对目标（`to_uid`）的两种反应状态 → `{'like': bool, 'flower': bool}`。

        前端据此决定按钮是否点亮。`from_uid` 为空（未登录视角）时返回全 False。
        """
        mine = {'like': False, 'flower': False}
        if not from_uid or not to_uid:
            return mine
        try:
            cursor = self.conn.cursor()
            rows = cursor.execute(
                'SELECT kind FROM profile_likes WHERE from_user_id = ? AND to_user_id = ?',
                (from_uid, to_uid)).fetchall()
            cursor.close()
            for row in rows:
                if row['kind'] in mine:
                    mine[row['kind']] = True
            return mine
        except sqlite3.Error as e:
            logger.error(f"读取我的互动状态失败: from={from_uid}, to={to_uid}, 错误: {e}")
            return mine
        except Exception as e:
            logger.error(f"读取我的互动状态时发生未知错误: from={from_uid}, to={to_uid}, 错误: {e}")
            return mine

    def _profile_message_row(self, row) -> dict:
        """一行留言 → 下发给前端的**白名单形状**。

        只给契约里的字段（有意**不下发** `to_user_id` / `deleted`：
        前者是主人自己的 id、后者是内部审计状态，前端一个都用不上）。
        """
        return {
            'id': int(row['id']),
            'from_uid': row['from_user_id'] or '',
            'from_name': row['from_name'] or '匿名',
            'content': row['content'] or '',
            'created_at': int(row['created_at'] or 0),
        }

    def add_profile_message(self, to_uid: str, from_uid: str, from_name: str,
                            content: str) -> int:
        """写一条留言，返回新行 `id`；失败返回 0（调用方据此回 500）。

        ⚠️ 与 `set_profile_reaction` 同样**不做业务校验**（自我留言、长度、频率
        一律由 `api.py` 裁决）。存储层只做两件兜底：截断到 500 字防爆行、
        `from_name` 空值落「匿名」。
        """
        if not to_uid or not from_uid or not content:
            logger.warning(f"留言参数不完整（已忽略）: to={to_uid!r}, from={from_uid!r}")
            return 0
        safe_content = str(content)[:500]
        safe_name = (str(from_name).strip()[:50] if from_name else '') or '匿名'
        try:
            with self._lock:
                self.cursor.execute(
                    'INSERT INTO profile_messages '
                    '(to_user_id, from_user_id, from_name, content, created_at, deleted) '
                    'VALUES (?, ?, ?, ?, ?, 0)',
                    (str(to_uid), str(from_uid), safe_name, safe_content, int(time.time())))
                new_id = int(self.cursor.lastrowid or 0)
                self.conn.commit()
            return new_id
        except sqlite3.Error as e:
            logger.error(f"写入留言失败: to={to_uid}, from={from_uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return 0
        except Exception as e:
            logger.error(f"写入留言时发生未知错误: to={to_uid}, from={from_uid}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return 0

    def list_profile_messages(self, to_uid: str, limit: int = 20, before_id=None) -> dict:
        """留言列表（**只含 `deleted = 0`**），按 id 倒序 + 游标分页。

        返回 `{'messages': [...], 'has_more': bool, 'total': N}`：
        · `total` 是该主页**未被软删**的留言总数（分页与"共 N 条"都要用）。
        · `before_id` 给上一页最小 id，取"比它更早"的一页（游标分页，
          不用 OFFSET —— 有人删留言时 OFFSET 会跳行/重行）。
        · 排序一律按 `id` 而非 `created_at`：同一秒连发的多条时间戳会并列，
          按时间戳排序的结果不稳定。写死 `id DESC` 才有确定性。
        · 多取一行判断 `has_more`，省一次 COUNT。
        · 读失败返回空列表 + total 0（宁可显示"还没有留言"，也不 500）。
        """
        result = {'messages': [], 'has_more': False, 'total': 0}
        if not to_uid:
            return result
        try:
            safe_limit = min(max(1, int(limit)), 50)
        except (TypeError, ValueError):
            safe_limit = 20
        try:
            before = None
            if before_id not in (None, ''):
                before = int(before_id)
        except (TypeError, ValueError):
            before = None
        try:
            cursor = self.conn.cursor()
            total_row = cursor.execute(
                'SELECT COUNT(*) AS n FROM profile_messages '
                'WHERE to_user_id = ? AND deleted = 0', (to_uid,)).fetchone()
            total = int(total_row['n'] or 0) if total_row else 0
            if before is None:
                rows = cursor.execute(
                    'SELECT * FROM profile_messages '
                    'WHERE to_user_id = ? AND deleted = 0 '
                    'ORDER BY id DESC LIMIT ?',
                    (to_uid, safe_limit + 1)).fetchall()
            else:
                rows = cursor.execute(
                    'SELECT * FROM profile_messages '
                    'WHERE to_user_id = ? AND deleted = 0 AND id < ? '
                    'ORDER BY id DESC LIMIT ?',
                    (to_uid, before, safe_limit + 1)).fetchall()
            cursor.close()
            has_more = len(rows) > safe_limit
            page = rows[:safe_limit]
            return {
                'messages': [self._profile_message_row(r) for r in page],
                'has_more': has_more,
                'total': total,
            }
        except sqlite3.Error as e:
            logger.error(f"读取留言列表失败: to={to_uid}, 错误: {e}")
            return result
        except Exception as e:
            logger.error(f"读取留言列表时发生未知错误: to={to_uid}, 错误: {e}")
            return result

    def get_profile_message(self, msg_id) -> dict:
        """按 id 取一条留言（**不过滤 deleted**）。

        删除权限校验必须能读到已软删的行 —— 否则"删两次"会从"幂等成功"
        变成 404，而调用方分不出"不存在"与"已删过"。读失败/不存在返回 None。
        """
        try:
            mid = int(msg_id)
        except (TypeError, ValueError):
            return None
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT * FROM profile_messages WHERE id = ?', (mid,)).fetchone()
            cursor.close()
            if not row:
                return None
            data = self._profile_message_row(row)
            # 删除权限需要这两个字段，但它们**不属于下发形状**：
            # `to_user_id` 是主人自己、`deleted` 是内部审计状态，都不给前端。
            # 单独放在下划线开头的内部键里，接口层用完即弃（组装响应时不会带出去）。
            data['_to_user_id'] = row['to_user_id'] or ''
            data['_deleted'] = int(row['deleted'] or 0)
            return data
        except sqlite3.Error as e:
            logger.error(f"读取单条留言失败: id={msg_id}, 错误: {e}")
            return None
        except Exception as e:
            logger.error(f"读取单条留言时发生未知错误: id={msg_id}, 错误: {e}")
            return None

    def soft_delete_profile_message(self, msg_id) -> bool:
        """软删留言（`deleted = 1`，保留审计）。返回是否成功。

        **不在这里判权限** —— 谁能删由 `api.py` 裁决（留言本人或页面主人，
        其余 403）。存储层只管把标志位写下去。
        重复删除返回 True（`rowcount == 0` 也算成功）：幂等，"已经删过了"不是失败。
        """
        try:
            mid = int(msg_id)
        except (TypeError, ValueError):
            return False
        try:
            with self._lock:
                self.cursor.execute(
                    'UPDATE profile_messages SET deleted = 1 WHERE id = ? AND deleted = 0',
                    (mid,))
                self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"软删留言失败: id={msg_id}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False
        except Exception as e:
            logger.error(f"软删留言时发生未知错误: id={msg_id}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def count_profile_messages_since(self, from_uid: str, to_uid: str, since: int) -> int:
        """`since` 之后「from → to」发出的留言条数（含已软删的）。

        用途：**每人对同一人每天 ≤ 20 条**的频率限制。刻意把软删的也算进去 ——
        否则"发了 20 条 → 全删掉 → 再发 20 条"就绕过了限制。读失败返回 0
        （宁可放行一条，也不因为统计读不到就把玩家堵死）。
        """
        if not from_uid or not to_uid:
            return 0
        try:
            cursor = self.conn.cursor()
            row = cursor.execute(
                'SELECT COUNT(*) AS n FROM profile_messages '
                'WHERE from_user_id = ? AND to_user_id = ? AND created_at >= ?',
                (str(from_uid), str(to_uid), int(since))).fetchone()
            cursor.close()
            return int(row['n'] or 0) if row else 0
        except sqlite3.Error as e:
            logger.error(f"统计当日留言条数失败: from={from_uid}, to={to_uid}, 错误: {e}")
            return 0
        except Exception as e:
            logger.error(f"统计当日留言条数时发生未知错误: from={from_uid}, to={to_uid}, 错误: {e}")
            return 0

    def get_token_by_password(self, username: str, password: str):
        """通过用户名和密码校验并生成token（使用 check_password_hash 验证）"""
        if not username or not password:
            logger.warning("尝试获取token但用户名或密码为空")
            return None
            
        try:
            with self._lock:
                cursor = self.conn.cursor()
                user = cursor.execute('SELECT id, password_hash FROM users WHERE username = ?',
                                      (username,)).fetchone()
                cursor.close()

            if user and check_password_hash(user['password_hash'], password):
                token = str(uuid.uuid4())
                with self._lock:
                    # 独立游标 + 锁：避免与其它写操作共用同一游标导致 SQL/参数错配
                    cursor = self.conn.cursor()
                    cursor.execute('UPDATE users SET token = ? WHERE id = ?', (token, user['id']))
                    self.conn.commit()
                    cursor.close()
                logger.info(f"成功为用户生成token: username={username}, user_id={user['id']}")
                return token
            else:
                logger.debug(f"token验证失败: 用户名或密码不正确: username={username}")
                return None
        except sqlite3.Error as e:
            logger.error(f"获取或生成token时发生数据库错误: username={username}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return None
        except Exception as e:
            logger.error(f"获取或生成token时发生未知错误: username={username}, 错误: {e}")
            if self.conn:
                self.conn.rollback()
            return None
    
    def close(self):
        """关闭数据库连接"""
        try:
            # 关闭游标
            if hasattr(self, 'cursor') and self.cursor:
                self.cursor.close()
                logger.debug("成功关闭数据库游标")
                self.cursor = None
                
            # 关闭连接
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
                logger.debug("成功关闭数据库连接")
                self.conn = None
        except Exception as e:
            # 注意：不引用 sqlite3.Error —— 解释器退出时 sqlite3 模块可能已被置 None，
            # 在 except 子句中求值 sqlite3.Error 会抛 AttributeError（__del__ 场景）
            logger.error(f"关闭数据库资源时发生错误: {e}")
    
    def __del__(self):
        """对象被销毁时自动关闭数据库连接"""
        try:
            self.close()
        except Exception:
            # 解释器关闭阶段资源不可用时静默忽略
            pass


# 创建全局数据库实例，保持向后兼容
db = Database()

# 向后兼容的函数封装
def init_db():
    """初始化数据库"""
    db.init_db()


def clear_temp_data():
    """重启时清空临时数据"""
    db.clear_temp_data()


def update_user(uid: str, **kwargs):
    """通用更新用户信息"""
    return db.update_user(uid, **kwargs)


def get_user(uid="", username=""):
    """通用获取用户信息"""
    return db.get_user(uid, username)


def get_user_by_token(token: str):
    """通过token获取用户信息"""
    return db.get_user_by_token(token)


def save_active_game(uid: str, room_id: str):
    """保存活跃游戏"""
    return db.save_active_game(uid, room_id)


def get_active_game(uid: str):
    """获取活跃游戏"""
    return db.get_active_game(uid)


def update_user_signature(uid: str, signature: str):
    """更新用户签名"""
    return db.update_user_signature(uid, signature)


def update_user_avatar(uid: str, avatar_path: str):
    """更新用户头像"""
    return db.update_user_avatar(uid, avatar_path)


def update_user_password(uid: str, password_hash: str):
    """更新用户密码"""
    return db.update_user_password(uid, password_hash)


def get_user_profile(uid: str):
    """获取用户资料"""
    return db.get_user_profile(uid)


def add_chat_message(user_id: str, username: str, content: str):
    """添加聊天消息"""
    return db.add_chat_message(user_id, username, content)


def get_chat_messages(limit=50):
    """获取聊天消息"""
    return db.get_chat_messages(limit)


def create_user(username: str, password_hash: str):
    """创建用户"""
    return db.create_user(username, password_hash)


def record_match(winner_id: str, loser_id: str, logs=None, count_stats=True):
    """记录比赛（count_stats=False 时只写历史、不计入胜场/连胜）"""
    return db.record_match(winner_id, loser_id, logs, count_stats)


def record_card_use(card_name: str, count: int = 1):
    """记一次卡牌使用（server.py 用模块级函数调用）"""
    return db.record_card_use(card_name, count)


def get_card_usage():
    """卡牌使用次数 {卡名: 次数}（api.py 用模块级函数调用）"""
    return db.get_card_usage()


def get_match_history(uid: str, limit=20):
    """获取比赛历史"""
    return db.get_match_history(uid, limit)


def get_leaderboard(limit=10):
    """获取排行榜"""
    return db._get_leaderboard(limit)


def get_user_rank(uid: str):
    """某个账号的排行榜名次（api.py 用模块级函数调用）"""
    return db.get_user_rank(uid)


# ---- 个人信息名片（api.py / server.py 都走模块级函数）----
def get_user_profile_extra(uid: str):
    """读名片个性字段（无记录时返回默认值）"""
    return db.get_user_profile_extra(uid)


def save_user_profile_extra(uid: str, fields: dict):
    """UPSERT 名片字段"""
    return db.save_user_profile_extra(uid, fields)


def record_user_card_use(uid: str, card_name: str, count: int = 1):
    """记一次个人卡牌使用（server.py 出牌时调用）"""
    return db.record_user_card_use(uid, card_name, count)


def get_user_card_usage(uid: str, limit: int = 3):
    """某人最常用的卡 Top-N"""
    return db.get_user_card_usage(uid, limit)


def get_user_card_uses_total(uid: str):
    """个人累计出牌次数"""
    return db.get_user_card_uses_total(uid)


# ---- 等级 / 经验 ----
def get_user_xp(uid: str):
    """累计经验（无记录 = 0）"""
    return db.get_user_xp(uid)


def get_xp_map(uids):
    """批量 `{uid: xp}`（排行榜用，避免 N 次查询）"""
    return db.get_xp_map(uids)


def add_user_xp(uid: str, delta: int):
    """加经验，返回加完之后的累计值"""
    return db.add_user_xp(uid, delta)


def set_user_xp(uid: str, xp: int):
    """直接设置累计经验（运维用）"""
    return db.set_user_xp(uid, xp)


# ---- 段位（排位积分）----
# ⚠️ 与其它批次同一条规矩：**模块级函数必须与类方法成对存在**。
# api.py / server.py / 测试都按模块级名字调用与打桩，只实现类方法会被绕过
# （第 2 批为此吃过一次假红：测试里明明 12 场，接口按 0 算）。
def get_user_rank_row(uid: str):
    """某人的排位积分行（无记录 = 全 0 的默认行）"""
    return db.get_user_rank_row(uid)


def get_rank_map(uids):
    """批量 `{uid: rank_row}`（只含库里有行的账号）"""
    return db.get_rank_map(uids)


def add_rank_points(uid: str, delta: int, is_admiral=None):
    """加/减排位积分，返回写完之后的那一行"""
    return db.add_rank_points(uid, delta, is_admiral)


def set_rank_points(uid: str, points: int, is_admiral=None):
    """直接设置排位积分（运维 / 测试用）"""
    return db.set_rank_points(uid, points, is_admiral)


def ranked_leaderboard(limit: int = 100, offset: int = 0):
    """段位榜一页（按积分倒序）"""
    return db.ranked_leaderboard(limit, offset)


def count_rank_at_least(points: int):
    """积分 ≥ 门槛的账号数"""
    return db.count_rank_at_least(points)


def captains_ordered(limit: int = 60):
    """船长池（积分 ≥ 船长起始分），带 `pool_position`"""
    return db.captains_ordered(limit)


def get_rank_position(uid: str):
    """全服段位名次（1 起；没打过排位 = 0）"""
    return db.get_rank_position(uid)


def get_rank_position_map(uids):
    """批量 `{uid: 全服段位名次}`"""
    return db.get_rank_position_map(uids)


def set_show_rank(uid: str, on):
    """写「段位是否公开」（单独一列，不走名片整行写入）"""
    return db.set_show_rank(uid, on)


# ---- 特权（外观全解锁 / 彩虹名字）----
# ⚠️ 只给运维/脚本用，**不要**挂到任何自助接口上：特权能被自己领就不叫特权了。
def list_user_perks(uid: str):
    """该账号持有的特权集合"""
    return db.list_user_perks(uid)


def get_perks_map(uids):
    """批量 `{uid: set(perk)}`（排行榜用，避免 N 次查询）"""
    return db.get_perks_map(uids)


def has_user_perk(uid: str, perk: str):
    """是否持有某特权"""
    return db.has_user_perk(uid, perk)


def grant_user_perk(uid: str, perk: str):
    """授予特权（幂等）"""
    return db.grant_user_perk(uid, perk)


def revoke_user_perk(uid: str, perk: str):
    """收回特权（幂等）"""
    return db.revoke_user_perk(uid, perk)


# ---- 徽章 / 成就（server.py 结算与 api.py 图鉴都走模块级函数）----
def get_user_counters(uid: str):
    """每局累计计数（无记录时返回全 0 默认值，不写库）"""
    return db.get_user_counters(uid)


def bump_user_counters(uid: str, **deltas):
    """累加每局计数（只在 server._finalize_match 里调）"""
    return db.bump_user_counters(uid, **deltas)


def get_user_achievements(uid: str):
    """已解锁徽章 {badge_id: unlocked_at}"""
    return db.get_user_achievements(uid)


def grant_user_achievements(uid: str, badge_ids):
    """授予徽章，返回本次**新增**的 id 列表"""
    return db.grant_user_achievements(uid, badge_ids)


def get_distinct_cards_used(uid: str):
    """用过的不同卡名张数"""
    return db.get_distinct_cards_used(uid)


# ---- 点赞 / 送花 / 留言板（api.py 与测试都走模块级函数）----
# ⚠️ 必须与类方法成对存在：本项目按模块级名字打桩（`db.list_profile_messages = ...`），
# 只实现类方法会让打桩被绕过 —— 第 2 批为此吃过一次假红。
def set_show_guestbook(uid: str, on):
    """写「留言板是否公开」（单独一列，不走名片整行写入）"""
    return db.set_show_guestbook(uid, on)


def set_profile_reaction(from_uid: str, to_uid: str, kind: str, on):
    """点赞 / 送花（幂等增删）"""
    return db.set_profile_reaction(from_uid, to_uid, kind, on)


def get_profile_reaction_counts(uid: str):
    """某人收到的互动计数 {like, flower}"""
    return db.get_profile_reaction_counts(uid)


def get_my_reactions(from_uid: str, to_uid: str):
    """我对某人的互动状态 {like: bool, flower: bool}"""
    return db.get_my_reactions(from_uid, to_uid)


def add_profile_message(to_uid: str, from_uid: str, from_name: str, content: str):
    """写一条留言，返回新行 id（失败 0）"""
    return db.add_profile_message(to_uid, from_uid, from_name, content)


def list_profile_messages(to_uid: str, limit: int = 20, before_id=None):
    """留言列表 {messages, has_more, total}（只含未软删的）"""
    return db.list_profile_messages(to_uid, limit, before_id)


def get_profile_message(msg_id):
    """按 id 取一条留言（含已软删的，供删除权限校验）"""
    return db.get_profile_message(msg_id)


def soft_delete_profile_message(msg_id):
    """软删留言（deleted = 1）"""
    return db.soft_delete_profile_message(msg_id)


def count_profile_messages_since(from_uid: str, to_uid: str, since: int):
    """`since` 之后 from → to 的留言条数（每日上限用）"""
    return db.count_profile_messages_since(from_uid, to_uid, since)


def _safe_dao(fn, default):
    """调一个 DAO 包装并把任何异常吞成默认值。

    用于「这个字段读不到也不该让接口 500」的场合（例如并行开发期某个 DAO 还没落地、
    或者库被锁）。`tests/test_achievements.py::test_endpoints_survive_missing_daos`
    就是在钉这条：缺 DAO 时接口要降级，不是崩。
    """
    try:
        return fn()
    except Exception as e:      # noqa: BLE001 —— 兜底就是为了不崩
        logger.warning(f'读取徽章判据数据失败，按默认值处理: {e}')
        return default


def get_achievement_stats(uid: str, base: dict = None, user: dict = None, rank=None):
    """徽章判定用的 stats —— **唯一一份组装实现**，结算与接口两条路径共用。

    结算路径 `server._finalize_match` 与接口/图鉴路径 `api.py` 都调这里。
    曾经两处各拼一份：当时两份都覆盖了 `achievements.CONTEXT_KEYS` 全集、结论一致，
    但那是巧合而非保证 —— 谁漏加一个键，对应判据就会**静默恒假**
    （`achievement_context` 把缺字段按 0 算，不报错）。

    ⚠️ 刻意写成**模块级函数**而不是 `Database` 的方法：本项目的测试与调用方都通过
    模块级包装打桩（`db.get_user_counters = ...`）。放进类里会让 `self.xxx` 绕过打桩，
    表现为「测试里明明是 12 场，接口却按 0 算」这种查半天的假红（我改的第一版就踩了）。

    :param base: 已拿到的 users 字段（缺的键会补）
    :param user: 已取到的 users 行（给了就不再查一次）
    :param rank: 已算好的名次（None 时才自己算）
    """
    if not uid:
        return {}
    row = user if isinstance(user, dict) else _safe_dao(lambda: get_user(uid=uid), {})
    row = row if isinstance(row, dict) else {}
    stats = dict(base) if isinstance(base, dict) else {}
    for key in ('wins', 'losses', 'longest_streak', 'created_at'):
        stats.setdefault(key, row.get(key))
    counters = _safe_dao(lambda: get_user_counters(uid), {})
    counters = counters if isinstance(counters, dict) else {}
    stats.update({
        'matches_played': counters.get('matches_played'),
        'sunk_total': counters.get('sunk_total'),
        'flawless_wins': counters.get('flawless_wins'),
        'fastest_win_sec': counters.get('fastest_win_sec'),
    })
    stats['card_uses_total'] = _safe_dao(lambda: get_user_card_uses_total(uid), 0)
    stats['distinct_cards'] = _safe_dao(lambda: get_distinct_cards_used(uid), 0)
    stats['rank'] = rank if rank is not None else _safe_dao(lambda: get_user_rank(uid), None)
    return stats


def get_token_by_password(username: str, password_hash: str):
    """通过用户名和密码哈希获取并生成token"""
    return db.get_token_by_password(username, password_hash)
