from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBDBMCP_", env_file=".env", extra="ignore")

    database_url: str
    host: str = "127.0.0.1"
    port: int = 8000
    pool_min_size: int = 1
    pool_max_size: int = 5
