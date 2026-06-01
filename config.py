from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/zol"
    ADMIN_TOKEN: str = "change-me"
    LOG_LEVEL: str = "info"
    CRON_HOUR: int = 3
    CRON_MINUTE: int = 0

    # אוטומציות חיצוניות (אופציונלי)
    MAKE_WEBHOOK_URL: str = ""        # Make.com webhook לוואטסאפ/מייל
    OPEN_FOOD_FACTS_URL: str = "https://world.openfoodfacts.org/api/v2/product"

settings = Settings()
