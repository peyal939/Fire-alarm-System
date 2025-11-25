import re
from decimal import Decimal

from rest_framework import serializers

from .enums import AlertStatus
from .models import Device, Telemetry, Alert
from .constants import AlertType, DeviceStatus
from django.db import models
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from .services import order_has_capacity
from products.models import Order
from products.enums import OrderStatus


class DeviceSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source="user.id", read_only=True)
    owner_email = serializers.EmailField(source="user.email", read_only=True)
    owner_phone = serializers.CharField(source="user.phone_number", read_only=True)
    online = serializers.SerializerMethodField()
    originating_order_id = serializers.PrimaryKeyRelatedField(
        source="originating_order",
        read_only=True,
    )
    device_role = serializers.CharField(read_only=True)
    master_id = serializers.IntegerField(source="master.id", read_only=True)
    master_hardware_identifier = serializers.CharField(
        source="master.hardware_identifier", read_only=True
    )
    master_device_name = serializers.CharField(
        source="master.device_name", read_only=True
    )
    master_last_seen = serializers.DateTimeField(
        source="master.last_seen", read_only=True
    )
    mesh_alert = serializers.SerializerMethodField(read_only=True)
    effective_status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Device
        fields = (
            "id",
            "hardware_identifier",
            "device_name",
            "device_role",
            "master_id",
            "master_hardware_identifier",
            "master_device_name",
            "master_last_seen",
            "mesh_alert",
            "latitude",
            "longitude",
            "phone_number",
            "phone_number_updated_at",
            "status",
            "effective_status",
            "registered_at",
            "last_seen",
            "online",
            "owner_id",
            "owner_email",
            "owner_phone",
            "originating_order_id",
        )
        read_only_fields = (
            "id",
            "registered_at",
            "last_seen",
            "phone_number",
            "phone_number_updated_at",
            "device_role",
            "master_id",
            "master_hardware_identifier",
            "master_device_name",
            "master_last_seen",
            "originating_order_id",
            "owner_id",
            "owner_email",
            "owner_phone",
        )

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        # Check subscription status
        # If suspended, hide sensitive/live data for non-admins
        request = self.context.get("request")
        user = request.user if request else None
        is_admin = user and (
            user.is_superuser or getattr(user, "role", "") == "superadmin"
        )

        sub = getattr(instance, "subscription", None)
        is_suspended = sub and not sub.is_active_for_user

        if is_suspended and not is_admin:
            # Mask live data
            ret["status"] = "suspended"
            ret["effective_status"] = "suspended"
            ret["online"] = False
            ret["last_seen"] = None
            ret["mesh_alert"] = None
            # Keep static data (name, id, location) so they can identify the device to pay for it

        # Ensure latitude/longitude are floats and have defaults
        lat = ret.get("latitude")
        if lat is None:
            ret["latitude"] = 23.810300
        else:
            try:
                ret["latitude"] = float(lat)
            except (ValueError, TypeError):
                ret["latitude"] = 23.810300

        lon = ret.get("longitude")
        if lon is None:
            ret["longitude"] = 90.412500
        else:
            try:
                ret["longitude"] = float(lon)
            except (ValueError, TypeError):
                ret["longitude"] = 90.412500

        return ret

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_online(self, obj: Device) -> bool:
        # Delegate to model property; keeps single source of truth.
        return bool(getattr(obj, "is_online", False))

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_mesh_alert(self, obj: Device) -> bool:
        """True if any device in this device's mesh has an open smoke_high alert.

        Mesh is defined as: the master + all its slaves. For masters, master=self; for slaves, master=obj.master.
        """
        try:
            master = obj if obj.device_role == Device.DeviceRole.MASTER else obj.master
            if master is None:
                return False
            member_ids = list(
                Device.objects.filter(deleted_at__isnull=True)
                .filter(models.Q(id=master.id) | models.Q(master_id=master.id))
                .values_list("id", flat=True)
            )
            if not member_ids:
                return False
            return Alert.objects.filter(
                device_id__in=member_ids,
                alert_type=AlertType.SMOKE_HIGH,
                status=AlertStatus.OPEN,
            ).exists()
        except Exception:
            return False

    @extend_schema_field(OpenApiTypes.STR)
    def get_effective_status(self, obj: Device) -> str:
        """Return a derived status string prioritizing offline if stale.

        Keeps the raw device-provided `status` field intact while ensuring UIs
        can display an authoritative offline state when last_seen expired.
        """
        if not getattr(obj, "is_online", False):
            return DeviceStatus.OFFLINE
        return obj.status or DeviceStatus.UNKNOWN


