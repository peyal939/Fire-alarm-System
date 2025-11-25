import os
import sys
import django
from pathlib import Path

# Setup Django environment
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from devices.models import Device
from django.db.models import F
from django.contrib.auth import get_user_model

def check_ordering():
    User = get_user_model()
    users = User.objects.all()
    for user in users:
        print(f"\nChecking devices for user: {user.email}")
        
        # Replicate the view's query
        queryset = Device.objects.filter(user=user, deleted_at__isnull=True)
        queryset = queryset.order_by(
            F("last_seen").desc(nulls_last=True),
            "-registered_at",
        )
        
        if not queryset.exists():
            print("  No devices found.")
            continue

        print(f"  {'Device':<20} | {'Status':<10} | {'Last Seen':<30}")
        print("  " + "-" * 65)

        for device in queryset:
            status = "Online" if device.is_online else "Offline"
            last_seen = str(device.last_seen) if device.last_seen else "Never"
            print(f"  {device.hardware_identifier:<20} | {status:<10} | {last_seen:<30}")

if __name__ == "__main__":
    check_ordering()
