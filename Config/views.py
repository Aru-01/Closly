import time
import os
from datetime import datetime
from django.conf import settings
from django.db import connection
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

START_TIME = time.time()


class ApiRootView(APIView):
    """
    Root Gateway View for Closly Backend.
    - If accessed from a web browser, renders an elegant, dark-themed API dashboard.
    - If accessed via JSON API client, returns structured API metadata and endpoint index.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        accept_header = request.headers.get('Accept', '')
        if 'text/html' in accept_header and not request.query_params.get('format') == 'json':
            return self._render_html_dashboard(request)

        return Response({
            'success': True,
            'service': 'Closly Backend API Gateway',
            'version': '2.0.0',
            'status': 'operational',
            'timestamp': timezone.now().isoformat(),
            'documentation': {
                'swagger_ui': request.build_absolute_uri('/api/docs/'),
                'redoc': request.build_absolute_uri('/api/redoc/'),
                'openapi_schema': request.build_absolute_uri('/api/schema/'),
                'postman_collection': request.build_absolute_uri('/api/docs/postman/'),
            },
            'heartbeat': {
                'health_check': request.build_absolute_uri('/api/health/'),
                'ping': request.build_absolute_uri('/api/health/ping/'),
            },
            'modules': {
                'users_and_auth': request.build_absolute_uri('/api/users/'),
                'digital_closet': request.build_absolute_uri('/api/closet/'),
                'social_stories_chat': request.build_absolute_uri('/api/social/'),
                'affiliate_newsfeed': request.build_absolute_uri('/api/affiliate/'),
                'rewards_and_points': request.build_absolute_uri('/api/rewards/'),
                'notifications': request.build_absolute_uri('/api/notifications/'),
                'legal': request.build_absolute_uri('/api/legal/'),
            },
            'realtime': {
                'websocket_chat': 'ws://' + request.get_host() + '/ws/chat/?token=<JWT_TOKEN>',
            }
        }, status=status.HTTP_200_OK)

    def _render_html_dashboard(self, request):
        uptime_seconds = int(time.time() - START_TIME)
        uptime_str = f"{uptime_seconds // 3600}h {(uptime_seconds % 3600) // 60}m {uptime_seconds % 60}s"
        host = request.get_host()

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Closly API Gateway | Intelligent Fashion Ecosystem</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #0B0F17;
            --bg-card: rgba(21, 28, 44, 0.7);
            --bg-card-hover: rgba(30, 41, 64, 0.85);
            --border-glass: rgba(255, 255, 255, 0.08);
            --border-accent: rgba(99, 102, 241, 0.3);
            --primary: #6366F1;
            --primary-glow: rgba(99, 102, 241, 0.25);
            --emerald: #10B981;
            --text-main: #F8FAFC;
            --text-muted: #94A3B8;
            --font-main: 'Outfit', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background-color: var(--bg-base);
            background-image: 
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.1) 0px, transparent 50%);
            color: var(--text-main);
            font-family: var(--font-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 40px 20px;
        }}
        .container {{
            width: 100%;
            max-width: 1000px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 40px;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: #34D399;
            padding: 6px 16px;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 600;
            letter-spacing: 0.05em;
            margin-bottom: 16px;
            text-transform: uppercase;
        }}
        .badge-dot {{
            width: 8px;
            height: 8px;
            background: #10B981;
            border-radius: 50%;
            box-shadow: 0 0 10px #10B981;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.4; transform: scale(0.8); }}
        }}
        h1 {{
            font-size: 2.8rem;
            font-weight: 700;
            background: linear-gradient(135deg, #FFFFFF 0%, #CBD5E1 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
            letter-spacing: -0.02em;
        }}
        .subtitle {{
            color: var(--text-muted);
            font-size: 1.1rem;
            max-width: 600px;
            margin: 0 auto;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border-glass);
            border-radius: 16px;
            padding: 24px;
            backdrop-filter: blur(12px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            text-decoration: none;
            color: inherit;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}
        .card:hover {{
            background: var(--bg-card-hover);
            border-color: var(--border-accent);
            transform: translateY(-4px);
            box-shadow: 0 12px 30px -10px var(--primary-glow);
        }}
        .card-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
        }}
        .card-icon {{
            font-size: 1.6rem;
            padding: 10px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.05);
        }}
        .card-title {{
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 6px;
        }}
        .card-desc {{
            color: var(--text-muted);
            font-size: 0.92rem;
            line-height: 1.5;
            margin-bottom: 16px;
        }}
        .card-link {{
            font-size: 0.85rem;
            color: var(--primary);
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-family: var(--font-mono);
        }}
        .stats-bar {{
            background: var(--bg-card);
            border: 1px solid var(--border-glass);
            border-radius: 16px;
            padding: 20px 28px;
            display: flex;
            flex-wrap: wrap;
            gap: 24px;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            backdrop-filter: blur(12px);
        }}
        .stat-item {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .stat-label {{
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .stat-value {{
            font-size: 1.1rem;
            font-weight: 600;
            font-family: var(--font-mono);
            color: #E2E8F0;
        }}
        .interactive-ping {{
            background: linear-gradient(135deg, rgba(99, 102, 241, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%);
            border: 1px solid var(--border-accent);
            border-radius: 16px;
            padding: 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            backdrop-filter: blur(12px);
            margin-bottom: 30px;
        }}
        .ping-info h3 {{
            font-size: 1.1rem;
            margin-bottom: 4px;
        }}
        .ping-info p {{
            font-size: 0.88rem;
            color: var(--text-muted);
        }}
        .btn {{
            background: var(--primary);
            color: #FFFFFF;
            border: none;
            padding: 12px 24px;
            border-radius: 10px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-family: var(--font-main);
            white-space: nowrap;
        }}
        .btn:hover {{
            opacity: 0.9;
            transform: scale(1.02);
            box-shadow: 0 4px 15px var(--primary-glow);
        }}
        .footer {{
            text-align: center;
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="badge">
                <span class="badge-dot"></span>
                API Gateway Operational
            </div>
            <h1>Closly Enterprise API</h1>
            <p class="subtitle">High-performance fashion social network, digital wardrobe, AI styling and affiliate monetization platform.</p>
        </div>

        <div class="stats-bar">
            <div class="stat-item">
                <span class="stat-label">Server Engine</span>
                <span class="stat-value">Daphne ASGI (HTTP/WS)</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Database</span>
                <span class="stat-value">PostgreSQL 16</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Broker / Layer</span>
                <span class="stat-value">Redis 7 Alpine</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">API Version</span>
                <span class="stat-value">v2.0.0</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Uptime</span>
                <span class="stat-value" id="uptime">{uptime_str}</span>
            </div>
        </div>

        <div class="interactive-ping">
            <div class="ping-info">
                <h3>Live Health Heartbeat</h3>
                <p id="ping-status">Ping endpoint /api/health/ping/ to measure live response latency and keep the server warm.</p>
            </div>
            <button class="btn" id="ping-btn" onclick="testPing()">⚡ Test Heartbeat Ping</button>
        </div>

        <div class="grid">
            <a href="/api/docs/" class="card">
                <div>
                    <div class="card-header">
                        <span class="card-icon">⚡</span>
                        <span class="card-link">Swagger UI &rarr;</span>
                    </div>
                    <div class="card-title">Interactive Swagger UI</div>
                    <div class="card-desc">Interactive, self-documenting OpenAPI 3.0 playground to test every endpoint with JWT authentication directly in your browser.</div>
                </div>
                <div class="card-link">GET /api/docs/</div>
            </a>

            <a href="/api/redoc/" class="card">
                <div>
                    <div class="card-header">
                        <span class="card-icon">📖</span>
                        <span class="card-link">Redoc &rarr;</span>
                    </div>
                    <div class="card-title">Redoc API Specification</div>
                    <div class="card-desc">Clean, responsive documentation reference designed for frontend and mobile engineers with rich schema models and payloads.</div>
                </div>
                <div class="card-link">GET /api/redoc/</div>
            </a>

            <a href="/api/health/" class="card">
                <div>
                    <div class="card-header">
                        <span class="card-icon">💓</span>
                        <span class="card-link">Health API &rarr;</span>
                    </div>
                    <div class="card-title">System Health Check</div>
                    <div class="card-desc">Real-time status monitor checking PostgreSQL database connections, Redis channel broker, and system memory state.</div>
                </div>
                <div class="card-link">GET /api/health/</div>
            </a>

            <a href="/api/docs/postman/" class="card">
                <div>
                    <div class="card-header">
                        <span class="card-icon">📦</span>
                        <span class="card-link">Download JSON &rarr;</span>
                    </div>
                    <div class="card-title">Postman Collection</div>
                    <div class="card-desc">Download the updated, production-ready Postman collection with all 72 endpoints, environment presets, and sample requests.</div>
                </div>
                <div class="card-link">GET /api/docs/postman/</div>
            </a>
        </div>

        <div class="footer">
            &copy; {datetime.now().year} Closly Technologies Inc. All rights reserved. &bull; Enterprise Fashion Intelligence
        </div>
    </div>

    <script>
        async function testPing() {{
            const btn = document.getElementById('ping-btn');
            const statusText = document.getElementById('ping-status');
            btn.disabled = true;
            btn.innerText = 'Pinging...';
            const start = performance.now();
            try {{
                const res = await fetch('/api/health/ping/');
                const latency = (performance.now() - start).toFixed(1);
                const data = await res.json();
                statusText.innerHTML = '<span style="color: #10B981; font-weight: 600;">PONG! 200 OK</span> &bull; Latency: ' + latency + 'ms &bull; Database & Cache Active';
            }} catch (e) {{
                statusText.innerHTML = '<span style="color: #EF4444; font-weight: 600;">Ping failed: ' + e.message + '</span>';
            }} finally {{
                btn.disabled = false;
                btn.innerText = '⚡ Test Heartbeat Ping';
            }}
        }}
    </script>
</body>
</html>"""
        return HttpResponse(html, content_type='text/html')


