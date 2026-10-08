# Closly — Backend API & Infrastructure

Closly is the backend service powering the Closly mobile and web applications. It brings together social networking, AI-powered wardrobe digitization, automated affiliate commerce, and gamified loyalty rewards into a single unified platform.

Built with Python, Django 5.2, Django REST Framework, and Django Channels (WebSockets), the system is designed to handle high concurrency with Redis caching, asynchronous Celery workers, and a fully dockerized microservice-style architecture.

---

## Architecture Overview

Here is a high-level picture of how requests flow through Closly:

```
[ Mobile App / Web Clients ]
             │
             ├─── HTTP / REST ──────> [ Nginx / Reverse Proxy ]
             └─── WebSockets (WSS) ──> [ Daphne ASGI Server :8000 ]
                                              │
                      ┌───────────────────────┼──────────────────────┐
                      │                       │                      │
             [ Django DRF API ]       [ Django Channels ]     [ Static/Media ]
                      │                       │               (Local / S3 / R2)
                      ├───────────────────────┤
                      │                       │
             [ PostgreSQL 16 ]         [ Redis 7 ]
                                      (Cache, Broker,
                                       Channel Layer)
                                              │
                                   ┌──────────┴──────────┐
                                   │                     │
                          [ Celery Worker ]       [ Celery Beat ]
                           - Feed Ingestion        - Hourly Story Cleanup
                           - Push Notifications    - Daily Notification Purge
                           - AI Image Processing   - Affiliate Sync Cron
```

### Core Technology Stack

- **Framework**: Django 5.2 & Django REST Framework (DRF) 3.16
- **ASGI & WebSockets**: Daphne + Django Channels 4.0 + Channels-Redis
- **Database**: PostgreSQL 16 (production/Docker) / SQLite (local dev fallback)
- **Asynchronous Task Queue**: Celery 5.3+ backed by Redis 7
- **AI Vision Engine**: OpenAI GPT-4o Vision API + internal FastAPI analyzer module
- **Push Notifications**: Firebase Admin SDK (Cloud Messaging / FCM)
- **Object Storage**: AWS S3 / Cloudflare R2 / Hetzner Storage Box via `django-storages` + `boto3` (graceful fallback to local volume storage)
- **Admin Interface**: Django Unfold (customized dark/light dashboard)
- **API Documentation**: OpenAPI 3.0 via `drf-spectacular` (Swagger UI & ReDoc)

---

## Key Features & App Modules

The platform is split into focused Django applications:

```
├── Config/             # Project settings, routing, ASGI/WSGI, Celery config
├── users/              # Authentication, onboarding, style DNA, profile management
├── closet/             # Digital wardrobe, AI camera scanner, wear tracker, audit
├── social/             # Outfits, explore/following feeds, stories, real-time chat
├── affiliate/          # Awin & Rakuten product ingestion, "For You" feed, clicks
├── rewards/            # Loyalty tiers, points ledger, purchase claims, referrals
├── notifications/      # FCM push dispatch, in-app notification center
├── legal_pages/        # Privacy policy, terms, account & data deletion requests
└── dress-analyzer-ai/  # Standalone/integrated FastAPI computer vision service
```

---

### 1. Identity, Auth & Style DNA (`users`)

- **UUID Primary Keys**: All user records use UUIDv4 to eliminate sequential enumeration attacks.
- **Multi-Method Authentication**:
  - Email + Password with custom UserManager.
  - OTP verification for registration and secure password resets (10-minute expiry with automatic database cleanup).
  - Social login via Firebase Auth (Google & Apple tokens verified through Firebase Admin SDK).
  - JWT Tokens with rotation and blacklisting (`rest_framework_simplejwt`).
- **Deep Style DNA Onboarding**: Captures multi-dimensional user preferences:
  - *Style Identities*: Streetwear, Minimalist, Classic, Bohemian, Romantic, Preppy, etc.
  - *Occasions*: Work-casual, smart, gym, weekend, travel, formal.
  - *Measurements & Body Type*: Hourglass, pear, rectangle, etc., height, weight, sizes.
  - *Skin Tone & Palette*: Stored as hex codes (`#F5CBA7`) with recommended color palettes.
  - *Brand Preferences*: Grouped lists across everyday, popular, and designer labels.
