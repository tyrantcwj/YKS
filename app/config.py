from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Pokemon Price Watch"
    database_path: str = "data/app.db"
    sync_interval_minutes: int = 360
    tcgdex_locale: str = "en"
    request_timeout_seconds: float = 15.0
    auth_username: str = "admin"
    auth_password: str = ""
    alert_webhook_url: str = ""
    alert_webhook_timeout_seconds: float = 10.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
