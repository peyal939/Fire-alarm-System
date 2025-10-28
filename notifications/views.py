"""Views for FCM device registration and notification management."""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .models import FCMDevice, NotificationLog
from .serializers import (
    FCMDeviceSerializer,
    NotificationLogSerializer,
    TestNotificationSerializer,
)
from .services import FCMService


class FCMDeviceViewSet(viewsets.ModelViewSet):
    """ViewSet for managing FCM device tokens.

    Endpoints:
    - POST /api/fcm/devices/ - Register new FCM token
    - GET /api/fcm/devices/ - List user's registered devices
    - DELETE /api/fcm/devices/{id}/ - Unregister a device
    - POST /api/fcm/devices/test/ - Send test notification
    """

    serializer_class = FCMDeviceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return only the current user's devices."""
        return FCMDevice.objects.filter(user=self.request.user)

    @extend_schema(
        summary="Register FCM device token",
        description=(
            "Register a new FCM device token for push notifications. "
            "If the token already exists, it will be updated with the current user."
        ),
        request=FCMDeviceSerializer,
        responses={201: FCMDeviceSerializer},
    )
    def create(self, request, *args, **kwargs):
        """Register a new FCM device token."""
        return super().create(request, *args, **kwargs)

    @extend_schema(
        summary="List registered devices",
        description="Get all FCM devices registered for the current user",
        responses={200: FCMDeviceSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        """List all registered devices for the current user."""
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Unregister device",
        description="Remove an FCM device token (stop receiving notifications)",
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        """Unregister a device token."""
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        summary="Send test notification",
        description="Send a test push notification to all registered devices",
        request=TestNotificationSerializer,
        responses={
            200: {
                "description": "Test notification sent",
                "examples": {
                    "application/json": {
                        "message": "Test notification sent successfully",
                        "results": {"success": 1, "failure": 0, "invalid_tokens": []},
                    }
                },
            }
        },
    )
    @action(detail=False, methods=["post"])
    def test(self, request):
        """Send a test notification to the user's devices."""
        serializer = TestNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        results = FCMService.send_test_notification(request.user)

        if results["success"] == 0 and results["failure"] == 0:
            return Response(
                {
                    "message": "No active devices found to send notification",
                    "results": results,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {"message": "Test notification sent successfully", "results": results},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Deactivate device token",
        description="Deactivate a device token without deleting it",
        responses={200: FCMDeviceSerializer},
    )
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivate a device token."""
        device = self.get_object()
        device.active = False
        device.save(update_fields=["active"])

        serializer = self.get_serializer(device)
        return Response(serializer.data)

    @extend_schema(
        summary="Activate device token",
        description="Re-activate a previously deactivated device token",
        responses={200: FCMDeviceSerializer},
    )
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Activate a device token."""
        device = self.get_object()
        device.active = True
        device.save(update_fields=["active"])

        serializer = self.get_serializer(device)
        return Response(serializer.data)


class NotificationLogViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing notification history.

    Endpoints:
    - GET /api/fcm/logs/ - List notification history
    - GET /api/fcm/logs/{id}/ - Get specific notification details
    """

    serializer_class = NotificationLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return only the current user's notification logs."""
        return NotificationLog.objects.filter(user=self.request.user)

    @extend_schema(
        summary="List notification history",
        description="Get notification history for the current user",
        parameters=[
            OpenApiParameter(
                name="status",
                description="Filter by status (sent, failed, invalid_token)",
                required=False,
                type=str,
            ),
        ],
        responses={200: NotificationLogSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        """List notification history with optional status filter."""
        queryset = self.get_queryset()

        # Filter by status if provided
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
