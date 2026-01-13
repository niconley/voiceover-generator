"""
Logging configuration and utilities.
"""
import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    log_format: Optional[str] = None,
    log_to_console: bool = True,
    log_to_file: bool = True
) -> logging.Logger:
    """
    Set up logging configuration.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file
        log_format: Custom log format string
        log_to_console: Whether to log to console
        log_to_file: Whether to log to file

    Returns:
        Configured root logger
    """
    # Default format
    if log_format is None:
        log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

    date_format = "%Y-%m-%d %H:%M:%S"

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # Console handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler
    if log_to_file and log_file:
        # Ensure log directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    root_logger.info(f"Logging initialized: level={log_level}, file={log_file}")

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class ProgressLogger:
    """
    Logger for tracking progress of batch operations.
    """

    def __init__(
        self,
        total_items: int,
        logger: Optional[logging.Logger] = None,
        log_interval: int = 10
    ):
        """
        Initialize progress logger.

        Args:
            total_items: Total number of items to process
            logger: Logger instance (creates new if None)
            log_interval: Log progress every N items
        """
        self.total_items = total_items
        self.processed_items = 0
        self.successful_items = 0
        self.failed_items = 0
        self.logger = logger or logging.getLogger(__name__)
        self.log_interval = log_interval
        self.start_time = datetime.now()

    def log_progress(self, success: bool = True, item_name: str = ""):
        """
        Log progress for one item.

        Args:
            success: Whether the item was processed successfully
            item_name: Name of the item for logging
        """
        self.processed_items += 1

        if success:
            self.successful_items += 1
        else:
            self.failed_items += 1

        # Log at intervals or on completion
        if (
            self.processed_items % self.log_interval == 0
            or self.processed_items == self.total_items
        ):
            self._log_status(item_name)

    def _log_status(self, current_item: str = ""):
        """Log current status."""
        percent = (self.processed_items / self.total_items) * 100
        elapsed = (datetime.now() - self.start_time).total_seconds()
        rate = self.processed_items / elapsed if elapsed > 0 else 0

        eta_seconds = (
            (self.total_items - self.processed_items) / rate
            if rate > 0
            else 0
        )

        self.logger.info(
            f"Progress: {self.processed_items}/{self.total_items} ({percent:.1f}%) | "
            f"Success: {self.successful_items} | "
            f"Failed: {self.failed_items} | "
            f"Rate: {rate:.1f} items/s | "
            f"ETA: {eta_seconds:.0f}s"
            + (f" | Current: {current_item}" if current_item else "")
        )

    def get_summary(self) -> str:
        """
        Get summary of progress.

        Returns:
            Summary string
        """
        elapsed = (datetime.now() - self.start_time).total_seconds()
        rate = self.processed_items / elapsed if elapsed > 0 else 0

        return (
            f"Completed {self.processed_items}/{self.total_items} items "
            f"({self.successful_items} successful, {self.failed_items} failed) "
            f"in {elapsed:.1f}s (avg {rate:.1f} items/s)"
        )


class LogCapture:
    """
    Context manager for capturing log messages.
    """

    def __init__(self, logger: Optional[logging.Logger] = None, level: int = logging.INFO):
        """
        Initialize log capture.

        Args:
            logger: Logger to capture (root logger if None)
            level: Minimum level to capture
        """
        self.logger = logger or logging.getLogger()
        self.level = level
        self.handler = None
        self.messages = []

    def __enter__(self):
        """Start capturing logs."""
        self.handler = LogListHandler(self.messages)
        self.handler.setLevel(self.level)
        self.logger.addHandler(self.handler)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop capturing logs."""
        if self.handler:
            self.logger.removeHandler(self.handler)

    def get_messages(self) -> list:
        """Get captured messages."""
        return self.messages


class LogListHandler(logging.Handler):
    """
    Handler that stores log records in a list.
    """

    def __init__(self, message_list: list):
        """
        Initialize handler.

        Args:
            message_list: List to store messages in
        """
        super().__init__()
        self.message_list = message_list

    def emit(self, record: logging.LogRecord):
        """Store log record."""
        self.message_list.append({
            'level': record.levelname,
            'message': record.getMessage(),
            'timestamp': datetime.fromtimestamp(record.created),
            'logger': record.name
        })


def log_function_call(logger: Optional[logging.Logger] = None):
    """
    Decorator to log function calls.

    Args:
        logger: Logger instance (creates new if None)

    Example:
        @log_function_call()
        def my_function(arg1, arg2):
            return result
    """
    def decorator(func):
        nonlocal logger
        if logger is None:
            logger = logging.getLogger(func.__module__)

        def wrapper(*args, **kwargs):
            logger.debug(
                f"Calling {func.__name__}("
                f"args={args}, kwargs={kwargs})"
            )
            try:
                result = func(*args, **kwargs)
                logger.debug(f"{func.__name__} completed successfully")
                return result
            except Exception as e:
                logger.error(f"{func.__name__} failed: {e}")
                raise

        return wrapper
    return decorator


def log_exceptions(logger: Optional[logging.Logger] = None):
    """
    Decorator to log exceptions.

    Args:
        logger: Logger instance (creates new if None)

    Example:
        @log_exceptions()
        def my_function():
            raise ValueError("error")
    """
    def decorator(func):
        nonlocal logger
        if logger is None:
            logger = logging.getLogger(func.__module__)

        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.exception(
                    f"Exception in {func.__name__}: {e}",
                    exc_info=True
                )
                raise

        return wrapper
    return decorator
