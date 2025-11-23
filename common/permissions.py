from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsSuperAdmin(BasePermission):
    """Allow access to Django superusers or platform superadmins."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return bool(user.is_superuser or getattr(user, "role", "") == "superadmin")


class IsOwnerOrSuperadmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        # superadmin bypass
        if getattr(user, "role", None) == "superadmin" or user.is_superuser:
            return True
        # determine owner attribute
        owner = getattr(obj, "user", None) or getattr(
            getattr(obj, "device", None), "user", None
        )
        return owner == user
