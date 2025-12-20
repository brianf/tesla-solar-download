#!/usr/bin/env python3
"""Structured logging infrastructure for Tesla solar downloads.

Provides dual-output logging:
- Console: Human-readable format for interactive use
- File: JSON lines format for machine parsing and web app analysis
"""

import json
import logging
import os
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps


class JSONFormatter(logging.Formatter):
    """Format log records as JSON lines."""

    def format(self, record):
        """Format a log record as a JSON string.

        Args:
            record: LogRecord instance

        Returns:
            str: JSON string with timestamp, level, message, and extra fields
        """
        log_data = {
            'timestamp': datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
        }

        # Add extra fields from logger.log(..., extra={...})
        if hasattr(record, 'operation'):
            for key, value in vars(record).items():
                if key not in [
                    'name',
                    'msg',
                    'args',
                    'created',
                    'filename',
                    'funcName',
                    'levelname',
                    'levelno',
                    'lineno',
                    'module',
                    'msecs',
                    'message',
                    'pathname',
                    'process',
                    'processName',
                    'relativeCreated',
                    'thread',
                    'threadName',
                    'exc_info',
                    'exc_text',
                    'stack_info',
                ]:
                    log_data[key] = value

        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Format log records for human-readable console output."""

    def format(self, record):
        """Format a log record for console display.

        Args:
            record: LogRecord instance

        Returns:
            str: Human-readable log line
        """
        # Keep console output simple and clean
        return record.getMessage()


def setup_logging(log_file=None, console_level=logging.INFO):
    """Initialize dual-output logging system.

    Args:
        log_file: Optional path to JSON log file. If None, no file logging.
        console_level: Logging level for console output (default: INFO)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything at root level

    # Remove any existing handlers
    root_logger.handlers = []

    # Console handler (human-readable)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # File handler (JSON lines)
    if log_file:
        try:
            # Create log directory if it doesn't exist
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)

            file_handler = logging.FileHandler(log_file, mode='a')
            file_handler.setLevel(logging.DEBUG)  # Log everything to file
            file_handler.setFormatter(JSONFormatter())
            root_logger.addHandler(file_handler)

            root_logger.info(
                f'Structured logging enabled to {log_file}',
                extra={'operation': 'logging_init', 'log_file': log_file},
            )
        except (IOError, OSError) as e:
            root_logger.warning(
                f'Failed to create log file {log_file}: {e}. '
                'Continuing with console-only logging.',
                extra={'operation': 'logging_init_failed', 'error': str(e)},
            )


@contextmanager
def log_operation(operation, **context):
    """Context manager for logging operations with timing.

    Args:
        operation: Name of the operation being performed
        **context: Additional context fields to include in log entries

    Yields:
        None

    Example:
        with log_operation('download_file', site_id=123, date='2025-12'):
            download_data()
    """
    logger = logging.getLogger(__name__)
    start = time.time()
    context['operation'] = operation

    try:
        yield
        duration = (time.time() - start) * 1000
        logger.info(
            f'{operation} completed',
            extra={**context, 'duration_ms': duration, 'status': 'success'},
        )
    except Exception as e:
        duration = (time.time() - start) * 1000
        logger.error(
            f'{operation} failed',
            extra={
                **context,
                'duration_ms': duration,
                'status': 'error',
                'error': str(e),
                'error_type': type(e).__name__,
                'traceback': traceback.format_exc(),
            },
        )
        raise


def retry_with_logging(tries=2, delay=5):
    """Retry decorator that logs attempts.

    Args:
        tries: Number of attempts (default: 2)
        delay: Delay between attempts in seconds (default: 5)

    Returns:
        Decorator function

    Example:
        @retry_with_logging(tries=3, delay=2)
        def download_data():
            # ... code that might fail
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(__name__)
            for attempt in range(1, tries + 1):
                try:
                    if attempt > 1:
                        logger.warning(
                            f'Retry attempt {attempt}/{tries} for {func.__name__}',
                            extra={
                                'operation': 'retry',
                                'function': func.__name__,
                                'attempt': attempt,
                                'max_attempts': tries,
                            },
                        )
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == tries:
                        logger.error(
                            f'All {tries} attempts failed for {func.__name__}',
                            extra={
                                'operation': 'retry_exhausted',
                                'function': func.__name__,
                                'attempts': tries,
                                'error': str(e),
                                'error_type': type(e).__name__,
                            },
                        )
                        raise
                    time.sleep(delay)

        return wrapper

    return decorator
