# APS Fire Alarm System - Complete Documentation

**Version:** 1.0.0  
**Last Updated:** November 11, 2025  
**System Type:** IoT Fire Detection & Alert Platform

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Overview](#system-overview)
3. [Business Rules & Domain Logic](#business-rules--domain-logic)
4. [Technical Architecture](#technical-architecture)
5. [Core Components](#core-components)
6. [API Reference](#api-reference)
7. [Security & Authentication](#security--authentication)
8. [Data Models](#data-models)
9. [Real-time Communication](#real-time-communication)
10. [Alert & Notification System](#alert--notification-system)
11. [Deployment & Operations](#deployment--operations)
12. [Configuration Reference](#configuration-reference)

---

## Executive Summary

The APS Fire Alarm System is a comprehensive IoT platform for monitoring fire detection devices, processing real-time telemetry data, managing alerts, and coordinating emergency responses. The system supports both standalone devices and mesh networks (master-slave configurations), provides real-time dashboard updates via WebSocket, and integrates with Firebase Cloud Messaging for mobile push notifications.

### Key Capabilities

- **Device Management:** Register and manage fire detection devices with owner-based access control
- **Real-time Monitoring:** Process MQTT telemetry streams from IoT sensors
- **Smart Alerting:** Automatic smoke detection with configurable thresholds and escalation rules
- **Mesh Networks:** Support for master-slave device configurations
- **Mobile Integration:** REST API for mobile applications with JWT authentication
- **Live Dashboard:** WebSocket-powered real-time monitoring interface
- **E-commerce:** Integrated product ordering and payment gateway (ShurjoPay)
- **Emergency Services:** Pre-loaded Bangladesh fire station directory

---

## System Overview

### Architecture Pattern

**Monolithic Django Application** with:
- Django REST Framework for API endpoints
- Django Channels for WebSocket communication
- Celery for background task processing
- MQTT client for IoT device ingestion
- MySQL for persistent storage
- Redis for Channels layer and Celery broker

### User Roles

1. **User (Client):** 
   - Can register/manage their own devices
   - Receive alerts for their devices
   - View their device dashboard
   - Purchase device packages

2. **Super Admin:**
   - Full system access
   - Can manage all users and devices
   - Access to admin panel
   - Cross-user device assignment capabilities

### Device Types

1. **Master Device:**
   - Standalone device or head of a mesh network
   - Reports its own telemetry
   - Can coordinate with slave devices
   - Must not have a parent master

2. **Slave Device:**
   - Part of a mesh network
   - Reports through or alongside master
   - Must be linked to a master device
   - Must belong to same owner as master

---

## Business Rules & Domain Logic

### 1. Device Registration & Ownership

#### Registration Rules
- Devices register via MQTT on topic `aps/fire/reg` (default)
- Hardware identifier must be unique system-wide
- Device must provide valid hardware ID and user email
- User must exist in system before device can register
- Registration creates device record with "pending" or "alive" status

#### Ownership Rules
- Devices belong to a single user (owner)
- Owner is determined at registration time
- Only device owner can view/manage their devices (except superadmins)
- Slave devices MUST belong to same user as their master
- Superadmins can assign slaves to masters across users (special case)

#### Device Hierarchy
- Master devices cannot have a parent master (master FK must be NULL)
- Slave devices MUST reference a master device (master FK required)
- Self-referencing is prohibited (device cannot be its own master)
- Circular references are prevented by role validation

### 2. Telemetry Processing

#### Data Ingestion
- Telemetry arrives via MQTT on topic `aps/fire/data` (default)
- Only **registered** devices can submit telemetry (strict validation)
- Unknown devices are silently ignored (logged as warnings)
- Each telemetry reading includes:
  - Smoke level (integer)
  - Device status (string: "alive", "alert", etc.)
  - Timestamp (Unix epoch seconds)
  - Optional: GPS coordinates (latitude/longitude)

#### Payload Formats

**Legacy Single-Device Format:**
```json
{
  "deviceID": "FD-ABC123",
  "smoke": 45,
  "status": "alive",
  "timestamp": 1699776000,
  "latitude": 23.8103,
  "longitude": 90.4125
}
```

**Composite Master-Slave Format:**
```json
{
  "deviceID": "FD-MASTER01",
  "smoke": 30,
  "status": "alive",
  "timestamp": 1699776000,
  "latitude": 23.8103,
  "longitude": 90.4125,
  "slaves": [
    {
      "deviceID": "FD-SLAVE01",
      "smoke": 55,
      "status": "alert",
      "timestamp": 1699775990
    },
    {
      "deviceID": "FD-SLAVE02",
      "smoke": 20,
      "status": "alive",
      "timestamp": 1699775995
    }
  ]
}
```

#### Online/Offline Detection
- Device is **online** if `last_seen` is within freshness window
- Default freshness window: **180 seconds** (3 minutes)
- Configurable via `DEVICE_ONLINE_FRESHNESS_SECONDS` env variable
- Derived dynamically (not stored as field)
- Slaves require own timestamp to be marked fresh (configurable)

### 3. Alert Management

#### Smoke Alert Triggering
- Alert triggers when `smoke_level > SMOKE_ALERT_THRESHOLD`
- Default threshold: **50** (configurable via env)
- Alert type: `smoke_high`
- Creates new `Alert` record with status `open`

#### Alert Lifecycle States
1. **Open:** Alert is active and unresolved
2. **Resolved:** Alert has been cleared (either auto or manual)

#### Auto-Resolution Rules
- Requires consecutive "safe" readings (smoke ≤ threshold)
- Number of safe readings required: `ALERT_AUTO_CLEAR_NORMAL_READINGS` (default: 1)
- When threshold met, alert status changes to `resolved`
- Resolved timestamp is recorded
- Safe reading streak resets on next high reading

#### Manual Actions
- **Acknowledge:** User/admin marks alert as acknowledged
  - Does NOT resolve the alert
  - Stops immediate reminders
  - Triggers escalation timer if configured
  - Records acknowledger and timestamp

- **Resolve:** Manually close the alert
  - Changes status to `resolved`
  - Stops all reminders
  - Records resolution timestamp

### 4. Notification & Reminder System

#### Immediate Push Notifications
- Triggered when NEW alert is created (not on updates)
- Sent to device owner via Firebase Cloud Messaging (FCM)
- Includes alert details and device information
- Also sent to nearby fire stations (if configured)

#### Reminder Cadence
- Periodic reminders for **unresolved** alerts
- Interval: `ALERT_REMINDER_INTERVAL_SECONDS` (default: 600 = 10 minutes)
- Set to `0` to disable reminders
- Managed by Celery Beat scheduler

#### Reminder Limits
- Maximum reminders per alert: `ALERT_REMINDER_MAX_COUNT` (default: 3)
- Set to `0` for unlimited reminders
- Counter increments each time reminder is sent

#### Acknowledgment Escalation
- When alert is acknowledged but unresolved
- Escalation delay: `ALERT_ACK_ESCALATION_SECONDS` (default: 600 = 10 minutes)
- If set to `0`, escalation is disabled
- After escalation window, reminders resume

#### Reminder Logic Flow
```
Alert Created → Immediate Push
    ↓
Not Acknowledged → Reminder every N seconds (up to max count)
    ↓
Acknowledged → Wait escalation window → Resume reminders
    ↓
Resolved → All reminders stop
```

### 5. Mesh Network Alerting

#### Mesh Alert Flag
- Dashboard shows `mesh_alert: true` if ANY device in network has open alert
- Mesh = Master + all its Slaves
- Used for visual indicators (red/yellow status)
- Computed in real-time during broadcasts

#### Alert Propagation
- Each device maintains its own alerts
- Slave alerts are independent of master alerts
- Mesh alert flag aggregates status across network
- Owner receives notifications for alerts on any device they own

### 6. Soft Delete Pattern

#### Soft Delete Behavior
- Records are never physically deleted from database
- `deleted_at` timestamp marks deletion
- `deleted_by` references user who performed deletion
- Queries automatically filter `deleted_at IS NULL`
- Audit trail preserved for compliance

#### Restoration
- Records can be un-deleted by clearing `deleted_at`
- No built-in UI for restoration (admin database access required)

### 7. Product & Order Management

#### Packages
- Pre-defined device packages with pricing
- Includes: device quantity range, price per device, monthly fee (MRF)
- Managed by superadmins
- Soft-delete enabled

#### Order Lifecycle
1. **Pending:** Order created, awaiting payment
2. **Paid:** Payment successful (via ShurjoPay)
3. **Delivered:** Devices shipped to customer
4. **Failed/Cancelled:** Payment failed or order cancelled

#### Payment Integration
- ShurjoPay gateway integration
- Supports BDT currency
- Transaction IDs tracked
- Gateway responses stored as JSON

### 8. Fire Station Directory

#### Hierarchical Structure
```
Division (e.g., Dhaka)
  └── District (e.g., Dhaka Metro)
      └── Fire Station (e.g., Mirpur Station)
```

#### Contact Management
- Bilingual support (Bengali & English)
- Multiple contact numbers per station
- Stored as pipe-delimited strings (`|`)
- Exposed via API for mobile apps

---

## Technical Architecture

### Technology Stack

#### Backend Framework
- **Django 5.x:** Core web framework
- **Django REST Framework:** API endpoints
- **Django Channels 4.x:** WebSocket support
- **Daphne:** ASGI server
- **Celery:** Asynchronous task processing
- **Celery Beat:** Scheduled task execution

#### Databases & Caching
- **MySQL:** Primary persistent storage
- **Redis:** Channels layer + Celery broker + device cache
- **PyMySQL:** MySQL driver for Python

#### IoT & Messaging
- **paho-mqtt:** MQTT client for device communication
- **Firebase Admin SDK:** Push notifications

#### API Documentation
- **drf-spectacular:** OpenAPI 3.0 schema generation
- **Swagger UI:** Interactive API docs at `/docs`
- **ReDoc:** Alternative docs at `/redoc`

#### Development Tools
- **python-dotenv:** Environment variable management
- **phonenumbers:** Phone number validation

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Mobile Apps / Web Clients               │
│                    (REST API / WebSocket Consumers)             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      Django Application (Daphne)                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   REST API   │  │  WebSocket   │  │  Dashboard   │         │
│  │   (DRF)      │  │  (Channels)  │  │  (Templates) │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└─────────────────────────────────────────────────────────────────┘
           │                    │                   │
           ↓                    ↓                   ↓
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│     MySQL       │   │     Redis       │   │  Firebase FCM   │
│  (Persistent)   │   │  (Channels +    │   │  (Push Notif)   │
│                 │   │   Celery)       │   │                 │
└─────────────────┘   └─────────────────┘   └─────────────────┘
                              ↑
                              │
                    ┌─────────────────┐
                    │  Celery Worker  │
                    │  + Beat         │
                    └─────────────────┘
                              ↑
                              │ (Alert Reminders)
                              
┌─────────────────────────────────────────────────────────────────┐
│                      MQTT Broker (External)                     │
│                  (Mosquitto / HiveMQ / etc.)                    │
└─────────────────────────────────────────────────────────────────┘
           ↑                                          ↑
           │                                          │
    ┌──────────────┐                         ┌──────────────┐
    │  IoT Device  │                         │  IoT Device  │
    │   (Master)   │                         │   (Slave)    │
    └──────────────┘                         └──────────────┘
```

### Request Flow

#### 1. Device Telemetry Ingestion
```
IoT Device → MQTT Broker → Django MQTT Client (mqtt.py)
    → Validate Device → Store Telemetry → Trigger Alert Logic
    → Broadcast WebSocket Update → Update Device Cache
    → Send FCM Push (if new alert)
```

#### 2. API Request (Mobile App)
```
Mobile App → JWT Auth → DRF ViewSet → Business Logic (services.py)
    → Database (MySQL) → Response Serializer → JSON Response
```

#### 3. WebSocket Real-time Updates
```
Client Connects → Join "devices" Channel Group
    → Receive Initial State (all devices)
    → Listen for Updates → Receive JSON Messages
    → Heartbeat Ping/Pong (every 20s)
```

#### 4. Alert Reminder Cycle
```
Celery Beat (every N seconds) → send_alert_reminders_task
    → Query Unresolved Alerts → Check Reminder Eligibility
    → Send FCM Push → Update reminder_count & last_reminder_at
    → Schedule Next Reminder
```

---

## Core Components

### 1. Accounts (`accounts/`)

**Purpose:** User management and authentication

**Models:**
- `User`: Custom email-based user model
  - Fields: `email`, `password`, `phone_number`, `full_name`, `address`, `role`
  - Roles: `user`, `superadmin`
  - Soft-delete enabled
  - Django permissions integration

**Key Endpoints:**
- `POST /auth/register/`: User registration
- `POST /auth/login/`: JWT token generation
- `POST /auth/refresh/`: Refresh access token
- `GET /auth/me/`: Current user profile
- `PATCH /auth/me/`: Update own profile

**Authentication Flow:**
- Email-based login (no username)
- JWT tokens for API (SimpleJWT)
- Session auth for dashboard (Django built-in)
- Password hashing via Django's `make_password`

### 2. Devices (`devices/`)

**Purpose:** Core IoT device, telemetry, and alert management

**Models:**

**`Device`**
- Hardware identifier (unique)
- Owner reference (ForeignKey to User)
- Device role: `master` or `slave`
- Master reference (self-referencing FK)
- GPS coordinates (latitude, longitude)
- Status, last_seen, registered_at
- Soft-delete enabled

**`Telemetry`**
- Device reference
- Smoke level (integer)
- Device status (string)
- Timestamp (device-provided)
- Received timestamp (server-side)
- Soft-delete enabled

**`Alert`**
- Device reference
- Alert type (e.g., `smoke_high`)
- Status: `open` or `resolved`
- Triggered/resolved timestamps
- Acknowledgment tracking
- Reminder tracking (count, last sent)
- Soft-delete enabled

**`DeviceAlarmState`**
- One-to-one with Device
- Tracks active alert
- Safe reading streak counter
- Next reminder timestamp

**Key Services (`services.py`):**
- `create_alert()`: Create new alert with notifications
- `resolve_alert()`: Close alert (manual or auto)
- `acknowledge_alert()`: Mark alert as seen
- Alert reminder eligibility checks

**Key Functions (`alarm_state.py`):**
- `record_high_smoke()`: Process high smoke reading
- `record_safe_smoke()`: Process safe reading, check auto-resolution
- State machine for alert lifecycle

### 3. Realtime (`realtime/`)

**Purpose:** MQTT ingestion and WebSocket broadcasting

**MQTT Client (`mqtt.py`):**
- Connects to broker on startup
- Subscribes to telemetry + registration topics
- Validates incoming device IDs against database
- Parses legacy & composite payloads
- Stores telemetry in database
- Broadcasts updates via Channels
- Health check endpoint tracking

**WebSocket Consumer (`consumers.py`):**
- `DeviceConsumer`: Handles `/ws` connections
- Joins `devices` channel group
- Sends initial device states on connect
- Receives real-time updates from MQTT client
- Implements heartbeat (ping/pong)
- Error handling to prevent crashes

**Device Cache (`device_cache.py`):**
- In-memory storage of latest device states
- Used for initial WebSocket payload
- Reduces database load on new connections
- Backed by Redis when available

### 4. Notifications (`notifications/`)

**Purpose:** Push notification delivery via Firebase

**Models:**

**`FCMDevice`**
- User reference
- Registration token (from mobile app)
- Device type (Android/iOS)
- Active status
- Last used timestamp

**`NotificationLog`**
- Audit trail for all push notifications
- Records success/failure
- Stores error messages
- Links to user and FCM device

**Services (`services.py`):**
- `FCMService.send_to_user()`: Send push to all user devices
- `FCMService.send_to_device()`: Send to specific device token
- Auto-deactivation of invalid tokens
- Platform-specific configuration (Android/iOS)

**Firebase Setup (`firebase.py`):**
- Initialize Firebase Admin SDK
- Load service account credentials
- Health check for Firebase connectivity

### 5. Fire Stations (`firestations/`)

**Purpose:** Bangladesh fire service directory

**Models:**
- `Division`: Top-level administrative regions (Dhaka, Chittagong, etc.)
- `District`: Sub-divisions within regions
- `FireStation`: Individual fire service offices with contact info

**Key Features:**
- Bilingual support (Bengali & English)
- Hierarchical filtering
- Contact number parsing
- RESTful API for mobile apps

### 6. Products (`products/`)

**Purpose:** E-commerce for device packages

**Models:**

**`Package`**
- Name, description
- Min/max device quantity
- Price per device
- Monthly recurring fee (MRF)
- Soft-delete enabled

**`Order`**
- User reference
- Package reference
- Quantity, amount
- Customer details (name, address, phone)
- Order status (pending, paid, delivered, failed)
- Payment gateway integration
- Soft-delete enabled

### 7. ShurjoPay (`shurjopay/`)

**Purpose:** Payment gateway integration

**Services:**
- Initialize payment session
- Verify payment callback
- Update order status
- Transaction logging

---

## API Reference

### Authentication Endpoints

#### Register User
```http
POST /auth/register/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "phone_number": "+8801712345678"
}

Response 201:
{
  "id": 1,
  "email": "user@example.com",
  "phone_number": "+8801712345678",
  "role": "user"
}
```

#### Login (Get JWT Tokens)
```http
POST /auth/login/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123!"
}

Response 200:
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

#### Refresh Access Token
```http
POST /auth/refresh/
Content-Type: application/json

{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}

Response 200:
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

#### Get Current User Profile
```http
GET /auth/me/
Authorization: Bearer <access_token>

Response 200:
{
  "id": 1,
  "email": "user@example.com",
  "phone_number": "+8801712345678",
  "role": "user",
  "full_name": "John Doe",
  "address": "123 Main St, Dhaka",
  "devices": [
    {
      "id": 1,
      "hardware_identifier": "FD-ABC123",
      "device_name": "Kitchen Detector",
      "device_role": "master",
      "latitude": "23.810300",
      "longitude": "90.412500",
      "status": "alive",
      "last_seen": "2025-11-11T10:30:00+06:00"
    }
  ]
}
```

### Device Endpoints

#### List My Devices
```http
GET /api/devices/
Authorization: Bearer <access_token>

Query Parameters:
- search: Filter by hardware_identifier or device_name
- device_role: Filter by role (master, slave)
- status: Filter by status
- page: Page number (default: 1)
- page_size: Results per page (default: 50)

Response 200:
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [...]
}
```

#### Create Device (Manual Registration)
```http
POST /api/devices/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "hardware_identifier": "FD-XYZ789",
  "device_name": "Living Room Detector",
  "device_role": "master",
  "latitude": "23.810300",
  "longitude": "90.412500"
}

Response 201:
{
  "id": 2,
  "hardware_identifier": "FD-XYZ789",
  ...
}
```

#### Get Device Details
```http
GET /api/devices/{id}/
Authorization: Bearer <access_token>

Response 200:
{
  "id": 1,
  "hardware_identifier": "FD-ABC123",
  "device_name": "Kitchen Detector",
  "device_role": "master",
  "latitude": "23.810300",
  "longitude": "90.412500",
  "phone_number": "+8801712345678",
  "status": "alive",
  "last_seen": "2025-11-11T10:30:00+06:00",
  "registered_at": "2025-11-01T08:00:00+06:00",
  "user": 1,
  "master": null
}
```

#### Update Device
```http
PATCH /api/devices/{id}/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "device_name": "Main Kitchen Detector",
  "phone_number": "+8801799999999"
}

Response 200:
{...}
```

#### Delete Device (Soft Delete)
```http
DELETE /api/devices/{id}/
Authorization: Bearer <access_token>

Response 204: No Content
```

### Telemetry Endpoints

#### List Device Telemetry
```http
GET /api/devices/{device_id}/telemetry/
Authorization: Bearer <access_token>

Query Parameters:
- start_date: Filter by timestamp >= (ISO format)
- end_date: Filter by timestamp <=
- page, page_size: Pagination

Response 200:
{
  "count": 100,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 1,
      "device": 1,
      "smoke_level": 45,
      "device_status": "alive",
      "timestamp": "2025-11-11T10:30:00+06:00",
      "received_at": "2025-11-11T10:30:01+06:00"
    }
  ]
}
```

### Alert Endpoints

#### List Device Alerts
```http
GET /api/devices/{device_id}/alerts/
Authorization: Bearer <access_token>

Query Parameters:
- status: Filter by status (open, resolved)
- alert_type: Filter by type (smoke_high)

Response 200:
{
  "count": 5,
  "results": [
    {
      "id": 1,
      "device": 1,
      "alert_type": "smoke_high",
      "status": "open",
      "triggered_at": "2025-11-11T10:25:00+06:00",
      "last_triggered_at": "2025-11-11T10:25:00+06:00",
      "resolved_at": null,
      "acknowledged_at": null,
      "acknowledged_by": null,
      "reminder_count": 2,
      "last_reminder_at": "2025-11-11T10:35:00+06:00"
    }
  ]
}
```

#### Acknowledge Alert
```http
POST /api/alerts/{alert_id}/acknowledge/
Authorization: Bearer <access_token>

Response 200:
{
  "id": 1,
  "status": "open",
  "acknowledged_at": "2025-11-11T10:40:00+06:00",
  "acknowledged_by": 1
}
```

#### Resolve Alert
```http
POST /api/alerts/{alert_id}/resolve/
Authorization: Bearer <access_token>

Response 200:
{
  "id": 1,
  "status": "resolved",
  "resolved_at": "2025-11-11T10:45:00+06:00"
}
```

### Fire Station Endpoints

#### List Divisions
```http
GET /api/firestations/divisions/
Authorization: Bearer <access_token>

Response 200:
[
  {
    "id": 1,
    "name_bn": "ঢাকা",
    "name_en": "Dhaka",
    "slug": "dhaka"
  }
]
```

#### List Districts in Division
```http
GET /api/firestations/districts/?division={division_id}
Authorization: Bearer <access_token>

Response 200:
[...]
```

#### List Fire Stations
```http
GET /api/firestations/stations/
Authorization: Bearer <access_token>

Query Parameters:
- division: Filter by division ID
- district: Filter by district ID
- search: Search by name

Response 200:
[
  {
    "id": 1,
    "district": {...},
    "name_bn": "মিরপুর ফায়ার স্টেশন",
    "name_en": "Mirpur Fire Station",
    "contact_numbers": "+8801234567890|+8801234567891",
    "contact_number_list": ["+8801234567890", "+8801234567891"]
  }
]
```

### FCM Device Registration

#### Register FCM Token
```http
POST /api/notifications/register-device/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "registration_token": "fcm_token_from_mobile_app",
  "device_type": "android",
  "device_name": "Pixel 7 Pro"
}

Response 201:
{
  "id": 1,
  "registration_token": "fcm_token...",
  "device_type": "android",
  "active": true
}
```

---

## Security & Authentication

### JWT Token Management

#### Token Lifetimes (Configurable)
- **Access Token:** Default 60 minutes (configurable via `JWT_ACCESS_TOKEN_LIFETIME_MINUTES`)
- **Refresh Token:** Default 7 days (configurable via `JWT_REFRESH_TOKEN_LIFETIME_DAYS`)
- For "lifetime" sessions, set very high values:
  - Access: `525600` (1 year)
  - Refresh: `3650` (10 years)

#### Token Structure
```json
{
  "token_type": "access",
  "exp": 1699779600,
  "iat": 1699776000,
  "jti": "a1b2c3d4...",
  "user_id": 1,
  "email": "user@example.com",
  "role": "user"
}
```

#### Token Usage
- Include in Authorization header: `Authorization: Bearer <token>`
- Refresh before expiration using refresh token
- No automatic blacklisting (stateless JWT)

### Permission System

#### API Permissions
- **IsAuthenticated:** Required for all API endpoints (default)
- **IsAdminUser:** Required for admin-only endpoints (user management, etc.)
- **IsOwnerOrAdmin:** Custom permission for device/alert access

#### Owner-Based Access Control
- Users can only access their own devices, telemetry, alerts
- Exception: Superadmins can access all resources
- Enforced in ViewSet querysets:
  ```python
  queryset = Device.objects.filter(user=request.user)
  ```

### Dashboard Session Auth

#### Login Flow
1. User visits `/login/`
2. Submits email + password
3. Django authenticates and creates session
4. Redirects to dashboard (`/`)
5. Session cookie maintains authentication

#### Session Security
- CSRF protection enabled
- Secure cookie (HTTPS only in production)
- HTTPOnly flag set
- SameSite policy

### MQTT Security

#### Device Validation
- All incoming MQTT messages validate device registration
- Unknown devices are rejected (not stored)
- Prevents unauthorized data injection

#### Broker Credentials
- Username/password authentication (optional)
- Configured via `MQTT_USER` and `MQTT_PASS`
- TLS/SSL support (configure broker-side)

### Firebase Security

#### Service Account
- Private key stored in JSON file (not committed)
- Path: `fire-alarm-54db1-firebase-adminsdk-fbsvc-3cef306df2.json`
- Must be kept secure, never expose publicly
- Gitignored by default

#### Token Validation
- FCM tokens validated on first use
- Invalid tokens auto-deactivated
- Prevents spam to inactive devices

---

## Data Models

### Entity Relationship Diagram

```
User (accounts.User)
  │
  ├──< Device (devices.Device)
  │     │
  │     ├──< Telemetry (devices.Telemetry)
  │     ├──< Alert (devices.Alert)
  │     ├──  DeviceAlarmState (devices.DeviceAlarmState) [1-to-1]
  │     └──  Device.master [self-reference]
  │
  ├──< FCMDevice (notifications.FCMDevice)
  ├──< NotificationLog (notifications.NotificationLog)
  └──< Order (products.Order)

Division (firestations.Division)
  └──< District (firestations.District)
        └──< FireStation (firestations.FireStation)

Package (products.Package)
  └──< Order (products.Order)
```

### Key Constraints

#### Database Constraints
- `Device.hardware_identifier`: UNIQUE
- `User.email`: UNIQUE
- `Device.master`: CHECK (NULL if role=master, NOT NULL if role=slave)
- `Device.user`: CHECK (slave.user_id == master.user_id OR creator is superadmin)

#### Application-Level Validation
- Self-referencing devices prevented (clean method)
- Role consistency enforced (master/slave rules)
- Phone number format validation (via phonenumbers library)

### Indexing Strategy

#### High-Traffic Queries
- `Device.user` + `deleted_at`: Owner lookups
- `Device.hardware_identifier`: MQTT ingestion
- `Telemetry.device` + `timestamp`: Time-series queries
- `Alert.device` + `status`: Active alert checks
- `DeviceAlarmState.next_reminder_at`: Reminder scheduling

#### Composite Indexes
```sql
CREATE INDEX idx_device_user_deleted ON devices_device(user_id, deleted_at);
CREATE INDEX idx_telemetry_device_ts ON devices_telemetry(device_id, timestamp);
CREATE INDEX idx_alert_device_status ON devices_alert(device_id, status);
```

---

## Real-time Communication

### WebSocket Protocol

#### Connection Endpoint
```
ws://localhost:8000/ws/
```

#### Connection Flow
1. Client initiates WebSocket connection
2. Server accepts and adds to `devices` group
3. Server sends initial state (all devices)
4. Client receives real-time updates
5. Heartbeat ping/pong every 20 seconds

#### Message Types

**Initial State (on connect):**
```json
{
  "type": "device_update",
  "deviceID": "FD-ABC123",
  "smoke": 45,
  "status": "alive",
  "timestamp": 1699776000,
  "timestamp_iso": "2025-11-11T10:30:00+06:00",
  "latitude": 23.8103,
  "longitude": 90.4125,
  "online": true,
  "mesh_alert": false
}
```

**Real-time Update:**
```json
{
  "type": "device_update",
  "deviceID": "FD-ABC123",
  "smoke": 55,
  "status": "alert",
  ...
}
```

**Device Removed:**
```json
{
  "type": "device_removed",
  "deviceID": "FD-ABC123"
}
```

**Heartbeat:**
```json
// Client → Server
{"type": "ping"}

// Server → Client
{"type": "pong"}
```

### Channels Layer Configuration

#### Redis (Production)
```python
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": ["redis://localhost:6379/0"],
            "capacity": 1000,  # Max messages per channel
            "expiry": 60,      # Message TTL
        }
    }
}
```

#### In-Memory (Development)
```python
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
        "CONFIG": {
            "capacity": 1000,
            "expiry": 60
        }
    }
}
```

### Broadcasting Mechanism

```python
# In mqtt.py after processing telemetry
channel_layer = get_channel_layer()
async_to_sync(channel_layer.group_send)(
    "devices",
    {
        "type": "device_update",
        "device": {
            "deviceID": "FD-ABC123",
            "smoke": 55,
            ...
        }
    }
)
```

---

## Alert & Notification System

### Alert State Machine

```
[No Alert] 
    ↓ smoke > threshold
