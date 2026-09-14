from django.contrib import admin
from django.urls import path , include
from django.conf import settings
from django.conf.urls.static import static
from users.views import PublicProfileWebView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/legal/', include('legal_pages.urls')),
    path('api/affiliate/', include('affiliate.urls')),
    path('api/closet/', include('closet.urls')),
    path('api/social/', include('social.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/rewards/', include('rewards.urls')),
    path('u/<uuid:user_id>/', PublicProfileWebView.as_view(), name='public-profile-short'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
