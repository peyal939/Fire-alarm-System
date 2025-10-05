from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import EmailTokenObtainPairView, register, me, user_detail_admin

urlpatterns = [
    path("register", register, name="register"),
    path("login", EmailTokenObtainPairView.as_view(), name="login"),
    path("refresh", TokenRefreshView.as_view(), name="token_refresh"),
    path("me", me, name="me"),
    path("users/<int:pk>", user_detail_admin, name="user-detail-admin"),
]
