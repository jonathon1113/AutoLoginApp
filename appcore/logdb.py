"""SQLite 登录日志存储（表结构与原项目保持一致）。"""

import datetime
import sqlite3

from .config import LOG_DB_FILE


class LogDB:
    def __init__(self, db_path=LOG_DB_FILE):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                device_name TEXT,
                url TEXT,
                status TEXT,
                message TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def add_log(self, device_name, url, status, message):
        """添加日志"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO login_logs (timestamp, device_name, url, status, message) VALUES (?, ?, ?, ?, ?)",
            (timestamp, device_name, url, status, message)
        )
        conn.commit()
        conn.close()

    def get_recent_logs(self, limit=100):
        """获取最近日志"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp, device_name, status, message FROM login_logs ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        logs = cursor.fetchall()
        conn.close()
        return logs

    def clear_logs(self):
        """清空日志"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM login_logs")
        conn.commit()
        conn.close()


log_db = LogDB()
