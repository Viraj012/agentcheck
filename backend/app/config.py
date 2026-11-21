"""All runtime configuration. Every limit in the system is defined here."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, PositiveFloat, PositiveInt, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "AgentCheck"

REPO_ROOT = Path(__file__).resolve().parents[2]

Fraction = Annotated[float, Field(gt=0, le=1)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Infrastructure and secrets
    database_url: str = "postgresql://agentcheck:agentcheck@localhost:5432/agentcheck"
    gemini_api_key: SecretStr | None = None
    gemini_model_fast: str = "gemini-3.5-flash-lite"
    gemini_model_judge: str = "gemini-3.8-flash"
    gemini_embedding_model: str = "gemini-embedding-2"
    embedding_dim: PositiveInt = 768
    cors_origins: list[str] = ["http://localhost:3000"]
    ip_hash_salt: SecretStr = SecretStr("change-me")

    # Crawl (SPEC 5.1, 5.2)
    max_pages: PositiveInt = 40
    max_page_bytes: PositiveInt = 2_000_000
    request_timeout_s: PositiveFloat = 10.0
    crawl_concurrency: PositiveInt = 4
    max_redirects: PositiveInt = 5
    min_page_chars: PositiveInt = 200
    needs_js_min_chars: PositiveInt = 500
    cache_days: PositiveInt = 7

    # Index and retrieval (SPEC 5.3, 5.4)
    chunk_target_tokens: PositiveInt = 500
    chunk_min_tokens: PositiveInt = 400
    chunk_max_tokens: PositiveInt = 600
    chunk_overlap_tokens: PositiveInt = 50
    embed_batch: PositiveInt = 100
    retrieve_k: PositiveInt = 6
    rrf_k: PositiveInt = 60

    # Exam and grading (SPEC 5.6, 5.7)
    num_questions: PositiveInt = 24
    num_answerable: PositiveInt = 16
    num_unanswerable: PositiveInt = 4
    num_out_of_scope: PositiveInt = 2
    num_injection: PositiveInt = 2
    answer_batch: PositiveInt = 8
    grade_batch: PositiveInt = 8

    # Verdict (SPEC 5.8)
    ready_min_accuracy: Fraction = 0.85
    not_ready_below_accuracy: Fraction = 0.60

    # Cost and abuse protection (SPEC 8, 9)
    chat_limit: PositiveInt = 10
    runs_per_ip_per_day: PositiveInt = 3
    max_runs_per_day: PositiveInt = 30
    llm_rpm: PositiveInt = 12
    max_llm_calls_per_run: PositiveInt = 20
    llm_max_retries: PositiveInt = 4

    # Background worker
    worker_poll_s: PositiveFloat = 2.0
    stale_lock_s: PositiveInt = 300
    max_attempts: PositiveInt = 2

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        categories = (
            self.num_answerable + self.num_unanswerable + self.num_out_of_scope + self.num_injection
        )
        if categories != self.num_questions:
            raise ValueError(
                f"question category counts ({categories}) must sum to num_questions "
                f"({self.num_questions})"
            )
        if self.not_ready_below_accuracy >= self.ready_min_accuracy:
            raise ValueError("not_ready_below_accuracy must be lower than ready_min_accuracy")
        if not self.chunk_min_tokens <= self.chunk_target_tokens <= self.chunk_max_tokens:
            raise ValueError("chunk token sizes must satisfy min <= target <= max")
        if self.chunk_overlap_tokens >= self.chunk_min_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_min_tokens")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
