"""Structured console/file logging plus asynchronous dashboard batch logging.

Keep JSON logging and use rolling file rotation so earlier log records remain
available after the active log reaches its size limit.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

import requests


STANDARD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
}

DEFAULT_ENDPOINT = "https://vuoaqongkzlzhowuajvl.supabase.co/functions/v1/log-receiver"


@dataclass(frozen=True)
class LoggerConfig:
    """Configuration for the application logger and dashboard receiver."""

    log_file: str = "logs/integration.log"
    integration_name: Optional[str] = "MrPlant FEEDJetshop"
    log_level: str = "INFO"
    log_format: Optional[str] = None
    log_datefmt: str = "%Y-%m-%d %H:%M:%S"
    console: bool = True
    logger_name: str = "feed_jetshop"
    rotation_mode: str = "size"
    rotate_when: str = "midnight"
    backup_count: int = 14
    max_bytes: int = 100 * 1024 * 1024
    endpoint: str = DEFAULT_ENDPOINT
    api_key_env: str = "LOG_RECEIVER_API_KEY"
    batch_size: int = 50
    flush_interval: float = 2.0
    request_timeout: float = 10.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def load_logger_config(overrides: Optional[dict] = None) -> LoggerConfig:
    """Load logger settings from the current environment, with optional overrides."""

    defaults = LoggerConfig()
    integration_name = os.getenv("INTEGRATION_NAME", defaults.integration_name or "").strip()
    cfg = LoggerConfig(
        logger_name=os.getenv("LOGGER_NAME", defaults.logger_name),
        log_level=os.getenv("LOG_LEVEL", defaults.log_level),
        log_file=os.getenv("LOG_FILE", defaults.log_file),
        log_format=os.getenv("LOG_FORMAT") or defaults.log_format,
        log_datefmt=os.getenv("LOG_DATEFMT", defaults.log_datefmt),
        console=_env_bool("LOG_CONSOLE", defaults.console),
        rotation_mode=os.getenv("LOG_ROTATION_MODE", defaults.rotation_mode).strip().lower(),
        rotate_when=os.getenv("LOG_ROTATE_WHEN", defaults.rotate_when),
        backup_count=_env_int("LOG_BACKUP_COUNT", defaults.backup_count),
        max_bytes=_env_int("LOG_MAX_BYTES", defaults.max_bytes),
        integration_name=integration_name or None,
        endpoint=os.getenv("LOG_ENDPOINT", defaults.endpoint),
        api_key_env=os.getenv("LOG_RECEIVER_API_KEY_ENV", defaults.api_key_env),
        batch_size=max(1, _env_int("LOG_BATCH_SIZE", defaults.batch_size)),
        flush_interval=max(0.1, _env_float("LOG_FLUSH_INTERVAL", defaults.flush_interval)),
        request_timeout=max(0.1, _env_float("LOG_REQUEST_TIMEOUT", defaults.request_timeout)),
    )
    if not overrides:
        return cfg

    values = cfg.__dict__.copy()
    values.update({key: value for key, value in overrides.items() if key in values})
    return LoggerConfig(**values)


# Compatibility with the name used by the dashboard logger reference snippet.
load_config = load_logger_config


class JsonFormatter(logging.Formatter):
    """The existing structured log format, retained for console and file output."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).astimezone().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        extras = {
            key: value for key, value in record.__dict__.items() if key not in STANDARD_ATTRS
        }
        payload.update(extras)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True, default=_json_default)


class TruncatingFileHandler(logging.FileHandler):
    """File handler that retains the newest content within a size limit."""

    def __init__(self, filename: str | Path, max_bytes: int) -> None:
        super().__init__(filename, mode="a", encoding="utf-8", delay=False)
        self.max_bytes = max_bytes

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        try:
            self._truncate_if_needed()
        except Exception:
            self.handleError(record)

    def _truncate_if_needed(self) -> None:
        if self.max_bytes <= 0:
            return

        try:
            self.stream.flush()
            size = os.path.getsize(self.baseFilename)
        except OSError:
            return
        if size <= self.max_bytes:
            return

        try:
            with open(self.baseFilename, "rb+") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                if size <= self.max_bytes:
                    return
                handle.seek(max(0, size - self.max_bytes))
                data = handle.read()
                newline_index = data.find(b"\n")
                if newline_index != -1:
                    data = data[newline_index + 1 :]
                handle.seek(0)
                handle.write(data)
                handle.truncate()
        except OSError:
            return


