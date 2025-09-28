from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import status, viewsets, filters
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
from .models import Device, Telemetry, Alert
from .serializers import (
    DeviceSerializer,
    TelemetrySerializer,
    AlertSerializer,
    DeviceRegisterSerializer,
    DeviceTreeSerializer,
)


@extend_schema(tags=["Devices"])
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
            "- Provide `master_id` referencing an existing master device that you own (non-admin users).\n"
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

        # Enforce unique ownership
        existing = Device.objects.filter(
            hardware_identifier=hid, deleted_at__isnull=True
        ).first()
        if existing:
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
            existing.save()
            return Response(DeviceSerializer(existing).data, status=200)

        # Create new and assign to current user
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
        return Response(DeviceSerializer(device).data, status=201)

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
        qs = (
            self.get_queryset()
            .select_related("master", "user")
            .prefetch_related("slaves")
        )
        masters = qs.filter(device_role=Device.DeviceRole.MASTER)
        ser = DeviceTreeSerializer(masters, many=True)
        return Response(ser.data)

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
