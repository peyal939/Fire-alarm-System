from django.urls import path, include
from . import views
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from rest_framework.permissions import IsAuthenticated


class DocsPermission(IsAuthenticated):
    """Allow access only to authenticated superusers or users with role=superadmin."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        user = request.user
        return bool(
            getattr(user, "is_superuser", False)
            or getattr(user, "role", "") == "superadmin"
        )


urlpatterns = [
    path("healthz", views.healthz),
    path("readyz", views.readyz),
    path("metrics/summary", views.metrics_summary),
    path("content/faq/", views.faq_content, name="content-faq"),
    path("content/about/", views.about_content, name="content-about"),
    path("auth/", include("accounts.urls")),
    path("", include("devices.urls")),
    path("", include("firestations.urls")),
    # OpenAPI schema and docs
    path(
        "schema/",
        SpectacularAPIView.as_view(permission_classes=[DocsPermission]),
        name="schema",
    ),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(
            url_name="schema", permission_classes=[DocsPermission]
        ),
        name="swagger-ui",
    ),
    path(
        "redoc/",
        SpectacularRedocView.as_view(
            url_name="schema", permission_classes=[DocsPermission]
        ),
        name="redoc",
    ),
]
