try:
    import pymysql

    pymysql.install_as_MySQLdb()
except Exception:
    # If PyMySQL isn't installed, leave as-is; Django will raise on DB connect
    pass

from .celery import app as celery_app  # noqa: F401

def _set_mysql_timezone(sender, connection, **kwargs):
    """
    Set MySQL session timezone to match Django's TIME_ZONE on each connection.
    This prevents datetime string conversion issues with PyMySQL.
    """
    if connection.vendor == 'mysql':
        with connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+06:00'")


# Connect the signal when Django is ready
from django.db.backends.signals import connection_created
connection_created.connect(_set_mysql_timezone)