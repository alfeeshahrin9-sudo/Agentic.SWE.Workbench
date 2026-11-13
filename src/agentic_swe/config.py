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
    llm_provider: str = Field(default="auto")  # auto | openai | ollama | github | groq | gemini
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", validation_alias="OPENAI_MODEL")
    ollama_base_url: str = Field(default="http://localhost:11434/v1")
    use_mcp_tools: bool = Field(default=False)
    mcp_servers_file: Path = Field(default=ROOT / "mcp_servers.json")
    e2b_api_key: str | None = Field(default=None, validation_alias="E2B_API_KEY")

    @property
    def resolved_base_url(self) -> str | None:
        if self.openai_base_url:
            return self.openai_base_url
        provider = self.llm_provider.lower()
        if provider == "ollama":
            return self.ollama_base_url
        if provider == "github":
            return "https://models.inference.ai.azure.com"
        if provider == "groq":
            return "https://api.groq.com/openai/v1"
        if provider == "gemini":
            return "https://generativelanguage.googleapis.com/v1beta/openai/"
        return None

    @property
    def resolved_api_key(self) -> str | None:
        if self.openai_api_key:
            return self.openai_api_key
        if self.llm_provider.lower() == "ollama" or (
            self.openai_base_url and "11434" in self.openai_base_url
        ):
            return "ollama"
        return None

    @property
    def llm_enabled(self) -> bool:
        return bool(self.resolved_api_key)


def get_settings() -> Settings:
    return Settings()
