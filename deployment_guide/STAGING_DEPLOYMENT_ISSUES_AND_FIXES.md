# 🚨 Staging Deployment Issues & Permanent Fixes
## apS Fire Alarm Backend - Production Deployment Guide

**Issue Date:** October 6, 2025  
**Environment:** Linux Server (Staging)  
**Domain:** https://firealarm.pranisheba.com.bd/  
**Status:** ⚠️ Partial functionality - Static APIs work, Live data broken

---

## 📊 Problem Summary

### ✅ What Works in Staging
- User authentication (JWT, login/logout)
- User creation and management
- Device registration via API (`POST /api/devices/`)
- Device updates (name, location, etc.)
- Database operations (MySQL)
- `/docs` OpenAPI documentation accessible
- `/admin` page loads (but NO CSS)

### ❌ What's Broken in Staging
1. **No Static Files (CSS/JS)** - Admin panel shows plain text, no styling
2. **No Live Telemetry** - MQTT messages not being processed
3. **No Alerts** - Smoke alerts not triggering
4. **No Device Map** - Dashboard shows no devices/live previews
5. **No WebSocket Updates** - Real-time features completely broken

### 🎯 Root Cause Analysis

| Issue | Root Cause | Impact |
|-------|------------|--------|
| **Admin CSS missing** | Static files not served correctly in production | Admin unusable |
| **No live telemetry** | MQTT background thread not running | No device data |
| **No alerts** | MQTT not ingesting → services.py never called | Safety system offline |
| **Empty dashboard** | WebSocket not connecting OR no data to show | Users see nothing |
| **Map not loading** | Could be static JS files OR WebSocket failure | No device monitoring |

---

## 🔍 Detailed Technical Analysis

### Issue #1: Static Files Not Serving (Admin CSS Missing)

**Symptoms:**
- `/admin` page loads but shows plain HTML text
- No CSS styling, no JavaScript
- Browser console shows 404 errors for `/static/admin/css/...`

**Why It Happens:**
```python
# In settings.py
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
```

1. ✅ You ran `python manage.py collectstatic --noinput` 
2. ✅ Files collected to `/staticfiles/` directory
3. ❌ **BUT: Daphne (ASGI server) does NOT serve static files in production!**

**The Problem:**
```dockerfile
# Your Dockerfile
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
```

Daphne is an **ASGI application server**, not a web server. It handles:
- ✅ HTTP requests to Django views
- ✅ WebSocket connections
- ❌ **Does NOT serve static files efficiently**

**How It Works Locally:**
```python
# config/asgi.py
if settings.DEBUG:
    http_app = ASGIStaticFilesHandler(http_app)  # ← Only in DEBUG mode!
```

When `DEBUG=True` (local), Django serves static files.  
When `DEBUG=False` (staging), Django expects **Nginx** to serve them.

**The Solution:**
You need **Nginx** as a reverse proxy to:
1. Serve static files directly from `/staticfiles/`
2. Proxy WebSocket connections to Daphne
3. Proxy HTTP requests to Daphne

---

### Issue #2: MQTT Background Thread Not Running

**Symptoms:**
- Devices can be registered in database
- Devices send MQTT messages to broker
- **BUT: Backend never receives/processes them**
- No telemetry records created
- No alerts triggered

**Why It Happens:**

Your MQTT client starts in `realtime/apps.py`:
```python
class RealtimeConfig(AppConfig):
    def ready(self):
        from .mqtt import ensure_mqtt_thread
        ensure_mqtt_thread()
```

**The Problem:**
Django's `AppConfig.ready()` is called during app initialization. However:

1. **In production containers**, app might restart frequently
2. **Thread might crash silently** without proper monitoring
3. **No health check** to verify MQTT is connected
4. **Logs not visible** - you don't know if thread started

**Verification Test:**
```bash
# SSH to your staging server
docker logs fire_alarm_app | grep -i mqtt
# Do you see "Connected to MQTT broker" or similar?
```

**Common Failure Scenarios:**

A. **Network connectivity**: Container can't reach MQTT broker
```python
MQTT_BROKER = "152.42.179.228"  # Can container access this IP?
MQTT_PORT = 1885
```

B. **Thread crashes during startup**:
```python
def run():
    client = mqtt.Client()
    # If this fails, thread dies silently!
    client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
```

