#!/bin/bash
# MQTT Health Monitor Script
# Location: /usr/local/bin/check-mqtt-health.sh
#
# This script checks if MQTT is connected and restarts the container if needed.
# Set up as a cron job to run every 5 minutes:
# sudo crontab -e
# */5 * * * * /usr/local/bin/check-mqtt-health.sh >> /var/log/mqtt-monitor.log 2>&1

# Configuration
HEALTH_URL="https://firealarm.pranisheba.com.bd/api/readyz"
CONTAINER_NAME="fire_alarm_app"
ALERT_WEBHOOK=""  # Optional: Add your alerting webhook URL

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Timestamp
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "[$TIMESTAMP] Checking MQTT health..."

# Check if health endpoint is reachable
HTTP_CODE=$(curl -s -o /tmp/health-response.json -w "%{http_code}" "$HEALTH_URL")

if [ "$HTTP_CODE" != "200" ]; then
    echo -e "${RED}[$TIMESTAMP] ❌ Health endpoint returned HTTP $HTTP_CODE${NC}"
    
    # Try to restart container
    echo "[$TIMESTAMP] Attempting to restart $CONTAINER_NAME..."
    docker restart "$CONTAINER_NAME"
    
    # Send alert if webhook configured
    if [ ! -z "$ALERT_WEBHOOK" ]; then
        curl -X POST "$ALERT_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "{\"text\": \"🚨 Fire Alarm Backend health check failed. HTTP $HTTP_CODE. Container restarted.\"}"
    fi
    
    exit 1
fi

# Parse JSON response
MQTT_STATUS=$(cat /tmp/health-response.json | jq -r '.checks.mqtt.status' 2>/dev/null)
MQTT_CONNECTED=$(cat /tmp/health-response.json | jq -r '.checks.mqtt.connected' 2>/dev/null)
OVERALL_STATUS=$(cat /tmp/health-response.json | jq -r '.status' 2>/dev/null)

# Check MQTT status
if [ "$MQTT_STATUS" != "ok" ] || [ "$MQTT_CONNECTED" != "true" ]; then
    MQTT_ERROR=$(cat /tmp/health-response.json | jq -r '.checks.mqtt.error // "Unknown error"')
    echo -e "${RED}[$TIMESTAMP] ❌ MQTT is DOWN! Error: $MQTT_ERROR${NC}"
    
    # Try to restart container
    echo "[$TIMESTAMP] Attempting to restart $CONTAINER_NAME..."
    docker restart "$CONTAINER_NAME"
    
    # Send alert if webhook configured
    if [ ! -z "$ALERT_WEBHOOK" ]; then
        curl -X POST "$ALERT_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "{\"text\": \"🚨 MQTT connection lost on Fire Alarm Backend. Error: $MQTT_ERROR. Container restarted.\"}"
    fi
    
    exit 1
fi

# Check overall health
if [ "$OVERALL_STATUS" == "unhealthy" ]; then
    echo -e "${RED}[$TIMESTAMP] ❌ System unhealthy!${NC}"
    echo "[$TIMESTAMP] Full response:"
    cat /tmp/health-response.json | jq '.'
    
    # Send alert if webhook configured
    if [ ! -z "$ALERT_WEBHOOK" ]; then
        curl -X POST "$ALERT_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "{\"text\": \"🚨 Fire Alarm Backend system unhealthy. Check logs immediately.\"}"
    fi
    
    exit 1
elif [ "$OVERALL_STATUS" == "degraded" ]; then
    echo -e "${YELLOW}[$TIMESTAMP] ⚠️  System degraded (MQTT issues but database OK)${NC}"
    exit 0
else
    echo -e "${GREEN}[$TIMESTAMP] ✅ MQTT is healthy${NC}"
    
    # Show last message time if available
    LAST_MSG=$(cat /tmp/health-response.json | jq -r '.checks.mqtt.last_message_time // "N/A"')
    if [ "$LAST_MSG" != "N/A" ] && [ "$LAST_MSG" != "null" ]; then
        LAST_MSG_DATE=$(date -d @"$LAST_MSG" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "N/A")
        echo "[$TIMESTAMP] Last MQTT message: $LAST_MSG_DATE"
    fi
    
    exit 0
fi
