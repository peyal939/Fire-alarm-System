import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from django.conf import settings

import warnings
import cryptography

# Suppress the harmless "Parsed a serial number which wasn't positive" warning
# This is caused by some older root certificates and newer cryptography versions
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=cryptography.utils.CryptographyDeprecationWarning)

logger = logging.getLogger(__name__)

class MongoDBClient:
    _instance = None
    _client = None
    _db = None
    _collection = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MongoDBClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is None:
            self._connect()

    def _connect(self):
        uri = getattr(settings, "MONGO_URI", None)
        if not uri:
            logger.warning("MONGO_URI not set. MongoDB integration disabled.")
            return

        try:
            # Connect with a short timeout to avoid blocking startup if Mongo is down
            self._client = MongoClient(uri, serverSelectionTimeoutMS=2000)
            # Trigger a check to see if we can actually connect
            # self._client.admin.command('ping') 
            
            db_name = getattr(settings, "MONGO_DB_NAME", "firealarm")
            collection_name = getattr(settings, "MONGO_COLLECTION_NAME", "sensordata")
            
            self._db = self._client[db_name]
            self._collection = self._db[collection_name]
            
            logger.info(f"✅ MongoDB client initialized (DB: {db_name}, Coll: {collection_name})")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"❌ Failed to connect to MongoDB: {e}")
            self._client = None

    def get_collection(self):
        """Returns the configured collection or None if not connected."""
        if self._client is None:
            # Try reconnecting lazily
            self._connect()
        
        return self._collection

    def insert_one(self, document):
        """Safely insert a document without raising exceptions."""
        col = self.get_collection()
        if col is None:
            return False
        
        try:
            col.insert_one(document)
            return True
        except Exception as e:
            logger.error(f"Failed to insert into MongoDB: {e}")
            return False

# Global instance
mongo_client = MongoDBClient()
