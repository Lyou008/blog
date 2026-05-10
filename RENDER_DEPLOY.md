# Render 部署指南

## 🚀 一键部署到 Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

## 📋 部署步骤

### 1. 推送到 GitHub

```bash
# 添加所有文件
git add .

# 提交更改
git commit -m "feat: 支持 PostgreSQL 和 SQLite 自动切换，准备部署到 Render"

# 推送到 GitHub
git push origin main
```

### 2. 在 Render 上部署

#### 方法 A：使用 Blueprint（推荐）

1. 登录 [Render Dashboard](https://dashboard.render.com)
2. 点击 **New +** → **Blueprint**
3. 连接你的 GitHub 仓库
4. Render 会自动检测 `render.yaml` 并创建：
   - Web Service（Flask 应用）
   - PostgreSQL 数据库
5. 点击 **Apply Blueprint** 开始部署

#### 方法 B：手动创建

1. 在 Render Dashboard 点击 **New +** → **Web Service**
2. 连接 GitHub 仓库：`your-username/flask-blog`
3. 配置：
   - **Name**: `flask-blog`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
4. 添加环境变量：
   - `FLASK_ENV`: `production`
   - `SECRET_KEY`: 点击 **Generate** 自动生成
   - `PYTHON_VERSION`: `3.11.0`
5. 创建 PostgreSQL 数据库：
   - 点击 **New +** → **PostgreSQL**
   - 创建后，将 **Internal Database URL** 复制到 Web Service 的环境变量 `DATABASE_URL`
6. 点击 **Create Web Service**

### 3. 初始化管理员账户

部署成功后：

1. 访问 `https://your-app.onrender.com/login`
2. 使用默认账户登录：
   - 用户名：`admin`
   - 密码：`admin123`
3. **⚠️ 重要**：登录后立即修改密码！

```python
# 在 Python shell 中修改密码
import os
os.environ['DATABASE_URL'] = 'your-postgres-url'
from app import app, generate_password_hash, execute_sql

# 修改密码
new_hash = generate_password_hash('your-new-password')
execute_sql('UPDATE users SET password_hash = ? WHERE username = ?', 
            (new_hash, 'admin'))
```

或者在 Render Shell 中执行：

```bash
# 打开 Render Shell
python3 -c "
import os;
os.environ['DATABASE_URL'] = '$(echo $DATABASE_URL)';
from app import app, generate_password_hash, execute_sql;
execute_sql('UPDATE users SET password_hash = ? WHERE username = ?', 
            (generate_password_hash('new-password-here'), 'admin'));
print('密码已更新');
"
```

## 🔧 环境变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接 URL | 无（使用 SQLite） |
| `SECRET_KEY` | Flask 密钥（**必须设置**） | 开发模式自动生成 |
| `FLASK_ENV` | Flask 环境 | `production` |
| `BLOG_ADMIN_USER` | 管理员用户名 | `admin` |

## 📦 数据库说明

### 自动检测机制

应用会自动检测 `DATABASE_URL` 环境变量：

- **有 `DATABASE_URL` 且以 `postgres` 开头** → 使用 PostgreSQL
- **否则** → 使用 SQLite（`blog.db`）

### 本地开发

```bash
# 使用 SQLite（默认）
python app.py

# 使用 PostgreSQL（需要本地安装）
export DATABASE_URL="postgresql://user:pass@localhost/blog"
python app.py
```

### Render 部署

Render 会自动设置 `DATABASE_URL` 指向你的 PostgreSQL 数据库。

## 🐛 故障排除

### 1. 应用无法启动

检查日志：

```bash
# Render Dashboard → 你的服务 → Logs
```

常见问题：

- `SECRET_KEY` 未设置 → 在环境变量中设置
- `psycopg2` 安装失败 → 确保 `requirements.txt` 包含 `psycopg2-binary`
- `DATABASE_URL` 格式错误 → 应该是 `postgresql://...`

### 2. 数据库迁移

从 SQLite 迁移到 PostgreSQL：

```bash
# 导出 SQLite 数据
sqlite3 blog.db .dump > backup.sql

# 导入到 PostgreSQL（需要转换 SQL 语法）
# 建议使用 pgloader 或手动转换
```

### 3. 静态文件不显示

确保 `static/` 目录在 Git 中：

```bash
git add static/
git commit -m "Add static files"
git push
```

## 📊 性能优化

### 使用 Persistent Disk（可选）

如果需要持久化存储上传的文件：

1. 在 Render Dashboard 创建 **Persistent Disk**
2. 挂载到 `/var/data`
3. 修改 `app.py`：

```python
app.config['UPLOAD_FOLDER'] = '/var/data/uploads'
```

### 启用 CDN（推荐）

使用 Cloudinary 或 AWS S3 存储上传的图片：

```python
# 安装 cloudinary
pip install cloudinary

# 配置
import cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
)
```

## 🔒 安全建议

1. **立即修改默认密码**
2. **设置强 `SECRET_KEY`**
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **启用 HTTPS**（Render 自动提供）
4. **设置 `SECURE_SSL_REDIRECT`**
   ```python
   if not app.debug:
       app.config['SESSION_COOKIE_SECURE'] = True
   ```

## 📚 更多信息

- [Render 官方文档](https://render.com/docs)
- [Flask 部署指南](https://flask.palletsprojects.com/en/2.3.x/deploying/)
- [PostgreSQL on Render](https://render.com/docs/databases)

---

部署有问题？查看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 或提交 Issue！
