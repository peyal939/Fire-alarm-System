from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("realtime.urls")),
    path("", include("api.urls")),
    path("", include("products.urls")),
    path("shurjopay/", include("shurjopay.urls")),
    path("api/fcm/", include("notifications.urls")),
    # API Documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
] + static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