def normalize_bd_phone_number(raw: str) -> str:
    """Normalize Bangladeshi phone numbers to +880XXXXXXXXXX format.

    Accepts inputs like 017XXXXXXXX, +88017XXXXXXXX, 88017XXXXXXXX, or 1712345678.
    Raises ValueError if the number cannot be normalized to the expected shape.
    """

    if raw is None:
        raise ValueError("Phone number is required")

    digits = re.sub(r"\D", "", raw)
    if not digits:
        raise ValueError("Phone number must contain digits")

    if digits.startswith("880"):
        digits = digits[3:]
    elif digits.startswith("88"):
        digits = digits[2:]

    if digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or not digits.startswith("1"):
        raise ValueError("Enter a valid Bangladeshi mobile number (e.g. 017XXXXXXXX)")

    return f"+880{digits}"


class DeviceRegisterSerializer(serializers.Serializer):
    hardware_identifier = serializers.CharField(
        max_length=64, help_text="Unique hardware identifier of the device"
    )
    device_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, help_text="Optional name"
    )
    latitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        help_text="Latitude in decimal degrees (-90..90)",
    )
    longitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        help_text="Longitude in decimal degrees (-180..180)",
    )
    device_role = serializers.ChoiceField(
        choices=Device.DeviceRole.choices,
        required=False,
        default=Device.DeviceRole.MASTER,
        help_text="Role of the device: master (default) or slave",
    )
    master_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "Required when device_role=slave. Must reference an existing master device (ID) "
            "that belongs to you (unless superadmin)."
        ),
    )
    originating_order_id = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.none(),
        required=False,
        allow_null=True,
        source="originating_order",
        help_text=(
            "Optional order to link this device to. Must be one of your paid orders with available slots."
        ),
    )
    target_user_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "Admin-only: user ID to register this device for. Ignored for non-admins."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request") if hasattr(self, "context") else None
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            self.fields["originating_order_id"].queryset = Order.objects.filter(
                user=user,
                order_status=OrderStatus.PAID,
                deleted_at__isnull=True,
                package__deleted_at__isnull=True,
            ).order_by("ordered_at", "id")

    def validate(self, attrs):
        lat = attrs.get("latitude")
        lon = attrs.get("longitude")
        if lat is None or lon is None:
            raise serializers.ValidationError("latitude and longitude are required")
        if not (Decimal("-90") <= lat <= Decimal("90")):
            raise serializers.ValidationError("latitude must be between -90 and 90")
        if not (Decimal("-180") <= lon <= Decimal("180")):
            raise serializers.ValidationError("longitude must be between -180 and 180")
        role = attrs.get("device_role") or Device.DeviceRole.MASTER
        master_id = attrs.get("master_id")
        selected_order = attrs.get("originating_order")
        # Cross-field validation for master/slave
        if str(role) == Device.DeviceRole.SLAVE:
            if not master_id:
                raise serializers.ValidationError(
                    "master_id is required when device_role is 'slave'"
                )
            # Validate master exists and belongs to current user and is a master
            request = self.context.get("request") if hasattr(self, "context") else None
            user = getattr(request, "user", None)
            try:
                master = (
                    Device.objects.filter(id=int(master_id), deleted_at__isnull=True)
                    .select_related("user")
                    .first()
                )
            except Exception:
                master = None
            if not master:
                raise serializers.ValidationError("master device not found")
            if user and not (
                getattr(user, "role", None) == "superadmin"
                or getattr(user, "is_superuser", False)
                or getattr(user, "is_staff", False)
            ):
                if master.user_id != getattr(user, "id", None):
                    raise serializers.ValidationError(
                        "master must belong to the same user"
                    )
            if master.device_role != Device.DeviceRole.MASTER:
                raise serializers.ValidationError(
                    "selected master is not a master device"
                )
            # Replace master_id with instance for downstream create logic convenience
            attrs["master"] = master
        else:
            # role == master => must not provide master_id
            if master_id:
                raise serializers.ValidationError(
                    "master_id must not be provided when device_role is 'master'"
                )
        if selected_order:
            request = self.context.get("request") if hasattr(self, "context") else None
            user = getattr(request, "user", None)
            if not user or not getattr(user, "is_authenticated", False):
                raise serializers.ValidationError(
                    "originating_order_id cannot be used without authentication"
                )
            order = (
                Order.objects.filter(
                    pk=selected_order.pk,
                    user=user,
                    order_status=OrderStatus.PAID,
                    deleted_at__isnull=True,
                    package__deleted_at__isnull=True,
                )
                .select_related("package")
                .first()
            )
            if not order:
                raise serializers.ValidationError(
                    "originating_order_id is not available for assignment"
                )

            # Check if we can skip capacity check (if device is already assigned or fulfilled)
            hid = attrs.get("hardware_identifier")
            skip_capacity_check = False

            # 1. Check existing device
            existing_device = Device.objects.filter(
                hardware_identifier=hid, deleted_at__isnull=True
            ).first()
            if existing_device and existing_device.originating_order_id == order.pk:
                skip_capacity_check = True

            # 2. Check fulfillment
            if not skip_capacity_check:
                from products.models import OrderFulfillment

                fulfillment = OrderFulfillment.objects.filter(
                    hardware_identifier=hid, deleted_at__isnull=True
                ).first()
                if fulfillment and fulfillment.order_id == order.pk:
                    skip_capacity_check = True

            if not skip_capacity_check:
                can_assign, _, message = order_has_capacity(order, role=str(role))
                if not can_assign:
                    raise serializers.ValidationError(message)

            attrs["originating_order"] = order

        return attrs


class DevicePhoneUpdateSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value: str) -> str:
        try:
            return normalize_bd_phone_number(value)
        except ValueError as exc:  # pragma: no cover - validation handles messaging
            raise serializers.ValidationError(str(exc)) from exc


class DeviceNodeSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source="user.id", read_only=True)
    owner_email = serializers.EmailField(source="user.email", read_only=True)
    owner_phone = serializers.CharField(source="user.phone_number", read_only=True)
    online = serializers.SerializerMethodField()
    device_role = serializers.CharField(read_only=True)
    master_id = serializers.IntegerField(source="master.id", read_only=True)
    effective_status = serializers.SerializerMethodField(read_only=True)
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = (
            "id",
            "hardware_identifier",
            "device_name",
            "latitude",
            "longitude",
            "phone_number",
            "phone_number_updated_at",
            "status",
            "effective_status",
            "registered_at",
            "last_seen",
            "online",
            "device_role",
            "master_id",
            "owner_id",
            "owner_email",
            "owner_phone",
        )
        read_only_fields = (
            "id",
            "registered_at",
            "last_seen",
            "phone_number",
            "phone_number_updated_at",
        )

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_latitude(self, obj: Device) -> float:
        val = obj.latitude if obj.latitude is not None else Decimal("23.810300")
        return float(val)

    @extend_schema_field(OpenApiTypes.FLOAT)
    def get_longitude(self, obj: Device) -> float:
        val = obj.longitude if obj.longitude is not None else Decimal("90.412500")
        return float(val)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_online(self, obj: Device) -> bool:
        return bool(getattr(obj, "is_online", False))

    @extend_schema_field(OpenApiTypes.STR)
    def get_effective_status(self, obj: Device) -> str:
        if not getattr(obj, "is_online", False):
            return "offline"
        return obj.status or "unknown"


class DeviceTreeSerializer(DeviceNodeSerializer):
    slaves = serializers.SerializerMethodField()

    class Meta(DeviceNodeSerializer.Meta):
        fields = DeviceNodeSerializer.Meta.fields + ("slaves",)

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_slaves(self, obj: Device):
        """Return slaves ordered by online status (online first)."""
        # Order slaves by last_seen descending (most recent first)
        # This puts online slaves at the top
        slaves = obj.slaves.filter(deleted_at__isnull=True).order_by(
            models.F("last_seen").desc(nulls_last=True), "-registered_at"
        )
        return DeviceNodeSerializer(slaves, many=True).data


class TelemetrySerializer(serializers.ModelSerializer):
    device_id = serializers.PrimaryKeyRelatedField(
        source="device", queryset=Device.objects.all(), write_only=True
    )
    device = serializers.PrimaryKeyRelatedField(read_only=True)
    device_hardware_identifier = serializers.CharField(
        source="device.hardware_identifier", read_only=True
    )
    owner_id = serializers.IntegerField(source="device.user.id", read_only=True)
    owner_email = serializers.EmailField(source="device.user.email", read_only=True)
    owner_phone = serializers.CharField(
        source="device.user.phone_number", read_only=True
    )

    class Meta:
        model = Telemetry
        fields = (
            "id",
            "device_id",
            "device",
            "device_hardware_identifier",
            "smoke_level",
            "device_status",
            "timestamp",
            "received_at",
            "owner_id",
            "owner_email",
            "owner_phone",
        )
        read_only_fields = ("id", "received_at")


class AlertSerializer(serializers.ModelSerializer):
    device_hardware_identifier = serializers.CharField(
        source="device.hardware_identifier", read_only=True
    )
    owner_id = serializers.IntegerField(source="device.user.id", read_only=True)
    owner_email = serializers.EmailField(source="device.user.email", read_only=True)
    owner_phone = serializers.CharField(
        source="device.user.phone_number", read_only=True
    )
    acknowledged_by = serializers.PrimaryKeyRelatedField(read_only=True)
    acknowledged_by_email = serializers.EmailField(
        source="acknowledged_by.email", read_only=True
    )

    class Meta:
        model = Alert
        fields = (
            "id",
            "device",
            "device_hardware_identifier",
            "alert_type",
            "status",
            "triggered_at",
            "last_triggered_at",
            "resolved_at",
            "acknowledged_at",
            "acknowledged_by",
            "acknowledged_by_email",
            "last_reminder_at",
            "reminder_count",
            "owner_id",
            "owner_email",
            "owner_phone",
        )
        read_only_fields = (
            "id",
            "triggered_at",
            "last_triggered_at",
            "resolved_at",
            "acknowledged_at",
            "acknowledged_by",
            "acknowledged_by_email",
            "last_reminder_at",
            "reminder_count",
        )
