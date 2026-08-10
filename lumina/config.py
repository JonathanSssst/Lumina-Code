from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_REQUEST_TOKENS = 8192


class Settings(BaseSettings):
    """Runtime settings, loaded from environment variables and .env file.

    Precedence: environment variable > .env file > defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- DeepSeek API ---
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    deepseek_planner_model: str = Field(default="deepseek-reasoner", alias="DEEPSEEK_PLANNER_MODEL")

    # --- Agent behavior ---
    max_iterations: int = Field(default=20, alias="LUMINA_MAX_ITERATIONS")
    max_tokens: int = Field(default=8192, alias="LUMINA_MAX_TOKENS")
    token_budget: int = Field(default=30000, alias="LUMINA_TOKEN_BUDGET")
    temperature: float = Field(default=0.3, alias="LUMINA_TEMPERATURE")
    max_auto_fix_rounds: int = Field(default=3, alias="LUMINA_MAX_AUTO_FIX_ROUNDS")

    @field_validator("max_tokens")
    @classmethod
    def _clamp_max_tokens(cls, v: int) -> int:
        return min(v, MAX_REQUEST_TOKENS)

    # --- Planner (reasoner plans, flash executes) ---
    enable_planner: bool = Field(default=False, alias="LUMINA_ENABLE_PLANNER")
    planner_max_tokens: int = Field(default=4096, alias="LUMINA_PLANNER_MAX_TOKENS")

    # --- Context compression (keeps long tasks from running out of budget) ---
    compression_enabled: bool = Field(default=True, alias="LUMINA_COMPRESSION")
    compress_at_percent: float = Field(default=0.6, alias="LUMINA_COMPRESS_AT")
    compress_keep_messages: int = Field(default=10, alias="LUMINA_COMPRESS_KEEP")

    # --- Self-review: verify the final answer, continue if gaps are found ---
    self_review: bool = Field(default=True, alias="LUMINA_SELF_REVIEW")

    # --- Web: extra workspace directories (comma-separated absolute paths) ---
    workspaces: str = Field(default="", alias="LUMINA_WORKSPACES")

    # --- Security ---
    danger_commands: str = Field(
        default="rm -rf,git push,git push --force,git reset --hard,git clean,drop database",
        alias="LUMINA_DANGER_COMMANDS",
    )
    safe_commands: str = Field(
        default="pytest,ruff,python,git status,git diff,git log,ls,dir,pip install",
        alias="LUMINA_SAFE_COMMANDS",
    )

    @property
    def danger_command_list(self) -> list[str]:
        return [c.strip().lower() for c in self.danger_commands.split(",") if c.strip()]

    @property
    def safe_command_list(self) -> list[str]:
        return [c.strip().lower() for c in self.safe_commands.split(",") if c.strip()]

    @property
    def api_key(self) -> str:
        return (self.deepseek_api_key or "").strip()

    def validate_for_run(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "DeepSeek API key is missing. Set DEEPSEEK_API_KEY in your environment "
                "or create a .env file (see .env.example)."
            )


def resolve_env_file(project_root: Path) -> Path | None:
    """Locate the .env file next to the project root if present."""
    candidate = project_root / ".env"
    return candidate if candidate.exists() else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
