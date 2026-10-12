from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from users.views import (
    PublicProfileWebView,
    ProtectedMediaServeView,
    GdprDataExportView,
    DeviceRegistrationView,
    InviteListView,
    InviteRedeemView,
)
from social.views import ContentReportCreateView
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
    # Gateway Root
    path("", ApiRootView.as_view(), name="api-root-gateway"),

    # Health Checks & Monitoring
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("health/ping/", PingHeartbeatView.as_view(), name="health-ping"),

    # API Documentation & Postman Collection
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
  
    # Canonical Public Profile Short Link
    path("u/<str:user_id>/", PublicProfileWebView.as_view(), name="public-profile-short"),

    # Protected Media Delivery (Signed / Auth Token)
    path("api/media/serve/<path:file_path>", ProtectedMediaServeView.as_view(), name="protected-media-serve"),

    # Specification Compliance Routes (GDPR Art. 20 Export, APNs/FCM Devices, DSA Reports, Invites)
    path("v1/me/export", GdprDataExportView.as_view(), name="v1-me-export-root"),
    path("v1/devices", DeviceRegistrationView.as_view(), name="v1-devices-root"),
    path("v1/invites", InviteListView.as_view(), name="v1-invites-root"),
    path("v1/invites/redeem", InviteRedeemView.as_view(), name="v1-invites-redeem-root"),
    path("v1/reports", ContentReportCreateView.as_view(), name="v1-reports-root"),

    # Canonical Application APIs (API v1)
    path("api/v1/users/", include("users.urls")),
    path("api/v1/closet/", include("closet.urls")),
    path("api/v1/feed/", include("affiliate.urls")),
    path("api/v1/social/", include("social.urls")),
    path("api/v1/rewards/", include("rewards.urls")),
    path("api/v1/notifications/", include("notifications.urls")),
    path("api/v1/legal/", include("legal_pages.urls")),

    # Admin Portal
    path("admin/", admin.site.urls),

    # Legacy Compatibility Mounts for Existing Test Suite
    path("api/users/", include(("users.urls", "users"), namespace="legacy_users")),
    path("api/closet/", include(("closet.urls", "closet"), namespace="legacy_closet")),
    path("api/social/", include(("social.urls", "social"), namespace="legacy_social")),
    path("api/affiliate/", include(("affiliate.urls", "affiliate"), namespace="legacy_affiliate")),
    path("api/rewards/", include(("rewards.urls", "rewards"), namespace="legacy_rewards")),
    path("api/notifications/", include(("notifications.urls", "notifications"), namespace="legacy_notifications")),
    path("api/legal/", include(("legal_pages.urls", "legal_pages"), namespace="legacy_legal")),
]

if settings.DEBUG:
    from django.views.static import serve
    from django.urls import re_path

    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
        *static(settings.STATIC_URL, document_root=settings.STATIC_ROOT),
    ]
