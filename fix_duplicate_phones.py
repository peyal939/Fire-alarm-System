"""
Script to fix duplicate phone numbers before applying unique constraint.
Run this on your live server before running migrations.

Usage:
    python fix_duplicate_phones.py

This script will:
1. Normalize all phone numbers to local format (01XXXXXXXXX)
2. Find all duplicate phone numbers (including variants like +880...)
3. Keep the phone number for the OLDEST user (first created)
4. Clear the phone number (set to NULL) for all other users with that phone
5. Convert empty strings to NULL
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db.models import Count
from accounts.models import User
from accounts.phone_utils import normalize_phone


def fix_duplicates():
    print("=" * 60)
    print("Fixing duplicate phone numbers")
    print("=" * 60)

    # Step 1: Find all variant duplicates (same number in different formats)
    # e.g., 01725969397 and +8801725969397 are the same
    print("\n[Step 1] Finding variant duplicates (same number, different formats)...")

    from accounts.phone_utils import phone_variants

    # Build a map of normalized_phone -> list of users
    phone_to_users = {}
    for user in (
        User.objects.exclude(phone_number__isnull=True)
        .exclude(phone_number="")
        .order_by("created_at")
    ):
        normalized = normalize_phone(user.phone_number)
        if normalized:
            key = normalized.local  # Use local format as canonical key
            if key not in phone_to_users:
                phone_to_users[key] = []
            phone_to_users[key].append(user)

    # Find and fix variant duplicates
    variant_fixed = 0
    for normalized_phone, users in phone_to_users.items():
        if len(users) > 1:
            print(f"\n  Variant duplicates for {normalized_phone}:")
            for i, user in enumerate(users):
                status = "KEEP" if i == 0 else "CLEAR"
                print(
                    f"    [{status}] {user.email} - phone: {user.phone_number} (ID: {user.id}, created: {user.created_at})"
                )

                # Keep the first one (oldest), clear the rest
                if i > 0:
                    user.phone_number = None
                    user.save(update_fields=["phone_number"])
                    variant_fixed += 1

    if variant_fixed:
        print(f"\n✓ Cleared {variant_fixed} variant duplicate(s)")
    else:
        print("✓ No variant duplicates found")

    # Step 2: Normalize all remaining phone numbers
    print("\n[Step 2] Normalizing phone numbers...")
    normalized_count = 0
    for user in User.objects.exclude(phone_number__isnull=True).exclude(
        phone_number=""
    ):
        normalized = normalize_phone(user.phone_number)
        if normalized and normalized.local != user.phone_number:
            old_phone = user.phone_number
            user.phone_number = normalized.local
            user.save(update_fields=["phone_number"])
            normalized_count += 1
            print(
                f"  Normalized: {old_phone} -> {normalized.local} (User: {user.email})"
            )

    if normalized_count:
        print(f"✓ Normalized {normalized_count} phone number(s)")
    else:
        print("✓ All phone numbers already in normalized format")

    # Step 3: Find and fix exact duplicates (same format)
    print("\n[Step 3] Finding exact duplicates...")
    dupes = (
        User.objects.values("phone_number")
        .annotate(cnt=Count("id"))
        .filter(cnt__gt=1, phone_number__isnull=False)
        .exclude(phone_number="")
    )

    if not dupes:
        print("✓ No duplicate phone numbers found!")
    else:
        print(f"Found {len(dupes)} duplicate phone number(s):\n")

        for d in dupes:
            phone = d["phone_number"]
            count = d["cnt"]
            print(f"  {phone}: {count} users")

            # Show which users have this phone number (ordered by creation date)
            users = User.objects.filter(phone_number=phone).order_by("created_at")
            for i, user in enumerate(users):
                status = "KEEP" if i == 0 else "CLEAR"
                print(
                    f"    [{status}] {user.email} (ID: {user.id}, created: {user.created_at})"
                )

                # Keep the first one (oldest), clear the rest
                if i > 0:
                    user.phone_number = None
                    user.save(update_fields=["phone_number"])
            print()

    # Step 4: Convert empty strings to NULL
    print("[Step 4] Converting empty phone numbers to NULL...")
    empty_count = User.objects.filter(phone_number="").update(phone_number=None)
    if empty_count:
        print(f"✓ Converted {empty_count} empty phone number(s) to NULL")
    else:
        print("✓ No empty phone numbers to convert")

    print("\n" + "=" * 60)
    print("Done! You can now safely run: python manage.py migrate accounts")
    print("=" * 60)


if __name__ == "__main__":
    fix_duplicates()
