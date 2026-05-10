# L丶YOU's Blog

> A personal blog built with Flask — deployed on Render  
> Live at 👉 https://lyou-blog.onrender.com

## Features

- 📝 Markdown editor for writing posts
- 🏷️ Tag-based categorization
- 📱 Responsive design (mobile/tablet/desktop)
- 🌙 Dark mode toggle
- 🔍 Full-text search
- 📄 Pagination
- 🔐 Admin login & authentication
- 🔑 Online password change
- 🖼️ Featured image upload
- 📊 Site statistics

## Local Development

```bash
# Install dependencies
pip install flask markdown python-dateutil gunicorn

# Start server
python app.py
```

Visit http://127.0.0.1:5000

**Default admin credentials:** `admin` / `admin123`

## Deployment

Deployed on **Render** (free tier).
Auto-deploys from GitHub `main` branch on every push.

### Tech Stack

| Tech | Purpose |
|------|---------|
| Flask | Web framework |
| SQLite | Database |
| Jinja2 | Template engine |
| Markdown | Content rendering |
| Gunicorn | Production WSGI server |
| Render | Cloud hosting |

## Project Structure

```
blog_project/
├── app.py              # Flask application (self-contained)
├── requirements.txt    # Python dependencies
├── static/             # Static assets
│   ├── css/style.css
│   └── js/main.js
└── templates/          # HTML templates (8 pages)
    ├── base.html
    ├── index.html
    ├── post.html
    ├── admin.html
    ├── edit.html
    ├── login.html
    ├── change_password.html
    └── 404.html
```

## Admin Guide

- **Login:** Click "Login" in the navbar, or visit `/login`
- **Write post:** Login → click "Write" → fill in title, content, tags → publish
- **Edit/Delete:** From admin panel (`/admin`) or post detail page
- **Change password:** From admin panel → "Change Password"
- **Upload image:** Use the image upload button in the editor toolbar
