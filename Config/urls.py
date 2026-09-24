from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from users.views import PublicProfileWebView
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
    # Health Check & Uptime Heartbeat Pings (prevents cold starts)
    path("api/health/", HealthCheckView.as_view(), name="health-check"),
    path("api/health/ping/", PingHeartbeatView.as_view(), name="health-ping"),
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
]

from django.views.static import serve
from django.urls import re_path

urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
