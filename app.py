#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Personal Blog - Flask Application
支持 PostgreSQL 和 SQLite 自动切换
专为 Render 部署优化
"""

import os
import sys
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   send_from_directory, jsonify, abort, flash, session)
import markdown as md_lib
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ── 数据库配置 ──────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

# 检测数据库类型
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRESQL = DATABASE_URL and DATABASE_URL.startswith('postgres')

if USE_POSTGRESQL:
    try:
        import psycopg2
        import psycopg2.extras
        print("📦 使用 PostgreSQL 数据库")
    except ImportError:
        print("❌ 未安装 psycopg2-binary，请添加到 requirements.txt")
        sys.exit(1)
else:
    print("📦 使用 SQLite 数据库")


# ── App 配置 ──────────────────────────────────────────────
# 安全配置：生产环境必须设置 SECRET_KEY
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    secret_key = 'dev-only-key-do-not-use-in-production'
    print("⚠️  警告：使用开发密钥")
app.secret_key = secret_key

app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
app.config['POSTS_PER_PAGE'] = 10

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# ── 数据库连接 ──────────────────────────────────────────────
def get_db_connection():
    """获取数据库连接（自动选择 SQLite 或 PostgreSQL）"""
    if USE_POSTGRESQL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
        return conn
    else:
        db_path = os.path.join(BASE_DIR, 'blog.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def execute_sql(sql, params=None):
    """执行 SQL 并返回 cursor（自动关闭连接）"""
    # 转换 SQL 语法：SQLite -> PostgreSQL 或反之
    if USE_POSTGRESQL:
        sql = sql.replace('?', '%s')
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        conn.commit()
        return cur
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def fetch_all(sql, params=None):
    """查询所有行"""
    if USE_POSTGRESQL:
        sql = sql.replace('?', '%s')
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_one(sql, params=None):
    """查询单行"""
    if USE_POSTGRESQL:
        sql = sql.replace('?', '%s')
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── 管理员配置 ──────────────────────────────────────────────
ADMIN_USERNAME = os.environ.get('BLOG_ADMIN_USER', 'admin')
ADMIN_PASSWORD_HASH = None


# ── 初始化数据库 ──────────────────────────────────────────────
def init_db():
    """初始化数据库表（支持 SQLite 和 PostgreSQL）"""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        if USE_POSTGRESQL:
            # PostgreSQL 语法
            cur.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_draft BOOLEAN DEFAULT FALSE,
                    allow_comments BOOLEAN DEFAULT TRUE
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS tags (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS post_tags (
                    post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (post_id, tag_id)
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS comments (
                    id SERIAL PRIMARY KEY,
                    post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                    author TEXT NOT NULL,
                    email TEXT,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_approved BOOLEAN DEFAULT FALSE
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL
                )
            ''')
        else:
            # SQLite 语法
            cur.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_draft BOOLEAN DEFAULT 0,
                    allow_comments BOOLEAN DEFAULT 1
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS post_tags (
                    post_id INTEGER REFERENCES posts(id),
                    tag_id INTEGER REFERENCES tags(id),
                    PRIMARY KEY (post_id, tag_id)
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER REFERENCES posts(id),
                    author TEXT NOT NULL,
                    email TEXT,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_approved BOOLEAN DEFAULT 0
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL
                )
            ''')
        
        conn.commit()
        print("✅ 数据库初始化完成")
    except Exception as e:
        conn.rollback()
        print(f"❌ 数据库初始化失败：{e}")
        raise
    finally:
        conn.close()


# ── 辅助函数 ──────────────────────────────────────────────
def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def render_markdown(text):
    """渲染 Markdown 为 HTML"""
    return md_lib.markdown(text, extensions=['extra', 'codehilite', 'toc'])


# ── 路由 ──────────────────────────────────────────────────
@app.route('/')
def index():
    """首页：显示所有已发布的文章"""
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * app.config['POSTS_PER_PAGE']
    
    posts = fetch_all('''
        SELECT * FROM posts 
        WHERE is_draft = 0 
        ORDER BY created_at DESC 
        LIMIT ? OFFSET ?
    ''', (app.config['POSTS_PER_PAGE'], offset))
    
    # 获取每篇文章的标签
    for post in posts:
        post['tags'] = fetch_all('''
            SELECT tags.name FROM tags 
            JOIN post_tags ON tags.id = post_tags.tag_id 
            WHERE post_tags.post_id = ?
        ''', (post['id'],))
    
    total_posts = fetch_one('SELECT COUNT(*) as count FROM posts WHERE is_draft = 0')
    total_pages = (total_posts['count'] + app.config['POSTS_PER_PAGE'] - 1) // app.config['POSTS_PER_PAGE']
    
    return render_template('index.html', posts=posts, page=page, total_pages=total_pages)


@app.route('/post/<int:post_id>')
def view_post(post_id):
    """查看单篇文章"""
    post = fetch_one('SELECT * FROM posts WHERE id = ?', (post_id,))
    if not post:
        abort(404)
    
    post['html_content'] = render_markdown(post['content'])
    post['tags'] = fetch_all('''
        SELECT tags.name FROM tags 
        JOIN post_tags ON tags.id = post_tags.tag_id 
        WHERE post_tags.post_id = ?
    ''', (post_id,))
    
    comments = fetch_all('''
        SELECT * FROM comments 
        WHERE post_id = ? AND is_approved = 1 
        ORDER BY created_at ASC
    ''', (post_id,))
    
    return render_template('post.html', post=post, comments=comments)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录"""
    global ADMIN_PASSWORD_HASH
    
    # 如果还没有设置密码，使用默认密码
    if ADMIN_PASSWORD_HASH is None:
        ADMIN_PASSWORD_HASH = generate_password_hash('admin123')
        # 创建默认用户
        try:
            execute_sql('''
                INSERT INTO users (username, password_hash) 
                VALUES (?, ?)
            ''', (ADMIN_USERNAME, ADMIN_PASSWORD_HASH))
        except:
            pass  # 用户可能已存在
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = fetch_one('SELECT * FROM users WHERE username = ?', (username,))
        
        if user and check_password_hash(user['password_hash'], password):
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('admin'))
        else:
            flash('用户名或密码错误')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    """登出"""
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('index'))


