from rest_framework.routers import DefaultRouter

from .api_views import FireStationViewSet

router = DefaultRouter()
router.register("firestations", FireStationViewSet, basename="firestation")

urlpatterns = router.urls
