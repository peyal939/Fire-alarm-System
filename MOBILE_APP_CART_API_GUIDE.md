# Mobile App Developer Guide: Cart System with COD Implementation

## Overview

This guide covers implementing the shopping cart system with Cash on Delivery (COD) support. The cart system replaces the old direct order creation flow.

---

## API Base URL

```
https://your-domain.com/api/products/
```

All endpoints require **JWT Authentication**:

```
Authorization: Bearer <access_token>
```

---

## Step 1: List Available Packages

Before adding to cart, fetch available packages to display to users.

**Endpoint:**

```
GET /api/products/packages/
```

**Response:**

```json
[
  {
    "id": 1,
    "name": "Basic Package",
    "min_quantity": 1,
    "max_quantity": 10,
    "price_per_device": "1500.00",
    "mrf": "100.00",
    "description": "Entry level fire alarm package"
  },
  {
    "id": 2,
    "name": "Premium Package",
    "min_quantity": 5,
    "max_quantity": 50,
    "price_per_device": "1200.00",
    "mrf": "80.00",
    "description": "Best value for larger installations"
  }
]
```

**Notes:**

- `min_quantity` / `max_quantity`: Enforce these limits in your UI
- `price_per_device`: Unit price for calculation
- `mrf`: Monthly Recurring Fee (for subscription display)

---

## Step 2: Add Item to Cart

When user selects a package and quantity, add it to cart.

**Endpoint:**

```
POST /api/products/cart/items/
```

**Request:**

```json
{
  "package_id": 1,
  "quantity": 3,
  "number_of_master_devices": 1,
  "number_of_slave_devices": 2
}
```

**Response (201 Created or 200 OK if updating existing):**

```json
{
  "id": 15,
  "package": {
    "id": 1,
    "name": "Basic Package",
    "price_per_device": "1500.00",
    "mrf": "100.00",
    "min_quantity": 1,
    "max_quantity": 10
  },
  "quantity": 3,
  "number_of_master_devices": 1,
  "number_of_slave_devices": 2,
  "line_total": "4500.00",
  "added_at": "2025-12-08T10:30:00+06:00",
  "updated_at": "2025-12-08T10:30:00+06:00"
}
```

**Validation Errors (400):**

```json
{
  "detail": "Minimum quantity for Basic Package is 1."
}
```

**Notes:**

- If same `package_id` already in cart, it **updates** the existing item (returns 200)
- `number_of_master_devices` + `number_of_slave_devices` should equal `quantity`

---

## Step 3: View Cart

Display the cart contents to the user.

**Endpoint:**

```
GET /api/products/cart/
```

**Response:**

```json
{
  "id": 5,
  "items": [
    {
      "id": 15,
      "package": {
        "id": 1,
        "name": "Basic Package",
        "price_per_device": "1500.00",
        "mrf": "100.00",
        "min_quantity": 1,
        "max_quantity": 10
      },
      "quantity": 3,
      "number_of_master_devices": 1,
      "number_of_slave_devices": 2,
      "line_total": "4500.00",
      "added_at": "2025-12-08T10:30:00+06:00",
      "updated_at": "2025-12-08T10:30:00+06:00"
    }
  ],
  "total": "4500.00",
  "item_count": 1,
  "expires_at": "2025-12-15T10:30:00+06:00",
  "is_expired": false,
  "created_at": "2025-12-08T10:30:00+06:00",
  "updated_at": "2025-12-08T10:30:00+06:00"
}
```

**Notes:**

- Cart expires after 7 days of inactivity
- If `is_expired` is true, prompt user to add items again
- Display `total` as the cart subtotal

---

## Step 4: Update Cart Item

Allow users to change quantity.

**Endpoint:**

```
PATCH /api/products/cart/items/{item_id}/
```

**Request:**

```json
{
  "quantity": 5,
  "number_of_master_devices": 2,
  "number_of_slave_devices": 3
}
```

**Response (200):**

```json
{
  "id": 15,
  "package": {...},
  "quantity": 5,
  "number_of_master_devices": 2,
  "number_of_slave_devices": 3,
  "line_total": "7500.00",
  ...
}
```

---

## Step 5: Remove Item from Cart

