from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PackageViewSet,
    OrderListAllView,
    UserOrderListView,
    UserOrderDetailView,
    OrderPaymentInitView,
    OrderPaymentMethodUpdateView,
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
from .admin_views import (
    AdminOrderListView,
    AdminOrderDetailView,
    AdminOrderUpdateView,
    AdminOrderBulkUpdateView,
    AdminOrderReportView,
    AdminPaymentReportView,
    AdminSubscriptionReportView,
    AdminDashboardOverviewView,
    AdminRevenueTrendView,
    AdminOrderStatusBreakdownView,
    AdminFulfillmentListView,
    AdminFulfillmentDetailView,
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
        "orders/<int:user_id>/<int:order_id>/payment-method/",
        OrderPaymentMethodUpdateView.as_view(),
        name="user-order-payment-method",
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
    
    # ==========================================================================
    # Admin Endpoints (using manage/ prefix to avoid conflict with Django admin)
    # ==========================================================================
    
    # Admin Order Management
    path("manage/orders/", AdminOrderListView.as_view(), name="admin-orders-list"),
    path("manage/orders/bulk-update/", AdminOrderBulkUpdateView.as_view(), name="admin-orders-bulk-update"),
    path("manage/orders/<int:order_id>/", AdminOrderDetailView.as_view(), name="admin-order-detail"),
    path("manage/orders/<int:order_id>/update/", AdminOrderUpdateView.as_view(), name="admin-order-update"),
    
    # Admin Reports
    path("manage/reports/orders/", AdminOrderReportView.as_view(), name="admin-report-orders"),
    path("manage/reports/payments/", AdminPaymentReportView.as_view(), name="admin-report-payments"),
    path("manage/reports/subscriptions/", AdminSubscriptionReportView.as_view(), name="admin-report-subscriptions"),

    # Admin Fulfillment management
    path("manage/fulfillments/", AdminFulfillmentListView.as_view(), name="admin-fulfillments-list"),
    path("manage/fulfillments/<int:fulfillment_id>/", AdminFulfillmentDetailView.as_view(), name="admin-fulfillments-detail"),
    
    # Admin Dashboard
    path("manage/dashboard/overview/", AdminDashboardOverviewView.as_view(), name="admin-dashboard-overview"),
    path("manage/dashboard/revenue-trend/", AdminRevenueTrendView.as_view(), name="admin-dashboard-revenue-trend"),
    path("manage/dashboard/order-status/", AdminOrderStatusBreakdownView.as_view(), name="admin-dashboard-order-status"),
]
