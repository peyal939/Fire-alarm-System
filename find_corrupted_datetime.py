#!/usr/bin/env python
"""
Run this script on the production server to find corrupted datetime fields.

Usage:
    python find_corrupted_datetime.py
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.db import connection

def check_table(table_name, datetime_columns):
    """Check a table for string values in datetime columns."""
    print(f"\n{'='*60}")
    print(f"Checking: {table_name}")
    print('='*60)
    
    with connection.cursor() as cursor:
        # Check if table exists
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = DATABASE() AND table_name = %s
        """, [table_name])
        if cursor.fetchone()[0] == 0:
            print(f"  Table does not exist, skipping...")
            return
        
        for col in datetime_columns:
            # Check if column exists
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_schema = DATABASE() 
                AND table_name = %s AND column_name = %s
            """, [table_name, col])
            if cursor.fetchone()[0] == 0:
                continue
            
            # Get all non-null values and check their Python type
            try:
                cursor.execute(f"SELECT id, `{col}` FROM `{table_name}` WHERE `{col}` IS NOT NULL")
                rows = cursor.fetchall()
                
                corrupted = []
                for row_id, value in rows:
                    if isinstance(value, str):
                        corrupted.append((row_id, value))
                
                if corrupted:
                    print(f"\n  ❌ CORRUPTED: {col}")
                    for row_id, value in corrupted[:10]:  # Show first 10
                        print(f"     id={row_id}: '{value}' (type: {type(value).__name__})")
                    if len(corrupted) > 10:
                        print(f"     ... and {len(corrupted) - 10} more")
                    print(f"\n  FIX SQL:")
                    print(f"     UPDATE `{table_name}` SET `{col}` = STR_TO_DATE(`{col}`, '%Y-%m-%d %H:%i:%s') WHERE `{col}` IS NOT NULL;")
                else:
                    print(f"  ✓ {col}: OK ({len(rows)} records)")
                    
            except Exception as e:
                print(f"  ⚠ {col}: Error - {e}")

def main():
    print("=" * 60)
    print("DATETIME CORRUPTION DIAGNOSTIC")
    print("=" * 60)
    
    # Check MySQL timezone settings
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@global.time_zone, @@session.time_zone")
        global_tz, session_tz = cursor.fetchone()
        print(f"\nMySQL Timezone: global={global_tz}, session={session_tz}")
    
    from django.conf import settings
    print(f"Django TIME_ZONE: {settings.TIME_ZONE}")
    print(f"Django USE_TZ: {settings.USE_TZ}")
    
    # Tables used in Device admin dropdowns
    tables = {
        'accounts_user': ['created_at', 'deleted_at', 'last_login'],
        'devices_device': ['created_at', 'deleted_at', 'last_seen', 'registered_at', 'phone_number_updated_at'],
        'products_order': ['created_at', 'deleted_at', 'ordered_at', 'updated_at'],
        'products_package': ['created_at', 'deleted_at', 'updated_at'],
    }
    
    for table, columns in tables.items():
        check_table(table, columns)
    
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    print("\nIf corrupted fields were found, run the FIX SQL commands shown above.")
    print("Or run: python manage.py fix_datetime_fields --fix")

if __name__ == '__main__':
    main()
