from django.urls import path
from .views import (
    InitiatePaymentView,
    VerifyPaymentView,
    ReturnView,
    CancelView,
    StatusView,
)

urlpatterns = [
    path("initiate/", InitiatePaymentView.as_view(), name="shurjopay-initiate"),
    path("verify/", VerifyPaymentView.as_view(), name="shurjopay-verify"),
    path("return/", ReturnView.as_view(), name="shurjopay-return"),
    path("cancel/", CancelView.as_view(), name="shurjopay-cancel"),
    path("status/", StatusView.as_view(), name="shurjopay-status"),
]
