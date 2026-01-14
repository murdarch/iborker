"""Configuration management using Pydantic settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class IBSettings(BaseSettings):
    """Settings for Interactive Brokers connection."""

    model_config = SettingsConfigDict(
        env_prefix="IB_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    host: str = "127.0.0.1"
    port: int = 7497  # TWS paper trading default
    client_id: int = 1
    timeout: float = 10.0
    readonly: bool = False


settings = IBSettings()
