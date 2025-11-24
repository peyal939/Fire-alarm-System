import os
import sys
import django
from pathlib import Path

# Setup Django environment
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from utils.mongo_client import mongo_client
from django.utils import timezone

def verify():
    print("Verifying MongoDB Connection...")
    col = mongo_client.get_collection()
    
    if col is None:
        print("❌ Failed to get collection. Check logs/credentials.")
        return

    print(f"✅ Connected to: {col.database.name}.{col.name}")
    
    # Test Insert
    doc = {
        "test": True,
        "timestamp": timezone.now(),
        "message": "Verification script test"
    }
    
    success = mongo_client.insert_one(doc)
    if success:
        print("✅ Insert successful!")
    else:
        print("❌ Insert failed.")

if __name__ == "__main__":
    verify()
