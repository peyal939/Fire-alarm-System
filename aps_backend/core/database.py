from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .config import get_settings


settings = get_settings()

# Using sync SQLAlchemy for simplicity; can switch to async if needed later.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
