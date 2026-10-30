from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    rtl_433_path: str = "rtl_433"
    rtl_frequency: str = "433.925M"
    rtl_sample_rate: str = "1000k"
    rtl_gain: str = "40"
    rtl_extra_flags: str = "-Y autolevel -Y magest"

    database_path: str = "/data/weather.db"

    cors_origins: str = "*"

    restart_backoff_seconds: float = 5.0
    max_restart_backoff_seconds: float = 60.0
    stale_reading_seconds: int = 180

    # rtl_433 can start successfully but still fail to claim the USB dongle
    # (e.g. the previous container's process hasn't released it yet right
    # after a redeploy) without ever exiting on its own, so the normal
    # crash-and-backoff restart never triggers. If no reading has arrived in
    # this many seconds while otherwise "running", it's killed and restarted
    # from scratch. Kept below stale_reading_seconds so this usually recovers
    # before the dashboard even shows "Stale".
    watchdog_timeout_seconds: float = 90.0

    static_dir: str = "/app/static"

    log_level: str = "INFO"

    # 433MHz has no authentication, so anything transmitting in range can
    # produce a plausible-looking reading. Only accept ones whose model name
    # contains this (case-insensitive; empty string accepts any model), and
    # optionally lock onto one physical sensor's id once it's known.
    sensor_model_filter: str = "Fineoffset"
    sensor_id_filter: int | None = None

    # Where the station is, in decimal degrees (south and west are negative).
    # Only used to work out sunrise and sunset so the chart can shade the
    # night; left unset, the dashboard simply doesn't shade it.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("sensor_id_filter", "latitude", "longitude", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # An unset .env value still arrives as "" rather than being absent,
        # which a number-or-None field otherwise rejects instead of treating as None.
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def build_rtl_433_command(self) -> list[str]:
        command = [
            self.rtl_433_path,
            "-f",
            self.rtl_frequency,
            "-s",
            self.rtl_sample_rate,
            "-g",
            self.rtl_gain,
        ]
        command.extend(self.rtl_extra_flags.split())
        command.extend(["-F", "json"])
        return command


@lru_cache
def get_settings() -> Settings:
    return Settings()
