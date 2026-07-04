from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    rtl_433_path: str = "rtl_433"
    rtl_frequency: str = "433.925M"
    rtl_sample_rate: str = "1000k"
    rtl_gain: str = "40"
    rtl_extra_flags: str = "-Y autolevel -Y magest"

    database_path: str = "/data/weather.db"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    cors_origins: str = "*"

    restart_backoff_seconds: float = 5.0
    max_restart_backoff_seconds: float = 60.0
    stale_reading_seconds: int = 180

    static_dir: str = "/app/static"

    @property
    def database_dir(self) -> Path:
        return Path(self.database_path).parent

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
