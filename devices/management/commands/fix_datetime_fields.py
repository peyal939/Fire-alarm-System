"""
Management command to find and fix corrupted datetime fields stored as strings.

This addresses the error: 'str' object has no attribute 'utcoffset'
which occurs when MySQL has string values in datetime columns.
"""
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils.dateparse import parse_datetime
from datetime import datetime


class Command(BaseCommand):
    help = "Find and fix datetime fields stored as strings in the database"

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Actually fix the corrupted fields (without this flag, only reports issues)',
        )
        parser.add_argument(
            '--table',
            type=str,
            help='Specific table to check (e.g., accounts_user, devices_device)',
        )

    def handle(self, *args, **options):
        fix_mode = options.get('fix', False)
        specific_table = options.get('table')
        
        # Tables and their datetime columns to check
        tables_to_check = {
            'accounts_user': ['created_at', 'deleted_at', 'last_login'],
            'devices_device': ['created_at', 'deleted_at', 'last_seen', 'registered_at', 'phone_number_updated_at'],
            'devices_alert': ['created_at', 'deleted_at', 'triggered_at', 'resolved_at'],
            'devices_telemetry': ['created_at', 'timestamp'],
            'products_order': ['created_at', 'deleted_at', 'ordered_at', 'updated_at'],
            'products_package': ['created_at', 'deleted_at', 'updated_at'],
        }
        
        if specific_table:
            if specific_table not in tables_to_check:
                self.stderr.write(f"Unknown table: {specific_table}")
                self.stderr.write(f"Available tables: {', '.join(tables_to_check.keys())}")
                return
            tables_to_check = {specific_table: tables_to_check[specific_table]}
        
        total_issues = 0
        total_fixed = 0
        
        with connection.cursor() as cursor:
            for table_name, columns in tables_to_check.items():
                self.stdout.write(f"\n--- Checking table: {table_name} ---")
                
                # Check if table exists
                cursor.execute(f"""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = DATABASE() AND table_name = %s
                """, [table_name])
                if cursor.fetchone()[0] == 0:
                    self.stdout.write(f"  Table {table_name} does not exist, skipping...")
                    continue
                
                for column in columns:
                    # Check if column exists
                    cursor.execute(f"""
                        SELECT COUNT(*) 
                        FROM information_schema.columns 
                        WHERE table_schema = DATABASE() 
                        AND table_name = %s 
                        AND column_name = %s
                    """, [table_name, column])
                    if cursor.fetchone()[0] == 0:
                        continue
                    
                    # Get column data type
                    cursor.execute(f"""
                        SELECT DATA_TYPE 
                        FROM information_schema.columns 
                        WHERE table_schema = DATABASE() 
                        AND table_name = %s 
                        AND column_name = %s
                    """, [table_name, column])
                    data_type = cursor.fetchone()[0]
                    
                    if data_type not in ('datetime', 'timestamp'):
                        self.stdout.write(f"  Column {column} is {data_type}, not datetime - skipping")
                        continue
                    
                    # Find rows where datetime looks like a string (shouldn't happen but check anyway)
                    # More importantly, find NULL values that should be populated or invalid values
                    try:
                        cursor.execute(f"""
                            SELECT id, `{column}` 
                            FROM `{table_name}` 
                            WHERE `{column}` IS NOT NULL 
                            LIMIT 10
                        """)
                        rows = cursor.fetchall()
                        
                        issues_in_column = 0
                        for row_id, value in rows:
                            if isinstance(value, str):
                                total_issues += 1
                                issues_in_column += 1
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"  ISSUE: {table_name}.{column} id={row_id} has string value: '{value}'"
                                    )
                                )
                                
                                if fix_mode:
                                    try:
                                        # Try to parse the string as datetime
                                        parsed = parse_datetime(value)
                                        if parsed is None:
                                            # Try common formats
                                            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f']:
                                                try:
                                                    parsed = datetime.strptime(value, fmt)
                                                    break
                                                except ValueError:
                                                    continue
                                        
                                        if parsed:
                                            cursor.execute(
                                                f"UPDATE `{table_name}` SET `{column}` = %s WHERE id = %s",
                                                [parsed, row_id]
                                            )
                                            total_fixed += 1
                                            self.stdout.write(
                                                self.style.SUCCESS(
                                                    f"    FIXED: Converted '{value}' to {parsed}"
                                                )
                                            )
                                        else:
                                            self.stdout.write(
                                                self.style.ERROR(
                                                    f"    FAILED: Could not parse '{value}'"
                                                )
                                            )
                                    except Exception as e:
                                        self.stdout.write(
                                            self.style.ERROR(f"    FAILED: {e}")
                                        )
                        
                        if issues_in_column == 0:
                            self.stdout.write(f"  Column {column}: OK (checked {len(rows)} rows)")
                            
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"  Error checking {column}: {e}")
                        )
        
        self.stdout.write("\n" + "=" * 50)
        if total_issues > 0:
            self.stdout.write(
                self.style.WARNING(f"Total issues found: {total_issues}")
            )
            if fix_mode:
                self.stdout.write(
                    self.style.SUCCESS(f"Total fixed: {total_fixed}")
                )
            else:
                self.stdout.write(
                    "Run with --fix flag to attempt automatic fixes"
                )
        else:
            self.stdout.write(
                self.style.SUCCESS("No string-typed datetime issues found!")
            )
        
        # Additional check: look for any raw SQL evidence of the issue
        self.stdout.write("\n--- Additional diagnostic ---")
        self.stdout.write("If the issue persists, run this SQL directly on MySQL:")
        self.stdout.write("""
-- Check for any datetime fields that might be stored as strings
-- This can happen if the column type was changed after data was inserted

-- For accounts_user
SELECT id, created_at, deleted_at, last_login 
FROM accounts_user 
WHERE created_at IS NOT NULL 
LIMIT 5;

-- For devices_device  
SELECT id, created_at, deleted_at, last_seen, registered_at
FROM devices_device 
WHERE id = 25;

-- Check MySQL timezone settings
SELECT @@global.time_zone, @@session.time_zone;
        """)
