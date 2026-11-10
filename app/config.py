from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Gmail Bridge"
    database_url: str
    bridge_api_key: str
    fernet_key: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    allowed_origins: str = "https://chatgpt.com,https://chat.openai.com"
    max_attachment_bytes: int = 15 * 1024 * 1024

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
