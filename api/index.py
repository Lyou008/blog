"""
Cloudflare Workers - Python 入口
将 Flask 博客部署到 Cloudflare Workers，使用 D1 数据库和 base64 图片存储。

使用方式：
  1. 配置 wrangler.toml 中的 D1 binding
  2. 运行 wrangler deploy 部署
  
本地开发：
  直接运行 python app.py（使用 SQLite）
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 设置 Workers 环境标记（app.py 会检测这个变量）
os.environ['CLOUDFLARE_WORKERS'] = '1'

# 导入并初始化数据库（传入 D1 binding）
import api.db as database

# 导入 Flask app
import app as blog_app
from asgiref.wsgi import WsgiToAsgi

# 将 Flask 包装为 ASGI
flask_asgi = WsgiToAsgi(blog_app.app)


async def on_fetch(request, env):
    """
    Cloudflare Workers 主入口。
    每次 HTTP 请求到达时，Workers 运行时调用此函数。
    """
    # ── 初始化数据库 ───────────────────────────────────────────
    # 从 Workers env 中获取 D1 binding
    db_binding = env.get('DB', None)
    if db_binding:
        database.init(env_db=db_binding)

    # ── 初始化管理员密码 ───────────────────────────────────────
    # 从环境变量或数据库加载
    os.environ['BLOG_ADMIN_USER'] = env.get('BLOG_ADMIN_USER', 'admin')
    os.environ['BLOG_ADMIN_PASS'] = env.get('BLOG_ADMIN_PASS', 'admin123')
    os.environ['BLOG_SECRET_KEY'] = env.get('BLOG_SECRET_KEY', 'cf-secret-' + uuid_hex())

    # 加载管理员密码
    try:
        blog_app.load_admin_password()
    except Exception:
        # 首次部署可能还没有数据，使用默认密码
        from werkzeug.security import generate_password_hash
        blog_app.ADMIN_PASSWORD_HASH = generate_password_hash('admin123')

    # ── 构建 ASGI scope 并调用 Flask ───────────────────────────
    try:
        return await handle_request(request, flask_asgi)
    except Exception as e:
        # 错误处理：返回 500
        from js import Response
        return Response.new(
            f"<h1>Server Error</h1><pre>{str(e)}</pre>".encode(),
            status=500,
            headers={"Content-Type": "text/html; charset=utf-8"}
        )


async def handle_request(request, asgi_app):
    """将 Workers Request 转换为 ASGI 调用并返回 Response。"""
    from urllib.parse import urlparse

    url = urlparse(request.url)
    body = await get_body(request)

    # ASGI scope
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': request.method,
        'path': url.path.rstrip('/') or '/',
        'raw_path': (url.path.rstrip('/') or '/').encode(),
        'query_string': url.query.encode(),
        'root_path': '',
        'scheme': url.scheme,
        'server': (url.hostname, url.port or 443),
        'client': ('0.0.0.0', 0),
        'headers': [],
    }

    # 请求头
    has_content_type = False
    for key, value in request.headers.items():
        k = key.lower()
        scope['headers'].append((k.encode(), value.encode()))
        if k == 'content-type':
            has_content_type = True

    # 确保有 Content-Type
    if not has_content_type and body:
        scope['headers'].append((b'content-type', b'application/octet-stream'))

    # 确保有 Host
    if not any(h[0] == b'host' for h in scope['headers']) and url.hostname:
        scope['headers'].append((b'host', url.hostname.encode()))

    # ASGI receive/send
    body_sent = False
    response_data = {'status': 200, 'headers': {}, 'body': b''}

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        return {'type': 'http.disconnect'}

    async def send(message):
        if message['type'] == 'http.response.start':
            response_data['status'] = message['status']
            for k, v in message.get('headers', []):
                response_data['headers'][k.decode()] = v.decode()
        elif message['type'] == 'http.response.body':
            response_data['body'] = message.get('body', b'')

    await asgi_app(scope, receive, send)

    # 返回 Workers Response
    from js import Response
    return Response.new(
        response_data['body'],
        status=response_data['status'],
        headers=response_data['headers']
    )


async def get_body(request):
    """读取请求体。"""
    try:
        if hasattr(request, 'body'):
            return await request.body()
        if hasattr(request, 'arrayBuffer'):
            buf = await request.arrayBuffer()
            import js
            return bytes(js.Uint8Array.new(buf))
    except Exception:
        pass
    return b''


def uuid_hex():
    """生成不带连字符的 UUID hex（依赖纯 Python uuid 模块）。"""
    import uuid
    return uuid.uuid4().hex
