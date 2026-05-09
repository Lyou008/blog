#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Personal Blog - Flask Application
PostgreSQL 版本，使用 Render 提供的免费 PostgreSQL 数据库。
"""
import os
import uuid
import re
import time
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   send_from_directory, jsonify, abort, flash, session)
import markdown as md_lib
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

# ── App 配置 ──────────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'blog-secret-key-2024-love-you')
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
app.config['POSTS_PER_PAGE'] = 10
app.config['SESSION_COOKIE_NAME'] = 'blog_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ── 管理员 ────────────────────────────────────────────────────
ADMIN_USERNAME = os.environ.get('BLOG_ADMIN_USER', 'admin')
ADMIN_PASSWORD_HASH = None


# ── 数据库连接 ────────────────────────────────────────────────

def get_db():
    """获取 PostgreSQL 数据库连接（带重试）。"""
    db_url = os.environ['DATABASE_URL']
    # Render 的 PostgreSQL 可能需要几秒才能就绪
    for i in range(10):
        try:
            conn = psycopg2.connect(db_url, sslmode='require')
            return conn
        except Exception as e:
            if i == 9:
                raise
            time.sleep(2)  # 等待 2 秒后重试


def execute(sql, params=None):
    """执行 SQL 并返回 cursor（自动提交）。"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    conn.commit()
    return cur


def fetch_all(sql, params=None):
    """查询所有行。"""
    cur = execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def fetch_one(sql, params=None):
    """查询单行。"""
    cur = execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def fetch_val(sql, params=None):
    """查询单个值。"""
    cur = execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row[0] if row else None


def init_db():
    """创建数据库表。"""
    execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            summary TEXT DEFAULT '',
            image TEXT DEFAULT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            views INTEGER DEFAULT 0
        );
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS post_tags (
            post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (post_id, tag_id)
        );
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    execute("CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);")
    execute("CREATE INDEX IF NOT EXISTS idx_posts_slug ON posts(slug);")


# ── 设置工具 ──────────────────────────────────────────────────

def get_setting(key, default=None):
    row = fetch_one('SELECT value FROM settings WHERE key=%s', (key,))
    return row['value'] if row else default


def set_setting(key, value):
    execute('INSERT INTO settings (key, value) VALUES (%s, %s) '
            'ON CONFLICT (key) DO UPDATE SET value=%s',
            (key, value, value))


# ── 辅助函数 ──────────────────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def render_markdown(text):
    return md_lib.markdown(text, extensions=['extra', 'codehilite', 'fenced_code', 'toc', 'sane_lists'])


