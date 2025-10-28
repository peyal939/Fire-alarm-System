# 📱 Firebase Cloud Messaging API Documentation for Mobile Developers

## 🌐 Base URL
```
http://your-backend-url/api/fcm/
```

## 🔐 Authentication
All endpoints require **JWT Bearer Token**:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Get JWT token from login endpoint: `POST /api/auth/login/`

---

## 📋 API Endpoints

### 1️⃣ Register FCM Device Token

**Register a device to receive push notifications**

```http
POST /api/fcm/devices/
Content-Type: application/json
Authorization: Bearer {your_jwt_token}
```

**Request Body:**
```json
{
  "registration_token": "fX7K9m2pQ3w:APA91bF...",
  "device_name": "John's iPhone 13",
  "device_type": "ios"
}
```

**Parameters:**
| Field | Type | Required | Options | Description |
|-------|------|----------|---------|-------------|
| `registration_token` | string | ✅ Yes | - | FCM token from Firebase SDK |
| `device_name` | string | ❌ No | - | Friendly device name |
| `device_type` | string | ✅ Yes | `android`, `ios`, `web` | Device platform |

**Success Response (201 Created):**
```json
{
  "id": 1,
  "registration_token": "fX7K9m2pQ3w:APA91bF...",
  "device_name": "John's iPhone 13",
  "device_type": "ios",
  "active": true,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:00Z",
  "last_used_at": null
}
```

**Error Responses:**
```json
// 400 Bad Request - Empty token
{
  "registration_token": ["Registration token cannot be empty"]
}

// 401 Unauthorized - Missing/invalid JWT
{
  "detail": "Authentication credentials were not provided."
}
```

**Example with cURL:**
```bash
curl -X POST "http://localhost:8000/api/fcm/devices/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "registration_token": "fX7K9m2pQ3w:APA91bF...",
    "device_name": "My Phone",
    "device_type": "android"
  }'
```

**When to call:**
- ✅ On user login (after getting JWT token)
- ✅ On app startup (if user already logged in)
- ✅ When FCM token refreshes (`onNewToken()` callback)
- ✅ After app reinstall

**Notes:**
- If token already exists, it will be updated with new user/info
- Same device can register multiple times (will update existing)
- Backend automatically reactivates if token was deactivated

---

### 2️⃣ List Registered Devices

**Get all devices registered for current user**

```http
GET /api/fcm/devices/
Authorization: Bearer {your_jwt_token}
```

**Success Response (200 OK):**
```json
[
  {
    "id": 1,
    "registration_token": "fX7K9m2pQ3w:APA91bF...",
    "device_name": "John's iPhone 13",
    "device_type": "ios",
    "active": true,
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z",
    "last_used_at": "2024-01-15T14:20:00Z"
  },
  {
    "id": 2,
    "registration_token": "dR3L8k1nM9v:APA91bH...",
    "device_name": "John's iPad Pro",
    "device_type": "ios",
    "active": true,
    "created_at": "2024-01-14T09:15:00Z",
    "updated_at": "2024-01-14T09:15:00Z",
    "last_used_at": "2024-01-15T13:45:00Z"
  }
]
```

**Example with cURL:**
```bash
curl -X GET "http://localhost:8000/api/fcm/devices/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Use cases:**
- Display user's registered devices in settings
- Device management screen
- Show last notification time (`last_used_at`)

---

### 3️⃣ Send Test Notification

**Send a test push notification to all user's devices**

```http
POST /api/fcm/devices/test/
Content-Type: application/json
Authorization: Bearer {your_jwt_token}
```

**Request Body (Optional):**
```json
{
  "message": "Custom test message"
}
```

**Success Response (200 OK):**
```json
{
  "message": "Test notification sent successfully",
  "results": {
    "success": 2,
    "failure": 0,
    "invalid_tokens": []
  }
}
```

**No Devices Response (404 Not Found):**
```json
{
  "message": "No active devices found to send notification",
  "results": {
    "success": 0,
    "failure": 0,
    "invalid_tokens": []
  }
}
```

**Example with cURL:**
```bash
curl -X POST "http://localhost:8000/api/fcm/devices/test/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{}'
```

**What you'll receive on mobile:**
```json
{
  "notification": {
    "title": "Test Notification",
    "body": "Your fire alarm notifications are working correctly!"
  },
  "data": {
    "type": "test"
  }
}
```

**Use cases:**
- "Test notifications" button in app settings
- Verify notifications work after registration
- Troubleshooting notification issues

---

### 4️⃣ Unregister Device

**Remove device token (stop receiving notifications)**

```http
DELETE /api/fcm/devices/{device_id}/
Authorization: Bearer {your_jwt_token}
```

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `device_id` | integer | ID from device list (from GET /api/fcm/devices/) |

**Success Response (204 No Content):**
```
(No response body)
```

**Error Response (404 Not Found):**
```json
{
  "detail": "Not found."
}
```

**Example with cURL:**
```bash
curl -X DELETE "http://localhost:8000/api/fcm/devices/1/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**When to call:**
- ✅ On user logout (IMPORTANT!)
- ✅ On "Remove device" in settings
- ✅ When user wants to stop notifications

