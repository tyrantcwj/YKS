from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "宝可梦卡价格订阅"
    database_path: str = "data/app.db"
    sync_interval_minutes: int = 360
    tcgdex_locale: str = "en"
    request_timeout_seconds: float = 15.0
    auth_username: str = "admin"
    auth_password: str = ""
    alert_webhook_url: str = ""
    alert_webhook_timeout_seconds: float = 10.0
    yks_update_mode: str = "auto"
    yks_update_repo: str = "tyrantcwj/YKS"
    yks_update_branch: str = "main"
    yks_update_timeout_seconds: float = 120.0
    yks_github_mirror_prefix: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
