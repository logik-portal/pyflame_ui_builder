"""Logging helpers for PyFlame UI Builder."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOGGER_NAME = 'pyflame_builder'
_LOG_FORMAT = '%(asctime)s | %(levelname)s | %(message)s'


def get_bootstrap_logger() -> logging.Logger:
    """Return stdout-only logger for early bootstrap/import messages."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
    return logger


def init_logging(base_dir: str) -> logging.Logger:
    """Initialize file + stdout logging handlers and return app logger."""
    log_dir = os.path.join(base_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'pyflame_builder.log')

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT)

    has_file = any(isinstance(h, RotatingFileHandler) for h in logger.handlers)
    has_stdout = any(
        isinstance(h, logging.StreamHandler) and getattr(h, 'stream', None) is sys.stdout
        for h in logger.handlers
    )

    if not has_file:
        try:
            file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as exc:
            # Never fail app startup because file logging is unavailable.
            # Keep stdout logging active and emit a one-line warning there.
            if not has_stdout:
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setFormatter(formatter)
                logger.addHandler(console_handler)
                has_stdout = True
            logger.warning('File logging disabled (%s): %s', log_path, exc)

    if not has_stdout:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
