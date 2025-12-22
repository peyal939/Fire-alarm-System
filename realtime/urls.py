from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # Phase 1 dashboard pages
    path("app/dashboard/", views.dashboard_page, name="dashboard_page"),
    path("app/devices/", views.devices_page, name="devices_page"),
    path("app/telemetry/", views.telemetry_page, name="telemetry_page"),
    path("app/alerts/", views.alerts_page, name="alerts_page"),
    path("app/products/", views.products_page, name="products_page"),
    path("app/firestations/", views.firestations_page, name="firestations_page"),
    path("app/account/", views.account_settings_page, name="account_settings"),
    path("app/admin-panel/", views.admin_panel, name="admin_panel"),
    path("app/reseller/", views.reseller_panel, name="reseller_panel"),
    # E-Commerce pages
    path("app/cart/", views.cart_page, name="cart_page"),
    path("app/checkout/", views.checkout_page, name="checkout_page"),
    path("app/orders/", views.orders_page, name="orders_page"),
    path("app/orders/<int:order_id>/", views.order_detail_page, name="order_detail_page"),
    path("app/payment/success/", views.payment_success_page, name="payment_success"),
    path("app/payment/failed/", views.payment_failed_page, name="payment_failed"),
]