@app.route('/admin')
@login_required
def admin():
    """管理后台"""
    posts = fetch_all('SELECT * FROM posts ORDER BY created_at DESC')
    return render_template('admin.html', posts=posts)


@app.route('/admin/new', methods=['GET', 'POST'])
@login_required
def new_post():
    """新建文章"""
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        is_draft = 1 if request.form.get('is_draft') else 0
        allow_comments = 1 if request.form.get('allow_comments', '1') else 0
        
        tags = request.form.get('tags', '').split(',')
        tags = [t.strip() for t in tags if t.strip()]
        
        # 创建文章
        cur = execute_sql('''
            INSERT INTO posts (title, content, is_draft, allow_comments)
            VALUES (?, ?, ?, ?)
        ''', (title, content, is_draft, allow_comments))
        
        # 获取新文章 ID
        if USE_POSTGRESQL:
            post_id = cur.fetchone()[0]
        else:
            post_id = cur.lastrowid
        
        # 处理标签
        for tag_name in tags:
            # 查找或创建标签
            existing = fetch_one('SELECT * FROM tags WHERE name = ?', (tag_name,))
            if existing:
                tag_id = existing['id']
            else:
                cur = execute_sql('INSERT INTO tags (name) VALUES (?)', (tag_name,))
                if USE_POSTGRESQL:
                    tag_id = cur.fetchone()[0]
                else:
                    tag_id = cur.lastrowid
            
            # 关联文章和标签
            try:
                execute_sql('''
                    INSERT INTO post_tags (post_id, tag_id) VALUES (?, ?)
                ''', (post_id, tag_id))
            except:
                pass  # 可能已存在
        
        flash('文章发布成功！')
        return redirect(url_for('admin'))
    
    return render_template('edit_post.html', post=None)


@app.route('/admin/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    """编辑文章"""
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        is_draft = 1 if request.form.get('is_draft') else 0
        allow_comments = 1 if request.form.get('allow_comments', '1') else 0
        
        # 更新文章
        execute_sql('''
            UPDATE posts 
            SET title = ?, content = ?, is_draft = ?, allow_comments = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (title, content, is_draft, allow_comments, post_id))
        
        flash('文章更新成功！')
        return redirect(url_for('admin'))
    
    post = fetch_one('SELECT * FROM posts WHERE id = ?', (post_id,))
    if not post:
        abort(404)
    
    return render_template('edit_post.html', post=post)


@app.route('/admin/delete/<int:post_id>')
@login_required
def delete_post(post_id):
    """删除文章"""
    execute_sql('DELETE FROM posts WHERE id = ?', (post_id,))
    flash('文章已删除！')
    return redirect(url_for('admin'))


@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """上传文件"""
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        return jsonify({'url': url_for('static', filename=f'uploads/{filename}')})
    
    return jsonify({'error': '文件类型不支持'}), 400


@app.route('/api/posts')
def api_posts():
    """API：获取文章列表"""
    posts = fetch_all('''
        SELECT id, title, created_at FROM posts 
        WHERE is_draft = 0 
        ORDER BY created_at DESC
    ''')
    return jsonify(posts)


# ── 主程序 ──────────────────────────────────────────────────
# 应用启动时自动初始化数据库（Gunicorn 和 python 都执行）
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print(f"⚠️  数据库初始化警告：{e}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
