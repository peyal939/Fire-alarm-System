"""Serializers for the Reseller API."""
from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import (
    Reseller,
    ResellerInventory,
    ResellerCustomer,
    ResellerPurchaseOrder,
    ResellerSale,
)

User = get_user_model()


class ResellerSerializer(serializers.ModelSerializer):
    """Serializer for viewing/editing reseller details."""
    device_count = serializers.SerializerMethodField()
    customer_count = serializers.SerializerMethodField()
    inventory_count = serializers.SerializerMethodField()
    admin_email = serializers.EmailField(source="admin_user.email", read_only=True)
    
    class Meta:
        model = Reseller
        fields = [
            "id",
            "admin_user",
            "admin_email",
            "company_name",
            "brand_name",
            "display_name",
            "company_registration_number",
            "tax_id",
            "contact_email",
            "contact_phone",
            "address",
            "city",
            "country",
            "status",
            "commission_rate",
            "discount_rate",
            "credit_limit",
            "current_credit_used",
            "available_credit",
            "logo_url",
            "primary_color",
            "custom_domain",
            "max_devices",
            "max_customers",
            "agreement_signed_at",
            "activated_at",
            "created_at",
            "device_count",
            "customer_count",
            "inventory_count",
        ]
        read_only_fields = [
            "id",
            "admin_user",
            "admin_email",
            "status",
            "commission_rate",
            "discount_rate",
            "credit_limit",
            "current_credit_used",
            "available_credit",
            "max_devices",
            "max_customers",
            "agreement_signed_at",
            "activated_at",
            "created_at",
            "device_count",
            "customer_count",
            "inventory_count",
        ]

    def get_device_count(self, obj):
        return obj.get_device_count()

    def get_customer_count(self, obj):
        return obj.get_customer_count()

    def get_inventory_count(self, obj):
        return obj.get_inventory_count()


class ResellerAdminSerializer(ResellerSerializer):
    """Serializer for super admins to manage resellers (all fields editable)."""
    
    class Meta(ResellerSerializer.Meta):
        read_only_fields = [
            "id",
            "admin_email",
            "available_credit",
            "created_at",
            "device_count",
            "customer_count",
            "inventory_count",
        ]


class ResellerRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for company_admin to register as a reseller."""
    
    class Meta:
        model = Reseller
        fields = [
            "company_name",
            "brand_name",
            "company_registration_number",
            "tax_id",
            "contact_email",
            "contact_phone",
            "address",
            "city",
            "country",
            "logo_url",
            "primary_color",
        ]

    def validate(self, attrs):
        user = self.context["request"].user
        # Check if user is company_admin
        if getattr(user, "role", "") != "company_admin":
            raise serializers.ValidationError(
                "Only company admins can register as resellers"
            )
        # Check if user already has a reseller account
        if hasattr(user, "reseller_account"):
            raise serializers.ValidationError(
                "You already have a reseller account"
            )
        return attrs

    def create(self, validated_data):
        user = self.context["request"].user
        validated_data["admin_user"] = user
        validated_data["created_by"] = user
        return super().create(validated_data)


class ResellerInventorySerializer(serializers.ModelSerializer):
    """Serializer for inventory items."""
    reseller_name = serializers.CharField(
        source="reseller.company_name", read_only=True
    )
    customer_name = serializers.SerializerMethodField()
    profit = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = ResellerInventory
        fields = [
            "id",
            "reseller",
            "reseller_name",
            "hardware_identifier",
            "device_role",
            "master_hardware_identifier",
            "purchase_order",
            "purchase_price",
            "status",
            "sold_to_customer",
            "customer_name",
            "sale_price",
            "sold_at",
            "profit",
            "notes",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "reseller",
            "reseller_name",
            "hardware_identifier",
            "device_role",
            "master_hardware_identifier",
            "purchase_order",
            "purchase_price",
            "profit",
            "created_at",
        ]

    def get_customer_name(self, obj):
        if obj.sold_to_customer:
            return (
                obj.sold_to_customer.contact_name
                or obj.sold_to_customer.user.full_name
                or obj.sold_to_customer.user.email
            )
        return None


class ResellerCustomerSerializer(serializers.ModelSerializer):
    """Serializer for reseller customers."""
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_phone = serializers.CharField(source="user.phone_number", read_only=True)
    device_count = serializers.SerializerMethodField()

    class Meta:
        model = ResellerCustomer
        fields = [
            "id",
            "reseller",
            "user",
            "user_email",
            "user_phone",
            "customer_reference",
            "company_name",
            "contact_name",
            "contact_phone",
            "contact_email",
            "address",
            "is_active",
            "notes",
            "device_count",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "reseller",
            "user_email",
            "user_phone",
            "device_count",
            "created_at",
        ]

    def get_device_count(self, obj):
        return obj.get_device_count()


class ResellerCustomerCreateSerializer(serializers.Serializer):
    """Serializer for creating a new customer for a reseller."""
    email = serializers.EmailField()
    phone_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    # Customer profile fields
    customer_reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    company_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    contact_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        # Check if user with this email already exists
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "A user with this email already exists. Use link_existing_customer instead."
            )
        return value

    def create(self, validated_data):
        reseller = self.context["reseller"]
        request_user = self.context["request"].user

        # Create the user account
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data.get("password"),
            phone_number=validated_data.get("phone_number") or None,
            full_name=validated_data.get("full_name", ""),
        )
        # Set reseller association on user
        user.reseller = reseller
        user.created_by = request_user
        user.save(update_fields=["reseller", "created_by"])

        # Create the customer profile
        customer = ResellerCustomer.objects.create(
            reseller=reseller,
            user=user,
            customer_reference=validated_data.get("customer_reference", ""),
            company_name=validated_data.get("company_name", ""),
            contact_name=validated_data.get("contact_name", ""),
            contact_phone=validated_data.get("contact_phone", ""),
            contact_email=validated_data.get("contact_email", ""),
            address=validated_data.get("address", ""),
            notes=validated_data.get("notes", ""),
            created_by=request_user,
        )
        return customer


class ResellerLinkCustomerSerializer(serializers.Serializer):
    """Serializer for linking an existing user as a reseller customer."""
    user_id = serializers.IntegerField(required=False)
    email = serializers.EmailField(required=False)
    
    customer_reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    company_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    contact_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("user_id") and not attrs.get("email"):
            raise serializers.ValidationError(
                "Either user_id or email must be provided"
            )
        
        # Find the user
        user = None
        if attrs.get("user_id"):
            try:
                user = User.objects.get(pk=attrs["user_id"])
            except User.DoesNotExist:
                raise serializers.ValidationError({"user_id": "User not found"})
        elif attrs.get("email"):
            try:
                user = User.objects.get(email=attrs["email"])
            except User.DoesNotExist:
                raise serializers.ValidationError({"email": "User not found"})
        
        attrs["user"] = user
        
        # Check if already a customer of this reseller
        reseller = self.context["reseller"]
        if ResellerCustomer.objects.filter(reseller=reseller, user=user).exists():
            raise serializers.ValidationError(
                "This user is already your customer"
            )
        
        return attrs

    def create(self, validated_data):
        reseller = self.context["reseller"]
        request_user = self.context["request"].user
        user = validated_data.pop("user")
        validated_data.pop("user_id", None)
        validated_data.pop("email", None)

        # Update user's reseller association if not set
        if not user.reseller:
            user.reseller = reseller
            user.save(update_fields=["reseller"])

        customer = ResellerCustomer.objects.create(
            reseller=reseller,
            user=user,
            customer_reference=validated_data.get("customer_reference", ""),
            company_name=validated_data.get("company_name", ""),
            contact_name=validated_data.get("contact_name", ""),
            contact_phone=validated_data.get("contact_phone", ""),
            contact_email=validated_data.get("contact_email", ""),
            address=validated_data.get("address", ""),
            notes=validated_data.get("notes", ""),
            created_by=request_user,
        )
        return customer


class DeviceAssignmentSerializer(serializers.Serializer):
    """Serializer for assigning a device from inventory to a customer."""
    inventory_item_id = serializers.IntegerField()
    customer_id = serializers.IntegerField()
    sale_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    device_name = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_inventory_item_id(self, value):
        reseller = self.context["reseller"]
        try:
            item = ResellerInventory.objects.get(
                pk=value,
                reseller=reseller,
                status=ResellerInventory.Status.AVAILABLE,
                deleted_at__isnull=True,
            )
        except ResellerInventory.DoesNotExist:
            raise serializers.ValidationError(
                "Inventory item not found or not available"
            )
        return value

    def validate_customer_id(self, value):
        reseller = self.context["reseller"]
        try:
            ResellerCustomer.objects.get(
                pk=value,
                reseller=reseller,
                is_active=True,
                deleted_at__isnull=True,
            )
        except ResellerCustomer.DoesNotExist:
            raise serializers.ValidationError(
                "Customer not found or not active"
            )
        return value


class ResellerDashboardSerializer(serializers.Serializer):
    """Serializer for the reseller dashboard summary."""
    total_devices_sold = serializers.IntegerField(default=0)
    devices_in_inventory = serializers.IntegerField(default=0)
    total_customers = serializers.IntegerField(default=0)
    active_customers = serializers.IntegerField(default=0)
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_profit = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    pending_commissions = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_available = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    devices_online = serializers.IntegerField(default=0)
    devices_offline = serializers.IntegerField(default=0)
    recent_alerts_count = serializers.IntegerField(default=0)
    status = serializers.CharField(required=False, allow_null=True)
    status_message = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class ResellerPurchaseOrderSerializer(serializers.ModelSerializer):
    """Serializer for reseller purchase orders."""
    order_status = serializers.CharField(source="order.order_status", read_only=True)
    quantity = serializers.IntegerField(source="order.quantity", read_only=True)

    class Meta:
        model = ResellerPurchaseOrder
        fields = [
            "id",
            "reseller",
            "order",
            "order_status",
            "quantity",
            "original_amount",
            "discount_applied",
            "final_amount",
            "is_credit_purchase",
            "credit_due_date",
            "credit_paid_at",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class ResellerSaleSerializer(serializers.ModelSerializer):
    """Serializer for reseller sales."""
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = ResellerSale
        fields = [
            "id",
            "reseller",
            "customer",
            "customer_name",
            "quantity",
            "total_amount",
            "commission_rate",
            "commission_amount",
            "commission_paid_at",
            "invoice_number",
            "notes",
            "created_at",
        ]
        read_only_fields = fields

    def get_customer_name(self, obj):
        if obj.customer:
            return (
                obj.customer.contact_name
                or obj.customer.user.full_name
                or obj.customer.user.email
            )
        return None