[Alert Created] → Immediate Push Notification
    ↓
[Open + Unacknowledged] → Reminders every N seconds
    ↓
[Open + Acknowledged] → Wait escalation window
    ↓
[Open + Escalated] → Resume reminders
    ↓
[Resolved] → All reminders stop
```

### Reminder Eligibility Logic

```python
def is_reminder_due(alert: Alert) -> bool:
    # Skip if resolved
    if alert.status != Alert.Status.OPEN:
        return False
    
    # Check max reminder count
    max_count = settings.ALERT_REMINDER_MAX_COUNT
    if max_count > 0 and alert.reminder_count >= max_count:
        return False
    
    # Check if acknowledged and escalation disabled
    if alert.acknowledged_at and settings.ALERT_ACK_ESCALATION_SECONDS == 0:
        return False
    
    # Check next reminder time
    state = DeviceAlarmState.objects.filter(active_alert=alert).first()
    if state and state.next_reminder_at:
        return timezone.now() >= state.next_reminder_at
    
    return True
```

### Push Notification Format

#### High Smoke Alert
```json
{
  "notification": {
    "title": "🔥 Fire Alert - Kitchen Detector",
    "body": "High smoke detected (Level: 85). Please check immediately!"
  },
  "data": {
    "alert_id": "123",
    "device_id": "1",
    "hardware_id": "FD-ABC123",
    "smoke_level": "85",
    "timestamp": "1699776000",
    "type": "smoke_high"
  },
  "android": {
    "priority": "high",
    "notification": {
      "sound": "alert_sound",
      "channel_id": "fire_alerts",
      "priority": "high"
    }
  }
}
```

### Celery Task Scheduling

#### Beat Schedule
```python
CELERY_BEAT_SCHEDULE = {
    "send_alert_reminders": {
        "task": "devices.tasks.send_alert_reminders_task",
        "schedule": timedelta(seconds=600),  # Every 10 minutes
    }
}
```

#### Worker Execution
```bash
# Start Celery worker
celery -A config worker -l info

