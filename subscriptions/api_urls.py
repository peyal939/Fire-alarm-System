from rest_framework.routers import DefaultRouter

from . import api_views
from . import invoice_views

router = DefaultRouter()
router.register("me", api_views.UserSubscriptionViewSet, basename="user-subscriptions")
router.register("invoices", invoice_views.UserInvoiceViewSet, basename="user-invoices")
# Admin routes - register admin/invoices first to ensure correct matching
router.register(
    "admin/invoices", invoice_views.AdminInvoiceViewSet, basename="admin-invoices"
)
router.register(
    "admin", api_views.AdminSubscriptionViewSet, basename="admin-subscriptions"
)

urlpatterns = router.urls
