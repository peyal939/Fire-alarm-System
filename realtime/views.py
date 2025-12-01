from datetime import timedelta

from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.views.decorators.http import require_http_methods

from common.decorators import superadmin_required
from otp.models import PhoneOTP
from otp.services import OTPSessionManager
from accounts.phone_utils import ensure_normalized_phone, phone_variants

User = get_user_model()


@login_required(login_url="/login")
def index(request):
    """Dashboard view; only for authenticated users."""
    return render(request, "index.html")


def _mask_phone(value: str) -> str:
    value = value or ""
    if len(value) <= 4:
        return value
    return "*" * (len(value) - 4) + value[-4:]


def _normalize_identifier(identifier: str):
    identifier = (identifier or "").strip()
    if not identifier:
        return None, None
    if "@" in identifier:
        return identifier.lower(), None
    normalized = ensure_normalized_phone(identifier)
    return (None, normalized) if normalized else (None, None)


def _next_resend_at(last_sent):
    if not last_sent:
        return None
    return last_sent + timedelta(
        seconds=settings.OTP_SETTINGS["resend_cooldown_seconds"]
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Session login with OTP confirmation."""

    next_url = request.POST.get("next") or request.GET.get("next") or "/"
    base_context = {
        "next": next_url,
        "otp_ttl_seconds": settings.OTP_SETTINGS["ttl_seconds"],
        "otp_resend_cooldown": settings.OTP_SETTINGS["resend_cooldown_seconds"],
        "otp_next_resend_at": None,
    }

    if request.method == "POST" and request.POST.get("resend_otp"):
        session_id = request.POST.get("otp_session_id")
        if not session_id:
            context = {
                **base_context,
                "error": "OTP session expired. Please sign in again.",
            }
            return render(request, "login.html", context, status=400)

        manager = OTPSessionManager(purpose=PhoneOTP.Purpose.LOGIN)
        session = PhoneOTP.objects.filter(
            session_id=session_id, purpose=PhoneOTP.Purpose.LOGIN
        ).first()
        if not session:
            context = {
                **base_context,
                "error": "OTP session expired. Please sign in again.",
            }
            return render(request, "login.html", context, status=400)

        masked_phone = _mask_phone(session.phone_number)
        context = {
            **base_context,
            "otp_pending": True,
            "otp_session_id": str(session.session_id),
            "masked_phone": masked_phone,
            "otp_last_sent": session.last_sent_at,
            "otp_next_resend_at": _next_resend_at(session.last_sent_at),
        }

        if not manager.can_resend(session):
            context["otp_error"] = "Please wait before requesting another code."
            return render(request, "login.html", context, status=429)

        try:
            session = manager.resend_session(session)
        except ValueError as exc:
            context["otp_error"] = str(exc)
            return render(request, "login.html", context, status=400)

        context.update(
            {
                "otp_notice": "We sent a new verification code.",
                "otp_last_sent": session.last_sent_at,
                "otp_next_resend_at": _next_resend_at(session.last_sent_at),
            }
        )
        return render(request, "login.html", context, status=202)

    if request.method == "POST" and request.POST.get("otp_session_id"):
        session_id = request.POST.get("otp_session_id")
        code = request.POST.get("otp_code", "").strip()
        if not session_id or not code:
            context = {
                **base_context,
                "otp_error": "OTP code is required.",
                "otp_session_id": session_id,
                "next": next_url,
            }
            return render(request, "login.html", context, status=400)

        manager = OTPSessionManager(purpose=PhoneOTP.Purpose.LOGIN)
        session = PhoneOTP.objects.filter(
            session_id=session_id, purpose=PhoneOTP.Purpose.LOGIN
        ).first()
        if not session or not manager.verify_code(session, code):
            masked_phone = None
            if session:
                masked_phone = _mask_phone(session.phone_number)
            context = {
                **base_context,
                "otp_error": "Invalid or expired OTP.",
                "otp_session_id": session_id,
                "masked_phone": masked_phone,
                "otp_pending": True,
                "otp_last_sent": getattr(session, "last_sent_at", None),
                "otp_next_resend_at": _next_resend_at(
                    getattr(session, "last_sent_at", None)
                ),
                "next": next_url,
            }
            return render(request, "login.html", context, status=400)

        user = session.user or getattr(session, "user", None)
        if not user:
            user_id = (session.metadata or {}).get("user_id")
            user = User.objects.filter(id=user_id).first()
        if not user:
            context = {
                **base_context,
                "error": "Login session expired. Please try again.",
                "next": next_url,
            }
            return render(request, "login.html", context, status=400)

        login(request, user)
        return redirect(next_url)

    if request.method == "POST":
        identifier = (
            request.POST.get("identifier")
            or request.POST.get("email")
            or request.POST.get("phone_number")
            or ""
        ).strip()
        password = request.POST.get("password", "")

        email, phone = _normalize_identifier(identifier)
        user_lookup = None
        if email:
            user_lookup = User.objects.filter(email=email).first()
        elif phone:
            variants = phone_variants(phone) or [phone]
            user_lookup = User.objects.filter(phone_number__in=variants).first()
            email = user_lookup.email if user_lookup else None

        if not email or not user_lookup:
            context = {
                **base_context,
                "error": "Invalid email/phone or password.",
                "email": identifier,
                "next": next_url,
            }
            return render(request, "login.html", context, status=401)

        user = authenticate(request, email=email, password=password)
        if user is None:
            context = {
                **base_context,
                "error": "Invalid email/phone or password.",
                "email": identifier,
                "next": next_url,
            }
            return render(request, "login.html", context, status=401)

        if not user.phone_number:
            context = {
                **base_context,
                "error": "A verified phone number is required for OTP login.",
                "email": identifier,
                "next": next_url,
            }
            return render(request, "login.html", context, status=400)

        manager = OTPSessionManager(purpose=PhoneOTP.Purpose.LOGIN)
        try:
            session = manager.create_session(
                phone_number=user.phone_number,
                user=user,
                metadata={
                    "user_id": user.id,
                    "session_login": True,
                    "identifier": identifier,
                },
            )
        except ValueError as exc:
            context = {
                **base_context,
                "error": str(exc),
                "email": identifier,
                "next": next_url,
            }
            return render(request, "login.html", context, status=429)
        context = {
            **base_context,
            "otp_session_id": str(session.session_id),
            "masked_phone": _mask_phone(user.phone_number),
            "next": next_url,
            "email": identifier,
            "otp_pending": True,
            "otp_last_sent": session.last_sent_at,
            "otp_next_resend_at": _next_resend_at(session.last_sent_at),
        }
        return render(request, "login.html", context, status=202)

    return render(request, "login.html", base_context)


def logout_view(request):
    logout(request)
    return redirect("/login")


# -------- Phase 1: Page stubs (session UI) --------


@login_required(login_url="/login")
def dashboard_page(request):
    return render(request, "dashboard_page.html")


@login_required(login_url="/login")
def devices_page(request):
    return render(request, "devices_page.html")


@login_required(login_url="/login")
def telemetry_page(request):
    return render(request, "telemetry_page.html")


@login_required(login_url="/login")
def alerts_page(request):
    return render(request, "alerts_page.html")


@login_required(login_url="/login")
def products_page(request):
    return render(request, "products_page.html")


@login_required(login_url="/login")
def firestations_page(request):
    return render(request, "firestations_page.html")


@superadmin_required
def admin_panel(request):
    from devices.models import Device
    from subscriptions.models import DeviceSubscription
    from products.models import Package

    users = User.objects.filter(deleted_at__isnull=True).order_by("-created_at")
    devices = (
        Device.objects.filter(deleted_at__isnull=True)
        .select_related("user", "package")
        .order_by("-created_at")
    )
    packages = Package.objects.filter(deleted_at__isnull=True)

    # Stats
    total_users = users.count()
    total_devices = devices.count()
    active_subscriptions = DeviceSubscription.objects.filter(status="active").count()

    return render(
        request,
        "admin_panel.html",
        {
            "users": users,
            "devices": devices,
            "packages": packages,
            "total_users": total_users,
            "total_devices": total_devices,
            "active_subscriptions": active_subscriptions,
        },
    )


@login_required(login_url="/login")
def account_settings_page(request):
    return render(request, "account_settings.html")
