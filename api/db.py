"""
Cloudflare D1 Database Adapter
支持两种模式：
  1. Workers 模式：通过 D1 binding (env.DB) 操作数据库
  2. 本地模式：通过 sqlite3 模块操作 (开发调试用)

两种模式共享同一套 SQL 语法（D1 兼容 SQLite）。
"""
import os
import sqlite3
import asyncio
import uuid
from datetime import datetime

# ── 全局状态 ────────────────────────────────────────────────────
_d1_binding = None          # Workers D1 binding
_is_workers = False          # 是否运行在 Workers 环境
_db_path = None              # 本地 SQLite 数据库路径


# ═════════════════════════════════════════════════════════════════
# 初始化
# ═════════════════════════════════════════════════════════════════

def init(env_db=None, db_path=None):
    """
    初始化数据库层。
    参数:
        env_db: Workers D1 binding（传入时启用 Workers 模式）
        db_path: 本地 SQLite 路径（仅在非 Workers 模式时使用）
    """
    global _d1_binding, _is_workers, _db_path
    if env_db is not None:
        _d1_binding = env_db
        _is_workers = True
    else:
        _is_workers = False
        _db_path = db_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'blog.db'
        )
    _init_tables()


def _run_async(coro):
    """在同步上下文中执行 async D1 调用。"""
    if _is_workers:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Workers 环境已有运行中的 loop
                import js
                return js.Promise.resolve(coro).then(lambda x: x)
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)
    return None


# ═════════════════════════════════════════════════════════════════
# 数据库连接（本地模式）
# ═════════════════════════════════════════════════════════════════

def _get_conn():
    """获取本地 SQLite 连接。"""
    if _is_workers:
        raise RuntimeError("Cannot use sqlite3 in Workers mode")
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ═════════════════════════════════════════════════════════════════
# 通用查询执行
# ═════════════════════════════════════════════════════════════════

async def _d1_exec(sql, params=None):
    """在 D1 上执行 SQL 语句。"""
    if not _d1_binding:
        raise RuntimeError("D1 binding not initialized")
    stmt = _d1_binding.prepare(sql)
    if params:
        stmt = stmt.bind(*params)
    return await stmt.run()


async def _d1_query(sql, params=None):
    """在 D1 上执行查询并返回结果列表。"""
    if not _d1_binding:
        raise RuntimeError("D1 binding not initialized")
    stmt = _d1_binding.prepare(sql)
    if params:
        stmt = stmt.bind(*params)
    result = await stmt.all()
    if result.success:
        return [dict(r) for r in result.results]
    return []


async def _d1_query_one(sql, params=None):
    """在 D1 上执行查询并返回单条结果。"""
    results = await _d1_query(sql, params)
    return results[0] if results else None


# ═════════════════════════════════════════════════════════════════
# 表结构初始化
# ═════════════════════════════════════════════════════════════════

def _init_tables():
    """创建数据库表结构。"""
    schema = """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            summary TEXT DEFAULT '',
            image TEXT DEFAULT '',
            image_data TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            views INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS post_tags (
            post_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (post_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS images (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            mime_type TEXT DEFAULT 'image/png',
            filename TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
    """

    if _is_workers:
        # D1 模式
        asyncio.get_event_loop().run_until_complete(
            _d1_exec(schema)
        )
    else:
        # SQLite 本地模式
        conn = _get_conn()
        conn.executescript(schema)
        conn.commit()
        conn.close()


# ═════════════════════════════════════════════════════════════════
# Settings
# ═════════════════════════════════════════════════════════════════

def get_setting(key, default=None):
    """获取设置值。"""
    if _is_workers:
        row = asyncio.get_event_loop().run_until_complete(
            _d1_query_one('SELECT value FROM settings WHERE key=?', (key,))
        )
        return row['value'] if row else default
    else:
        conn = _get_conn()
        row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        conn.close()
        return row['value'] if row else default


