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
]