**Endpoint:**

```
DELETE /api/products/cart/items/{item_id}/
```

**Response:** `204 No Content`

---

## Step 6: Clear Entire Cart

**Endpoint:**

```
DELETE /api/products/cart/
```

**Response:** `204 No Content`

---

## Step 7: Checkout (⭐ Most Important)

Convert cart to order(s). This is where **payment method selection** happens.

**Endpoint:**

```
POST /api/products/cart/checkout/
```

### Request Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `shipping_address` | string | Recommended | Full shipping address |
| `customer_name` | string | Optional | Customer's full name |
| `customer_phone` | string | Optional | Contact phone number |
| `customer_email` | string | Optional | Email for order updates |
| `customer_city` | string | Optional | City name |
| `customer_post_code` | string | Optional | Postal/ZIP code |
| `customer_address` | string | Optional | Billing address (if different) |
| `currency` | string | Optional | Default: "BDT" |
| `payment_method` | string | **Required for COD** | `"online"` or `"cod"` |

### Payment Methods

| Value | Description |
|-------|-------------|
| `"online"` | Pay Now via shurjoPay gateway (default) |
| `"cod"` | Cash on Delivery - pay when product arrives |

---

### Example: Online Payment Checkout

**Request:**

```json
{
  "shipping_address": "House 123, Road 5, Dhanmondi, Dhaka 1205",
  "customer_name": "Mohammad Rahman",
  "customer_phone": "01712345678",
  "customer_email": "rahman@example.com",
  "customer_city": "Dhaka",
  "customer_post_code": "1205",
  "currency": "BDT",
  "payment_method": "online"
}
```

**Response (201):**

```json
{
  "orders": [
    {
      "id": 125,
      "user": 10,
      "package": 1,
      "quantity": 3,
      "amount": "4500.00",
      "currency": "BDT",
      "payment_method": "online",
      "order_status": "pending",
      "shipping_address": "House 123, Road 5, Dhanmondi, Dhaka 1205",
      "customer_name": "Mohammad Rahman",
      "customer_phone": "01712345678",
      "customer_email": "rahman@example.com",
      "customer_city": "Dhaka",
      "customer_post_code": "1205",
      "ordered_at": "2025-12-08T11:00:00+06:00"
    }
  ],
  "message": "Created 1 order(s) from cart."
}
```

**Next Step for Online Payment:** Call payment initiation endpoint (Step 8)

---

### Example: Cash on Delivery Checkout

**Request:**

```json
{
  "shipping_address": "House 456, Road 10, Gulshan, Dhaka 1212",
  "customer_name": "Fatima Begum",
  "customer_phone": "01898765432",
  "customer_email": "fatima@example.com",
  "customer_city": "Dhaka",
  "customer_post_code": "1212",
  "currency": "BDT",
  "payment_method": "cod"
}
```

**Response (201):**

```json
{
  "orders": [
    {
      "id": 126,
      "user": 10,
      "package": 1,
      "quantity": 3,
      "amount": "4500.00",
      "currency": "BDT",
      "payment_method": "cod",
      "order_status": "pending",
      "shipping_address": "House 456, Road 10, Gulshan, Dhaka 1212"
    }
  ],
  "message": "Created 1 order(s) from cart."
}
```

**Next Step for COD:** Show order confirmation screen. **No payment initiation needed.**

---

## Step 8: Initiate Payment (Online Only)

**Only call this for `payment_method: "online"` orders.**

**Endpoint:**

```
POST /api/products/orders/{user_id}/{order_id}/pay/
```

**Request:** Empty body or `{}`

**Response (200):**

```json
{
  "checkout_url": "https://securepay.shurjopay.com/checkout/abc123xyz",
  "sp_order_id": "SP123456789",
  "message": "Redirect user to checkout_url"
}
```

**Action:** Open `checkout_url` in a WebView or external browser for payment.

**Error for COD orders (400):**

```json
{
  "detail": "Payment initiation is only available for online payment orders."
}
```

---

## Step 9: View User's Orders

Display order history with payment method and status.

**Endpoint:**

```
GET /api/products/orders/{user_id}/
```

**Response:**

