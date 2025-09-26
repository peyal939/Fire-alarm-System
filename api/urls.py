from django.urls import path, include
from . import views

urlpatterns = [
    path("healthz", views.healthz),
    path("readyz", views.readyz),
    path("auth/", include("accounts.urls")),
    path("", include("devices.urls")),
]