def set_setting(key, value):
    """设置值。"""
    if _is_workers:
        asyncio.get_event_loop().run_until_complete(
            _d1_exec('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        )
    else:
        conn = _get_conn()
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()


# ═════════════════════════════════════════════════════════════════
# Posts
# ═════════════════════════════════════════════════════════════════

def get_posts(page=1, per_page=10, search=None, tag=None):
    """获取文章列表（分页）。"""
    offset = (page - 1) * per_page

    if _is_workers:
        loop = asyncio.get_event_loop()
        if search:
            like = f'%{search}%'
            total = len(loop.run_until_complete(
                _d1_query('SELECT id FROM posts WHERE title LIKE ? OR content LIKE ? OR summary LIKE ?',
                          (like, like, like))
            ))
            posts = loop.run_until_complete(
                _d1_query('SELECT * FROM posts WHERE title LIKE ? OR content LIKE ? OR summary LIKE ? '
                          'ORDER BY created_at DESC LIMIT ? OFFSET ?',
                          (like, like, like, per_page, offset))
            )
        elif tag:
            total = len(loop.run_until_complete(
                _d1_query('SELECT p.id FROM posts p JOIN post_tags pt ON p.id=pt.post_id '
                          'JOIN tags t ON t.id=pt.tag_id WHERE t.name=?', (tag,))
            ))
            posts = loop.run_until_complete(
                _d1_query('SELECT p.* FROM posts p JOIN post_tags pt ON p.id=pt.post_id '
                          'JOIN tags t ON t.id=pt.tag_id WHERE t.name=? '
                          'ORDER BY p.created_at DESC LIMIT ? OFFSET ?',
                          (tag, per_page, offset))
            )
        else:
            total = len(loop.run_until_complete(_d1_query('SELECT id FROM posts')))
            posts = loop.run_until_complete(
                _d1_query('SELECT * FROM posts ORDER BY created_at DESC LIMIT ? OFFSET ?',
                          (per_page, offset))
            )
        return posts, total
    else:
        conn = _get_conn()
        posts = []
        total = 0
        if search:
            like = f'%{search}%'
            total = conn.execute(
                'SELECT COUNT(*) FROM posts WHERE title LIKE ? OR content LIKE ? OR summary LIKE ?',
                (like, like, like)
            ).fetchone()[0]
            posts = conn.execute(
                'SELECT * FROM posts WHERE title LIKE ? OR content LIKE ? OR summary LIKE ? '
                'ORDER BY created_at DESC LIMIT ? OFFSET ?',
                (like, like, like, per_page, offset)
            ).fetchall()
        elif tag:
            total = conn.execute(
                'SELECT COUNT(*) FROM posts p JOIN post_tags pt ON p.id=pt.post_id '
                'JOIN tags t ON t.id=pt.tag_id WHERE t.name=?', (tag,)
            ).fetchone()[0]
            posts = conn.execute(
                'SELECT p.* FROM posts p JOIN post_tags pt ON p.id=pt.post_id '
                'JOIN tags t ON t.id=pt.tag_id WHERE t.name=? '
                'ORDER BY p.created_at DESC LIMIT ? OFFSET ?',
                (tag, per_page, offset)
            ).fetchall()
        else:
            total = conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
            posts = conn.execute(
                'SELECT * FROM posts ORDER BY created_at DESC LIMIT ? OFFSET ?',
                (per_page, offset)
            ).fetchall()
        conn.close()
        return [dict(p) for p in posts], total


def get_post(post_id):
    """获取单篇文章。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            _d1_query_one('SELECT * FROM posts WHERE id=?', (post_id,))
        )
    else:
        conn = _get_conn()
        post = conn.execute('SELECT * FROM posts WHERE id=?', (post_id,)).fetchone()
        conn.close()
        return dict(post) if post else None


def get_post_by_slug(slug):
    """通过 slug 获取文章。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            _d1_query_one('SELECT * FROM posts WHERE slug=?', (slug,))
        )
    else:
        conn = _get_conn()
        post = conn.execute('SELECT * FROM posts WHERE slug=?', (slug,)).fetchone()
        conn.close()
        return dict(post) if post else None


def increment_views(post_id):
    """增加文章阅读数。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            _d1_exec('UPDATE posts SET views = views + 1 WHERE id=?', (post_id,))
        )
    else:
        conn = _get_conn()
        conn.execute('UPDATE posts SET views = views + 1 WHERE id=?', (post_id,))
        conn.commit()
        conn.close()


def create_post(title, slug, content, summary='', image='', tags_str=''):
    """创建文章，返回 post_id。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if _is_workers:
        loop = asyncio.get_event_loop()

        # 确保 slug 唯一
        existing = loop.run_until_complete(
            _d1_query_one('SELECT id FROM posts WHERE slug=?', (slug,))
        )
        if existing:
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        result = loop.run_until_complete(
            _d1_exec(
                'INSERT INTO posts (title, slug, content, summary, image, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (title, slug, content, summary, image, now, now)
            )
        )
        post_id = result.lastRowId if hasattr(result, 'lastRowId') else None

        # 处理标签
        _process_tags_d1(post_id, tags_str)

        return post_id
    else:
        conn = _get_conn()
        existing = conn.execute('SELECT id FROM posts WHERE slug=?', (slug,)).fetchone()
        if existing:
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        cursor = conn.execute(
            'INSERT INTO posts (title, slug, content, summary, image, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (title, slug, content, summary, image, now, now)
        )
        post_id = cursor.lastrowid
        _process_tags_sqlite(conn, post_id, tags_str)
        conn.commit()
        conn.close()
        return post_id


def update_post(post_id, title, content, summary='', image=None, tags_str='', delete_image=False):
    """更新文章。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if _is_workers:
        loop = asyncio.get_event_loop()

        if image is not None:
            if delete_image:
                loop.run_until_complete(
                    _d1_exec('UPDATE posts SET title=?, content=?, summary=?, image=?, updated_at=? WHERE id=?',
                             (title, content, summary, '', now, post_id))
                )
            else:
                loop.run_until_complete(
                    _d1_exec('UPDATE posts SET title=?, content=?, summary=?, image=?, updated_at=? WHERE id=?',
                             (title, content, summary, image, now, post_id))
                )
        else:
            loop.run_until_complete(
                _d1_exec('UPDATE posts SET title=?, content=?, summary=?, updated_at=? WHERE id=?',
                         (title, content, summary, now, post_id))
            )

        # 删除旧标签关联
        loop.run_until_complete(
            _d1_exec('DELETE FROM post_tags WHERE post_id=?', (post_id,))
        )
        _process_tags_d1(post_id, tags_str)
    else:
        conn = _get_conn()
        if image is not None:
            if delete_image:
                conn.execute(
                    'UPDATE posts SET title=?, content=?, summary=?, image=?, updated_at=? WHERE id=?',
                    (title, content, summary, '', now, post_id)
                )
            else:
                conn.execute(
                    'UPDATE posts SET title=?, content=?, summary=?, image=?, updated_at=? WHERE id=?',
                    (title, content, summary, image, now, post_id)
                )
        else:
            conn.execute(
                'UPDATE posts SET title=?, content=?, summary=?, updated_at=? WHERE id=?',
                (title, content, summary, now, post_id)
            )
        conn.execute('DELETE FROM post_tags WHERE post_id=?', (post_id,))
        _process_tags_sqlite(conn, post_id, tags_str)
        conn.commit()
        conn.close()


def delete_post(post_id):
    """删除文章。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        post = loop.run_until_complete(
            _d1_query_one('SELECT * FROM posts WHERE id=?', (post_id,))
        )
        if not post:
            return None
        loop.run_until_complete(_d1_exec('DELETE FROM posts WHERE id=?', (post_id,)))
        return post
    else:
        conn = _get_conn()
        post = conn.execute('SELECT * FROM posts WHERE id=?', (post_id,)).fetchone()
        if not post:
            conn.close()
            return None
        conn.execute('DELETE FROM posts WHERE id=?', (post_id,))
        conn.commit()
        conn.close()
        return dict(post)


def get_all_posts_admin():
    """获取所有文章（管理列表，不含内容）。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            _d1_query('SELECT id, title, slug, created_at, updated_at, views FROM posts ORDER BY created_at DESC')
        )
    else:
        conn = _get_conn()
        posts = conn.execute(
            'SELECT id, title, slug, created_at, updated_at, views FROM posts ORDER BY created_at DESC'
        ).fetchall()
        conn.close()
        return [dict(p) for p in posts]


def get_post_tags(post_id):
    """获取文章的标签列表。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        tags = loop.run_until_complete(
            _d1_query('SELECT t.name FROM tags t JOIN post_tags pt ON t.id=pt.tag_id WHERE pt.post_id=?',
                      (post_id,))
        )
        return [t['name'] for t in tags]
    else:
        conn = _get_conn()
        tags = conn.execute(
            'SELECT t.name FROM tags t JOIN post_tags pt ON t.id=pt.tag_id WHERE pt.post_id=?',
            (post_id,)
        ).fetchall()
        conn.close()
        return [t['name'] for t in tags]


def get_adjacent_posts(created_at):
    """获取上一篇和下一篇文章。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        prev = loop.run_until_complete(
            _d1_query_one('SELECT id, title FROM posts WHERE created_at < ? ORDER BY created_at DESC LIMIT 1',
                          (created_at,))
        )
        next_p = loop.run_until_complete(
            _d1_query_one('SELECT id, title FROM posts WHERE created_at > ? ORDER BY created_at ASC LIMIT 1',
                          (created_at,))
        )
        return prev, next_p
    else:
        conn = _get_conn()
        prev = conn.execute(
            'SELECT id, title FROM posts WHERE created_at < ? ORDER BY created_at DESC LIMIT 1',
            (created_at,)
        ).fetchone()
        next_p = conn.execute(
            'SELECT id, title FROM posts WHERE created_at > ? ORDER BY created_at ASC LIMIT 1',
            (created_at,)
        ).fetchone()
        conn.close()
        return dict(prev) if prev else None, dict(next_p) if next_p else None


# ═════════════════════════════════════════════════════════════════
# Tags
# ═════════════════════════════════════════════════════════════════

def get_all_tags():
    """获取所有标签。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            _d1_query('SELECT * FROM tags ORDER BY name')
        )
    else:
        conn = _get_conn()
        tags = conn.execute('SELECT * FROM tags ORDER BY name').fetchall()
        conn.close()
        return [dict(t) for t in tags]


