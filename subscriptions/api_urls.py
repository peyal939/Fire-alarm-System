from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("me", api_views.UserSubscriptionViewSet, basename="user-subscriptions")
router.register(
    "admin", api_views.AdminSubscriptionViewSet, basename="admin-subscriptions"
)

urlpatterns = router.urls
