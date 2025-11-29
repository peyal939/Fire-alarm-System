# APS Fire Alarm System - Backend

> Django + DRF + Channels monolith for an IoT fire detection platform.

**Last Updated:** November 29, 2025  
**Python Version:** 3.12+  
**Django Version:** 5.1.x

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Quick Start (Development)](#quick-start-development)
5. [Environment Variables](#environment-variables)
6. [Database Setup](#database-setup)
7. [Running the Application](#running-the-application)
8. [Management Commands](#management-commands)
9. [API Reference](#api-reference)
10. [Authentication](#authentication)
11. [MQTT Protocol](#mqtt-protocol)
12. [WebSocket (Real-time)](#websocket-real-time)
13. [Background Tasks (Celery)](#background-tasks-celery)
14. [Testing](#testing)
15. [Docker Deployment](#docker-deployment)
16. [Production Deployment](#production-deployment)
17. [Troubleshooting](#troubleshooting)
18. [Key Business Logic](#key-business-logic)
19. [Related Documentation](#related-documentation)
20. [Contacts & Handover Notes](#contacts--handover-notes)

---

## Project Overview

The APS Fire Alarm System is a comprehensive IoT platform for:
- **Device Management:** Register and manage fire detection devices
- **Real-time Monitoring:** Process MQTT telemetry from IoT sensors
- **Smart Alerting:** Automatic smoke detection with configurable thresholds
- **Mesh Networks:** Master-slave device configurations
- **Live Dashboard:** WebSocket-powered real-time monitoring
- **E-commerce:** Product ordering with ShurjoPay payment gateway
- **Subscriptions:** Monthly billing with grace periods
- **Fire Stations:** Bangladesh fire service directory

### Key Features
- Custom email-based user model with three roles: `user`, `company_admin`, `superadmin`
- JWT authentication for API, session auth for web dashboard
- Strict MQTT ingestion (only registered devices accepted)
- Real-time WebSocket broadcasting to dashboard
- Firebase Cloud Messaging (FCM) for push notifications
- OTP-based registration and login
- Soft-delete pattern for audit compliance

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Web Dashboard / API Clients              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Django Application (Daphne ASGI)               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  REST API   │  │  WebSocket  │  │  Web Dashboard      │  │
│  │  (DRF)      │  │  (Channels) │  │  (Templates)        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
        │                 │                    │
        ▼                 ▼                    ▼
┌─────────────┐   ┌─────────────┐      ┌─────────────┐
│   MySQL     │   │   Redis     │      │ Firebase FCM│
│ (Database)  │   │ (Channels + │      │ (Push Notif)│
│             │   │  Celery)    │      │             │
└─────────────┘   └─────────────┘      └─────────────┘
                        ▲
                        │
                ┌───────────────┐
                │ Celery Worker │
                │ + Beat        │
                └───────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    MQTT Broker (Mosquitto)                  │
└─────────────────────────────────────────────────────────────┘
        ▲                                      ▲
        │                                      │
┌───────────────┐                      ┌───────────────┐
│  IoT Device   │                      │  IoT Device   │
│   (Master)    │                      │   (Slave)     │
└───────────────┘                      └───────────────┘
```

### Tech Stack
| Component | Technology |
|-----------|------------|
| Framework | Django 5.1.x |
| API | Django REST Framework |
| WebSocket | Django Channels 4.x |
| ASGI Server | Daphne |
| Database | MySQL (PyMySQL driver) |
| Cache/Broker | Redis |
| Task Queue | Celery |
| MQTT Client | paho-mqtt |
| Auth | SimpleJWT |
| Push Notifications | Firebase Admin SDK |
| Payment Gateway | ShurjoPay |
| API Docs | drf-spectacular (Swagger/ReDoc) |

---

## Project Structure

```
pranisheba-fire-alarm-app-backend/
├── config/                     # Django settings, URLs, ASGI/WSGI
│   ├── settings.py             # Main settings (reads from .env)
│   ├── urls.py                 # Root URL configuration
│   ├── asgi.py                 # ASGI application entry
│   ├── celery.py               # Celery configuration
│   └── wsgi.py                 # WSGI application entry
│
├── accounts/                   # User management & authentication
│   ├── models.py               # Custom User model (email-based)
│   ├── views.py                # Auth endpoints (register, login, OTP)
│   ├── serializers.py          # User serializers
│   └── tests/                  # Account tests
│
├── devices/                    # Core IoT device management
│   ├── models.py               # Device, Telemetry, Alert, DeviceAlarmState
│   ├── views.py                # Device CRUD, telemetry, alerts
│   ├── services.py             # Alert creation, resolution logic
│   ├── alarm_state.py          # Alert state machine
│   ├── tasks.py                # Celery tasks (reminders)
│   ├── constants.py            # Device status constants
│   └── management/commands/    # Custom management commands
│
├── realtime/                   # Real-time features
│   ├── mqtt.py                 # MQTT client & telemetry ingestion
│   ├── consumers.py            # WebSocket consumers
│   ├── device_cache.py         # In-memory device state cache
│   └── apps.py                 # MQTT auto-start on app ready
│
├── notifications/              # Push notifications (FCM)
│   ├── models.py               # FCMDevice, NotificationLog
│   ├── services.py             # FCMService for sending
│   ├── firebase.py             # Firebase Admin SDK init
│   └── sms.py                  # SMS gateway integration
│
├── products/                   # E-commerce (packages & orders)
│   ├── models.py               # Package, Order, OrderFulfillment
│   ├── views.py                # Order management
│   └── services.py             # Order calculations
│
├── subscriptions/              # Device subscriptions & billing
│   ├── models.py               # DeviceSubscription, SubscriptionCharge
│   ├── services.py             # Billing logic
│   └── tasks.py                # Celery tasks (charge generation)
│
├── firestations/               # Bangladesh fire station directory
│   ├── models.py               # Division, District, FireStation
│   └── management/commands/    # Import commands
│
├── otp/                        # OTP management
│   ├── models.py               # PhoneOTP
│   └── services.py             # OTPSessionManager
│
├── shurjopay/                  # Payment gateway integration
│   └── ...                     # ShurjoPay client wrapper
│
├── api/                        # API routing
│   └── urls.py                 # API URL consolidation
│
├── common/                     # Shared utilities
│   ├── permissions.py          # Custom DRF permissions
│   └── decorators.py           # Utility decorators
│
├── templates/                  # Django HTML templates
│   ├── index.html              # Dashboard
│   ├── devices_page.html       # Device management page
│   └── login.html              # Login page
│
├── static/                     # Static assets (CSS, JS, images)
├── staticfiles/                # Collected static (production)
│
├── deployment_guide/           # Production deployment docs
│   ├── DEPLOYMENT_GUIDE.md     # Complete deployment guide
│   ├── DEPLOYMENT_QUICKREF.md  # Quick reference
│   └── nginx-config-production.conf
│
├── data/                       # Data files
│   ├── fire_departments.csv    # Fire station import data
│   └── geo/                    # Geographic data
│
├── requirements.txt            # Python dependencies
├── docker-compose.yml          # Docker configuration
├── Dockerfile                  # Docker image definition
├── manage.py                   # Django management script
├── device_simulator.py         # MQTT device simulator for testing
└── .env                        # Environment variables (not in git)
```

---

## Quick Start (Development)

### Prerequisites
- Python 3.12+ 
- MySQL 8.0+
- Redis (optional for dev, required for production)
- MQTT Broker (Mosquitto or similar)

### Step 1: Clone & Setup Virtual Environment

```powershell
# Clone the repository
git clone <repository-url>
cd pranisheba-fire-alarm-app-backend

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment

Create a `.env` file in the project root (see [Environment Variables](#environment-variables) for all options):

```env
# Minimum required for development
DJANGO_SECRET_KEY=your-secret-key-change-in-production
DEBUG=true
ALLOWED_HOSTS=*

# MySQL Database
MYSQL_DATABASE=aps_fire_alarm
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_HOST=localhost
MYSQL_PORT=3306

# MQTT Broker
MQTT_BROKER=localhost
MQTT_PORT=1883
```

### Step 3: Initialize Database

```powershell
# Run migrations
python manage.py migrate

# Create superuser (admin account)
python manage.py createsuperuser
```

### Step 4: Import Fire Station Data (Optional)

```powershell
python manage.py import_fire_departments
```

### Step 5: Run the Application

**Terminal 1 - Web Server:**
```powershell
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

**Terminal 2 - MQTT Ingestor:**
```powershell
python manage.py run_mqtt_ingestor
```

**Terminal 3 - Celery Worker (if using background tasks):**
```powershell
celery -A config worker -l info
```

**Terminal 4 - Celery Beat (if using scheduled tasks):**
```powershell
celery -A config beat -l info
```

Open http://localhost:8000

---

## Environment Variables

Create a `.env` file in the project root. All variables are loaded via `python-dotenv`.

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | `change-me` | **REQUIRED in production.** Django secret key |
| `DEBUG` | `true` | Set to `false` in production |
| `ALLOWED_HOSTS` | `*` | Comma-separated list of allowed hosts |
| `HOST` | `0.0.0.0` | Server bind host |
| `PORT` | `8000` | Server port |

### Database (MySQL)

| Variable | Default | Description |
|----------|---------|-------------|
| `MYSQL_DATABASE` | `aps` | Database name |
| `MYSQL_USER` | `root` | Database user |
| `MYSQL_PASSWORD` | (empty) | Database password |
| `MYSQL_HOST` | `localhost` | Database host |
| `MYSQL_PORT` | `3306` | Database port |

### Redis & Celery

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | (empty) | Redis URL. If empty, uses in-memory channel layer |
| `CELERY_BROKER_URL` | Uses `REDIS_URL` | Celery broker URL |
| `CELERY_RESULT_BACKEND` | Uses broker URL | Celery result backend |

### MQTT Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER` | `localhost` | MQTT broker hostname |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_TOPIC` | `aps/fire/data` | Telemetry topic |
| `MQTT_DEVICE_REG_TOPIC` | `aps/fire/reg` | Device registration/config topic |
| `MQTT_USER` | (empty) | MQTT username |
| `MQTT_PASS` | (empty) | MQTT password |

### Alert Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SMOKE_ALERT_THRESHOLD` | `50` | Smoke level to trigger alert |
| `DEVICE_ONLINE_FRESHNESS_SECONDS` | `180` | Seconds before device is considered offline |
| `ALERT_REMINDER_INTERVAL_SECONDS` | `600` | Reminder interval (0 to disable) |
| `ALERT_REMINDER_MAX_COUNT` | `3` | Max reminders per alert (0 for unlimited) |
| `ALERT_ACK_ESCALATION_SECONDS` | `600` | Escalation window after acknowledgment |
| `ALERT_AUTO_CLEAR_NORMAL_READINGS` | `1` | Safe readings required to auto-resolve |

### Subscription/Billing

| Variable | Default | Description |
|----------|---------|-------------|
| `SUBSCRIPTION_CYCLE_DAYS` | `30` | Billing cycle length |
| `SUBSCRIPTION_GRACE_DAYS` | `7` | Grace period before suspension |
| `SUBSCRIPTION_DUE_SOON_REMINDER_DAYS` | `5` | Days before due to send reminder |

### JWT Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` | `60` | Access token lifetime |
| `JWT_REFRESH_TOKEN_LIFETIME_DAYS` | `7` | Refresh token lifetime |

### OTP Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OTP_CODE_LENGTH` | `6` | OTP code length |
| `OTP_TTL_SECONDS` | `300` | OTP validity period |
| `OTP_RESEND_COOLDOWN_SECONDS` | `60` | Minimum time between OTP sends |
| `OTP_MAX_VERIFY_ATTEMPTS` | `5` | Max verification attempts |
| `OTP_LOGIN_ENFORCED` | `true` | Require OTP for login |
| `OTP_TEST_BYPASS_CODE` | (empty) | Test bypass code (dev only) |

### SMS Gateway

| Variable | Default | Description |
|----------|---------|-------------|
| `SMS_GATEWAY_URL` | (empty) | SMS gateway URL |
| `SMS_GATEWAY_API_KEY` | (empty) | API key |
| `SMS_GATEWAY_SECRET_KEY` | (empty) | Secret key |
| `SMS_GATEWAY_CALLER_ID` | `praniSheba` | Sender ID |
| `SMS_GATEWAY_ENABLED` | `false` | Enable SMS sending |

### Firebase (FCM)

Place Firebase service account JSON file in project root:
```
fire-alarm-54db1-firebase-adminsdk-fbsvc-3cef306df2.json
```

### ShurjoPay

| Variable | Default | Description |
|----------|---------|-------------|
| `SHURJOPAY_USERNAME` | (empty) | ShurjoPay username |
| `SHURJOPAY_PASSWORD` | (empty) | ShurjoPay password |
| `SHURJOPAY_PREFIX` | (empty) | Order ID prefix |
| `SHURJOPAY_RETURN_URL` | (empty) | Payment return URL |

### MongoDB (Historical Data - Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | (empty) | MongoDB connection string |
| `MONGO_DB_NAME` | `firealarm` | Database name |
| `MONGO_COLLECTION_NAME` | `sensordata` | Collection name |

### CSRF (Production)

| Variable | Default | Description |
|----------|---------|-------------|
| `CSRF_TRUSTED_ORIGINS` | (empty) | Comma-separated trusted origins |

---

## Database Setup

### MySQL Installation

**Windows:**
1. Download MySQL Installer from https://dev.mysql.com/downloads/installer/
2. Install MySQL Server 8.0+
3. Create database:
```sql
CREATE DATABASE aps_fire_alarm CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### Migrations

```powershell
# Create migrations for model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Check migration status
python manage.py showmigrations
```

### Initial Data

```powershell
# Create superuser
python manage.py createsuperuser

# Import fire station data
python manage.py import_fire_departments

# Remove duplicate fire stations (if needed)
python manage.py dedupe_firestations
```

---

## Running the Application

### Development Mode

**Minimum Setup (3 terminals):**

```powershell
# Terminal 1: Web Server (Daphne)
daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Terminal 2: MQTT Ingestor
python manage.py run_mqtt_ingestor

# Terminal 3: Celery Worker (for background tasks)
celery -A config worker -l info
```

**Full Setup (4 terminals):**
```powershell
# Terminal 4: Celery Beat (for scheduled tasks like reminders)
celery -A config beat -l info
```

### Access Points

| URL | Description |
|-----|-------------|
| http://localhost:8000 | Dashboard (requires login) |
| http://localhost:8000/login/ | Login page |
| http://localhost:8000/app/devices | Devices management page |
| http://localhost:8000/docs | Swagger API documentation |
| http://localhost:8000/redoc | ReDoc API documentation |
| http://localhost:8000/schema | OpenAPI schema (YAML) |
| http://localhost:8000/admin/ | Django admin panel |
| ws://localhost:8000/ws | WebSocket endpoint |

---

## Management Commands

### Built-in Commands

```powershell
# Run MQTT ingestor (required for device telemetry)
python manage.py run_mqtt_ingestor

# Send pending alert reminders manually
python manage.py send_alert_reminders

# Import fire department data
python manage.py import_fire_departments

# Remove duplicate fire stations
python manage.py dedupe_firestations

# Collect static files (production)
python manage.py collectstatic --noinput
```

### Django Standard Commands

```powershell
# Database migrations
python manage.py migrate
python manage.py makemigrations

# Create superuser
python manage.py createsuperuser

# Open Django shell
python manage.py shell

# Check for issues
python manage.py check
```

---

## API Reference

### Base URL
```
http://localhost:8000/
```

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register/` | Register new user |
| POST | `/auth/register/init/` | Begin OTP registration |
| POST | `/auth/register/verify/` | Complete OTP registration |
| POST | `/auth/login/` | Login (returns JWT or OTP challenge) |
| POST | `/auth/login/verify/` | Complete OTP login |
| POST | `/auth/refresh/` | Refresh access token |
| GET | `/auth/me/` | Get current user profile |
| PATCH | `/auth/me/` | Update profile |
| POST | `/auth/change-password/` | Change password |
| POST | `/auth/password-reset/init/` | Start password reset |
| POST | `/auth/password-reset/complete/` | Complete password reset |

### Device Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/devices/` | List devices (owner-scoped) |
| POST | `/devices/register/` | Register/claim device |
| GET | `/devices/{id}/` | Get device details |
| PATCH | `/devices/{id}/` | Update device |
| DELETE | `/devices/{id}/` | Soft delete device |
| GET | `/devices/{id}/telemetry/` | Device telemetry history |
| GET | `/devices/{id}/alerts/` | Device alerts |
| POST | `/devices/{id}/phone/` | Set device phone number |
| GET | `/devices/tree/` | Masters with nested slaves |
| GET | `/devices/unclaimed/` | Unclaimed devices from orders |

### Alert Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/alerts/` | List alerts (filterable) |
| GET | `/alerts/{id}/` | Get alert details |
| POST | `/alerts/{id}/acknowledge/` | Acknowledge alert |
| POST | `/alerts/{id}/resolve/` | Resolve alert |

### Telemetry Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/telemetry/` | List telemetry (filterable) |

### Subscription Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/subscriptions/me/` | User's subscriptions |
| GET | `/subscriptions/me/{id}/` | Subscription detail |
| GET | `/subscriptions/me/{id}/charges/` | Subscription charges |
| POST | `/subscriptions/me/{id}/topup/` | Create top-up charge |
| GET | `/subscriptions/admin/` | (Admin) All subscriptions |
| POST | `/subscriptions/admin/{id}/override/` | (Admin) Set override |
| POST | `/subscriptions/admin/{id}/manual-payment/` | (Admin) Record payment |

### Fire Station Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/firestations/divisions/` | List divisions |
| GET | `/firestations/districts/` | List districts |
| GET | `/firestations/stations/` | List fire stations |

### Package & Order Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/packages/` | List packages |
| POST | `/packages/` | (Admin) Create package |
| GET | `/orders/` | User's orders |
| POST | `/orders/` | Create order |
| GET | `/orders/admin/` | (Admin) All orders |

### FCM Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/fcm/devices/` | Register FCM token |
| GET | `/fcm/devices/` | List user's FCM devices |
| DELETE | `/fcm/devices/{id}/` | Unregister device |
| POST | `/fcm/devices/test/` | Send test notification |
| GET | `/fcm/logs/` | Notification history |

### Query Parameters

| Parameter | Endpoints | Description |
|-----------|-----------|-------------|
| `since` | telemetry, alerts | Start date (ISO8601 or epoch) |
| `until` | telemetry, alerts | End date (ISO8601 or epoch) |
| `status` | alerts | `open` or `resolved` |
| `device` | telemetry, alerts | Device ID filter |
| `device_role` | devices | `master` or `slave` |
| `search` | devices | Search by name/ID |

### Full API Documentation

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **OpenAPI Schema:** http://localhost:8000/schema

---

## Authentication

### Two Authentication Methods

1. **JWT (API):** For mobile apps and API clients
2. **Session (Web):** For dashboard login

### JWT Flow

```http
# 1. Login
POST /auth/login/
Content-Type: application/json

{"email": "user@example.com", "password": "secret"}

# Response (if OTP not enforced):
{"access": "eyJ...", "refresh": "eyJ..."}

# Response (if OTP enforced):
{"session_id": "uuid", "otp_sent_to": "****1234", "expires_in": 300}

# 2. Complete OTP (if required)
POST /auth/login/verify/
{"session_id": "uuid", "code": "123456"}

# 3. Use access token
GET /devices/
Authorization: Bearer eyJ...

# 4. Refresh token when expired
POST /auth/refresh/
{"refresh": "eyJ..."}
```

### Role System

| Role | Description | Privileges |
|------|-------------|------------|
| `user` | Regular user | Own devices only |
| `company_admin` | Company admin | Own devices + ordered devices |
| `superadmin` | Super admin | Full system access |

**Important:** Roles can only be assigned via Django Admin or `createsuperuser`. API registration always creates `user` role.

---

## MQTT Protocol

### Topics

| Topic | Default | Direction | Purpose |
|-------|---------|-----------|---------|
| `aps/fire/data` | `MQTT_TOPIC` | Device → Server | Telemetry data |
| `aps/fire/reg` | `MQTT_DEVICE_REG_TOPIC` | Server → Device | Device configuration |

### Telemetry Payload (Device → Server)

**Single Device:**
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

**Master with Slaves (Composite):**
```json
{
  "masterID": "MASTER-001",
  "smoke": 30,
  "status": "alive",
  "timestamp": 1699776000,
  "latitude": 23.8103,
  "longitude": 90.4125,
  "slaves": [
    {"deviceID": "SLAVE-01", "smoke": 55, "status": "alert", "timestamp": 1699775990},
    {"deviceID": "SLAVE-02", "smoke": 20, "status": "alive", "timestamp": 1699775995}
  ]
}
```

### Device Configuration Payload (Server → Device)

```json
{
  "device_id": "FD-ABC123",
  "phoneNumber": "+8801778043119",
  "soundOff": 0
}
```

### Ingestion Rules

1. **Only registered devices accepted** - unknown devices are ignored
2. **Master must exist** - for composite payloads, master must be registered
3. **Slaves must be linked** - each slave must be registered under that master
4. **Telemetry storage** - only saved when smoke > threshold (50)
5. **Timestamps in Dhaka time** - Asia/Dhaka (GMT+6)

### Testing with Device Simulator

```powershell
python device_simulator.py
```

Edit the script to configure broker and device IDs.

---

## WebSocket (Real-time)

### Endpoint
```
ws://localhost:8000/ws
wss://your-domain.com/ws  (production)
```

### Message Format

```json
{
  "deviceID": "FD-ABC123",
  "smoke": 120,
  "status": "alert",
  "timestamp": 1699776000,
  "latitude": 23.8103,
  "longitude": 90.4125,
  "is_online": true,
  "mesh_alert": false
}
```

### Connection Flow

1. Client connects to `/ws`
2. Server sends current state of all devices
3. Server broadcasts updates on telemetry changes
4. Heartbeat ping/pong every 20 seconds

---

## Background Tasks (Celery)

### Required Services

```powershell
# Worker (processes tasks)
celery -A config worker -l info

# Beat (scheduler for periodic tasks)
celery -A config beat -l info
```

### Scheduled Tasks

| Task | Interval | Description |
|------|----------|-------------|
| `send_alert_reminders_task` | 10 minutes | Send reminder notifications for unresolved alerts |
| `generate_due_charges` | 60 minutes | Generate subscription charges |
| `suspend_overdue_subscriptions` | 60 minutes | Suspend unpaid subscriptions |
| `refresh_subscription_statuses` | 120 minutes | Update subscription statuses |
| `send_due_soon_reminders` | Daily | Remind users of upcoming dues |

### Task Configuration

Controlled via environment variables:
- `ALERT_REMINDER_INTERVAL_SECONDS` (set to 0 to disable)
- `SUBSCRIPTION_CHARGE_INTERVAL_MINUTES`
- `SUBSCRIPTION_STATUS_SWEEP_INTERVAL_MINUTES`

---

## Testing

### Run All Tests

```powershell
python manage.py test accounts devices -v 2
```

### Run Specific App Tests

```powershell
# Accounts tests
python manage.py test accounts -v 2

# Devices tests
python manage.py test devices -v 2

# Firestations tests
python manage.py test firestations -v 2
```

### Test Coverage

```powershell
pip install coverage
coverage run manage.py test accounts devices
coverage report
coverage html  # generates htmlcov/index.html
```

---

## Docker Deployment

### Quick Start

```powershell
# Build and run
docker compose up --build

# Run in background
docker compose up -d --build
```

Access at http://localhost:6066

### Docker Compose Services

```yaml
services:
  web:
    build: .
    ports:
      - "6066:8000"
    env_file:
      - .env
```

### Full Production Stack

For production, add Redis and use the deployment guide:
```yaml
services:
  web:
    # ... app container
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  mqtt:
    image: eclipse-mosquitto:2
    ports:
      - "1883:1883"
```

---

## Production Deployment

### Quick Reference

See **[`deployment_guide/DEPLOYMENT_QUICKREF.md`](./deployment_guide/DEPLOYMENT_QUICKREF.md)** for fast deployment commands.

### Full Guide

See **[`deployment_guide/DEPLOYMENT_GUIDE.md`](./deployment_guide/DEPLOYMENT_GUIDE.md)** for complete instructions.

### Production Checklist

- [ ] Set `DEBUG=false`
- [ ] Set secure `DJANGO_SECRET_KEY`
- [ ] Configure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
- [ ] Set up Redis for Channels and Celery
- [ ] Configure Nginx reverse proxy
- [ ] Set up SSL/TLS (Let's Encrypt)
- [ ] Run `collectstatic`
- [ ] Configure systemd services
- [ ] Set up MQTT broker with authentication
- [ ] Configure Firebase credentials
- [ ] Set up database backups

### Nginx Configuration

See **[`deployment_guide/nginx-config-production.conf`](./deployment_guide/nginx-config-production.conf)**

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 301 redirect on device register | Missing trailing slash | Use `/devices/register/` |
| Dashboard 500 about username | Template issue | Already fixed in codebase |
| MySQL connection error | Wrong credentials | Check `.env` database settings |
| WebSocket not connecting | HTTPS/WSS mismatch | Ensure Nginx proxies WSS correctly |
| MQTT not receiving data | Broker not running | Start Mosquitto, check credentials |
| Celery tasks not running | Worker not started | Start `celery -A config worker` |
| Static files 404 | Not collected | Run `python manage.py collectstatic` |
| FCM not working | Missing credentials | Check Firebase JSON file |

### Debug Mode

```powershell
# Check Django configuration
python manage.py check

# Test database connection
python manage.py dbshell

# Verify migrations
python manage.py showmigrations

# Django shell for debugging
python manage.py shell
```

### Log Locations

- Django logs: Console output (configure in settings for file logging)
- Celery logs: Console output of worker/beat
- Nginx logs: `/var/log/nginx/access.log`, `/var/log/nginx/error.log`

---

## Key Business Logic

### Alert Lifecycle

```
Smoke > 50 → Alert Created (open)
    ↓
Notification sent → User sees alert
    ↓
[Acknowledge] → Stops reminders (10 min)
    ↓
[Resolve] or Auto-resolve → Alert closed
```

### Auto-Resolution

Alerts auto-resolve when:
1. Smoke level drops to ≤ threshold
2. Consecutive safe readings (configured by `ALERT_AUTO_CLEAR_NORMAL_READINGS`)

### Subscription States

| State | Description |
|-------|-------------|
| `active` | Subscription current and paid |
| `grace` | Past due, within grace period |
| `suspended` | Access blocked, payment required |

### Master-Slave Rules

1. Slaves MUST have a master (cannot be standalone)
2. Masters MUST NOT have a master
3. Both must belong to same owner (unless superadmin)
4. Slave telemetry requires slave to be pre-registered

---

## Related Documentation

| Document | Location | Description |
|----------|----------|-------------|
| System Documentation | `SYSTEM_DOCUMENTATION.md` | Complete technical reference |
| User Manual | `USER_MANUAL.md` | End-user guide for all roles |
| API Documentation | `FCM_API_DOCUMENTATION.md` | FCM integration details |
| Deployment Guide | `deployment_guide/DEPLOYMENT_GUIDE.md` | Production setup |
| Quick Reference | `deployment_guide/DEPLOYMENT_QUICKREF.md` | Fast deployment commands |
| Architecture | `deployment_guide/ARCHITECTURE_DIAGRAMS.md` | Visual diagrams |
| Postman Collection | `firealarm_postman_collection.json` | API testing collection |
| OpenAPI Schema | `openapi.yaml`, `schema.yaml` | API specifications |

---

## Contacts & Handover Notes

### Project Contacts

| Role | Name | Contact |
|------|------|---------|
| Original Developer | Nahidul Islam Peyal | npeyal045@gmail.com |
| Project Owner |  |  |

### Important Credentials/Secrets

All secrets are stored in `.env` file (not in git). For handover, ensure the new team has:

1. **Database credentials** (MySQL)
2. **Firebase service account JSON file**
3. **ShurjoPay credentials**
4. **SMS Gateway credentials**
5. **MQTT broker credentials**
6. **Production server access**

### Known Issues / Technical Debt

1. [List any known issues]
2. [List any incomplete features]
3. [List any planned improvements]

### Recommended Improvements

1. Add database query optimization for large telemetry tables
2. Implement telemetry data archiving/cleanup job
3. Add unit tests for subscription billing edge cases
4. Consider microservice split for MQTT ingestion at scale

### Third-Party Services

| Service | Purpose | Dashboard/Console |
|---------|---------|-------------------|
| Firebase | Push notifications | https://console.firebase.google.com |
| ShurjoPay | Payment gateway | |
| SMS Gateway | OTP/Alerts | |
| MongoDB (optional) | Historical data | MongoDB Atlas/Compass |

---

## License

Internal project. Add a LICENSE file if open-sourcing.

---

**Happy Coding! 🚀**