```json
[
  {
    "id": 126,
    "payment_method": "cod",
    "order_status": "pending",
    "amount": "4500.00",
    "shipping_address": "...",
    "ordered_at": "2025-12-08T11:00:00+06:00"
  },
  {
    "id": 125,
    "payment_method": "online",
    "order_status": "paid",
    "amount": "4500.00"
  }
]
```

---

## UI Implementation Guide

### Cart Screen

```
┌─────────────────────────────────────┐
│  🛒 Shopping Cart                   │
├─────────────────────────────────────┤
│  Basic Package          x3          │
│  ৳1,500 × 3 = ৳4,500               │
│  [−] [3] [+]            [🗑 Remove] │
├─────────────────────────────────────┤
│  Subtotal:              ৳4,500      │
│                                     │
│  [  Proceed to Checkout  ]          │
└─────────────────────────────────────┘
```

### Checkout Screen

```
┌─────────────────────────────────────┐
│  📦 Checkout                        │
├─────────────────────────────────────┤
│  Shipping Address *                 │
│  ┌─────────────────────────────┐   │
│  │ House 123, Road 5, Dhaka    │   │
│  └─────────────────────────────┘   │
│                                     │
│  Name            Phone              │
│  ┌──────────┐   ┌──────────┐       │
│  │ Rahman   │   │ 01712... │       │
│  └──────────┘   └──────────┘       │
│                                     │
│  Email           City               │
│  ┌──────────┐   ┌──────────┐       │
│  │ a@b.com  │   │ Dhaka    │       │
│  └──────────┘   └──────────┘       │
│                                     │
│  ─── Payment Method ───             │
│                                     │
│  ┌─────────────────────────────┐   │
│  │ ◉ Pay Now (Online)          │   │
│  │ ○ Cash on Delivery          │   │
│  └─────────────────────────────┘   │
│                                     │
│  Order Total:           ৳4,500      │
│                                     │
│  [    Place Order    ]              │
└─────────────────────────────────────┘
```

### Order Confirmation (COD)

```
┌─────────────────────────────────────┐
│  ✅ Order Placed!                   │
├─────────────────────────────────────┤
│  Order #126                         │
│                                     │
│  Payment: Cash on Delivery          │
│  Status: Awaiting Delivery          │
│                                     │
│  Please keep ৳4,500 ready           │
│  when your order arrives.           │
│                                     │
│  [  View My Orders  ]               │
└─────────────────────────────────────┘
```

### Orders List Screen

```
┌─────────────────────────────────────┐
│  📋 My Orders                       │
├─────────────────────────────────────┤
│  Order #126          Dec 8, 2025    │
│  ৳4,500             💵 COD          │
│  Status: ⏳ Pending                  │
├─────────────────────────────────────┤
│  Order #125          Dec 7, 2025    │
│  ৳3,000             💳 Online       │
│  Status: ✅ Paid                     │
│  [Pay Now] ← Hide for COD orders    │
└─────────────────────────────────────┘
```

---

## Order Status Reference

| Status | Display Text | Description |
|--------|--------------|-------------|
| `pending` | Pending / Awaiting Payment | Order created, not paid |
| `paid` | Paid | Payment received |
| `processing` | Processing | Being prepared |
| `shipped` | Shipped | On the way |
| `delivered` | Delivered | Complete |
| `cancelled` | Cancelled | Order cancelled |
| `failed` | Failed | Payment failed |
| `refunded` | Refunded | Money returned |

**For COD orders:** `pending` means "Awaiting Delivery" (payment will be collected on delivery)

---

## Step 10: Download Invoice (After Payment)

Once an order is **paid**, users can download their invoice. The system **automatically creates** the invoice when requested - just like professional e-commerce apps!

### 🎯 Recommended: Get Invoice by Order ID

The easiest way - just use the order ID to get the invoice. The system auto-creates it if needed.

```http
GET /api/subscriptions/invoices/order/{order_id}/
Authorization: Bearer {access_token}
```

**Response:**

