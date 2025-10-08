"""Constants and custom exceptions for the devices app.

This module centralizes string literals, enums, and custom exception classes
to improve code maintainability and error handling across the application.
"""

from __future__ import annotations


# ==================== Alert Type Constants ====================
class AlertType:
    """Constants for alert types used throughout the system."""

    SMOKE_HIGH = "smoke_high"
    DEVICE_STATUS = "device_status"

    # All valid alert types
    ALL = [SMOKE_HIGH, DEVICE_STATUS]


# ==================== Device Status Constants ====================
class DeviceStatus:
    """Constants for device operational status."""

    ALIVE = "alive"
    ALERT = "alert"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


# ==================== MQTT and Telemetry Constants ====================
class MQTTPayloadKeys:
    """Keys used in MQTT payload parsing."""

    DEVICE_ID = "deviceID"
    MASTER_DEVICE_ID = "masterDeviceID"
    MASTER_ID = "masterID"
    TIMESTAMP = "timestamp"
    SMOKE = "smoke"
    STATUS = "status"
    SLAVES = "slaves"
    ID = "id"


# ==================== Custom Exceptions ====================
class DeviceError(Exception):
    """Base exception for device-related errors."""

    pass


class DeviceNotFoundError(DeviceError):
    """Raised when a device with given identifier is not found."""

    def __init__(self, hardware_identifier: str):
        self.hardware_identifier = hardware_identifier
        super().__init__(f"Device '{hardware_identifier}' not found or deleted")


class UnregisteredDeviceError(DeviceError):
    """Raised when attempting to ingest telemetry for an unregistered device."""

    def __init__(self, hardware_identifier: str):
        self.hardware_identifier = hardware_identifier
        super().__init__(f"Device '{hardware_identifier}' is not registered")


class InvalidMasterSlaveRelationshipError(DeviceError):
    """Raised when slave device doesn't belong to specified master."""

    def __init__(self, slave_id: str, master_id: str):
        self.slave_id = slave_id
        self.master_id = master_id
        super().__init__(
            f"Slave '{slave_id}' is not registered under master '{master_id}'"
        )


class TelemetryIngestionError(Exception):
    """Base exception for telemetry ingestion errors."""

    pass


class InvalidTelemetryPayloadError(TelemetryIngestionError):
    """Raised when MQTT payload is malformed or missing required fields."""

    def __init__(self, reason: str, payload: dict = None):
        self.reason = reason
        self.payload = payload
        super().__init__(f"Invalid telemetry payload: {reason}")


class MQTTProcessingError(Exception):
    """Raised when MQTT message processing fails."""

    def __init__(self, message: str, original_exception: Exception = None):
        self.original_exception = original_exception
        super().__init__(message)


# ==================== Alert Processing Exceptions ====================
class AlertError(Exception):
    """Base exception for alert-related errors."""

    pass


class AlertResolutionError(AlertError):
    """Raised when alert resolution fails."""

    def __init__(self, alert_id: int, reason: str):
        self.alert_id = alert_id
        self.reason = reason
        super().__init__(f"Failed to resolve alert {alert_id}: {reason}")


class MeshAlertError(AlertError):
    """Raised when mesh alert computation fails."""

    def __init__(self, device_id: int | str, reason: str):
        self.device_id = device_id
        self.reason = reason
        super().__init__(f"Mesh alert error for device {device_id}: {reason}")


# ==================== WebSocket/Channels Exceptions ====================
class WebSocketBroadcastError(Exception):
    """Raised when WebSocket broadcast fails (non-fatal)."""

    def __init__(self, device_id: str, reason: str):
        self.device_id = device_id
        self.reason = reason
        super().__init__(f"Failed to broadcast update for device {device_id}: {reason}")


# ==================== Helper Functions ====================
def is_valid_alert_type(alert_type: str) -> bool:
    """Check if the given string is a valid alert type."""
    return alert_type in AlertType.ALL


def normalize_device_status(status: str | None) -> str:
    """Normalize device status to lowercase and handle None values."""
    if not status:
        return DeviceStatus.UNKNOWN
    return str(status).strip().lower()
