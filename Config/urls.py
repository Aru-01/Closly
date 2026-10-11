from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from users.views import (
    PublicProfileWebView,
    GdprDataExportView,
    DeviceRegistrationView,
    ProtectedMediaServeView,
    InviteListView,
    InviteRedeemView,
)
from social.views.report_views import ContentReportCreateView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from .views import (
    ApiRootView,
    HealthCheckView,
    PingHeartbeatView,
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
    # Health Check & Uptime Heartbeat Pings (P-33: standardized /health and /v1/health)
    path("health/", HealthCheckView.as_view(), name="health-check-root"),
    path("health", HealthCheckView.as_view(), name="health-check-root-noslash"),
    path("v1/health", HealthCheckView.as_view(), name="v1-health-check"),
    path("api/health/", HealthCheckView.as_view(), name="health-check"),
    path("api/health/ping/", PingHeartbeatView.as_view(), name="health-ping"),
    # Spec root endpoints (#5, #6, #8, #9, #10)
    path("v1/me/export", GdprDataExportView.as_view(), name="v1-me-export-root"),
    path("v1/devices", DeviceRegistrationView.as_view(), name="v1-devices-root"),
    path("devices", DeviceRegistrationView.as_view(), name="devices-root"),
    path("v1/invites", InviteListView.as_view(), name="v1-invites-root-noslash"),
    path("v1/invites/", InviteListView.as_view(), name="v1-invites-root"),
    path("v1/invites/redeem", InviteRedeemView.as_view(), name="v1-invites-redeem-root-noslash"),
    path("v1/invites/redeem/", InviteRedeemView.as_view(), name="v1-invites-redeem-root"),
    path("v1/reports", ContentReportCreateView.as_view(), name="v1-reports-root-noslash"),
    path("v1/reports/", ContentReportCreateView.as_view(), name="v1-reports-root"),

    # Admin Module
    path("admin/", admin.site.urls),

    # ==============================================================================
    # TASK 8: Canonical API Routing Standardization
    # ==============================================================================
    # 1. All Authentication-related routes strictly grouped under base_url/auth/...
    path("auth/", include("users.auth_urls")),

    # 2. ALL other application APIs strictly grouped under base_url/api/v1/...
    path("api/v1/users/", include("users.urls")),
    path("api/v1/closet/", include("closet.urls")),
    path("api/v1/feed/", include("affiliate.urls")),
    path("api/v1/catalog/", include(("affiliate.urls", "affiliate"), namespace="catalog")),
    path("api/v1/social/", include("social.urls")),
    path("api/v1/rewards/", include("rewards.urls")),
    path("api/v1/notifications/", include("notifications.urls")),
    path("api/v1/legal/", include("legal_pages.urls")),
    path("api/v1/devices", DeviceRegistrationView.as_view(), name="v1-devices-api"),
    path("api/v1/invites", InviteListView.as_view(), name="v1-invites-api-noslash"),
    path("api/v1/invites/", InviteListView.as_view(), name="v1-invites-api"),
    path("api/v1/invites/redeem", InviteRedeemView.as_view(), name="v1-invites-redeem-api-noslash"),
    path("api/v1/invites/redeem/", InviteRedeemView.as_view(), name="v1-invites-redeem-api"),
    path("api/v1/reports", ContentReportCreateView.as_view(), name="v1-reports-api-noslash"),
    path("api/v1/reports/", ContentReportCreateView.as_view(), name="v1-reports-api"),
    path("api/v1/me/export", GdprDataExportView.as_view(), name="v1-me-export-api"),

    # Backward compatibility mounts for transition / mobile client migration
    path("api/users/", include(("users.urls", "users"), namespace="legacy_users")),
    path("api/legal/", include(("legal_pages.urls", "legal_pages"), namespace="legacy_legal")),
    path("api/affiliate/", include(("affiliate.urls", "affiliate"), namespace="legacy_affiliate")),
    path("api/closet/", include(("closet.urls", "closet"), namespace="legacy_closet")),
    path("api/social/", include(("social.urls", "social"), namespace="legacy_social")),
    path("api/notifications/", include(("notifications.urls", "notifications"), namespace="legacy_notifications")),
    path("api/rewards/", include(("rewards.urls", "rewards"), namespace="legacy_rewards")),
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
