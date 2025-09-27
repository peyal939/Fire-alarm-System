from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.http import require_http_methods
from common.decorators import superadmin_required


@login_required(login_url="/login")
def index(request):
    """Dashboard view; only for authenticated users."""
    return render(request, "index.html")


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Simple session-based login for the dashboard.

    Accepts email + password. On success, redirects to `next` or `/`.
    """
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        next_url = request.POST.get("next") or request.GET.get("next") or "/"

        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            return redirect(next_url)

        # Invalid credentials
        context = {
            "error": "Invalid email or password.",
            "email": email,
            "next": next_url,
        }
        return render(request, "login.html", context, status=401)

    # GET
    return render(request, "login.html", {"next": request.GET.get("next", "")})


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


@superadmin_required
def admin_panel(request):
    return render(request, "admin_panel.html")
