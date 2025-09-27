from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("realtime.urls")),
    path("", include("api.urls")),
    path("", include("products.urls")),
] + static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
