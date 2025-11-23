from django.urls import path

from . import views

app_name = "subscriptions"

urlpatterns = [
    path("admin/", views.admin_subscription_list, name="admin-list"),
    path("admin/<int:pk>/", views.admin_subscription_detail, name="admin-detail"),
    path("me/", views.user_subscription_dashboard, name="user-dashboard"),
    path("me/pay/<int:pk>/", views.user_subscription_pay, name="user-pay"),
]
