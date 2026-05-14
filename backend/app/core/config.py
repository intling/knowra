from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "knowra"
    app_env: str = "local"
    debug: bool = True
    api_prefix: str = "/api"
    backend_cors_origins: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://knowra:knowra@localhost:5432/knowra"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
