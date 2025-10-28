# Firebase Push Notifications Module

This module provides Firebase Cloud Messaging (FCM) integration for sending push notifications to mobile app users when fire alerts or device issues are detected.

## Features

- ✅ Automatic push notifications on fire alerts
- ✅ Device offline notifications
- ✅ Device status alerts
- ✅ Multiple device support per user
- ✅ Automatic token validation and cleanup
- ✅ Notification history and logging
- ✅ Test notification endpoint
- ✅ Admin panel for monitoring

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Firebase
Get your Firebase service account credentials from Firebase Console and either:

**Option A:** Place `firebase-credentials.json` in project root

**Option B:** Set environment variable:
```bash
export FIREBASE_CREDENTIALS_PATH=/path/to/credentials.json
```

### 3. Run Migrations
```bash
python manage.py makemigrations notifications
python manage.py migrate
```

### 4. Start Server
```bash
python manage.py runserver
```

Look for: `Firebase initialized successfully`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/fcm/devices/` | POST | Register FCM token |
| `/api/fcm/devices/` | GET | List user's devices |
| `/api/fcm/devices/{id}/` | DELETE | Unregister device |
| `/api/fcm/devices/test/` | POST | Send test notification |
| `/api/fcm/devices/{id}/deactivate/` | POST | Deactivate token |
| `/api/fcm/devices/{id}/activate/` | POST | Reactivate token |
| `/api/fcm/logs/` | GET | View notification history |

## Automatic Notifications

The system automatically sends notifications when:

1. **Fire Alert** - Smoke level exceeds threshold
   - 🚨 High priority notification
   - Custom alert sound
   - Sent to all user's devices

2. **Device Status Alert** - Device reports error status
   - ⚠️ Medium priority
   - Standard notification sound

3. **Device Offline** (can be added) - Device hasn't sent data in 3+ minutes

## Architecture

```
devices/services.py
    ↓ (alert created)
notifications/services.py
    ↓ (FCMService.send_alert_notification)
Firebase Cloud Messaging
    ↓
Mobile App
```

## Models

### FCMDevice
Stores user device tokens for push notifications.

Fields:
- `user` - Owner of the device
- `registration_token` - FCM token from mobile app
- `device_name` - User-friendly name (e.g., "John's iPhone")
- `device_type` - android/ios/web
- `active` - Whether token is valid
- `last_used_at` - Last successful notification

### NotificationLog
Audit log of all sent notifications.

Fields:
- `user` - Recipient
- `title` - Notification title
- `body` - Notification message
- `data` - Custom payload
- `status` - sent/failed/invalid_token
- `error_message` - If failed
- `sent_at` - Timestamp

## Testing

### Send Test Notification
```bash
curl -X POST http://localhost:8000/api/fcm/devices/test/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Trigger Fire Alert (via MQTT)
```python
import paho.mqtt.client as mqtt
import json

client = mqtt.Client()
client.connect("localhost", 1883)

# Send high smoke reading
payload = {
    "device_id": "DEV001",
    "smoke": 75,  # Above threshold
    "status": "alert",
    "timestamp": int(time.time())
}

client.publish("aps/fire/data", json.dumps(payload))
```

### Check Notification Logs
1. Admin panel: `/admin/notifications/notificationlog/`
2. API: `GET /api/fcm/logs/`

## Monitoring

### Admin Panel
- `/admin/notifications/fcmdevice/` - View registered devices
- `/admin/notifications/notificationlog/` - View notification history

### Logs
```bash
# Check Firebase initialization
grep "Firebase initialized" logs/app.log

# Check notification sends
grep "Notification sent successfully" logs/app.log

# Check for errors
grep "Failed to send notification" logs/app.log
```

## Configuration

Environment variables:

```bash
# Firebase credentials (choose one)
FIREBASE_CREDENTIALS_PATH=firebase-credentials.json
# OR
FIREBASE_CREDENTIALS='{"type":"service_account",...}'
```

## Security

- ✅ Firebase credentials never committed to git
- ✅ Tokens validated automatically
- ✅ Invalid tokens deactivated
- ✅ User isolation (users only see their tokens)
- ✅ JWT authentication required

## Mobile Integration

See `MOBILE_FCM_GUIDE.md` for detailed mobile app integration instructions.

Quick example:
```kotlin
// Android - Register token
val token = FirebaseMessaging.getInstance().token.await()
api.registerToken(TokenRequest(token, "My Phone", "android"))
```

## Troubleshooting

### Firebase not initializing
- Check credentials file exists
- Verify JSON format is valid
- Check file permissions

### Notifications not received
- Verify token registered: `GET /api/fcm/devices/`
- Check notification logs: `GET /api/fcm/logs/`
- Test from Firebase Console
- Verify mobile app has notification permissions

### Invalid token errors
- Automatically handled - tokens deactivated
- Mobile app should re-register on token refresh

## Development

### Add New Notification Type

1. Add method to `notifications/services.py`:
```python
@staticmethod
def send_custom_notification(user, ...):
    return FCMService.send_to_user(
        user=user,
        title="Custom Title",
        body="Custom message",
        data={"type": "custom", ...}
    )
```

2. Call from your code:
```python
from notifications.services import FCMService
FCMService.send_custom_notification(user, ...)
```

### Customize Notification Sound

In `services.py`, change `sound` parameter:
```python
FCMService.send_to_user(..., sound="custom_sound")
```

Mobile app must include the sound file.

## Documentation

- `FIREBASE_SETUP_GUIDE.md` - Complete setup guide
- `MOBILE_FCM_GUIDE.md` - Mobile developer integration guide
- This README - Module overview

## Support

For issues:
1. Check server logs for errors
2. Verify Firebase Console shows message delivery
3. Test with Firebase Console "Send test message"
4. Review notification logs in admin panel
