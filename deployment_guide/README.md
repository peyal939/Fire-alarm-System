# 📦 Deployment Guide Documentation
## apS Fire Alarm Backend - Production Deployment Resources

This folder contains all documentation and configuration files needed to deploy the Fire Alarm Backend to production/staging environments.

---

## 📚 Documentation Files

### 1. **START HERE** 👉 [`DEPLOYMENT_QUICKREF.md`](./DEPLOYMENT_QUICKREF.md)
**Quick reference guide for urgent deployments**

- 📄 **What it is:** Condensed version of all deployment information
- ⏱️ **Reading time:** 5 minutes
- 🎯 **Use when:** You need to deploy quickly or troubleshoot urgent issues
- ✅ **Contains:**
  - Problem summary
  - Quick fix commands
  - Verification tests
  - Common troubleshooting

---

### 2. **COMPREHENSIVE GUIDE** 📖 [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md)
**Step-by-step production deployment instructions**

- 📄 **What it is:** Complete walkthrough from fresh server to running application
- ⏱️ **Reading time:** 15-20 minutes
- 🎯 **Use when:** First-time deployment or setting up new environment
- ✅ **Contains:**
  - Pre-deployment checklist
  - Installation commands (Nginx, Docker, SSL)
  - Configuration steps
  - Verification procedures
  - Troubleshooting guide
  - Monitoring setup

**Sections:**
1. Install Required Software
2. Clone Repository and Setup
3. Setup Database
4. Build and Start Docker Containers
5. Run Django Migrations
6. Configure Nginx
7. Setup SSL Certificate
8. Setup MQTT Monitoring
9. Verify Deployment
10. Test Live Data Flow

---

### 3. **TECHNICAL DEEP-DIVE** 🔬 [`STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md`](./STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md)
**Comprehensive analysis of production issues and solutions**

- 📄 **What it is:** 700+ line technical document explaining why things break and how to fix them
- ⏱️ **Reading time:** 30-40 minutes
- 🎯 **Use when:** You want to understand the technical reasons behind the fixes
- ✅ **Contains:**
  - Root cause analysis for each issue
  - Why Daphne doesn't serve static files
  - How MQTT thread management works
  - WebSocket protocol requirements
  - Redis channel layer necessity
  - Architecture diagrams
  - Component interaction flows
  - Security considerations
  - Performance optimization tips

**Perfect for:**
- DevOps engineers
- System architects
- Developers who want to understand the full system
- Troubleshooting complex issues

---

### 4. **VISUAL ARCHITECTURE** 🏗️ [`ARCHITECTURE_DIAGRAMS.md`](./ARCHITECTURE_DIAGRAMS.md)
**Before/after architecture diagrams and data flows**

- 📄 **What it is:** ASCII diagrams showing system architecture
- ⏱️ **Reading time:** 10 minutes
- 🎯 **Use when:** You need to visualize how components interact
- ✅ **Contains:**
  - Current (broken) architecture
  - Fixed production architecture
  - Data flow diagrams (MQTT, WebSocket, Static files)
  - Network topology
  - Port mapping summary
  - Security layers
  - Component responsibilities

**Perfect for:**
- Visual learners
- System design discussions
- Onboarding new team members
- Architecture reviews

---

## 🔧 Configuration Files

### 5. **Nginx Configuration** [`nginx-config-production.conf`](./nginx-config-production.conf)
**Complete Nginx reverse proxy configuration**

```bash
# Where to place:
/etc/nginx/sites-available/firealarm.pranisheba.com.bd

# How to use:
sudo cp nginx-config-production.conf /etc/nginx/sites-available/firealarm.pranisheba.com.bd
sudo ln -s /etc/nginx/sites-available/firealarm.pranisheba.com.bd /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

**Features:**
- ✅ Static file serving from `/static/`
- ✅ WebSocket proxy with upgrade headers
- ✅ SSL/TLS configuration
- ✅ Security headers
- ✅ Gzip compression
- ✅ Health check endpoints
- ✅ HTTP → HTTPS redirect

**IMPORTANT:** Update the static files path (line ~60):
```nginx
alias /path/to/pranisheba-fire-alarm-app-backend/staticfiles/;
```

---

### 6. **Environment Template** [`.env.production.template`](./.env.production.template)
**Production environment variables template**

```bash
# How to use:
cp .env.production.template ../.env
nano ../.env  # Update with your values
```

**Critical values to update:**
- `DJANGO_SECRET_KEY` - Generate with: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- `DEBUG=False` - Must be False in production!
- `ALLOWED_HOSTS` - Your domain only
- `MYSQL_PASSWORD` - Strong password
- `REDIS_URL=redis://fire_alarm_redis:6379/0` - Enable Redis channel layers

