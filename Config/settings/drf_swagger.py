from datetime import timedelta
from decouple import config
from .base import SECRET_KEY

# Django REST Framework Configuration
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "Config.exceptions.custom_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "users.authentication.FirebaseAuthentication",
    ),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
        "user": "300/min",
        "login": "10/120s",
        "otp_verify": "5/120s",
        "otp_resend": "3/120s",
        "password_reset": "5/120s",
        "ai_scan": "15/min",
        "ai_scan_anon": "3/min",
    },
}

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = config("CORS_ALLOW_ALL_ORIGINS", default=True, cast=bool)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "https://charissa-intuitable-corroboratorily.ngrok-free.dev",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://10.0.2.2:8000",
]
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "ngrok-skip-browser-warning",
]

# Simple JWT Configuration
SIMPLE_JWT = {
    # Token lifetime
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
    # Token claims
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": None,
    # Token format
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    # Token classes
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    # Sliding tokens
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(hours=1),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=7),
}

# OpenAPI & Swagger Documentation Settings (drf-spectacular)
SPECTACULAR_SETTINGS = {
    'TITLE': 'Closly API Ecosystem',
    'DESCRIPTION': (
        'Comprehensive OpenAPI 3.0 specification for Closly - Intelligent Digital Wardrobe, '
        'Fashion Social Network, AI Stylist & Affiliate E-Commerce Platform.\n\n'
        '### Authentication\n'
        'Most endpoints require a JWT Bearer Token in the `Authorization` header:\n'
        '```\n'
        'Authorization: Bearer <your_access_token>\n'
        '```'
    ),
    'VERSION': '2.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': r'/api/',
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': False,
        'filter': True,
        'docExpansion': 'none',
        'defaultModelsExpandDepth': 1,
        'defaultModelExpandDepth': 1,
        'displayRequestDuration': True,
        'syntaxHighlight.theme': 'monokai',
        'showExtensions': True,
        'showCommonExtensions': True,
        'tryItOutEnabled': True,
    },
    'REDOC_UI_SETTINGS': {
        'theme': {
            'colors': {
                'primary': {
                    'main': '#6366F1',
                }
            }
        }
    },
    'TAGS': [
        {
            'name': 'Authentication & Security',
            'description': 'User signup, login, Firebase phone/social auth, OTP verification, and JWT token rotation.',
        },
        {
            'name': 'User Profile & Preferences',
            'description': 'User profile management, styling preferences, language settings, and public profile sharing.',
        },
        {
            'name': 'Account Privacy & GDPR',
            'description': 'GDPR compliant account deletion and profile data erasure requests with email confirmation tokens.',
        },
        {
            'name': 'Closet & Digital Wardrobe',
            'description': 'Digital closet inventory, clothing item cataloging, category tagging, and wear tracking.',
        },
        {
            'name': 'AI Wardrobe Scanner & Vision',
            'description': 'AI-driven computer vision scanning, dominant color extraction, wardrobe audit, and score analytics.',
        },
        {
            'name': 'Outfits & Looks',
            'description': 'Daily outfit creation, lookbook items, calendar styling, outfit likes, and today weather recommendations.',
        },
        {
            'name': 'Social Feed & Network',
            'description': 'Public & following newsfeeds, user discovery, explore grid, and follower/following relationship graphs.',
        },
        {
            'name': 'Stories & Ephemeral Moments',
            'description': '24-hour ephemeral stories, user story rings, story view logging, reactions, and story replies.',
        },
        {
            'name': 'Direct Messaging & Chat',
            'description': 'Real-time 1-on-1 direct conversations, chat history, unread counters, and instant message dispatch.',
        },
        {
            'name': 'Affiliate Products & Scraping',
            'description': 'Monetized affiliate product discovery, For-You recommendations, click tracking, brands, and saved wishlists.',
        },
        {
            'name': 'Rewards & Gamification',
            'description': 'Closly points balance, milestone rewards, points history, and verified purchase points claims.',
        },
        {
            'name': 'User Notifications',
            'description': 'User in-app notifications, unread notification badges, and notification status management.',
        },
        {
            'name': 'Legal & Compliance',
            'description': 'Privacy policy, terms of service, support portal, and account deletion web forms.',
        },
        {
            'name': 'System Gateway & Heartbeat',
            'description': 'API root directory, system health check (PostgreSQL + Redis), uptime ping heartbeat, and Postman specs.',
        },
    ],
}
