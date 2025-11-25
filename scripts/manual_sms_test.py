import sys
import os
import django
from datetime import timedelta
from django.utils import timezone

# Setup Django environment
# Assumes script is run from project root
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from accounts.models import User
from devices.models import Device
from subscriptions.models import DeviceSubscription
from subscriptions.enums import DeviceSubscriptionStatus
from subscriptions import services


def run_test(phone_number):
    print(f"--- SMS REMINDER TEST ---")
    print(f"Target Phone: {phone_number}")

    # 1. Create Temp User
    # Use a unique email to avoid collisions
    timestamp = int(timezone.now().timestamp())
    email = f"sms_test_{timestamp}@example.com"

    print(f"Creating temporary user: {email}")
    user = User.objects.create_user(
        email=email, password="password123", phone_number=phone_number
    )

    try:
        # 2. Create Temp Device
        device_id = f"SMS-TEST-{timestamp}"
        print(f"Creating temporary device: {device_id}")
        device = Device.objects.create(
            user=user, hardware_identifier=device_id, device_name="SMS Test Device"
        )

        # 3. Create Subscription due in 5 days
        # The service looks for next_due_at matching (now + days_before)
        days_before = 5
        target_date = timezone.now() + timedelta(days=days_before)

        # Add a few hours to ensure it falls safely within the day window
        target_date = target_date.replace(hour=12, minute=0, second=0)

        print(f"Creating subscription due on: {target_date}")
        subscription = DeviceSubscription.objects.create(
            device=device,
            status=DeviceSubscriptionStatus.ACTIVE,
            billing_anchor=timezone.now(),
            last_paid_through=timezone.now(),
            next_due_at=target_date,
            monthly_amount=500,
        )

        # 4. Run the service
        print("Invoking reminder service...")
        # We pass limit=1 to just process this one (or others if pending, but we care about the return)
        count = services.send_due_soon_sms_reminders(days_before=days_before)

        if count > 0:
            print(f"\n[SUCCESS] Service reported sending {count} SMS reminder(s).")
            print("Check your phone now!")
        else:
            print("\n[FAILURE] Service reported sending 0 SMS.")
            print("Possible reasons:")
            print("1. SMS Gateway is disabled in .env")
            print("2. Date calculation mismatch")
            print("3. Phone number format invalid")

    except Exception as e:
        print(f"\n[ERROR] An exception occurred: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Cleanup
        print("\nCleaning up test data...")
        try:
            if "subscription" in locals():
                subscription.delete()
            if "device" in locals():
                device.delete()
            if "user" in locals():
                user.delete()
            print("Cleanup complete.")
        except Exception as e:
            print(f"Error during cleanup: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/manual_sms_test.py <phone_number>")
        print("Example: python scripts/manual_sms_test.py 01700000000")
    else:
        run_test(sys.argv[1])
