# L丶YOU 的博客

> 基于 Flask 的个人博客系统 — 已部署在 Render，在线访问 👉 https://lyou-blog.onrender.com

## 功能

- 📝 Markdown 编辑文章
- 🏷️ 标签分类
- 📱 响应式设计（手机/平板/桌面）
- 🌙 深色模式
- 🔍 全文搜索
- 📄 分页浏览
- 🔐 管理员登录认证
- 🔑 在线修改密码
- 🖼️ 特色图片上传
- 📊 站点统计

## 本地运行

```bash
# 安装依赖
pip install flask markdown python-dateutil gunicorn

# 启动
python app.py
```

访问 http://127.0.0.1:5000

**默认管理员账号：** `admin` / `admin123`

## 部署

已部署到 **Render**（免费）。
每次推送到 GitHub `main` 分支，Render 自动重新部署。

### 技术栈

| 技术 | 用途 |
|------|------|
| Flask | Web 框架 |
| SQLite | 数据库 |
| Jinja2 | 模板引擎 |
| Markdown | 文章渲染 |
| Gunicorn | 生产服务器 |
| Render | 云托管 |

## 项目结构

```
blog_project/
├── app.py              # Flask 主应用（完整自包含）
├── requirements.txt    # Python 依赖
├── static/             # 静态文件
│   ├── css/style.css
│   └── js/main.js
└── templates/          # HTML 模板（8个页面）
    ├── base.html
    ├── index.html
    ├── post.html
    ├── admin.html
    ├── edit.html
    ├── login.html
    ├── change_password.html
    └── 404.html
```
