# L丶YOU 的博客

基于 Flask 的个人博客系统，支持 Markdown 编辑、图片上传、深色模式、标签分类、全文搜索、管理员认证。

**两种运行模式：**
- **本地模式**：SQLite + 文件系统，python app.py 直接运行
- **Cloudflare Workers 模式**：D1 数据库 + base64 图片存储，wrangler 部署

## 本地运行

```bash
pip install flask markdown python-dateutil
python app.py
```

访问 http://127.0.0.1:5000
默认管理员：`admin` / `admin123`

## 部署方案

### 方案一：Cloudflare Workers（D1 数据库，功能完整）

> 先决条件：安装 Node.js，然后 `npm install -g wrangler`

**步骤 1：创建 D1 数据库**
```bash
cd blog_project
wrangler d1 create lyou-blog-db
# → 输出类似: Created database 'lyou-blog-db' at id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# 记下这个 database_id
```

**步骤 2：配置 wrangler.toml**
打开 `wrangler.toml`，把 `database_id` 替换为上面输出的 ID：
```toml
[[d1_databases]]
binding = "DB"
database_name = "lyou-blog-db"
database_id = "你的-database-id"   # ← 改成实际 ID
```

**步骤 3：推送到 GitHub 并登录 Cloudflare**
```bash
# 推送代码
git init && git add . && git commit -m "适配 Cloudflare Workers"
git remote add origin https://github.com/你的用户名/blog.git
git push -u origin main

# 登录 Cloudflare
wrangler login
```

**步骤 4：设置 Secrets（敏感信息）**
```bash
# 设置管理员密码
wrangler secret put BLOG_ADMIN_PASS
# 输入: admin123（或你的密码）

# 设置 Session 密钥
wrangler secret put BLOG_SECRET_KEY
# 输入一个随机字符串，如: sk-$(openssl rand -hex 16)
```

**步骤 5：部署**
```bash
wrangler deploy
```
部署成功后，会输出 `https://lyou-blog.你的用户名.workers.dev`

**步骤 6（可选）：绑定自定义域名**
Cloudflare Dashboard → Workers & Pages → lyou-blog → Triggers → Custom Domain → 添加你的域名

### 方案二：Render（一键部署，完全兼容 Flask）

1. 注册 https://render.com （用 GitHub 登录）
2. Dashboard → **New +** → **Web Service**
3. 连接你的 GitHub 仓库
4. 填写：
   - **Name**: `lyou-blog`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
5. 点 **Create Web Service**，等 3 分钟部署完成
6. 免费的域名是 `lyou-blog.onrender.com`

### 方案三：PythonAnywhere（经典 Flask 托管）

1. 注册 https://www.pythonanywhere.com
2. Dashboard → **Web** → **Add a new web app**
3. 选择 Manual Configuration → Python 3.10
4. 在 Console 里 git clone 本仓库
5. 安装依赖：`pip install flask markdown python-dateutil`
6. 在 Web 页面配置 WSGI 文件指向 `app.py`
7. 点击 **Reload**，即可通过 `你的用户名.pythonanywhere.com` 访问

## 配置

管理员密码通过环境变量设置：

```bash
# Windows
set BLOG_ADMIN_PASS=你的密码
set BLOG_ADMIN_USER=admin

# Linux/Mac
export BLOG_ADMIN_PASS=你的密码
export BLOG_ADMIN_USER=admin
```

部署平台（Render / Railway）可在后台 **Environment Variables** 中设置。

## 技术栈

- 后端：Flask (Python)
- 数据库：SQLite（本地） / Cloudflare D1（部署）
- 图片存储：文件系统（本地） / 数据库 base64（部署）
- 前端：原生 HTML/CSS/JS
- 编辑器：Markdown
- 认证：Session + 密码哈希
- 部署：Wrangler CLI
