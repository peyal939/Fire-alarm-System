from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PackageViewSet,
    OrderListAllView,
    UserOrderListView,
    UserOrderDetailView,
    OrderPaymentInitView,
    OrderIdNotifyView,
    AdminOrderStatusUpdateView,
    OrderFulfillView,
)
from .cart_views import (
    CartView,
    CartItemListView,
    CartItemDetailView,
    CartCheckoutView,
)

router = DefaultRouter()
router.register(r"packages", PackageViewSet, basename="package")

urlpatterns = [
    path("", include(router.urls)),
    path("orders/", OrderListAllView.as_view(), name="orders-list-all"),
    # Nested user/order endpoints
    path("orders/<int:user_id>/", UserOrderListView.as_view(), name="user-order-list"),
    path(
        "orders/<int:user_id>/<int:order_id>/",
        UserOrderDetailView.as_view(),
        name="user-order-detail",
    ),
    path(
        "orders/<int:user_id>/<int:order_id>/pay/",
        OrderPaymentInitView.as_view(),
        name="user-order-pay",
    ),
    path(
        "orders/<int:user_id>/<int:order_id>/fulfill/",
        OrderFulfillView.as_view(),
        name="user-order-fulfill",
    ),
    # webhook to receive external provider order id after payment
    path("orders/payment/notify/", OrderIdNotifyView.as_view(), name="orderid-notify"),
    # admin: update order status
    path(
        "orders/update_status/<int:user_id>/<int:order_id>/",
        AdminOrderStatusUpdateView.as_view(),
        name="orders-update-status",
    ),
    # Cart endpoints
    path("cart/", CartView.as_view(), name="cart"),
    path("cart/items/", CartItemListView.as_view(), name="cart-items"),
    path("cart/items/<int:item_id>/", CartItemDetailView.as_view(), name="cart-item-detail"),
    path("cart/checkout/", CartCheckoutView.as_view(), name="cart-checkout"),
]
