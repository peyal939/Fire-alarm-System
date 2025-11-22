from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import ManualPaymentForm, OverrideWindowForm, UserTopUpForm
from .models import DeviceSubscription, SubscriptionCharge
from . import services


logger = logging.getLogger(__name__)


def _subscription_queryset():
    return DeviceSubscription.objects.select_related(
        "device",
        "device__user",
    )


@staff_member_required
def admin_subscription_list(request):
    qs = _subscription_queryset().order_by("status", "next_due_at")
    status_filter = request.GET.get("status")
    query = request.GET.get("q", "").strip()
    if status_filter:
        qs = qs.filter(status=status_filter)
    if query:
        qs = qs.filter(
            Q(device__hardware_identifier__icontains=query)
            | Q(device__user__email__icontains=query)
            | Q(device__device_name__icontains=query)
        )
    stats = {
        "active": _subscription_queryset()
        .filter(status=DeviceSubscription.Status.ACTIVE)
        .count(),
        "grace": _subscription_queryset()
        .filter(status=DeviceSubscription.Status.GRACE)
        .count(),
        "suspended": _subscription_queryset()
        .filter(status=DeviceSubscription.Status.SUSPENDED)
        .count(),
    }
    return render(
        request,
        "subscriptions/admin_list.html",
        {
            "subscriptions": qs[:200],
            "status_filter": status_filter,
            "query": query,
            "stats": stats,
            "status_choices": DeviceSubscription.Status.choices,
        },
    )


@staff_member_required
def admin_subscription_detail(request, pk: int):
    subscription = get_object_or_404(
        _subscription_queryset(),
        pk=pk,
    )
    override_form = OverrideWindowForm(
        request.POST if request.POST.get("action") == "override" else None,
        initial={"admin_override_until": subscription.admin_override_until},
    )
    manual_form = ManualPaymentForm(
        request.POST if request.POST.get("action") == "manual" else None
    )

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "override" and override_form.is_valid():
            subscription.admin_override_until = override_form.cleaned_data[
                "admin_override_until"
            ]
            subscription.save(update_fields=["admin_override_until"])
            if subscription.admin_override_until:
                messages.success(
                    request,
                    "Override window updated. Device will stay online until the selected date.",
                )
            else:
                messages.success(request, "Override window cleared.")
            return redirect(request.path)

        if action == "manual" and manual_form.is_valid():
            charge = services.apply_manual_payment(
                subscription,
                months=manual_form.cleaned_data["months"],
                note=manual_form.cleaned_data.get("note", ""),
                actor=request.user,
            )
            if charge:
                messages.success(
                    request,
                    f"Manual payment recorded for {charge.cycles} month(s).",
                )
            else:
                messages.error(request, "Unable to record manual payment.")
            return redirect(request.path)

    recent_charges = subscription.charges.select_related(
        "payment_transaction"
    ).order_by("-created_at")[:25]
    return render(
        request,
        "subscriptions/admin_detail.html",
        {
            "subscription": subscription,
            "override_form": override_form,
            "manual_form": manual_form,
            "recent_charges": recent_charges,
        },
    )


@login_required
def user_subscription_dashboard(request):
    subs = _subscription_queryset().filter(
        device__user=request.user,
        device__deleted_at__isnull=True,
    )
    cards = []
    now = timezone.now()
    for sub in subs:
        days_remaining = (
            max((sub.last_paid_through - now).days, 0) if sub.last_paid_through else 0
        )
        cards.append(
            {
                "subscription": sub,
                "device": sub.device,
                "days_remaining": days_remaining,
                "form": UserTopUpForm(initial={"subscription_id": sub.pk, "months": 1}),
            }
        )
    return render(
        request,
        "subscriptions/user_dashboard.html",
        {
            "cards": cards,
        },
    )


@login_required
def user_subscription_pay(request, pk: int):
    subscription = get_object_or_404(
        _subscription_queryset(),
        pk=pk,
        device__user=request.user,
    )
    if request.user.is_superuser or getattr(request.user, "role", "") == "superadmin":
        messages.error(
            request,
            "Admin or super admin can't pay. Only owner of the order can pay.",
        )
        return redirect(reverse("subscriptions:user-dashboard"))
    form = UserTopUpForm(request.POST or None, initial={"subscription_id": pk})
    if request.method != "POST" or not form.is_valid():
        logger.info(
            "Pay-now form invalid",
            extra={
                "user_id": getattr(request.user, "pk", None),
                "subscription_id": subscription.pk,
                "errors": form.errors if form.is_bound else None,
            },
        )
        messages.error(request, "Please use the payment form to start a transaction.")
        return redirect(reverse("subscriptions:user-dashboard"))

    months = form.cleaned_data["months"]
    logger.info(
        "Pay-now requested",
        extra={
            "user_id": getattr(request.user, "pk", None),
            "subscription_id": subscription.pk,
            "months": months,
        },
    )
    charge = services.create_charge_for_subscription(
        subscription,
        allow_prepay=True,
        cycles=months,
        auto_initiate=False,
    )
    if not charge:
        logger.warning(
            "Pay-now charge creation failed",
            extra={
                "user_id": getattr(request.user, "pk", None),
                "subscription_id": subscription.pk,
                "months": months,
            },
        )
        messages.error(request, "Unable to create a new charge right now.")
        return redirect(reverse("subscriptions:user-dashboard"))

    txn = services.initiate_payment_for_charge(
        charge,
        client_ip=request.META.get("REMOTE_ADDR", ""),
    )
    if txn and txn.checkout_url:
        logger.info(
            "Pay-now redirect ready",
            extra={
                "user_id": getattr(request.user, "pk", None),
                "subscription_id": subscription.pk,
                "charge_id": charge.pk,
                "transaction_id": getattr(txn, "pk", None),
                "checkout_url": txn.checkout_url,
            },
        )
        return redirect(txn.checkout_url)
    logger.warning(
        "Pay-now missing checkout URL",
        extra={
            "user_id": getattr(request.user, "pk", None),
            "subscription_id": subscription.pk,
            "charge_id": getattr(charge, "pk", None),
            "transaction_id": getattr(txn, "pk", None) if txn else None,
        },
    )
    messages.error(request, "Payment gateway unavailable. Please try again later.")
    return redirect(reverse("subscriptions:user-dashboard"))