```json
{
  "id": 5,
  "number": "INV-2025-0005",
  "user_email": "user@example.com",
  "order_id": 126,
  "subtotal": "4500.00",
  "tax": "0.00",
  "total": "4500.00",
  "status": "paid",
  "status_display": "Paid",
  "has_pdf": true,
  "issued_at": "2025-12-08T10:30:00Z",
  "paid_at": "2025-12-08T10:35:00Z",
  "line_items": [
    {
      "id": 1,
      "description": "Premium Package - Device Purchase",
      "quantity": 3,
      "unit_price": "1500.00",
      "total": "4500.00"
    }
  ]
}
```

### 📥 Download Invoice PDF by Order ID

One-click PDF download - the recommended approach for mobile apps:

```http
GET /api/subscriptions/invoices/order/{order_id}/pdf/
Authorization: Bearer {access_token}
```

**Response:** Binary PDF file

**Response Headers:**

```
Content-Type: application/pdf
Content-Disposition: attachment; filename="invoice_INV-2025-0005.pdf"
```

> **Note:** Invoice and PDF are auto-generated if they don't exist. Users only need the order ID!

### Mobile Implementation

**React Native Example:**

```javascript
// Download invoice PDF for an order - RECOMMENDED
const downloadInvoiceForOrder = async (orderId) => {
  try {
    const response = await fetch(
      `${BASE_URL}/api/subscriptions/invoices/order/${orderId}/pdf/`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      }
    );

    if (response.ok) {
      const blob = await response.blob();
      // Save to device using react-native-blob-util or expo-file-system
      const filename = `invoice_order_${orderId}.pdf`;
      // ... save file logic
    } else if (response.status === 400) {
      Alert.alert("Invoice not available", "Invoice is only available for paid orders.");
    }
  } catch (error) {
    console.error("Failed to download invoice:", error);
  }
};
```

**Flutter Example:**

```dart
Future<void> downloadInvoice(int orderId) async {
  final response = await http.get(
    Uri.parse('$baseUrl/api/subscriptions/invoices/order/$orderId/pdf/'),
    headers: {'Authorization': 'Bearer $accessToken'},
  );
  
  if (response.statusCode == 200) {
    // Save PDF to device
    final directory = await getApplicationDocumentsDirectory();
    final file = File('${directory.path}/invoice_$orderId.pdf');
    await file.writeAsBytes(response.bodyBytes);
    // Open PDF viewer
    OpenFile.open(file.path);
  }
}
```

### UI Integration - Order Detail Screen

```
┌─────────────────────────────────────┐
│  📦 Order #126                      │
│  Status: ✅ Paid                     │
├─────────────────────────────────────┤
│  Premium Package × 3                │
│  Total: ৳4,500                      │
├─────────────────────────────────────┤
│  Shipping: 123 Main St, Dhaka       │
│  Payment: 💳 Online                 │
├─────────────────────────────────────┤
│                                     │
│  [ 📄 Download Invoice ]            │  ← Only show for paid orders
│                                     │
└─────────────────────────────────────┘
```

**Show download button when:**

```javascript
const canDownloadInvoice = ["paid", "processing", "shipped", "delivered"].includes(
  order.order_status
);
```

### Alternative: List All Invoices

You can also list all user invoices (useful for invoice history screen):

```http
GET /api/subscriptions/invoices/
Authorization: Bearer {access_token}
```

**Response:**

```json
{
  "count": 2,
  "results": [
    {
      "id": 5,
      "number": "INV-2025-0005",
      "total": "4500.00",
      "status": "paid",
      "status_display": "Paid",
      "has_pdf": true,
      "issued_at": "2025-12-08T10:30:00Z",
      "paid_at": "2025-12-08T10:35:00Z"
    }
  ]
}
```

### Get Invoice Detail by Invoice ID

```http
GET /api/subscriptions/invoices/{invoice_id}/
Authorization: Bearer {access_token}
```

### Download PDF by Invoice ID

```http
GET /api/subscriptions/invoices/{invoice_id}/pdf/
Authorization: Bearer {access_token}
```

### Invoice Status Values

| Status | Description |
|--------|-------------|
| `draft` | Invoice created but not finalized |
| `pending` | Invoice sent, awaiting payment |
| `paid` | Payment received |
| `cancelled` | Invoice cancelled |
| `refunded` | Payment refunded |

---

## Error Handling

### Common Errors

**401 Unauthorized:**

