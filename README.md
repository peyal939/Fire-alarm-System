## apS Fire Alarm Backend

Django + DRF + Channels monolith for a fire detector IoT platform. It handles users, devices, telemetry, and alerts, with strict telemetry ingestion for registered devices only. A simple login-protected dashboard shows live device updates on a map.

### Key features
- Custom user model (email-based) and JWT for API; session login for web dashboard
- Devices, Telemetry, Alerts domain with owner scoping and soft-delete
- Strict MQTT ingestion (unknown devices are ignored); status derived from telemetry
- Real-time broadcasting via WebSocket (`/ws`) to the dashboard
- REST APIs with filters and pagination, documented at `/docs` and `/redoc`
- Monolithic structure with per-app boundaries; in-memory channel layer by default (no Redis required)

### Tech stack
- Django 5.x, DRF, Channels 4.x, Daphne
- SimpleJWT (API auth), session auth (dashboard)
- MySQL via PyMySQL
- paho-mqtt, python-dotenv
- drf-spectacular (+ sidecar) for OpenAPI docs

---

## Project layout
- `config/` – settings, URLs, ASGI/WSGI
- `api/` – health routes and API routers (auth, devices)
- `accounts/` – custom user model + JWT endpoints
- `devices/` – models, serializers, views for devices/telemetry/alerts
- `realtime/` – dashboard views, MQTT client, Channels consumers
- `templates/` – `index.html` (dashboard), `login.html` (session login)
- `static/` – icons/assets
- `device_simulator.py` – simple MQTT publisher for local testing

---

## Getting started (Windows/PowerShell)

1) Python and dependencies
	 - Use Python 3.12+ (3.13 works). From the project root:
	 - Create and activate a venv, then install requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2) Configure environment
	 - Create a `.env` file (not committed). Example keys used by `settings.py`:

```
DJANGO_SECRET_KEY=change-me
DEBUG=true
ALLOWED_HOSTS=*

# Database (MySQL via PyMySQL)
MYSQL_DATABASE=aps
MYSQL_USER=root
MYSQL_PASSWORD=yourpass
MYSQL_HOST=localhost
MYSQL_PORT=3306

# Channels (optional). Omit to use in-memory channel layer in dev
# REDIS_URL=redis://localhost:6379/0

# MQTT
MQTT_BROKER=localhost
MQTT_PORT=1883
MQTT_TOPIC=aps/fire/data
MQTT_USER=
MQTT_PASS=

# Alerts
SMOKE_ALERT_THRESHOLD=50

# Online/offline freshness (seconds). Default is 180 (3 minutes)
DEVICE_ONLINE_FRESHNESS_SECONDS=180
```

3) Initialize DB

```powershell
python manage.py migrate
python manage.py createsuperuser
```

4) Run the app

```powershell
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

Open http://localhost:8000

---

## Authentication

There are two auth flows:
- Dashboard (web): session login at `/login/` using email + password. Dashboard (`/`) is protected; use the superuser or a registered user.
- API: JWT via SimpleJWT endpoints under `/auth/`.

JWT endpoints:
- `POST /auth/register` – create user (email + password)
- `POST /auth/login` – obtain access/refresh
- `POST /auth/refresh` – refresh token
- `GET /auth/me` – current user details

OpenAPI docs provide request/response examples: `/docs` (Swagger), `/redoc` (ReDoc), schema at `/schema`.

### Role policy
- The `superadmin` role is only assignable via the Django Admin or by creating a superuser.
- API registration ignores any `role`, `is_staff`, or `is_superuser` fields and always creates a non-privileged `user`.
- JWT tokens include a `role` claim for convenience; clients must not rely on being able to escalate privileges via API.

---

## Core APIs (quick reference)

Devices:
- `GET /devices/` – list devices (owned by user)
- `POST /devices/register/` – claim/register a device to the current user
- `GET /devices/{id}/` – retrieve
- `DELETE /devices/{id}/` – soft delete
- `GET /devices/{id}/telemetry/?since=&until=` – device telemetry
- `GET /devices/{id}/alerts/?status=` – device alerts

Telemetry (global, read-only):
- `GET /telemetry/?device=&since=&until=`

Alerts (global, read-only):
- `GET /alerts/?device=&status=`
- `POST /alerts/{id}/resolve/` – mark an alert resolved

Notes:
- `since`/`until` accept ISO8601 (e.g. `2025-01-01T00:00:00Z`) or epoch seconds.
- `status` supports `open` or `resolved`.
- Device register endpoint requires a trailing slash: `/devices/register/`.

---

## MQTT ingestion

- Topic: `MQTT_TOPIC` (default `aps/fire/data`)
- The MQTT client runs in-process and forwards accepted telemetry to the API layer and WebSocket broadcaster.
- Only registered devices are accepted; unknown devices are ignored.

Example payload (JSON):

```json
{
	"hardware_identifier": "DEV123",
	"smoke": 120,
	"status": "alive",
	"timestamp": 1725148800,
	"latitude": 23.78,
	"longitude": 90.41
}
```

Status is derived from telemetry; alerts open when smoke exceeds `SMOKE_ALERT_THRESHOLD` (now 50).

Persistence policy:
- Telemetry rows are persisted only when `smoke` is greater than `SMOKE_ALERT_THRESHOLD` (now 50).
- Low/no smoke readings still update device `status` and `last_seen`, and may resolve alerts, but are not stored in the telemetry table.

Online/offline
- A device is considered online if a message has been received within `DEVICE_ONLINE_FRESHNESS_SECONDS` (default 180s = 3 minutes). Otherwise, it's offline.

Timezone:
- The application uses Asia/Dhaka (GMT+6) for all timestamps.
- Epoch seconds in query params and incoming MQTT telemetry are interpreted in Dhaka time.
- API responses include timezone offsets (e.g., `+0600`).

### Device simulator

```powershell
python device_simulator.py
```

Adjust the script or environment variables to point at your MQTT broker.

---

## WebSocket (dashboard)

- Endpoint: `/ws` (the dashboard auto-selects `ws://` or `wss://` based on the page protocol).
- Message shape (example):

```json
{
	"deviceID": "DEV123",
	"smoke": 120,
	"status": "alive",
	"timestamp": 1725148800,
	"latitude": 23.78,
	"longitude": 90.41
}
```

The dashboard shows a blinking red icon and a bell indicator when any device appears in alert state.

---

## Running tests

```powershell
python manage.py test accounts devices -v 2
```

Tip: run tests by app label to avoid test discovery collisions.

---

## Troubleshooting

- 301/redirect on device register
	- Use `/devices/register/` (note the trailing slash).

- Dashboard 500 about `username`
	- The custom user uses email; templates use `{% firstof request.user.email request.user.get_username %}`.

- MySQL connection errors
	- Verify MySQL is running and credentials in `.env` match. Ensure `PyMySQL` is installed (already in requirements).

- WebSocket not connecting under HTTPS
	- Ensure the page is served via HTTPS and your reverse proxy allows `wss://` to `/ws`.

- Redis in dev
	- Not required. If `REDIS_URL` is unset, Channels uses the in-memory layer.

---

## Optional: Docker

Docker files are included for convenience, but local dev does not require Docker or Redis.

```powershell
# Build and run
docker compose up --build
```

Open http://localhost:6066

The compose file loads environment from `.env`.

---

## License
Internal project. If open-sourcing, add a LICENSE file.
