# 🚀 Production Deployment Guide
## Step-by-Step Instructions for Staging/Production Server

**Target Environment:** Linux Server (Ubuntu/Debian)  
**Domain:** https://firealarm.pranisheba.com.bd/  
**Last Updated:** October 6, 2025

---

## 📋 Pre-Deployment Checklist

Before starting deployment, ensure you have:

- [ ] Root or sudo access to the Linux server
- [ ] Domain name configured (DNS pointing to server IP)
- [ ] SSH access to the server
- [ ] Docker and Docker Compose installed
- [ ] Git installed
- [ ] At least 2GB RAM and 10GB disk space

---

## Step 1: Install Required Software

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y \
    nginx \
    certbot \
    python3-certbot-nginx \
    docker.io \
    docker-compose \
    git \
    curl \
    jq

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add your user to docker group (logout and login after this)
sudo usermod -aG docker $USER
```

---

## Step 2: Clone Repository and Setup

```bash
# Navigate to your deployment directory
cd /opt  # or /var/www or your preferred location

# Clone the repository
git clone <your-repo-url> pranisheba-fire-alarm-app-backend
cd pranisheba-fire-alarm-app-backend

# Create production environment file
cp .env.production.template .env

# Edit .env with your production values
nano .env
```

**Critical values to update in .env:**
```bash
DJANGO_SECRET_KEY="generate-a-new-one"  # See note below
DEBUG=False
ALLOWED_HOSTS=firealarm.pranisheba.com.bd
MYSQL_PASSWORD=strong_password_here
REDIS_URL=redis://fire_alarm_redis:6379/0  # Note: use container name
CSRF_TRUSTED_ORIGINS=https://firealarm.pranisheba.com.bd
```

**Generate secret key:**
```bash
# Run this command and copy the output to DJANGO_SECRET_KEY
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## Step 3: Setup Database

```bash
# Install MySQL if not already installed
sudo apt install -y mysql-server

# Secure MySQL installation
sudo mysql_secure_installation

# Create database and user
sudo mysql -u root -p
```

In MySQL prompt:
```sql
CREATE DATABASE aps_production CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'aps_user'@'localhost' IDENTIFIED BY 'your-strong-password';
GRANT ALL PRIVILEGES ON aps_production.* TO 'aps_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

**Update .env with these credentials!**

---

## Step 4: Build and Start Docker Containers

```bash
# Make sure you're in the project directory
cd /opt/pranisheba-fire-alarm-app-backend

# Build the Docker image
docker-compose build

# Start containers (Redis + Daphne)
docker-compose up -d

# Check containers are running
docker ps
# You should see: fire_alarm_app and fire_alarm_redis

# Check logs
docker logs fire_alarm_app
docker logs fire_alarm_redis
```

**Look for in fire_alarm_app logs:**
```
✅ MQTT connected to 152.42.179.228:1885
🚀 MQTT background thread started
```

---

## Step 5: Run Django Migrations and Collect Static Files

```bash
# Run database migrations
docker exec fire_alarm_app python manage.py migrate

# Create superuser (for /admin access)
docker exec -it fire_alarm_app python manage.py createsuperuser
# Follow prompts to create admin account

# Collect static files
docker exec fire_alarm_app python manage.py collectstatic --noinput

# Verify static files collected
docker exec fire_alarm_app ls -la /app/staticfiles/admin/
# Should show css/, js/, img/ directories
```

---

## Step 6: Configure Nginx

```bash
# Copy nginx config to sites-available
sudo cp nginx-config-production.conf /etc/nginx/sites-available/firealarm.pranisheba.com.bd

# Edit the config to update paths
sudo nano /etc/nginx/sites-available/firealarm.pranisheba.com.bd
```

**Update this line (around line 60):**
```nginx
# Change from:
alias /path/to/pranisheba-fire-alarm-app-backend/staticfiles/;

# To your actual path:
alias /opt/pranisheba-fire-alarm-app-backend/staticfiles/;
```

**Enable the site:**
```bash
# Create symbolic link
sudo ln -s /etc/nginx/sites-available/firealarm.pranisheba.com.bd /etc/nginx/sites-enabled/

# Test nginx configuration
sudo nginx -t
# Should show: "syntax is ok" and "test is successful"

# Reload nginx
sudo systemctl reload nginx
```

---

## Step 7: Setup SSL Certificate (HTTPS)

```bash
# Get SSL certificate from Let's Encrypt
sudo certbot --nginx -d firealarm.pranisheba.com.bd -d www.firealarm.pranisheba.com.bd

