"""
Patch Django's MySQL backend to handle datetime values that are incorrectly
stored as strings in the database.

This fixes: AttributeError: 'str' object has no attribute 'utcoffset'

Import this module early in your Django project (e.g., in settings.py or __init__.py)
"""

from datetime import datetime, date, time
from django.db.backends.mysql import operations as mysql_ops


# Store original converter
_original_convert_datetimefield_value = mysql_ops.DatabaseOperations.convert_datetimefield_value


def _patched_convert_datetimefield_value(self, value, expression, connection):
    """
    Convert datetime field value, handling string values gracefully.
    
    This patches Django's MySQL backend to handle cases where datetime fields
    contain string values instead of proper datetime objects.
    """
    if value is None:
        return value
    
    # If value is already a datetime, use original converter
    if isinstance(value, datetime):
        return _original_convert_datetimefield_value(self, value, expression, connection)
    
    # Handle string values
    if isinstance(value, str):
        value = value.strip()
        if not value or value in ('0000-00-00 00:00:00', '0000-00-00', 'None', 'null'):
            return None
        
        # Try to parse common datetime formats
        for fmt in (
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%d',
        ):
            try:
                parsed = datetime.strptime(value, fmt)
                # Now let Django's original converter handle timezone
                return _original_convert_datetimefield_value(self, parsed, expression, connection)
            except ValueError:
                continue
        
        # If we can't parse it, return None instead of crashing
        import logging
        logger = logging.getLogger('django.db.backends')
        logger.warning(f"Could not parse datetime string: {value!r}")
        return None
    
    # For any other type, try the original converter
    return _original_convert_datetimefield_value(self, value, expression, connection)


# Apply the patch
mysql_ops.DatabaseOperations.convert_datetimefield_value = _patched_convert_datetimefield_value


# Also patch convert_datefield_value if it exists
if hasattr(mysql_ops.DatabaseOperations, 'convert_datefield_value'):
    _original_convert_datefield_value = mysql_ops.DatabaseOperations.convert_datefield_value
    
    def _patched_convert_datefield_value(self, value, expression, connection):
        if value is None:
            return value
        
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        
        if isinstance(value, datetime):
            return value.date()
        
        if isinstance(value, str):
            value = value.strip()
            if not value or value == '0000-00-00':
                return None
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                return None
        
        return _original_convert_datefield_value(self, value, expression, connection)
    
    mysql_ops.DatabaseOperations.convert_datefield_value = _patched_convert_datefield_value


# Patch convert_timefield_value if it exists
if hasattr(mysql_ops.DatabaseOperations, 'convert_timefield_value'):
    _original_convert_timefield_value = mysql_ops.DatabaseOperations.convert_timefield_value
    
    def _patched_convert_timefield_value(self, value, expression, connection):
        if value is None:
            return value
        
        if isinstance(value, time):
            return value
        
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            for fmt in ('%H:%M:%S', '%H:%M:%S.%f', '%H:%M'):
                try:
                    return datetime.strptime(value, fmt).time()
                except ValueError:
                    continue
            return None
        
        return _original_convert_timefield_value(self, value, expression, connection)
    
    mysql_ops.DatabaseOperations.convert_timefield_value = _patched_convert_timefield_value


print("✓ Django MySQL datetime string patch applied")
