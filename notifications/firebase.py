"""Firebase Cloud Messaging initialization and configuration.

This module handles the initialization of Firebase Admin SDK for sending
push notifications to mobile devices.
"""

import logging
import os
from pathlib import Path

import firebase_admin
from firebase_admin import credentials
from django.conf import settings

logger = logging.getLogger(__name__)

_firebase_initialized = False


def initialize_firebase():
    """Initialize Firebase Admin SDK with service account credentials.

    This function should be called once during application startup.
    It looks for Firebase service account credentials in the following order:
    1. FIREBASE_CREDENTIALS_PATH environment variable (path to JSON file)
    2. FIREBASE_CREDENTIALS environment variable (JSON string)
    3. firebase-credentials.json in BASE_DIR

    If no credentials are found, Firebase will not be initialized and push
    notifications will be disabled (logs warning).
    """
    global _firebase_initialized

    if _firebase_initialized:
        logger.debug("Firebase already initialized")
        return

    # Try to get credentials from environment
    creds_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    creds_json = os.getenv("FIREBASE_CREDENTIALS")

    # Fallback to default location
    if not creds_path and not creds_json:
        default_path = Path(settings.BASE_DIR) / "firebase-credentials.json"
        if default_path.exists():
            creds_path = str(default_path)

    try:
        if creds_path:
            # Initialize from file
            cred = credentials.Certificate(creds_path)
            firebase_admin.initialize_app(cred)
            logger.info(f"Firebase initialized successfully from {creds_path}")
            _firebase_initialized = True
        elif creds_json:
            # Initialize from JSON string
            import json

            cred_dict = json.loads(creds_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase initialized successfully from environment JSON")
            _firebase_initialized = True
        else:
            logger.warning(
                "Firebase credentials not found. Push notifications will be disabled. "
                "Set FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS environment variable, "
                "or place firebase-credentials.json in project root."
            )
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}", exc_info=True)


def is_firebase_initialized() -> bool:
    """Check if Firebase has been successfully initialized."""
    return _firebase_initialized
