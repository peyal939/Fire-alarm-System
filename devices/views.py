from __future__ import annotations

from decimal import Decimal, InvalidOperation
import logging

from django.db import models, transaction
from django.utils import timezone
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
)

from . import services
from .models import Device, Telemetry, Alert
from .serializers import (
    DeviceSerializer,
    TelemetrySerializer,
    AlertSerializer,
    DeviceRegisterSerializer,
    DeviceTreeSerializer,
    DevicePhoneUpdateSerializer,
)
from .constants import DeviceConfigurationPublishError

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


class DeviceViewSet(viewsets.ModelViewSet):
    serializer_class = DeviceSerializer
    # Require authentication first to avoid AnonymousUser reaching queryset resolution
    permission_classes = [IsAuthenticated, IsOwnerOrSuperadmin]
    http_method_names = ["get", "patch", "delete", "post"]
    # Provide a base queryset so schema generators can infer model/lookup types
    queryset = Device.objects.select_related("user").filter(deleted_at__isnull=True)
    # Constrain lookup to digits and document path param as integer
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        base = Device.objects.select_related("user").filter(deleted_at__isnull=True)
        user = self.request.user
        # Safety guard: if somehow unauthenticated slips through, return empty set
        if not getattr(user, "is_authenticated", False):
            return Device.objects.none()
        if getattr(user, "role", None) == "superadmin" or user.is_superuser:
            return base
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
        queryset = queryset.order_by(
            models.F("last_seen").desc(nulls_last=True),
            "-registered_at",  # Secondary sort by registration time
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

    def destroy(self, request, *args, **kwargs):
        instance: Device = self.get_object()
        instance.deleted_at = timezone.now()
        instance.deleted_by = request.user
        instance.save(update_fields=["deleted_at", "deleted_by"])
        return Response(status=status.HTTP_204_NO_CONTENT)

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
        hid = ser.validated_data["hardware_identifier"].strip()
        name = ser.validated_data.get("device_name", "").strip()
        lat_dec = ser.validated_data.get("latitude")
        lon_dec = ser.validated_data.get("longitude")
        role = ser.validated_data.get("device_role") or Device.DeviceRole.MASTER
        master = ser.validated_data.get("master")  # set in serializer when role==slave

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
            if existing.user != request.user and not (
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
            existing.save()

            # Broadcast the updated device to WebSocket clients
            _broadcast_new_device(existing)

            return Response(DeviceSerializer(existing).data, status=200)

        # Check for soft-deleted device with the same hardware_identifier
        soft_deleted = Device.objects.filter(
            hardware_identifier=hid, deleted_at__isnull=False
        ).first()

        if soft_deleted:
            # Un-delete (restore) the device and reassign to current user
            soft_deleted.deleted_at = None
            soft_deleted.deleted_by = None
            soft_deleted.user = request.user
            soft_deleted.created_by = request.user
            soft_deleted.created_at = timezone.now()
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

            soft_deleted.save()
            _broadcast_new_device(soft_deleted)
            return Response(DeviceSerializer(soft_deleted).data, status=201)

        device = Device(
            user=request.user,
            hardware_identifier=hid,
            device_name=name,
            latitude=lat_dec,
            longitude=lon_dec,
            created_by=request.user,
            device_role=role,
        )
        if role == Device.DeviceRole.SLAVE:
            device.master = master
        device.save()

        _broadcast_new_device(device)
        return Response(DeviceSerializer(device).data, status=201)

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
        return Response(self.get_serializer(device).data, status=200)

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
        masters = qs.filter(device_role=Device.DeviceRole.MASTER).order_by(
            models.F("last_seen").desc(nulls_last=True), "-registered_at"
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
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone

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
        if status_param in {s for s, _ in Alert.Status.choices}:
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
        qs = Telemetry.objects.select_related("device", "device__user").filter(
            deleted_at__isnull=True, device__deleted_at__isnull=True
        )
        user = self.request.user
        if not getattr(user, "is_authenticated", False):
            return Telemetry.objects.none()
        if not (getattr(user, "role", None) == "superadmin" or user.is_superuser):
            qs = qs.filter(device__user=user)

        # Filters
        device_id = self.request.query_params.get("device")
        since = self.request.query_params.get("since")  # ISO8601 or epoch seconds
        until = self.request.query_params.get("until")
        if device_id:
            try:
                qs = qs.filter(device_id=int(device_id))
            except Exception:
                pass

        from django.utils.dateparse import parse_datetime
        from django.utils import timezone

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
        qs = Alert.objects.select_related("device", "device__user").filter(
            deleted_at__isnull=True, device__deleted_at__isnull=True
        )
        user = self.request.user
        if not getattr(user, "is_authenticated", False):
            return Alert.objects.none()
        if not (getattr(user, "role", None) == "superadmin" or user.is_superuser):
            qs = qs.filter(device__user=user)

        # Filters
        device_id = self.request.query_params.get("device")
        status_param = self.request.query_params.get("status")
        if device_id:
            try:
                qs = qs.filter(device_id=int(device_id))
            except Exception:
                pass
        if status_param in {s for s, _ in Alert.Status.choices}:
            qs = qs.filter(status=status_param)
        return qs

    @action(detail=True, methods=["post"], url_path="resolve")
    @extend_schema(tags=["Alerts"], summary="Resolve an alert")
    def resolve(self, request, pk=None):
        alert: Alert = self.get_object()
        if alert.status == Alert.Status.RESOLVED:
            return Response(AlertSerializer(alert).data)
        from django.utils import timezone

        alert.status = Alert.Status.RESOLVED
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["status", "resolved_at"])
        return Response(AlertSerializer(alert).data)