# Start Celery beat scheduler
celery -A config beat -l info
```

---

## Deployment & Operations

### Environment Setup

#### Required Environment Variables
```bash
# Django Core
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=false
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Database
MYSQL_DATABASE=aps
MYSQL_USER=aps_user
MYSQL_PASSWORD=secure_password
MYSQL_HOST=db_host
MYSQL_PORT=3306

# Redis
REDIS_URL=redis://redis_host:6379/0

# MQTT
MQTT_BROKER=mqtt.yourdomain.com
MQTT_PORT=1883
MQTT_TOPIC=aps/fire/data
MQTT_DEVICE_REG_TOPIC=aps/fire/reg
MQTT_USER=mqtt_username
MQTT_PASS=mqtt_password

# Alert Configuration
SMOKE_ALERT_THRESHOLD=50
ALERT_AUTO_CLEAR_NORMAL_READINGS=1
ALERT_REMINDER_INTERVAL_SECONDS=600
ALERT_REMINDER_MAX_COUNT=3
ALERT_ACK_ESCALATION_SECONDS=600
DEVICE_ONLINE_FRESHNESS_SECONDS=180

# JWT Configuration
JWT_ACCESS_TOKEN_LIFETIME_MINUTES=60
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7

# Celery
CELERY_BROKER_URL=redis://redis_host:6379/0
CELERY_RESULT_BACKEND=redis://redis_host:6379/0

