from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import Cart, CartItem, Order
from .enums import PaymentMethod
from .cart_serializers import (
    CartSerializer,
    CartItemSerializer,
    CartItemCreateSerializer,
    CartItemUpdateSerializer,
    CartItemBulkCreateSerializer,
    CartCheckoutSerializer,
)
from .services import calculate_order_total


logger = logging.getLogger(__name__)

CART_EXPIRY_DAYS = 7


def get_or_create_cart(user) -> Cart:
    """Get existing cart or create a new one for the user."""
    try:
        cart = Cart.objects.get(user=user)
        # If cart is expired, clear it and refresh expiry
        if cart.is_expired:
            cart.items.all().delete()
            cart.refresh_expiry(CART_EXPIRY_DAYS)
        return cart
    except Cart.DoesNotExist:
        return Cart.objects.create(
            user=user,
            expires_at=timezone.now() + timedelta(days=CART_EXPIRY_DAYS),
        )


@extend_schema(tags=["Cart"])
class CartView(APIView):
    """Get current user's cart or clear it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get current user's shopping cart",
        responses={200: CartSerializer},
    )
    def get(self, request):
        """Retrieve the current user's cart with all items."""
        cart = get_or_create_cart(request.user)
        return Response(CartSerializer(cart).data)

    @extend_schema(
        summary="Clear the shopping cart",
        responses={204: None},
    )
    def delete(self, request):
        """Clear all items from the cart."""
        try:
            cart = Cart.objects.get(user=request.user)
            cart.items.all().delete()
            cart.refresh_expiry(CART_EXPIRY_DAYS)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Cart.DoesNotExist:
            return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Cart"])
class CartItemListView(APIView):
    """Add items to cart."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Add item to cart",
        request=CartItemCreateSerializer,
        responses={201: CartItemSerializer, 200: CartItemSerializer},
    )
    def post(self, request):
        """Add a package to the cart. If package already in cart, updates quantity."""
        serializer = CartItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cart = get_or_create_cart(request.user)
        package = serializer.validated_data["package_id"]
        quantity = serializer.validated_data.get("quantity", 1)
        master_devices = serializer.validated_data.get("number_of_master_devices", 1)
        slave_devices = serializer.validated_data.get("number_of_slave_devices", 0)

        # Check if item already exists in cart
        existing_item = cart.items.filter(package=package).first()
        if existing_item:
            # Update existing item
            existing_item.quantity = quantity
            existing_item.number_of_master_devices = master_devices
            existing_item.number_of_slave_devices = slave_devices
            existing_item.save()
            cart.refresh_expiry(CART_EXPIRY_DAYS)
            return Response(
                CartItemSerializer(existing_item).data,
                status=status.HTTP_200_OK,
            )

        # Create new item
        item = CartItem.objects.create(
            cart=cart,
            package=package,
            quantity=quantity,
            number_of_master_devices=master_devices,
            number_of_slave_devices=slave_devices,
        )
        cart.refresh_expiry(CART_EXPIRY_DAYS)
        return Response(CartItemSerializer(item).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Cart"])
class CartItemBulkView(APIView):
    """Bulk add multiple items to cart in a single request."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Bulk add items to cart",
        description="Add multiple packages to cart in a single request. Useful for mobile apps to reduce API calls.",
        request=CartItemBulkCreateSerializer,
        responses={
            201: CartSerializer,
            200: CartSerializer,
        },
    )
    def post(self, request):
        """
        Bulk add items to cart.
        
        If a package already exists in cart, its quantity will be updated.
        Returns the full cart after all items are processed.
        """
        serializer = CartItemBulkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cart = get_or_create_cart(request.user)
        items_data = serializer.validated_data["items"]
        
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for item_data in items_data:
                package = item_data["package_id"]
                quantity = item_data.get("quantity", 1)
                master_devices = item_data.get("number_of_master_devices", 1)
                slave_devices = item_data.get("number_of_slave_devices", 0)

                # Check if item already exists in cart
                existing_item = cart.items.filter(package=package).first()
                if existing_item:
                    # Update existing item
                    existing_item.quantity = quantity
                    existing_item.number_of_master_devices = master_devices
                    existing_item.number_of_slave_devices = slave_devices
                    existing_item.save()
                    updated_count += 1
                else:
                    # Create new item
                    CartItem.objects.create(
                        cart=cart,
                        package=package,
                        quantity=quantity,
                        number_of_master_devices=master_devices,
                        number_of_slave_devices=slave_devices,
                    )
                    created_count += 1

            cart.refresh_expiry(CART_EXPIRY_DAYS)

        # Refresh cart from DB to get updated items
        cart.refresh_from_db()
        
        logger.info(
            "Bulk cart items added",
            extra={
                "user_id": request.user.pk,
                "items_created": created_count,
                "items_updated": updated_count,
            },
        )

        response_status = status.HTTP_201_CREATED if created_count > 0 else status.HTTP_200_OK
        return Response(
            {
                "cart": CartSerializer(cart).data,
                "summary": {
                    "items_created": created_count,
                    "items_updated": updated_count,
                    "total_items_processed": created_count + updated_count,
                },
            },
            status=response_status,
        )


