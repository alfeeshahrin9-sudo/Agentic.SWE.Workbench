from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="AGENTIC_SWE_",
        extra="ignore",
    )

    runs_dir: Path = Field(default=ROOT / ".runs")
    max_heal_attempts: int = 5
    max_files_touched: int = 8
    command_timeout_sec: int = 120
    sandbox_backend: str = Field(default="local")  # local | e2b
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    e2b_api_key: str | None = Field(default=None, validation_alias="E2B_API_KEY")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)


def get_settings() -> Settings:
    return Settings()
