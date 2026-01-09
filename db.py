import sqlite3
import time
import uuid
from pathlib import Path

from werkzeug.security import generate_password_hash

DB_PATH = Path(__file__).parent / 'data' / 'battleship.db'


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
              CREATE TABLE IF NOT EXISTS users
              (
                  id TEXT PRIMARY KEY,
                  username TEXT UNIQUE,
                  password_hash TEXT,
                  wins INTEGER DEFAULT 0,
                  losses INTEGER DEFAULT 0,
                  current_streak INTEGER DEFAULT 0,
                  longest_streak INTEGER DEFAULT 0,
                  created_at INTEGER,
                  signature TEXT DEFAULT '',
                  avatar TEXT DEFAULT '',
                  token TEXT DEFAULT ''
              )
              ''')
    c.execute('''
              CREATE TABLE IF NOT EXISTS matches
              (
                  id TEXT PRIMARY KEY,
                  winner_id TEXT,
                  loser_id TEXT,
                  timestamp INTEGER
              )
              ''')
    c.execute('''
              CREATE TABLE IF NOT EXISTS chat_messages
              (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  username TEXT,
                  content TEXT,
                  timestamp INTEGER
              )
              ''')
    c.execute('''
              CREATE TABLE IF NOT EXISTS active_games
              (
                  user_id TEXT PRIMARY KEY,
                  room_id TEXT,
                  updated_at INTEGER
              )
              ''')
    conn.commit()
    conn.close()


def clear_temp_data():
    """重启时清空临时数据"""
    conn = get_conn()
    try:
        conn.execute('DELETE FROM active_games')
        conn.execute("UPDATE users SET token = ''")
        conn.commit()
    finally:
        conn.close()


def update_user(uid, **kwargs):
    """通用更新用户信息"""
    if not kwargs:
        return True
    conn = get_conn()
    try:
        query = 'UPDATE users SET ' + ', '.join([f"{k} = ?" for k in kwargs.keys()]) + ' WHERE id = ?'
        params = list(kwargs.values()) + [uid]
        conn.execute(query, params)
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_user(uid=None, username=None):
    """通用获取用户信息"""
    conn = get_conn()
    c = conn.cursor()
    if uid:
        row = c.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    elif username:
        row = c.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    else:
        conn.close()
        return None
    conn.close()
    return dict(row) if row else None


def get_user_by_token(token):
    """通过token获取用户信息"""
    conn = get_conn()
    c = conn.cursor()
    row = c.execute('SELECT * FROM users WHERE token = ?', (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_active_game(uid, room_id):
    conn = get_conn()
    try:
        conn.execute('INSERT OR REPLACE INTO active_games (user_id, room_id, updated_at) VALUES (?, ?, ?)',
                     (uid, room_id, int(time.time())))
        conn.commit()
    finally:
        conn.close()


def get_active_game(uid):
    conn = get_conn()
    try:
        row = conn.execute('SELECT room_id FROM active_games WHERE user_id = ?', (uid,)).fetchone()
        return row
    finally:
        conn.close()

def update_user_signature(uid, signature):
    conn = get_conn()
    try:
        conn.execute('UPDATE users SET signature = ? WHERE id = ?', (signature, uid))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def update_user_avatar(uid, avatar_path):
    conn = get_conn()
    try:
        conn.execute('UPDATE users SET avatar = ? WHERE id = ?', (avatar_path, uid))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def update_user_password(uid, password_hash):
    conn = get_conn()
    try:
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, uid))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_user_profile(uid):
    conn = get_conn()
    c = conn.cursor()
    row = c.execute('SELECT id, username, signature, avatar FROM users WHERE id = ?', (uid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_chat_message(user_id, username, content):
    conn = get_conn()
    try:
        conn.execute('INSERT INTO chat_messages (user_id, username, content, timestamp) VALUES (?, ?, ?, ?)',
                     (user_id, username, content, int(time.time())))
        conn.commit()
    finally:
        conn.close()


def get_chat_messages(limit=50):
    conn = get_conn()
    try:
        rows = conn.execute('SELECT * FROM chat_messages ORDER BY timestamp DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows][::-1]
    finally:
        conn.close()


def create_user(username, password_hash):
    conn = get_conn()
    try:
        uid = str(uuid.uuid4())
        conn.execute('INSERT INTO users (id, username, password_hash, created_at) VALUES (?,?,?,?)',
                     (uid, username, password_hash, int(time.time())))
        conn.commit()
        return uid
    except Exception:
        return None
    finally:
        conn.close()


def record_match(winner_id, loser_id):
    conn = get_conn()
    c = conn.cursor()
    mid = str(uuid.uuid4())
    t = int(time.time())
    c.execute('INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
              (mid, winner_id, loser_id, t))

    # 增加胜负统计与连胜逻辑
    # 先取目前的 streak 值以便更新 longest_streak
    winner = c.execute('SELECT current_streak, longest_streak FROM users WHERE id = ?', (winner_id,)).fetchone()
    if winner:
        new_streak = (winner['current_streak'] or 0) + 1
        new_longest = max(new_streak, (winner['longest_streak'] or 0))
        c.execute('UPDATE users SET wins = wins + 1, current_streak = ?, longest_streak = ? WHERE id = ?',
                  (new_streak, new_longest, winner_id))
    else:
        # 如果用户不存在（可能是游客），仍允许插入 match 但不更新 stats
        pass

    loser = c.execute('SELECT * FROM users WHERE id = ?', (loser_id,)).fetchone()
    if loser:
        c.execute('UPDATE users SET losses = losses + 1, current_streak = 0 WHERE id = ?', (loser_id,))

    conn.commit()
    conn.close()
    return True


def get_leaderboard(limit=10):
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute(
        'SELECT id, username, wins, losses, current_streak, longest_streak, avatar FROM users ORDER BY wins DESC, longest_streak DESC LIMIT ?',
        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_token_by_password(username, password_hash):
    """通过用户名和密码哈希获取并生成token"""
    conn = get_conn()
    c = conn.cursor()
    user = c.execute('SELECT id FROM users WHERE username = ? AND password_hash = ?', (username, password_hash)).fetchone()
    if user:
        token = str(uuid.uuid4())
        c.execute('UPDATE users SET token = ? WHERE id = ?', (token, user['id']))
        conn.commit()
        conn.close()
        return token
    conn.close()
    return None

