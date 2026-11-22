import json
import logging

from app.logging_setup import JsonFormatter


def test_json_formatter_includes_extra_fields() -> None:
    record = logging.LogRecord("app.llm", logging.INFO, __file__, 1, "llm call", None, None)
    record.model = "gemini-x"
    record.latency_ms = 120
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "llm call"
    assert line["level"] == "INFO"
    assert line["logger"] == "app.llm"
    assert (line["model"], line["latency_ms"]) == ("gemini-x", 120)
    assert "time" in line