C. **Django workers restart**, killing the thread

---

### Issue #3: WebSocket Connections Failing

**Symptoms:**
- Dashboard loads but shows no devices
- No live updates on map
- Browser console shows WebSocket errors

**Why It Happens:**

Your frontend tries to connect to WebSocket:
```javascript
// In templates (assuming)
const ws = new WebSocket('wss://firealarm.pranisheba.com.bd/ws');
```

**The Problem Chain:**

1. **HTTPS requires WSS** (not WS)
   - Your site uses HTTPS: `https://firealarm.pranisheba.com.bd/`
   - WebSocket must use WSS: `wss://firealarm.pranisheba.com.bd/ws`

2. **Nginx must proxy WebSocket correctly**
   ```nginx
   # WRONG: Missing WebSocket headers
   location /ws {
       proxy_pass http://daphne:8000;
   }
   
   # CORRECT: With WebSocket upgrade headers
   location /ws {
       proxy_pass http://daphne:8000;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
   }
   ```

3. **Daphne must be accessible from Nginx**
   - If Nginx runs on host and Daphne in Docker, networking matters

4. **Channel layers must work**
   ```python
   # settings.py - Your current config
   CHANNEL_LAYERS = {
       "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
   }
   ```
   ⚠️ **In-memory layers DON'T work with multiple workers!**  
   You need Redis for production.

---

### Issue #4: Dashboard Shows No Devices

**Symptoms:**
- Devices exist in MySQL database
- Dashboard map is empty
- No device markers shown

**Why It Happens:**

This could be **multiple issues compounding**:

