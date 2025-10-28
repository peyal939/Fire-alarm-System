"""URL configuration for notifications app."""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FCMDeviceViewSet, NotificationLogViewSet

router = DefaultRouter()
router.register(r"devices", FCMDeviceViewSet, basename="fcm-device")
router.register(r"logs", NotificationLogViewSet, basename="notification-log")

urlpatterns = [
    path("", include(router.urls)),
]