def _process_tags_d1(post_id, tags_str):
    """D1 模式：处理文章标签。"""
    if not tags_str:
        return
    loop = asyncio.get_event_loop()
    for name in [t.strip() for t in tags_str.split(',') if t.strip()]:
        tag = loop.run_until_complete(
            _d1_query_one('SELECT id FROM tags WHERE name=?', (name,))
        )
        if tag:
            tag_id = tag['id']
        else:
            result = loop.run_until_complete(
                _d1_exec('INSERT INTO tags (name) VALUES (?)', (name,))
            )
            tag_id = result.lastRowId if hasattr(result, 'lastRowId') else None
        if tag_id:
            loop.run_until_complete(
                _d1_exec('INSERT OR IGNORE INTO post_tags (post_id, tag_id) VALUES (?, ?)',
                         (post_id, tag_id))
            )


def _process_tags_sqlite(conn, post_id, tags_str):
    """SQLite 模式：处理文章标签。"""
    if not tags_str:
        return
    for name in [t.strip() for t in tags_str.split(',') if t.strip()]:
        tag = conn.execute('SELECT id FROM tags WHERE name=?', (name,)).fetchone()
        if tag:
            tag_id = tag['id']
        else:
            cursor = conn.execute('INSERT INTO tags (name) VALUES (?)', (name,))
            tag_id = cursor.lastrowid
        conn.execute('INSERT OR IGNORE INTO post_tags (post_id, tag_id) VALUES (?, ?)',
                     (post_id, tag_id))


