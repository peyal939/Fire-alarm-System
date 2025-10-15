from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PackageViewSet,
    UserOrderListView,
    UserOrderDetailView,
    OrderIdNotifyView,
    AdminOrderStatusUpdateView,
)

router = DefaultRouter()
router.register(r"packages", PackageViewSet, basename="package")

urlpatterns = [
    path("", include(router.urls)),
    # Nested user/order endpoints
    path("orders/<int:user_id>/", UserOrderListView.as_view(), name="user-order-list"),
    path(
        "orders/<int:user_id>/<int:order_id>/",
        UserOrderDetailView.as_view(),
        name="user-order-detail",
    ),
    # webhook to receive external provider order id after payment
    path("orders/payment/notify/", OrderIdNotifyView.as_view(), name="orderid-notify"),
    # admin: update order status
    path(
        "orders/update_status/<int:user_id>/<int:order_id>/",
        AdminOrderStatusUpdateView.as_view(),
        name="orders-update-status",
    ),
]
