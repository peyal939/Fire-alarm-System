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


class IsResellerWithAnyStatus(BasePermission):
    """Allow access to users with any reseller account (including pending)."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        # Check if user has a reseller account (any status)
        reseller = getattr(user, "reseller_account", None)
        return reseller is not None and reseller.deleted_at is None


class IsReseller(BasePermission):
    """Allow access only to users with an active reseller account."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        # Check if user has a reseller account and it's active
        reseller = getattr(user, "reseller_account", None)
        if not reseller:
            return False
        return reseller.is_active


class IsSuperAdminOrReseller(BasePermission):
    """Allow platform superadmins and active resellers."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        # Superadmin always allowed
        if user.is_superuser or getattr(user, "role", "") == "superadmin":
            return True
        # Check for active reseller
        reseller = getattr(user, "reseller_account", None)
        return reseller and reseller.is_active


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

        # Reseller bypass (if the device/object was sold by this reseller)
        reseller = getattr(user, "reseller_account", None)
        if reseller and reseller.is_active:
            # Check if obj is a Device sold by this reseller
            obj_reseller = getattr(obj, "reseller", None)
            if not obj_reseller:
                # If obj is Telemetry/Alert, check via device
                device = getattr(obj, "device", None)
                if device:
                    obj_reseller = getattr(device, "reseller", None)
            
            if obj_reseller and obj_reseller.id == reseller.id:
                return True

        # determine owner attribute
        owner = getattr(obj, "user", None) or getattr(
            getattr(obj, "device", None), "user", None
        )
        return owner == user


class IsOwnerOrResellerOrSuperadmin(BasePermission):
    """
    Extended permission that allows:
    - Superadmins (full access)
    - Resellers (access to devices they sold)
    - Company Admins (access to devices from their orders)
    - Device owners (access to their own devices)
    """
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        
        # Superadmin bypass
        if getattr(user, "role", None) == "superadmin" or user.is_superuser:
            return True

        # Get the device (obj might be Device, Telemetry, Alert, etc.)
        device = obj if hasattr(obj, "hardware_identifier") else getattr(obj, "device", None)
        
        # Reseller access - can manage devices they sold
        reseller = getattr(user, "reseller_account", None)
        if reseller and reseller.is_active and device:
            if getattr(device, "reseller_id", None) == reseller.id:
                return True

        # Company Admin bypass (if they own the originating order)
        if getattr(user, "role", None) == "company_admin":
            order = getattr(device, "originating_order", None) if device else getattr(obj, "originating_order", None)
            if order and order.user_id == user.id:
                return True

        # Owner check
        owner = getattr(obj, "user", None)
        if not owner and device:
            owner = getattr(device, "user", None)
        
        return owner == user