# ═════════════════════════════════════════════════════════════════
# 统计
# ═════════════════════════════════════════════════════════════════

def get_stats():
    """获取站点统计。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        total_posts = len(loop.run_until_complete(_d1_query('SELECT id FROM posts')))
        views_row = loop.run_until_complete(
            _d1_query_one('SELECT COALESCE(SUM(views), 0) as total FROM posts')
        )
        total_views = views_row['total'] if views_row else 0
        total_tags = len(loop.run_until_complete(_d1_query('SELECT id FROM tags')))
        last = loop.run_until_complete(
            _d1_query_one('SELECT updated_at FROM posts ORDER BY updated_at DESC LIMIT 1')
        )
        return {
            'total_posts': total_posts,
            'total_views': total_views,
            'total_tags': total_tags,
            'last_updated': last['updated_at'] if last else None,
        }
    else:
        conn = _get_conn()
        total_posts = conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
        total_views = conn.execute('SELECT COALESCE(SUM(views), 0) FROM posts').fetchone()[0]
        total_tags = conn.execute('SELECT COUNT(*) FROM tags').fetchone()[0]
        last = conn.execute('SELECT updated_at FROM posts ORDER BY updated_at DESC LIMIT 1').fetchone()
        conn.close()
        return {
            'total_posts': total_posts,
            'total_views': total_views,
            'total_tags': total_tags,
            'last_updated': last['updated_at'] if last else None,
        }


def get_recent_posts(limit=5):
    """获取最近文章。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            _d1_query('SELECT id, title, created_at FROM posts ORDER BY created_at DESC LIMIT ?', (limit,))
        )
    else:
        conn = _get_conn()
        posts = conn.execute(
            'SELECT id, title, created_at FROM posts ORDER BY created_at DESC LIMIT ?',
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(p) for p in posts]


# ═════════════════════════════════════════════════════════════════
# Images (D1 base64 存储，替代文件系统)
# ═════════════════════════════════════════════════════════════════

def save_image(image_id, data_base64, mime_type='image/png', filename=''):
    """将图片保存到数据库。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if _is_workers:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            _d1_exec(
                'INSERT OR REPLACE INTO images (id, data, mime_type, filename, created_at) VALUES (?, ?, ?, ?, ?)',
                (image_id, data_base64, mime_type, filename, now)
            )
        )
    else:
        conn = _get_conn()
        conn.execute(
            'INSERT OR REPLACE INTO images (id, data, mime_type, filename, created_at) VALUES (?, ?, ?, ?, ?)',
            (image_id, data_base64, mime_type, filename, now)
        )
        conn.commit()
        conn.close()


def get_image(image_id):
    """从数据库获取图片。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            _d1_query_one('SELECT * FROM images WHERE id=?', (image_id,))
        )
    else:
        conn = _get_conn()
        img = conn.execute('SELECT * FROM images WHERE id=?', (image_id,)).fetchone()
        conn.close()
        return dict(img) if img else None


def delete_image(image_id):
    """从数据库删除图片。"""
    if _is_workers:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_d1_exec('DELETE FROM images WHERE id=?', (image_id,)))
    else:
        conn = _get_conn()
        conn.execute('DELETE FROM images WHERE id=?', (image_id,))
        conn.commit()
        conn.close()
