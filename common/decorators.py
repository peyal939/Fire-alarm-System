from functools import wraps
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required


def require_superadmin(view_func):
    """Allow only superadmins (by role or is_superuser). Returns 403 otherwise.
    Does not force login; use together with @login_required when needed.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = getattr(request, "user", None)
        if (
            getattr(user, "is_superuser", False)
            or getattr(user, "role", None) == "superadmin"
        ):
            return view_func(request, *args, **kwargs)
        return HttpResponseForbidden("Forbidden: admin access only")

    return _wrapped


def superadmin_required(view_func):
    """Login + superadmin guard in one decorator."""

    @login_required(login_url="/login")
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if (
            getattr(user, "is_superuser", False)
            or getattr(user, "role", None) == "superadmin"
        ):
            return view_func(request, *args, **kwargs)
        return HttpResponseForbidden("Forbidden: Super Admins only")

    return _wrapped
