"""
统一数据库适配层 - 同时支持 PostgreSQL 和 SQLite
解决原项目中 app.py (PostgreSQL) 和 api/db.py (SQLite/D1) 架构混乱的问题

使用示例:
    from db_unified import get_db
    
    db = get_db()
    posts = db.fetch_all('SELECT * FROM posts')
"""
import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


# ── 数据库抽象基类 ────────────────────────────────────────────

class Database(ABC):
    """数据库抽象基类，定义统一的接口。"""
    
    @abstractmethod
    def execute(self, sql: str, params: Optional[tuple] = None) -> Any:
        """执行 SQL 并返回 cursor。"""
        pass
    
    @abstractmethod
    def fetch_all(self, sql: str, params: Optional[tuple] = None) -> List[Dict]:
        """查询所有行。"""
        pass
    
    @abstractmethod
    def fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[Dict]:
        """查询单行。"""
        pass
    
    @abstractmethod
    def fetch_val(self, sql: str, params: Optional[tuple] = None) -> Any:
        """查询单个值。"""
        pass
    
    @abstractmethod
    def close(self):
        """关闭数据库连接。"""
        pass


# ── PostgreSQL 实现 ──────────────────────────────────────────

class PostgreSQLDB(Database):
    """PostgreSQL 数据库实现（用于 Render 部署）。"""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.conn = None
    
    def _get_conn(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(self.db_url, sslmode='require')
        return self.conn
    
    def execute(self, sql: str, params: Optional[tuple] = None) -> Any:
        conn = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        conn.commit()
        return cur
    
    def fetch_all(self, sql: str, params: Optional[tuple] = None) -> List[Dict]:
        cur = self.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    
    def fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[Dict]:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    
    def fetch_val(self, sql: str, params: Optional[tuple] = None) -> Any:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return list(row.values())[0]
    
    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()


# ── SQLite 实现 ──────────────────────────────────────────────

class SQLiteDB(Database):
    """SQLite 数据库实现（用于本地开发）。"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
    
    def _get_conn(self):
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
        return self.conn
    
    def _adapt_sql(self, sql: str) -> str:
        """将 PostgreSQL 语法适配为 SQLite 语法。"""
        # ILIKE -> LIKE (SQLite 不区分大小写)
        sql = sql.replace('ILIKE', 'LIKE')
        # %s -> ? (SQLite 参数占位符)
        # 注意：这个简单替换可能不适用于所有情况
        return sql
    
    def _adapt_params(self, params: Optional[tuple]) -> Optional[tuple]:
        """适配参数（如果需要）。"""
        return params
    
    def execute(self, sql: str, params: Optional[tuple] = None) -> Any:
        conn = self._get_conn()
        adapted_sql = self._adapt_sql(sql)
        adapted_params = self._adapt_params(params)
        cur = conn.cursor()
        if adapted_params:
            cur.execute(adapted_sql, adapted_params)
        else:
            cur.execute(adapted_sql)
        conn.commit()
        return cur
    
    def fetch_all(self, sql: str, params: Optional[tuple] = None) -> List[Dict]:
        cur = self.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    
    def fetch_one(self, sql: str, params: Optional[tuple] = None) -> Optional[Dict]:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    
    def fetch_val(self, sql: str, params: Optional[tuple] = None) -> Any:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        return list(row.values())[0]
    
    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


# ── 工厂函数 ─────────────────────────────────────────────────

def get_db() -> Database:
    """
    根据环境变量返回对应的数据库实例。
    
    环境变量:
        DATABASE_URL: 如果设置，使用 PostgreSQL
        否则使用本地 SQLite (blog.db)
    """
    db_url = os.environ.get('DATABASE_URL')
    
    if db_url:
        # PostgreSQL 模式 (生产环境)
        return PostgreSQLDB(db_url)
    else:
        # SQLite 模式 (本地开发)
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'blog.db'
        )
        return SQLiteDB(db_path)


# ── 上下文管理器 ─────────────────────────────────────────────

class DBConnection:
    """数据库连接上下文管理器，确保连接正确关闭。"""
    
    def __init__(self):
        self.db = get_db()
    
    def __enter__(self):
        return self.db
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()
        return False  # 不吞掉异常


# ── 使用示例 ─────────────────────────────────────────────────

def example_usage():
    """示例代码：展示如何使用统一的数据库层。"""
    
    # 方式1：直接使用
    db = get_db()
    try:
        posts = db.fetch_all('SELECT * FROM posts ORDER BY created_at DESC')
        for post in posts:
            print(post['title'])
    finally:
        db.close()
    
    # 方式2：使用上下文管理器（推荐）
    with DBConnection() as db:
        post = db.fetch_one('SELECT * FROM posts WHERE id=?', (1,))
        if post:
            print(post['title'])


if __name__ == '__main__':
    # 测试
    print("测试统一数据库层...")
    with DBConnection() as db:
        # 初始化表结构
        db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        print("✓ 数据库连接成功！")
        print(f"✓ 数据库类型: {type(db).__name__}")
