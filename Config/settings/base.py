from pathlib import Path
import os
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Security
SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-ah+qh6%9#=jnm-vw(y9=u3wf5#(30$w%=7#g8xz*r^m&+&l^4z"
)
DEBUG = config("DEBUG", default=True, cast=bool)

raw_allowed_hosts = config("ALLOWED_HOSTS", default="api.myclosly.com,localhost,127.0.0.1,10.0.2.2")
ALLOWED_HOSTS = [
    h.strip().replace("https://", "").replace("http://", "").split("/")[0]
    for h in raw_allowed_hosts.split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    "https://api.myclosly.com",
    "https://*.myclosly.com",
    "http://api.myclosly.com",
    "http://188.34.176.78",
    "http://188.34.176.78:8000",
    "https://charissa-intuitable-corroboratorily.ngrok-free.dev",
    "https://*.ngrok-free.dev",
    "https://*.ngrok.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://10.0.2.2:8000",
]
raw_csrf_origins = config("CSRF_TRUSTED_ORIGINS", default="")
for origin in raw_csrf_origins.split(","):
    origin = origin.strip()
    if origin and origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

# Application definition
INSTALLED_APPS = [
    "daphne",
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party apps
    "channels",
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    # custom apps
    "users.apps.UsersConfig",
    "legal_pages.apps.LegalPagesConfig",
    "affiliate.apps.AffiliateConfig",
    "closet.apps.ClosetConfig",
    "social.apps.SocialConfig",
    "notifications.apps.NotificationsConfig",
    "rewards.apps.RewardsConfig",
]

AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "users.middleware.UserActivityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

INTERNAL_IPS = [
    "127.0.0.1",
]

ROOT_URLCONF = "Config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "Config.wsgi.application"
ASGI_APPLICATION = "Config.asgi.application"

# Database
DB_ENGINE = config("DB_ENGINE", default="django.db.backends.postgresql")
DB_NAME = config("DB_NAME", default="Closly")

db_host = config("DB_HOST", default="localhost")
if os.path.exists("/.dockerenv"):
    import socket

    if db_host in ("localhost", "127.0.0.1"):
        db_host = "host.docker.internal"
    elif db_host == "db":
        try:
            socket.gethostbyname("db")
        except Exception:
            db_host = "host.docker.internal"

DATABASES = {
    "default": {
        "ENGINE": DB_ENGINE,
        "NAME": DB_NAME,
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": db_host,
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=600, cast=int),
    }
}

# Cache Configuration
USE_REDIS_CACHE = config("USE_REDIS_CACHE", default=False, cast=bool)
if USE_REDIS_CACHE:
    redis_cache_host = config("REDIS_HOST", default="127.0.0.1")
    redis_cache_port = config("REDIS_PORT", default="6379")
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": f"redis://{redis_cache_host}:{redis_cache_port}/1",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "closly-fast-cache",
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static & Media files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Optional Cloud Object Storage (AWS S3 / Cloudflare R2 / Hetzner Storage Box)
USE_S3_STORAGE = config("USE_S3_STORAGE", default=False, cast=bool)

if USE_S3_STORAGE:
    if "storages" not in INSTALLED_APPS:
        INSTALLED_APPS.append("storages")

    AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
    AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="")
    AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME", default="eu-central-1")
    AWS_S3_ENDPOINT_URL = config("AWS_S3_ENDPOINT_URL", default=None)  # Cloudflare R2 / Hetzner / MinIO
    AWS_S3_CUSTOM_DOMAIN = config("AWS_S3_CUSTOM_DOMAIN", default=None)  # e.g., cdn.myclosly.com
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = config("AWS_QUERYSTRING_AUTH", default=False, cast=bool)
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }

    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
    elif AWS_S3_ENDPOINT_URL and AWS_STORAGE_BUCKET_NAME:
        MEDIA_URL = f"{AWS_S3_ENDPOINT_URL.rstrip('/')}/{AWS_STORAGE_BUCKET_NAME}/media/"
    elif AWS_STORAGE_BUCKET_NAME:
        MEDIA_URL = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/media/"
    else:
        MEDIA_URL = "/media/"

    MEDIA_ROOT = BASE_DIR / "media"

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "location": "media",
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }
else:
    # Standard local file storage (Default for Local Dev & Test Server)
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"
    STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email Configuration
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER)
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=10, cast=int)

