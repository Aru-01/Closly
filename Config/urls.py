from django.contrib import admin
from django.urls import path , include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/legal/', include('legal_pages.urls')),
    path('api/affiliate/', include('affiliate.urls')),
    path('api/closet/', include('closet.urls')),
    path('api/social/', include('social.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