- **Real-Time Dynamic Translation Middleware**: Transparently translates outgoing JSON API responses into the user's preferred language (e.g., Hindi, Portuguese) via `deep-translator`. Technical keys, IDs, URLs, and hex codes are skipped automatically, and translations are cached in Redis to maintain fast response times.
- **Audit & Compliance**:
  - Full login history tracking (IP address, user-agent, timestamp).
  - Multi-step account deletion and profile data erasure workflows with verification tokens.
  - Public web profiles (`/u/<user_id>/`) with server-side OpenGraph tags for rich previews when shared.

---

### 2. Smart Digital Wardrobe & AI Scanner (`closet`)

- **Wardrobe Cataloging**: Users categorize garments into Tops, Bottoms, Shoes, Dresses/Outerwear, and Accessories.
- **AI Camera Scanner (`closet/openai_analyzer.py`)**:
  - Direct integration with GPT-4o Vision to classify garments from a camera snapshot.
  - Detects garment type, primary & secondary colors, patterns (solid, floral, striped), brand logo recognition, and estimated retail price ranges.
  - **Concurrency Gating**: Uses an internal `BoundedSemaphore` to throttle simultaneous AI scans and prevent OpenAI 429 rate limits during traffic spikes.
  - **Deduplication & Cache**: Images are hashed via SHA-256; re-analyzing the same image returns cached results instantly.
- **Wear Tracking & Cost-Per-Wear**:
  - "Wear Today" one-tap action increments item wear counters.
  - Real-time calculation: `per_wear_cost = price / times_worn`, helping users quantify the value of their clothes.
- **Closet Audit & Score Dashboard**:
  - Analyzes color balance, most/least worn garments, brand distributions, and gives users a wardrobe utilization score.

---

### 3. Social Network, Stories & Real-Time Messaging (`social`)

- **Outfit Publishing**:
  - Single or multi-image carousel posts (up to 4 high-res photos).
  - Tag clothes directly from the digital closet, add weather notes and style categories.
  - Configurable visibility: Public or Private.
- **Dynamic Feeds & Calendar**:
  - *Public Feed*: Trending and chronological community looks.
  - *Following Feed*: Curated strictly from users you follow.
  - *Explore Feed*: Discover new creators and trending aesthetics.
  - *Your Day*: Chronological personal timeline of daily outfit logs.
  - *Outfit Calendar*: Month-by-month calendar view mapping daily outfit history.
- **24-Hour Stories**:
  - Instagram-style disappearing stories with view tracking, duplicate prevention, and love reactions.
  - Celery Beat hourly task sweeps expired stories without degrading API latency.
- **Real-Time WebSocket Chat (`social/consumers.py`)**:
  - Daphne ASGI + Channels-Redis channel layer.
  - Token-authenticated connections via query parameter (`ws://host/ws/chat/?token=<jwt>`).
  - Typing indicators, read receipts, and online/offline status updates.
  - Supports rich messages: plain text, image uploads, sharing closet outfits, and sharing affiliate products directly inside the chat thread.

---

### 4. Affiliate Commerce Engine (`affiliate`)

- **Multi-Network Catalog**:
  - Connects to Awin and Rakuten Advertising networks.
  - Houses thousands of products with merchant tracking URLs (`aw_deep_link`), sale prices, original RRP, and discount percentage calculations.
- **High-Performance Ingestion (`sync_awin_feeds`, `sync_rakuten_feeds`)**:
  - Streams gzip CSV files directly from affiliate endpoints without saving full dumps to disk.
  - Uses bulk-upserts (`bulk_create` with `update_conflicts=True`) in chunks of 1,000 items to minimize database locks.
  - Marks obsolete products inactive in a single atomic update query.
- **Personalized "For You" Feed**:
  - Matches user Style DNA (preferred brands, color palettes, garment categories) against the affiliate database to provide an individualized shopping stream.
- **Internal Click Tracking**:
  - Records user intent (`ProductClick`) when clicking "Buy" before redirecting to the merchant, providing internal conversion analytics.
- **Wishlist**: Users can "Love" or "Save" affiliate items into a personal wishlist.

