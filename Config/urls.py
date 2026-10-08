from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from users.views import (
    PublicProfileWebView,
    GdprDataExportView,
    DeviceRegistrationView,
    ProtectedMediaServeView,
)
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from .views import (
    ApiRootView,
    HealthCheckView,
    PingHeartbeatView,
    PostmanCollectionDownloadView,
)

urlpatterns = [
    # API Gateway Root Dashboard
    path("", ApiRootView.as_view(), name="api-root-gateway"),
    # OpenAPI 3.0, Swagger UI & Redoc Documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path(
        "api/docs/postman/",
        PostmanCollectionDownloadView.as_view(),
        name="postman-download",
    ),
    # Health Check & Uptime Heartbeat Pings (P-33: standardized /health and /v1/health)
    path("health/", HealthCheckView.as_view(), name="health-check-root"),
    path("health", HealthCheckView.as_view(), name="health-check-root-noslash"),
    path("v1/health", HealthCheckView.as_view(), name="v1-health-check"),
    path("api/health/", HealthCheckView.as_view(), name="health-check"),
    path("api/health/ping/", PingHeartbeatView.as_view(), name="health-ping"),
    # Spec root endpoints (#5, #6, #8)
    path("v1/me/export", GdprDataExportView.as_view(), name="v1-me-export-root"),
    path("v1/devices", DeviceRegistrationView.as_view(), name="v1-devices-root"),
    path("devices", DeviceRegistrationView.as_view(), name="devices-root"),
    # Admin & App Modules
    path("admin/", admin.site.urls),
    path("api/users/", include("users.urls")),
    path("api/legal/", include("legal_pages.urls")),
    path("api/affiliate/", include("affiliate.urls")),
    path("api/closet/", include("closet.urls")),
    path("api/social/", include("social.urls")),
    path("api/notifications/", include("notifications.urls")),
    path("api/rewards/", include("rewards.urls")),
    path(
        "u/<str:user_id>/", PublicProfileWebView.as_view(), name="public-profile-short"
    ),
    # P-04: Private media delivery with signed tokens or authentication
    path(
        "api/media/serve/<path:file_path>",
        ProtectedMediaServeView.as_view(),
        name="protected-media-serve",
    ),
]

if settings.DEBUG:
    from django.views.static import serve
    from django.urls import re_path
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
        *static(settings.STATIC_URL, document_root=settings.STATIC_ROOT),
    ]