---

### 7. **Health Monitor Script** [`check-mqtt-health.sh`](./check-mqtt-health.sh)
**Automated MQTT connection monitoring**

```bash
# Where to place:
/usr/local/bin/check-mqtt-health.sh

# How to install:
sudo cp check-mqtt-health.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/check-mqtt-health.sh

# Setup cron job (runs every 5 minutes):
sudo crontab -e
# Add line:
*/5 * * * * /usr/local/bin/check-mqtt-health.sh >> /var/log/mqtt-monitor.log 2>&1
```

**Features:**
- ✅ Checks `/api/readyz` endpoint
- ✅ Verifies MQTT connection status
- ✅ Auto-restarts container if unhealthy
- ✅ Optional webhook alerting
- ✅ Colored output (✅ ❌ ⚠️)

---

## 🚀 Quick Start Guide

### For First-Time Deployment:

1. **Read first:** [`DEPLOYMENT_QUICKREF.md`](./DEPLOYMENT_QUICKREF.md) (5 min)
2. **Follow step-by-step:** [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md) (30-45 min)
3. **Configure Nginx:** Use [`nginx-config-production.conf`](./nginx-config-production.conf)
4. **Setup environment:** Use [`.env.production.template`](./.env.production.template)
5. **Install monitoring:** Use [`check-mqtt-health.sh`](./check-mqtt-health.sh)
6. **Verify:** Follow verification steps in deployment guide

### For Troubleshooting:

1. **Quick fixes:** Check [`DEPLOYMENT_QUICKREF.md`](./DEPLOYMENT_QUICKREF.md) troubleshooting section
2. **Deep analysis:** Read relevant section in [`STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md`](./STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md)
3. **Visual understanding:** See [`ARCHITECTURE_DIAGRAMS.md`](./ARCHITECTURE_DIAGRAMS.md)

### For Understanding:

1. **Architecture:** [`ARCHITECTURE_DIAGRAMS.md`](./ARCHITECTURE_DIAGRAMS.md)
2. **Technical details:** [`STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md`](./STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md)
3. **Data flows:** See "Component Communication Flow" in architecture diagrams

---

## ✅ Deployment Checklist

Use this checklist when deploying:

### Pre-Deployment
- [ ] Read `DEPLOYMENT_QUICKREF.md`
- [ ] Server has Ubuntu/Debian Linux
- [ ] Domain DNS pointing to server IP
- [ ] SSH access configured
- [ ] At least 2GB RAM, 10GB disk

### Infrastructure Setup
- [ ] Nginx installed
- [ ] Docker & Docker Compose installed
- [ ] SSL certificate obtained (Certbot)
- [ ] MySQL database created

### Configuration
- [ ] `.env` file created from template
- [ ] `DEBUG=False` in `.env`
- [ ] `REDIS_URL` configured in `.env`
- [ ] Strong `DJANGO_SECRET_KEY` generated
- [ ] Nginx config updated with correct paths
- [ ] Nginx enabled and reloaded

### Application
- [ ] Repository cloned
- [ ] Docker containers built
- [ ] Redis container running
- [ ] Migrations applied
- [ ] Static files collected
- [ ] Superuser created

### Monitoring
- [ ] Health check endpoint responding
- [ ] MQTT monitor script installed
- [ ] Cron job configured
- [ ] Logs accessible