---

### 5. Gamification & Loyalty Rewards (`rewards`)

- **Dual-Balance Ledger**:
  - `available_points`: Spendable points that expire after 60 days.
  - `lifetime_points`: All-time earned points that permanently dictate VIP tier status and never decrease on point expiry.
- **VIP Tiers**:
  - **Bronze**: 0 – 2,000 pts
  - **Silver**: 2,000 – 5,000 pts
  - **Gold**: 5,000 – 10,000 pts
  - **Platinum**: 10,000 – 50,000 pts
  - **Diamond**: 50,000+ pts
- **Point Actions**:
  - Sharing an outfit look: `+120 pts`
  - Inviting friends with custom referral code: `+200 pts`
  - Making an affiliate purchase: `+200 pts`
  - Adding an item to closet: `+50 pts`
- **Audit Ledger**: Every balance change is recorded in `RewardPointTransaction` for transparent accounting.

---

### 6. Notifications & Firebase Cloud Messaging (`notifications`)

- **Hybrid Dispatch**:
  - Mobile Push Notifications via Firebase Cloud Messaging (FCM).
  - In-app notification center tracking read/unread statuses.
- **Triggered Events**: Outfit likes, new followers, chat messages, points earned, tier upgrades, and system broadcasts.
- **Automated Retention**: Daily Celery Beat cron permanently deletes notifications older than 60 days to prevent table bloat.

---

## API Endpoints Reference

All endpoints are prefixed with `/api/` (except the documentation and public web routes):

### Documentation & Gateway
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | API Gateway Root & Status Dashboard |
| `GET` | `/docs/` | Interactive Swagger UI (OpenAPI 3.0) |
| `GET` | `/redoc/` | ReDoc Interactive Documentation |
| `GET` | `/api/docs/postman/` | Downloadable Postman Collection JSON |
| `GET` | `/api/health/` | Service health check |
| `GET` | `/api/health/ping/` | Lightweight uptime heartbeat |

### Authentication & User Management (`/api/users/`)
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/users/signup/` | Register with email and password |
| `POST` | `/api/users/login/` | Authenticate and obtain JWT access + refresh tokens |
| `POST` | `/api/users/logout/` | Blacklist current refresh token |
| `POST` | `/api/users/firebase-auth/` | Authenticate via Firebase Google / Apple token |
| `POST` | `/api/users/verify-otp/` | Verify registration or password OTP |
| `POST` | `/api/users/resend-otp/` | Request a fresh OTP code |
| `POST` | `/api/users/password-reset/` | Request password reset email |
| `POST` | `/api/users/password-reset-confirm/` | Set new password with OTP confirmation |
| `GET/PUT` | `/api/users/profile/` | Fetch or update user profile |
| `GET/POST`| `/api/users/preferences/` | Get or update style DNA & onboarding preferences |
| `POST` | `/api/users/set-language/` | Change preferred translation language |
| `GET` | `/api/users/profile/share/` | Generate profile share link & referral code |

### Digital Wardrobe (`/api/closet/`)
| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/closet/items/` | List wardrobe items or add new piece |
| `GET/PUT/DEL`| `/api/closet/items/<id>/` | View, update, or remove an item |
| `POST` | `/api/closet/items/<id>/wear/` | Record item worn today (updates cost-per-wear) |
| `POST` | `/api/closet/ai-scan/` | Scan garment image with AI vision |
| `GET` | `/api/closet/audit/` | Closet audit report (color breakdown, usage) |
| `GET` | `/api/closet/score/` | Wardrobe utilization & efficiency score |

### Social & Feeds (`/api/social/`)
| Method | Endpoint | Description |
|---|---|---|
| `GET/POST` | `/api/social/outfits/` | Get my outfits or post a new look |
| `GET` | `/api/social/feed/` | Public community newsfeed |
| `GET` | `/api/social/feed/following/` | Following-only newsfeed |
| `GET` | `/api/social/explore/` | Explore newsfeed |
| `GET` | `/api/social/outfits/calendar/` | Monthly outfit log calendar |
| `POST` | `/api/social/outfits/<id>/like/` | Like or unlike an outfit |
| `POST` | `/api/social/users/<id>/follow/` | Follow or unfollow a user |
| `GET/POST` | `/api/social/stories/` | View story feed or upload a new 24h story |
| `POST` | `/api/social/stories/<id>/view/` | Mark story as viewed |
| `GET` | `/api/social/conversations/` | List direct message inbox conversations |
| `GET/POST` | `/api/social/messages/<user_id>/` | Fetch message history or send message |

