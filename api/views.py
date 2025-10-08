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
    summary="Readiness probe with component health checks",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Service is ready with all components healthy",
            examples=[
                OpenApiExample(
                    "healthy",
                    value={
                        "status": "healthy",
                        "timestamp": 1728234567.89,
                        "checks": {
                            "database": {"status": "ok"},
                            "mqtt": {"status": "ok", "connected": True},
                        },
                    },
                    response_only=True,
                )
            ],
        ),
        503: OpenApiResponse(
            description="Service unavailable - critical components failing"
        ),
    },
)
@api_view(["GET"])
def readyz(request):
    """
    Comprehensive health check endpoint for monitoring.

    Returns status of:
    - Database connectivity
    - MQTT connection status
    - Application health

    Use this endpoint for:
    - Load balancer health checks
    - Monitoring/alerting systems
    - DevOps dashboards
    """
    import time
    from django.db import connection
    from rest_framework import status

    health = {"status": "healthy", "timestamp": time.time(), "checks": {}}

    # Database check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health["checks"]["database"] = {
            "status": "ok",
            "message": "Database connection successful",
        }
    except Exception as e:
        health["checks"]["database"] = {"status": "error", "error": str(e)}
        health["status"] = "unhealthy"

    # MQTT check
    try:
        from realtime.mqtt import get_mqtt_status

        mqtt_status = get_mqtt_status()

        if mqtt_status["connected"]:
            health["checks"]["mqtt"] = {
                "status": "ok",
                "connected": True,
                "broker": mqtt_status.get("broker"),
                "port": mqtt_status.get("port"),
                "last_message_time": mqtt_status.get("last_message_time"),
                "connection_time": mqtt_status.get("connection_time"),
            }
        else:
            health["checks"]["mqtt"] = {
                "status": "error",
                "connected": False,
                "error": mqtt_status.get("error", "Not connected"),
            }
            health["status"] = "degraded"

    except Exception as e:
        health["checks"]["mqtt"] = {
            "status": "error",
            "error": f"Failed to get MQTT status: {str(e)}",
        }
        health["status"] = "degraded"

    # Return appropriate HTTP status code
    http_status = status.HTTP_200_OK
    if health["status"] == "unhealthy":
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE

    return Response(health, status=http_status)


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
    # Online if device has reported recently, regardless of reported status.
    # Freshness window is short (seconds): if no data in 2-5s => offline.
    freshness_seconds = getattr(settings, "DEVICE_ONLINE_FRESHNESS_SECONDS", 5)
    window = timedelta(seconds=int(freshness_seconds))
    now = timezone.now()
    user = getattr(request, "user", None)
    base_devices = Device.objects.filter(deleted_at__isnull=True)
    base_alerts = Alert.objects.filter(device__deleted_at__isnull=True)

    # Non-admins only get counts for their own devices
    if not (
        getattr(user, "is_superuser", False)
        or getattr(user, "role", None) == "superadmin"
    ):
        base_devices = base_devices.filter(user=user)
        base_alerts = base_alerts.filter(device__user=user)

    total_devices = base_devices.count()
    open_alerts = base_alerts.filter(status=Alert.Status.OPEN).count()
    online = base_devices.filter(
        last_seen__isnull=False,
        last_seen__gte=now - window,
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
