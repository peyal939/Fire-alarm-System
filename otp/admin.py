from django.contrib import admin

from .models import PhoneOTP


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = (
        "session_id",
        "phone_number",
        "purpose",
        "user",
        "attempts",
        "resend_count",
        "expires_at",
        "verified_at",
        "locked_at",
    )
    list_filter = ("purpose", "verified_at", "locked_at")
    search_fields = ("phone_number", "session_id")
    readonly_fields = (
        "session_id",
        "created_at",
        "updated_at",
        "verified_at",
        "locked_at",
        "last_sent_at",
    )
