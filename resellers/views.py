"""
Reseller API Views

This module provides API endpoints for resellers to:
- Manage their account and profile
- View and manage inventory
- Create and manage customers
- Assign devices to customers
- View dashboard/analytics
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from common.permissions import IsSuperAdmin, IsReseller, IsSuperAdminOrReseller, IsResellerWithAnyStatus
from devices.models import Device, Alert
from devices.serializers import DeviceSerializer, AlertSerializer

from .models import (
    Reseller,
    ResellerInventory,
    ResellerCustomer,
    ResellerPurchaseOrder,
    ResellerSale,
)
from .serializers import (
    ResellerSerializer,
    ResellerAdminSerializer,
    ResellerRegistrationSerializer,
    ResellerInventorySerializer,
    ResellerCustomerSerializer,
    ResellerCustomerCreateSerializer,
    ResellerLinkCustomerSerializer,
    DeviceAssignmentSerializer,
    ResellerDashboardSerializer,
    ResellerPurchaseOrderSerializer,
    ResellerSaleSerializer,
)

logger = logging.getLogger(__name__)


def get_user_reseller(user):
    """Helper to get the reseller account for a user."""
    return getattr(user, "reseller_account", None)


class ResellerRegistrationView(APIView):
    """
    Endpoint for company_admin users to register as resellers.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Resellers"],
        summary="Register as a reseller",
        description="Company admins can register their company as a reseller",
        request=ResellerRegistrationSerializer,
        responses={
            201: ResellerSerializer,
            400: OpenApiResponse(description="Validation error"),
            403: OpenApiResponse(description="Not a company admin"),
        },
    )
    def post(self, request):
        serializer = ResellerRegistrationSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            reseller = serializer.save()
            return Response(
                ResellerSerializer(reseller).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResellerProfileView(APIView):
    """
    Endpoint for resellers to view and update their profile.
    Accessible to resellers with any status (including pending).
    """
    permission_classes = [IsAuthenticated, IsResellerWithAnyStatus]

    @extend_schema(
        tags=["Resellers"],
        summary="Get reseller profile",
        responses={200: ResellerSerializer},
    )
    def get(self, request):
        reseller = get_user_reseller(request.user)
        return Response(ResellerSerializer(reseller).data)

    @extend_schema(
        tags=["Resellers"],
        summary="Update reseller profile",
        request=ResellerSerializer,
        responses={200: ResellerSerializer},
    )
    def patch(self, request):
        reseller = get_user_reseller(request.user)
        serializer = ResellerSerializer(
            reseller, data=request.data, partial=True, context={"request": request}
        )
        if serializer.is_valid():
            serializer.save(updated_by=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResellerDashboardView(APIView):
    """
    Dashboard summary for resellers.
    Accessible to resellers with any status (shows limited data for pending).
    """
    permission_classes = [IsAuthenticated, IsResellerWithAnyStatus]

    @extend_schema(
        tags=["Resellers"],
        summary="Get reseller dashboard",
        description="Returns summary statistics for the reseller dashboard",
        responses={200: ResellerDashboardSerializer},
    )
    def get(self, request):
        reseller = get_user_reseller(request.user)
        now = timezone.now()
        
        # For pending/suspended resellers, return minimal dashboard
        if not reseller.is_active:
            data = {
                "total_devices_sold": 0,
                "devices_in_inventory": 0,
                "total_customers": 0,
                "active_customers": 0,
                "total_revenue": Decimal("0.00"),
                "total_profit": Decimal("0.00"),
                "pending_commissions": Decimal("0.00"),
                "credit_available": Decimal("0.00"),
                "devices_online": 0,
                "devices_offline": 0,
                "recent_alerts_count": 0,
                "status": reseller.status,
                "status_message": self._get_status_message(reseller.status),
            }
            return Response(data)
        
        # Count devices
        devices = Device.objects.filter(reseller=reseller, deleted_at__isnull=True)
        total_devices = devices.count()
        
        # Online/Offline (based on last_seen within 3 minutes)
        online_threshold = now - timezone.timedelta(seconds=180)
        devices_online = devices.filter(last_seen__gte=online_threshold).count()
        devices_offline = total_devices - devices_online
        
        # Inventory
        inventory_available = ResellerInventory.objects.filter(
            reseller=reseller,
            status=ResellerInventory.Status.AVAILABLE,
            deleted_at__isnull=True,
        ).count()
        
        # Customers
        total_customers = reseller.customers.filter(deleted_at__isnull=True).count()
        active_customers = reseller.customers.filter(
            deleted_at__isnull=True, is_active=True
        ).count()
        
        # Revenue and profit from sales
        sales_agg = ResellerSale.objects.filter(
            reseller=reseller, deleted_at__isnull=True
        ).aggregate(
            total_revenue=Sum("total_amount"),
            pending_commissions=Sum(
                "commission_amount",
                filter=Q(commission_paid_at__isnull=True),
            ),
        )
        
        # Profit from inventory items sold
        profit_agg = ResellerInventory.objects.filter(
            reseller=reseller,
            status=ResellerInventory.Status.SOLD,
            deleted_at__isnull=True,
        ).aggregate(
            total_profit=Sum("sale_price") - Sum("purchase_price")
        )
        
        # Recent alerts (last 24 hours)
        recent_alerts = Alert.objects.filter(
            device__reseller=reseller,
            triggered_at__gte=now - timezone.timedelta(hours=24),
            deleted_at__isnull=True,
        ).count()
        
        data = {
            "total_devices_sold": total_devices,
            "devices_in_inventory": inventory_available,
            "total_customers": total_customers,
            "active_customers": active_customers,
            "total_revenue": sales_agg.get("total_revenue") or Decimal("0.00"),
            "total_profit": profit_agg.get("total_profit") or Decimal("0.00"),
            "pending_commissions": sales_agg.get("pending_commissions") or Decimal("0.00"),
            "credit_available": reseller.available_credit,
            "devices_online": devices_online,
            "devices_offline": devices_offline,
            "recent_alerts_count": recent_alerts,
            "status": reseller.status,
        }
        
        return Response(ResellerDashboardSerializer(data).data)

    def _get_status_message(self, status):
        """Return user-friendly message for reseller status."""
        messages = {
            Reseller.Status.PENDING: "Your reseller account is pending approval. You will be notified once approved.",
            Reseller.Status.SUSPENDED: "Your reseller account has been suspended. Please contact support.",
            Reseller.Status.TERMINATED: "Your reseller account has been terminated.",
        }
        return messages.get(status, "")


class ResellerInventoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing reseller inventory.
    """
    serializer_class = ResellerInventorySerializer
    permission_classes = [IsAuthenticated, IsResellerWithAnyStatus]
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        reseller = get_user_reseller(self.request.user)
        if not reseller or not reseller.is_active:
            return ResellerInventory.objects.none()
        return ResellerInventory.objects.filter(
            reseller=reseller, deleted_at__isnull=True
        ).select_related("sold_to_customer", "sold_to_customer__user")

    @extend_schema(
        tags=["Reseller Inventory"],
        summary="List inventory items",
        parameters=[
            OpenApiParameter(
                name="status",
                description="Filter by status (available, reserved, sold, returned, defective)",
                type=str,
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class ResellerCustomerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing reseller customers.
    """
    serializer_class = ResellerCustomerSerializer
    permission_classes = [IsAuthenticated, IsResellerWithAnyStatus]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        reseller = get_user_reseller(self.request.user)
        if not reseller or not reseller.is_active:
            return ResellerCustomer.objects.none()
        return ResellerCustomer.objects.filter(
            reseller=reseller, deleted_at__isnull=True
        ).select_related("user")

    @extend_schema(
        tags=["Reseller Customers"],
        summary="List customers",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=["Reseller Customers"],
        summary="Create new customer",
        description="Create a new user and customer profile",
        request=ResellerCustomerCreateSerializer,
        responses={201: ResellerCustomerSerializer},
    )
    def create(self, request, *args, **kwargs):
        reseller = get_user_reseller(request.user)
        serializer = ResellerCustomerCreateSerializer(
            data=request.data,
            context={"request": request, "reseller": reseller},
        )
        if serializer.is_valid():
            customer = serializer.save()
            return Response(
                ResellerCustomerSerializer(customer).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        tags=["Reseller Customers"],
        summary="Link existing user as customer",
        request=ResellerLinkCustomerSerializer,
        responses={201: ResellerCustomerSerializer},
    )
    @action(detail=False, methods=["post"], url_path="link")
    def link_customer(self, request):
        reseller = get_user_reseller(request.user)
        serializer = ResellerLinkCustomerSerializer(
            data=request.data,
            context={"request": request, "reseller": reseller},
        )
        if serializer.is_valid():
            customer = serializer.save()
            return Response(
                ResellerCustomerSerializer(customer).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete(acting_user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResellerDeviceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for resellers to view devices they've sold.
    """
    serializer_class = DeviceSerializer
    permission_classes = [IsAuthenticated, IsResellerWithAnyStatus]

    def get_queryset(self):
        reseller = get_user_reseller(self.request.user)
        if not reseller or not reseller.is_active:
            return Device.objects.none()
        return Device.objects.filter(
            reseller=reseller, deleted_at__isnull=True
        ).select_related("user", "subscription")

    @extend_schema(
        tags=["Reseller Devices"],
        summary="List devices sold by reseller",
        parameters=[
            OpenApiParameter(
                name="customer_id",
                description="Filter by customer ID",
                type=int,
            ),
            OpenApiParameter(
                name="online",
                description="Filter by online status (true/false)",
                type=bool,
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        
        # Filter by customer
        customer_id = request.query_params.get("customer_id")
        if customer_id:
            try:
                customer = ResellerCustomer.objects.get(pk=int(customer_id))
                queryset = queryset.filter(user=customer.user)
            except (ValueError, ResellerCustomer.DoesNotExist):
                pass
        
        # Filter by online status
        online = request.query_params.get("online")
        if online is not None:
            online_threshold = timezone.now() - timezone.timedelta(seconds=180)
            if online.lower() == "true":
                queryset = queryset.filter(last_seen__gte=online_threshold)
            else:
                queryset = queryset.exclude(last_seen__gte=online_threshold)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class ResellerAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for resellers to view alerts from devices they've sold.
    """
    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated, IsResellerWithAnyStatus]

    def get_queryset(self):
        reseller = get_user_reseller(self.request.user)
        if not reseller or not reseller.is_active:
            return Alert.objects.none()
        return Alert.objects.filter(
            device__reseller=reseller, deleted_at__isnull=True
        ).select_related("device", "device__user")

    @extend_schema(
        tags=["Reseller Alerts"],
        summary="List alerts for reseller's devices",
        parameters=[
            OpenApiParameter(
                name="status",
                description="Filter by alert status (open, acknowledged, resolved)",
                type=str,
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class DeviceAssignmentView(APIView):
    """
    Assign a device from inventory to a customer.
    """
    permission_classes = [IsAuthenticated, IsReseller]

    @extend_schema(
        tags=["Resellers"],
        summary="Assign device to customer",
        description="Assign a device from inventory to a customer, creating the Device record",
        request=DeviceAssignmentSerializer,
        responses={
            201: DeviceSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @transaction.atomic
    def post(self, request):
        reseller = get_user_reseller(request.user)
        serializer = DeviceAssignmentSerializer(
            data=request.data, context={"request": request, "reseller": reseller}
        )
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = serializer.validated_data
        
        # Get the inventory item and customer
        inventory_item = ResellerInventory.objects.select_for_update().get(
            pk=data["inventory_item_id"]
        )
        customer = ResellerCustomer.objects.get(pk=data["customer_id"])
        
        # Create the Device for the customer
        device = Device.objects.create(
            user=customer.user,
            hardware_identifier=inventory_item.hardware_identifier,
            device_name=data.get("device_name", ""),
            device_role=inventory_item.device_role,
            reseller=reseller,
            created_by=request.user,
        )
        
        # If slave device, try to link to master
        if (
            inventory_item.device_role == "slave"
            and inventory_item.master_hardware_identifier
        ):
            try:
                master = Device.objects.get(
                    hardware_identifier=inventory_item.master_hardware_identifier,
                    user=customer.user,
                )
                device.master = master
                device.save(update_fields=["master"])
            except Device.DoesNotExist:
                logger.warning(
                    "Master device %s not found for slave %s",
                    inventory_item.master_hardware_identifier,
                    inventory_item.hardware_identifier,
                )
        
        # Update inventory item
        inventory_item.status = ResellerInventory.Status.SOLD
        inventory_item.sold_to_customer = customer
        inventory_item.sale_price = data["sale_price"]
        inventory_item.sold_at = timezone.now()
        inventory_item.updated_by = request.user
        inventory_item.save()
        
        # Create sale record
        profit = data["sale_price"] - inventory_item.purchase_price
        commission = profit * (reseller.commission_rate / 100)
        
        ResellerSale.objects.create(
            reseller=reseller,
            customer=customer,
            quantity=1,
            total_amount=data["sale_price"],
            commission_rate=reseller.commission_rate,
            commission_amount=commission,
            created_by=request.user,
        )
        
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)


# ============================================================================
# Reseller Order Views (for resellers to place and view orders)
# ============================================================================

class ResellerOrderListView(APIView):
    """
    View for resellers to see their orders (purchase orders from us).
    """
    permission_classes = [IsAuthenticated, IsResellerWithAnyStatus]

    @extend_schema(
        tags=["Reseller Orders"],
        summary="List reseller's purchase orders",
        description="Returns all orders placed by this reseller",
    )
    def get(self, request):
        from products.models import Order
        from products.serializers import OrderSerializer
        
        reseller = get_user_reseller(request.user)
        if not reseller:
            return Response({"detail": "Not a reseller"}, status=status.HTTP_403_FORBIDDEN)
        
        # Get orders that have reseller purchase orders linked
        purchase_orders = ResellerPurchaseOrder.objects.filter(
            reseller=reseller, deleted_at__isnull=True
        ).select_related('order', 'order__package').order_by('-created_at')
        
        data = []
        for po in purchase_orders:
            order = po.order
            # Count fulfilled devices
            fulfilled_count = order.fulfillments.filter(deleted_at__isnull=True).count()
            # Count inventory items created
            inventory_count = ResellerInventory.objects.filter(
                reseller=reseller, 
                purchase_order=order,
                deleted_at__isnull=True
            ).count()
            
            data.append({
                "id": po.id,
                "order_id": order.id,
                "order_status": order.order_status,
                "package_name": order.package.name if order.package else None,
                "quantity": order.quantity,
                "number_of_master_devices": order.number_of_master_devices,
                "number_of_slave_devices": order.number_of_slave_devices,
                "original_amount": str(po.original_amount),
                "discount_applied": str(po.discount_applied),
                "final_amount": str(po.final_amount),
                "is_credit_purchase": po.is_credit_purchase,
                "credit_due_date": po.credit_due_date,
                "credit_paid_at": po.credit_paid_at,
                "fulfilled_count": fulfilled_count,
                "inventory_count": inventory_count,
                "ordered_at": order.ordered_at,
                "created_at": po.created_at,
            })
        
        return Response(data)


class ResellerPlaceOrderView(APIView):
    """
    View for resellers to place new bulk orders.
    Uses the existing cart/checkout system with reseller discounts applied.
    """
    permission_classes = [IsAuthenticated, IsReseller]

    @extend_schema(
        tags=["Reseller Orders"],
        summary="Place a new bulk order",
        description="Create a new order for devices with reseller discount applied",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "package_id": {"type": "integer", "description": "Package ID to order"},
                    "quantity": {"type": "integer", "description": "Total number of devices"},
                    "number_of_master_devices": {"type": "integer", "description": "Number of master devices"},
                    "number_of_slave_devices": {"type": "integer", "description": "Number of slave devices"},
                    "use_credit": {"type": "boolean", "description": "Purchase on credit (if available)"},
                    "shipping_address": {"type": "string", "description": "Shipping address"},
                    "notes": {"type": "string", "description": "Order notes"},
                },
                "required": ["package_id", "quantity", "number_of_master_devices"],
            }
        },
    )
    @transaction.atomic
    def post(self, request):
        from products.models import Order, Package
        from products.enums import OrderStatus, PaymentMethod
        
        reseller = get_user_reseller(request.user)
        if not reseller:
            return Response({"detail": "Not a reseller"}, status=status.HTTP_403_FORBIDDEN)
        
        data = request.data
        
        # Validate package
        try:
            package = Package.objects.get(pk=data.get("package_id"), deleted_at__isnull=True)
        except Package.DoesNotExist:
            return Response({"detail": "Invalid package"}, status=status.HTTP_400_BAD_REQUEST)
        
        quantity = int(data.get("quantity", 0))
        num_masters = int(data.get("number_of_master_devices", 0))
        num_slaves = int(data.get("number_of_slave_devices", 0))
        
        # Validate quantities
        if quantity < package.min_quantity or quantity > package.max_quantity:
            return Response({
                "detail": f"Quantity must be between {package.min_quantity} and {package.max_quantity}"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if num_masters + num_slaves != quantity:
            return Response({
                "detail": "Master + Slave devices must equal total quantity"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Calculate pricing
        original_amount = (package.price_per_device * quantity) + (package.mrf * num_masters)
        discount_rate = reseller.discount_rate or Decimal("0.00")
        discount_amount = (original_amount * discount_rate / 100).quantize(Decimal("0.01"))
        final_amount = original_amount - discount_amount
        
        # Check credit if using credit
        use_credit = data.get("use_credit", False)
        if use_credit:
            if not reseller.credit_limit or reseller.credit_limit <= 0:
                return Response({"detail": "No credit limit available"}, status=status.HTTP_400_BAD_REQUEST)
            
            available_credit = reseller.credit_limit - reseller.current_credit_used
            if final_amount > available_credit:
                return Response({
                    "detail": f"Insufficient credit. Available: ৳{available_credit}, Required: ৳{final_amount}"
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create the order
        order = Order.objects.create(
            user=request.user,
            package=package,
            quantity=quantity,
            number_of_master_devices=num_masters,
            number_of_slave_devices=num_slaves,
            amount=final_amount,
            currency="BDT",
            customer_name=reseller.company_name,
            customer_address=reseller.address,
            customer_phone=reseller.contact_phone,
            customer_city=reseller.city,
            customer_email=reseller.contact_email,
            payment_method=PaymentMethod.ONLINE if not use_credit else PaymentMethod.CASH_ON_DELIVERY,
            order_status=OrderStatus.PENDING if not use_credit else OrderStatus.PAID,
            shipping_address=data.get("shipping_address", reseller.address),
            created_by=request.user,
        )
        
        # Create reseller purchase order
        credit_due_date = None
        if use_credit:
            credit_due_date = (timezone.now() + timezone.timedelta(days=30)).date()
            # Update credit used
            reseller.current_credit_used += final_amount
            reseller.save(update_fields=["current_credit_used", "updated_at"])
        
        po = ResellerPurchaseOrder.objects.create(
            reseller=reseller,
            order=order,
            original_amount=original_amount,
            discount_applied=discount_amount,
            final_amount=final_amount,
            is_credit_purchase=use_credit,
            credit_due_date=credit_due_date,
            notes=data.get("notes", ""),
            created_by=request.user,
        )
        
        return Response({
            "id": po.id,
            "order_id": order.id,
            "order_status": order.order_status,
            "original_amount": str(original_amount),
            "discount_applied": str(discount_amount),
            "final_amount": str(final_amount),
            "is_credit_purchase": use_credit,
            "credit_due_date": credit_due_date,
            "message": "Order created. Proceed to payment." if not use_credit else "Order created on credit.",
        }, status=status.HTTP_201_CREATED)


# ============================================================================
# Admin Views (for super admins to manage resellers)
# ============================================================================

class AdminResellerDashboardView(APIView):
    """
    Dashboard for super admins to see reseller overview statistics.
    """
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    @extend_schema(
        tags=["Admin - Resellers"],
        summary="Reseller program dashboard",
        description="Returns overview statistics for the reseller program",
    )
    def get(self, request):
        from products.models import Order
        
        now = timezone.now()
        
        # Reseller counts by status
        reseller_stats = Reseller.objects.filter(deleted_at__isnull=True).aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(status=Reseller.Status.PENDING)),
            active=Count('id', filter=Q(status=Reseller.Status.ACTIVE)),
            suspended=Count('id', filter=Q(status=Reseller.Status.SUSPENDED)),
            terminated=Count('id', filter=Q(status=Reseller.Status.TERMINATED)),
        )
        
        # Purchase order stats
        po_stats = ResellerPurchaseOrder.objects.filter(deleted_at__isnull=True).aggregate(
            total_orders=Count('id'),
            total_value=Sum('final_amount'),
            total_discount=Sum('discount_applied'),
            credit_outstanding=Sum(
                'final_amount',
                filter=Q(is_credit_purchase=True, credit_paid_at__isnull=True)
            ),
        )
        
        # Inventory stats
        inventory_stats = ResellerInventory.objects.filter(deleted_at__isnull=True).aggregate(
            total=Count('id'),
            available=Count('id', filter=Q(status=ResellerInventory.Status.AVAILABLE)),
            sold=Count('id', filter=Q(status=ResellerInventory.Status.SOLD)),
            reserved=Count('id', filter=Q(status=ResellerInventory.Status.RESERVED)),
        )
        
        # Devices sold by resellers
        devices_sold = Device.objects.filter(
            reseller__isnull=False, 
            deleted_at__isnull=True
        ).count()
        
        # Sales stats
        sales_stats = ResellerSale.objects.filter(deleted_at__isnull=True).aggregate(
            total_sales=Count('id'),
            total_revenue=Sum('total_amount'),
            total_commission=Sum('commission_amount'),
            commission_pending=Sum(
                'commission_amount',
                filter=Q(commission_paid_at__isnull=True)
            ),
        )
        
        # Recent activity (last 30 days)
        thirty_days_ago = now - timezone.timedelta(days=30)
        recent_orders = ResellerPurchaseOrder.objects.filter(
            created_at__gte=thirty_days_ago, deleted_at__isnull=True
        ).count()
        recent_sales = ResellerSale.objects.filter(
            created_at__gte=thirty_days_ago, deleted_at__isnull=True
        ).count()
        
        # Top resellers by devices sold
        top_resellers = Reseller.objects.filter(
            status=Reseller.Status.ACTIVE, deleted_at__isnull=True
        ).annotate(
            devices_sold=Count('sold_devices', filter=Q(sold_devices__deleted_at__isnull=True)),
            total_sales=Sum('sales__total_amount', filter=Q(sales__deleted_at__isnull=True)),
        ).order_by('-devices_sold')[:5].values(
            'id', 'company_name', 'devices_sold', 'total_sales'
        )
        
        return Response({
            "resellers": reseller_stats,
            "purchase_orders": {
                "total_orders": po_stats["total_orders"] or 0,
                "total_value": str(po_stats["total_value"] or Decimal("0.00")),
                "total_discount_given": str(po_stats["total_discount"] or Decimal("0.00")),
                "credit_outstanding": str(po_stats["credit_outstanding"] or Decimal("0.00")),
            },
            "inventory": inventory_stats,
            "devices_sold_by_resellers": devices_sold,
            "sales": {
                "total_sales": sales_stats["total_sales"] or 0,
                "total_revenue": str(sales_stats["total_revenue"] or Decimal("0.00")),
                "total_commission_earned": str(sales_stats["total_commission"] or Decimal("0.00")),
                "commission_pending": str(sales_stats["commission_pending"] or Decimal("0.00")),
            },
            "recent_activity": {
                "orders_last_30_days": recent_orders,
                "sales_last_30_days": recent_sales,
            },
            "top_resellers": list(top_resellers),
        })


class AdminResellerOrdersView(APIView):
    """
    View all reseller purchase orders for super admins.
    """
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    @extend_schema(
        tags=["Admin - Resellers"],
        summary="List all reseller purchase orders",
        parameters=[
            OpenApiParameter(name="reseller_id", type=int, description="Filter by reseller ID"),
            OpenApiParameter(name="status", type=str, description="Filter by order status"),
            OpenApiParameter(name="credit_only", type=bool, description="Show only credit purchases"),
        ],
    )
    def get(self, request):
        qs = ResellerPurchaseOrder.objects.filter(
            deleted_at__isnull=True
        ).select_related('reseller', 'order', 'order__package').order_by('-created_at')
        
        # Filters
        reseller_id = request.query_params.get("reseller_id")
        if reseller_id:
            qs = qs.filter(reseller_id=int(reseller_id))
        
        order_status = request.query_params.get("status")
        if order_status:
            qs = qs.filter(order__order_status=order_status)
        
        credit_only = request.query_params.get("credit_only")
        if credit_only and credit_only.lower() == "true":
            qs = qs.filter(is_credit_purchase=True)
        
        data = []
        for po in qs[:100]:  # Limit to 100
            order = po.order
            fulfilled_count = order.fulfillments.filter(deleted_at__isnull=True).count()
            
            data.append({
                "id": po.id,
                "reseller_id": po.reseller_id,
                "reseller_name": po.reseller.company_name,
                "order_id": order.id,
                "order_status": order.order_status,
                "package_name": order.package.name if order.package else None,
                "quantity": order.quantity,
                "original_amount": str(po.original_amount),
                "discount_applied": str(po.discount_applied),
                "final_amount": str(po.final_amount),
                "is_credit_purchase": po.is_credit_purchase,
                "credit_due_date": po.credit_due_date,
                "credit_paid_at": po.credit_paid_at,
                "fulfilled_count": fulfilled_count,
                "ordered_at": order.ordered_at,
            })
        
        return Response(data)


class AdminMarkCreditPaidView(APIView):
    """
    Mark a credit purchase as paid.
    """
    permission_classes = [IsAuthenticated, IsSuperAdmin]

    @extend_schema(
        tags=["Admin - Resellers"],
        summary="Mark credit purchase as paid",
    )
    @transaction.atomic
    def post(self, request, po_id):
        try:
            po = ResellerPurchaseOrder.objects.select_related('reseller').get(
                pk=po_id, deleted_at__isnull=True
            )
        except ResellerPurchaseOrder.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        
        if not po.is_credit_purchase:
            return Response({"detail": "Not a credit purchase"}, status=status.HTTP_400_BAD_REQUEST)
        
        if po.credit_paid_at:
            return Response({"detail": "Already marked as paid"}, status=status.HTTP_400_BAD_REQUEST)
        
        po.credit_paid_at = timezone.now()
        po.updated_by = request.user
        po.save(update_fields=["credit_paid_at", "updated_by", "updated_at"])
        
        # Reduce reseller's credit used
        reseller = po.reseller
        reseller.current_credit_used = max(
            Decimal("0.00"), 
            reseller.current_credit_used - po.final_amount
        )
        reseller.save(update_fields=["current_credit_used", "updated_at"])
        
        return Response({
            "id": po.id,
            "credit_paid_at": po.credit_paid_at,
            "reseller_credit_remaining": str(reseller.credit_limit - reseller.current_credit_used),
        })


class AdminResellerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for super admins to manage resellers.
    """
    serializer_class = ResellerAdminSerializer
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    queryset = Reseller.objects.filter(deleted_at__isnull=True)

    @extend_schema(
        tags=["Admin - Resellers"],
        summary="List all resellers",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=["Admin - Resellers"],
        summary="Activate a reseller",
    )
    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        reseller = self.get_object()
        reseller.status = Reseller.Status.ACTIVE
        reseller.activated_at = timezone.now()
        reseller.updated_by = request.user
        reseller.save()
        return Response(ResellerAdminSerializer(reseller).data)

    @extend_schema(
        tags=["Admin - Resellers"],
        summary="Suspend a reseller",
    )
    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        reseller = self.get_object()
        reseller.status = Reseller.Status.SUSPENDED
        reseller.updated_by = request.user
        reseller.save()
        return Response(ResellerAdminSerializer(reseller).data)

    @extend_schema(
        tags=["Admin - Resellers"],
        summary="Terminate a reseller",
    )
    @action(detail=True, methods=["post"], url_path="terminate")
    def terminate(self, request, pk=None):
        reseller = self.get_object()
        reseller.status = Reseller.Status.TERMINATED
        reseller.updated_by = request.user
        reseller.save()
        return Response(ResellerAdminSerializer(reseller).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete(acting_user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
