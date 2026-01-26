"""
Structured logging configuration for ambermeta.

This module provides a centralized logging configuration for the ambermeta package,
replacing ad-hoc print statements with proper logging levels for better debugging
and production-ready output control.

Usage:
    from ambermeta.logging_config import get_logger, configure_logging

    # Configure logging (optional, default is INFO level)
    configure_logging(level="DEBUG", log_file="ambermeta.log")

    # Get a logger for your module
    logger = get_logger(__name__)
    logger.info("Processing file...")
    logger.debug("Detailed debug information")
    logger.warning("Something might be wrong")
    logger.error("An error occurred")
"""

from __future__ import annotations

import logging
import sys
from typing import Optional


# Package-wide logger name
LOGGER_NAME = "ambermeta"

# Default format strings
DEFAULT_FORMAT = "%(levelname)s: %(message)s"
VERBOSE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEBUG_FORMAT = "%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s"


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger for the specified module.

    Args:
        name: Module name (typically __name__). If None, returns the root package logger.

    Returns:
        A configured logger instance.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing started")
    """
    if name is None:
        return logging.getLogger(LOGGER_NAME)

    # Create child logger under the package namespace
    if name.startswith(LOGGER_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


def configure_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_style: str = "default",
    stream: Optional[object] = None,
) -> None:
    """
    Configure the logging system for ambermeta.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to write logs to a file
        format_style: Log format style ("default", "verbose", "debug")
        stream: Stream to write logs to (default: sys.stderr)

    Example:
        >>> configure_logging(level="DEBUG", log_file="ambermeta.log")
    """
    logger = logging.getLogger(LOGGER_NAME)

    # Clear any existing handlers
    logger.handlers.clear()

    # Set the logging level
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    # Select format string
    if format_style == "verbose":
        fmt = VERBOSE_FORMAT
    elif format_style == "debug":
        fmt = DEBUG_FORMAT
    else:
        fmt = DEFAULT_FORMAT

    formatter = logging.Formatter(fmt)

    # Add console handler
    console_handler = logging.StreamHandler(stream or sys.stderr)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(logging.Formatter(VERBOSE_FORMAT))
        logger.addHandler(file_handler)

    # Prevent propagation to root logger
    logger.propagate = False


def set_log_level(level: str) -> None:
    """
    Dynamically change the logging level.

    Args:
        level: New logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logger = logging.getLogger(LOGGER_NAME)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)
    for handler in logger.handlers:
        handler.setLevel(numeric_level)


def enable_quiet_mode() -> None:
    """Suppress all logging output except errors and critical messages."""
    set_log_level("ERROR")


def enable_verbose_mode() -> None:
    """Enable verbose logging (DEBUG level)."""
    set_log_level("DEBUG")


# Initialize default logging configuration
configure_logging()


__all__ = [
    "get_logger",
    "configure_logging",
    "set_log_level",
    "enable_quiet_mode",
    "enable_verbose_mode",
    "LOGGER_NAME",
]
