import time
import os
from django.conf import settings
from django.db import connection
from django.shortcuts import render
from django.http import JsonResponse, FileResponse, Http404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiResponse

START_TIME = time.time()


@extend_schema(
    tags=["System Gateway & Heartbeat"],
    summary="API Root Gateway Dashboard",
    description="Returns interactive HTML gateway dashboard in browser, or JSON API directory if requested via API client.",
    responses={
        200: OpenApiResponse(description="API Gateway Directory and service index metadata")
    },
)
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
                'swagger_ui': request.build_absolute_uri('/docs/'),
                'swagger_ui_alt': request.build_absolute_uri('/api/docs/'),
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
        return render(request, 'api_dashboard.html', {
            'uptime_str': uptime_str,
            'current_year': timezone.now().year,
        })


@extend_schema(
    tags=["System Gateway & Heartbeat"],
    summary="System Health Check",
    description="Tests PostgreSQL database and Redis connectivity and returns operational health status.",
    responses={
        200: OpenApiResponse(description="All core subsystems are healthy"),
        503: OpenApiResponse(description="One or more critical subsystems are degraded or down"),
    },
)
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
            health_status['checks']['cache_broker'] = {
                'status': 'degraded',
                'warning': str(e),
            }

        latency_ms = round((time.time() - start_time) * 1000, 2)
        health_status['latency_ms'] = latency_ms

        http_status = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        health_status['status'] = 'healthy' if is_healthy else 'unhealthy'

        return Response(health_status, status=http_status)


@extend_schema(
    tags=["System Gateway & Heartbeat"],
    summary="Uptime Ping Heartbeat",
    description="High-frequency, ultra-lightweight ping response (~1ms) for uptime monitoring and container warming.",
    responses={
        200: OpenApiResponse(description="Pong heartbeat response")
    },
)
class PingHeartbeatView(APIView):
    """
    Lightweight, high-frequency ping endpoint (~1ms response time).
    Use this endpoint in external uptime monitors to keep the app and container warm.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return JsonResponse({
            'status': 'pong',
            'time': timezone.now().isoformat(),
            'message': 'Closly server is warm and operational.'
        }, status=200)


@extend_schema(
    tags=["System Gateway & Heartbeat"],
    summary="Download Postman Collection",
    description="Directly serves the latest Postman Collection JSON file for mobile and frontend developers.",
    responses={
        200: OpenApiResponse(description="Postman Collection JSON attachment"),
        404: OpenApiResponse(description="Postman collection file not found"),
    },
)
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
