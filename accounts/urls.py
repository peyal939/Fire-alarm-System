from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    EmailTokenObtainPairView,
    login_verify,
    register_init,
    register_verify,
    register,
    password_reset_init,
    password_reset_complete,
    me,
    change_password,
    user_detail_admin,
)

urlpatterns = [
    path("register/init", register_init, name="register-init"),
    path("register/verify", register_verify, name="register-verify"),
    path("register", register, name="register"),
    path("login", EmailTokenObtainPairView.as_view(), name="login"),
    path("login/verify", login_verify, name="login-verify"),
    path("password/forgot/init", password_reset_init, name="password-reset-init"),
    path(
        "password/forgot/complete",
        password_reset_complete,
        name="password-reset-complete",
    ),
    path("refresh", TokenRefreshView.as_view(), name="token_refresh"),
    path("me", me, name="me"),
    path("change-password", change_password, name="change-password"),
    path("users/<int:pk>", user_detail_admin, name="user-detail-admin"),
]
