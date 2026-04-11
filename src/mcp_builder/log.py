"""Structlog configuration for mcp-builder.

Call configure_logging() once at startup (from CLI or test harness).
Without calling it, structlog still works with sensible defaults.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(verbose: bool = False) -> None:
    """Configure structlog for console output.

    Args:
        verbose: If True, set log level to DEBUG. Otherwise INFO.
    """
    logging.basicConfig(
        format="%(message)s",
        level=logging.DEBUG if verbose else logging.INFO,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
