from __future__ import annotations

from collections.abc import Iterator

import pytest

from fort_gym.bench.config import get_settings

PROVIDER_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_poisoned_dotenv(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=poison-anthropic\n"
        "OPENAI_API_KEY=poison-openai\n"
        "OPENROUTER_API_KEY=poison-openrouter\n",
        encoding="utf-8",
    )


def test_disable_dotenv_blocks_provider_keys(tmp_path, monkeypatch) -> None:
    _write_poisoned_dotenv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORT_GYM_DISABLE_DOTENV", "1")
    for key in PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    assert settings.ANTHROPIC_API_KEY is None
    assert settings.OPENAI_API_KEY is None
    assert settings.OPENROUTER_API_KEY is None


def test_dotenv_loading_remains_enabled_by_default(tmp_path, monkeypatch) -> None:
    _write_poisoned_dotenv(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FORT_GYM_DISABLE_DOTENV", raising=False)
    for key in PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    assert settings.ANTHROPIC_API_KEY == "poison-anthropic"
    assert settings.OPENAI_API_KEY == "poison-openai"
    assert settings.OPENROUTER_API_KEY == "poison-openrouter"