# CSRF (for production)
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

### Docker Deployment

#### Docker Compose Setup
```yaml
version: '3.8'

services:
  db:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: rootpass
      MYSQL_DATABASE: aps
      MYSQL_USER: aps_user
      MYSQL_PASSWORD: aps_pass
    volumes:
      - mysql_data:/var/lib/mysql
    ports:
      - "3306:3306"

  redis:
    image: redis:7
    ports:
      - "6379:6379"

  web:
    build: .
    command: daphne -b 0.0.0.0 -p 8000 config.asgi:application
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - db
      - redis

  celery_worker:
    build: .
    command: celery -A config worker -l info
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      - db
      - redis

  celery_beat:
    build: .
    command: celery -A config beat -l info
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      - db
      - redis

volumes:
  mysql_data:
```

### Production Checklist

#### Pre-Deployment
- [ ] Set `DEBUG=false`
- [ ] Configure proper `ALLOWED_HOSTS`
- [ ] Generate strong `DJANGO_SECRET_KEY`
- [ ] Set up MySQL with proper credentials
- [ ] Configure Redis for Channels + Celery
- [ ] Set up MQTT broker (Mosquitto/HiveMQ)
- [ ] Configure Firebase service account
- [ ] Set CSRF trusted origins
- [ ] Review alert thresholds and intervals

