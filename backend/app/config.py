from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./offerlens.db"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    cors_origins: str = "http://localhost:3000"
    cors_origin_regex: str | None = None  # e.g. https://offerlens.*\.vercel\.app
    max_upload_mb: int = 10
    cleanup_every: int = 50  # wipe stored offers after this many uploads + comparisons (0 = never)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        # Hosted Postgres providers hand out postgres:// URLs; SQLAlchemy needs the driver name
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


settings = Settings()
