"""Runtime configuration, loaded from the environment and an optional .env file."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LESSON_", env_file=ENV_FILE, extra="ignore")

    writer_model: str = "google_genai:gemini-3.5-flash"
    judge_model: str = "google_genai:gemini-3.5-flash"
    fallback_models: list[str] = [
        "google_genai:gemini-3.6-flash",
        "google_genai:gemini-3.7-flash",
        "google_genai:gemini-3.8-flash",
        "google_genai:gemini-3.5-flash-lite",
        "google_genai:gemini-3.1-flash-lite",
    ]
    writer_thinking: str | None = "medium"
    judge_thinking: str | None = "medium"
    temperature: float | None = None
    max_output_tokens: int = 16000
    request_timeout_seconds: int = 45
    hedge_after_seconds: float = 15.0
    call_deadline_seconds: float = 75.0
    section_concurrency: int = 7

    max_retries: int = Field(default=2, ge=1, le=2)
    judge_concurrency: int = Field(default=6, ge=1)
    llm_rounds: int = Field(default=3, ge=1)
    fresh_starts: int = Field(default=1, ge=0, le=2)

    evolve_failure_threshold: int = Field(default=2, ge=1)
    evolve_window_runs: int = Field(default=10, ge=1)
    max_active_guidelines: int = Field(default=8, ge=1)

    data_dir: Path = PROJECT_ROOT / "data"
    output_dir: Path = PROJECT_ROOT / "outputs"
    frontend_dir: Path = PROJECT_ROOT / "frontend" / "dist"

    @property
    def memory_path(self) -> Path:
        return self.data_dir / "memory.db"
