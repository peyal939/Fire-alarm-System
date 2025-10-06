# 🏗️ Architecture: Before vs After Fixes

## Current (Broken) Architecture in Staging

```
Internet
   │
   │ HTTPS
   │
   ▼
[Linux Server]
   │
   │ Port 6066
   │
   ▼
┌─────────────────────────────────┐
│   Docker: fire_alarm_app        │
│   (Daphne ASGI Server)          │
│                                 │
│   ❌ No static file serving     │
│   ❌ MQTT thread unstable       │
│   ❌ WebSocket not configured   │
│   ❌ In-memory channel layer    │
└─────────────────────────────────┘
   │
   ▼
[MySQL Database]


Problems:
1. Admin CSS returns 404 (Daphne doesn't serve static files)
2. MQTT crashes silently (no monitoring/auto-restart)
3. WebSocket fails (missing upgrade headers)
4. No live data (MQTT not processing)
5. Empty dashboard (all above issues combined)
```

---

## Fixed Production Architecture

```
Internet
   │
   │ HTTPS (443)
   │
   ▼
┌──────────────────────────────────────────────┐
│             Nginx Reverse Proxy              │
│                                              │
│  ┌────────────┬──────────────┬────────────┐ │
│  │ /static/   │    /ws       │     /      │ │
│  │  (direct)  │ (WebSocket)  │   (HTTP)   │ │
│  └─────┬──────┴──────┬───────┴──────┬─────┘ │
└────────┼─────────────┼──────────────┼───────┘
         │             │              │
         │             │              │
         ▼             ▼              ▼
    ┌───────┐   ┌────────────────────────────┐
    │Static │   │  Docker Compose Network    │
    │Files  │   │                            │
    │       │   │  ┌──────────────────────┐  │
    │✅CSS  │   │  │  fire_alarm_app      │  │
    │✅JS   │   │  │  (Daphne)            │  │
    │✅IMG  │   │  │                      │  │
    └───────┘   │  │  ✅ MQTT Client      │  │
                │  │     - Auto-reconnect  │  │
                │  │     - Health tracking │  │
                │  │  ✅ WebSocket Server │  │
                │  │  ✅ Django Backend   │  │
                │  └──────┬──────┬────────┘  │
                │         │      │           │
                │         │      └──────┐    │
                │         ▼             ▼    │
                │  ┌─────────────┐ ┌────────┴───┐
                │  │fire_alarm   │ │  MySQL DB  │
                │  │_redis       │ │            │
                │  │             │ └────────────┘
                │  │✅Channel    │
                │  │  Layers     │
                │  └─────────────┘
                └────────────────────────────────┘
                         │
                         │ TCP 1885
                         ▼
              ┌─────────────────────┐
              │   MQTT Broker       │
              │   (152.42.179.228)  │
              └─────────────────────┘
                         ▲
                         │
                  [IoT Devices]


Data Flow (Fixed):
1. Static Files: Nginx → /staticfiles/ (direct, fast)
2. WebSocket: Browser WSS → Nginx (upgrade) → Daphne → Redis → Broadcast
3. HTTP API: Browser → Nginx → Daphne → Django → MySQL
4. MQTT: Devices → Broker → Daphne (MQTT thread) → Django → MySQL
5. Live Updates: MQTT → Django → Redis → WebSocket → Browser
```

---

## Component Communication Flow

### Live Telemetry Flow (Fixed)

```
Device Sends Data
       ↓
   MQTT Broker (152.42.179.228:1885)
       ↓
   MQTT Client Thread (in Daphne)
   - ✅ Auto-reconnect on failure
   - ✅ Health status tracking
   - ✅ Connection callbacks
       ↓
   mqtt.py: process_payload()
       ↓
   services.py: ingest_telemetry()
   - Creates Telemetry record
   - Checks alert thresholds
   - Triggers mesh alerts
       ↓
   MySQL Database
       ↓
   _broadcast_device_update()
       ↓
   Redis Channel Layer (NEW!)
       ↓
   WebSocket Consumer
       ↓
   Browser Dashboard (Live Update!)
```

### Admin Panel CSS Loading (Fixed)

```
Browser: https://firealarm.../admin
       ↓
   Nginx receives request
       ↓
   Checks location /static/
       ↓
   Serves directly from:
   /path/to/staticfiles/admin/css/base.css
       ↓
   ✅ Browser gets CSS (fast!)
```

### WebSocket Connection (Fixed)

```
Browser: new WebSocket('wss://firealarm.../ ws')
       ↓
   Nginx receives WebSocket request
       ↓
   Checks location /ws
   - ✅ proxy_set_header Upgrade $http_upgrade
   - ✅ proxy_set_header Connection "upgrade"
       ↓
   Forwards to Daphne on port 6066
       ↓
   Daphne ASGI application
       ↓
   Channels routing → consumers.DeviceConsumer
       ↓
   Redis Channel Layer
   - ✅ Shared across all workers
   - ✅ Pub/sub for broadcasts
       ↓
   Consumer.send() → Browser
       ↓
   ✅ Real-time updates working!
```

---

## Key Infrastructure Changes

### 1. Nginx Layer (NEW)

**Responsibilities:**
- ✅ Serve static files directly (CSS, JS, images)
- ✅ SSL/TLS termination (HTTPS)
- ✅ WebSocket protocol upgrade
- ✅ Reverse proxy to Daphne
- ✅ Security headers
- ✅ Request buffering/compression

**Configuration:**
```nginx
# Static files
location /static/ {
    alias /path/to/staticfiles/;
    expires 30d;
}

# WebSocket
location /ws {
    proxy_pass http://localhost:6066;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

# HTTP
location / {
    proxy_pass http://localhost:6066;
}
```

---

### 2. Redis Container (NEW)

