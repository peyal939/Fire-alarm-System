from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsSuperAdmin(BasePermission):
    """Allow access to Django superusers or platform superadmins."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_superuser or getattr(user, "role", "") == "superadmin")


class IsSuperAdminOrCompanyAdmin(BasePermission):
    """Allow platform superadmins and company admins (scoped in views)."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        role = getattr(user, "role", "")
        if user.is_superuser or role == "superadmin":
            return True
        return role == "company_admin"


class IsOwnerOrSuperadmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        # superadmin bypass
        if getattr(user, "role", None) == "superadmin" or user.is_superuser:
            return True

        # Company Admin bypass (if they own the originating order)
        if getattr(user, "role", None) == "company_admin":
            # If obj is Device
            order = getattr(obj, "originating_order", None)
            if not order:
                # If obj is Telemetry/Alert
                device = getattr(obj, "device", None)
                if device:
                    order = getattr(device, "originating_order", None)

            if order and order.user_id == user.id:
                return True

        # determine owner attribute
        owner = getattr(obj, "user", None) or getattr(
            getattr(obj, "device", None), "user", None
        )
        return owner == user
