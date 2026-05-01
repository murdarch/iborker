"""Configuration management using Pydantic settings."""

from typing import Literal

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
    timeout: float = 10.0
    readonly: bool = False

    # Client ID management
    client_id: int = 1  # Used when client_id_mode="fixed"
    client_id_start: int = 1  # Base/floor for auto-allocated IDs
    client_id_mode: Literal["auto", "fixed"] = "auto"

    # Account nicknames: {"U1234567": "IRA", "U7654321": "Main"}
    account_nicknames: dict[str, str] = {}

    # Guardrails mode (only required when --guardrails-on is passed)
    daily_goal: float | None = None
    loss_cooldown_threshold: float | None = None
    loss_cooldown_seconds: int | None = None
    rearm_cooldown_seconds: int | None = None
    trade_cooldown_seconds: int | None = None
    max_round_trips: int | None = None
    clock_in_countdown_minutes: int = 15

    @classmethod
    def guardrails_required(cls, settings: "IBSettings | None" = None) -> list[str]:
        """Return env-var names required for guardrails mode that are unset.

        Defaults to a freshly-loaded settings instance.  Tests can pass an
        instance constructed with ``_env_file=None`` to skip the project
        ``.env`` file.
        """
        s = settings if settings is not None else cls()
        missing: list[str] = []
        if s.daily_goal is None:
            missing.append("IB_DAILY_GOAL")
        if s.loss_cooldown_threshold is None:
            missing.append("IB_LOSS_COOLDOWN_THRESHOLD")
        if s.loss_cooldown_seconds is None:
            missing.append("IB_LOSS_COOLDOWN_SECONDS")
        if s.rearm_cooldown_seconds is None:
            missing.append("IB_REARM_COOLDOWN_SECONDS")
        if s.trade_cooldown_seconds is None:
            missing.append("IB_TRADE_COOLDOWN_SECONDS")
        if s.max_round_trips is None:
            missing.append("IB_MAX_ROUND_TRIPS")
        return missing


settings = IBSettings()
