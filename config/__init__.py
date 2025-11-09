try:
    import pymysql

    pymysql.install_as_MySQLdb()
except Exception:
    # If PyMySQL isn't installed, leave as-is; Django will raise on DB connect
    pass

from .celery import app as celery_app  # noqa: F401
