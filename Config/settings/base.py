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

raw_allowed_hosts = config("ALLOWED_HOSTS", default="*")
ALLOWED_HOSTS = [
    h.strip().replace("https://", "").replace("http://", "").split("/")[0]
    for h in raw_allowed_hosts.split(",")
    if h.strip()
]
for host in [
    "charissa-intuitable-corroboratorily.ngrok-free.dev",
    ".ngrok-free.dev",
    ".ngrok.io",
    "localhost",
    "127.0.0.1",
    "10.0.2.2",
    "*",
]:
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

CSRF_TRUSTED_ORIGINS = [
    "https://charissa-intuitable-corroboratorily.ngrok-free.dev",
    "https://*.ngrok-free.dev",
    "https://*.ngrok.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://10.0.2.2:8000",
]

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
    "users.middleware.TranslationMiddleware",
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
DB_ENGINE = config("DB_ENGINE", default="django.db.backends.sqlite3")
DB_NAME = config("DB_NAME", default=None)

if "postgresql" in DB_ENGINE and DB_NAME:
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
            "ENGINE": "django.db.backends.postgresql",
            "NAME": DB_NAME,
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": db_host,
            "PORT": config("DB_PORT", default="5432"),
            "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=600, cast=int),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Cache Configuration
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
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email Configuration
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER)

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

# Reverse Proxy SSL Headers
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
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
