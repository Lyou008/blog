"""
Cloudflare Workers 入口 - 单文件部署
包含：D1 数据库适配 + Flask ASGI 包装 + Workers 入口
"""
import os
import sys
import asyncio
import uuid
import base64
import json
from datetime import datetime
from urllib.parse import urlparse

# ── 环境设置 ──────────────────────────────────────────────────
os.environ['CLOUDFLARE_WORKERS'] = '1'

# ── 导入 Flask ────────────────────────────────────────────────
import app as blog_app
from flask import Flask, url_for
from asgiref.wsgi import WsgiToAsgi

# Workers 中模板路径调整
_here = os.path.dirname(os.path.abspath(__file__))
blog_app.app.template_folder = os.path.join(_here, 'templates')
blog_app.app.static_folder = os.path.join(_here, 'static')

# ASGI 包装
flask_asgi = WsgiToAsgi(blog_app.app)

# ── D1 数据库适配器 ──────────────────────────────────────────
_d1 = None

def init_db(env_db):
    global _d1
    _d1 = env_db
    _run("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL, summary TEXT DEFAULT '',
            image TEXT DEFAULT '', image_data TEXT DEFAULT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            views INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS post_tags (
            post_id INTEGER NOT NULL, tag_id INTEGER NOT NULL,
            PRIMARY KEY (post_id, tag_id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS images (
            id TEXT PRIMARY KEY, data TEXT NOT NULL,
            mime_type TEXT DEFAULT 'image/png', filename TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
    """)

def _run(sql, params=None):
    if not _d1: raise RuntimeError("D1 not initialized")
    stmt = _d1.prepare(sql)
    if params: stmt = stmt.bind(*params)
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(stmt.run())

def _all(sql, params=None):
    if not _d1: raise RuntimeError("D1 not initialized")
    stmt = _d1.prepare(sql)
    if params: stmt = stmt.bind(*params)
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(stmt.all())
    return [dict(r) for r in result.results] if result.success else []

def _one(sql, params=None):
    rows = _all(sql, params)
    return rows[0] if rows else None

# ── 数据操作 API ──────────────────────────────────────────────

def db_create_post(title, slug, content, summary='', image='', tags_str=''):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    exist = _one('SELECT id FROM posts WHERE slug=?', (slug,))
    if exist: slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    _run('INSERT INTO posts (title,slug,content,summary,image,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
         (title, slug, content, summary, image, now, now))
    post_id = _one('SELECT MAX(id) as id FROM posts')['id']
    if tags_str:
        for name in [t.strip() for t in tags_str.split(',') if t.strip()]:
            tag = _one('SELECT id FROM tags WHERE name=?', (name,))
            if tag: tag_id = tag['id']
            else:
                _run('INSERT INTO tags (name) VALUES (?)', (name,))
                tag_id = _one('SELECT MAX(id) as id FROM tags')['id']
            if tag_id: _run('INSERT OR IGNORE INTO post_tags VALUES (?,?)', (post_id, tag_id))
    return post_id

def db_get_posts(page=1, per_page=10, search=None, tag=None):
    offset = (page-1)*per_page
    if search:
        like = f'%{search}%'
        total = len(_all('SELECT id FROM posts WHERE title LIKE ? OR content LIKE ?', (like, like)))
        posts = _all('SELECT * FROM posts WHERE title LIKE ? OR content LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?', (like, like, per_page, offset))
    elif tag:
        total = len(_all('SELECT p.id FROM posts p JOIN post_tags pt ON p.id=pt.post_id JOIN tags t ON t.id=pt.tag_id WHERE t.name=?', (tag,)))
        posts = _all('SELECT p.* FROM posts p JOIN post_tags pt ON p.id=pt.post_id JOIN tags t ON t.id=pt.tag_id WHERE t.name=? ORDER BY p.created_at DESC LIMIT ? OFFSET ?', (tag, per_page, offset))
    else:
        total = len(_all('SELECT id FROM posts'))
        posts = _all('SELECT * FROM posts ORDER BY created_at DESC LIMIT ? OFFSET ?', (per_page, offset))
    return posts, total

def db_get_post(post_id):
    return _one('SELECT * FROM posts WHERE id=?', (post_id,))

def db_increment_views(post_id):
    _run('UPDATE posts SET views = views + 1 WHERE id=?', (post_id,))

def db_get_post_tags(post_id):
    tags = _all('SELECT t.name FROM tags t JOIN post_tags pt ON t.id=pt.tag_id WHERE pt.post_id=?', (post_id,))
    return [t['name'] for t in tags]

def db_get_adjacent(created_at):
    prev = _one('SELECT id,title FROM posts WHERE created_at<? ORDER BY created_at DESC LIMIT 1', (created_at,))
    next_p = _one('SELECT id,title FROM posts WHERE created_at>? ORDER BY created_at ASC LIMIT 1', (created_at,))
    return prev, next_p

def db_get_admin_posts():
    return _all('SELECT id,title,slug,created_at,updated_at,views FROM posts ORDER BY created_at DESC')

def db_update_post(post_id, title, content, summary, image=None, tags_str='', delete_image=False):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if image is not None:
        img_val = '' if delete_image else image
        _run('UPDATE posts SET title=?,content=?,summary=?,image=?,updated_at=? WHERE id=?',
             (title, content, summary, img_val, now, post_id))
    else:
        _run('UPDATE posts SET title=?,content=?,summary=?,updated_at=? WHERE id=?',
             (title, content, summary, now, post_id))
    _run('DELETE FROM post_tags WHERE post_id=?', (post_id,))
    if tags_str:
        for name in [t.strip() for t in tags_str.split(',') if t.strip()]:
            tag = _one('SELECT id FROM tags WHERE name=?', (name,))
            if tag: tag_id = tag['id']
            else:
                _run('INSERT INTO tags (name) VALUES (?)', (name,))
                tag_id = _one('SELECT MAX(id) as id FROM tags')['id']
            if tag_id: _run('INSERT OR IGNORE INTO post_tags VALUES (?,?)', (post_id, tag_id))

def db_delete_post(post_id):
    post = db_get_post(post_id)
    if post: _run('DELETE FROM posts WHERE id=?', (post_id,))
    return post

def db_get_stats():
    posts = len(_all('SELECT id FROM posts'))
    views_r = _one('SELECT COALESCE(SUM(views),0) as t FROM posts')
    views = views_r['t'] if views_r else 0
    tags = len(_all('SELECT id FROM tags'))
    last = _one('SELECT updated_at FROM posts ORDER BY updated_at DESC LIMIT 1')
    return {'total_posts': posts, 'total_views': views, 'total_tags': tags,
            'last_updated': last['updated_at'] if last else None}

def db_get_recent(limit=5):
    return _all('SELECT id,title,created_at FROM posts ORDER BY created_at DESC LIMIT ?', (limit,))

def db_all_tags():
    return _all('SELECT * FROM tags ORDER BY name')

def db_get_setting(key, default=None):
    row = _one('SELECT value FROM settings WHERE key=?', (key,))
    return row['value'] if row else default

def db_set_setting(key, value):
    _run('INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)', (key, value))

def db_save_image(img_id, data, mime='image/png', filename=''):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    _run('INSERT OR REPLACE INTO images (id,data,mime_type,filename,created_at) VALUES (?,?,?,?,?)',
         (img_id, data, mime, filename, now))

def db_get_image(img_id):
    return _one('SELECT * FROM images WHERE id=?', (img_id,))

# ── 替换 app.py 中的数据库函数 ────────────────────────────────
def patch_app():
    """用 D1 版本的函数替换 Flask app 的数据库操作。"""
    blog_app.database = type('DB', (), {
        'get_posts': staticmethod(db_get_posts),
        'get_post': staticmethod(db_get_post),
        'increment_views': staticmethod(db_increment_views),
        'get_post_tags': staticmethod(db_get_post_tags),
        'get_adjacent_posts': staticmethod(db_get_adjacent),
        'get_all_posts_admin': staticmethod(db_get_admin_posts),
        'create_post': staticmethod(db_create_post),
        'update_post': staticmethod(db_update_post),
        'delete_post': staticmethod(db_delete_post),
        'get_stats': staticmethod(db_get_stats),
        'get_recent_posts': staticmethod(db_get_recent),
        'get_all_tags': staticmethod(db_all_tags),
        'get_setting': staticmethod(db_get_setting),
        'set_setting': staticmethod(db_set_setting),
        'save_image': staticmethod(db_save_image),
        'get_image': staticmethod(db_get_image),
    })()


# ── Workers 入口 ──────────────────────────────────────────────

async def on_fetch(request, env):
    try:
        # 初始化 D1
        db_binding = env.get('DB', None)
        if db_binding:
            init_db(db_binding)
            patch_app()

        # 设置环境变量
        os.environ['BLOG_ADMIN_USER'] = env.get('BLOG_ADMIN_USER', 'admin')
        os.environ['BLOG_ADMIN_PASS'] = env.get('BLOG_ADMIN_PASS', 'admin123')
        os.environ['BLOG_SECRET_KEY'] = env.get('BLOG_SECRET_KEY', 'cf-secret-key')
        blog_app.app.secret_key = os.environ['BLOG_SECRET_KEY']

        # 加载管理员密码
        from werkzeug.security import generate_password_hash
        pw_hash = db_get_setting('admin_password_hash')
        if pw_hash:
            blog_app.ADMIN_PASSWORD_HASH = pw_hash
        else:
            blog_app.ADMIN_PASSWORD_HASH = generate_password_hash(
                os.environ.get('BLOG_ADMIN_PASS', 'admin123'))
            db_set_setting('admin_password_hash', blog_app.ADMIN_PASSWORD_HASH)

        # 处理请求
        return await handle_request(request, flask_asgi)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        from js import Response
        return Response.new(
            f"<h2>Error</h2><pre>{str(e)}\n{tb}</pre>".encode(),
            status=500,
            headers={"Content-Type": "text/html; charset=utf-8"}
        )


async def handle_request(request, asgi_app):
    url = urlparse(request.url)
    body = await get_body(request)

    scope = {
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': request.method,
        'path': url.path.rstrip('/') or '/',
        'raw_path': (url.path.rstrip('/') or '/').encode(),
        'query_string': url.query.encode(), 'root_path': '',
        'scheme': url.scheme, 'server': (url.hostname, url.port or 443),
        'client': ('0.0.0.0', 0), 'headers': [],
    }

    for key, value in request.headers.items():
        scope['headers'].append((key.lower().encode(), value.encode()))

    if not any(h[0]==b'host' for h in scope['headers']) and url.hostname:
        scope['headers'].append((b'host', url.hostname.encode()))

    body_sent = False
    resp = {'status': 200, 'headers': {}, 'body': b''}

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        return {'type': 'http.disconnect'}

    async def send(msg):
        if msg['type'] == 'http.response.start':
            resp['status'] = msg['status']
            for k, v in msg.get('headers', []):
                resp['headers'][k.decode()] = v.decode()
        elif msg['type'] == 'http.response.body':
            resp['body'] = msg.get('body', b'')

    await asgi_app(scope, receive, send)

    from js import Response
    return Response.new(resp['body'], status=resp['status'], headers=resp['headers'])


async def get_body(request):
    try:
        if hasattr(request, 'body'): return await request.body()
        if hasattr(request, 'arrayBuffer'):
            buf = await request.arrayBuffer()
            import js
            return bytes(js.Uint8Array.new(buf))
    except: pass
    return b''