```json
{"detail": "Authentication credentials were not provided."}
```

→ User needs to login again

**400 Bad Request - Empty Cart:**

```json
{"detail": "Cart is empty."}
```

→ Redirect to products/packages screen

**400 Bad Request - Expired Cart:**

```json
{"detail": "Cart has expired. Please add items again."}
```

→ Show message, redirect to products

**400 Bad Request - Quantity Validation:**

```json
{"detail": "Minimum quantity for Premium Package is 5."}
```

→ Show validation error on quantity field

**403 Forbidden - Admin User:**

```json
{"detail": "Admin users cannot create orders."}
```

→ Admin accounts cannot place orders

---

## Complete Flow Diagram

```
┌──────────────┐
│ Browse       │
│ Packages     │
└──────┬───────┘
       │ GET /packages/
       ▼
┌──────────────┐
│ Add to Cart  │
└──────┬───────┘
       │ POST /cart/items/
       ▼
┌──────────────┐
│ View Cart    │◄────────┐
└──────┬───────┘         │
       │ GET /cart/      │ Update/Remove
       ▼                 │
┌──────────────┐         │
│ Checkout     │─────────┘
│ Form         │
└──────┬───────┘
       │
       ▼
   ┌───────────────────┐
   │ Select Payment    │
   │ Method            │
   └─────────┬─────────┘
             │
     ┌───────┴───────┐
     ▼               ▼
┌─────────┐    ┌─────────┐
│ Online  │    │  COD    │
└────┬────┘    └────┬────┘
     │              │
     │ POST         │ POST
     │ /cart/       │ /cart/
     │ checkout/    │ checkout/
     │              │
     ▼              ▼
┌─────────┐    ┌─────────────┐
│ Initiate│    │ Order       │
│ Payment │    │ Confirmed!  │
└────┬────┘    │             │
     │         │ "Pay ৳X on  │
     │ POST    │  delivery"  │
     │ /pay/   └─────────────┘
     ▼
┌─────────┐
│ WebView │
│ Payment │
│ Gateway │
└────┬────┘
     │
     ▼
┌─────────────┐
│ Payment     │
│ Complete    │
└─────────────┘
```

---

## Quick Reference - All Endpoints

| Action | Method | Endpoint |
|--------|--------|----------|
| List packages | GET | `/api/products/packages/` |
| View cart | GET | `/api/products/cart/` |
| Add to cart | POST | `/api/products/cart/items/` |
| Update item | PATCH | `/api/products/cart/items/{id}/` |
| Remove item | DELETE | `/api/products/cart/items/{id}/` |
| Clear cart | DELETE | `/api/products/cart/` |
| **Checkout** | POST | `/api/products/cart/checkout/` |
| Initiate payment | POST | `/api/products/orders/{user_id}/{order_id}/pay/` |
| List orders | GET | `/api/products/orders/{user_id}/` |
| Order detail | GET | `/api/products/orders/{user_id}/{order_id}/` |
| **Invoice for order** | GET | `/api/subscriptions/invoices/order/{order_id}/` |
| **Download PDF for order** | GET | `/api/subscriptions/invoices/order/{order_id}/pdf/` |
| List all invoices | GET | `/api/subscriptions/invoices/` |
| Invoice detail | GET | `/api/subscriptions/invoices/{id}/` |
| Download PDF | GET | `/api/subscriptions/invoices/{id}/pdf/` |

---

## Migration from Old Order API

If you were using the old direct order creation:

### Old Way (Deprecated)

```
POST /api/products/orders/{user_id}/
{
  "package_id": 1,
  "quantity": 2,
  "shipping_address": "..."
}
```

- No COD support
- Creates order directly

### New Way (Recommended)

1. `POST /api/products/cart/items/` - Add to cart
2. `POST /api/products/cart/checkout/` - Checkout with `payment_method`
3. (If online) `POST /api/products/orders/{user_id}/{order_id}/pay/` - Get payment URL

**Key Changes:**

- Use cart endpoints instead of direct order creation
- Add payment method selector in checkout UI
- Only call `/pay/` for online orders, not COD

---

## Support

For API issues or questions, contact the backend team.

**OpenAPI Documentation:** `https://your-domain.com/docs/`
