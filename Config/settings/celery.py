import sys
from decouple import config
from .base import TIME_ZONE

# Redis Configuration (Channels & Celery)
REDIS_HOST = config("REDIS_HOST", default="127.0.0.1")
REDIS_PORT = config("REDIS_PORT", default="6379")

# Channels Redis Layer (with InMemory fallback for testing / offline dev)
USE_IN_MEMORY_CHANNELS = config("USE_IN_MEMORY_CHANNELS", default=False, cast=bool)

if USE_IN_MEMORY_CHANNELS:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [
                    {
                        "address": f"redis://{REDIS_HOST}:{REDIS_PORT}",
                        "socket_timeout": 30,
                        "socket_connect_timeout": 10,
                    }
                ],
            },
        },
    }

# Celery Configuration
CELERY_BROKER_URL = config(
    "CELERY_BROKER_URL", default=f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
)
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND", default=f"redis://{REDIS_HOST}:{REDIS_PORT}/0"
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
from celery.schedules import crontab
CELERY_TIMEZONE = config("CELERY_TIMEZONE", default="Europe/Berlin")
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True
CELERY_TASK_ALWAYS_EAGER = config("CELERY_TASK_ALWAYS_EAGER", default=("test" in sys.argv), cast=bool)
CELERY_TASK_EAGER_PROPAGATES = True

CELERY_BEAT_SCHEDULE = {
    "expire-24h-stories-hourly": {
        "task": "social.tasks.expire_old_stories_task",
        "schedule": 3600.0,  # runs every hour to clean up 24-hour stories
    },
    "sync-awin-feeds-daily": {
        "task": "affiliate.tasks.sync_awin_feeds_task",
        "schedule": crontab(hour=2, minute=0),  # 02:00 Berlin time
    },
    "sync-rakuten-feeds-daily": {
        "task": "affiliate.tasks.sync_rakuten_feeds_task",
        "schedule": crontab(hour=2, minute=30),  # 02:30 Berlin time
    },
    "aggregate-feed-impressions-daily": {
        "task": "affiliate.tasks.aggregate_feed_impressions_daily_task",
        "schedule": crontab(hour=3, minute=0),  # 03:00 Berlin time
    },
    "sync-shopify-feeds-daily": {
        "task": "affiliate.tasks.sync_shopify_feeds_task",
        "schedule": crontab(hour=3, minute=30),  # 03:30 Berlin time
    },
    "cleanup-old-notifications-daily": {
        "task": "notifications.tasks.cleanup_old_notifications_task",
        "schedule": 86400.0,  # runs once daily (86,400s) to purge notifications older than 60 days
    },
    "flush-expired-tokens-daily": {
        "task": "users.tasks.flush_expired_tokens_task",
        "schedule": 86400.0,  # runs once daily (86,400s) to purge expired JWT blacklist/outstanding tokens
    },
    "purge-old-login-history-daily": {
        "task": "users.tasks.purge_old_login_history_task",
        "schedule": 86400.0,  # runs once daily (86,400s) to purge login history older than 90 days (U-25)
    },
    "purge-completed-gdpr-jobs-daily": {
        "task": "users.tasks.purge_completed_gdpr_jobs_task",
        "schedule": 86400.0,  # runs once daily (86,400s) to purge completed GDPR deletion jobs older than 30 days
    },
}