A. **Static JS files not loading** (Issue #1)
   - Map library (Leaflet/MapBox) not loading
   - Browser console shows 404 for JS files

B. **WebSocket not connecting** (Issue #3)
   - JavaScript expects live data via WebSocket
   - No connection = no data

C. **No telemetry data** (Issue #2)
   - MQTT not running = devices never update `last_seen`
   - Devices show as offline
   - Frontend hides offline devices?

D. **API endpoint issue**
   ```javascript
   // Frontend might call:
   fetch('/api/devices/')
   ```
   - Does this work in staging?
   - Check browser Network tab

---

## 🛠️ Complete Solution Architecture

### Current (Broken) Architecture
```
Internet → HTTPS → [Linux Server]
                        ↓
                   Docker: Daphne (port 6066)
                        ↓
                   ❌ No static files
                   ❌ WebSocket not configured
                   ❌ MQTT thread unstable
```

### Correct Production Architecture
```
Internet → HTTPS → Nginx (443)
                     ↓
        ┌────────────┴────────────┐
        ↓                         ↓
    Serve Static Files      Proxy to Daphne (8000)
    /static/ → /app/staticfiles/     ↓
                                  ASGI App + WebSocket
                                     ↓
                                 Django + Channels
                                     ↓
                        ┌────────────┴────────────┐
                        ↓                         ↓
                    MySQL (3306)           MQTT Broker (1885)
                                                  ↓
                                            IoT Devices
```

---

## 📋 Permanent Fixes - Step by Step

### Fix #1: Configure Nginx for Static Files and WebSocket

Create `/etc/nginx/sites-available/firealarm.pranisheba.com.bd`:

```nginx
# Upstream to Daphne ASGI server
upstream daphne_server {
    server localhost:6066;  # Your docker-compose maps 6066:8000
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name firealarm.pranisheba.com.bd;
    
    # Redirect all HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name firealarm.pranisheba.com.bd;
    
    # SSL certificates (configure your cert paths)
    ssl_certificate /etc/letsencrypt/live/firealarm.pranisheba.com.bd/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/firealarm.pranisheba.com.bd/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # Max upload size
    client_max_body_size 100M;
    
    # Logs
    access_log /var/log/nginx/firealarm_access.log;
    error_log /var/log/nginx/firealarm_error.log;
    
    # Serve static files directly (CRITICAL FIX!)
    location /static/ {
        alias /path/to/pranisheba-fire-alarm-app-backend/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        
        # CORS if needed for assets
        add_header Access-Control-Allow-Origin *;
    }
    
    # WebSocket endpoint (CRITICAL FIX!)
    location /ws {
        proxy_pass http://daphne_server;
        
        # WebSocket upgrade headers
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Standard proxy headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts for long-lived connections
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
    
    # All other requests → Django/Daphne
    location / {
        proxy_pass http://daphne_server;
        
        # Standard proxy headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

**Enable the site:**
```bash
sudo ln -s /etc/nginx/sites-available/firealarm.pranisheba.com.bd /etc/nginx/sites-enabled/
sudo nginx -t  # Test configuration
sudo systemctl reload nginx
```

**Update nginx paths:**
Replace `/path/to/pranisheba-fire-alarm-app-backend/staticfiles/` with your actual path.

---

### Fix #2: Configure Redis for Production Channel Layers

**Why needed:**
- In-memory channel layers don't work with multiple Daphne workers
- WebSocket broadcasts fail across different processes
- Redis provides shared state

**Update `.env` for staging:**
```bash
# Add Redis configuration
REDIS_URL=redis://localhost:6379/0
```

**Update `docker-compose.yml`:**
```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    container_name: fire_alarm_redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
    command: redis-server --appendonly yes
  
  web:
    build: .
    container_name: fire_alarm_app
    ports:
      - "6066:8000"
    volumes:
      - .:/app
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings
    command: daphne -b 0.0.0.0 -p 8000 config.asgi:application
    env_file:
      - .env
    depends_on:
      - redis
    restart: unless-stopped

volumes:
  redis_data:
```

**Update `requirements.txt`:**
```txt
channels-redis==4.2.1
```

**Install on server:**
```bash
pip install channels-redis==4.2.1
```

**Verify settings.py** (already correct):
```python
REDIS_URL = os.getenv("REDIS_URL", "")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
```

---

### Fix #3: Monitor and Auto-Restart MQTT Thread

**Problem:** MQTT thread crashes silently, no monitoring.

**Solution A: Add Health Check Endpoint**

Create `realtime/mqtt.py` additions:

```python
# Add to top of mqtt.py
import time

# Add global status tracking
_mqtt_status = {
    "connected": False,
    "last_message_time": None,
    "connection_time": None,
    "error": None,
}

def get_mqtt_status():
    """Return current MQTT connection status for health checks."""
    return _mqtt_status.copy()

# Update ensure_mqtt_thread()
def ensure_mqtt_thread():
    global _thread_started
    if _thread_started:
        return
    _thread_started = True

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            _mqtt_status["connected"] = True
            _mqtt_status["connection_time"] = time.time()
            _mqtt_status["error"] = None
            logger.info(f"✅ MQTT connected to {settings.MQTT_BROKER}:{settings.MQTT_PORT}")
        else:
            _mqtt_status["connected"] = False
            _mqtt_status["error"] = f"Connection failed with code {rc}"
            logger.error(f"❌ MQTT connection failed: {rc}")

    def on_disconnect(client, userdata, rc):
        _mqtt_status["connected"] = False
        logger.warning(f"⚠️ MQTT disconnected with code {rc}")

    def on_message(client, userdata, msg):
        _mqtt_status["last_message_time"] = time.time()
        raw = msg.payload.decode(errors="ignore").strip()
        try:
            payload = json.loads(raw)
            process_payload(payload)
        except Exception as e:
            logging.error(f"Failed to process MQTT message: {e}; raw={raw}")

    def run():
        while True:  # Auto-reconnect loop
            try:
                client = mqtt.Client()
                if settings.MQTT_USER:
                    client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASS)
                
                client.on_connect = on_connect
                client.on_disconnect = on_disconnect
                client.on_message = on_message
                
                logger.info(f"🔄 Attempting MQTT connection to {settings.MQTT_BROKER}:{settings.MQTT_PORT}")
                client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
                client.subscribe(settings.MQTT_TOPIC)
                client.loop_forever()  # Blocks until disconnect
                
            except Exception as e:
                _mqtt_status["error"] = str(e)
                logger.error(f"❌ MQTT thread crashed: {e}. Retrying in 10s...")
                time.sleep(10)  # Wait before retry

    t = threading.Thread(target=run, daemon=True, name="MQTT-Client")
    t.start()
    logger.info("🚀 MQTT thread started")
```

**Create health check endpoint:**

`api/views.py`:
```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.db import connection
from realtime.mqtt import get_mqtt_status
import time

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    Health check endpoint for monitoring.
    Returns status of database, MQTT, and app.
    """
    health = {
        "status": "healthy",
        "timestamp": time.time(),
        "checks": {}
    }
    
    # Database check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        health["checks"]["database"] = {"status": "error", "error": str(e)}
        health["status"] = "unhealthy"
    
    # MQTT check
    mqtt_status = get_mqtt_status()
    if mqtt_status["connected"]:
        health["checks"]["mqtt"] = {
            "status": "ok",
            "connected": True,
            "last_message": mqtt_status.get("last_message_time"),
        }
    else:
        health["checks"]["mqtt"] = {
            "status": "error",
            "connected": False,
            "error": mqtt_status.get("error"),
        }
        health["status"] = "degraded"
    
    return Response(health)
```

**Add to `api/urls.py`:**
```python
from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
    # ... existing routes
]
```

**Test health check:**
```bash
curl https://firealarm.pranisheba.com.bd/api/health/
```

---

### Fix #4: Production Environment Configuration

**Update `.env` for staging:**

```bash
# Core Django
DJANGO_SECRET_KEY="generate-a-strong-secret-key-here"
DEBUG=False
ALLOWED_HOSTS=firealarm.pranisheba.com.bd,www.firealarm.pranisheba.com.bd

# Database
MYSQL_DATABASE=aps_production
MYSQL_USER=aps_user
MYSQL_PASSWORD=strong_password_here
MYSQL_HOST=localhost
MYSQL_PORT=3306

# MQTT
MQTT_BROKER=152.42.179.228
MQTT_PORT=1885
MQTT_TOPIC=aps/fire/data
MQTT_USER=apsIoT
MQTT_PASS=apsIoT25

# Redis (CRITICAL for production!)
REDIS_URL=redis://localhost:6379/0

# Security
CSRF_TRUSTED_ORIGINS=https://firealarm.pranisheba.com.bd

# Device settings
DEVICE_ONLINE_FRESHNESS_SECONDS=180
SMOKE_ALERT_THRESHOLD=50
SLAVE_REQUIRE_OWN_TIMESTAMP=False
```

**Security checklist:**
- [ ] `DEBUG=False` set
- [ ] Strong `DJANGO_SECRET_KEY` (use `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
- [ ] `ALLOWED_HOSTS` restricted to your domain only
- [ ] Strong MySQL password
- [ ] Redis protected (not exposed publicly)

---

### Fix #5: Update Frontend WebSocket Connection

**Check your templates** for WebSocket connection code:

**WRONG (will fail on HTTPS):**
```javascript
const ws = new WebSocket('ws://firealarm.pranisheba.com.bd/ws');
```

**CORRECT:**
```javascript
// Auto-detect protocol
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
```

**Or hardcode for production:**
```javascript
const ws = new WebSocket('wss://firealarm.pranisheba.com.bd/ws');
```

**Verify in your templates:**
```bash
grep -r "WebSocket" templates/
```

---

## 🚀 Deployment Checklist

### Pre-Deployment

- [ ] Install Nginx on server: `sudo apt install nginx`
- [ ] Install Certbot for SSL: `sudo apt install certbot python3-certbot-nginx`
- [ ] Get SSL certificate: `sudo certbot --nginx -d firealarm.pranisheba.com.bd`
- [ ] Add Redis to docker-compose.yml
- [ ] Add `channels-redis==4.2.1` to requirements.txt
- [ ] Update `.env` with production values
- [ ] Set `DEBUG=False` in `.env`
- [ ] Set `REDIS_URL=redis://localhost:6379/0` in `.env`

### Deployment Steps

```bash
# 1. Pull latest code
cd /path/to/pranisheba-fire-alarm-app-backend
git pull origin main

# 2. Rebuild Docker containers
docker-compose down
docker-compose build
docker-compose up -d

# 3. Collect static files (inside container)
docker exec fire_alarm_app python manage.py collectstatic --noinput

# 4. Copy static files to Nginx-accessible location
sudo cp -r staticfiles/ /var/www/firealarm-static/

# OR: Update Nginx config to point to container volume
# location /static/ {
#     alias /path/to/pranisheba-fire-alarm-app-backend/staticfiles/;
# }

# 5. Apply migrations
docker exec fire_alarm_app python manage.py migrate

# 6. Configure Nginx
sudo cp nginx_config /etc/nginx/sites-available/firealarm.pranisheba.com.bd
sudo ln -s /etc/nginx/sites-available/firealarm.pranisheba.com.bd /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# 7. Verify services
docker ps  # Check containers running
docker logs fire_alarm_app | grep -i mqtt  # Check MQTT connected
docker logs fire_alarm_redis  # Check Redis running

# 8. Test endpoints
curl https://firealarm.pranisheba.com.bd/api/health/
curl https://firealarm.pranisheba.com.bd/static/apsLogo.ico
```

### Post-Deployment Verification

**1. Static Files:**
```bash
# Browser: Open admin
https://firealarm.pranisheba.com.bd/admin

# Should see styled login page with CSS
# Check browser console - no 404 errors for static files
```

**2. MQTT Connection:**
```bash
docker logs fire_alarm_app | tail -50

# Look for:
# ✅ MQTT connected to 152.42.179.228:1885
# ✅ Subscribed to aps/fire/data
```

**3. WebSocket:**
```bash
# Browser: Open dashboard
https://firealarm.pranisheba.com.bd/

# Open DevTools → Network → WS (WebSocket tab)
# Should see: wss://firealarm.pranisheba.com.bd/ws [101 Switching Protocols]
```

**4. Live Telemetry:**
```bash
# Run device simulator locally
python device_simulator.py

# Check logs:
docker logs -f fire_alarm_app

# Should see: "Processing MQTT payload for device..."
```

**5. Health Check:**
```bash
curl https://firealarm.pranisheba.com.bd/api/health/

# Expected output:
{
  "status": "healthy",
  "timestamp": 1728234567.89,
  "checks": {
    "database": {"status": "ok"},
    "mqtt": {"status": "ok", "connected": true}
  }
}
```

---

## 🐛 Troubleshooting Guide

### Issue: Admin Still Has No CSS

**Check 1: Static files collected?**
```bash
docker exec fire_alarm_app ls -la /app/staticfiles/admin/
# Should see css/, js/, img/ directories
```

**Check 2: Nginx serving correctly?**
```bash
curl -I https://firealarm.pranisheba.com.bd/static/admin/css/base.css
# Should return: HTTP/1.1 200 OK
# Not: HTTP/1.1 404 Not Found
```

**Check 3: Nginx config correct?**
```bash
sudo nginx -t
sudo cat /etc/nginx/sites-enabled/firealarm.pranisheba.com.bd | grep -A5 "location /static"
```

**Check 4: File permissions?**
```bash
ls -la /path/to/staticfiles/
# Should be readable by nginx user (www-data)
sudo chown -R www-data:www-data /path/to/staticfiles/
```

---

### Issue: MQTT Not Connecting

**Check 1: Container can reach broker?**
```bash
docker exec fire_alarm_app ping -c3 152.42.179.228
docker exec fire_alarm_app nc -zv 152.42.179.228 1885
```

**Check 2: Credentials correct?**
```bash
docker exec fire_alarm_app env | grep MQTT
```

**Check 3: Thread started?**
```bash
docker logs fire_alarm_app | grep "MQTT thread started"
```

**Check 4: Firewall blocking?**
```bash
# On MQTT broker server
sudo ufw status
sudo ufw allow 1885/tcp
```

---

### Issue: WebSocket Not Connecting

**Check 1: Browser console errors?**
```javascript
// Open browser DevTools → Console
// Look for WebSocket errors
```

**Check 2: Nginx config has upgrade headers?**
```bash
sudo cat /etc/nginx/sites-enabled/firealarm.pranisheba.com.bd | grep -A10 "location /ws"
# Must have:
# proxy_set_header Upgrade $http_upgrade;
# proxy_set_header Connection "upgrade";
```

**Check 3: Daphne accessible?**
```bash
curl -I http://localhost:6066/
# Should return: HTTP/1.1 200 OK or similar
```

**Check 4: Redis running?**
```bash
docker exec fire_alarm_redis redis-cli ping
# Should return: PONG
```

**Check 5: Channel layers configured?**
```bash
docker exec fire_alarm_app python manage.py shell
>>> from channels.layers import get_channel_layer
>>> channel_layer = get_channel_layer()
>>> print(channel_layer)
# Should show: RedisChannelLayer (not InMemoryChannelLayer)
```

---

### Issue: Dashboard Shows No Devices

**Check 1: Devices exist in database?**
```bash
docker exec fire_alarm_app python manage.py shell
>>> from devices.models import Device
>>> Device.objects.count()
# Should return > 0
```

**Check 2: API returns devices?**
```bash
# Get auth token first
TOKEN=$(curl -X POST https://firealarm.pranisheba.com.bd/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password"}' \
  | jq -r '.access')

# Get devices
curl https://firealarm.pranisheba.com.bd/api/devices/ \
  -H "Authorization: Bearer $TOKEN"
```

**Check 3: JavaScript loading?**
```bash
# Browser DevTools → Network → JS
# Check for 404 errors on JS files
```

**Check 4: WebSocket receiving data?**
```bash
# Browser DevTools → Network → WS → Select connection → Messages
# Should see device updates coming through
```

---

## 📊 Monitoring Setup (Recommended)

### Systemd Service for MQTT Monitoring

Create `/etc/systemd/system/mqtt-monitor.service`:

```ini
[Unit]
Description=MQTT Connection Monitor for Fire Alarm
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check-mqtt.sh

[Install]
WantedBy=multi-user.target
```

Create `/usr/local/bin/check-mqtt.sh`:

```bash
#!/bin/bash
# Check if MQTT is connected

HEALTH_URL="https://firealarm.pranisheba.com.bd/api/health/"
RESPONSE=$(curl -s $HEALTH_URL)

MQTT_STATUS=$(echo $RESPONSE | jq -r '.checks.mqtt.status')

if [ "$MQTT_STATUS" != "ok" ]; then
    echo "❌ MQTT is DOWN! Restarting container..."
    docker restart fire_alarm_app
    
    # Send alert (optional - configure your alerting)
    # curl -X POST https://your-alert-webhook.com/alert \
    #   -d "MQTT connection lost on production server"
else
    echo "✅ MQTT is healthy"
fi
```

```bash
sudo chmod +x /usr/local/bin/check-mqtt.sh

# Run every 5 minutes
sudo crontab -e
# Add line:
*/5 * * * * /usr/local/bin/check-mqtt.sh >> /var/log/mqtt-monitor.log 2>&1
```

---

## 🎯 Summary of Required Changes

### Code Changes Needed

1. **Add MQTT health monitoring** to `realtime/mqtt.py`
2. **Add health check endpoint** to `api/views.py`
3. **Update WebSocket connection** in templates (use WSS with auto-detection)
4. **Add channels-redis** to `requirements.txt`

### Infrastructure Changes Needed

1. **Install and configure Nginx** as reverse proxy
2. **Add Redis container** to docker-compose.yml
3. **Update .env** with production values (DEBUG=False, REDIS_URL, etc.)
4. **Configure SSL certificates** with Certbot
5. **Set up monitoring** (health checks, log monitoring)

### Configuration Files to Create

1. **Nginx config** (`/etc/nginx/sites-available/firealarm.pranisheba.com.bd`)
2. **Updated docker-compose.yml** (with Redis)
3. **Production .env** file
4. **MQTT monitor script** (optional but recommended)

---

## ✅ Success Criteria

Your staging environment will be fully functional when:

- [ ] `/admin` page loads with full CSS styling
- [ ] Device simulator sends data → appears in database within seconds
- [ ] Smoke alerts trigger automatically when threshold exceeded
- [ ] Dashboard map shows all registered devices
- [ ] Live device updates appear without page refresh
- [ ] WebSocket connection shows "Connected" in DevTools
- [ ] `/api/health/` returns `{"status": "healthy"}`
- [ ] All features work exactly like local development

---

## 🆘 Need Help?

If you encounter issues:

1. **Check Docker logs:**
   ```bash
   docker logs fire_alarm_app --tail=100
   docker logs fire_alarm_redis --tail=100
   ```

2. **Check Nginx logs:**
   ```bash
   sudo tail -f /var/log/nginx/firealarm_error.log
   ```

3. **Test health endpoint:**
   ```bash
   curl https://firealarm.pranisheba.com.bd/api/health/ | jq
   ```

4. **Verify environment variables:**
   ```bash
   docker exec fire_alarm_app env | grep -E "(DEBUG|REDIS|MQTT)"
   ```

---

**This document provides a complete, production-ready deployment guide. Follow each section carefully, and your staging environment will work exactly like your local development environment!** 🚀

**Generated by:** GitHub Copilot  
**Date:** October 6, 2025  
**Version:** 1.0
