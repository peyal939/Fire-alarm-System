from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    APP_NAME: str = "apS Fire Backend"
    ENV: str = "dev"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Security
    JWT_SECRET: str = "change-me"
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Database (MySQL 8+)
    # Example: mysql+pymysql://user:pass@localhost:3306/aps
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost:3306/aps"

    # Redis (optional, for jobs/pubsub)
    REDIS_URL: str | None = None

    # MQTT
    MQTT_BROKER: str = "152.42.179.228"
    MQTT_PORT: int = 1885
    MQTT_TOPIC: str = "aps/fire/data"
    MQTT_USER: str | None = "apsIoT"
    MQTT_PASS: str | None = "apsIoT25"

    # Map defaults
    MAP_BASE_LAT: float = 23.777628
    MAP_BASE_LON: float = 90.405449
    MAP_JITTER: float = 0.01


@lru_cache
def get_settings() -> Settings:
    return Settings()
