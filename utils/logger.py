"""Structured logging setup using loguru."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_CONFIGURED = False


def setup_logging(level: str = "INFO", log_dir: str | Path | None = "logs") -> None:
    """Configure loguru sinks once (stdout + rotating file)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logger.remove()
    logger.add(
        sys.stdout,
        level=level.upper(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )

    if log_dir:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        logger.add(
            path / "agentic-workflow_{time:YYYY-MM-DD}.log",
            level=level.upper(),
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            enqueue=True,
        )

    _CONFIGURED = True


# Eager default so `from utils.logger import logger` always works
try:
    from config.settings import get_settings

    setup_logging(get_settings().log_level)
except Exception:
    setup_logging("INFO")

__all__ = ["logger", "setup_logging"]
