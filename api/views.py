from rest_framework.decorators import api_view
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from django.utils import timezone
from datetime import timedelta
from django.conf import settings

from devices.enums import AlertStatus
from devices.models import Device, Alert


FAQ_CONTENT = {
    "categories": [
        {
            "id": "device_setup",
            "title": "Device & Setup",
            "order": 1,
            "questions": [
                {
                    "id": "register-device",
                    "question": "How do I register my fire alarm device?",
                    "answer": "Follow these steps to onboard a new device.",
                    "answer_steps": [
                        "Open the app and select 'Add Device'.",
                        "Enter the unique hardware ID printed on the device or packaging.",
                        "Allow the app to link through the device's built-in GPRS SIM connection.",
                        "Set the device location manually or tap 'Detect My Location'.",
                        "Tap 'Register' to finish the process.",
                    ],
                },
                {
                    "id": "multiple-devices",
                    "question": "Can I connect multiple devices to one account?",
                    "answer": (
                        "Yes. You can pair any number of master and slave devices with your account. "
                        "Master units operate independently, while slave units extend coverage as part of a mesh network."
                    ),
                },
                {
                    "id": "master-vs-slave",
                    "question": "What's the difference between master and slave devices?",
                    "answer": (
                        "Master devices function on their own and coordinate a device group. "
                        "Slave devices attach to a master to broaden protection through mesh networking."
                    ),
                },
                {
                    "id": "device-online",
                    "question": "How do I know if my device is online?",
                    "answer": (
                        "Any device that has reported data in the last three minutes is treated as online. "
                        "In the app, online devices display a green status indicator."
                    ),
                },
            ],
        },
        {
            "id": "alerts_notifications",
            "title": "Alerts & Notifications",
            "order": 2,
            "questions": [
                {
                    "id": "alert-timing",
                    "question": "When will I receive fire alerts?",
                    "answer": (
                        "Push notifications are issued immediately whenever smoke levels exceed the configured threshold "
                        "(50 by default). Alerts are generated the moment elevated readings are detected."
                    ),
                },
                {
                    "id": "unacknowledged-alert",
                    "question": "What happens if I don't acknowledge an alert?",
                    "answer": (
                        "If an alert remains unacknowledged, the system sends reminder notifications every 10 minutes, "
                        "up to three times, until you acknowledge it or the alert resolves."
                    ),
                },
                {
                    "id": "stop-reminders",
                    "question": "How do I stop receiving reminders?",
                    "answer": (
                        "Tap the alert to acknowledge it. Once smoke levels return to normal, the alert auto-resolves "
                        "and reminder notifications stop."
                    ),
                },
            ],
        },
        {
            "id": "account_security",
            "title": "Account & Security",
            "order": 3,
            "questions": [
                {
                    "id": "update-contact",
                    "question": "Can I change my email or phone number?",
                    "answer": "Yes. Open the Settings screen in the app to update your profile details at any time.",
                },
                {
                    "id": "relocate-device",
                    "question": "Can I relocate my device to a different room?",
                    "answer": (
                        "Yes. Update the device name and GPS coordinates in device settings so the dashboard reflects the new location."
                    ),
                },
                {
                    "id": "device-offline",
                    "question": "What should I do if my device shows offline?",
                    "answer": (
                        "Confirm the device has power and network connectivity. If it stays offline for more than five minutes, "
                        "restart the unit and check again."
                    ),
                },
                {
                    "id": "delete-device",
                    "question": "How do I delete a device from my account?",
                    "answer": (
                        "Open the device settings and choose 'Delete Device'. This action is permanent—re-adding the device "
                        "requires a fresh registration."
                    ),
                },
            ],
        },
        {
            "id": "billing_packages",
            "title": "Billing & Packages",
            "order": 4,
            "questions": [
                {
                    "id": "service-cost",
                    "question": "How much does the service cost?",
                    "answer": (
                        "We offer multiple packages tailored to different device counts. Visit the app's 'Packages' section "
                        "for current pricing and monthly fees."
                    ),
                },
                {
                    "id": "payment-methods",
                    "question": "What payment methods are accepted?",
                    "answer": (
                        "Payments are processed through ShurjoPay, supporting bKash, Nagad, major credit/debit cards, and mobile banking."
                    ),
                },
                {
                    "id": "cancel-order",
                    "question": "Can I cancel my order?",
                    "answer": (
                        "Orders can be cancelled before payment is completed. If payment has already been made, contact support for assistance."
                    ),
                },
            ],
        },
        {
            "id": "technical",
            "title": "Technical",
            "order": 5,
            "questions": [
                {
                    "id": "smoke-threshold",
                    "question": "What is the smoke threshold for alerts?",
                    "answer": (
                        "The default threshold is 50 on a 0–100 scale. Readings above this value trigger a fire alert, "
                        "though you can adjust the threshold based on device calibration."
                    ),
                },
                {
                    "id": "telemetry-frequency",
                    "question": "How often does my device send data?",
                    "answer": (
                        "Devices typically transmit telemetry every 30 to 60 seconds when active and may reduce frequency during normal conditions to conserve power."
                    ),
                },
                {
                    "id": "offline-behavior",
                    "question": "Does the app work without internet?",
                    "answer": (
                        "The app needs an internet connection for real-time alerts and updates. Devices continue monitoring offline and deliver pending alerts once connectivity returns."
                    ),
                },
            ],
        },
    ]
}


ABOUT_CONTENT = {
    "company": "adorsho praniSheba Limited",
    "overview": (
        "adorsho praniSheba Limited is an AgriTech company using IoT-enabled livestock monitoring, "
        "digital animal identification, and smart data insights to support farmers across Bangladesh. "
        "Our connected devices track health, movement, and shed conditions in real time—helping farmers protect their animals, "
        "reduce losses, and improve productivity."
    ),
    "contact": {
        "address": "Haque Tower, Mohakhali, Dhaka",
        "phone": "+8809643207003",
        "website": "https://pranisheba.com.bd",
        "facebook": "https://facebook.com/adorshopranisheba",
        "linkedin": "https://linkedin.com/company/adorsho-pranisheba-ltd",
    },
}


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
    open_alerts = base_alerts.filter(status=AlertStatus.OPEN).count()
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


@extend_schema(
    tags=["Content"],
    summary="FAQ content",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Frequently asked questions grouped by category",
            examples=[
                OpenApiExample(
                    "faq",
                    value=FAQ_CONTENT,
                    response_only=True,
                )
            ],
        )
    },
)
@api_view(["GET"])
def faq_content(request):
    return Response(FAQ_CONTENT)


@extend_schema(
    tags=["Content"],
    summary="About us content",
    responses={
        200: OpenApiResponse(
            response=OpenApiTypes.OBJECT,
            description="Company overview, mission, and focus areas",
            examples=[
                OpenApiExample(
                    "about",
                    value=ABOUT_CONTENT,
                    response_only=True,
                )
            ],
        )
    },
)
@api_view(["GET"])
def about_content(request):
    return Response(ABOUT_CONTENT)
