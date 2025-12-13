"""Runtime configuration helpers for fort-gym."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


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
    ARTIFACTS_DIR: str = os.getenv("ARTIFACTS_DIR", "artifacts")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "512"))
    LLM_TEMP: float = float(os.getenv("LLM_TEMP", "0.1"))
    LLM_RATE_LIMIT_TPS: float = float(os.getenv("LLM_RATE_LIMIT_TPS", "1.0"))

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
        ARTIFACTS_DIR=os.getenv("ARTIFACTS_DIR", "artifacts"),
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
        OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY"),
        ANTHROPIC_MODEL=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        LLM_MAX_TOKENS=int(os.getenv("LLM_MAX_TOKENS", "512")),
        LLM_TEMP=float(os.getenv("LLM_TEMP", "0.1")),
        LLM_RATE_LIMIT_TPS=float(os.getenv("LLM_RATE_LIMIT_TPS", "1.0")),
    )


def have_openai() -> bool:
    return bool(get_settings().OPENAI_API_KEY)


def have_anthropic() -> bool:
    return bool(get_settings().ANTHROPIC_API_KEY)


__all__ = [
    "Settings",
    "get_settings",
    "have_openai",
    "have_anthropic",
    "DFROOT",
    "DFHACK_RUN",
    "dfhack_cmd",
]