---

### 5️⃣ Deactivate Device

**Temporarily pause notifications without deleting token**

```http
POST /api/fcm/devices/{device_id}/deactivate/
Authorization: Bearer {your_jwt_token}
```

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `device_id` | integer | ID from device list |

**Success Response (200 OK):**
```json
{
  "id": 1,
  "registration_token": "fX7K9m2pQ3w:APA91bF...",
  "device_name": "John's iPhone 13",
  "device_type": "ios",
  "active": false,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T16:45:00Z",
  "last_used_at": "2024-01-15T14:20:00Z"
}
```

**Example with cURL:**
```bash
curl -X POST "http://localhost:8000/api/fcm/devices/1/deactivate/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Use cases:**
- "Pause notifications" feature
- Temporarily disable without removing device
- Can be reactivated later

---

### 6️⃣ Reactivate Device

**Resume receiving notifications on previously deactivated device**

```http
POST /api/fcm/devices/{device_id}/activate/
Authorization: Bearer {your_jwt_token}
```

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `device_id` | integer | ID from device list |

**Success Response (200 OK):**
```json
{
  "id": 1,
  "registration_token": "fX7K9m2pQ3w:APA91bF...",
  "device_name": "John's iPhone 13",
  "device_type": "ios",
  "active": true,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T17:00:00Z",
  "last_used_at": "2024-01-15T14:20:00Z"
}
```

**Example with cURL:**
```bash
curl -X POST "http://localhost:8000/api/fcm/devices/1/activate/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

### 7️⃣ View Notification History

**Get history of all notifications sent to user**

```http
GET /api/fcm/logs/
Authorization: Bearer {your_jwt_token}
```

**Query Parameters:**
| Parameter | Type | Options | Description |
|-----------|------|---------|-------------|
| `status` | string | `sent`, `failed`, `invalid_token` | Filter by status |

**Success Response (200 OK):**
```json
[
  {
    "id": 123,
    "title": "🚨 Fire Alert!",
    "body": "High smoke detected on Kitchen Sensor!",
    "data": {
      "type": "fire_alert",
      "alert_id": "45",
      "alert_type": "smoke_high",
      "device_name": "Kitchen Sensor",
      "priority": "high"
    },
    "status": "sent",
    "error_message": "",
    "sent_at": "2024-01-15T14:30:00Z",
    "device_name": "John's iPhone 13"
  },
  {
    "id": 122,
    "title": "Test Notification",
    "body": "Your fire alarm notifications are working correctly!",
    "data": {
      "type": "test"
    },
    "status": "sent",
    "error_message": "",
    "sent_at": "2024-01-15T10:35:00Z",
    "device_name": "John's iPhone 13"
  }
]
```