def make_slug(title):
    slug = title.lower().strip()
    slug = re.sub(r'[^\w\s\u4e00-\u9fff-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    if not slug:
        slug = f'post-{uuid.uuid4().hex[:8]}'
    return slug


def process_tags(post_id, tags_raw):
    if not tags_raw:
        return
    for name in [t.strip() for t in tags_raw.split(',') if t.strip()]:
        tag = fetch_one('SELECT id FROM tags WHERE name=%s', (name,))
        if tag:
            tag_id = tag['id']
        else:
            execute('INSERT INTO tags (name) VALUES (%s)', (name,))
            tag_id = fetch_val('SELECT MAX(id) FROM tags')
        execute('INSERT INTO post_tags (post_id, tag_id) VALUES (%s, %s) '
                'ON CONFLICT DO NOTHING', (post_id, tag_id))


def get_post_tags(post_id):
    rows = fetch_all(
        'SELECT t.name FROM tags t JOIN post_tags pt ON t.id=pt.tag_id WHERE pt.post_id=%s',
        (post_id,)
    )
    return [r['name'] for r in rows]


def get_stats():
    total_posts = fetch_val('SELECT COUNT(*) FROM posts')
    total_views = fetch_val('SELECT COALESCE(SUM(views), 0) FROM posts')
    total_tags = fetch_val('SELECT COUNT(*) FROM tags')
    last = fetch_one('SELECT updated_at FROM posts ORDER BY updated_at DESC LIMIT 1')
    return {
        'total_posts': total_posts,
        'total_views': total_views,
        'total_tags': total_tags,
        'last_updated': last['updated_at'] if last else None,
    }


def get_recent_posts(limit=5):
    return fetch_all(
        'SELECT id, title, created_at FROM posts ORDER BY created_at DESC LIMIT %s',
        (limit,)
    )


# ── 认证 ──────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('请先登录后再执行此操作', 'error')
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function


@app.context_processor
def inject_auth():
    return {'logged_in': session.get('logged_in', False), 'admin_username': session.get('username', '')}


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('admin'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('请输入用户名和密码', 'error')
            return render_template('login.html')
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['logged_in'] = True
            session['username'] = username
            flash('登录成功，欢迎回来！', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('admin'))
        else:
            flash('用户名或密码错误', 'error')
            return render_template('login.html')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('已成功退出登录', 'success')
    return redirect(url_for('index'))


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    global ADMIN_PASSWORD_HASH
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not check_password_hash(ADMIN_PASSWORD_HASH, current):
            flash('当前密码错误', 'error')
            return render_template('change_password.html')
        if len(new_pw) < 6:
            flash('新密码至少需要 6 个字符', 'error')
            return render_template('change_password.html')
        if new_pw != confirm:
            flash('两次输入的新密码不一致', 'error')
            return render_template('change_password.html')
        ADMIN_PASSWORD_HASH = generate_password_hash(new_pw)
        set_setting('admin_password_hash', ADMIN_PASSWORD_HASH)
        flash('密码修改成功！', 'success')
        return redirect(url_for('admin'))
    return render_template('change_password.html')


# ── 首页 ──────────────────────────────────────────────────────

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    tag = request.args.get('tag', '').strip()
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page

    if search:
        like = f'%{search}%'
        total = fetch_val(
            'SELECT COUNT(*) FROM posts WHERE title ILIKE %s OR content ILIKE %s OR summary ILIKE %s',
            (like, like, like)
        )
        posts = fetch_all(
            'SELECT * FROM posts WHERE title ILIKE %s OR content ILIKE %s OR summary ILIKE %s '
            'ORDER BY created_at DESC LIMIT %s OFFSET %s',
            (like, like, like, per_page, offset)
        )
    elif tag:
        total = fetch_val(
            'SELECT COUNT(*) FROM posts p JOIN post_tags pt ON p.id=pt.post_id '
            'JOIN tags t ON t.id=pt.tag_id WHERE t.name=%s', (tag,)
        )
        posts = fetch_all(
            'SELECT p.* FROM posts p JOIN post_tags pt ON p.id=pt.post_id '
            'JOIN tags t ON t.id=pt.tag_id WHERE t.name=%s '
            'ORDER BY p.created_at DESC LIMIT %s OFFSET %s',
            (tag, per_page, offset)
        )
    else:
        total = fetch_val('SELECT COUNT(*) FROM posts')
        posts = fetch_all(
            'SELECT * FROM posts ORDER BY created_at DESC LIMIT %s OFFSET %s',
            (per_page, offset)
        )

    for p in posts:
        p['tags'] = get_post_tags(p['id'])

    all_tags = fetch_all('SELECT * FROM tags ORDER BY name')
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template('index.html', posts=posts, page=page,
                           total_pages=total_pages, search=search, tag=tag,
                           tags=all_tags, stats=get_stats(),
                           recent_posts=get_recent_posts())


# ── 文章详情 ──────────────────────────────────────────────────

@app.route('/post/<int:post_id>')
def view_post(post_id):
    post = fetch_one('SELECT * FROM posts WHERE id=%s', (post_id,))
    if not post:
        abort(404)

    execute('UPDATE posts SET views = views + 1 WHERE id=%s', (post_id,))

    tags = get_post_tags(post_id)
    prev_post = fetch_one(
        'SELECT id, title FROM posts WHERE created_at < %s ORDER BY created_at DESC LIMIT 1',
        (post['created_at'],)
    )
    next_post = fetch_one(
        'SELECT id, title FROM posts WHERE created_at > %s ORDER BY created_at ASC LIMIT 1',
        (post['created_at'],)
    )

    return render_template('post.html', post=post,
                           content_html=render_markdown(post['content']),
                           tags=tags, prev_post=prev_post, next_post=next_post,
                           stats=get_stats(), recent_posts=get_recent_posts())


# ── 管理后台 ──────────────────────────────────────────────────

@app.route('/admin')
@login_required
def admin():
    posts = fetch_all(
        'SELECT id, title, slug, created_at, updated_at, views FROM posts ORDER BY created_at DESC'
    )
    return render_template('admin.html', posts=posts, stats=get_stats())


@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        summary = request.form.get('summary', '').strip()
        tags_raw = request.form.get('tags', '').strip()

        if not title:
            flash('标题不能为空', 'error')
            return render_template('edit.html', post=None, mode='create')
        if not content:
            flash('内容不能为空', 'error')
            return render_template('edit.html', post=None, mode='create')

        image = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                image = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image))

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        slug = make_slug(title)

        existing = fetch_one('SELECT id FROM posts WHERE slug=%s', (slug,))
        if existing:
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        cur = execute(
            'INSERT INTO posts (title, slug, content, summary, image, created_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id',
            (title, slug, content, summary, image, now, now)
        )
        post_id = cur.fetchone()[0]
        cur.close()

        process_tags(post_id, tags_raw)

        flash('文章发布成功！', 'success')
        return redirect(url_for('view_post', post_id=post_id))

    return render_template('edit.html', post=None, mode='create', stats=get_stats())