### Affiliate Commerce (`/api/affiliate/`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/affiliate/products/` | Paginated product feed with search and filters |
| `GET` | `/api/affiliate/products/for-you/` | Personalized product suggestions based on Style DNA |
| `GET` | `/api/affiliate/products/<id>/` | Full product details with affiliate links |
| `POST` | `/api/affiliate/products/<id>/save/` | Toggle product favorite / wishlist |
| `GET` | `/api/affiliate/products/saved/` | Retrieve user wishlist |
| `POST` | `/api/affiliate/products/<id>/click/` | Track outbound affiliate link click |

### Rewards & Gamification (`/api/rewards/`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/rewards/points/` | Current points balance, tier progress, and expiration warnings |
| `GET` | `/api/rewards/points/history/` | Transaction history ledger |
| `POST` | `/api/rewards/points/claim-purchase/`| Submit purchase receipt/order ID for reward points |

### Notifications (`/api/notifications/`)
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/notifications/` | List user notifications |
| `POST` | `/api/notifications/<id>/read/` | Mark single notification as read |
| `POST` | `/api/notifications/mark-all-read/`| Mark all notifications as read |

---

## Local Development Setup

### Prerequisites

- Python 3.12+ (in virtual environment)
- Docker Desktop (for Docker development or background services: Postgres & Redis)
- Git

---

### Option A — Local Django Development

Local Django runs directly on your host machine and connects to local PostgreSQL/Redis (or Docker-backed Postgres on port 5433 / Redis on 6379).

1. **Activate your virtual environment**:
   ```powershell
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # macOS/Linux:
   source .venv/bin/activate
   ```

2. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

3. **Start the Django development server**:
   ```bash
   py manage.py runserver
   # or explicitly bind to IPv4 loopback:
   py manage.py runserver 127.0.0.1:8000
   ```

4. **Access the application**:
   - **API Dashboard**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/) or [http://localhost:8000/](http://localhost:8000/)
   - **Swagger UI**: [http://127.0.0.1:8000/docs/](http://127.0.0.1:8000/docs/)
   - **System Health**: [http://127.0.0.1:8000/health/](http://127.0.0.1:8000/health/)
   - **Admin Portal**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

5. **Stopping local Django**:
   - Press `CTRL+C` or `CTRL+BREAK` in the terminal window.
   - On Windows PowerShell, if a background process holds the port:
     ```powershell
     Get-NetTCPConnection -LocalPort 8000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
     ```

---

### Option B — Docker Stack Development

Docker runs the entire production-like environment (Postgres 16, Redis 7, Celery Worker, Celery Beat, and Daphne Web server).

1. **Start all services**:
   ```bash
   docker-compose up -d
   ```
   **Service Port Mappings**:
   - **Web (Daphne ASGI)**: `http://127.0.0.1:8001/` (mapped to internal container port 8000)
   - **PostgreSQL**: `127.0.0.1:5433` -> internal port 5432
   - **Redis**: `127.0.0.1:6379` -> internal port 6379
   - **Celery Worker & Beat**: running internally in Docker network

