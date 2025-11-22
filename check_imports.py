from django.utils.module_loading import import_string
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

paths = [
    "shurjopay.models.PaymentTransactionStatus",
    "devices.models.AlertStatus",
]

for p in paths:
    try:
        cls = import_string(p)
        print(f"SUCCESS: {p} -> {cls}")
        print(f"  Module: {cls.__module__}")
        print(f"  Qualname: {cls.__qualname__}")
    except Exception as e:
        print(f"FAILURE: {p} -> {e}")
