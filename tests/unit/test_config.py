from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


def test_env_example_documents_every_setting() -> None:
    assert set(_example_values()) == {name.upper() for name in Settings.model_fields}


def test_env_example_values_match_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _example_values():
        monkeypatch.delenv(key, raising=False)
    defaults = Settings(_env_file=None)
    from_example = Settings(_env_file=ENV_EXAMPLE)
    assert from_example == defaults