2. **Access the Docker application**:
   - **API Dashboard**: [http://127.0.0.1:8001/](http://127.0.0.1:8001/) or [http://localhost:8001/](http://localhost:8001/)
   - **Swagger UI**: [http://127.0.0.1:8001/docs/](http://127.0.0.1:8001/docs/)
   - **System Health**: [http://127.0.0.1:8001/health/](http://127.0.0.1:8001/health/)
   - **Admin Portal**: [http://127.0.0.1:8001/admin/](http://127.0.0.1:8001/admin/)

3. **Check container status and logs**:
   ```bash
   docker-compose ps
   docker-compose logs -f web
   ```

4. **Stop Docker stack**:
   ```bash
   docker-compose down
   ```

---

### Development Port Strategy & Port Collision Prevention

To prevent host port collisions between local Django and Docker containers:
- **Local Django**: Listens on host port **`8000`** (`http://127.0.0.1:8000/`).
- **Docker Web Container**: Listens on host port **`8001`** (`http://127.0.0.1:8001/`), forwarding to internal container port `8000`.
- Both environments can run simultaneously without socket collisions.
- In production, configure `WEB_HOST_PORT=8000` in `.env` if binding directly to port 8000 behind Nginx.

**Troubleshooting Port Collisions**:
If you receive `bind: Only one usage of each socket address is normally permitted`:
1. Check what is holding the port:
   ```powershell
   Get-NetTCPConnection -LocalPort 8000, 8001 | Format-Table -AutoSize
   ```
2. Stop the local process or run `docker-compose down`.

---

## Environment Variables Configuration

Create a `.env` file in the root directory. Below are the key settings:

```ini
# Core Django
DEBUG=False
SECRET_KEY=your-strong-random-secret-key
ALLOWED_HOSTS=api.closly.com,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://api.closly.com

# Database (PostgreSQL)
DB_ENGINE=django.db.backends.postgresql
DB_NAME=Closly
DB_USER=postgres
DB_PASSWORD=your_secure_password
DB_HOST=db
DB_PORT=5432

# Redis & Celery
REDIS_HOST=redis
REDIS_PORT=6379
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Optional Object Storage (AWS S3 / Cloudflare R2 / Hetzner)
# If left blank, uploads are stored locally in the ./media volume
USE_S3=False
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=
AWS_S3_ENDPOINT_URL=
AWS_S3_CUSTOM_DOMAIN=
AWS_S3_REGION_NAME=auto

# AI Vision Services
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
AI_SCAN_CONCURRENCY_LIMIT=15

# Push Notifications
FIREBASE_CREDENTIALS_PATH=my-closly-firebase-adminsdk.json

# Transactional Email (AWS SES SMTP - Frankfurt eu-central-1)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=email-smtp.eu-central-1.amazonaws.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<AWS_SES_SMTP_USERNAME_e.g._AKIA...>
EMAIL_HOST_PASSWORD=<AWS_SES_SMTP_PASSWORD>
DEFAULT_FROM_EMAIL=noreply@myclosly.com
SERVER_EMAIL=noreply@myclosly.com
EMAIL_TIMEOUT=10

# Affiliate Data Feeds
AWIN_FEED_URL=
RAKUTEN_FEED_URL=
```

---

## Scheduled Tasks (Celery Beat)

The platform runs several automated background routines:

| Task Name | Schedule | Description |
|---|---|---|
| `social.tasks.expire_old_stories_task` | Every hour | Deactivates stories past their 24h expiration timestamp |
| `notifications.tasks.cleanup_old_notifications_task` | Daily | Removes in-app notifications older than 60 days |
| `affiliate.tasks.sync_awin_feeds_task` | Periodic cron | Streams, decompresses, and bulk-upserts product feeds from Awin |
| `affiliate.tasks.sync_rakuten_feeds_task` | Periodic cron | Ingests product feeds from Rakuten Advertising |

---

## Production Deployment Notes

1. **Static & Media Files**:
   - Collect static files before launching:
     ```bash
     python manage.py collectstatic --noinput
     ```
   - Static files are served via `whitenoise`.
   - Media files (profile pictures, clothes, outfits) should be routed to an S3-compatible bucket (`USE_S3=True`) with a CDN (such as Cloudflare) placed in front.

2. **WebSockets in Production**:
   - Ensure your reverse proxy (Nginx, Traefik, or Caddy) supports HTTP upgrade headers:
     ```nginx
     proxy_http_version 1.1;
     proxy_set_header Upgrade $http_upgrade;
     proxy_set_header Connection "upgrade";
     ```

3. **Zero-Downtime Restarts**:
   - When pulling new changes:
     ```bash
     git pull origin main
     docker compose exec web python manage.py migrate
     docker compose restart web celery_worker celery_beat
     ```

---

## License

This project is proprietary software belonging to Closly. All rights reserved.

---

Built with passion by [Arif](https://www.linkedin.com/in/aru01/) 🖤💻

