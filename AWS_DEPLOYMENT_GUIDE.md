# 🚀 Closly Backend — AWS EC2 Deployment Guide (A-to-Z Beginner Friendly)

This guide takes you step-by-step from zero to a fully functional production deployment of the **Closly Backend** on **Amazon Web Services (AWS) EC2** with **Ubuntu 24.04/22.04 LTS**, **PostgreSQL**, **Redis**, **Daphne (ASGI + WebSockets)**, **Celery**, and **Nginx with free SSL (Let's Encrypt)**.

---

## 📋 Table of Contents
1. [Prerequisites & Architecture](#1-prerequisites--architecture)
2. [Step 1: Launch an AWS EC2 Instance](#step-1-launch-an-aws-ec2-instance)
3. [Step 2: Configure AWS Security Group (Firewall)](#step-2-configure-aws-security-group-firewall)
4. [Step 3: Connect to EC2 via SSH](#step-3-connect-to-ec2-via-ssh)
5. [Step 4: Initial Server Setup & Swap Memory](#step-4-initial-server-setup--swap-memory)
6. [Option A: Fast Docker Compose Deployment (Recommended)](#option-a-fast-docker-compose-deployment-recommended)
7. [Option B: Native Ubuntu Services Deployment (Systemd)](#option-b-native-ubuntu-services-deployment-systemd)
8. [Step 5: Configure Nginx & WebSocket Reverse Proxy](#step-5-configure-nginx--websocket-reverse-proxy)
9. [Step 6: Point Your Domain & Set Up Free SSL](#step-6-point-your-domain--set-up-free-ssl)
10. [Step 7: Production Verification & Health Check](#step-7-production-verification--health-check)
11. [Step 8: Useful Maintenance Commands](#step-8-useful-maintenance-commands)

---

## 1. Prerequisites & Architecture

The Closly Backend requires:
- **Python 3.12**
- **PostgreSQL 15+** (Relational database)
- **Redis 7+** (In-memory broker for WebSockets & Celery background tasks)
- **Daphne** (ASGI application server capable of handling both REST API HTTP requests and WebSocket connections)
- **Celery Worker & Celery Beat** (Asynchronous background tasks and scheduled tasks)
- **Nginx** (Reverse proxy, SSL termination, and high-speed static/media file serving)

### Recommended EC2 Specifications:
- **Instance Type**: `t3.small` (2 GB RAM) minimum, or `t3.medium` (4 GB RAM) recommended.
- **Storage**: 20 GB – 30 GB gp3 SSD.
- **OS**: Ubuntu Server 24.04 LTS or 22.04 LTS (64-bit x86).

---

## Step 1: Launch an AWS EC2 Instance

1. Log into your [AWS Management Console](https://console.aws.amazon.com/).
2. In the top search bar, type **EC2** and click **EC2**.
3. Click the orange **"Launch instance"** button.
4. **Name and tags**: Enter `closly-backend-prod`.
5. **Application and OS Images**: Choose **Ubuntu** -> **Ubuntu Server 24.04 LTS (HVM), SSD Volume Type**.
6. **Instance type**: Select **t3.small** (or **t3.medium**).
7. **Key pair (login)**:
   - Click **Create new key pair**.
   - Key pair name: `closly-key`.
   - Key pair type: `RSA`.
   - Private key file format: `.pem` (for OpenSSH / Mac / Linux / Windows PowerShell).
   - Click **Create key pair** and save the downloaded `closly-key.pem` in a safe location (e.g. `C:\Users\YourUser\.ssh\closly-key.pem`).
8. **Network settings**:
   - Check ✅ **Allow SSH traffic from** -> **Anywhere** (0.0.0.0/0) or My IP.
   - Check ✅ **Allow HTTP traffic from the internet** (Port 80).
   - Check ✅ **Allow HTTPS traffic from the internet** (Port 443).
9. **Configure storage**: Change size from 8 GiB to **25 GiB** gp3.
10. Click **Launch instance**.
11. Wait 1-2 minutes until the instance state shows **"Running"**. Copy your instance's **Public IPv4 address** (e.g., `54.123.45.67`).

---

## Step 2: Configure AWS Security Group (Firewall)

Verify your EC2 Security Group rules:
1. In EC2 Dashboard, go to **Network & Security** -> **Security Groups**.
2. Click your instance's security group -> **Edit inbound rules**.
3. Ensure the following 3 rules exist:
   - **SSH**: Port `22` | Source: `0.0.0.0/0`
   - **HTTP**: Port `80` | Source: `0.0.0.0/0`
   - **HTTPS**: Port `443` | Source: `0.0.0.0/0`
4. Click **Save rules**.

---

## Step 3: Connect to EC2 via SSH

Open **PowerShell** (Windows) or **Terminal** (Mac/Linux) on your computer:

```bash
# 1. On Windows PowerShell, navigate to where your .pem file is:
cd C:\Users\YourUser\.ssh

# 2. (Mac/Linux only) Set correct read-only permission:
chmod 400 closly-key.pem

# 3. Connect to your EC2 instance (replace with your actual EC2 Public IP):
ssh -i "closly-key.pem" ubuntu@YOUR_EC2_PUBLIC_IP
```

When asked `Are you sure you want to continue connecting (yes/no)?`, type `yes` and hit Enter. You are now inside your remote Ubuntu server!

---

## Step 4: Initial Server Setup & Swap Memory

Run these commands inside your EC2 terminal:

```bash
# 1. Update and upgrade Ubuntu packages
sudo apt update && sudo apt upgrade -y

# 2. Add 2GB Swap Memory (prevents out-of-memory crashes during builds)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 3. Install common utilities
sudo apt install -y curl git ufw htop unzip libpq-dev
```

---

## Option A: Fast Docker Compose Deployment (Recommended)

This is the simplest, cleanest method. Everything (Postgres, Redis, Daphne Web, Celery Worker, Celery Beat) runs in synchronized containers.

### 1. Install Docker & Docker Compose
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker

# Verify Docker installation
docker --version
docker compose version
```

### 2. Clone Repository & Setup Environment
```bash
# Clone project into /var/www/closly (or your home directory)
cd /home/ubuntu
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git closly
cd closly

# Copy sample environment file
cp .env.example .env
nano .env
```

Edit your `.env` values:
```ini
DEBUG=False
SECRET_KEY=generate_a_long_random_50_character_secret_key_here
ALLOWED_HOSTS=api.yourdomain.com,YOUR_EC2_PUBLIC_IP,localhost,127.0.0.1
BACKEND_URL=https://api.yourdomain.com
FORCE_HTTPS_MEDIA_URL=True

# Database (Used by Docker Compose)
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
Press `Ctrl+O`, Enter to save, and `Ctrl+X` to exit nano.

### 3. Copy Firebase Service Account JSON
Place your Firebase Admin SDK service account file in the project root:
```bash
# Copy your credentials JSON to:
nano my-closly-firebase-adminsdk-fbsvc-2085b8b0b1.json
# Paste contents, save and exit.
```

### 4. Build and Start All Containers
```bash
# Build and launch in background
docker compose up -d --build

# Run database migrations
docker compose exec web python manage.py migrate

# Collect static files
docker compose exec web python manage.py collectstatic --noinput

# Create your admin superuser account
docker compose exec web python manage.py createsuperuser
```

### 5. Check Status of All Services
```bash
docker compose ps
docker compose logs -f web
```
You should see Daphne running on `0.0.0.0:8000`. Skip to **[Step 5](#step-5-configure-nginx--websocket-reverse-proxy)**.

---

## Option B: Native Ubuntu Services Deployment (Systemd)

If you prefer running services directly on the host without Docker:

### 1. Install System Dependencies
```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev postgresql postgresql-contrib redis-server nginx libpq-dev libjpeg-dev zlib1g-dev
```

### 2. Configure PostgreSQL
```bash
sudo -u postgres psql
```
In the PostgreSQL prompt:
```sql
CREATE DATABASE closly_db;
CREATE USER closly_user WITH PASSWORD 'YourStrongDbPassword123!';
ALTER ROLE closly_user SET client_encoding TO 'utf8';
ALTER ROLE closly_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE closly_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE closly_db TO closly_user;
\q
```

### 3. Setup Project & Virtual Environment
```bash
cd /home/ubuntu
git clone https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git closly
cd closly

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Setup .env file
cp .env.example .env
nano .env
```
Ensure your `.env` contains:
```ini
DEBUG=False
SECRET_KEY=your_generated_secret_key
ALLOWED_HOSTS=api.yourdomain.com,YOUR_EC2_PUBLIC_IP,localhost,127.0.0.1
BACKEND_URL=https://api.yourdomain.com
FORCE_HTTPS_MEDIA_URL=True

DB_ENGINE=django.db.backends.postgresql
DB_NAME=closly_db
DB_USER=closly_user
DB_PASSWORD=YourStrongDbPassword123!
DB_HOST=127.0.0.1
DB_PORT=5432

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
```

### 4. Run Migrations & Collect Static
```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### 5. Setup Daphne Multi-Worker Systemd Service (High-Concurrency)
Daphne is single-threaded async. To utilize all CPU cores for 5,000+ users, run **4 Daphne workers** load-balanced by Nginx:

Create `/etc/systemd/system/closly_daphne@.service`:
```bash
sudo nano /etc/systemd/system/closly_daphne@.service
```
Paste the following:
```ini
[Unit]
Description=Closly Daphne ASGI Server on Port %i
After=network.target redis-server.service postgresql.service

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/closly
ExecStart=/home/ubuntu/closly/.venv/bin/daphne -b 127.0.0.1 -p %i Config.asgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### 6. Setup Celery Worker Service
```bash
sudo nano /etc/systemd/system/closly_celery.service
```
Paste:
```ini
[Unit]
Description=Closly Celery Worker
After=network.target redis-server.service postgresql.service

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/closly
ExecStart=/home/ubuntu/closly/.venv/bin/celery -A Config worker -l info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 7. Setup Celery Beat Service
```bash
sudo nano /etc/systemd/system/closly_celery_beat.service
```
Paste:
```ini
[Unit]
Description=Closly Celery Beat Scheduler
After=network.target redis-server.service postgresql.service

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/closly
ExecStart=/home/ubuntu/closly/.venv/bin/celery -A Config beat -l info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 8. Enable & Start Services (4 Daphne Workers)
```bash
sudo systemctl daemon-reload

# Start 4 parallel Daphne worker processes on ports 8001, 8002, 8003, 8004
sudo systemctl enable --now closly_daphne@8001
sudo systemctl enable --now closly_daphne@8002
sudo systemctl enable --now closly_daphne@8003
sudo systemctl enable --now closly_daphne@8004

# Start Celery tasks
sudo systemctl enable --now closly_celery
sudo systemctl enable --now closly_celery_beat

# Verify all 4 workers are active
sudo systemctl status "closly_daphne@*"
```

---

## Step 5: Configure Nginx & WebSocket Reverse Proxy

Nginx acts as the front gateway, terminating SSL, load-balancing traffic across the 4 Daphne workers, proxying REST API calls, and upgrading WebSocket connections.

1. Install Nginx (if not already installed):
```bash
sudo apt install -y nginx
```

2. Create a new Nginx configuration file:
```bash
sudo nano /etc/nginx/sites-available/closly
```

3. Paste the following configuration (replace `api.yourdomain.com` with your domain or EC2 Public IP):
```nginx
upstream daphne_backend {
    # Load balances requests across 4 Daphne worker processes
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
    server 127.0.0.1:8003;
    server 127.0.0.1:8004;
}

server {
    listen 80;
    server_name api.yourdomain.com;

    # Allow uploads up to 50MB (high-res garment images)
    client_max_body_size 50M;

    # Static files served directly by Nginx with aggressive caching
    location /static/ {
        alias /home/ubuntu/closly/staticfiles/;
        expires 30d;
        access_log off;
        add_header Cache-Control "public, max-age=2592000";
    }

    # Media files (user photos, outfits, stories) served directly
    location /media/ {
        alias /home/ubuntu/closly/media/;
        expires 7d;
        access_log off;
        add_header Cache-Control "public, max-age=604800";
    }

    # HTTP & WebSocket Reverse Proxy to Daphne
    location / {
        proxy_pass http://daphne_backend;
        
        # Mandatory WebSocket upgrade headers
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Standard proxy headers
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

4. Enable site & test Nginx configuration:
```bash
sudo ln -sf /etc/nginx/sites-available/closly /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

---

## Step 6: Point Your Domain & Set Up Free SSL

1. Go to your DNS provider (Cloudflare, GoDaddy, Namecheap, AWS Route 53).
2. Add an **A Record**:
   - **Type**: `A`
   - **Name**: `api` (or `@` for root domain)
   - **Value**: `YOUR_EC2_PUBLIC_IP`
   - **TTL**: Auto / 300s
3. Wait 2-5 minutes for DNS to propagate. Test with:
   ```bash
   ping api.yourdomain.com
   ```
4. Install **Certbot** and acquire free Let's Encrypt SSL certificate:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourdomain.com
```
Enter your email and accept terms. Certbot will automatically configure HTTPS inside your Nginx config and set up automatic 90-day renewals!

---

## Step 7: Production Verification & Health Check

Visit the following URLs in your browser to verify your deployment:

1. **System Health Check**:
   `https://api.yourdomain.com/api/system/health/`
   Should return:
   ```json
   {
     "status": "healthy",
     "database": "connected",
     "redis": "connected"
   }
   ```
2. **Interactive Swagger Documentation**:
   `https://api.yourdomain.com/api/docs/`
3. **Admin Dashboard**:
   `https://api.yourdomain.com/admin/`

---

## Step 8: Useful Maintenance Commands

```bash
# View live application logs (Docker)
docker compose logs -f web
docker compose logs -f celery_worker

# View live application logs (Native Systemd)
sudo journalctl -u closly_daphne -f
sudo journalctl -u closly_celery -f

# Restart Daphne
docker compose restart web              # (Docker)
sudo systemctl restart closly_daphne   # (Native)

# Run migrations after git pull
docker compose exec web python manage.py migrate
# or (Native):
source .venv/bin/activate && python manage.py migrate

# Check Redis connection
redis-cli ping
```

🎉 **Congratulations! Your Closly Backend is live and running securely on AWS!**
