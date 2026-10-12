# My Closly — Enterprise Backend Architecture

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-092E20.svg?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16-red.svg)](https://www.django-rest-framework.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Celery](https://img.shields.io/badge/Celery-5.3-37814A.svg?logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![Redis](https://img.shields.io/badge/Redis-7.0-DC382D.svg?logo=redis&logoColor=white)](https://redis.io/)
[![License](https://img.shields.io/badge/License-Proprietary-black.svg)]()

> **Production-grade backend engineering for the DACH fashion ecosystem.**  
> Built with Domain-Driven Design (DDD), "Skinny Views & Fat Services", real-time vector similarity search via `pgvector`, asynchronous AI computer vision, bulletproof affiliate attribution, and strict GDPR compliance.

---

## 📑 Table of Contents
1. [System Overview](#system-overview)
2. [Technology Stack](#technology-stack)
3. [Core Architecture & Design Patterns](#core-architecture--design-patterns)
   - [Domain-Driven Design (DDD) & Service Layer](#domain-driven-design-ddd--service-layer)
   - [Global Database Optimization & N+1 Eradication](#global-database-optimization--n1-eradication)
4. [AI Vector Engine & "For You" Feed](#ai-vector-engine--for-you-feed)
5. [Async AI Wardrobe Scanner](#async-ai-wardrobe-scanner)
6. [Telemetry & Client-Side Event Batching](#telemetry--client-side-event-batching)
7. [Affiliate Attribution & Dynamic Ingestion](#affiliate-attribution--dynamic-ingestion)
8. [Data Privacy, GDPR & Security Hardening](#data-privacy-gdpr--security-hardening)
9. [Celery Workers & Beat Schedules](#celery-workers--beat-schedules)
10. [Local Development & Setup Guide](#local-development--setup-guide)
11. [Testing & Verification](#testing--verification)

---

## 🏛️ System Overview

**My Closly** bridges personal wardrobe digitization, AI-curated fashion discovery, and monetization through European affiliate networks (AWIN & Rakuten). The system solves four core engineering challenges:
1. **The Learning Feed Loop**: Dynamically computes user style affinity without per-request LLM latency through 768-dimensional SigLIP image embeddings and PostgreSQL vector distance indexing.
2. **The "Event Storm" Dilemma**: Ingests high-frequency user interactions (swipes, impressions, dwell times) via client-side batching and asynchronous Celery workers.
3. **Affiliate Click Attribution (EARN)**: Automatically injects cryptographic `clickref` / `u1` tracking tokens into outbound merchant links and reconciles webhook conversions back to user reward profiles.
4. **GDPR Data Minimization**: Fully compliant with European privacy standards (GDPR Art. 9), strictly rejecting sensitive biometric or body measurement data while maintaining cryptographic security standards.

```
                      ┌─────────────────────────────────────────┐
                      │      Clients (iOS / Android / Web)      │
                      └────────────────────┬────────────────────┘
                                           │ HTTPS / WSS
                                           ▼
                      ┌─────────────────────────────────────────┐
                      │    Nginx Edge Proxy & SSRF Firewall     │
                      └────────────────────┬────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    ▼                                             ▼
       ┌────────────────────────┐                    ┌────────────────────────┐
       │   Daphne ASGI Server   │                    │  Protected Media Store │
       │  (Django HTTP + REST)  │                    │   (Sanitized CDN Proxy)│
       └───────────┬────────────┘                    └────────────────────────┘
                   │
    ┌──────────────┴──────────────┐
    ▼                             ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│     PostgreSQL 16       │   │         Redis 7         │
│  - pgvector (768-dim)   │   │  - Broker & Results     │
│  - Relational Schema    │   │  - Feed Cache (26h TTL) │
│  - Atomic Row Locks     │   │  - Distributed Locks    │
└─────────────────────────┘   └────────────┬────────────┘
                                           │
                   ┌───────────────────────┴───────────────────────┐
                   ▼                                               ▼
       ┌────────────────────────┐                     ┌────────────────────────┐
       │  Celery Task Worker    │                     │   Celery Beat Worker   │
       │  - Telemetry Ingestion │                     │  - Daily Brand Sync    │
       │  - AI Vision Pipelines │                     │  - Nightly Embeddings  │
       │  - Webhook Attribution │                     │  - Conversion Rec.     │
       └────────────────────────┘                     └────────────────────────┘
```

---

## 💻 Technology Stack

| Layer | Technologies | Role / Justification |
|---|---|---|
| **Core Framework** | Python 3.12, Django 5.2.8 | Enterprise ORM, security middleware, mature ecosystem |
| **API Framework** | Django REST Framework 3.16 | High-throughput serialized REST endpoints |
| **Realtime & ASGI** | Daphne, Django Channels 4.0 | High-concurrency WebSockets for 1:1 chat |
| **Primary Database** | PostgreSQL 16 + `pgvector` | ACID transactional storage + 768-d vector similarity |
| **Cache & Message Broker** | Redis 7 (Alpine) | In-memory feed caching, Celery message broker |
| **Task Queue** | Celery 5.3+ | Asynchronous batch processing, ingestion, and cron |
| **Computer Vision / AI** | OpenAI GPT-4o Vision, SigLIP | Garment feature extraction and vector embeddings |
| **Image Pipeline** | Pillow (PIL) | EXIF/GPS stripping, thumbnail generation, SSRF defense |
| **Affiliate Networks** | AWIN Publisher API, Rakuten API | DACH product feeds, deep linking, conversion webhooks |
| **Documentation** | drf-spectacular (OpenAPI 3.0) | Interactive Swagger UI (`/docs/`) and OpenAPI schemas |

---

## 🏗️ Core Architecture & Design Patterns

### Domain-Driven Design (DDD) & Service Layer
The codebase follows a strict **"Skinny Views, Fat Services"** pattern. Views are strictly gatekeepers responsible for HTTP routing, permission checking, serializer validation, and returning standardized JSON envelopes. All business logic, third-party integrations, and database mutations live in isolated `services/` modules.

```
affiliate/
├── services/
│   ├── catalog_services.py     # Filter pipelines, queries, affiliate link generation
│   ├── discovery_services.py   # Vector scoring, MMR diversification, feed caching
│   ├── sprint_services.py      # Style Sprint swipe processing, bulk interaction writes
│   ├── telemetry_services.py   # Asynchronous interaction batch ingestion
│   └── image_cdn.py            # SSRF-guarded image replication & CDN synchronization
├── serializers/
│   ├── feed_serializers.py      # Product listing & detail serializers
│   ├── conversion_serializers.py# Conversion & webhook payload validation
│   └── telemetry_serializers.py # Event array validation
└── views/
    ├── catalog_views.py        # Skinny newsfeed, category, and brand endpoints
    ├── discovery_views.py      # Skinny "For You" personalized feed endpoint
    ├── sprint_views.py         # Skinny Style Sprint card deck & swipe handlers
    └── telemetry_views.py      # Skinny HTTP 202 Accepted batch ingestion endpoint
```

### Global Database Optimization & N+1 Eradication
To eliminate query explosion under high load, every ORM query across the platform is audited and optimized:
- **`select_related()`**: Explicitly joined across all Single Foreign Keys (e.g., `AffiliateProduct.brand_ref`, `ProductClick.user`).
- **`prefetch_related()`**: Enforced across Many-to-Many and reverse relations (e.g., `TodayOutfit.tagged_items`, `FitCheck.closet_items`).
- **Bulk Operations**: Telemetry events and swipe reactions utilize `bulk_create()` and `bulk_update()`.
- **Atomic Concurrency**: Reward balance mutations and invite redemptions use `transaction.atomic()` with `select_for_update()` row locking to eliminate race conditions.

---

## 🧠 AI Vector Engine & "For You" Feed

The discovery feed uses a hybrid scoring pipeline operating on **768-dimensional multimodal vectors** generated from garment imagery:

1. **Pre-Filter Gate**: Filters active products matching the DACH market (`currency='EUR'`, `is_active=True`, in-stock, and gender preference matches).
2. **Seen-Item & Saved-Item Exclusion**: Products viewed within the last 30 days or previously saved are excluded.
3. **Vector Distance & Cosine Scoring**:
   $$\text{Score} = w_1 \cdot \text{Sim}(\mathbf{v}_{\text{item}}, \mathbf{v}_{\text{taste}}) + w_2 \cdot \text{Decay}(\Delta t) + w_3 \cdot \text{Discount} + w_4 \cdot \text{Affinity}_{\text{brand}} + w_5 \cdot \text{Affinity}_{\text{palette}}$$
4. **Maximal Marginal Relevance (MMR) & Diversity**:
   - Brand Cap: Maximum 3 items from the same brand per 20-product page.
   - Global Quota: No single brand exceeds 30% of any 100-item candidate window.
5. **Seeded Redis Caching**: Candidates are calculated and cached per `(user_id, seed)` in Redis with a 26-hour TTL (`feed:{user_id}:{seed}`).

---

## 📷 Async AI Wardrobe Scanner

The AI Wardrobe Scanner converts outfit photos into structured digital closet items without blocking web worker threads:

1. **Client Submission**: `POST /api/closet/ai-scan/` validates file signatures and instantly returns **HTTP 202 Accepted** with a task reference.
2. **Privacy Sanitization**: The Celery worker downloads the buffer, strips all EXIF/GPS metadata via Pillow, and stores a cryptographic SHA-256 hash.
3. **Deduplication Check**: If the image hash was previously analyzed, cached results are reused immediately.
4. **AI Vision Analysis**: GPT-4o Vision processes the garment attributes (category, palette, pattern, silhouette, estimated retail value).
5. **Killswitch Guard**: If `MYC_AI_KILLSWITCH=True` is toggled in configuration, the endpoint gracefully returns HTTP 503 Service Unavailable without crashing.

---

## ⚡ Telemetry & Client-Side Event Batching

To prevent mobile battery drain and backend "Event Storms":
- Mobile clients buffer user interactions locally (swipes, impressions, dwell times).
- Interaction arrays are dispatched in bulk to `POST /api/v1/feed/events/batch/` (up to 200 events per payload).
- The skinny view immediately responds with `HTTP 202 Accepted`.
- An asynchronous Celery task batches insertions into the `Event` table using `bulk_create(ignore_conflicts=True)` and applies Exponential Moving Average (EMA) updates to the user's `StyleProfile.taste_vector`.

---

## 💰 Affiliate Attribution & Dynamic Ingestion

### Cryptographic Click Tracking (EARN Loop)
When a user clicks "Buy Now" on a product:
1. `ProductClickView` generates a secure UUIDv4 `click_ref`.
2. Outbound affiliate URLs are dynamically enriched:
   - **AWIN**: Appends `&clickref={click_ref}&clickref2=feed`
   - **Rakuten**: Appends `&u1={click_ref}`
3. Webhook endpoints (`/api/v1/feed/webhooks/awin/`) receive conversion notifications from merchant networks, verify cryptographic HMAC signatures, match the transaction to the original `click_ref`, and transition rewards from **PENDING** to **AVAILABLE**.

### Dynamic Feed Sync
- **AWIN CSV.gz Sync**: Streamed directly via memory-efficient gzip iterators without loading full multi-gigabyte archives into RAM.
- **Rakuten XML Sync**: Synchronizes approved merchant catalogs using OAuth token rotation.
- **Zero-Delta Alarm**: If a feed drops more than 50% of active SKUs unexpectedly, automated deactivation is halted to prevent catalog blackouts.

---

## 🔒 Data Privacy, GDPR & Security Hardening

### GDPR Article 9 Data Minimization (Finding U-21)
In strict compliance with EU GDPR data minimization guidelines:
- **Zero Sensitive Body Data**: The backend strictly prohibits and drops all sensitive body measurements (`height_cm`, `weight_kg`, `chest`, `waist`, `hip`).
- **Zero Ethnic Proxies**: Deprecated the 7-step skin-tone hex scale to eliminate Article 9 racial/ethnic origin inference risks.
- **Onboarding Focus**: Personalization strictly uses fashion preferences: look clusters, preferred occasions, price tiers (`price_band`), sizes (`clothing_sizes`), and brand blocklists (`blocked_brands`).

### Security Defenses
- **Anti-SSRF Image Proxy**: Validates image URLs, rejecting loopback, link-local, private RFC 1918 subnets, and cloud metadata endpoints (`169.254.169.254`).
- **Cryptographic 6-Digit OTP**: Constant-time verification (`secrets.compare_digest`), 10-minute validity, and per-account rate limiting.
- **Token Invalidation**: Outstanding JWT tokens are revoked upon password change, reset, or account logout.

---

## ⏱️ Celery Workers & Beat Schedules

The backend runs scheduled background maintenance managed through `celery beat`:

| Job Name | Frequency | Target / Purpose |
|---|---|---|
| `sync-brand-registry-daily` | Daily at 02:00 CET | Syncs approved AWIN & Rakuten DACH merchant registries |
| `sync-awin-feeds-nightly` | Daily at 02:30 CET | Streams EUR product feeds with zero-write delta checks |
| `sync-rakuten-feeds-nightly`| Daily at 03:00 CET | Queries Rakuten product search APIs for live stock |
| `reconcile-affiliate-conversions` | Hourly | Polls affiliate transaction endpoints for approved sales |
| `expire-old-stories-hourly`| Hourly | Deactivates ephemeral 24-hour social stories |
| `purge-old-login-history` | Daily | Purges login IP logs older than 90 days (GDPR retention) |
| `cleanup-old-notifications`| Daily | Deletes user notifications older than 60 days |

---

## 🚀 Local Development & Setup Guide

### 1. Prerequisites
- Python 3.12+
- PostgreSQL 16 with the `pgvector` extension
- Redis 7.0+
- Git

### 2. Environment Configuration
Clone the repository and create your local `.env` file:
```bash
git clone https://github.com/your-org/myclosly.git
cd myclosly
cp .env.example .env
```

Ensure the following core variables are configured in `.env`:
```env
DEBUG=True
SECRET_KEY=your-secure-random-secret-key-at-least-50-chars
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://closly_user:closly_pass@localhost:5432/closly_db
REDIS_URL=redis://localhost:6379/0
USE_REDIS_CACHE=True
MYC_AI_KILLSWITCH=False
OPENAI_API_KEY=sk-...
```

### 3. Virtual Environment & Dependencies
```bash
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Database Migrations & Initial Setup
```bash
# Enable pgvector and run migrations
python manage.py migrate

# Create superuser for Django Unfold Admin
python manage.py createsuperuser

# Collect static assets
python manage.py collectstatic --noinput
```

### 5. Running the Application Stack
In separate terminal windows:

```bash
# 1. Start Daphne ASGI web server
daphne -b 0.0.0.0 -p 8000 Config.asgi:application

# 2. Start Celery worker
celery -A Config worker -l info --concurrency=4

# 3. Start Celery beat scheduler
celery -A Config beat -l info
```

Access the interactive API documentation at:
- **Swagger UI**: [http://localhost:8000/docs/](http://localhost:8000/docs/)
- **ReDoc**: [http://localhost:8000/redoc/](http://localhost:8000/redoc/)
- **Django Unfold Admin**: [http://localhost:8000/admin/](http://localhost:8000/admin/)

---

<br><br>
Built with passion by [Arif](https://www.linkedin.com/in/aru01/) 🖤💻
