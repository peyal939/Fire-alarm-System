from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import IsOwnerOrSuperadmin
from .models import Device, Telemetry, Alert
from .serializers import DeviceSerializer, TelemetrySerializer, AlertSerializer


class DeviceViewSet(viewsets.ModelViewSet):
    serializer_class = DeviceSerializer
    permission_classes = [IsOwnerOrSuperadmin]
    http_method_names = ["get", "patch", "delete", "post"]

    def get_queryset(self):
        base = Device.objects.select_related("user").filter(deleted_at__isnull=True)
        user = self.request.user
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

    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        hid = str(request.data.get("hardware_identifier", "")).strip()
        name = str(request.data.get("device_name", "")).strip()
        lat = request.data.get("latitude")
        lon = request.data.get("longitude")

        if not hid:
            return Response({"detail": "hardware_identifier is required"}, status=400)

        # Validate optional lat/lon
        def to_decimal(val):
            if val in (
                None,
                "",
            ):
                return None
            try:
                return Decimal(str(val))
            except (InvalidOperation, ValueError):
                return None

        lat_dec = to_decimal(lat)
        lon_dec = to_decimal(lon)

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
        device = Device.objects.create(
            user=request.user,
            hardware_identifier=hid,
            device_name=name,
            latitude=lat_dec,
            longitude=lon_dec,
            created_by=request.user,
        )
        return Response(DeviceSerializer(device).data, status=201)

    @action(detail=True, methods=["get"], url_path="telemetry")
    def list_telemetry(self, request, pk=None):
        device: Device = self.get_object()
        qs = Telemetry.objects.filter(device=device, deleted_at__isnull=True)

        # time filters
        since = request.query_params.get("since")
        until = request.query_params.get("until")
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone

        def to_dt(value):
            if not value:
                return None
            try:
                if value.isdigit():
                    return timezone.datetime.fromtimestamp(int(value), tz=timezone.utc)
            except Exception:
                pass
            dt = parse_datetime(value)
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.utc)
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


class TelemetryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TelemetrySerializer
    permission_classes = [IsOwnerOrSuperadmin]
    http_method_names = ["get"]

    def get_queryset(self):
        qs = Telemetry.objects.select_related("device", "device__user").filter(
            deleted_at__isnull=True, device__deleted_at__isnull=True
        )
        user = self.request.user
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

        def to_dt(value):
            if not value:
                return None
            try:
                # epoch seconds
                if value.isdigit():
                    return timezone.datetime.fromtimestamp(int(value), tz=timezone.utc)
            except Exception:
                pass
            dt = parse_datetime(value)
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.utc)
            return dt

        since_dt = to_dt(since)
        until_dt = to_dt(until)
        if since_dt:
            qs = qs.filter(timestamp__gte=since_dt)
        if until_dt:
            qs = qs.filter(timestamp__lte=until_dt)

        return qs


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertSerializer
    permission_classes = [IsOwnerOrSuperadmin]
    http_method_names = ["get", "post"]

    def get_queryset(self):
        qs = Alert.objects.select_related("device", "device__user").filter(
            deleted_at__isnull=True, device__deleted_at__isnull=True
        )
        user = self.request.user
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
    def resolve(self, request, pk=None):
        alert: Alert = self.get_object()
        if alert.status == Alert.Status.RESOLVED:
            return Response(AlertSerializer(alert).data)
        from django.utils import timezone

        alert.status = Alert.Status.RESOLVED
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["status", "resolved_at"])
        return Response(AlertSerializer(alert).data)
