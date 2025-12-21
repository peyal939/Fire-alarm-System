"""
Django management command to fix datetime fields stored as strings in MySQL.

This fixes the error:
    AttributeError: 'str' object has no attribute 'utcoffset'

Usage:
    python manage.py fix_datetime_strings          # Dry run (shows what would be fixed)
    python manage.py fix_datetime_strings --apply  # Actually apply fixes
    python manage.py fix_datetime_strings --app devices  # Only check devices app
    python manage.py fix_datetime_strings --model Device  # Only check Device model
"""

import logging
from datetime import datetime, date, time
from django.core.management.base import BaseCommand
from django.apps import apps
from django.db import connection, models

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Find and fix datetime fields stored as strings in MySQL database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually apply fixes (default is dry-run mode)",
        )
        parser.add_argument(
            "--app",
            type=str,
            help="Only check models from this app (e.g., 'devices', 'accounts')",
        )
        parser.add_argument(
            "--model",
            type=str,
            help="Only check this specific model (e.g., 'Device', 'User')",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed progress information",
        )

    def handle(self, *args, **options):
        apply_fixes = options["apply"]
        app_filter = options.get("app")
        model_filter = options.get("model")
        verbose = options.get("verbose", False)

        if apply_fixes:
            self.stdout.write(
                self.style.WARNING("Running in APPLY mode - changes will be saved!")
            )
        else:
            self.stdout.write(
                self.style.NOTICE(
                    "Running in DRY-RUN mode - no changes will be made. Use --apply to fix."
                )
            )

        self.stdout.write("")

        total_issues = 0
        total_fixed = 0

        # Get all models
        all_models = apps.get_models()

        for model in all_models:
            # Filter by app if specified
            if app_filter and model._meta.app_label != app_filter:
                continue

            # Filter by model name if specified
            if model_filter and model.__name__ != model_filter:
                continue

            # Get datetime fields
            datetime_fields = self._get_datetime_fields(model)
            if not datetime_fields:
                continue

            if verbose:
                self.stdout.write(
                    f"Checking {model._meta.app_label}.{model.__name__}..."
                )

            issues, fixed = self._check_and_fix_model(
                model, datetime_fields, apply_fixes, verbose
            )
            total_issues += issues
            total_fixed += fixed

        self.stdout.write("")
        self.stdout.write("=" * 60)
        if apply_fixes:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done! Found {total_issues} issues, fixed {total_fixed}."
                )
            )
        else:
            if total_issues > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"Found {total_issues} datetime fields stored as strings."
                    )
                )
                self.stdout.write(
                    self.style.NOTICE("Run with --apply to fix these issues.")
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS("No datetime string issues found!")
                )

    def _get_datetime_fields(self, model):
        """Get all datetime, date, and time fields from a model."""
        datetime_fields = []
        for field in model._meta.get_fields():
            if isinstance(
                field, (models.DateTimeField, models.DateField, models.TimeField)
            ):
                # Skip reverse relations and many-to-many
                if hasattr(field, "column") and field.column:
                    datetime_fields.append(field)
        return datetime_fields

    def _check_and_fix_model(self, model, datetime_fields, apply_fixes, verbose):
        """Check and optionally fix datetime fields for a model."""
        issues = 0
        fixed = 0
        table_name = model._meta.db_table

        for field in datetime_fields:
            column_name = field.column
            field_issues, field_fixed = self._check_and_fix_column(
                model, table_name, column_name, field, apply_fixes, verbose
            )
            issues += field_issues
            fixed += field_fixed

        return issues, fixed

    def _check_and_fix_column(
        self, model, table_name, column_name, field, apply_fixes, verbose
    ):
        """Check and fix a specific column for string datetime values."""
        issues = 0
        fixed = 0

        # Use raw SQL to check for string values that look like dates
        # but are stored incorrectly
        with connection.cursor() as cursor:
            # First, let's check the actual column type in the database
            cursor.execute(
                """
                SELECT DATA_TYPE, COLUMN_TYPE 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = %s 
                AND COLUMN_NAME = %s
                """,
                [table_name, column_name],
            )
            result = cursor.fetchone()
            if not result:
                return 0, 0

            data_type, column_type = result

            # If the column is VARCHAR or TEXT, we have a schema problem
            if data_type.upper() in ("VARCHAR", "TEXT", "CHAR", "LONGTEXT", "MEDIUMTEXT"):
                self.stdout.write(
                    self.style.ERROR(
                        f"  SCHEMA ERROR: {table_name}.{column_name} is {column_type} "
                        f"but should be DATETIME/DATE/TIME!"
                    )
                )
                self.stdout.write(
                    self.style.NOTICE(
                        f"  Fix: ALTER TABLE `{table_name}` MODIFY `{column_name}` "
                        f"DATETIME NULL;"
                    )
                )
                return 1, 0

            # For proper datetime columns, check if any have invalid/corrupt data
            # by trying to read them through Django ORM
            try:
                # Get all records and check each datetime field
                pk_name = model._meta.pk.name
                
                # Read raw values directly
                cursor.execute(
                    f"SELECT `{pk_name}`, `{column_name}` FROM `{table_name}` "
                    f"WHERE `{column_name}` IS NOT NULL LIMIT 1000"
                )
                rows = cursor.fetchall()

                for pk_value, raw_value in rows:
                    if raw_value is None:
                        continue

                    # Check if value is a string when it shouldn't be
                    if isinstance(raw_value, str):
                        issues += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"  {table_name}.{column_name} (pk={pk_value}): "
                                f"string value '{raw_value}'"
                            )
                        )

                        if apply_fixes:
                            converted = self._convert_string_to_datetime(
                                raw_value, field
                            )
                            if converted is not None:
                                cursor.execute(
                                    f"UPDATE `{table_name}` SET `{column_name}` = %s "
                                    f"WHERE `{pk_name}` = %s",
                                    [converted, pk_value],
                                )
                                fixed += 1
                                self.stdout.write(
                                    self.style.SUCCESS(
                                        f"    -> Fixed: {converted}"
                                    )
                                )
                            else:
                                # Set to NULL if we can't parse it
                                if field.null:
                                    cursor.execute(
                                        f"UPDATE `{table_name}` SET `{column_name}` = NULL "
                                        f"WHERE `{pk_name}` = %s",
                                        [pk_value],
                                    )
                                    fixed += 1
                                    self.stdout.write(
                                        self.style.NOTICE(
                                            f"    -> Set to NULL (unparseable)"
                                        )
                                    )
                                else:
                                    self.stdout.write(
                                        self.style.ERROR(
                                            f"    -> Cannot fix: field is NOT NULL and value is unparseable"
                                        )
                                    )

            except Exception as e:
                if verbose:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  Error checking {table_name}.{column_name}: {e}"
                        )
                    )

        return issues, fixed

    def _convert_string_to_datetime(self, value, field):
        """Convert a string value to the appropriate datetime type."""
        if not isinstance(value, str):
            return value

        value = value.strip()
        if not value or value in ("0000-00-00 00:00:00", "0000-00-00", ""):
            return None

        if isinstance(field, models.DateTimeField):
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d",
            ):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue

        elif isinstance(field, models.DateField):
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                pass

        elif isinstance(field, models.TimeField):
            for fmt in ("%H:%M:%S", "%H:%M:%S.%f", "%H:%M"):
                try:
                    return datetime.strptime(value, fmt).time()
                except ValueError:
                    continue

        return None
