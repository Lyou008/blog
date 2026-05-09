#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Personal Blog - Flask Application
支持两种运行模式：
  1. 本地模式：使用 SQLite + 文件系统
  2. Cloudflare Workers 模式：使用 D1 + R2/base64

通过 api/db 模块统一数据库操作，自动适配运行环境。
"""
import os
import uuid
import base64
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   send_from_directory, jsonify, abort, flash, session)
import markdown as md_lib
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ── 环境检测 ──────────────────────────────────────────────────
IS_WORKERS = os.environ.get('CLOUDFLARE_WORKERS', '0') == '1'

# ── 导入数据库层 ──────────────────────────────────────────────
# Workers 模式下 app.py 在 api/index.py 的 sys.path 下被导入
# 本地模式下直接 import
try:
    import api.db as database
except ImportError:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'api'))
    import db as database

# ── App Configuration ──────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

if IS_WORKERS:
    app.secret_key = os.environ.get('BLOG_SECRET_KEY', 'cf-worker-secret-key')
else:
    app.secret_key = 'local-dev-secret-key-blog-2024'

app.config['DATABASE'] = os.path.join(BASE_DIR, 'blog.db')
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
app.config['POSTS_PER_PAGE'] = 10
app.config['SESSION_COOKIE_NAME'] = 'blog_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

if not IS_WORKERS:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ── 管理员配置 ──────────────────────────────────────────────────
ADMIN_USERNAME = os.environ.get('BLOG_ADMIN_USER', 'admin')
ADMIN_PASSWORD_HASH = None  # 在 startup 时从 DB 加载


# ── 辅助函数 ──────────────────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def render_markdown(text):
    extensions = ['extra', 'codehilite', 'fenced_code', 'toc', 'sane_lists']
    return md_lib.markdown(text, extensions=extensions)


def make_slug(title):
    import re
    slug = title.lower().strip()
    slug = re.sub(r'[^\w\s\u4e00-\u9fff-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    if not slug:
        slug = f'post-{uuid.uuid4().hex[:8]}'
    return slug


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
    return {
        'logged_in': session.get('logged_in', False),
        'admin_username': session.get('username', '')
    }


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
        if (username == ADMIN_USERNAME and
                check_password_hash(ADMIN_PASSWORD_HASH, password)):
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
        database.set_setting('admin_password_hash', ADMIN_PASSWORD_HASH)
        flash('密码修改成功！', 'success')
        return redirect(url_for('admin'))
    return render_template('change_password.html')


# ── 首页 ──────────────────────────────────────────────────────

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    tag = request.args.get('tag', '').strip()

    posts, total = database.get_posts(page, app.config['POSTS_PER_PAGE'], search, tag)

    # 为每篇文章获取标签
    for p in posts:
        p['tags'] = database.get_post_tags(p['id'])

    total_pages = max(1, (total + app.config['POSTS_PER_PAGE'] - 1) // app.config['POSTS_PER_PAGE'])
    all_tags = database.get_all_tags()
    stats = database.get_stats()
    recent = database.get_recent_posts(5)

    return render_template('index.html',
                           posts=posts, page=page, total_pages=total_pages,
                           search=search, tag=tag, tags=all_tags,
                           stats=stats, recent_posts=recent)


# ── 文章详情 ──────────────────────────────────────────────────

@app.route('/post/<int:post_id>')
def view_post(post_id):
    post = database.get_post(post_id)
    if not post:
        abort(404)

    database.increment_views(post_id)
    tags = database.get_post_tags(post_id)
    prev_post, next_post = database.get_adjacent_posts(post['created_at'])
    content_html = render_markdown(post['content'])
    stats = database.get_stats()
    recent = database.get_recent_posts(5)

    # 处理图片显示：如果图片存在且属于 Workers 模式（image 字段存的是 image_id）
    featured_image_url = None
    if post.get('image'):
        if IS_WORKERS:
            featured_image_url = url_for('serve_image', image_id=post['image'])
        else:
            featured_image_url = url_for('uploaded_file', filename=post['image'])

    return render_template('post.html',
                           post=post, content_html=content_html,
                           tags=tags, prev_post=prev_post, next_post=next_post,
                           stats=stats, recent_posts=recent,
                           featured_image_url=featured_image_url)


# ── 图片服务（Workers 模式：从 DB 中读取 base64 图片）────────

@app.route('/image/<image_id>')
def serve_image(image_id):
    """Workers 模式：从数据库返回图片。"""
    img = database.get_image(image_id)
    if not img:
        abort(404)
    data = base64.b64decode(img['data'])
    from flask import Response
    return Response(data, mimetype=img.get('mime_type', 'image/png'))


# ── 管理后台 / CRUD ──────────────────────────────────────────

@app.route('/admin')
@login_required
def admin():
    posts = database.get_all_posts_admin()
    stats = database.get_stats()
    return render_template('admin.html', posts=posts, stats=stats)


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

        # 图片处理
        image_id_or_filename = _handle_image_upload(request)

        slug = make_slug(title)
        post_id = database.create_post(
            title, slug, content, summary,
            image=image_id_or_filename or '',
            tags_str=tags_raw
        )

        flash('文章发布成功！', 'success')
        return redirect(url_for('view_post', post_id=post_id))

    return render_template('edit.html', post=None, mode='create',
                           stats=database.get_stats())


@app.route('/edit/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = database.get_post(post_id)
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

        # 图片处理
        new_image = _handle_image_upload(request)
        if new_image:
            # 上传了新图片
            image = new_image
        elif delete_image:
            image = ''
        else:
            image = None  # 不修改

        database.update_post(post_id, title, content, summary,
                             image=image, tags_str=tags_raw,
                             delete_image=(delete_image and image is None))

        flash('文章更新成功！', 'success')
        return redirect(url_for('view_post', post_id=post_id))

    tags_str = ', '.join(database.get_post_tags(post_id))

    # 构建图片 URL（模板用）
    image_url = None
    if post.get('image'):
        if IS_WORKERS:
            image_url = url_for('serve_image', image_id=post['image'])
        else:
            image_url = url_for('uploaded_file', filename=post['image'])

    return render_template('edit.html', post=post, mode='edit',
                           tags_str=tags_str, stats=database.get_stats(),
                           image_url=image_url)


@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = database.delete_post(post_id)
    if not post:
        abort(404)

    # 清理图片文件（本地模式）
    if not IS_WORKERS and post.get('image'):
        img_path = os.path.join(app.config['UPLOAD_FOLDER'], post['image'])
        if os.path.exists(img_path):
            os.remove(img_path)

    flash('文章已删除', 'success')
    return redirect(url_for('admin'))


def _handle_image_upload(request):
    """
    处理图片上传：
    - 本地模式：保存到文件系统，返回文件名
    - Workers 模式：保存到 DB（base64），返回 image_id
    """
    if 'image' not in request.files:
        return None
    file = request.files['image']
    if not file or not file.filename or not allowed_file(file.filename):
        return None

    if IS_WORKERS:
        # Workers 模式：base64 存入 images 表
        file_data = file.read()
        b64_data = base64.b64encode(file_data).decode('utf-8')
        mime = file.content_type or 'image/png'
        image_id = uuid.uuid4().hex
        database.save_image(image_id, b64_data, mime, file.filename)
        return image_id
    else:
        # 本地模式：存入文件系统
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return filename


# ── 图片上传 API（编辑器用） ─────────────────────────────────

@app.route('/upload-image', methods=['POST'])
@login_required
def upload_image_editor():
    """编辑器内嵌图片上传。"""
    if 'file' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400

    file = request.files['file']
    if not file or not file.filename or not allowed_file(file.filename):
        return jsonify({'error': '不支持的文件格式'}), 400

    if IS_WORKERS:
        file_data = file.read()
        b64_data = base64.b64encode(file_data).decode('utf-8')
        mime = file.content_type or 'image/png'
        image_id = uuid.uuid4().hex
        database.save_image(image_id, b64_data, mime, file.filename)
        return jsonify({
            'url': url_for('serve_image', image_id=image_id),
            'filename': file.filename
        })
    else:
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({
            'url': url_for('uploaded_file', filename=filename),
            'filename': filename
        })


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """本地模式：提供上传文件。"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ── API ────────────────────────────────────────────────────────

@app.route('/api/posts')
def api_posts():
    posts = database.get_all_posts_admin()
    return jsonify(posts)


@app.route('/api/stats')
def api_stats():
    return jsonify(database.get_stats())


# ── 404 ────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404


# ── 启动 ──────────────────────────────────────────────────────

def load_admin_password():
    """从数据库加载或初始化管理员密码。"""
    global ADMIN_PASSWORD_HASH
    hashed = database.get_setting('admin_password_hash')
    if hashed:
        ADMIN_PASSWORD_HASH = hashed
    else:
        default_pass = os.environ.get('BLOG_ADMIN_PASS', 'admin123')
        ADMIN_PASSWORD_HASH = generate_password_hash(default_pass)
        database.set_setting('admin_password_hash', ADMIN_PASSWORD_HASH)


if __name__ == '__main__':
    if not IS_WORKERS:
        database.init(db_path=app.config['DATABASE'])
        load_admin_password()
        print("✅ Blog is running at http://127.0.0.1:5000")
        app.run(debug=True, host='0.0.0.0', port=5000)
