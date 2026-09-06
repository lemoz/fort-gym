"""Runtime configuration helpers for fort-gym."""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

_DEFAULT_OPENROUTER_MAX_TOTAL_TOKENS = 128_000
_DEFAULT_OPENROUTER_MAX_COST_USD = 25.0


def _positive_int_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_float_env(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return value


# DFHack path configuration (Mac vs Linux)
DFROOT = Path(os.getenv("DFROOT", "/opt/dwarf-fortress"))
DFHACK_RUN = DFROOT / "dfhack-run"


def dfhack_cmd(*args: str) -> list[str]:
    """Return the absolute dfhack-run command sequence for subprocess calls.

    Usage:
        subprocess.check_output(dfhack_cmd("lua", "-e", "print('hello')"))

    Environment:
        Set DFROOT to point to your DF installation:
        - Mac (Lazy Mac Pack): export DFROOT="$HOME/Applications/Lazy Mac Pack/Dwarf Fortress"
        - Linux/VM: export DFROOT="/opt/dwarf-fortress" (default)
    """
    return [str(DFHACK_RUN), *args]


def _load_dotenv() -> None:
    if os.getenv("FORT_GYM_DISABLE_DOTENV") == "1":
        return
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
    FORT_GYM_SEED_SAVE: Optional[str] = os.getenv("FORT_GYM_SEED_SAVE")
    FORT_GYM_RUNTIME_SAVE: str = os.getenv("FORT_GYM_RUNTIME_SAVE", "current")
    TICKS_PER_STEP: int = int(os.getenv("TICKS_PER_STEP", "200"))
    ARTIFACTS_DIR: str = os.getenv("ARTIFACTS_DIR", "fort_gym/artifacts")
    FORT_GYM_PUBLIC_CAMPAIGN_DIR: Optional[str] = os.getenv("FORT_GYM_PUBLIC_CAMPAIGN_DIR")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "z-ai/glm-5.2")
    OPENROUTER_BASE_URL: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    OPENROUTER_TIMEOUT_SECONDS: float = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30"))
    OPENROUTER_MAX_ATTEMPTS: int = int(os.getenv("OPENROUTER_MAX_ATTEMPTS", "3"))
    OPENROUTER_MAX_TOOL_ROUNDS: int = int(os.getenv("OPENROUTER_MAX_TOOL_ROUNDS", "4"))
    OPENROUTER_DISABLE_REASONING: bool = bool(
        int(os.getenv("OPENROUTER_DISABLE_REASONING", "1"))
    )
    OPENROUTER_PROVIDER_NAME: Optional[str] = os.getenv("OPENROUTER_PROVIDER_NAME")
    OPENROUTER_STRICT_SUPERVISED: bool = bool(
        int(os.getenv("OPENROUTER_STRICT_SUPERVISED", "0"))
    )
    OPENROUTER_MAX_TOTAL_TOKENS: int = _DEFAULT_OPENROUTER_MAX_TOTAL_TOKENS
    OPENROUTER_MAX_COST_USD: float = _DEFAULT_OPENROUTER_MAX_COST_USD
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    ANTHROPIC_OPUS_MODEL: str = os.getenv("ANTHROPIC_OPUS_MODEL", "claude-opus-4-8")
    ANTHROPIC_TIMEOUT_SECONDS: float = float(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "30"))
    ANTHROPIC_MAX_ATTEMPTS: int = int(os.getenv("ANTHROPIC_MAX_ATTEMPTS", "6"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "512"))
    LLM_TEMP: float = float(os.getenv("LLM_TEMP", "0.1"))
    LLM_RATE_LIMIT_TPS: float = float(os.getenv("LLM_RATE_LIMIT_TPS", "1.0"))
    MEMORY_WINDOW: int = int(os.getenv("FORT_GYM_MEMORY_WINDOW", "10"))
    ACTION_HISTORY_LIMIT: int = int(
        os.getenv(
            "FORT_GYM_ACTION_HISTORY_LIMIT",
            os.getenv("FORT_GYM_KEYSTROKE_ACTION_HISTORY_LIMIT", "30"),
        )
    )
    KEYSTROKE_ACTION_HISTORY_LIMIT: int = int(
        os.getenv("FORT_GYM_KEYSTROKE_ACTION_HISTORY_LIMIT", "30")
    )

    class Config:
        frozen = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        DFHACK_ENABLED=bool(int(os.getenv("DFHACK_ENABLED", "0"))),
        DFHACK_HOST=os.getenv("DFHACK_HOST", "127.0.0.1"),
        DFHACK_PORT=int(os.getenv("DFHACK_PORT", "5000")),
        FORT_GYM_SEED_SAVE=os.getenv("FORT_GYM_SEED_SAVE"),
        FORT_GYM_RUNTIME_SAVE=os.getenv("FORT_GYM_RUNTIME_SAVE", "current"),
        TICKS_PER_STEP=int(os.getenv("TICKS_PER_STEP", "200")),
        ARTIFACTS_DIR=os.getenv("ARTIFACTS_DIR", "fort_gym/artifacts"),
        FORT_GYM_PUBLIC_CAMPAIGN_DIR=os.getenv("FORT_GYM_PUBLIC_CAMPAIGN_DIR"),
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
        OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        OPENROUTER_API_KEY=os.getenv("OPENROUTER_API_KEY"),
        OPENROUTER_MODEL=os.getenv("OPENROUTER_MODEL", "z-ai/glm-5.2"),
        OPENROUTER_BASE_URL=os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        OPENROUTER_TIMEOUT_SECONDS=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30")),
        OPENROUTER_MAX_ATTEMPTS=int(os.getenv("OPENROUTER_MAX_ATTEMPTS", "3")),
        OPENROUTER_MAX_TOOL_ROUNDS=int(os.getenv("OPENROUTER_MAX_TOOL_ROUNDS", "4")),
        OPENROUTER_DISABLE_REASONING=bool(
            int(os.getenv("OPENROUTER_DISABLE_REASONING", "1"))
        ),
        OPENROUTER_PROVIDER_NAME=os.getenv("OPENROUTER_PROVIDER_NAME"),
        OPENROUTER_STRICT_SUPERVISED=bool(
            int(os.getenv("OPENROUTER_STRICT_SUPERVISED", "0"))
        ),
        OPENROUTER_MAX_TOTAL_TOKENS=_positive_int_env(
            "OPENROUTER_MAX_TOTAL_TOKENS",
            _DEFAULT_OPENROUTER_MAX_TOTAL_TOKENS,
        ),
        OPENROUTER_MAX_COST_USD=_positive_float_env(
            "OPENROUTER_MAX_COST_USD",
            _DEFAULT_OPENROUTER_MAX_COST_USD,
        ),
        ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY"),
        ANTHROPIC_MODEL=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        ANTHROPIC_OPUS_MODEL=os.getenv("ANTHROPIC_OPUS_MODEL", "claude-opus-4-8"),
        ANTHROPIC_TIMEOUT_SECONDS=float(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "30")),
        ANTHROPIC_MAX_ATTEMPTS=int(os.getenv("ANTHROPIC_MAX_ATTEMPTS", "6")),
        LLM_MAX_TOKENS=int(os.getenv("LLM_MAX_TOKENS", "512")),
        LLM_TEMP=float(os.getenv("LLM_TEMP", "0.1")),
        LLM_RATE_LIMIT_TPS=float(os.getenv("LLM_RATE_LIMIT_TPS", "1.0")),
        MEMORY_WINDOW=int(os.getenv("FORT_GYM_MEMORY_WINDOW", "10")),
        ACTION_HISTORY_LIMIT=int(
            os.getenv(
                "FORT_GYM_ACTION_HISTORY_LIMIT",
                os.getenv("FORT_GYM_KEYSTROKE_ACTION_HISTORY_LIMIT", "30"),
            )
        ),
        KEYSTROKE_ACTION_HISTORY_LIMIT=int(
            os.getenv("FORT_GYM_KEYSTROKE_ACTION_HISTORY_LIMIT", "30")
        ),
    )


def have_openai() -> bool:
    return bool(get_settings().OPENAI_API_KEY)


def have_openrouter() -> bool:
    return bool(get_settings().OPENROUTER_API_KEY)


def have_anthropic() -> bool:
    return bool(get_settings().ANTHROPIC_API_KEY)


__all__ = [
    "Settings",
    "get_settings",
    "have_openai",
    "have_openrouter",
    "have_anthropic",
    "DFROOT",
    "DFHACK_RUN",
    "dfhack_cmd",
]