#### Security Hardening
- [ ] Enable HTTPS (TLS/SSL certificates)
- [ ] Configure secure session cookies
- [ ] Restrict database access (firewall rules)
- [ ] Use strong passwords for all services
- [ ] Keep Firebase service account file secure
- [ ] Enable MQTT authentication
- [ ] Set up proper CORS policies
- [ ] Implement rate limiting (optional)

#### Monitoring & Logging
- [ ] Configure Django logging to file/syslog
- [ ] Set up MQTT health checks
- [ ] Monitor Celery task queue
- [ ] Track database query performance
- [ ] Monitor WebSocket connection count
- [ ] Alert on high error rates

### Database Migrations

```bash
# Create migrations after model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Rollback to specific migration
python manage.py migrate devices 0005_previous_migration
```

### Static Files Collection

```bash
# Collect static files for production
python manage.py collectstatic --noinput
```

### Backup Strategy

#### Database Backup
```bash
# Dump MySQL database
mysqldump -u aps_user -p aps > backup_$(date +%Y%m%d).sql

# Restore from backup
mysql -u aps_user -p aps < backup_20251111.sql
```

#### Redis Persistence
- Enable RDB snapshots in redis.conf
- Configure AOF (Append-Only File) for durability

---

## Configuration Reference

### Alert Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SMOKE_ALERT_THRESHOLD` | `50` | Smoke level that triggers alert |
| `ALERT_AUTO_CLEAR_NORMAL_READINGS` | `1` | Consecutive safe readings to auto-resolve |
| `ALERT_REMINDER_INTERVAL_SECONDS` | `600` | Time between reminders (0 = disabled) |
| `ALERT_REMINDER_MAX_COUNT` | `3` | Max reminders per alert (0 = unlimited) |
| `ALERT_ACK_ESCALATION_SECONDS` | `600` | Delay before resuming reminders after ACK (0 = disabled) |

