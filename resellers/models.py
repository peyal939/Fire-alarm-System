"""
Reseller Management Models

This module implements a reseller/distributor system where companies can:
1. Purchase devices in bulk from the platform
2. Resell devices under their own brand
3. Manage their own customers and devices
4. Have admin-like functionality scoped to their inventory

Key Models:
- Reseller: The company/entity that buys and resells devices
- ResellerInventory: Tracks devices in reseller's stock (before sold to end users)
- ResellerCustomer: End customers who bought from a reseller
"""
from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditSoftDeleteModel(models.Model):
    """Base model with audit fields and soft delete support."""
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_updated_by",
    )
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_deleted_by",
    )

    class Meta:
        abstract = True

    def soft_delete(self, *, acting_user=None, timestamp=None):
        """Mark the record as deleted without actual deletion."""
        ts = timestamp or timezone.now()
        self.deleted_at = ts
        self.deleted_by = acting_user
        self.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
        return ts


class Reseller(AuditSoftDeleteModel):
    """
    Represents a reseller/distributor company that can:
    - Purchase devices in bulk
    - Resell under their own branding
    - Manage their customer base
    - Have scoped admin access
    
    The admin_user is the company_admin user who manages this reseller account.
    """
    class Status(models.TextChoices):
        PENDING = "pending", "Pending Approval"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        TERMINATED = "terminated", "Terminated"

    # The user with company_admin role who owns/manages this reseller account
    admin_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reseller_account",
        help_text="The company_admin user who manages this reseller",
    )
    
    # Company/Branding Information
    company_name = models.CharField(max_length=255)
    brand_name = models.CharField(
        max_length=255, 
        blank=True,
        help_text="Brand name shown to reseller's customers (if different from company name)"
    )
    company_registration_number = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=100, blank=True)
    
    # Contact Information
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=32)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default="Bangladesh")
    
    # Business Settings
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Commission percentage reseller earns on sales (0-100)"
    )
    discount_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Discount percentage on bulk purchases (0-100)"
    )
    credit_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Maximum credit allowed for this reseller"
    )
    current_credit_used = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Current credit balance used"
    )
    
    # Branding/White-label Options
    logo_url = models.URLField(blank=True, help_text="URL to reseller's logo")
    primary_color = models.CharField(
        max_length=7, 
        blank=True,
        help_text="Primary brand color in hex (e.g., #FF5733)"
    )
    custom_domain = models.CharField(
        max_length=255, 
        blank=True,
        help_text="Custom domain for white-label access"
    )
    
    # Limits and Quotas
    max_devices = models.PositiveIntegerField(
        default=0,
        help_text="Maximum devices this reseller can have in total (0 = unlimited)"
    )
    max_customers = models.PositiveIntegerField(
        default=0,
        help_text="Maximum customers this reseller can have (0 = unlimited)"
    )
    
    # Activation and Agreement
    agreement_signed_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this reseller"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["admin_user"]),
            models.Index(fields=["company_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.company_name} ({self.admin_user.email})"

    @property
    def display_name(self) -> str:
        """Return brand_name if set, otherwise company_name."""
        return self.brand_name or self.company_name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE and self.deleted_at is None

    @property
    def available_credit(self) -> Decimal:
        return self.credit_limit - self.current_credit_used

    def get_device_count(self) -> int:
        """Count all devices associated with this reseller."""
        from devices.models import Device
        return Device.objects.filter(
            reseller=self,
            deleted_at__isnull=True
        ).count()

    def get_customer_count(self) -> int:
        """Count all active customers of this reseller."""
        return self.customers.filter(deleted_at__isnull=True).count()

    def get_inventory_count(self) -> int:
        """Count devices currently in inventory (not yet sold)."""
        return self.inventory.filter(
            status=ResellerInventory.Status.AVAILABLE,
            deleted_at__isnull=True
        ).count()


class ResellerInventory(AuditSoftDeleteModel):
    """
    Tracks devices in reseller's inventory before they're sold to end customers.
    
    Lifecycle:
    1. AVAILABLE: Device purchased by reseller, ready to sell
    2. RESERVED: Device reserved for a customer order
    3. SOLD: Device sold and transferred to customer
    4. RETURNED: Device returned from customer
    5. DEFECTIVE: Device marked as defective
    """
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        SOLD = "sold", "Sold"
        RETURNED = "returned", "Returned"
        DEFECTIVE = "defective", "Defective"

    reseller = models.ForeignKey(
        Reseller,
        on_delete=models.PROTECT,
        related_name="inventory",
    )
    hardware_identifier = models.CharField(max_length=64, db_index=True)
    device_role = models.CharField(
        max_length=10,
        choices=[("master", "Master"), ("slave", "Slave")],
        default="master",
    )
    master_hardware_identifier = models.CharField(
        max_length=64, 
        null=True, 
        blank=True,
        help_text="For slave devices, the hardware ID of their master"
    )
    
    # Purchase information (from platform)
    purchase_order = models.ForeignKey(
        "products.Order",
        on_delete=models.PROTECT,
        related_name="reseller_inventory_items",
        help_text="The order when reseller purchased this device"
    )
    purchase_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price reseller paid for this device"
    )
    
    # Sale information (to end customer)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True,
    )
    sold_to_customer = models.ForeignKey(
        "ResellerCustomer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchased_inventory_items",
    )
    sale_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price charged to end customer"
    )
    sold_at = models.DateTimeField(null=True, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["reseller", "status"]),
            models.Index(fields=["hardware_identifier"]),
            models.Index(fields=["sold_to_customer"]),
        ]
        verbose_name_plural = "Reseller Inventories"
        # A device can only be in one reseller's inventory at a time
        constraints = [
            models.UniqueConstraint(
                fields=["hardware_identifier", "reseller"],
                condition=models.Q(status__in=["available", "reserved"]),
                name="unique_active_inventory_per_reseller"
            )
        ]

    def __str__(self) -> str:
        return f"{self.hardware_identifier} ({self.reseller.company_name})"

    @property
    def profit(self) -> Decimal | None:
        """Calculate profit on this device if sold."""
        if self.sale_price and self.purchase_price:
            return self.sale_price - self.purchase_price
        return None


