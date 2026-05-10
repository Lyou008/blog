#!/usr/bin/env python3
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

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'blog-secret-key')
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
app.config['POSTS_PER_PAGE'] = 10

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ADMIN_USERNAME = os.environ.get('BLOG_ADMIN_USER', 'admin')
ADMIN_PASSWORD_HASH = None

def get_db():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("DATABASE_URL not set!")
    for i in range(10):
        try:
            conn = psycopg2.connect(db_url, sslmode='require')
            return conn
        except Exception as e:
            if i == 9:
                raise
            time.sleep(2)

def execute(sql, params=None):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    conn.commit()
    return cur

def fetch_all(sql, params=None):
    cur = execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]

def fetch_one(sql, params=None):
    cur = execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None

def fetch_val(sql, params=None):
    cur = execute(sql, params)
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return list(row.values())[0]

print("Syntax check passed!")