### Device Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVICE_ONLINE_FRESHNESS_SECONDS` | `180` | Time window for device to be considered online |
| `SLAVE_REQUIRE_OWN_TIMESTAMP` | `true` | Require slave timestamp in composite payload |

### JWT Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` | `60` | Access token validity period |
| `JWT_REFRESH_TOKEN_LIFETIME_DAYS` | `7` | Refresh token validity period |

### WebSocket Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBSOCKET_SERVER_HEARTBEAT_SECONDS` | `20` | Heartbeat ping interval (0 = disabled) |

### MQTT Topics

| Topic | Purpose |
|-------|---------|
| `aps/fire/data` | Telemetry ingestion (default) |
| `aps/fire/reg` | Device registration (default) |

---

## Troubleshooting

### Common Issues

#### 1. MQTT Not Receiving Data
**Symptoms:** No telemetry updates, devices show offline

**Solutions:**
- Check MQTT broker is running and accessible
- Verify `MQTT_BROKER` and `MQTT_PORT` settings
- Test connection: `mosquitto_sub -h localhost -t 'aps/fire/#'`
- Check device is publishing to correct topic
- Review Django logs for connection errors

#### 2. WebSocket Not Updating
**Symptoms:** Dashboard not showing real-time updates

**Solutions:**
- Verify Redis is running (if using Redis channel layer)
- Check Daphne is running (not runserver)
- Open browser console for WebSocket errors
- Test connection: `wscat -c ws://localhost:8000/ws/`
- Ensure firewall allows WebSocket traffic