**Example with cURL:**
```bash
# All notifications
curl -X GET "http://localhost:8000/api/fcm/logs/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# Only failed notifications
curl -X GET "http://localhost:8000/api/fcm/logs/?status=failed" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Use cases:**
- Show notification history in app
- Debug notification issues
- User can see what alerts they missed

---

## 🔔 Notification Payload Structure

When backend sends notification, your app receives:

### Fire Alert Notification

```json
{
  "notification": {
    "title": "🚨 Fire Alert!",
    "body": "High smoke detected on Kitchen Sensor!"
  },
  "data": {
    "type": "fire_alert",
    "alert_id": "123",
    "alert_type": "smoke_high",
    "device_name": "Kitchen Sensor",
    "priority": "high"
  }
}
```

**How to handle:**
```kotlin
// Android Example
when (remoteMessage.data["type"]) {
    "fire_alert" -> {
        // HIGH PRIORITY ALERT
        // Play loud alarm sound
        // Show full-screen notification
        // Vibrate continuously
        // Make notification persistent
        val alertId = remoteMessage.data["alert_id"]
        val deviceName = remoteMessage.data["device_name"]
        showFireAlert(alertId, deviceName)
    }
}
```

---

### Device Status Alert

```json
{
  "notification": {
    "title": "⚠️ Device Status Alert",
    "body": "Bedroom Sensor reported status: error"
  },
  "data": {
    "type": "device_status",
    "alert_id": "124",
    "alert_type": "device_status",
    "device_name": "Bedroom Sensor",
    "device_status": "error"
  }
}
```

**How to handle:**
```kotlin
// Android Example
when (remoteMessage.data["type"]) {
    "device_status" -> {
        // NORMAL PRIORITY
        // Show standard notification
        // Default sound
        val deviceName = remoteMessage.data["device_name"]
        val status = remoteMessage.data["device_status"]
        showDeviceStatusAlert(deviceName, status)
    }
}
```

---

### Device Offline Notification

```json
{
  "notification": {
    "title": "⚠️ Device Offline",
    "body": "Living Room Sensor is now offline"
  },
  "data": {
    "type": "device_offline",
    "device_id": "456",
    "device_name": "Living Room Sensor"
  }
}
```

---

### Test Notification

```json
{
  "notification": {
    "title": "Test Notification",
    "body": "Your fire alarm notifications are working correctly!"
  },
  "data": {
    "type": "test"
  }
}
```

---

## 📱 Mobile Integration Flow

### Step 1: User Logs In
```
1. User enters email/password
2. Call POST /api/auth/login/
3. Get JWT token
4. Store JWT token securely
```

### Step 2: Get FCM Token
```kotlin
// Android
FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
    if (task.isSuccessful) {
        val fcmToken = task.result
        registerTokenWithBackend(fcmToken)
    }
}
```

### Step 3: Register with Backend
```
POST /api/fcm/devices/
{
  "registration_token": "fcmToken",
  "device_name": "Device.model",
  "device_type": "android"
}
```

### Step 4: Handle Token Refresh
```kotlin
// Android - When FCM token changes
override fun onNewToken(token: String) {
    super.onNewToken(token)
    // Re-register with backend
    registerTokenWithBackend(token)
}
```

### Step 5: Handle Incoming Notifications
```kotlin
override fun onMessageReceived(message: RemoteMessage) {
    val type = message.data["type"]
    when (type) {
        "fire_alert" -> handleFireAlert(message)
        "device_status" -> handleDeviceStatus(message)
        "device_offline" -> handleDeviceOffline(message)
        "test" -> handleTestNotification(message)
    }
}
```

### Step 6: User Logs Out
```
DELETE /api/fcm/devices/{device_id}/
```

---

## ⚠️ Important Notes

### Token Management
- FCM tokens can change - always handle `onNewToken()` callback
- Re-register when token refreshes
- One device can have only one active token
- Backend automatically updates if same token registered twice

### Multiple Devices
- Same user can register multiple devices
- Notifications sent to ALL active devices
- Each device has unique `device_id`

### Invalid Tokens
- Backend automatically detects and deactivates invalid tokens
- Invalid tokens won't receive notifications
- User should re-register if token becomes invalid

### Authentication
- All endpoints require valid JWT token
- Token expires after configured time (check with backend team)
- Refresh token before it expires

---

## 🐛 Troubleshooting

### Not Receiving Notifications

**1. Check token is registered:**
```bash
GET /api/fcm/devices/
```
Verify your device is listed with `active: true`

**2. Send test notification:**
```bash
POST /api/fcm/devices/test/
```

**3. Check notification logs:**
```bash
GET /api/fcm/logs/?status=failed
```

**4. Common issues:**
- ❌ Token not registered → Call `POST /api/fcm/devices/`
- ❌ Token deactivated → Re-register token
- ❌ JWT expired → Get new JWT token
- ❌ App permissions → Check notification permissions granted
- ❌ Firebase not configured → Add `google-services.json` / `GoogleService-Info.plist`

---

## 📊 Response Status Codes

| Code | Meaning | Description |
|------|---------|-------------|
| 200 | OK | Request successful |
| 201 | Created | Device registered successfully |
| 204 | No Content | Device deleted successfully |
| 400 | Bad Request | Invalid request data |
| 401 | Unauthorized | Missing or invalid JWT token |
| 404 | Not Found | Device or resource not found |
| 500 | Server Error | Backend error (contact support) |

---

## 🔗 Related Endpoints

### Get JWT Token (Login)
```http
POST /api/auth/login/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123"
}

Response:
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

Use `access` token as Bearer token in Authorization header.

---

## 📚 Additional Resources

- **Swagger UI:** http://localhost:8000/docs/
- **ReDoc:** http://localhost:8000/redoc/
- **Firebase Console:** https://console.firebase.google.com
- **FCM Documentation:** https://firebase.google.com/docs/cloud-messaging

---

## 🎯 Quick Checklist for Developer

- [ ] Add Firebase SDK to mobile app
- [ ] Download `google-services.json` (Android) or `GoogleService-Info.plist` (iOS)
- [ ] Implement FCM token retrieval
- [ ] Call `POST /api/fcm/devices/` on login
- [ ] Handle `onNewToken()` callback
- [ ] Implement notification handler for different types
- [ ] Call `DELETE /api/fcm/devices/{id}/` on logout
- [ ] Test with `POST /api/fcm/devices/test/`
- [ ] Handle notification permissions
- [ ] Test fire alert scenario

---

**Need help?** Contact backend team or check interactive API docs at `/docs/` 🚀
