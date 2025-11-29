# APS Fire Alarm System - Web Application User Manual

**Version:** 1.0.0  
**Last Updated:** November 29, 2025  
**Platform:** Web Dashboard

---

## Table of Contents

1. [Introduction](#introduction)
2. [User Types & Roles](#user-types--roles)
3. [Regular User Guide](#regular-user-guide)
4. [Company Admin Guide](#company-admin-guide)
5. [Super Admin Guide](#super-admin-guide)
6. [Common Features](#common-features)
7. [Troubleshooting](#troubleshooting)
8. [FAQ](#faq)

---

## Introduction

The APS Fire Alarm System is a comprehensive IoT-based fire detection and alert platform designed to protect your home, office, or business premises. The web dashboard provides:

- **Real-time Fire Detection:** Continuous smoke level monitoring via live dashboard
- **Instant Alerts:** Email and SMS notifications when danger is detected
- **Live Dashboard:** Monitor all your devices in real-time with WebSocket updates
- **Emergency Coordination:** Quick access to Bangladesh fire station contacts
- **Mesh Networking:** Connect multiple devices (Master-Slave) for comprehensive coverage

### System Requirements

- **Web Browser:** Modern browser (Chrome, Firefox, Safari, Edge)
- **Internet Connection:** Stable internet required for real-time monitoring
- **Screen Resolution:** Minimum 1024x768 recommended

### Accessing the Web Dashboard

Navigate to your APS Fire Alarm System URL in your web browser:
```
https://your-domain.com/
```

---

## User Types & Roles

The APS Fire Alarm System has three user roles, each with different access levels:

| Feature | Regular User | Company Admin | Super Admin |
|---------|-------------|---------------|-------------|
| Register/Manage Own Devices | ✅ | ✅ | ✅ |
| View Own Device Dashboard | ✅ | ✅ | ✅ |
| Receive Alerts for Own Devices | ✅ | ✅ | ✅ |
| Purchase Device Packages | ✅ | ✅ | ✅ |
| Manage Devices from Orders | ❌ | ✅ | ✅ |
| View All Users | ❌ | ❌ | ✅ |
| Manage All Devices | ❌ | ❌ | ✅ |
| Manage Packages & Orders | ❌ | ❌ | ✅ |
| Assign Devices Cross-User | ❌ | ❌ | ✅ |
| Access Admin Panel | ❌ | ❌ | ✅ |

---

# Regular User Guide

## 1. Getting Started

### 1.1 Creating Your Account

1. **Navigate to the Registration Page:** Click "Register" or "Create Account" on the login page
2. **Enter Your Details:**
   - **Email Address:** This will be your login ID
   - **Phone Number:** For OTP verification and SMS alerts (Bangladesh format: +880XXXXXXXXXX)
   - **Password:** Minimum 8 characters, include uppercase, lowercase, and numbers
   - **Full Name:** Your complete name
   - **Address:** Your location/address
3. **Submit Registration:** Click the "Register" button
4. **Verify Your Phone:** Enter the OTP code sent to your phone via SMS
5. **Complete Registration:** Upon verification, you will be logged in automatically

### 1.2 Logging In

1. Navigate to the login page
2. Enter your **Email** or **Phone Number**
3. Enter your **Password**
4. Click **Login**
5. If OTP login is enabled, enter the verification code sent to your phone

### 1.3 Forgot Password

1. On the login page, click **"Forgot Password?"**
2. Enter your registered email or phone number
3. Click **"Send OTP"**
4. Enter the OTP code sent to your phone
5. Enter your new password
6. Confirm your new password
7. Click **"Reset Password"**
8. You can now log in with your new password

---

## 2. Dashboard Overview

### 2.1 Main Dashboard

After logging in, you will see the main dashboard with:

- **Device Overview:** Summary of all your registered devices
- **Live Status Map:** Geographic view of device locations
- **Alert Summary:** Count of active alerts
- **Quick Actions:** Shortcuts to common tasks

### 2.2 Navigation Menu

The navigation menu provides access to:

| Menu Item | Description |
|-----------|-------------|
| **Dashboard** | Main overview with device status |
| **Devices** | List and manage all your devices |
| **Alerts** | View and manage fire alerts |
| **Orders** | View your purchase history |
| **Fire Stations** | Find emergency contact numbers |
| **Profile** | Manage your account settings |

---

## 3. Device Management

### 3.1 Understanding Device Types

| Device Type | Description | Use Case |
|-------------|-------------|----------|
| **Master Device** | Standalone or primary device in a network | Main detector in a room/building |
| **Slave Device** | Connected to a master device | Additional coverage areas |

**Mesh Network:** A master device can have multiple slave devices connected to it. If any device in the mesh detects smoke, the entire network is flagged.

### 3.2 Viewing Your Devices

1. Click **"Devices"** in the navigation menu
2. View the device list with:
   - **Status Indicator:**
     - 🟢 **Green** = Online & Normal
     - 🟡 **Yellow** = Online with Alert
     - 🔴 **Red** = Active Alert/Danger
     - ⚪ **Gray** = Offline
   - **Device Name** and Hardware ID
   - **Last Seen** timestamp
   - **Current Smoke Level**
3. Devices are sorted with online devices first

### 3.3 Registering a New Device

1. Navigate to **Devices** page
2. Click **"Register Device"** or **"Add Device"**
3. Fill in the registration form:
   - **Hardware ID:** The unique ID printed on your device (e.g., FD-ABC123)
   - **Device Name:** A friendly name (e.g., "Kitchen Detector")
   - **Device Role:** Select "Master" for standalone or "Slave" if connecting to a master
   - **Location:** Click on the map to set device coordinates (Latitude/Longitude)
   - **Phone Number:** Optional phone for SMS alerts specific to this device
4. **For Slave Devices:**
   - Select the Master device from the dropdown list
   - The master must be a device you own
   - You cannot link a slave to another slave
5. Click **"Register"** to complete

### 3.4 Viewing Unclaimed Devices

If you purchased a package but haven't registered the devices yet:

1. Go to **Devices** → Click **"Unclaimed Devices"**
2. View the list of devices waiting to be claimed
3. Click on a device to register and configure it
4. These devices were assigned to you through your order fulfillment

### 3.5 Editing Device Details

1. Go to **Devices** and click on the device you want to edit
2. Click **"Edit"** button
3. You can update:
   - Device Name
   - Phone Number (for SMS alerts)
   - Location coordinates (click on map)
4. Click **"Save"** to apply changes

### 3.6 Viewing Device Details

Click on any device to see:
- **Current Status:** Online/Offline and smoke level
- **Device Information:** Hardware ID, role, registration date
- **Location:** Map showing device position
- **Linked Devices:** For masters, see all connected slaves
- **Recent Telemetry:** Latest sensor readings
- **Alert History:** Past alerts for this device

### 3.7 Deleting a Device

1. Go to **Devices** and click on the device
2. Click **"Delete"** button
3. Confirm the deletion in the popup dialog
4. **Note:** Deleted devices can be reclaimed later by re-registering with the same Hardware ID

---

## 4. Real-Time Monitoring

### 4.1 Live Dashboard

The dashboard uses WebSocket connections for real-time updates:

- **No Manual Refresh Needed:** Data updates automatically
- **Smoke Level Gauge:** Shows current reading (0-100+)
- **Status Updates:** Instant notification when device status changes
- **Mesh Alert Indicator:** Shows if any device in a network has an active alert

### 4.2 Device Status Indicators

| Status | Color | Meaning |
|--------|-------|---------|
| **Online - Normal** | 🟢 Green | Device connected, smoke level normal |
| **Online - Alert** | 🔴 Red | Device connected, smoke level high |
| **Offline** | ⚪ Gray | Device hasn't reported in 3+ minutes |

### 4.3 Online/Offline Detection

- A device is considered **online** if it reported data within the last 3 minutes (180 seconds)
- This is calculated in real-time based on the `last_seen` timestamp
- Offline devices may indicate power or connectivity issues

---

## 5. Alert Management

### 5.1 Understanding Alerts

| Alert Type | Trigger | Action Required |
|------------|---------|-----------------|
| **Smoke High** | Smoke level exceeds 50 (default threshold) | Check for fire, evacuate if necessary |

### 5.2 Viewing Alerts

1. Click **"Alerts"** in the navigation menu
2. View all alerts with:
   - Device name and location
   - Alert type
   - Trigger time
   - Current status (Open/Resolved)
3. Filter alerts by:
   - **Status:** Open, Resolved
   - **Device:** Specific device
   - **Date Range:** Custom time period

### 5.3 Alert Lifecycle

```
Smoke Detected (>50) → Alert Created (Open)
        ↓
   Notification Sent → Awaiting Response
        ↓
   [Acknowledge] → Acknowledged (still Open)
        ↓
   [Resolve] or Auto-Resolve → Resolved (Closed)
```

### 5.4 Managing Alerts

**To Acknowledge an Alert:**
1. Click on the alert to open details
2. Click **"Acknowledge"**
3. This indicates you are aware of the alert
4. Stops immediate reminder notifications
5. Does NOT resolve the alert

**To Resolve an Alert:**
1. Click on the alert to open details
2. Click **"Resolve"**
3. The alert is marked as closed
4. All reminder notifications stop
5. Resolved timestamp is recorded

**Auto-Resolution:**
- Alerts automatically resolve when smoke levels return to normal
- Requires consecutive safe readings (below threshold)
- No manual action needed for auto-resolution

### 5.5 Alert Reminders

If you don't acknowledge or resolve an alert:
- **Reminder Interval:** Every 10 minutes (default)
- **Maximum Reminders:** 3 per alert (default)
- **After Acknowledgment:** 10-minute escalation window before reminders resume

### 5.6 Mesh Network Alerts

- If ANY device in a master-slave network has an active alert, the entire mesh is flagged
- The dashboard shows `mesh_alert: true` for visual indication
- You receive notifications for alerts on any device you own

---

## 6. Viewing Device History

### 6.1 Telemetry Data

1. Click on a device from the dashboard
2. Click **"View History"** or **"Telemetry"** tab
3. View historical data including:
   - Smoke levels over time
   - Device status changes
   - Timestamps for each reading
4. Use date filters to narrow the time range

### 6.2 Alert History

1. Go to **Alerts** → Toggle to **"History"** or **"All"**
2. View past resolved alerts with:
   - Trigger time
   - Resolution time
   - Duration
   - Who acknowledged/resolved

---

## 7. Purchasing Device Packages

### 7.1 Browse Available Packages

1. Navigate to **Shop** or **Packages** section
2. View available packages showing:
   - Package Name
   - Number of devices included
   - Price per device
   - Monthly Recurring Fee (MRF)
3. Click on a package for detailed information

### 7.2 Placing an Order

1. Select a package
2. Choose quantity (within package limits)
3. Specify device breakdown:
   - Number of Master devices
   - Number of Slave devices
4. Enter shipping information:
   - Full Name
   - Phone Number
   - Shipping Address
5. Click **"Proceed to Payment"**
6. Complete payment via ShurjoPay gateway
7. Receive order confirmation

### 7.3 Tracking Your Orders

1. Navigate to **Orders** or **My Purchases**
2. View your order history with status:
   - **Pending:** Awaiting payment
   - **Paid:** Payment confirmed, awaiting shipment
   - **Delivered:** Order fulfilled and shipped
   - **Failed/Cancelled:** Payment failed or order cancelled

---

## 8. Finding Fire Stations

### 8.1 Accessing Fire Station Directory

1. Click **"Fire Stations"** in the navigation menu
2. Browse the hierarchical directory:
   - **Division:** Select region (e.g., Dhaka, Chittagong)
   - **District:** Select sub-region
   - **Stations:** View individual fire stations

### 8.2 Fire Station Information

Each fire station listing includes:
- **Station Name:** In Bengali (বাংলা) and English
- **Location:** District and division
- **Contact Numbers:** Multiple phone numbers if available

### 8.3 Quick Contact

- Click on any phone number to copy it
- Use for emergency calls when needed

---

## 9. Profile & Account Settings

### 9.1 Viewing Your Profile

1. Click on your name/avatar in the top navigation
2. Select **"Profile"** or **"Settings"**
3. View your account information:
   - Email
   - Phone Number
   - Full Name
   - Address
   - Role
   - Registered Devices count

### 9.2 Updating Your Profile

1. Go to **Profile** → Click **"Edit"**
2. Update editable fields:
   - Full Name
   - Phone Number
   - Address
3. Click **"Save Changes"**
4. **Note:** Email address cannot be changed

### 9.3 Changing Your Password

1. Go to **Profile** → **"Security"** or **"Change Password"**
2. Enter your **Current Password**
3. Enter your **New Password**
4. Confirm the new password by entering it again
5. Click **"Update Password"**

---

# Company Admin Guide

As a Company Admin, you have all Regular User capabilities plus additional features for managing organizational devices.

## 1. Company Admin Overview

Company Admins are typically:
- Business owners managing multiple premises
- Property managers overseeing multiple properties
- Organizations with centralized fire safety management

## 2. Extended Device Management

### 2.1 Managing Devices from Orders

When you place orders for your organization:

1. Go to **Devices** → **"All Devices"**
2. You can view and manage:
   - Devices registered under your account
   - Devices from orders placed under your account
3. This enables centralized management of all organizational devices

### 2.2 Organizing Devices by Location

Best practices for Company Admins:

1. **Naming Convention:** Use clear names like "Building A - Floor 2 - Room 201"
2. **Accurate Coordinates:** Set precise GPS locations for each device
3. **Master-Slave Grouping:** Group devices by building/floor using mesh networks
4. **Contact Numbers:** Set different phone numbers for on-site personnel

### 2.3 Device Overview Dashboard

Company Admins see an enhanced dashboard with:
- All devices in a single consolidated view
- Filter by status, role, or location
- Quick identification of problematic devices
- Aggregated alert counts

## 3. Alert Management for Organizations

### 3.1 Centralized Alert Monitoring

1. Access the **Alerts** dashboard
2. View alerts from ALL devices you own or ordered
3. Sort by location or severity
4. Delegate response based on device location

### 3.2 Alert Delegation

For multi-location organizations:
1. Set appropriate phone numbers on each device
2. SMS alerts go to the contact assigned to that device
3. Dashboard provides overview for central management

## 4. Order Management

### 4.1 Bulk Ordering

1. Navigate to **Packages**
2. Select packages for multiple locations
3. Place orders with bulk quantities
4. Track fulfillment status

### 4.2 Device Fulfillment Tracking

1. Go to **Orders** to view order status
2. When devices arrive, claim them via **Unclaimed Devices**
3. Register devices with location-specific details

---

# Super Admin Guide

Super Admins have complete system access for platform administration.

## 1. Super Admin Overview

Super Admin responsibilities:
- Platform-wide user management
- All device oversight and troubleshooting
- Package and pricing management
- Order fulfillment and administration
- System monitoring and configuration

## 2. Accessing the Admin Panel

1. Log in with Super Admin credentials
2. Access the **Admin Panel** from the navigation menu
3. The admin interface provides access to all management functions

## 3. User Management

### 3.1 Viewing All Users

1. Go to **Admin** → **Users**
2. View complete user list with:
   - Email and Phone Number
   - Role (user, company_admin, superadmin)
   - Registration Date
   - Device Count
   - Account Status

### 3.2 Searching for Users

Use the search feature to find users:
- Search by email (partial match supported)
- Search by phone number
- Results update as you type

### 3.3 Editing User Accounts

1. Click on a user to open their profile
2. Click **"Edit"**
3. Modifiable fields:
   - Full Name
   - Phone Number
   - Address
   - Role (user, company_admin, superadmin)
   - Active status (enable/disable account)
4. Click **"Save Changes"**

### 3.4 Managing User Accounts

- **Deactivate User:** Set active status to false
- **Delete User:** Soft-delete (data preserved for audit)
- **Change Role:** Promote or demote user privileges

## 4. Device Administration

### 4.1 Viewing All Devices

1. Go to **Admin** → **Devices**
2. View all devices across all users
3. Available filters:
   - Owner/User
   - Status (online, offline, alert)
   - Device Role (master, slave)
   - Registration Date

### 4.2 Cross-User Device Assignment

Super Admins can assign slave devices to masters owned by different users:

1. Navigate to the slave device
2. Click **"Edit"**
3. In the Master dropdown, you can select ANY master device
4. Save changes

**Use Case:** Enterprise deployments where devices span multiple user accounts

### 4.3 Device Troubleshooting

For device issues:
1. Check **Last Seen** timestamp for connectivity
2. View **Telemetry History** for irregular readings
3. Verify device registration details
4. Check subscription status if access is suspended

### 4.4 Managing Device Subscriptions

1. Go to **Admin** → **Subscriptions**
2. View subscription status for all devices:
   - **Active:** Current and paid
   - **Grace:** Past due, within grace period
   - **Suspended:** Requires payment
3. Actions available:
   - Set admin override dates
   - Extend grace periods
   - Record manual payments

## 5. Package Management

### 5.1 Creating New Packages

1. Go to **Admin** → **Packages**
2. Click **"Add Package"**
3. Enter package details:
   - **Name:** Package display name
   - **Description:** Details about the package
   - **Min Quantity:** Minimum devices per order
   - **Max Quantity:** Maximum devices per order
   - **Price Per Device:** Individual device cost
   - **Monthly Fee (MRF):** Recurring subscription cost
4. Click **"Create Package"**

### 5.2 Editing Packages

1. Select a package from the list
2. Click **"Edit"**
3. Modify any package attributes
4. Click **"Save"**
5. **Note:** Changes do not affect existing orders

### 5.3 Deleting Packages

1. Select a package
2. Click **"Delete"**
3. Confirm deletion
4. Package is soft-deleted (hidden but data preserved)

## 6. Order Administration

### 6.1 Viewing All Orders

1. Go to **Admin** → **Orders**
2. View all orders system-wide
3. Filter by:
   - Status (pending, paid, delivered, failed, cancelled)
   - Package
   - User
   - Date range

### 6.2 Order Fulfillment

When fulfilling paid orders:

1. Find the order in **Paid** status
2. Click **"Fulfill Order"**
3. Enter hardware identifiers for each device:
   - Assign device IDs from inventory
   - Specify Master or Slave role for each
   - Optionally pre-assign master-slave relationships
4. Mark order as **Delivered**
5. User can now claim devices via their dashboard

### 6.3 Manual Order Updates

1. Select an order
2. Available actions:
   - Update status manually
   - Add payment transaction details
   - Add internal notes
   - Cancel order (with reason)

## 7. System Monitoring

### 7.1 Dashboard Overview

The admin dashboard shows:
- Total registered users
- Total active devices
- Online vs. offline device ratio
- Current active alerts
- Recent registration activity

### 7.2 Alert Monitoring

1. Go to **Admin** → **Alerts**
2. View all active alerts across the system
3. Identify patterns (multiple alerts in same area)
4. Contact users for critical unacknowledged alerts

### 7.3 System Health

Monitor system components:
- **MQTT Connection:** Verify broker connectivity
- **WebSocket Status:** Check real-time connections
- **Celery Workers:** Ensure background tasks running
- **Database:** Monitor query performance

## 8. Subscription Administration

### 8.1 Subscription Overview

1. Go to **Admin** → **Subscriptions**
2. View all device subscriptions
3. Status breakdown:
   - Active subscriptions
   - Grace period subscriptions
   - Suspended devices

### 8.2 Admin Overrides

For billing exceptions or customer service:

1. Select a device subscription
2. Set **"Admin Override Until"** date
3. Add notes explaining the reason
4. Device remains active until override expires
5. Useful for payment disputes or technical issues

### 8.3 Recording Manual Payments

When customers pay outside the normal flow:

1. Find the subscription or charge
2. Click **"Record Manual Payment"**
3. Enter payment reference/receipt number
4. Add notes for audit trail
5. Subscription status updates accordingly

### 8.4 Managing Grace Periods

1. View devices in **Grace** status
2. Options:
   - Extend grace period
   - Suspend immediately
   - Apply admin override
3. Send reminder communications as needed

---

# Common Features

## 1. Real-Time Updates via WebSocket

The dashboard maintains a live WebSocket connection:

- **Automatic Updates:** No page refresh needed
- **Instant Status Changes:** Updates within 1-2 seconds
- **Connection Heartbeat:** Ping/pong every 20 seconds to maintain connection
- **Reconnection:** Automatic reconnection if connection drops

## 2. Notification Preferences

### Email Notifications
- Alert notifications for smoke detection
- Order confirmations and status updates
- Account security notifications

### SMS Notifications
- Critical fire alerts
- OTP for authentication
- Sent to device-specific phone numbers

## 3. Data Export

Export your data for reporting:
- Device lists
- Alert history
- Telemetry data
- Order history

## 4. Language Support

- Interface available in English
- Fire station information in Bengali (বাংলা) and English
- Contact numbers use Bangladesh format

---

# Troubleshooting

## Device Issues

| Problem | Possible Cause | Solution |
|---------|---------------|----------|
| Device shows Offline | No internet/power at device | Check device power and WiFi connection |
| Device not registering | Incorrect hardware ID | Verify the ID matches exactly (case-sensitive) |
| Registration conflict (409) | Device registered by another user | Contact support for ownership transfer |
| Slave won't link to master | Different owners | Ensure same account owns both devices |
| Device location incorrect | Wrong coordinates | Edit device and update map location |

## Alert Issues

| Problem | Possible Cause | Solution |
|---------|---------------|----------|
| Not receiving SMS alerts | Wrong phone number | Update phone number in device settings |
| Too many reminders | Alert not acknowledged | Acknowledge or resolve the alert |
| False alarms | Threshold too sensitive | Contact support to adjust threshold |
| Alert not auto-resolving | Smoke level still high | Check device environment |

## Account Issues

| Problem | Possible Cause | Solution |
|---------|---------------|----------|
| Can't login | Wrong password | Use "Forgot Password" to reset |
| OTP not received | Wrong phone number | Verify registered phone number |
| Session expired | Token timeout | Log in again |
| Access denied | Insufficient permissions | Contact admin for role upgrade |

## Dashboard Issues

| Problem | Possible Cause | Solution |
|---------|---------------|----------|
| Dashboard not updating | WebSocket disconnected | Refresh the page |
| Slow loading | Network issue | Check internet connection |
| Data not showing | Session expired | Log out and log in again |
| Map not displaying | Browser blocking scripts | Allow JavaScript and cookies |

---

# FAQ

## General Questions

**Q: What browsers are supported?**  
A: Chrome, Firefox, Safari, and Edge (latest versions). Internet Explorer is not supported.

**Q: How many devices can I register?**  
A: There's no limit. You can register as many devices as you've purchased.

**Q: Can I access the dashboard from multiple computers?**  
A: Yes, you can log in from any device with a web browser.

**Q: What happens if my internet goes down?**  
A: IoT devices continue to detect smoke locally. Alerts are queued and sent once your connection is restored.

## Device Questions

**Q: What's the difference between Master and Slave devices?**  
A: Master devices work standalone or lead a mesh network. Slave devices must connect to a master and report through it.

**Q: Can I move a device to a different location?**  
A: Yes, edit the device and update the coordinates on the map.

**Q: What does "Unclaimed" device mean?**  
A: Devices from your order that haven't been registered yet. They're waiting for you to set them up.

**Q: Can I transfer a device to another user?**  
A: Contact support for device ownership transfers.

## Alert Questions

**Q: What smoke level triggers an alert?**  
A: The default threshold is 50. Values above this trigger a smoke_high alert.

**Q: How do I stop reminder notifications?**  
A: Acknowledge or resolve the alert to stop reminders.

**Q: What happens if I ignore an alert?**  
A: You'll receive up to 3 reminders (every 10 minutes by default).

**Q: Do alerts auto-resolve?**  
A: Yes, when smoke levels return to normal (below threshold) with consecutive safe readings.

## Billing Questions

**Q: What payment methods are accepted?**  
A: ShurjoPay gateway supports mobile banking, credit/debit cards, and other Bangladesh payment methods.

**Q: Is there a monthly fee?**  
A: Some packages include Monthly Recurring Fee (MRF) for subscription services. Check your package details.

**Q: What happens if I miss a payment?**  
A: Devices enter a grace period. After expiration, device access is suspended until payment is made.

**Q: How do I update payment information?**  
A: Contact support for billing inquiries.

## Security Questions

**Q: Is my data secure?**  
A: Yes, all connections use HTTPS encryption. Passwords are hashed and never stored in plain text.

**Q: Can someone else access my devices?**  
A: Only you (and Super Admins) can access your devices. Keep your login credentials secure.

**Q: What if I suspect unauthorized access?**  
A: Change your password immediately and contact support.

---

## Support Contact

**For Technical Support:**
- Email: support@apsfire.com
- Phone: +880-XXXX-XXXXXX

**For Emergencies:**
- Use the **Fire Stations** feature to find your nearest fire service
- National Emergency: **999**

---

*This user manual is subject to updates. Please check for the latest version on our website.*

**© 2025 APS Fire Alarm System. All rights reserved.**