#### 3. Reminders Not Sending
**Symptoms:** No push notifications for alerts

**Solutions:**
- Check Celery worker and beat are running
- Verify `ALERT_REMINDER_INTERVAL_SECONDS > 0`
- Check Firebase credentials are valid
- Review `NotificationLog` for error messages
- Ensure FCM device tokens are registered

#### 4. Device Not Registering
**Symptoms:** Device publishes but doesn't appear in system

**Solutions:**
- Check user email exists in system
- Verify hardware ID is unique
- Review MQTT logs for validation errors
- Check device is publishing to registration topic
- Ensure JSON payload is valid

### Health Checks

#### MQTT Status
```http
GET /realtime/mqtt-health/

Response:
{
  "connected": true,
  "last_message_time": "2025-11-11T10:30:00",
  "connection_time": "2025-11-11T08:00:00",
  "broker": "localhost",
  "port": 1883
}
```

#### Database Connection
```bash
python manage.py check --database default
```

#### Redis Connection
```bash
redis-cli ping
# Should respond: PONG
```

### Logs

#### Django Application Logs
```bash
# Console output (development)
tail -f logs/django.log

# Specific app logs
tail -f logs/devices.log
tail -f logs/mqtt.log
```

#### MQTT Client Logs
```python
# Enable debug logging in settings.py
LOGGING = {
    'loggers': {
        'realtime.mqtt': {
            'level': 'DEBUG',
        },
    },
}
```

