from __future__ import annotations

from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from products.models import Package, Cart, CartItem, Order


class CartModelTests(TestCase):
    """Tests for Cart and CartItem models."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
        )
        self.package = Package.objects.create(
            name="Test Package",
            min_quantity=1,
            max_quantity=10,
            price_per_device=Decimal("1000.00"),
            mrf=Decimal("100.00"),
        )

    def test_cart_creation(self):
        """Test cart is created with proper expiry."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        self.assertEqual(cart.user, self.user)
        self.assertFalse(cart.is_expired)

    def test_cart_expiry(self):
        """Test cart expiry detection."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertTrue(cart.is_expired)

    def test_cart_refresh_expiry(self):
        """Test cart expiry refresh."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertTrue(cart.is_expired)
        cart.refresh_expiry(7)
        self.assertFalse(cart.is_expired)

    def test_cart_item_line_total(self):
        """Test cart item line total calculation."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        item = CartItem.objects.create(
            cart=cart,
            package=self.package,
            quantity=3,
        )
        # (1000 + 100) * 3 = 3300
        expected = Decimal("3300.00")
        self.assertEqual(item.line_total, expected)

    def test_cart_total(self):
        """Test cart total calculation."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        CartItem.objects.create(cart=cart, package=self.package, quantity=2)
        # (1000 + 100) * 2 = 2200
        expected = Decimal("2200.00")
        self.assertEqual(cart.get_total(), expected)


class CartAPITests(APITestCase):
    """Tests for Cart API endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            role="user",
        )
        self.package = Package.objects.create(
            name="Test Package",
            min_quantity=1,
            max_quantity=10,
            price_per_device=Decimal("1000.00"),
            mrf=Decimal("100.00"),
        )
        self.client.force_authenticate(user=self.user)

    def test_get_cart_creates_if_not_exists(self):
        """Test GET /cart/ creates cart if it doesn't exist."""
        url = reverse("cart")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("items", response.data)
        self.assertIn("total", response.data)
        self.assertTrue(Cart.objects.filter(user=self.user).exists())

    def test_add_item_to_cart(self):
        """Test POST /cart/items/ adds item to cart."""
        url = reverse("cart-items")
        data = {
            "package_id": self.package.pk,
            "quantity": 2,
            "number_of_master_devices": 2,
            "number_of_slave_devices": 0,
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["quantity"], 2)

    def test_add_item_updates_existing(self):
        """Test adding same package updates existing item."""
        # Add first item
        url = reverse("cart-items")
        data = {"package_id": self.package.pk, "quantity": 2}
        self.client.post(url, data, format="json")
        
        # Add same package again
        data["quantity"] = 5
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["quantity"], 5)
        
        # Should still be only one item
        cart = Cart.objects.get(user=self.user)
        self.assertEqual(cart.items.count(), 1)

    def test_update_cart_item(self):
        """Test PATCH /cart/items/<id>/ updates quantity."""
        # Create cart with item
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        item = CartItem.objects.create(cart=cart, package=self.package, quantity=2)
        
        url = reverse("cart-item-detail", kwargs={"item_id": item.pk})
        response = self.client.patch(url, {"quantity": 5}, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 5)

    def test_delete_cart_item(self):
        """Test DELETE /cart/items/<id>/ removes item."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        item = CartItem.objects.create(cart=cart, package=self.package, quantity=2)
        
        url = reverse("cart-item-detail", kwargs={"item_id": item.pk})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CartItem.objects.filter(pk=item.pk).exists())

    def test_clear_cart(self):
        """Test DELETE /cart/ clears all items."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        CartItem.objects.create(cart=cart, package=self.package, quantity=2)
        
        url = reverse("cart")
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        cart.refresh_from_db()
        self.assertEqual(cart.items.count(), 0)

    def test_checkout_creates_orders(self):
        """Test POST /cart/checkout/ creates orders from cart."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        CartItem.objects.create(
            cart=cart,
            package=self.package,
            quantity=2,
            number_of_master_devices=2,
            number_of_slave_devices=0,
        )
        
        url = reverse("cart-checkout")
        data = {
            "shipping_address": "123 Test St",
            "customer_name": "Test Customer",
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("orders", response.data)
        self.assertEqual(len(response.data["orders"]), 1)
        
        # Cart should be empty
        cart.refresh_from_db()
        self.assertEqual(cart.items.count(), 0)
        
        # Order should exist
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.quantity, 2)
        self.assertEqual(order.shipping_address, "123 Test St")

    def test_checkout_empty_cart_fails(self):
        """Test checkout with empty cart returns error."""
        url = reverse("cart-checkout")
        response = self.client.post(url, {}, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_checkout_expired_cart_fails(self):
        """Test checkout with expired cart returns error."""
        cart = Cart.objects.create(
            user=self.user,
            expires_at=timezone.now() - timedelta(days=1),
        )
        CartItem.objects.create(cart=cart, package=self.package, quantity=2)
        
        url = reverse("cart-checkout")
        response = self.client.post(url, {}, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expired", response.data["detail"].lower())

    def test_quantity_validation_min(self):
        """Test quantity below package minimum fails."""
        # Create package with min_quantity = 5
        package = Package.objects.create(
            name="Bulk Package",
            min_quantity=5,
            max_quantity=100,
            price_per_device=Decimal("800.00"),
            mrf=Decimal("80.00"),
        )
        
        url = reverse("cart-items")
        data = {"package_id": package.pk, "quantity": 2}
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_quantity_validation_max(self):
        """Test quantity above package maximum fails."""
        url = reverse("cart-items")
        data = {"package_id": self.package.pk, "quantity": 100}  # max is 10
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_cannot_checkout(self):
        """Test admin users cannot checkout."""
        admin = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
        )
        self.client.force_authenticate(user=admin)
        
        cart = Cart.objects.create(
            user=admin,
            expires_at=timezone.now() + timedelta(days=7),
        )
        CartItem.objects.create(cart=cart, package=self.package, quantity=2)
        
        url = reverse("cart-checkout")
        response = self.client.post(url, {}, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_access_denied(self):
        """Test unauthenticated requests are denied."""
        self.client.force_authenticate(user=None)
        
        url = reverse("cart")
        response = self.client.get(url)
        
        # DRF returns 403 Forbidden for unauthenticated requests by default
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
