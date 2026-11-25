"""Structured JSON logging (structlog). Secrets and document text are redacted."""
import logging
import sys

import structlog

SENSITIVE_KEYS = {"password", "token", "access_token", "jwt", "secret", "authorization", "content", "text"}


def _redact(_: object, __: str, event_dict: dict) -> dict:
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):  # noqa: ANN201
    return structlog.get_logger(name)
