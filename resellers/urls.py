"""URL configuration for the Resellers API."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ResellerRegistrationView,
    ResellerProfileView,
    ResellerDashboardView,
    ResellerInventoryViewSet,
    ResellerCustomerViewSet,
    ResellerDeviceViewSet,
    ResellerAlertViewSet,
    DeviceAssignmentView,
    ResellerOrderListView,
    ResellerPlaceOrderView,
    AdminResellerViewSet,
    AdminResellerDashboardView,
    AdminResellerOrdersView,
    AdminMarkCreditPaidView,
)

# Router for ViewSets
router = DefaultRouter()
router.register(r"inventory", ResellerInventoryViewSet, basename="reseller-inventory")
router.register(r"customers", ResellerCustomerViewSet, basename="reseller-customers")
router.register(r"devices", ResellerDeviceViewSet, basename="reseller-devices")
router.register(r"alerts", ResellerAlertViewSet, basename="reseller-alerts")

# Admin router
admin_router = DefaultRouter()
admin_router.register(r"resellers", AdminResellerViewSet, basename="admin-resellers")

urlpatterns = [
    # Reseller registration and profile
    path("register/", ResellerRegistrationView.as_view(), name="reseller-register"),
    path("profile/", ResellerProfileView.as_view(), name="reseller-profile"),
    path("dashboard/", ResellerDashboardView.as_view(), name="reseller-dashboard"),
    
    # Reseller orders
    path("orders/", ResellerOrderListView.as_view(), name="reseller-orders"),
    path("orders/place/", ResellerPlaceOrderView.as_view(), name="reseller-place-order"),
    
    # Device assignment
    path("assign-device/", DeviceAssignmentView.as_view(), name="reseller-assign-device"),
    
    # ViewSet routes
    path("", include(router.urls)),
    
    # Admin routes (prefix with /admin/)
    path("admin/", include(admin_router.urls)),
    path("admin/dashboard/", AdminResellerDashboardView.as_view(), name="admin-reseller-dashboard"),
    path("admin/orders/", AdminResellerOrdersView.as_view(), name="admin-reseller-orders"),
    path("admin/orders/<int:po_id>/mark-paid/", AdminMarkCreditPaidView.as_view(), name="admin-mark-credit-paid"),
]