@extend_schema(tags=["Cart"])
class CartItemDetailView(APIView):
    """Update or remove a specific cart item."""

    permission_classes = [IsAuthenticated]

    def _get_item(self, request, item_id):
        """Get cart item ensuring it belongs to the user."""
        try:
            return CartItem.objects.select_related("cart", "package").get(
                id=item_id, cart__user=request.user
            )
        except CartItem.DoesNotExist:
            return None

    @extend_schema(
        summary="Update cart item quantity",
        request=CartItemUpdateSerializer,
        responses={200: CartItemSerializer, 404: None},
    )
    def patch(self, request, item_id: int):
        """Update the quantity of a cart item."""
        item = self._get_item(request, item_id)
        if not item:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = CartItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quantity = serializer.validated_data["quantity"]

        # Validate against package constraints
        if quantity < item.package.min_quantity:
            return Response(
                {"detail": f"Minimum quantity is {item.package.min_quantity}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if quantity > item.package.max_quantity:
            return Response(
                {"detail": f"Maximum quantity is {item.package.max_quantity}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        item.quantity = quantity
        if "number_of_master_devices" in serializer.validated_data:
            item.number_of_master_devices = serializer.validated_data[
                "number_of_master_devices"
            ]
        if "number_of_slave_devices" in serializer.validated_data:
            item.number_of_slave_devices = serializer.validated_data[
                "number_of_slave_devices"
            ]
        item.save()
        item.cart.refresh_expiry(CART_EXPIRY_DAYS)
        return Response(CartItemSerializer(item).data)

    @extend_schema(
        summary="Remove item from cart",
        responses={204: None, 404: None},
    )
    def delete(self, request, item_id: int):
        """Remove an item from the cart."""
        item = self._get_item(request, item_id)
        if not item:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Cart"])
class CartCheckoutView(APIView):
    """Convert cart to order(s)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Checkout - convert cart to order(s)",
        request=CartCheckoutSerializer,
        responses={
            201: {"type": "object", "properties": {"orders": {"type": "array"}}},
            400: None,
        },
    )
    def post(self, request):
        """
        Convert cart items into order(s).

        Creates one order per cart item (package). This maintains consistency
        with the existing order model which has a single package per order.
        """
        user = request.user

        # Validate user can create orders
        if user.is_superuser or getattr(user, "role", "") == "superadmin":
            return Response(
                {"detail": "Admin users cannot create orders."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            cart = Cart.objects.prefetch_related("items__package").get(user=user)
        except Cart.DoesNotExist:
            return Response(
                {"detail": "Cart is empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if cart.is_expired:
            cart.items.all().delete()
            return Response(
                {"detail": "Cart has expired. Please add items again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        items = list(cart.items.select_related("package").all())
        if not items:
            return Response(
                {"detail": "Cart is empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CartCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        checkout_data = serializer.validated_data

        created_orders = []

        with transaction.atomic():
            for item in items:
                # Calculate order total - MRF only for master devices
                total = calculate_order_total(
                    item.package, 
                    item.quantity,
                    item.number_of_master_devices
                )

                # Create order
                order = Order.objects.create(
                    user=user,
                    package=item.package,
                    quantity=item.quantity,
                    number_of_master_devices=item.number_of_master_devices,
                    number_of_slave_devices=item.number_of_slave_devices,
                    amount=total,
                    created_by=user,
                    shipping_address=checkout_data.get("shipping_address", ""),
                    currency=checkout_data.get("currency", "BDT"),
                    customer_name=checkout_data.get("customer_name", ""),
                    customer_address=checkout_data.get("customer_address", ""),
                    customer_phone=checkout_data.get("customer_phone", ""),
                    customer_city=checkout_data.get("customer_city", ""),
                    customer_post_code=checkout_data.get("customer_post_code", ""),
                    customer_email=checkout_data.get("customer_email", ""),
                    payment_method=checkout_data.get(
                        "payment_method", PaymentMethod.ONLINE
                    ),
                )
                order.reference = str(order.id)
                order.save(update_fields=["reference"])
                created_orders.append(order)

            # Clear cart after successful checkout
            cart.items.all().delete()
            cart.refresh_expiry(CART_EXPIRY_DAYS)

        logger.info(
            "Cart checkout completed",
            extra={
                "user_id": user.pk,
                "order_count": len(created_orders),
                "order_ids": [o.pk for o in created_orders],
            },
        )

        # Import here to avoid circular import
        from .serializers import OrderSerializer

        return Response(
            {
                "orders": OrderSerializer(created_orders, many=True).data,
                "message": f"Created {len(created_orders)} order(s) from cart.",
            },
            status=status.HTTP_201_CREATED,
        )