# ==============================================================================
# MYC_* Centralized Configuration & Brand Architecture (Audit U-10, U-14, U-32)
# ==============================================================================
MYC_BRAND_NAME = config("MYC_BRAND_NAME", default="Closly")
MYC_COMPANY_NAME = config("MYC_COMPANY_NAME", default="Closly Technologies GmbH")
MYC_SUPPORT_EMAIL = config("MYC_SUPPORT_EMAIL", default="support@myclosly.com")
MYC_PRIVACY_EMAIL = config("MYC_PRIVACY_EMAIL", default="privacy@myclosly.com")
MYC_DEEP_LINK_SCHEME = config("MYC_DEEP_LINK_SCHEME", default="closly")
MYC_PUBLIC_BASE_URL = config("MYC_PUBLIC_BASE_URL", default="https://myclosly.com")
MYC_DEFAULT_LANGUAGE = config("MYC_DEFAULT_LANGUAGE", default="de")
MYC_REGISTRATION_MODE = config("MYC_REGISTRATION_MODE", default="open")  # 'open' or 'invite'
MYC_INVITE_BYPASS_CODES = [
    c.strip().upper()
    for c in config("MYC_INVITE_BYPASS_CODES", default="TESTFLIGHT-REVIEW,APPLE-REVIEW").split(",")
    if c.strip()
]
MYC_MIN_AGE = config("MYC_MIN_AGE", default=16, cast=int)
MYC_MAX_UPLOAD_MB = config("MYC_MAX_UPLOAD_MB", default=10, cast=int)
MYC_REFERRAL_MONTHLY_CAP = config("MYC_REFERRAL_MONTHLY_CAP", default=10, cast=int)
MYC_REFERRAL_POINTS = config("MYC_REFERRAL_POINTS", default=200, cast=int)
MYC_LOGIN_HISTORY_RETENTION_DAYS = config("MYC_LOGIN_HISTORY_RETENTION_DAYS", default=90, cast=int)
MYC_GDPR_JOB_RETENTION_DAYS = config("MYC_GDPR_JOB_RETENTION_DAYS", default=30, cast=int)

# Production Cookie & HSTS Security (Audit U-33)
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    CSRF_COOKIE_SAMESITE = 'Strict'
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Production SECRET_KEY verification (Audit U-36)
if not DEBUG:
    if not SECRET_KEY or SECRET_KEY.startswith("django-insecure-"):
        import django.core.exceptions
        raise django.core.exceptions.ImproperlyConfigured(
            "CRITICAL SECURITY FAILURE: SECRET_KEY must be securely defined in environment when DEBUG=False!"
        )

# Firebase Configuration
FIREBASE_CREDENTIALS_PATH = config(
    "FIREBASE_CREDENTIALS_PATH", default="firebase-credentials.json"
)

# Affiliate Configurations
AWIN_FEED_URL = config("AWIN_FEED_URL", default=None)
AWIN_PUBLISHER_ID = config("AWIN_PUBLISHER_ID", default="2612792")

RAKUTEN_TOKEN = config("RAKUTEN_TOKEN", default=None)
RAKUTEN_REFRESH_TOKEN = config("RAKUTEN_REFRESH_TOKEN", default=None)
RAKUTEN_CLIENT_ID = config("RAKUTEN_CLIENT_ID", default=None)
RAKUTEN_CLIENT_SECRET = config("RAKUTEN_CLIENT_SECRET", default=None)
RAKUTEN_PUBLISHER_SID = config("RAKUTEN_PUBLISHER_SID", default="4674442")

# ==============================================================================
# Catalog Feed, Attribution, & Discovery Engine Configurations (02_catalog_feed)
# ==============================================================================
MYC_INGEST_CURRENCIES = [
    c.strip().upper()
    for c in config("MYC_INGEST_CURRENCIES", default="EUR").split(",")
    if c.strip()
]
MYC_FEED_CURRENCIES = [
    c.strip().upper()
    for c in config("MYC_FEED_CURRENCIES", default="EUR").split(",")
    if c.strip()
]
MYC_FEED_CANDIDATES = config("MYC_FEED_CANDIDATES", default=600, cast=int)
MYC_FEED_CACHE_TTL = config("MYC_FEED_CACHE_TTL", default=93600, cast=int)  # 26 hours (93,600s)
MYC_CLICK_THROTTLE_RATE = config("MYC_CLICK_THROTTLE_RATE", default="30/h")
MYC_EVENT_BATCH_MAX_SIZE = config("MYC_EVENT_BATCH_MAX_SIZE", default=200, cast=int)
MYC_SYNC_ZERO_DELTA_THRESHOLD = config("MYC_SYNC_ZERO_DELTA_THRESHOLD", default=0.5, cast=float)
MYC_SYNC_MISS_COUNT_THRESHOLD = config("MYC_SYNC_MISS_COUNT_THRESHOLD", default=2, cast=int)
MYC_FEED_MAX_SAME_BRAND_WINDOW_20 = config("MYC_FEED_MAX_SAME_BRAND_WINDOW_20", default=3, cast=int)
MYC_FEED_MAX_BRAND_SHARE_WINDOW_100 = config("MYC_FEED_MAX_BRAND_SHARE_WINDOW_100", default=0.30, cast=float)
MYC_SHOPIFY_REQ_INTERVAL_MS = config("MYC_SHOPIFY_REQ_INTERVAL_MS", default=2000, cast=int)
MYC_BOT_USER_AGENT = config("MYC_BOT_USER_AGENT", default="mycloslybot/1.0 (+https://myclosly.com/bot)")

