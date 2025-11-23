from __future__ import annotations

from django import forms
from django.utils import timezone


class OverrideWindowForm(forms.Form):
    admin_override_until = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"}
        ),
        help_text="Leave blank to clear the override window.",
    )

    def clean_admin_override_until(self):
        value = self.cleaned_data.get("admin_override_until")
        if value is None:
            return None
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value


class ManualPaymentForm(forms.Form):
    months = forms.IntegerField(
        min_value=1,
        max_value=24,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        help_text="Number of monthly cycles covered by the manual payment.",
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "class": "form-control", "placeholder": "Notes"}
        ),
    )


class UserTopUpForm(forms.Form):
    months = forms.IntegerField(
        min_value=1,
        max_value=12,
        initial=1,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": 1, "max": 12}
        ),
    )
    subscription_id = forms.IntegerField(widget=forms.HiddenInput())