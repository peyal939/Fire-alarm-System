from __future__ import annotations

from decimal import Decimal, InvalidOperation
import logging

from django.db import models, transaction, IntegrityError
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets, filters
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import IsOwnerOrSuperadmin
from drf_spectacular.utils import (
    extend_schema,
    OpenApiParameter,
    OpenApiExample,
    OpenApiResponse,
    OpenApiTypes,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers

from . import services
from .enums import AlertStatus
from .models import Device, Telemetry, Alert
from .serializers import (
    DeviceSerializer,
    TelemetrySerializer,
    AlertSerializer,
    DeviceRegisterSerializer,
    DeviceTreeSerializer,
    DevicePhoneUpdateSerializer,
    DeviceDelegationSerializer,
)
from .constants import DeviceConfigurationPublishError
from .services import OrderAssignmentError
from .alarm_state import reset_state_for_alert, schedule_next_reminder
from subscriptions.enums import DeviceSubscriptionStatus
from subscriptions.models import DeviceSubscription
from subscriptions.services import ensure_device_subscription
from products.models import OrderFulfillment

logger = logging.getLogger(__name__)


def _broadcast_new_device(device: Device) -> None:
    """Push newly registered device state to real-time subscribers."""

    try:
        from realtime.mqtt import _broadcast_device_update
        from devices.constants import DeviceStatus

        latest = Telemetry.objects.filter(device=device).order_by("-timestamp").first()

        ts_int = None
        ts_dt = timezone.now()
        smoke_val = 0

        if latest:
            ts_int = int(latest.timestamp.timestamp())
            ts_dt = latest.timestamp
            smoke_val = latest.smoke_level

        _broadcast_device_update(
            device,
            device_id=device.hardware_identifier,
            ts_int=ts_int,
            ts_dt=ts_dt,
            smoke_val=smoke_val,
            status_str=device.status or DeviceStatus.OFFLINE,
        )
    except Exception as exc:  # pragma: no cover - broadcast failure shouldn't block
        logger.warning(
            "Failed to broadcast device %s registration update: %s",
            device.hardware_identifier,
            exc,
        )


def _broadcast_device_removed(device: Device) -> None:
    """Notify subscribers that a device has been removed."""

    try:
        from realtime.mqtt import broadcast_device_removed

        broadcast_device_removed(device)
    except Exception as exc:  # pragma: no cover - removal broadcast is best-effort
        logger.warning(
            "Failed to broadcast device %s removal: %s",
            device.hardware_identifier,
            exc,
        )


def _ensure_subscription(device: Device) -> None:
    if not device or not getattr(device, "pk", None):
        return
    try:
        ensure_device_subscription(device)
    except Exception as exc:  # pragma: no cover - subscription sync is best-effort
        logger.warning(
            "Failed to ensure subscription for device %s: %s",
            getattr(device, "pk", None),
            exc,
        )


def _subscription_access_q(*, relation: str = "subscription", now=None) -> Q:
    now = now or timezone.now()
    prefix = f"{relation}__" if relation else ""

    def field(name: str) -> str:
        return f"{prefix}{name}"

    return (
        Q(**{field("isnull"): True})
        | Q(**{field("status"): DeviceSubscriptionStatus.ACTIVE})
        | (
            Q(**{field("status"): DeviceSubscriptionStatus.GRACE})
            & (
                Q(**{field("grace_expires_at__isnull"): True})
                | Q(**{field("grace_expires_at__gte"): now})
            )
        )
        | Q(**{field("admin_override_until__gte"): now})
    )


class DeviceViewSet(viewsets.ModelViewSet):
    serializer_class = DeviceSerializer
    # Require authentication first to avoid AnonymousUser reaching queryset resolution
    permission_classes = [IsAuthenticated, IsOwnerOrSuperadmin]
    http_method_names = ["get", "patch", "delete", "post"]
    # Provide a base queryset so schema generators can infer model/lookup types
    queryset = Device.objects.select_related("user", "subscription").filter(
        deleted_at__isnull=True
    )
    # Constrain lookup to digits and document path param as integer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        base = Device.objects.select_related("user", "subscription").filter(
            deleted_at__isnull=True
        )
        user = self.request.user
        # Safety guard: if somehow unauthenticated slips through, return empty set
        if not getattr(user, "is_authenticated", False):
            return Device.objects.none()
        if getattr(user, "role", None) == "superadmin" or user.is_superuser:
            return base

        if getattr(user, "role", None) == "company_admin":
            return base.filter(
                Q(user=user) | Q(originating_order__user=user)
            ).distinct()

        # For normal users, we return ALL their devices so they can see "Suspended" status.
        # The serializer will handle hiding sensitive data if suspended.
        return base.filter(user=user)

    def list(self, request, *args, **kwargs):
        """List all devices with ordering: online devices first, then offline.

        Since is_online is a computed property based on last_seen, we order by:
        1. last_seen DESC (nulls last) - puts recently active devices first
        2. This effectively shows online devices at the top
        """
        queryset = self.filter_queryset(self.get_queryset())

        # Order by last_seen descending (most recent first), nulls last
        # This puts online devices (recently seen) at the top
        # Robust ordering: Force devices with a last_seen value to the top
        # This avoids DB-specific NULL handling quirks
        queryset = queryset.annotate(
            has_last_seen=models.Case(
                models.When(last_seen__isnull=False, then=1),
                default=0,
                output_field=models.IntegerField(),
            )
        ).order_by(
            "-has_last_seen",  # Those with last_seen (1) come first
            "-last_seen",  # Then sort by recency
            "-registered_at",  # Tie-breaker
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):  # disable default create
        return Response(
            {"detail": "Use /devices/register to create/claim devices"}, status=405
        )

    def partial_update(self, request, *args, **kwargs):
        """Patch a device's editable fields.

        Permissions:
        - Admins (superuser or role=superadmin) can patch any device.
        - Normal users can patch only their own devices (enforced by IsOwnerOrSuperadmin).
        """
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance: Device = self.get_object()
        instance.soft_delete(acting_user=request.user)

        # Reset fulfillment status if exists so it can be reclaimed
        OrderFulfillment.objects.filter(
            hardware_identifier=instance.hardware_identifier
        ).update(is_claimed=False)

        _broadcast_device_removed(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["Devices"],
        summary="List unclaimed devices",
        description="List devices assigned to the user (e.g. via Order) but not yet registered/setup.",
        responses={200: DeviceSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="unclaimed")
    def unclaimed(self, request):
        """List fulfilled but unclaimed devices for the user."""
        qs = OrderFulfillment.objects.filter(
            order__user=request.user, is_claimed=False, deleted_at__isnull=True
        ).select_related("order")

        # Create dummy Device instances to ensure serialization consistency
        dummy_devices = []
        for item in qs:
            # Create a transient Device instance (not saved to DB)
            d = Device(
                id=-item.id,  # Negative ID to avoid collision
                hardware_identifier=item.hardware_identifier,
                device_name="",
                device_role=item.device_role,
                latitude=Decimal("23.810300"),  # Default location for map pin
                longitude=Decimal("90.412500"),
                status="unknown",
                user=request.user,
                originating_order=item.order,
            )
            # Manually attach attributes expected by serializer that aren't on the model instance
            # d.is_online is a property, so we can't set it directly on the instance.
            # However, DeviceSerializer uses getattr(obj, "is_online", False).
            # Since d.last_seen is None, d.is_online will return False automatically.
            # d.is_online = False

            d.master = (
                None  # Unclaimed devices don't have a linked master device record yet
            )

            # For master_hardware_identifier, we need to trick the serializer
            # DeviceSerializer uses source='master.hardware_identifier'
            # Since d.master is None, this would be None.
            # But OrderFulfillment has the info.
            # We can't easily inject it into d.master without a dummy master object.
            if item.master_hardware_identifier:
                # Create a dummy master just for the identifier
                d.master = Device(
                    hardware_identifier=item.master_hardware_identifier, device_name=""
                )

            dummy_devices.append(d)

        serializer = DeviceSerializer(dummy_devices, many=True)
        return Response(serializer.data)

    @extend_schema(
        tags=["Devices"],
        summary="Register/claim a device",
        description=(
            "Register a device as either a master (default) or a slave.\n\n"
            "How to register a slave device:\n"
            "- Set `device_role` to `slave`.\n"
            "- Provide `master_id` referencing an existing master device that you own (non-admin users). Admins/staff/superadmins can attach a slave to any master regardless of owner.\n"
            "- The selected master must have role `master`; you cannot attach to another slave.\n\n"
            "Additional rules:\n"
            "- `master_id` is required when `device_role` is `slave`, and must NOT be provided when `device_role` is `master`.\n"
            "- Latitude and longitude are required on first registration.\n"
            "- If the hardware identifier is already registered by another user, the endpoint returns 409 Conflict.\n"
            "- If the device is already registered by you (or you are superadmin), the same call updates name/coordinates and returns 200.\n"
        ),
        request=DeviceRegisterSerializer,
        responses={
            201: DeviceSerializer,
            200: DeviceSerializer,
            409: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description="Conflict when attempting to register a device owned by another user.",
                examples=[
                    OpenApiExample(
                        "DeviceAlreadyRegistered",
                        value={"detail": "Device already registered by another user"},
                        response_only=True,
                    )
                ],
            ),
        },
        examples=[
            OpenApiExample(
                "RegisterMasterRequest",
                value={
                    "hardware_identifier": "MASTER-001",
                    "device_name": "Main Panel",
                    "latitude": 23.777628,
                    "longitude": 90.405449,
                    "device_role": "master",
                },
                request_only=True,
            ),
            OpenApiExample(
                "RegisterSlaveRequest",
                value={
                    "hardware_identifier": "SLAVE-101",
                    "device_name": "Floor 1 Sensor",
                    "latitude": 23.777700,
                    "longitude": 90.405500,
                    "device_role": "slave",
                    "master_id": 123,
                },
                request_only=True,
            ),
        ],
    )
    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        ser = DeviceRegisterSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        validated = ser.validated_data
        hid = validated["hardware_identifier"].strip()
        name = validated.get("device_name", "").strip()
        lat_dec = validated.get("latitude")
        lon_dec = validated.get("longitude")
        role = validated.get("device_role") or Device.DeviceRole.MASTER
        master = validated.get("master")  # set in serializer when role==slave
        preferred_order = validated.get("originating_order")
        target_user_id = validated.get("target_user_id")
        package = validated.get("package")  # admin-assigned package

        owner = request.user
        if target_user_id and (
            request.user.is_superuser
            or getattr(request.user, "role", None) == "superadmin"
            or getattr(request.user, "is_staff", False)
        ):
            from django.contrib.auth import get_user_model

            User = get_user_model()
            owner = User.objects.filter(pk=target_user_id).first()
            if not owner:
                return Response({"detail": "Target user not found."}, status=400)

        if not hid:
            return Response({"detail": "hardware_identifier is required"}, status=400)

        # Note: new device registration requires lat/lon via serializer validation

        # Check for existing device (including soft-deleted ones)
        # First check active devices
        existing = Device.objects.filter(
            hardware_identifier=hid, deleted_at__isnull=True
        ).first()

        if existing:
            # Active device exists - update it if allowed
            if existing.user != owner and not (
                request.user.is_superuser
                or getattr(request.user, "role", None) == "superadmin"
            ):
                return Response(
                    {"detail": "Device already registered by another user"}, status=409
                )
            # Update if same owner or superadmin
            if name:
                existing.device_name = name
            if lat_dec is not None:
                existing.latitude = lat_dec
            if lon_dec is not None:
                existing.longitude = lon_dec
            # Update role and master if provided
            if role:
                existing.device_role = role
            if role == Device.DeviceRole.SLAVE and master:
                existing.master = master
            elif role == Device.DeviceRole.MASTER:
                existing.master = None
            # Update package if provided (admin feature)
            if package and not existing.package_id:
                existing.package = package

            # Mark as registered if this is the first claim
            if not existing.registered_at:
                existing.registered_at = timezone.now()

            existing.save()
            if not existing.originating_order_id:
                if preferred_order:
                    services.assign_device_to_order(
                        existing, preferred_order=preferred_order
                    )
                else:
                    services.assign_device_to_order(existing)

            # Broadcast the updated device to WebSocket clients
            _broadcast_new_device(existing)
            _ensure_subscription(existing)

            return Response(DeviceSerializer(existing).data, status=200)

        # Check for soft-deleted device with the same hardware_identifier
        soft_deleted = Device.objects.filter(
            hardware_identifier=hid, deleted_at__isnull=False
        ).first()

        # Check OrderFulfillment
        fulfillment = OrderFulfillment.objects.filter(
            hardware_identifier=hid, deleted_at__isnull=True
        ).first()

        if soft_deleted:
            # Check if the user has a valid fulfillment for this device
            has_valid_fulfillment = False
            if (
                fulfillment
                and fulfillment.order.user == owner
                and not fulfillment.is_claimed
            ):
                has_valid_fulfillment = True

            # Only allow restore if it belonged to the target owner OR if they have a valid fulfillment
            if (
                not has_valid_fulfillment
                and soft_deleted.user != owner
                and not (
                    request.user.is_superuser
                    or getattr(request.user, "role", None) == "superadmin"
                )
            ):
                return Response(
                    {"detail": "Device not found or not assigned to you"}, status=404
                )

            # Un-delete (restore) the device and reassign to owner
            soft_deleted.deleted_at = None
            soft_deleted.deleted_by = None
            soft_deleted.user = owner
            soft_deleted.updated_by = request.user
            soft_deleted.updated_at = timezone.now()
            # soft_deleted.registered_at = timezone.now() # Keep original registration date? Or update?
            # If it was deleted, maybe treat as new registration?
            soft_deleted.registered_at = timezone.now()

            if name:
                soft_deleted.device_name = name
            if lat_dec is not None:
                soft_deleted.latitude = lat_dec
            if lon_dec is not None:
                soft_deleted.longitude = lon_dec
            soft_deleted.device_role = role
            if role == Device.DeviceRole.SLAVE and master:
                soft_deleted.master = master
            elif role == Device.DeviceRole.MASTER:
                soft_deleted.master = None

            if has_valid_fulfillment:
                soft_deleted.originating_order = fulfillment.order
                fulfillment.is_claimed = True
                fulfillment.save(update_fields=["is_claimed"])
            else:
                # Clear originating order if device is moving to a different owner (e.g. admin override)
                if (
                    soft_deleted.originating_order_id
                    and soft_deleted.originating_order
                    and soft_deleted.originating_order.user_id != request.user.id
                ):
                    soft_deleted.originating_order = None

            soft_deleted.save()

            if not has_valid_fulfillment and soft_deleted.originating_order_id is None:
                if preferred_order:
                    services.assign_device_to_order(
                        soft_deleted, preferred_order=preferred_order
                    )
                else:
                    services.assign_device_to_order(soft_deleted)

            _ensure_subscription(soft_deleted)
            _broadcast_new_device(soft_deleted)
            return Response(DeviceSerializer(soft_deleted).data, status=201)

        # If neither active nor soft-deleted found, create new device

        if not fulfillment:
            # Strict mode: only allow registration if fulfilled (unless superadmin)
            if not (
                request.user.is_superuser
                or getattr(request.user, "role", None) == "superadmin"
            ):
                return Response(
                    {"detail": "Device ID not authorized. Please contact support."},
                    status=400,
                )

        if fulfillment:
            if fulfillment.is_claimed:
                return Response({"detail": "Device ID already claimed."}, status=409)
            if fulfillment.order.user != owner and not (
                request.user.is_superuser
                or getattr(request.user, "role", None) == "superadmin"
            ):
                return Response(
                    {"detail": "Device ID belongs to another user."}, status=403
                )

        try:
            with transaction.atomic():
                device_kwargs = dict(
                    user=owner,
                    hardware_identifier=hid,
                    device_name=name,
                    latitude=lat_dec,
                    longitude=lon_dec,
                    device_role=role,
                    registered_at=timezone.now(),
                    created_by=request.user,
                )
                if role == Device.DeviceRole.SLAVE and master:
                    device_kwargs["master"] = master
                if package:
                    device_kwargs["package"] = package

                device = Device.objects.create(**device_kwargs)

                if fulfillment:
                    device.originating_order = fulfillment.order
                    device.save(update_fields=["originating_order"])
                    fulfillment.is_claimed = True
                    fulfillment.save(update_fields=["is_claimed"])
                else:
                    # Only auto-attach to an order for non-admin users; admins can
                    # register devices (gifts, manual deployments, etc.) without
                    # tying them to an Order.
                    if not (
                        request.user.is_superuser
                        or getattr(request.user, "role", None) == "superadmin"
                    ):
                        if preferred_order:
                            services.assign_device_to_order(
                                device, preferred_order=preferred_order
                            )
                        else:
                            services.assign_device_to_order(device)

                _ensure_subscription(device)
                _broadcast_new_device(device)
                return Response(DeviceSerializer(device).data, status=201)
        except ValidationError as exc:
            # Surface model validation errors (e.g. missing master for slave) as 400 responses
            return Response(exc.message_dict, status=400)
        except IntegrityError:
            return Response(
                {"detail": "Device already registered by another user"}, status=409
            )
        except OrderAssignmentError as exc:
            return Response({"detail": str(exc)}, status=400)

    @extend_schema(
        tags=["Devices"],
        summary="Admin register a device for any user",
        description="Admin-only endpoint to register a device for any user by their email.",
        request=inline_serializer(
            name="AdminRegisterDeviceRequest",
            fields={
                "hardware_identifier": drf_serializers.CharField(),
                "device_name": drf_serializers.CharField(required=False, allow_blank=True),
                "user_email": drf_serializers.EmailField(),
                "device_role": drf_serializers.ChoiceField(choices=["master", "slave"], required=False),
                "package_id": drf_serializers.IntegerField(required=False),
            },
        ),
        responses={201: DeviceSerializer},
    )
    @action(detail=False, methods=["post"], url_path="admin-register")
    def admin_register(self, request):
        """Admin-only endpoint to register a device for any user."""
        if not (
            request.user.is_superuser
            or getattr(request.user, "role", None) == "superadmin"
        ):
            return Response({"detail": "Admin access required"}, status=403)

        user_email = request.data.get("user_email", "").strip().lower()
        if not user_email:
            return Response({"detail": "user_email is required"}, status=400)

        from django.contrib.auth import get_user_model

        User = get_user_model()
        target_user = User.objects.filter(email=user_email).first()
        if not target_user:
            return Response(
                {"detail": f"User with email {user_email} not found"}, status=404
            )

        hid = request.data.get("hardware_identifier", "").strip()
        if not hid:
            return Response({"detail": "hardware_identifier is required"}, status=400)

        # Check if device already exists
        existing = Device.objects.filter(
            hardware_identifier=hid, deleted_at__isnull=True
        ).first()
        if existing:
            return Response({"detail": "Device already registered"}, status=409)

        device_name = request.data.get("device_name", "").strip()
        device_role = request.data.get("device_role", Device.DeviceRole.MASTER)
        package_id = request.data.get("package_id")

        package = None
        if package_id:
            from products.models import Package

            package = Package.objects.filter(
                pk=package_id, deleted_at__isnull=True
            ).first()

        try:
            with transaction.atomic():
                device = Device.objects.create(
                    user=target_user,
                    hardware_identifier=hid,
                    device_name=device_name,
                    device_role=device_role,
                    package=package,
                    latitude=Decimal("23.810300"),  # Default Dhaka location
                    longitude=Decimal("90.412500"),
                    registered_at=timezone.now(),
                    created_by=request.user,
                )
                _ensure_subscription(device)
                _broadcast_new_device(device)
                return Response(DeviceSerializer(device).data, status=201)
        except IntegrityError:
            return Response({"detail": "Device registration failed"}, status=409)

    @extend_schema(
        tags=["Devices"],
        summary="Assign a phone number to a device",
        description=(
            "Attach a Bangladeshi phone number to a registered, online device and"
            " propagate it to the IoT hardware via MQTT. Numbers are stored in"
            " +880XXXXXXXXXX format."
        ),
        request=DevicePhoneUpdateSerializer,
        responses={
            200: DeviceSerializer,
            409: OpenApiResponse(
                description="Device offline",
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        "DeviceOffline",
                        value={
                            "detail": "Device must be online to assign a phone number."
                        },
                        response_only=True,
                    )
                ],
            ),
            502: OpenApiResponse(
                description="MQTT publish failed",
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        "PublishFailed",
                        value={
                            "detail": "Failed to push phone number update to the device. Please try again shortly."
                        },
                        response_only=True,
                    )
                ],
            ),
        },
        examples=[
            OpenApiExample(
                "AssignPhoneRequest",
                value={"phone_number": "01778043119"},
                request_only=True,
            ),
            OpenApiExample(
                "AssignPhoneResponse",
                value={
                    "id": 42,
                    "hardware_identifier": "aPsF1001",
                    "phone_number": "+8801778043119",
                    "phone_number_updated_at": "2025-10-27T10:30:00+0600",
                },
                response_only=True,
            ),
        ],
    )
    @action(detail=True, methods=["post"], url_path="phone")
    def assign_phone(self, request, pk=None):
        device = self.get_object()
        serializer = DevicePhoneUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not device.is_online:
            return Response(
                {"detail": "Device must be online to assign a phone number."},
                status=status.HTTP_409_CONFLICT,
            )

        phone_number = serializer.validated_data["phone_number"]
        try:
            with transaction.atomic():
                now = timezone.now()
                device.phone_number = phone_number
                device.phone_number_updated_at = now
                device.save(update_fields=["phone_number", "phone_number_updated_at"])
                services.publish_device_phone_assignment(
                    device,
                    phone_number=phone_number,
                )
        except DeviceConfigurationPublishError as exc:
            logger.error(
                "Failed to publish phone number for %s: %s",
                device.hardware_identifier,
                exc,
            )
            return Response(
                {
                    "detail": "Failed to push phone number update to the device. Please try again shortly."
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        device.refresh_from_db(fields=["phone_number", "phone_number_updated_at"])
        return Response(self.get_serializer(device).data)

    @extend_schema(
        tags=["Devices"],
        summary="Assign a phone number to a device",
        description=(
            "Attach a Bangladeshi phone number to an already registered device and push"
            f" it to the IoT hardware via MQTT on topic `{settings.MQTT_DEVICE_REG_TOPIC}`."
            " The device must be online (fresh last_seen) for the update to succeed."
            " Numbers are normalized to +880XXXXXXXXXX and published using the payload"
            " {device_id, phoneNumber, soundOff} with soundOff fixed at 0."
        ),
        request=DevicePhoneUpdateSerializer,
        responses={
            200: DeviceSerializer,
            409: OpenApiResponse(
                description="Device offline",
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        "DeviceOffline",
                        value={
                            "detail": "Device must be online to assign a phone number."
                        },
                    )
                ],
            ),
            502: OpenApiResponse(
                description="MQTT publish failure",
                response=OpenApiTypes.OBJECT,
                examples=[
                    OpenApiExample(
                        "PublishFailed",
                        value={
                            "detail": "Failed to push phone number update to the device. Please try again shortly."
                        },
                    )
                ],
            ),
        },
        examples=[
            OpenApiExample(
                "AssignPhoneRequest",
                value={"phone_number": "01778043119"},
                request_only=True,
            ),
            OpenApiExample(
                "AssignPhoneResponse",
                value={
                    "id": 101,
                    "hardware_identifier": "aPsF1001",
                    "phone_number": "+8801778043119",
                    "phone_number_updated_at": "2025-10-27T10:22:00+0600",
                },
                response_only=True,
            ),
        ],
    )
    @action(detail=True, methods=["post"], url_path="phone")
    def assign_phone(self, request, pk=None):
        device = self.get_object()
        ser = DevicePhoneUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        if not device.is_online:
            return Response(
                {"detail": "Device must be online to assign a phone number."},
                status=status.HTTP_409_CONFLICT,
            )

        phone_number = ser.validated_data["phone_number"]
        try:
            with transaction.atomic():
                now = timezone.now()
                device.phone_number = phone_number
                device.phone_number_updated_at = now
                device.save(update_fields=["phone_number", "phone_number_updated_at"])
                services.publish_device_phone_assignment(
                    device,
                    phone_number=phone_number,
                )
        except DeviceConfigurationPublishError as exc:
            logger.error(
                "Failed to publish phone number for %s: %s",
                device.hardware_identifier,
                exc,
            )
            return Response(
                {
                    "detail": "Failed to push phone number update to the device. Please try again shortly."
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        device.refresh_from_db(fields=["phone_number", "phone_number_updated_at"])
        device.refresh_from_db(fields=["phone_number", "phone_number_updated_at"])
        return Response(self.get_serializer(device).data, status=200)

    @extend_schema(
        tags=["Devices"],
        summary="Delegate device access to another user",
        request=DeviceDelegationSerializer,
        responses={200: DeviceSerializer, 403: None, 404: None},
    )
    @action(detail=True, methods=["post"], url_path="delegate_access")
    def delegate_access(self, request, pk=None):
        device = self.get_object()
        # Check if request user is the "company owner" of this device
        is_company_owner = (
            device.originating_order
            and device.originating_order.user == request.user
            and getattr(request.user, "role", "") == "company_admin"
        )
        is_admin = (
            getattr(request.user, "role", "") == "superadmin"
            or request.user.is_superuser
        )

        if not (is_company_owner or is_admin):
            return Response(
                {"detail": "You do not have permission to delegate this device."},
                status=403,
            )

        serializer = DeviceDelegationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone_number"]

        # Find target user
        from django.contrib.auth import get_user_model

        User = get_user_model()
        target_user = User.objects.filter(phone_number=phone).first()

        if not target_user:
            return Response(
                {"detail": "User with this phone number not found."}, status=404
            )

        if (
            device.device_role == Device.DeviceRole.SLAVE
            and device.master_id
            and device.master.user_id != target_user.id
        ):
            return Response(
                {
                    "detail": (
                        "Delegate the master device to this user first. A slave must share"
                        " the same owner as its master to keep the mesh consistent."
                    )
                },
                status=400,
            )

        # Assign device
        device.user = target_user
        device.save(update_fields=["user"])

        return Response(self.get_serializer(device).data)

    @extend_schema(
        tags=["Devices"],
        summary="List devices as a tree (masters with nested slaves)",
        responses={
            200: OpenApiResponse(
                response=DeviceTreeSerializer(many=True),
                examples=[
                    OpenApiExample(
                        "DevicesTreeResponse",
                        value=[
                            {
                                "id": 123,
                                "hardware_identifier": "MASTER-001",
                                "device_name": "Main Panel",
                                "device_role": "master",
                                "slaves": [
                                    {
                                        "id": 456,
                                        "hardware_identifier": "SLAVE-101",
                                        "device_role": "slave",
                                        "master_id": 123,
                                    },
                                    {
                                        "id": 789,
                                        "hardware_identifier": "SLAVE-102",
                                        "device_role": "slave",
                                        "master_id": 123,
                                    },
                                ],
                            }
                        ],
                        response_only=True,
                    )
                ],
            )
        },
    )
    @action(detail=False, methods=["get"], url_path="tree")
    def tree(self, request):
        """List devices as a tree with online masters first."""
        qs = (
            self.get_queryset()
            .select_related("master", "user")
            .prefetch_related("slaves")
        )
        masters = (
            qs.filter(device_role=Device.DeviceRole.MASTER)
            .annotate(
                has_last_seen=models.Case(
                    models.When(last_seen__isnull=False, then=1),
                    default=0,
                    output_field=models.IntegerField(),
                )
            )
            .order_by("-has_last_seen", "-last_seen", "-registered_at")
        )
        ser = DeviceTreeSerializer(masters, many=True)
        return Response(ser.data)

    @extend_schema(
        tags=["Devices"],
        summary="Composite snapshot (master + slaves)",
        description=(
            "Return a composite payload for a master and its slaves using keys compatible with the IoT format.\n\n"
            "- If the 'master' query parameter (hardware identifier) is provided, returns a single composite object.\n"
            "- If omitted, returns a list of composite objects for all masters in the caller's scope.\n\n"
            "Fields:\n"
            "- masterDeviceID: string (hardware identifier of master)\n"
            "- timestamp: epoch seconds derived from last_seen (or null)\n"
            "- smoke: last known smoke level (latest telemetry within freshness window, else 0)\n"
            "- status: device.status (defaults to 'alive' if empty)\n"
            "- slaves: array of { deviceID, timestamp, smoke, status } for each registered slave under the master."
        ),
        parameters=[
            OpenApiParameter(
                name="master",
                description="Master hardware identifier. If omitted, returns all masters",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"], url_path="composite")
    def composite(self, request):
        """Return composite master/slave snapshot(s) matching the IoT payload schema."""
        qs = (
            self.get_queryset()
            .select_related("user")
            .prefetch_related("slaves")
            .filter(device_role=Device.DeviceRole.MASTER)
        )

        master_hid = request.query_params.get("master", "").strip()
        if master_hid:
            qs = qs.filter(hardware_identifier=master_hid)
            master = qs.first()
            if not master:
                return Response({"detail": "master not found"}, status=404)
            return Response(self._composite_for_master(master))

        # No specific master provided: return all masters in scope
        data = [self._composite_for_master(m) for m in qs]
        return Response(data)

    def _composite_for_master(self, master: Device) -> dict:
        """Build a composite object for a master matching the IoT keys."""
        # Helper to compute last smoke within freshness window
        from django.utils import timezone

        def last_smoke(dev: Device) -> int:
            # Use latest telemetry only if within freshness window; else 0
            window = int(getattr(settings, "DEVICE_ONLINE_FRESHNESS_SECONDS", 180))
            t = (
                Telemetry.objects.filter(device=dev, deleted_at__isnull=True)
                .order_by("-timestamp")
                .first()
            )
            if not t:
                return 0
            if t.timestamp and t.timestamp >= timezone.now() - timezone.timedelta(
                seconds=window
            ):
                try:
                    return int(t.smoke_level)
                except Exception:
                    return 0
            return 0

        def to_epoch(dtobj) -> int | None:
            if not dtobj:
                return None
            try:
                return int(dtobj.timestamp())
            except Exception:
                return None

        m_payload = {
            "masterDeviceID": master.hardware_identifier,
            "timestamp": to_epoch(master.last_seen),
            "smoke": last_smoke(master),
            "status": (master.status or "alive"),
            "slaves": [],
        }

        # Load slaves belonging to this master (respecting soft-delete)
        slaves_qs = (
            Device.objects.filter(master_id=master.id, deleted_at__isnull=True)
            .select_related("user", "master")
            .order_by("id")
        )
        for s in slaves_qs:
            m_payload["slaves"].append(
                {
                    "deviceID": s.hardware_identifier,
                    "timestamp": to_epoch(s.last_seen),
                    "smoke": last_smoke(s),
                    "status": (s.status or "alive"),
                }
            )

        return m_payload

    @extend_schema(
        tags=["Telemetry"],
        summary="List telemetry for a device",
        parameters=[
            OpenApiParameter(
                name="id",
                description="Device ID (integer)",
                required=True,
                type=int,
                location=OpenApiParameter.PATH,
            ),
            OpenApiParameter(
                name="since",
                description="ISO8601 datetime or epoch seconds (>=)",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="until",
                description="ISO8601 datetime or epoch seconds (<=)",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
            ),
        ],
    )
    @action(detail=True, methods=["get"], url_path="telemetry")
    def list_telemetry(self, request, pk=None):
        device: Device = self.get_object()
        qs = Telemetry.objects.filter(device=device, deleted_at__isnull=True)

        # time filters
        since = request.query_params.get("since")
        until = request.query_params.get("until")

        tz = timezone.get_current_timezone()

        def to_dt(value):
            if not value:
                return None
            try:
                if value.isdigit():
                    return timezone.datetime.fromtimestamp(int(value), tz=tz)
            except Exception:
                pass
            dt = parse_datetime(value)
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt, tz)
            return dt

        since_dt = to_dt(since)
        until_dt = to_dt(until)
        if since_dt:
            qs = qs.filter(timestamp__gte=since_dt)
        if until_dt:
            qs = qs.filter(timestamp__lte=until_dt)

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = TelemetrySerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = TelemetrySerializer(qs, many=True)
        return Response(ser.data)

    @extend_schema(
        tags=["Alerts"],
        summary="List alerts for a device",
        parameters=[
            OpenApiParameter(
                name="id",
                description="Device ID (integer)",
                required=True,
                type=int,
                location=OpenApiParameter.PATH,
            ),
            OpenApiParameter(
                name="status",
                description="Filter by status: open|resolved",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
            ),
        ],
    )
    @action(detail=True, methods=["get"], url_path="alerts")
    def list_alerts(self, request, pk=None):
        device: Device = self.get_object()
        qs = Alert.objects.filter(device=device, deleted_at__isnull=True)
        status_param = request.query_params.get("status")
        if status_param in {s for s, _ in AlertStatus.choices}:
            qs = qs.filter(status=status_param)

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = AlertSerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = AlertSerializer(qs, many=True)
        return Response(ser.data)


@extend_schema(tags=["Telemetry"])
class TelemetryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TelemetrySerializer
    permission_classes = [IsAuthenticated, IsOwnerOrSuperadmin]
    http_method_names = ["get"]
    queryset = Telemetry.objects.select_related("device", "device__user").filter(
        deleted_at__isnull=True, device__deleted_at__isnull=True
    )

    @extend_schema(
        summary="List telemetry (global)",
        parameters=[
            OpenApiParameter(
                name="device",
                description="Device ID",
                required=False,
                type=int,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="since",
                description="ISO8601 datetime or epoch seconds (>=)",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="until",
                description="ISO8601 datetime or epoch seconds (<=)",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
            ),
        ],
    )
    def get_queryset(self):
        qs = Telemetry.objects.select_related(
            "device",
            "device__user",
            "device__subscription",
        ).filter(deleted_at__isnull=True, device__deleted_at__isnull=True)
        user = self.request.user
        if not getattr(user, "is_authenticated", False):
            return Telemetry.objects.none()
        if not (getattr(user, "role", None) == "superadmin" or user.is_superuser):
            now = timezone.now()
            qs = qs.filter(device__user=user).filter(
                _subscription_access_q(relation="device__subscription", now=now)
            )

        # Filters
        device_id = self.request.query_params.get("device")
        since = self.request.query_params.get("since")  # ISO8601 or epoch seconds
        until = self.request.query_params.get("until")
        if device_id:
            try:
                qs = qs.filter(device_id=int(device_id))
            except Exception:
                pass

        tz = timezone.get_current_timezone()

        def to_dt(value):
            if not value:
                return None
            try:
                # epoch seconds
                if value.isdigit():
                    return timezone.datetime.fromtimestamp(int(value), tz=tz)
            except Exception:
                pass
            dt = parse_datetime(value)
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt, tz)
            return dt

        since_dt = to_dt(since)
        until_dt = to_dt(until)
        if since_dt:
            qs = qs.filter(timestamp__gte=since_dt)
        if until_dt:
            qs = qs.filter(timestamp__lte=until_dt)

        return qs


@extend_schema(tags=["Alerts"])
class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrSuperadmin]
    http_method_names = ["get", "post"]
    queryset = Alert.objects.select_related("device", "device__user").filter(
        deleted_at__isnull=True, device__deleted_at__isnull=True
    )

    @extend_schema(
        summary="List alerts (global)",
        parameters=[
            OpenApiParameter(
                name="device",
                description="Device ID",
                required=False,
                type=int,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="status",
                description="Filter by status: open|resolved",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY,
            ),
        ],
    )
    def get_queryset(self):
        qs = Alert.objects.select_related(
            "device",
            "device__user",
            "device__subscription",
        ).filter(deleted_at__isnull=True, device__deleted_at__isnull=True)
        user = self.request.user
        if not getattr(user, "is_authenticated", False):
            return Alert.objects.none()
        if not (getattr(user, "role", None) == "superadmin" or user.is_superuser):
            now = timezone.now()
            qs = qs.filter(device__user=user).filter(
                _subscription_access_q(relation="device__subscription", now=now)
            )

        # Filters
        device_id = self.request.query_params.get("device")
        status_param = self.request.query_params.get("status")
        if device_id:
            try:
                qs = qs.filter(device_id=int(device_id))
            except Exception:
                pass
        if status_param in {s for s, _ in AlertStatus.choices}:
            qs = qs.filter(status=status_param)
        return qs

    @action(detail=True, methods=["post"], url_path="acknowledge")
    @extend_schema(tags=["Alerts"], summary="Acknowledge an alert")
    def acknowledge(self, request, pk=None):
        alert: Alert = self.get_object()
        if alert.status == AlertStatus.RESOLVED:
            return Response(AlertSerializer(alert).data)

        now = timezone.now()
        update_fields = ["acknowledged_at"]
        alert.acknowledged_at = now

        if getattr(request.user, "is_authenticated", False):
            alert.acknowledged_by = request.user
            update_fields.append("acknowledged_by")

        alert.save(update_fields=update_fields)
        schedule_next_reminder(alert)
        return Response(AlertSerializer(alert).data)

    @action(detail=True, methods=["post"], url_path="resolve")
    @extend_schema(tags=["Alerts"], summary="Resolve an alert")
    def resolve(self, request, pk=None):
        alert: Alert = self.get_object()
        if alert.status == AlertStatus.RESOLVED:
            return Response(AlertSerializer(alert).data)

        now = timezone.now()
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = now

        update_fields = ["status", "resolved_at"]

        if not alert.acknowledged_at:
            alert.acknowledged_at = now
            update_fields.append("acknowledged_at")
        if not alert.acknowledged_by and getattr(
            request.user, "is_authenticated", False
        ):
            alert.acknowledged_by = request.user
            update_fields.append("acknowledged_by")

        alert.save(update_fields=update_fields)
        reset_state_for_alert(alert)
        return Response(AlertSerializer(alert).data)