class HealthCheckView(APIView):
    """
    Production health check and heartbeat endpoint.
    - Tests database connection
    - Tests Redis connectivity
    - Returns HTTP 200 if healthy, HTTP 503 if critical service is down
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        start_time = time.time()
        health_status = {
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'service': 'closly_backend',
            'version': '2.0.0',
            'checks': {},
        }
        is_healthy = True

        # 1. Database Check
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()
            health_status['checks']['database'] = {
                'status': 'up',
                'engine': settings.DATABASES['default']['ENGINE'].split('.')[-1],
            }
        except Exception as e:
            is_healthy = False
            health_status['checks']['database'] = {
                'status': 'down',
                'error': str(e),
            }

        # 2. Redis / Channel Layer Check
        try:
            redis_host = getattr(settings, 'REDIS_HOST', '127.0.0.1')
            redis_port = getattr(settings, 'REDIS_PORT', 6379)
            use_in_memory = getattr(settings, 'USE_IN_MEMORY_CHANNELS', False)
            if use_in_memory:
                health_status['checks']['cache_broker'] = {
                    'status': 'up',
                    'backend': 'InMemoryChannelLayer',
                }
            else:
                import redis
                r = redis.Redis(host=redis_host, port=int(redis_port), socket_timeout=2)
                r.ping()
                health_status['checks']['cache_broker'] = {
                    'status': 'up',
                    'backend': 'redis',
                    'host': f"{redis_host}:{redis_port}",
                }
        except Exception as e:
            # Non-critical warning if broker is offline during local test
            health_status['checks']['cache_broker'] = {
                'status': 'degraded',
                'warning': str(e),
            }

        latency_ms = round((time.time() - start_time) * 1000, 2)
        health_status['latency_ms'] = latency_ms

        http_status = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        health_status['status'] = 'healthy' if is_healthy else 'unhealthy'

        return Response(health_status, status=http_status)


class PingHeartbeatView(APIView):
    """
    Lightweight, high-frequency ping endpoint (~1ms response time).
    Use this endpoint in external uptime monitors (e.g. UptimeRobot, Render keepalive,
    AWS Route53, BetterUptime) to keep the app and container warm and prevent cold starts.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return JsonResponse({
            'status': 'pong',
            'time': timezone.now().isoformat(),
            'message': 'Closly server is warm and operational.'
        }, status=200)


class PostmanCollectionDownloadView(APIView):
    """
    Directly serves the latest Postman collection JSON file for developers.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        postman_file = os.path.join(settings.BASE_DIR, 'MyClosly_API_Postman_Collection.json')
        if os.path.exists(postman_file):
            response = FileResponse(
                open(postman_file, 'rb'),
                content_type='application/json'
            )
            response['Content-Disposition'] = 'attachment; filename="MyClosly_API_Postman_Collection.json"'
            return response
        raise Http404("Postman collection file not found.")