# Behavioral Recommendation Event Weights (backend-driven, non-LLM)
MYC_EVENT_WEIGHTS = {
    "impression": config("MYC_WEIGHT_IMPRESSION", default=0.1, cast=float),
    "detail_view": config("MYC_WEIGHT_DETAIL_VIEW", default=1.0, cast=float),
    "long_view": config("MYC_WEIGHT_LONG_VIEW", default=2.0, cast=float),
    "like": config("MYC_WEIGHT_LIKE", default=5.0, cast=float),
    "save": config("MYC_WEIGHT_SAVE", default=8.0, cast=float),
    "click_out": config("MYC_WEIGHT_CLICK_OUT", default=3.0, cast=float),
    "purchase": config("MYC_WEIGHT_PURCHASE", default=15.0, cast=float),
    "skip": config("MYC_WEIGHT_SKIP", default=-3.0, cast=float),
}

# Image Asset CDN Replication (Audit CF-18)
MYC_CDN_REPLICATION_ENABLED = config("MYC_CDN_REPLICATION_ENABLED", default=False, cast=bool)
MYC_CDN_BASE_URL = config("MYC_CDN_BASE_URL", default=None)
MYC_IMAGE_DOWNLOAD_TIMEOUT = config("MYC_IMAGE_DOWNLOAD_TIMEOUT", default=10, cast=int)
MYC_IMAGE_MAX_SIZE_BYTES = config("MYC_IMAGE_MAX_SIZE_BYTES", default=10 * 1024 * 1024, cast=int)

# Affiliate Purchase Conversion Linkage (Audit CF-30)
MYC_AWIN_WEBHOOK_SECRET = config("MYC_AWIN_WEBHOOK_SECRET", default="closly-awin-webhook-secret-2026")
MYC_AUTO_AWARD_PURCHASE_POINTS = config("MYC_AUTO_AWARD_PURCHASE_POINTS", default=True, cast=bool)
MYC_PURCHASE_AWARD_POINTS = config("MYC_PURCHASE_AWARD_POINTS", default=200, cast=int)

# Reverse Proxy SSL Headers
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = False
USE_X_FORWARDED_PORT = True

# Base URLs
BACKEND_URL = config("BACKEND_URL", default="")
FORCE_HTTPS_MEDIA_URL = config("FORCE_HTTPS_MEDIA_URL", default=not DEBUG, cast=bool)

# AI Vision Configuration
GEMINI_API_KEY = config("GEMINI_API_KEY", default=None)
LLM_API_KEY = config("LLM_API_KEY", default="")
LLM_BASE_URL = config("LLM_BASE_URL", default=None)
LLM_MODEL = config("LLM_MODEL", default="gpt-4o")
MAX_IMAGE_SIZE_MB = config("MAX_IMAGE_SIZE_MB", default=5, cast=int)
APIFY_API_TOKEN = config("APIFY_API_TOKEN", default="")
APIFY_GOOGLE_ACTOR = config("APIFY_GOOGLE_ACTOR", default="apify/google-search-scraper")
DRESS_ANALYZER_DIR = BASE_DIR / "dress-analyzer-ai"

AI_SCAN_CONCURRENCY_LIMIT = config("AI_SCAN_CONCURRENCY_LIMIT", default=15, cast=int)
AI_SCAN_QUEUE_TIMEOUT = config("AI_SCAN_QUEUE_TIMEOUT", default=35, cast=int)
AI_SCAN_CACHE_TTL = config("AI_SCAN_CACHE_TTL", default=600, cast=int)
