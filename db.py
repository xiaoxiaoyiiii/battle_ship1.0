import json
import sqlite3
import time
import uuid
import logging
import threading
import os
from pathlib import Path
from werkzeug.security import check_password_hash

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
                'show_stats, show_fav_cards, show_history, updated_at '
                'FROM user_profile WHERE user_id = ?', (uid,)).fetchone()
            cursor.close()
            if not row:
                return self._profile_defaults(uid)
            data = {k: row[k] for k in row.keys()}
            data['user_id'] = uid
            data['tags'] = self._parse_tags(data.get('tags'))
            for flag in ('show_stats', 'show_fav_cards', 'show_history'):
                data[flag] = 1 if data.get(flag) is None else int(data[flag])
            data['updated_at'] = int(data.get('updated_at') or 0)
            return data
        except sqlite3.Error as e:
            logger.error(f"读取个人名片失败: uid={uid}, 错误: {e}")
            return self._profile_defaults(uid)
        except Exception as e:
            logger.error(f"读取个人名片时发生未知错误: uid={uid}, 错误: {e}")
            return self._profile_defaults(uid)

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
        for flag in ('show_stats', 'show_fav_cards', 'show_history'):
            row[flag] = 1 if row[flag] in (1, True, '1') else 0
        try:
            with self._lock:
                self.cursor.execute(
                    'INSERT INTO user_profile '
                    '(user_id, title_id, tags, status_text, frame_id, card_bg_id, '
                    ' show_stats, show_fav_cards, show_history, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
                    'ON CONFLICT(user_id) DO UPDATE SET '
                    'title_id = excluded.title_id, tags = excluded.tags, '
                    'status_text = excluded.status_text, frame_id = excluded.frame_id, '
                    'card_bg_id = excluded.card_bg_id, show_stats = excluded.show_stats, '
                    'show_fav_cards = excluded.show_fav_cards, '
                    'show_history = excluded.show_history, updated_at = excluded.updated_at',
                    (uid, str(row['title_id'] or ''), row['tags'],
                     str(row['status_text'] or ''), str(row['frame_id'] or 'none'),
                     str(row['card_bg_id'] or 'deep'), row['show_stats'],
                     row['show_fav_cards'], row['show_history'], int(time.time())))
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