**Responsibilities:**
- ✅ Channel layer backend for Django Channels
- ✅ Pub/sub for WebSocket broadcasts
- ✅ Shared state across Daphne workers
- ✅ Message queue for real-time updates

**Configuration:**
```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
```

**Django Integration:**
```python
# settings.py
REDIS_URL = "redis://fire_alarm_redis:6379/0"
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}
```

---

### 3. MQTT Health Monitoring (NEW)

**Responsibilities:**
- ✅ Track MQTT connection status
- ✅ Auto-reconnect on failure
- ✅ Provide health check data
- ✅ Log connection events

**Implementation:**
```python
# realtime/mqtt.py
_mqtt_status = {
    "connected": False,
    "last_message_time": None,
    "connection_time": None,
    "error": None,
}

def get_mqtt_status():
    return _mqtt_status.copy()

# Auto-reconnect loop
def run():
    while True:
        try:
            client.connect(...)
            client.loop_forever()
        except Exception as e:
            logger.error(f"MQTT crashed: {e}. Retrying in 10s...")
            time.sleep(10)
```

**Health Check Endpoint:**
```bash
GET /api/readyz

{
  "status": "healthy",
  "checks": {
    "database": {"status": "ok"},
    "mqtt": {
      "status": "ok",
      "connected": true,
      "broker": "152.42.179.228",
      "port": 1885
    }
  }
}
```

---

## Network Topology

```
┌─────────────────────────────────────────────────────────────┐
│                     Linux Server                             │
│                                                              │
│  ┌────────────────┐                                         │
│  │  Nginx         │  Port 443 (HTTPS)                       │
│  │  (Port 80/443) │  ← Internet Traffic                     │
│  └───┬────────────┘                                         │
│      │                                                       │
│      ├─ /static/ → /path/to/staticfiles/                    │
│      │                                                       │
│      ├─ /ws → localhost:6066 (WebSocket upgrade)            │
│      │                                                       │
│      └─ / → localhost:6066 (HTTP proxy)                     │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Docker Network: fire_alarm_network                   │  │
│  │                                                        │  │
│  │  ┌──────────────────┐      ┌──────────────────┐     │  │
│  │  │ fire_alarm_app   │──────│ fire_alarm_redis │     │  │
│  │  │ (Port 6066)      │ Redis│ (Port 6379)      │     │  │
│  │  └──────────────────┘      └──────────────────┘     │  │
│  │          │                                            │  │
│  │          │                                            │  │
│  │          ▼                                            │  │
│  │  ┌──────────────────┐                                │  │
│  │  │ MySQL            │                                │  │
│  │  │ (Port 3306)      │                                │  │
│  │  └──────────────────┘                                │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Monitoring (Cron Job Every 5 min)                    │ │
│  │  /usr/local/bin/check-mqtt-health.sh                  │ │
│  │  → Checks /api/readyz                                 │ │
│  │  → Restarts container if unhealthy                    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ TCP 1885
                          ▼
               ┌──────────────────────┐
               │  External MQTT       │
               │  Broker              │
               │  152.42.179.228:1885 │
               └──────────────────────┘
                          ▲
                          │
                   [IoT Devices]
```

---

## Port Mapping Summary

| Port | Service | Purpose | Exposed |
|------|---------|---------|---------|
| 80 | Nginx | HTTP → HTTPS redirect | ✅ Internet |
| 443 | Nginx | HTTPS traffic | ✅ Internet |
| 6066 | Daphne (Docker) | ASGI application | ❌ Localhost only |
| 6379 | Redis (Docker) | Channel layers | ❌ Docker network |
| 3306 | MySQL | Database | ❌ Localhost only |
| 1885 | MQTT Broker | IoT telemetry | ✅ External IP |

---

## Security Layers

```
┌─────────────────────────────────────────┐
│  Internet (Untrusted)                   │
└─────────────────┬───────────────────────┘
                  │
                  │ TLS/SSL
                  │
            ┌─────▼─────┐
            │   Nginx   │ ← SSL Termination
            │           │ ← Security Headers
            │           │ ← Rate Limiting
            └─────┬─────┘
                  │
                  │ HTTP/WebSocket
                  │ (localhost only)
                  │
            ┌─────▼─────┐
            │  Daphne   │ ← ALLOWED_HOSTS check
            │  Django   │ ← CSRF protection
            │           │ ← JWT/Session auth
            │           │ ← Permission checks
            └─────┬─────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌────────┐  ┌────────┐  ┌─────────┐
│ MySQL  │  │ Redis  │  │  MQTT   │
│        │  │        │  │ Broker  │
└────────┘  └────────┘  └─────────┘
```

---

## Deployment Checklist

### Infrastructure
- [ ] Nginx installed and configured
- [ ] SSL certificates obtained (Certbot)
- [ ] Redis container running
- [ ] Docker Compose updated
- [ ] Static files collected

### Configuration
- [ ] .env with DEBUG=False
- [ ] .env with REDIS_URL
- [ ] .env with production ALLOWED_HOSTS
- [ ] Nginx config has correct static path
- [ ] Nginx config has WebSocket headers

### Monitoring
- [ ] Health check endpoint working
- [ ] MQTT monitor script installed
- [ ] Cron job configured
- [ ] Log rotation configured

### Verification
- [ ] Admin CSS loads (styled interface)
- [ ] WebSocket connects (WSS protocol)
- [ ] MQTT receives messages
- [ ] Alerts trigger on threshold
- [ ] Dashboard shows devices
- [ ] Live updates work

---

This architecture ensures:
- ✅ Production-grade static file serving
- ✅ Reliable WebSocket connections
- ✅ Stable MQTT ingestion
- ✅ Real-time updates
- ✅ Health monitoring
- ✅ Auto-recovery on failures
- ✅ Security best practices