@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = fetch_one('SELECT * FROM posts WHERE id=%s', (post_id,))
    if not post:
        abort(404)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        summary = request.form.get('summary', '').strip()
        tags_raw = request.form.get('tags', '').strip()
        delete_image = request.form.get('delete_image', '') == 'on'

        if not title:
            flash('标题不能为空', 'error')
            return render_template('edit.html', post=post, mode='edit')
        if not content:
            flash('内容不能为空', 'error')
            return render_template('edit.html', post=post, mode='edit')

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        image = post['image']

        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                if image:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], image)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                ext = file.filename.rsplit('.', 1)[1].lower()
                image = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image))

        if delete_image and image:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], image)
            if os.path.exists(old_path):
                os.remove(old_path)
            image = None

        execute(
            'UPDATE posts SET title=%s, content=%s, summary=%s, image=%s, updated_at=%s WHERE id=%s',
            (title, content, summary, image, now, post_id)
        )
        execute('DELETE FROM post_tags WHERE post_id=%s', (post_id,))
        process_tags(post_id, tags_raw)

        flash('文章更新成功！', 'success')
        return redirect(url_for('view_post', post_id=post_id))

    tags_str = ', '.join(get_post_tags(post_id))
    return render_template('edit.html', post=post, mode='edit',
                           tags_str=tags_str, stats=get_stats())


@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = fetch_one('SELECT * FROM posts WHERE id=%s', (post_id,))
    if not post:
        abort(404)

    if post['image']:
        img_path = os.path.join(app.config['UPLOAD_FOLDER'], post['image'])
        if os.path.exists(img_path):
            os.remove(img_path)

    execute('DELETE FROM posts WHERE id=%s', (post_id,))

    flash('文章已删除', 'success')
    return redirect(url_for('admin'))


# ── 图片上传 API ──────────────────────────────────────────────

@app.route('/upload-image', methods=['POST'])
@login_required
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400
    file = request.files['file']
    if not file or not file.filename or not allowed_file(file.filename):
        return jsonify({'error': '不支持的文件格式'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return jsonify({'url': url_for('uploaded_file', filename=filename), 'filename': filename})


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ── API ──────────────────────────────────────────────────────

@app.route('/api/posts')
def api_posts():
    posts = fetch_all(
        'SELECT id, title, slug, summary, created_at, views FROM posts ORDER BY created_at DESC'
    )
    return jsonify(posts)


@app.route('/api/stats')
def api_stats():
    return jsonify(get_stats())


# ── 404 ──────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


# ── 启动 ──────────────────────────────────────────────────────

def load_admin_password():
    global ADMIN_PASSWORD_HASH
    hashed = get_setting('admin_password_hash')
    if hashed:
        ADMIN_PASSWORD_HASH = hashed
    else:
        default_pass = os.environ.get('BLOG_ADMIN_PASS', 'admin123')
        ADMIN_PASSWORD_HASH = generate_password_hash(default_pass)
        set_setting('admin_password_hash', ADMIN_PASSWORD_HASH)


# ── 数据库初始化标志 ────────────────────────────────────────
_db_initialized = False


def ensure_db():
    """延迟初始化数据库（第一次请求时调用）。"""
    global _db_initialized
    if _db_initialized:
        return
    init_db()
    load_admin_password()
    _db_initialized = True


@app.before_request
def _ensure_db():
    """每个请求前确保数据库已初始化。"""
    ensure_db()
    ensure_db()


if __name__ == '__main__':
    print("✅ Blog is running at http://127.0.0.1:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
