from rest_framework.decorators import api_view
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from django.utils import timezone
from datetime import timedelta
from django.conf import settings

from devices.models import Device, Alert


@extend_schema(
    tags=["System"],
    summary="Liveness probe",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Service is alive",
            examples=[OpenApiExample("ok", value={"status": "ok"}, response_only=True)],
        )
    },
)
@api_view(["GET"])
def healthz(request):
    return Response({"status": "ok"})


@extend_schema(
    tags=["System"],
    summary="Readiness probe",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Service is ready",
            examples=[
                OpenApiExample("ready", value={"status": "ready"}, response_only=True)
            ],
        )
    },
)
@api_view(["GET"])
def readyz(request):
    return Response({"status": "ready"})


@extend_schema(
    tags=["Metrics"],
    summary="Dashboard metrics summary",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Counts for dashboard KPIs",
            examples=[
                OpenApiExample(
                    "metrics",
                    value={
                        "total_devices": 12,
                        "open_alerts": 3,
                        "online": 9,
                        "offline": 3,
                    },
                    response_only=True,
                )
            ],
        )
    },
)
@api_view(["GET"])
def metrics_summary(request):
    # Online if device has reported recently AND last known status is 'alive'.
    # Freshness window is short (seconds) to meet requirement: no data in 2-5s => offline.
    freshness_seconds = getattr(settings, "DEVICE_ONLINE_FRESHNESS_SECONDS", 5)
    window = timedelta(seconds=int(freshness_seconds))
    now = timezone.now()
    total_devices = Device.objects.filter(deleted_at__isnull=True).count()
    open_alerts = Alert.objects.filter(
        status=Alert.Status.OPEN, device__deleted_at__isnull=True
    ).count()
    online = Device.objects.filter(
        deleted_at__isnull=True,
        last_seen__isnull=False,
        last_seen__gte=now - window,
        status__iexact="alive",
    ).count()
    offline = max(total_devices - online, 0)
    return Response(
        {
            "total_devices": total_devices,
            "open_alerts": open_alerts,
            "online": online,
            "offline": offline,
        }
    )
