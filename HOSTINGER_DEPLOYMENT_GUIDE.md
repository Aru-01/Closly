# 🌐 Closly Backend — Hostinger VPS Deployment Guide (Complete Step-by-Step)

This guide provides a comprehensive walkthrough for deploying the **Closly Backend** on a **Hostinger VPS** using **Ubuntu 24.04 / 22.04 LTS**.

---

> ⚠️ **CRITICAL NOTE ABOUT HOSTINGER:**
> You **MUST** use a **Hostinger KVM VPS** (VPS 1, VPS 2, etc.), **NOT** shared web hosting.
> - *Shared Web Hosting* only supports PHP/MySQL and cannot run long-running background daemons like **Daphne (WebSockets)**, **Redis**, or **Celery Workers**.
> - *Hostinger KVM VPS* gives you dedicated root access, full memory, and freedom to run Docker, PostgreSQL, Redis, and Python.

---

## 📋 Table of Contents
1. [Step 1: Access Your Hostinger VPS](#step-1-access-your-hostinger-vps)
2. [Step 2: Server Preparation & Swap Memory](#step-2-server-preparation--swap-memory)
3. [Option A: One-Command Docker Compose Deployment (Recommended)](#option-a-one-command-docker-compose-deployment-recommended)
4. [Option B: Native Systemd Services Deployment](#option-b-native-systemd-services-deployment)
5. [Step 3: Point Domain in Hostinger DNS Management](#step-3-point-domain-in-hostinger-dns-management)
6. [Step 4: Configure Nginx & WebSocket Reverse Proxy](#step-4-configure-nginx--websocket-reverse-proxy)
7. [Step 5: Install Free Let's Encrypt SSL](#step-5-install-free-lets-encrypt-ssl)
8. [Step 6: Verify Deployment & Health Check](#step-6-verify-deployment--health-check)
9. [Troubleshooting & Pro-Tips](#troubleshooting--pro-tips)

---

## Step 1: Access Your Hostinger VPS

1. Log into your [Hostinger Account (hPanel)](https://hpanel.hostinger.com/).
2. Click **VPS** from the top menu.
3. Select your active VPS plan (e.g., *KVM 1* or *KVM 2*).
4. In the **OS & Panel** settings, make sure your OS is **Ubuntu 22.04 64bit** or **Ubuntu 24.04 64bit** (If not, click *Operating System* and rebuild with Ubuntu).
5. Look for:
   - **IP Address**: (e.g. `185.193.12.34`)
   - **Root Password**: Set or reset your root password here.
6. Open **PowerShell** (Windows) or **Terminal** (Mac/Linux) on your computer and connect:

```bash
ssh root@YOUR_HOSTINGER_VPS_IP
```
Enter your VPS root password when prompted.

---

## Step 2: Server Preparation & Swap Memory

Once logged into your Hostinger VPS, run the following setup commands:

```bash
# 1. Update system packages
apt update && apt upgrade -y

# 2. Add 2GB Swap Memory (essential for Hostinger VPS 1 to prevent memory spikes)
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 3. Install essential tools
apt install -y git curl wget ufw htop libpq-dev

# 4. Configure Hostinger UFW Firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

---

## Option A: One-Command Docker Compose Deployment (Recommended)

Docker Compose bundles PostgreSQL, Redis, Daphne Web Server, and Celery into isolated containers that automatically restart if the VPS reboots.

### 1. Install Docker & Docker Compose Plugin
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
docker --version
docker compose version
```

### 2. Clone Your Project
```bash
cd /root
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git closly
cd closly
```

### 3. Setup Production Environment `.env`
```bash
cp .env.example .env
nano .env
```

Set the production variables:
```ini
DEBUG=False
SECRET_KEY=put_a_very_long_secure_random_key_here_50_chars
ALLOWED_HOSTS=api.yourdomain.com,YOUR_HOSTINGER_VPS_IP,localhost,127.0.0.1
BACKEND_URL=https://api.yourdomain.com
FORCE_HTTPS_MEDIA_URL=True

# Database (Handled automatically by Docker Compose)
DB_ENGINE=django.db.backends.postgresql
DB_NAME=Closly
DB_USER=postgres
DB_PASSWORD=YourStrongDatabasePassword123!
DOCKER_DB_HOST=db
DB_PORT=5432

# Redis & Celery
REDIS_HOST=redis
REDIS_PORT=6379
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# AI Services
LLM_API_KEY=your-openai-api-key
LLM_MODEL=gpt-4o
APIFY_API_TOKEN=your-apify-token
```
Press `Ctrl+O`, Enter, then `Ctrl+X` to save and exit.

### 4. Copy Firebase Credentials
```bash
nano my-closly-firebase-adminsdk-fbsvc-2085b8b0b1.json
# Paste your service account JSON contents, save and exit.
```

### 5. Launch the Entire System
```bash
# 1. Build and start all 5 containers (DB, Redis, Daphne, Worker, Beat)
docker compose up -d --build

# 2. Run Database Migrations
docker compose exec web python manage.py migrate

# 3. Collect Static Assets
docker compose exec web python manage.py collectstatic --noinput

# 4. Create your Admin Superuser
docker compose exec web python manage.py createsuperuser
```

Verify all services are up:
```bash
docker compose ps
```
You should see `closly_web`, `closly_postgres`, `closly_redis`, `closly_celery_worker`, and `closly_celery_beat` all marked as **Up**. Skip to **[Step 3](#step-3-point-domain-in-hostinger-dns-management)**.

---

## Option B: Native Systemd Services Deployment

If you prefer installing Python, PostgreSQL, and Redis directly on the VPS:

### 1. Install System Dependencies
```bash
apt update
apt install -y python3-pip python3-venv python3-dev postgresql postgresql-contrib redis-server nginx libpq-dev libjpeg-dev zlib1g-dev
```

### 2. Configure PostgreSQL
```bash
sudo -u postgres psql
```
```sql
CREATE DATABASE closly_db;
CREATE USER closly_user WITH PASSWORD 'YourStrongDbPassword123!';
ALTER ROLE closly_user SET client_encoding TO 'utf8';
ALTER ROLE closly_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE closly_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE closly_db TO closly_user;
\q
```

### 3. Setup Codebase & Virtual Environment
```bash
cd /var/www
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git closly
cd closly

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
nano .env
```
Ensure your `.env` connects to `DB_HOST=127.0.0.1`, `DB_NAME=closly_db`, and `DB_USER=closly_user`.

Run initialization:
```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### 4. Create Systemd Services for Daphne & Celery

**Daphne ASGI Service**:
```bash
nano /etc/systemd/system/closly_daphne.service
```
```ini
[Unit]
Description=Closly Daphne ASGI Server
After=network.target redis-server.service

[Service]
User=root
WorkingDirectory=/var/www/closly
ExecStart=/var/www/closly/.venv/bin/daphne -b 127.0.0.1 -p 8000 Config.asgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Celery Worker Service**:
```bash
nano /etc/systemd/system/closly_celery.service
```
```ini
[Unit]
Description=Closly Celery Worker
After=network.target redis-server.service

[Service]
User=root
WorkingDirectory=/var/www/closly
ExecStart=/var/www/closly/.venv/bin/celery -A Config worker -l info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Celery Beat Service**:
```bash
nano /etc/systemd/system/closly_celery_beat.service
```
```ini
[Unit]
Description=Closly Celery Beat Scheduler
After=network.target redis-server.service

[Service]
User=root
WorkingDirectory=/var/www/closly
ExecStart=/var/www/closly/.venv/bin/celery -A Config beat -l info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
systemctl daemon-reload
systemctl enable --now closly_daphne closly_celery closly_celery_beat
```

---

## Step 3: Point Domain in Hostinger DNS Management

If your domain is hosted on Hostinger:
1. In **hPanel**, go to **Domains** -> Select your domain.
2. Click **DNS / Nameservers**.
3. Under **Manage DNS records**, create an **A Record**:
   - **Type**: `A`
   - **Name**: `api` (creates `api.yourdomain.com`) or `@` (for root domain)
   - **Points to**: `YOUR_HOSTINGER_VPS_IP`
   - **TTL**: `300`
4. Click **Add Record**. Wait 3-5 minutes for propagation.

---

## Step 4: Configure Nginx & WebSocket Reverse Proxy

1. Install Nginx:
```bash
apt install -y nginx
```

2. Create site configuration:
```bash
nano /etc/nginx/sites-available/closly
```

3. Paste this optimized Nginx configuration:
```nginx
upstream daphne_app {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name api.yourdomain.com;

    # Allow high-res clothing and story photos
    client_max_body_size 50M;

    # Static assets served directly by Nginx
    location /static/ {
        alias /root/closly/staticfiles/;   # Or /var/www/closly/staticfiles/ if using Option B
        expires 30d;
        access_log off;
    }

    # Media uploads served directly
    location /media/ {
        alias /root/closly/media/;         # Or /var/www/closly/media/ if using Option B
        expires 7d;
        access_log off;
    }

    # Reverse proxy for REST APIs and WebSockets
    location / {
        proxy_pass http://daphne_app;

        # WebSocket Upgrade headers
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Forwarded headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_redirect off;
        proxy_buffering off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

4. Enable and restart Nginx:
```bash
ln -sf /etc/nginx/sites-available/closly /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
```

---

## Step 5: Install Free Let's Encrypt SSL

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d api.yourdomain.com
```
Follow the on-screen prompt, type your email, and accept terms. Certbot will automatically issue the SSL certificate, renew it every 90 days, and redirect all HTTP traffic to HTTPS!

---

## Step 6: Verify Deployment & Health Check

Test your live endpoints:
1. **Health Check API**: `https://api.yourdomain.com/api/system/health/` (Should return database and redis as connected).
2. **Swagger Docs**: `https://api.yourdomain.com/api/docs/`
3. **Luxury Admin**: `https://api.yourdomain.com/admin/`

---

## Troubleshooting & Pro-Tips

| Problem | Cause | Solution |
| :--- | :--- | :--- |
| **502 Bad Gateway** | Daphne is not running | Run `docker compose ps` or `systemctl status closly_daphne` to see error logs. |
| **Media Images 403 Forbidden** | File permissions | Run `chmod -R 755 /root/closly/media` or `/var/www/closly/media`. |
| **WebSocket Connection Failed** | Missing proxy upgrade | Ensure `Upgrade $http_upgrade` and `Connection "upgrade"` are inside your Nginx location block. |
| **Server Crash during Build** | Out of Memory | Ensure the 2GB Swap file from Step 2 is active (`free -h`). |

🎉 **Your Closly backend is now fully live on Hostinger VPS!**
