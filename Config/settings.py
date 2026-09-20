from pathlib import Path
import os
from decouple import config
from datetime import timedelta


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-ah+qh6%9#=jnm-vw(y9=u3wf5#(30$w%=7#g8xz*r^m&+&l^4z'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

raw_allowed_hosts = config('ALLOWED_HOSTS', default='*')
ALLOWED_HOSTS = [
    h.strip().replace('https://', '').replace('http://', '').split('/')[0]
    for h in raw_allowed_hosts.split(',') if h.strip()
]
for host in [
    'charissa-intuitable-corroboratorily.ngrok-free.dev',
    '.ngrok-free.dev',
    '.ngrok.io',
    'localhost',
    '127.0.0.1',
    '10.0.2.2',
    '*',
]:
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

CSRF_TRUSTED_ORIGINS = [
    'https://charissa-intuitable-corroboratorily.ngrok-free.dev',
    'https://*.ngrok-free.dev',
    'https://*.ngrok.io',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://10.0.2.2:8000',
]


# Application definition

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third party apps
    'channels',
    'rest_framework',
    'drf_spectacular',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    # custom apps
    'users.apps.UsersConfig',
    'legal_pages.apps.LegalPagesConfig',
    'affiliate.apps.AffiliateConfig',
    'closet.apps.ClosetConfig',
    'social.apps.SocialConfig',
    'notifications.apps.NotificationsConfig',
    'rewards.apps.RewardsConfig',
]

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER': 'Config.exceptions.custom_exception_handler',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'users.authentication.FirebaseAuthentication',
    ),
}

AUTH_USER_MODEL = 'users.User'

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'users.middleware.TranslationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = config('CORS_ALLOW_ALL_ORIGINS', default=True, cast=bool)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    'https://charissa-intuitable-corroboratorily.ngrok-free.dev',
    'http://localhost:3000',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://10.0.2.2:8000',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'ngrok-skip-browser-warning',
]

ROOT_URLCONF = 'Config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'Config.wsgi.application'
ASGI_APPLICATION = 'Config.asgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DB_ENGINE = config('DB_ENGINE', default='django.db.backends.sqlite3')
DB_NAME = config('DB_NAME', default=None)

if 'postgresql' in DB_ENGINE and DB_NAME:
    db_host = config('DB_HOST', default='localhost')
    if os.path.exists('/.dockerenv'):
        import socket
        if db_host in ('localhost', '127.0.0.1'):
            db_host = 'host.docker.internal'
        elif db_host == 'db':
            try:
                socket.gethostbyname('db')
            except Exception:
                db_host = 'host.docker.internal'

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': DB_NAME,
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': db_host,
            'PORT': config('DB_PORT', default='5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# Media files (Uploaded images)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Simple JWT Configuration
SIMPLE_JWT = {
    # Token lifetime
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'UPDATE_LAST_LOGIN': True,
    
    # Token claims
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    
    # Token format
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    
    # Token classes
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    
    # Sliding tokens
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(hours=1),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=7),
}

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

# Firebase Configuration
FIREBASE_CREDENTIALS_PATH = config('FIREBASE_CREDENTIALS_PATH', default='firebase-credentials.json')

# Awin Affiliate Configuration
# Awin Affiliate Configuration
AWIN_FEED_URL      = config('AWIN_FEED_URL', default=None)
AWIN_PUBLISHER_ID  = config('AWIN_PUBLISHER_ID', default='2612792')

# Rakuten Advertising Configuration
RAKUTEN_TOKEN         = config('RAKUTEN_TOKEN', default=None)
RAKUTEN_REFRESH_TOKEN = config('RAKUTEN_REFRESH_TOKEN', default=None)
RAKUTEN_CLIENT_ID     = config('RAKUTEN_CLIENT_ID', default=None)
RAKUTEN_CLIENT_SECRET = config('RAKUTEN_CLIENT_SECRET', default=None)
RAKUTEN_PUBLISHER_SID = config('RAKUTEN_PUBLISHER_SID', default='4674442')

# Reverse Proxy SSL Headers (ngrok, Nginx, Cloudflare, etc.)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# Media & Base URL Configuration
BACKEND_URL = config('BACKEND_URL', default='')
FORCE_HTTPS_MEDIA_URL = config('FORCE_HTTPS_MEDIA_URL', default=True, cast=bool)

# AI Vision Configuration (Optional Google Gemini Vision API Key)
GEMINI_API_KEY = config('GEMINI_API_KEY', default=None)

# Redis Configuration (Channels & Celery)
REDIS_HOST = config('REDIS_HOST', default='127.0.0.1')
REDIS_PORT = config('REDIS_PORT', default='6379')

# Channels Redis Layer (with InMemory fallback for testing / offline dev)
USE_IN_MEMORY_CHANNELS = config('USE_IN_MEMORY_CHANNELS', default=False, cast=bool)

if USE_IN_MEMORY_CHANNELS:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [{
                    'address': f'redis://{REDIS_HOST}:{REDIS_PORT}',
                    'socket_timeout': 30,
                    'socket_connect_timeout': 10,
                }],
            },
        },
    }

# Celery Configuration
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default=f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default=f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True
CELERY_BEAT_SCHEDULE = {
    'expire-24h-stories-hourly': {
        'task': 'social.tasks.expire_old_stories_task',
        'schedule': 3600.0,  # runs every hour to clean up 24-hour stories
    },
    'sync-awin-feeds-daily': {
        'task': 'affiliate.tasks.sync_awin_feeds_task',
        'schedule': 86400.0,  # runs once every 24 hours to sync new affiliate inventory
    },
}

# Swagger / OpenAPI 3.0 Documentation (drf-spectacular)
SPECTACULAR_SETTINGS = {
    'TITLE': 'Closly Backend API',
    'DESCRIPTION': 'Official production REST & WebSocket API documentation for Closly fashion & digital closet ecosystem.',
    'VERSION': '2.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': False,
        'defaultModelsExpandDepth': -1,
        'defaultModelExpandDepth': 1,
        'docExpansion': 'none',
        'filter': True,
    },
    'REDOC_UI_SETTINGS': {
        'expandResponses': '200,201',
    },
}

# OpenAI & AI Dress Analyzer Configuration (AI Team Integration)
LLM_API_KEY = config('LLM_API_KEY', default='')
LLM_BASE_URL = config('LLM_BASE_URL', default=None)
LLM_MODEL = config('LLM_MODEL', default='gpt-4o')
MAX_IMAGE_SIZE_MB = config('MAX_IMAGE_SIZE_MB', default=5, cast=int)
APIFY_API_TOKEN = config('APIFY_API_TOKEN', default='')
APIFY_GOOGLE_ACTOR = config('APIFY_GOOGLE_ACTOR', default='apify/google-search-scraper')
DRESS_ANALYZER_DIR = BASE_DIR / 'dress-analyzer-ai'

# AI Scan Concurrency Gate & Performance Caching
AI_SCAN_CONCURRENCY_LIMIT = config('AI_SCAN_CONCURRENCY_LIMIT', default=15, cast=int)
AI_SCAN_QUEUE_TIMEOUT = config('AI_SCAN_QUEUE_TIMEOUT', default=35, cast=int)
AI_SCAN_CACHE_TTL = config('AI_SCAN_CACHE_TTL', default=600, cast=int)