class ResellerCustomer(AuditSoftDeleteModel):
    """
    End customers who purchase from a reseller.
    
    This allows resellers to:
    - Track their own customer base
    - The user account belongs to the platform but is linked to the reseller
    - Reseller can see and manage devices of their customers
    """
    reseller = models.ForeignKey(
        Reseller,
        on_delete=models.PROTECT,
        related_name="customers",
    )
    # The actual user account on the platform
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reseller_customer_profiles",
    )
    
    # Customer information (may differ from user profile)
    customer_reference = models.CharField(
        max_length=64,
        blank=True,
        help_text="Reseller's internal customer reference/ID"
    )
    company_name = models.CharField(max_length=255, blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    contact_email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["reseller", "user"]),
            models.Index(fields=["customer_reference"]),
        ]
        # A user can only be a customer of the same reseller once
        constraints = [
            models.UniqueConstraint(
                fields=["reseller", "user"],
                name="unique_customer_per_reseller"
            )
        ]

    def __str__(self) -> str:
        name = self.contact_name or self.user.full_name or self.user.email
        return f"{name} ({self.reseller.company_name})"

    def get_device_count(self) -> int:
        """Count devices owned by this customer."""
        from devices.models import Device
        return Device.objects.filter(
            user=self.user,
            reseller=self.reseller,
            deleted_at__isnull=True
        ).count()


class ResellerPurchaseOrder(AuditSoftDeleteModel):
    """
    Tracks bulk purchase orders from resellers.
    Links to the main Order model but adds reseller-specific details.
    """
    reseller = models.ForeignKey(
        Reseller,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
    )
    order = models.OneToOneField(
        "products.Order",
        on_delete=models.PROTECT,
        related_name="reseller_purchase",
    )
    
    # Pricing with reseller discount
    original_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount before reseller discount"
    )
    discount_applied = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    final_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount after discount"
    )
    
    # Payment tracking
    is_credit_purchase = models.BooleanField(
        default=False,
        help_text="Whether this was purchased on credit"
    )
    credit_due_date = models.DateField(null=True, blank=True)
    credit_paid_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["reseller"]),
        ]

    def __str__(self) -> str:
        return f"PO-{self.pk} ({self.reseller.company_name})"


class ResellerSale(AuditSoftDeleteModel):
    """
    Tracks sales made by resellers to their customers.
    Useful for commission calculation and reporting.
    """
    reseller = models.ForeignKey(
        Reseller,
        on_delete=models.PROTECT,
        related_name="sales",
    )
    customer = models.ForeignKey(
        ResellerCustomer,
        on_delete=models.SET_NULL,
        null=True,
        related_name="purchases",
    )
    
    # What was sold
    quantity = models.PositiveIntegerField(default=1)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Commission
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Commission rate at time of sale"
    )
    commission_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Calculated commission for this sale"
    )
    commission_paid_at = models.DateTimeField(null=True, blank=True)
    
    # Reference
    invoice_number = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["reseller"]),
            models.Index(fields=["customer"]),
        ]

    def __str__(self) -> str:
        return f"Sale-{self.pk} ({self.reseller.company_name})"
