from django.contrib import admin
from django import forms
from django.urls import path
from django.utils.html import format_html
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Package, Order, Cart, CartItem
from .enums import OrderStatus
from .forms import OrderFulfillmentForm
from .services import fulfill_order


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "min_quantity", "max_quantity", "price_per_device", "mrf", "description")
    search_fields = ("name",)


class OrderAdminForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = '__all__'

    def clean_order_status(self):
        status = self.cleaned_data['order_status']
        if status == OrderStatus.DELIVERED:
            expected = self.instance.number_of_master_devices + self.instance.number_of_slave_devices
            if self.instance.assigned_devices < expected:
                raise forms.ValidationError("Cannot mark as Delivered until all devices are assigned (Fulfilled).")
        return status


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
    list_display = (
        "id",
        "user",
        "package",
        "reference",
        "number_of_master_devices",
        "number_of_slave_devices",
        "quantity",
        "amount",
        "currency",
        "customer_name",
        "order_status",
        "ordered_at",
        "fulfillment_actions",
    )
    list_filter = ("order_status", "package")
    search_fields = ("id", "gateway_transaction_id", "reference", "customer_name", "customer_phone")
    readonly_fields = ("gateway_response", "ordered_at", "fulfillment_actions")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:order_id>/fulfill/',
                self.admin_site.admin_view(self.fulfill_order_view),
                name='products_order_fulfill',
            ),
        ]
        return custom_urls + urls

    def fulfill_order_view(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id)
        if request.method == 'POST':
            form = OrderFulfillmentForm(request.POST, order=order)
            if form.is_valid():
                try:
                    fulfill_order(
                        order, 
                        form.cleaned_data['master_ids_list'], 
                        form.cleaned_data['slave_ids_list'],
                        actor=request.user
                    )
                    self.message_user(request, "Order fulfilled successfully. Devices created.")
                    return redirect('admin:products_order_change', order_id)
                except Exception as e:
                    self.message_user(request, str(e), level=messages.ERROR)
        else:
            form = OrderFulfillmentForm(order=order)

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'form': form,
            'order': order,
            'title': f'Fulfill Order {order.pk}',
        }
        return render(request, 'admin/products/order/fulfill.html', context)

    def fulfillment_actions(self, obj):
        if obj.assigned_devices > 0:
            return "Fulfilled"
        if obj.order_status != OrderStatus.PAID:
             return "Not Paid"
        return format_html(
            '<a class="button" href="{}">Fulfill Order</a>',
            f"{obj.pk}/fulfill/"
        )
    fulfillment_actions.short_description = "Fulfillment"
    fulfillment_actions.allow_tags = True


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ("line_total", "added_at")
    raw_id_fields = ("package",)


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "item_count",
        "cart_total",
        "expires_at",
        "is_expired",
        "created_at",
    )
    list_filter = ("expires_at",)
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at", "cart_total", "is_expired")
    inlines = [CartItemInline]

    def item_count(self, obj):
        return obj.items.count()
    item_count.short_description = "Items"

    def cart_total(self, obj):
        return f"BDT {obj.get_total():,.2f}"
    cart_total.short_description = "Total"
