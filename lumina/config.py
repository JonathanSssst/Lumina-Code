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
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    # --- LLM provider (OpenAI-compatible protocol) ---
    # LuminaCode speaks the OpenAI chat/completions protocol, so any
    # compatible vendor works: DeepSeek, OpenAI, Ollama, vLLM, ...
    # `LUMINA_LLM_PROVIDER` picks the active one: "deepseek" | "openai" | "auto".
    # In "auto" mode, setting OPENAI_API_KEY switches the provider to openai.
    llm_provider: str = Field(default="auto", alias="LUMINA_LLM_PROVIDER")

    # DeepSeek (default)
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    deepseek_planner_model: str = Field(default="deepseek-reasoner", alias="DEEPSEEK_PLANNER_MODEL")

    # OpenAI / any OpenAI-compatible vendor
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_planner_model: str = Field(default="gpt-4o", alias="OPENAI_PLANNER_MODEL")

    # --- Agent behavior ---
    max_iterations: int = Field(default=20, alias="LUMINA_MAX_ITERATIONS")
    max_tokens: int = Field(default=8192, alias="LUMINA_MAX_TOKENS")
    # 0 = unlimited (no cumulative-token cap). Set a positive value to stop
    # long tasks once the conversation consumes that many tokens.
    token_budget: int = Field(default=0, alias="LUMINA_TOKEN_BUDGET")
    # Context window the UI uses to display per-session usage (tokens/context).
    context_limit: int = Field(default=131072, alias="LUMINA_CONTEXT_LIMIT")
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
        default="pytest,ruff,python,git status,git diff,git log,ls,dir,cd,pip install",
        alias="LUMINA_SAFE_COMMANDS",
    )

    @property
    def danger_command_list(self) -> list[str]:
        return [c.strip().lower() for c in self.danger_commands.split(",") if c.strip()]

    @property
    def safe_command_list(self) -> list[str]:
        return [c.strip().lower() for c in self.safe_commands.split(",") if c.strip()]

    @property
    def provider(self) -> str:
        chosen = (self.llm_provider or "auto").strip().lower()
        if chosen in ("deepseek", "openai"):
            return chosen
        return "openai" if (self.openai_api_key or "").strip() else "deepseek"

    @property
    def api_key(self) -> str:
        return (self.openai_api_key if self.provider == "openai" else self.deepseek_api_key or "").strip()

    @property
    def base_url(self) -> str:
        return self.openai_base_url if self.provider == "openai" else self.deepseek_base_url

    @property
    def model(self) -> str:
        return self.openai_model if self.provider == "openai" else self.deepseek_model

    @property
    def planner_model(self) -> str:
        return self.openai_planner_model if self.provider == "openai" else self.deepseek_planner_model

    @property
    def key_env_var(self) -> str:
        return "OPENAI_API_KEY" if self.provider == "openai" else "DEEPSEEK_API_KEY"

    def validate_for_run(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                f"API key is missing for the active provider ({self.provider}). "
                f"Set {self.key_env_var} in your environment or create a .env file (see .env.example)."
            )


def resolve_env_file(project_root: Path) -> Path | None:
    """Locate the .env file next to the project root if present."""
    candidate = project_root / ".env"
    return candidate if candidate.exists() else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