# Follow prompts:
# - Enter email for renewal notifications
# - Agree to terms of service
# - Choose to redirect HTTP to HTTPS (recommended: Yes)

# Verify auto-renewal works
sudo certbot renew --dry-run
```

**Certbot will automatically update your nginx config with SSL settings!**

---

## Step 8: Setup MQTT Health Monitoring

```bash
# Copy monitoring script
sudo cp check-mqtt-health.sh /usr/local/bin/check-mqtt-health.sh

# Make it executable
sudo chmod +x /usr/local/bin/check-mqtt-health.sh

# Create log directory
sudo mkdir -p /var/log/mqtt-monitor
sudo touch /var/log/mqtt-monitor/mqtt-monitor.log

# Test the script
sudo /usr/local/bin/check-mqtt-health.sh
# Should show: ✅ MQTT is healthy

# Setup cron job to run every 5 minutes
sudo crontab -e
# Add this line:
*/5 * * * * /usr/local/bin/check-mqtt-health.sh >> /var/log/mqtt-monitor/mqtt-monitor.log 2>&1
```

---

## Step 9: Verify Deployment

### 9.1 Check Docker Containers

```bash
# All containers should be running
docker ps

# Expected output:
# fire_alarm_app    (Status: Up)
# fire_alarm_redis  (Status: Up)
```

### 9.2 Check MQTT Connection

```bash
# Check logs for MQTT connection
docker logs fire_alarm_app | grep -i mqtt

# Should see:
# ✅ MQTT connected to 152.42.179.228:1885
# 🚀 MQTT background thread started
```

### 9.3 Check Health Endpoint

```bash
# Test health check (with jq for pretty output)
curl -s https://firealarm.pranisheba.com.bd/api/readyz | jq

# Expected output:
{
  "status": "healthy",
  "timestamp": 1728234567.89,
  "checks": {
    "database": {
      "status": "ok",
      "message": "Database connection successful"
    },
    "mqtt": {
      "status": "ok",
      "connected": true,
      "broker": "152.42.179.228",
      "port": 1885
    }
  }
}
```

### 9.4 Check Static Files

```bash
# Test admin CSS loads
curl -I https://firealarm.pranisheba.com.bd/static/admin/css/base.css

# Expected: HTTP/2 200
# NOT: HTTP/2 404
```

### 9.5 Check Admin Panel

Open browser:
```
https://firealarm.pranisheba.com.bd/admin
```

**Expected:**
- ✅ Styled login page with CSS
- ✅ Blue/green color scheme
- ✅ No plain HTML text

**If you see plain text, static files are NOT loading correctly!**

### 9.6 Check WebSocket Connection

Open browser DevTools (F12):
1. Go to: `https://firealarm.pranisheba.com.bd/`
2. Open **Network** tab
3. Filter by **WS** (WebSocket)
4. Look for connection to: `wss://firealarm.pranisheba.com.bd/ws`

**Expected:**
- Status: `101 Switching Protocols` (green)
- Messages tab shows incoming data

**If status is red or errors, WebSocket is broken!**

---

## Step 10: Test Live Data Flow

### 10.1 Register a Test Device

```bash
# Get authentication token
TOKEN=$(curl -X POST https://firealarm.pranisheba.com.bd/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"email":"your-admin@email.com","password":"your-password"}' \
  | jq -r '.access')

# Register a device
curl -X POST https://firealarm.pranisheba.com.bd/api/devices/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Sensor",
    "hardware_identifier": "TEST_001",
    "location": "Server Room"
  }'
```

### 10.2 Send Test MQTT Message

**From your local machine or device:**
```python
import paho.mqtt.client as mqtt
import json
import time

payload = {
    "deviceID": "TEST_001",
    "timestamp": int(time.time()),
    "smoke": 30,
    "status": "alive"
}

client = mqtt.Client()
client.username_pw_set("apsIoT", "apsIoT25")
client.connect("152.42.179.228", 1885, 60)
client.publish("aps/fire/data", json.dumps(payload))
client.disconnect()

print("Test message sent!")
```

### 10.3 Verify Data Received

```bash
# Check backend logs
docker logs fire_alarm_app --tail=50 | grep -i "TEST_001"

# Should see: "Processing payload for device TEST_001"

# Check database
docker exec fire_alarm_app python manage.py shell
```

In Django shell:
```python
from devices.models import Device, Telemetry
device = Device.objects.get(hardware_identifier='TEST_001')
print(f"Device: {device.name}")
print(f"Last seen: {device.last_seen}")
print(f"Telemetry count: {device.telemetry_records.count()}")
# Should show recent data!
```