class DashboardBatchHandler(logging.Handler):
    """Buffer dashboard entries and send them on a dedicated worker thread."""

    def __init__(
        self,
        endpoint: str,
        integration_name: str,
        *,
        run_id: Optional[str] = None,
        batch_size: int = 50,
        flush_interval: float = 2.0,
        api_key_env: str = "LOG_RECEIVER_API_KEY",
        request_timeout: float = 10.0,
    ) -> None:
        super().__init__()
        self.endpoint = endpoint
        self.integration_name = integration_name
        self.run_id = run_id or str(uuid.uuid4())
        self.batch_size = max(1, batch_size)
        self.flush_interval = max(0.1, flush_interval)
        self.api_key_env = api_key_env
        self.request_timeout = max(0.1, request_timeout)
        self._buffer: list[dict[str, Any]] = []
        self._condition = threading.Condition()
        self._last_flush = time.monotonic()
        self._flush_requested = False
        self._stopping = False
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="dashboard-log-sender",
            daemon=True,
        )
        self._worker.start()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "integration_name": self.integration_name,
                "level": record.levelname.lower(),
                "message": record.getMessage(),
                "run_id": self.run_id,
                "timestamp": int(time.time() * 1000),
            }
            with self._condition:
                if self._stopping:
                    return
                self._buffer.append(entry)
                if len(self._buffer) >= self.batch_size:
                    self._condition.notify()
        except Exception:
            # Dashboard availability must never interrupt the integration.
            pass

    def _worker_loop(self) -> None:
        while True:
            batch: list[dict[str, Any]] = []
            with self._condition:
                while not self._stopping and not self._flush_requested:
                    elapsed = time.monotonic() - self._last_flush
                    if len(self._buffer) >= self.batch_size or elapsed >= self.flush_interval:
                        break
                    self._condition.wait(self.flush_interval - elapsed)

                if self._buffer and (
                    self._stopping
                    or self._flush_requested
                    or len(self._buffer) >= self.batch_size
                    or time.monotonic() - self._last_flush >= self.flush_interval
                ):
                    take = len(self._buffer) if self._stopping else self.batch_size
                    batch = self._buffer[:take]
                    del self._buffer[:take]
                    self._last_flush = time.monotonic()
                    self._flush_requested = False
                elif self._stopping:
                    return

            if batch:
                self._send(batch)

    def _send(self, batch: list[dict[str, Any]]) -> None:
        try:
            api_key = os.getenv(self.api_key_env, "")
            headers = {"x-api-key": api_key} if api_key else {}
            response = requests.post(
                self.endpoint,
                json=batch,
                headers=headers,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
        except Exception:
            # Do not log API failures through this handler (that would recurse).
            pass

    def flush(self) -> None:
        with self._condition:
            if self._buffer:
                self._flush_requested = True
                self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        if threading.current_thread() is not self._worker and self._worker.is_alive():
            self._worker.join(timeout=self.request_timeout + 0.5)
        super().close()


def _build_file_handler(
    cfg: LoggerConfig, level: int, formatter: logging.Formatter
) -> logging.Handler:
    path = Path(cfg.log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = (cfg.rotation_mode or "truncate").lower()
    if mode == "none":
        handler: logging.Handler = logging.FileHandler(path, encoding="utf-8")
    elif mode == "time":
        handler = TimedRotatingFileHandler(
            path,
            when=cfg.rotate_when,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
    elif mode == "size":
        handler = RotatingFileHandler(
            path,
            maxBytes=cfg.max_bytes,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
    elif mode == "truncate":
        # Available only when explicitly configured for newest-content retention.
        handler = TruncatingFileHandler(path, max_bytes=cfg.max_bytes)
    else:
        raise ValueError(f"Unsupported log rotation mode: {cfg.rotation_mode!r}")
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


class MergeExtraAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        merged = dict(self.extra)
        merged.update(extra)
        kwargs["extra"] = merged
        return msg, kwargs


def setup_logger(
    config: Optional[LoggerConfig] = None,
    *,
    run_id: Optional[str] = None,
) -> logging.Logger:
    """Configure the canonical logger once, preserving the existing import API."""

    cfg = config or load_logger_config()
    logger = logging.getLogger(cfg.logger_name) if cfg.logger_name else logging.getLogger()
    level = getattr(logging, (cfg.log_level or "INFO").upper(), logging.INFO)

    if getattr(logger, "_configured_by_logger_setup", False):
        logger.setLevel(level)
        for handler in logger.handlers:
            if isinstance(handler, DashboardBatchHandler) and run_id:
                handler.run_id = run_id
        return logger

    logger.setLevel(level)
    logger.propagate = False
    formatter: logging.Formatter
    if cfg.log_format:
        formatter = logging.Formatter(cfg.log_format, datefmt=cfg.log_datefmt)
    else:
        formatter = JsonFormatter()

    logger.handlers.clear()
    logger.addHandler(_build_file_handler(cfg, level, formatter))

    if cfg.console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if cfg.integration_name:
        dashboard_handler = DashboardBatchHandler(
            cfg.endpoint,
            cfg.integration_name,
            run_id=run_id,
            batch_size=cfg.batch_size,
            flush_interval=cfg.flush_interval,
            api_key_env=cfg.api_key_env,
            request_timeout=cfg.request_timeout,
        )
        dashboard_handler.setLevel(level)
        logger.addHandler(dashboard_handler)
        atexit.register(dashboard_handler.close)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    setattr(logger, "_configured_by_logger_setup", True)
    return logger


def setup_logging(log_file: str, level: str, run_id: str) -> logging.LoggerAdapter:
    """Compatibility entrypoint used by the existing FEED/Jetshop code."""

    config = load_logger_config(
        {
            "log_file": log_file,
            "log_level": level,
            "logger_name": "feed_jetshop",
        }
    )
    logger = setup_logger(config, run_id=run_id)
    return MergeExtraAdapter(logger, {"runId": run_id})
