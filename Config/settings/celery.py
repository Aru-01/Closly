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
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS = True

CELERY_BEAT_SCHEDULE = {
    "expire-24h-stories-hourly": {
        "task": "social.tasks.expire_old_stories_task",
        "schedule": 3600.0,  # runs every hour to clean up 24-hour stories
    },
    "sync-awin-feeds-5h": {
        "task": "affiliate.tasks.sync_awin_feeds_task",
        "schedule": 18000.0,  # runs every 5 hours (18,000s) to keep Awin inventory fresh
    },
    "sync-rakuten-feeds-5h": {
        "task": "affiliate.tasks.sync_rakuten_feeds_task",
        "schedule": 18000.0,  # runs every 5 hours (18,000s) to keep Rakuten inventory fresh
    },
}
