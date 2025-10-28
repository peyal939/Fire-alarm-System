import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure PyMySQL is used as MySQLdb before Django imports DB backend
try:
    import pymysql  # type: ignore

    pymysql.install_as_MySQLdb()
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")

APP_NAME = os.getenv("APP_NAME", "apS Fire Backend")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# MQTT (no hardcoded sensitive creds; safe defaults for non-sensitive fields)
# Broker defaults to localhost and port 1883 if not provided; credentials default to empty
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883") or "1883")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "aps/fire/data")
MQTT_DEVICE_REG_TOPIC = os.getenv("MQTT_DEVICE_REG_TOPIC", "aps/fire/reg")
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASS", "")

# Alert rules
SMOKE_ALERT_THRESHOLD = int(os.getenv("SMOKE_ALERT_THRESHOLD", "50"))
# Device online freshness window (seconds). If a device hasn't sent a message
# within this window, it's considered offline.
# Default to 180 seconds (3 minutes); override via env if needed.
DEVICE_ONLINE_FRESHNESS_SECONDS = int(
    os.getenv("DEVICE_ONLINE_FRESHNESS_SECONDS", "180")
)

# If True, a slave entry in a composite MQTT payload must contain its OWN
# timestamp field (distinct from the master's) to be treated as a fresh
# telemetry update. This prevents a master from continually marking slaves
# online when they haven't actually sent data. Disable (set to 'false') if
# your firmware does not yet send per-slave timestamps.
SLAVE_REQUIRE_OWN_TIMESTAMP = (
    os.getenv("SLAVE_REQUIRE_OWN_TIMESTAMP", "true").lower() == "true"
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "accounts",
    "devices",
    "products",
    "api",
    "realtime",
    "notifications",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "shurjopay",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

# Timezone: always use Dhaka (GMT+6)
TIME_ZONE = "Asia/Dhaka"
USE_TZ = True

# When tunneling (e.g., ngrok), Django may receive X-Forwarded-Proto from a proxy.
# This ensures request.is_secure() works correctly behind HTTPS tunnels.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# CSRF trusted origins: required when using HTTPS origins like ngrok
_csrf_origins_env = os.getenv("CSRF_TRUSTED_ORIGINS", "").strip()
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins_env.split(",") if o.strip()]
# Helpful defaults for common dev tunnels when DEBUG
if DEBUG:
    CSRF_TRUSTED_ORIGINS += [
        "https://*.ngrok-free.app",
        "https://*.ngrok.app",
        "https://*.trycloudflare.com",
    ]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE", "aps"),
        "USER": os.getenv("MYSQL_USER", "root"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD", ""),
        "HOST": os.getenv("MYSQL_HOST", "localhost"),
        "PORT": os.getenv("MYSQL_PORT", "3306"),
        "OPTIONS": {
            "init_command": "SET sql_mode='STRICT_ALL_TABLES'",
        },
    }
}

# Channels: Use Redis if REDIS_URL is provided; fallback to in-memory for dev
REDIS_URL = os.getenv("REDIS_URL", "")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
                # Increase capacity to handle burst traffic from MQTT
                # Default is 100, which is too low for production IoT systems
                "capacity": 1000,  # Max messages per channel
                "expiry": 60,  # Message TTL in seconds (discard old messages)
            },
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
            "CONFIG": {
                "capacity": 1000,  # Increase from default 100
                "expiry": 60,  # Message TTL in seconds
            },
        }
    }

"""Static & media configuration.

In development Django can serve from STATICFILES_DIRS; in production we
collect all assets into STATIC_ROOT and let Nginx (or another web server)
serve them. A leading slash in STATIC_URL is required so references in
templates become absolute ("/static/..."), otherwise some reverse proxy
setups or the Django admin may fail to load CSS/JS.
"""

# Public URL prefix for static assets
STATIC_URL = "/static/"

# Source directories (uncollected) used in development & by collectstatic
STATICFILES_DIRS = [BASE_DIR / "static"]

# Target directory for collected static files (created by collectstatic)
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom user model
AUTH_USER_MODEL = "accounts.User"

# DRF and JWT configuration
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Include timezone offset (+06:00) in rendered datetimes
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S%z",
}

from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "ALGORITHM": "HS256",
}

# drf-spectacular settings
SPECTACULAR_SETTINGS = {
    "TITLE": os.getenv("OPENAPI_TITLE", "APS Fire Alarm API"),
    "DESCRIPTION": os.getenv(
        "OPENAPI_DESCRIPTION",
        "API schema for authentication, devices, telemetry, and alerts.",
    ),
    "VERSION": os.getenv("OPENAPI_VERSION", "1.0.0"),
    "SERVE_INCLUDE_SCHEMA": False,
}

# Session login settings for dashboard
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
