import json
import sqlite3
import time
import uuid
from pathlib import Path


class Database:
    def __init__(self):
        self.db_path = Path(__file__).parent / 'data' / 'battleship.db'
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
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
        self.cursor.execute('''
              CREATE TABLE IF NOT EXISTS matches
              (
                  id        TEXT PRIMARY KEY,
                  winner_id TEXT,
                  loser_id  TEXT,
                  timestamp INTEGER
              )
              ''')
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
        self.cursor.execute('''
              CREATE TABLE IF NOT EXISTS active_games
              (
                  user_id    TEXT PRIMARY KEY,
                  room_id    TEXT,
                  updated_at INTEGER
              )
              ''')
        self.conn.commit()
        self.cursor.execute('''
              CREATE TABLE IF NOT EXISTS match_logs
              (
                  match_id TEXT PRIMARY KEY,
                  logs     TEXT
              )
              ''')
        self.conn.commit()
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
        except Exception:
            # 视图创建失败不影响核心功能
            pass
    
    def clear_temp_data(self):
        """重启时清空临时数据"""
        try:
            self.cursor.execute('DELETE FROM active_games')
            self.cursor.execute("UPDATE users SET token = ''")
            self.conn.commit()
        except Exception:
            pass
    
    def update_user(self, uid: str, **kwargs):
        """通用更新用户信息"""
        if not kwargs:
            return True
        try:
            query = 'UPDATE users SET ' + ', '.join([f"{k} = ?" for k in kwargs.keys()]) + ' WHERE id = ?'
            params = list(kwargs.values()) + [uid]
            self.cursor.execute(query, params)
            self.conn.commit()
            return True
        except Exception:
            return False
    
    def get_user(self, uid="", username=""):
        """通用获取用户信息"""
        if uid:
            row = self.cursor.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        elif username:
            row = self.cursor.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        else:
            return None
        return dict(row) if row else None
    
    def get_user_by_token(self, token: str):
        """通过token获取用户信息"""
        row = self.cursor.execute('SELECT * FROM users WHERE token = ?', (token,)).fetchone()
        return dict(row) if row else None
    
    def save_active_game(self, uid: str, room_id: str):
        try:
            self.cursor.execute('INSERT OR REPLACE INTO active_games (user_id, room_id, updated_at) VALUES (?, ?, ?)',
                         (uid, room_id, int(time.time())))
            self.conn.commit()
        except Exception:
            pass
    
    def get_active_game(self, uid: str):
        try:
            row = self.cursor.execute('SELECT room_id FROM active_games WHERE user_id = ?', (uid,)).fetchone()
            return row
        except Exception:
            return None
    
    def update_user_signature(self, uid: str, signature: str):
        try:
            self.cursor.execute('UPDATE users SET signature = ? WHERE id = ?', (signature, uid))
            self.conn.commit()
            return True
        except Exception:
            return False
    
    def update_user_avatar(self, uid: str, avatar_path: str):
        try:
            self.cursor.execute('UPDATE users SET avatar = ? WHERE id = ?', (avatar_path, uid))
            self.conn.commit()
            return True
        except Exception:
            return False
    
    def update_user_password(self, uid: str, password_hash: str):
        try:
            self.cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, uid))
            self.conn.commit()
            return True
        except Exception:
            return False
    
    def get_user_profile(self, uid: str):
        row = self.cursor.execute('SELECT id, username, signature, avatar FROM users WHERE id = ?', (uid,)).fetchone()
        return dict(row) if row else None
    
    def add_chat_message(self, user_id: str, username: str, content: str):
        try:
            self.cursor.execute('INSERT INTO chat_messages (user_id, username, content, timestamp) VALUES (?, ?, ?, ?)',
                         (user_id, username, content, int(time.time())))
            self.conn.commit()
        except Exception:
            pass
    
    def get_chat_messages(self, limit=50):
        try:
            rows = self.cursor.execute('SELECT * FROM chat_messages ORDER BY timestamp DESC LIMIT ?', (limit,)).fetchall()
            return [dict(r) for r in rows][::-1]
        except Exception:
            return []
    
    def create_user(self, username: str, password_hash: str):
        try:
            uid = str(uuid.uuid4())
            self.cursor.execute('INSERT INTO users (id, username, password_hash, created_at) VALUES (?,?,?,?)',
                         (uid, username, password_hash, int(time.time())))
            self.conn.commit()
            return uid
        except Exception:
            return None
    
    def record_match(self, winner_id: str, loser_id: str, logs=None):
        mid = str(uuid.uuid4())
        t = int(time.time())
        self.cursor.execute('INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
                  (mid, winner_id, loser_id, t))
    
        # 记录局内日志（可选）
        if logs is not None:
            try:
                logs_json = json.dumps(logs, ensure_ascii=False)
                self.cursor.execute('INSERT OR REPLACE INTO match_logs (match_id, logs) VALUES (?, ?)', (mid, logs_json))
            except Exception:
                # 忽略日志序列化错误，仍然保留胜负记录
                pass
    
        # 增加胜负统计与连胜逻辑
        # 先取目前的 streak 值以便更新 longest_streak
        winner = self.cursor.execute('SELECT current_streak, longest_streak FROM users WHERE id = ?', (winner_id,)).fetchone()
        if winner:
            new_streak = (winner['current_streak'] or 0) + 1
            new_longest = max(new_streak, (winner['longest_streak'] or 0))
            self.cursor.execute('UPDATE users SET wins = wins + 1, current_streak = ?, longest_streak = ? WHERE id = ?',
                      (new_streak, new_longest, winner_id))
        else:
            # 如果用户不存在（可能是游客），仍允许插入 match 但不更新 stats
            pass
    
        loser = self.cursor.execute('SELECT * FROM users WHERE id = ?', (loser_id,)).fetchone()
        if loser:
            self.cursor.execute('UPDATE users SET losses = losses + 1, current_streak = 0 WHERE id = ?', (loser_id,))
    
        self.conn.commit()
        return True
    
    def get_match_history(self, uid: str, limit=20):
        rows = self.cursor.execute('''
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
        ''', (uid, uid, limit)).fetchall()
        
        history = []
        for r in rows:
            logs = []
            if r['logs']:
                try:
                    logs = json.loads(r['logs'])
                except Exception:
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
        return history
    
    def get_leaderboard(self, limit=10):
        rows = self.cursor.execute(
            'SELECT id, username, wins, losses, current_streak, longest_streak, avatar FROM users ORDER BY wins DESC, longest_streak DESC LIMIT ?',
            (limit,)).fetchall()
        return [dict(r) for r in rows]
    
    def get_token_by_password(self, username: str, password_hash: str):
        """通过用户名和密码哈希获取并生成token"""
        user = self.cursor.execute('SELECT id FROM users WHERE username = ? AND password_hash = ?',
                     (username, password_hash)).fetchone()
        if user:
            token = str(uuid.uuid4())
            self.cursor.execute('UPDATE users SET token = ? WHERE id = ?', (token, user['id']))
            self.conn.commit()
            return token
        return None
    
    def close(self):
        """关闭数据库连接"""
        if hasattr(self, 'cursor') and self.cursor:
            self.cursor.close()
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
    
    def __del__(self):
        """对象被销毁时自动关闭数据库连接"""
        self.close()


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


def record_match(winner_id: str, loser_id: str, logs=None):
    """记录比赛"""
    return db.record_match(winner_id, loser_id, logs)


def get_match_history(uid: str, limit=20):
    """获取比赛历史"""
    return db.get_match_history(uid, limit)


def get_leaderboard(limit=10):
    """获取排行榜"""
    return db.get_leaderboard(limit)


def get_token_by_password(username: str, password_hash: str):
    """通过用户名和密码哈希获取并生成token"""
    return db.get_token_by_password(username, password_hash)
