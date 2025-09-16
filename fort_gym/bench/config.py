"""Runtime configuration helpers for fort-gym."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
    except OSError:
        pass


class Settings(BaseModel):
    DFHACK_ENABLED: bool = bool(int(os.getenv("DFHACK_ENABLED", "0")))
    DFHACK_HOST: str = os.getenv("DFHACK_HOST", "127.0.0.1")
    DFHACK_PORT: int = int(os.getenv("DFHACK_PORT", "5000"))
    TICKS_PER_STEP: int = int(os.getenv("TICKS_PER_STEP", "200"))
    ARTIFACTS_DIR: str = os.getenv("ARTIFACTS_DIR", "fort_gym/artifacts")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "512"))
    LLM_TEMP: float = float(os.getenv("LLM_TEMP", "0.1"))
    LLM_RATE_LIMIT_TPS: float = float(os.getenv("LLM_RATE_LIMIT_TPS", "1.0"))

    class Config:
        frozen = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    return Settings()


def have_openai() -> bool:
    return bool(get_settings().OPENAI_API_KEY)


def have_anthropic() -> bool:
    return bool(get_settings().ANTHROPIC_API_KEY)


__all__ = ["Settings", "get_settings", "have_openai", "have_anthropic"]