#### Celery Logs
```bash
# Worker logs
celery -A config worker -l debug

# Beat logs
celery -A config beat -l debug
```

---

## Performance Optimization

### Database Optimization

#### Query Optimization
- Use `select_related()` for foreign keys
- Use `prefetch_related()` for many-to-many and reverse FKs
- Add database indexes for frequent queries
- Avoid N+1 queries in serializers

#### Connection Pooling
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'CONN_MAX_AGE': 600,  # Persistent connections
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_ALL_TABLES'",
            'charset': 'utf8mb4',
        },
    }
}
```

### Caching Strategy

#### Device State Cache
- Redis-backed in-memory cache
- Reduces database load for WebSocket connections
- TTL: 60 seconds
- Invalidated on telemetry updates

#### API Response Caching (Optional)
```python
from django.views.decorators.cache import cache_page

@cache_page(60 * 5)  # Cache for 5 minutes
def device_list(request):
    ...
```

### Channels Layer Tuning

#### Capacity Settings
```python
CHANNEL_LAYERS = {
    'default': {
        'CONFIG': {
            'capacity': 1000,  # Increase for high-traffic systems
            'expiry': 60,      # Message TTL
        }
    }
}
```

### Celery Concurrency

```bash
# Multiple workers for parallel processing
celery -A config worker -l info --concurrency=4
```

---

## Testing

### Running Tests

```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test devices
python manage.py test realtime

# Run with coverage
coverage run --source='.' manage.py test
coverage report
coverage html
```

### Test Device Simulator

```bash
# Simulate device telemetry
python device_simulator.py
```

---

## Changelog & Version History

### Version 1.0.0 (Current)
- Initial production release
- Core device management
- MQTT telemetry ingestion
- WebSocket real-time updates
- Alert system with reminders
- Firebase push notifications
- Product ordering & payment
- Fire station directory
- Configurable JWT lifetimes

---

## Support & Maintenance

### Code Review Checklist
- [ ] All models have proper indexes
- [ ] Soft-delete applied where needed
- [ ] Owner-based access control enforced
- [ ] Input validation on all endpoints
- [ ] Error handling and logging
- [ ] Tests cover critical paths
- [ ] Documentation updated

### Regular Maintenance Tasks
- Weekly: Review error logs
- Monthly: Database backup verification
- Monthly: Dependency updates (security patches)
- Quarterly: Performance audit
- Yearly: Firebase credentials rotation

---

## Appendix

### Glossary

- **Master Device:** Standalone fire detector or head of mesh network
- **Slave Device:** Auxiliary detector linked to a master
- **Mesh Network:** Group of devices (1 master + N slaves) working together
- **Telemetry:** Sensor data (smoke level, status, timestamp)
- **Alert:** Triggered event when smoke exceeds threshold
- **Reminder:** Scheduled push notification for unresolved alerts
- **Soft Delete:** Logical deletion (flagging) instead of physical removal
- **FCM:** Firebase Cloud Messaging for push notifications
- **MQTT:** Message Queuing Telemetry Transport protocol for IoT

### References

- Django Documentation: https://docs.djangoproject.com/
- DRF Documentation: https://www.django-rest-framework.org/
- Channels Documentation: https://channels.readthedocs.io/
- MQTT Protocol: https://mqtt.org/
- Firebase Admin SDK: https://firebase.google.com/docs/admin/setup

---

**End of Documentation**
