"""Output must not crash on consoles with a legacy code page (e.g. cp1251/cp866 on Windows)."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable

import pytest

import producer
from app.log import JsonFormatter, configure_logging


class _KeepOpenBuffer(io.BytesIO):
    """A TextIOWrapper closes its buffer when collected; keep the bytes readable for asserts."""

    def close(self) -> None:
        pass


InstallConsole = Callable[[], Callable[[], bytes]]


@pytest.fixture
def legacy_console(monkeypatch: pytest.MonkeyPatch) -> InstallConsole:
    """Call inside the test: pytest re-installs its own sys.stdout between setup and call."""

    def install() -> Callable[[], bytes]:
        return _install(monkeypatch)

    return install


def _install(monkeypatch: pytest.MonkeyPatch) -> Callable[[], bytes]:
    buffer = _KeepOpenBuffer()
    stream = io.TextIOWrapper(buffer, encoding="cp1251", errors="strict", write_through=True)
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr("sys.stderr", stream)

    def written() -> bytes:
        stream.flush()
        return buffer.getvalue()

    return written


def test_log_line_with_unencodable_text_does_not_fail(legacy_console: InstallConsole) -> None:
    written = legacy_console()
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("INFO")
        logging.getLogger("t").warning("тело: 🚀", extra={"body": "✓"})
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
    line = written().decode("cp1251")
    assert "тело" in line  # Cyrillic stays readable
    assert "\\U0001f680" in line  # emoji escaped instead of raising


def test_json_formatter_keeps_cyrillic_and_extras() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "Кампания", None, None)
    record.call_id = "call_0001"  # what logging's extra= does
    payload = json.loads(JsonFormatter().format(record))
    assert payload["msg"] == "Кампания"
    assert payload["call_id"] == "call_0001"


def test_producer_reports_unreachable_broker_on_legacy_console(
    legacy_console: InstallConsole, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = legacy_console()
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:1/")
    assert producer.main() == 1
    assert b"failed to publish" in written()
