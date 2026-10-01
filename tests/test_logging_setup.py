import json
import logging
import threading
from datetime import datetime, timezone

from src.logging_setup import (
    DashboardBatchHandler,
    JsonFormatter,
    LoggerConfig,
    MergeExtraAdapter,
    TruncatingFileHandler,
    setup_logger,
)


def test_json_formatter_includes_extras():
    formatter = JsonFormatter()
    record = logging.LogRecord("test", logging.INFO, __file__, 10, "hello", args=(), exc_info=None)
    record.runId = "run-123"
    record.productNo = "Pelle-1092-10"

    payload = json.loads(formatter.format(record))
    assert payload["message"] == "hello"
    assert payload["runId"] == "run-123"
    assert payload["productNo"] == "Pelle-1092-10"


def test_merge_extra_adapter_merges_extras():
    logger = logging.getLogger("test_merge_extra")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)

    class CaptureHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

    handler = CaptureHandler()
    logger.addHandler(handler)

    adapter = MergeExtraAdapter(logger, {"runId": "run-1"})
    adapter.info("hello", extra={"event": "test"})

    assert handler.records
    payload = json.loads(JsonFormatter().format(handler.records[0]))
    assert payload["runId"] == "run-1"
    assert payload["event"] == "test"


def test_json_formatter_serializes_datetime():
    formatter = JsonFormatter()
    record = logging.LogRecord("test", logging.INFO, __file__, 10, "hello", args=(), exc_info=None)
    record.startTime = datetime(2026, 1, 16, 7, 30, 0, tzinfo=timezone.utc)

    payload = json.loads(formatter.format(record))
    assert payload["startTime"] == "2026-01-16T07:30:00+00:00"


def test_truncating_file_handler_limits_size(tmp_path):
    log_path = tmp_path / "test.log"
    handler = TruncatingFileHandler(log_path, max_bytes=400)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("test_truncate")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    for _ in range(100):
        logger.info("x" * 50)

    handler.flush()
    assert log_path.stat().st_size <= 400


def test_dashboard_batch_handler_posts_in_background_with_api_key(monkeypatch):
    sent = {}
    completed = threading.Event()

    class Response:
        def raise_for_status(self):
            pass

    def fake_post(endpoint, *, json, headers, timeout):
        sent.update(endpoint=endpoint, batch=json, headers=headers, timeout=timeout)
        completed.set()
        return Response()

    monkeypatch.setenv("TEST_DASHBOARD_API_KEY", "test-api-key")
    monkeypatch.setattr("src.logging_setup.requests.post", fake_post)
    handler = DashboardBatchHandler(
        "https://example.test/log-receiver",
        "test-integration",
        run_id="run-123",
        batch_size=2,
        flush_interval=30,
        api_key_env="TEST_DASHBOARD_API_KEY",
        request_timeout=3,
    )
    handler.emit(logging.LogRecord("test", logging.INFO, __file__, 10, "first", (), None))
    handler.emit(logging.LogRecord("test", logging.WARNING, __file__, 11, "second", (), None))

    assert completed.wait(2)
    handler.close()

    assert sent["endpoint"] == "https://example.test/log-receiver"
    assert sent["headers"] == {"x-api-key": "test-api-key"}
    assert sent["timeout"] == 3
    assert [entry["message"] for entry in sent["batch"]] == ["first", "second"]
    assert all(entry["integration_name"] == "test-integration" for entry in sent["batch"])
    assert all(entry["run_id"] == "run-123" for entry in sent["batch"])


def test_setup_logger_does_not_add_duplicate_handlers(tmp_path):
    logger_name = "test_setup_logger_idempotent"
    config = LoggerConfig(
        logger_name=logger_name,
        log_file=str(tmp_path / "idempotent.log"),
        integration_name=None,
        console=False,
    )

    logger = setup_logger(config)
    initial_handler_count = len(logger.handlers)
    again = setup_logger(config)

    assert again is logger
    assert initial_handler_count == 1
    assert len(logger.handlers) == initial_handler_count
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