### 10.4 Check Dashboard

Open browser:
```
https://firealarm.pranisheba.com.bd/
```

**Expected:**
- ✅ Device appears on map
- ✅ Live smoke level updates
- ✅ Status indicator shows "Online"
- ✅ No page refresh needed

---

## 🐛 Troubleshooting

### Issue: Admin Has No CSS

**Check 1: Static files exist?**
```bash
docker exec fire_alarm_app ls -la /app/staticfiles/admin/css/base.css
# Should exist and be readable
```

**Check 2: Nginx serving static files?**
```bash
curl -I https://firealarm.pranisheba.com.bd/static/admin/css/base.css
# Expected: HTTP/2 200
```

**Fix:**
```bash
# Check nginx config
sudo nano /etc/nginx/sites-enabled/firealarm.pranisheba.com.bd
# Verify "location /static/" has correct alias path

# Reload nginx
sudo systemctl reload nginx
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

**Check 3: Logs show connection?**
```bash
docker logs fire_alarm_app | grep -i mqtt
```

**Fix if not connecting:**
```bash
# Restart container
docker restart fire_alarm_app

# Check logs again
docker logs fire_alarm_app --tail=50
```

---

### Issue: WebSocket Not Connecting

**Check 1: Browser console shows error?**
- Open DevTools → Console
- Look for WebSocket errors

**Check 2: Nginx has upgrade headers?**
```bash
sudo nginx -T | grep -A10 "location /ws"
# Must have: proxy_set_header Upgrade $http_upgrade;
```

**Check 3: Redis running?**
```bash
docker exec fire_alarm_redis redis-cli ping
# Should return: PONG
```

**Fix:**
```bash
# Check redis in .env
docker exec fire_alarm_app env | grep REDIS_URL
# Should be: redis://fire_alarm_redis:6379/0

# Restart containers
docker-compose restart
```

---

### Issue: Dashboard Shows No Devices

**Check 1: Devices in database?**
```bash
docker exec fire_alarm_app python manage.py shell -c "from devices.models import Device; print(Device.objects.count())"
```

**Check 2: API returns devices?**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://firealarm.pranisheba.com.bd/api/devices/ | jq
```

**Check 3: JavaScript loading?**
- Open DevTools → Network → JS
- Check for 404 errors

---

## 🔄 Updating the Application

```bash
# Navigate to project directory
cd /opt/pranisheba-fire-alarm-app-backend

# Pull latest changes
git pull origin main

# Rebuild and restart containers
docker-compose down
docker-compose build
docker-compose up -d

# Run migrations if any
docker exec fire_alarm_app python manage.py migrate

# Collect static files
docker exec fire_alarm_app python manage.py collectstatic --noinput

# Check logs
docker logs fire_alarm_app --tail=50
```

---

## 📊 Monitoring Commands

```bash
# View all container logs
docker-compose logs -f

# View only app logs
docker logs -f fire_alarm_app

# View only Redis logs
docker logs -f fire_alarm_redis

# View nginx logs
sudo tail -f /var/log/nginx/firealarm_error.log
sudo tail -f /var/log/nginx/firealarm_access.log

# View MQTT monitor logs
sudo tail -f /var/log/mqtt-monitor/mqtt-monitor.log

# Check system resources
docker stats

# Check health endpoint
watch -n 5 'curl -s https://firealarm.pranisheba.com.bd/api/readyz | jq'
```

---

## 🎯 Success Criteria Checklist

Your deployment is successful when:

- [ ] `/admin` loads with full CSS styling
- [ ] `/docs` shows OpenAPI documentation
- [ ] `/api/readyz` returns `"status": "healthy"`
- [ ] Device can be registered via API
- [ ] MQTT messages create telemetry records
- [ ] Smoke alerts trigger when threshold exceeded
- [ ] Dashboard map shows registered devices
- [ ] Live updates appear without page refresh
- [ ] WebSocket shows "Connected" in DevTools
- [ ] Health check returns green status

---

## 📞 Support

If you encounter issues not covered in this guide:

1. Check all logs:
   ```bash
   docker logs fire_alarm_app
   sudo tail /var/log/nginx/firealarm_error.log
   ```

2. Run health check:
   ```bash
   curl -s https://firealarm.pranisheba.com.bd/api/readyz | jq
   ```

3. Verify environment:
   ```bash
   docker exec fire_alarm_app env | grep -E "(DEBUG|REDIS|MQTT|ALLOWED)"
   ```

---

**🎉 Deployment Complete! Your Fire Alarm Backend should now work exactly like local development!**
