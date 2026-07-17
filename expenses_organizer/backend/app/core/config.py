from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Expenses Organizer"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/expenses_organizer"
    upload_dir: str = "uploads"
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "documents"

    ocr_languages: str = "spa+eng"
    tesseract_cmd: str | None = None
    poppler_path: str | None = None
    tessdata_prefix: str | None = None

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"

    cors_allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


settings = Settings()
