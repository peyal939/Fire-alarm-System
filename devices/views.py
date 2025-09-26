from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import IsOwnerOrSuperadmin
from .models import Device
from .serializers import DeviceSerializer


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