### Verification
- [ ] Admin CSS loads (styled interface)
- [ ] WebSocket connects (`wss://...`)
- [ ] MQTT processes messages
- [ ] Alerts trigger correctly
- [ ] Dashboard shows devices
- [ ] Live updates work without refresh

---

## 🆘 Common Issues & Solutions

### Issue: Admin has no CSS
**Solution:** Check [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md) → "Issue: Admin Has No CSS"

### Issue: MQTT not connecting
**Solution:** Check [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md) → "Issue: MQTT Not Connecting"

### Issue: WebSocket fails
**Solution:** Check [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md) → "Issue: WebSocket Not Connecting"

### Issue: Dashboard empty
**Solution:** Check [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md) → "Issue: Dashboard Shows No Devices"

For detailed technical explanations, see [`STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md`](./STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md)

---

## 📊 What Each Issue Means

| Symptom | Root Cause | Document to Read |
|---------|------------|------------------|
| Admin shows plain text | Static files not served | DEPLOYMENT_GUIDE.md → Fix #1 |
| No telemetry data | MQTT thread not running | STAGING_DEPLOYMENT_ISSUES_AND_FIXES.md → Issue #2 |
| Empty dashboard | Multiple issues | DEPLOYMENT_QUICKREF.md → Troubleshooting |
| WebSocket errors | Missing headers/Redis | ARCHITECTURE_DIAGRAMS.md → WebSocket Flow |
| No live updates | All of the above | DEPLOYMENT_GUIDE.md → Full Guide |

---

## 🎯 Success Criteria

Your deployment is successful when all these pass:

### Functional Tests
- [ ] `/admin` loads with full CSS styling
- [ ] `/docs` shows OpenAPI documentation
- [ ] `/api/readyz` returns `{"status": "healthy"}`
- [ ] Device registration works via API
- [ ] MQTT messages create database records
- [ ] Smoke alerts trigger on threshold
- [ ] Dashboard map shows all devices
- [ ] Live updates appear without refresh
- [ ] WebSocket status is "Connected"

### Technical Verification
- [ ] `curl -I https://domain/static/admin/css/base.css` → HTTP 200
- [ ] `curl https://domain/api/readyz | jq` → healthy status
- [ ] `docker ps` → both containers running
- [ ] `docker logs fire_alarm_app | grep MQTT` → "✅ MQTT connected"
- [ ] Browser DevTools → WS connection shows 101 status

---

## 📞 Getting Help

If you encounter issues not covered in these docs:

1. **Check logs:**
   ```bash
   docker logs fire_alarm_app --tail=100
   sudo tail -f /var/log/nginx/error.log
   ```

2. **Run health check:**
   ```bash
   curl -s https://your-domain/api/readyz | jq
   ```

3. **Verify environment:**
   ```bash
   docker exec fire_alarm_app env | grep -E "(DEBUG|REDIS|MQTT)"
   ```

4. **Test components:**
   - Static files: `curl -I https://domain/static/admin/css/base.css`
   - WebSocket: Check browser DevTools → Network → WS
   - MQTT: Check logs for "✅ MQTT connected"
   - Database: `docker exec fire_alarm_app python manage.py dbshell`

---

## 📝 Document Maintenance

**Last Updated:** October 6, 2025  
**Django Version:** 5.1.2  
**Channels Version:** 4.1.0  
**Redis Version:** 7-alpine  

**When to update these docs:**
- Django/Channels version upgrade
- New deployment requirements
- Additional production issues discovered
- Infrastructure changes (Nginx, Docker, etc.)

---

## 🎉 Summary

This deployment guide provides **everything you need** to deploy the Fire Alarm Backend to production:

- ✅ **7 documentation files** covering all aspects
- ✅ **3 configuration files** ready to use
- ✅ **Step-by-step instructions** from scratch to running
- ✅ **Troubleshooting guides** for common issues
- ✅ **Architecture diagrams** for visual understanding
- ✅ **Health monitoring** for reliability

**Estimated deployment time: 30-45 minutes** for experienced engineers, 1-2 hours for first-time deployers.

**All documents are standalone** - you can read them in any order based on your needs!

---

**Happy Deploying! 🚀**
