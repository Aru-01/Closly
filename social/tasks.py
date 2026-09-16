from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(name='social.tasks.expire_old_stories_task')
def expire_old_stories_task():
    """
    Periodic task to mark stories older than 24 hours (or past expires_at) as inactive.
    Runs hourly via Celery Beat.
    """
    from .models import Story
    now = timezone.now()
    count = Story.objects.filter(is_active=True, expires_at__lte=now).update(is_active=False)
    logger.info(f"Story cleanup: {count} stories deactivated.")
    return f"{count} expired stories deactivated."


@shared_task(name='social.tasks.heartbeat_self_ping_task')
def heartbeat_self_ping_task():
    """
    Automated self-ping task executed by Celery Beat every 5 minutes.
    - Pings PostgreSQL database to keep connection pools active and warm.
    - Pings Redis cache/broker to verify connectivity.
    - Performs an internal HTTP GET request to /api/health/ping/ to keep web workers active.
    - Prevents cold starts and verifies end-to-end responsiveness.
    """
    import urllib.request
    from django.db import connection
    from django.conf import settings

    results = {
        'timestamp': timezone.now().isoformat(),
        'database': 'unknown',
        'redis': 'unknown',
        'http_ping': 'skipped',
    }

    # 1. Database Ping
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()
        results['database'] = 'OK'
    except Exception as e:
        results['database'] = f'ERROR: {e}'
        logger.error(f"[Heartbeat] Database ping failed: {e}")

    # 2. Redis Ping
    try:
        import redis
        redis_host = getattr(settings, 'REDIS_HOST', '127.0.0.1')
        redis_port = int(getattr(settings, 'REDIS_PORT', 6379))
        r = redis.Redis(host=redis_host, port=redis_port, socket_timeout=2)
        if r.ping():
            results['redis'] = 'OK'
    except Exception as e:
        results['redis'] = f'ERROR: {e}'
        logger.warning(f"[Heartbeat] Redis ping failed: {e}")

    # 3. HTTP Web Server Ping (Keeps web dyno/Daphne responsive)
    try:
        target_url = "http://127.0.0.1:8000/api/health/ping/"
        req = urllib.request.Request(
            target_url,
            headers={'User-Agent': 'Closly-Celery-Heartbeat/1.0', 'ngrok-skip-browser-warning': 'true'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            results['http_ping'] = f'HTTP {response.status}'
    except Exception as e:
        # If internal 127.0.0.1 failed (e.g. inside docker container where web is 'web:8000'), try web host
        try:
            target_url = "http://web:8000/api/health/ping/"
            req = urllib.request.Request(
                target_url,
                headers={'User-Agent': 'Closly-Celery-Heartbeat/1.0', 'ngrok-skip-browser-warning': 'true'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                results['http_ping'] = f'HTTP {response.status} (via docker network)'
        except Exception as inner_e:
            results['http_ping'] = f'HTTP ping unreachable ({e})'

    logger.info(f"[System Heartbeat Ping] Status: {results}")
    return results

