from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

DEFAULT_WEIGHTS = {"skills": 0.40, "semantic": 0.20, "role": 0.15,
                   "experience": 0.10, "education": 0.05, "location": 0.10}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _weights() -> dict[str, float]:
    raw = os.getenv("MATCH_WEIGHTS")
    if raw:
        try:
            w = json.loads(raw)
            return {k: float(w.get(k, v)) for k, v in DEFAULT_WEIGHTS.items()}
        except (ValueError, TypeError):
            pass
    return dict(DEFAULT_WEIGHTS)


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    groq_model: str = field(default_factory=lambda: _env("GROQ_MODEL", "llama-3.3-70b-versatile"))
    search_provider: str = field(default_factory=lambda: _env("SEARCH_PROVIDER", "duckduckgo").lower())
    tavily_api_key: str = field(default_factory=lambda: _env("TAVILY_API_KEY"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./careerpilot.db"))
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    max_iterations: int = field(default_factory=lambda: int(_env("MAX_ITERATIONS", "2")))
    min_good_jobs: int = field(default_factory=lambda: int(_env("MIN_GOOD_JOBS", "3")))
    verify_top_n: int = field(default_factory=lambda: int(_env("VERIFY_TOP_N", "10")))
    max_results_per_query: int = field(default_factory=lambda: int(_env("MAX_RESULTS_PER_QUERY", "8")))
    http_timeout: float = field(default_factory=lambda: float(_env("HTTP_TIMEOUT", "10")))
    max_pdf_mb: int = field(default_factory=lambda: int(_env("MAX_PDF_MB", "5")))
    rate_limit_per_min: int = field(default_factory=lambda: int(_env("RATE_LIMIT_PER_MIN", "30")))
    use_sentence_transformers: bool = field(default_factory=lambda: _env("USE_SENTENCE_TRANSFORMERS", "0") == "1")
    match_weights: dict = field(default_factory=_weights)
    api_url: str = field(default_factory=lambda: _env("API_URL", "http://localhost:8000"))


def get_settings() -> Settings:
    return Settings()
