"""
Retry strategy with exponential backoff for API calls.
"""
import time
import logging
from typing import Callable, TypeVar, Optional, Type
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryStrategy:
    """
    Implements exponential backoff retry logic for failed API calls.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        retryable_exceptions: Optional[tuple] = None,
        retryable_status_codes: Optional[list[int]] = None
    ):
        """
        Initialize retry strategy.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            exponential_base: Base for exponential calculation
            retryable_exceptions: Tuple of exception types to retry
            retryable_status_codes: List of HTTP status codes to retry
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

        # Default retryable exceptions
        self.retryable_exceptions = retryable_exceptions or (
            ConnectionError,
            TimeoutError,
        )

        # Default retryable status codes
        self.retryable_status_codes = retryable_status_codes or [429, 500, 503, 504]

        logger.info(
            f"RetryStrategy initialized: max_retries={max_retries}, "
            f"base_delay={base_delay}s, max_delay={max_delay}s"
        )

    def should_retry(
        self,
        exception: Exception,
        attempt: int
    ) -> bool:
        """
        Determine if an error should be retried.

        Args:
            exception: The exception that was raised
            attempt: Current attempt number (0-indexed)

        Returns:
            True if should retry, False otherwise
        """
        # Check if max retries exceeded
        if attempt >= self.max_retries:
            logger.info(f"Max retries ({self.max_retries}) exceeded")
            return False

        # Check if exception type is retryable
        if isinstance(exception, self.retryable_exceptions):
            logger.info(
                f"Retryable exception: {type(exception).__name__} (attempt {attempt + 1})"
            )
            return True

        # Check for HTTP errors with retryable status codes
        if hasattr(exception, 'status_code'):
            if exception.status_code in self.retryable_status_codes:
                logger.info(
                    f"Retryable status code: {exception.status_code} (attempt {attempt + 1})"
                )
                return True

        # Check for ElevenLabs specific errors
        if hasattr(exception, 'code'):
            if exception.code in self.retryable_status_codes:
                logger.info(
                    f"Retryable error code: {exception.code} (attempt {attempt + 1})"
                )
                return True

        logger.info(f"Non-retryable error: {type(exception).__name__}")
        return False

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay before next retry using exponential backoff.

        Formula: min(base_delay * (exponential_base ^ attempt), max_delay)

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        logger.debug(f"Calculated retry delay: {delay:.2f}s for attempt {attempt}")
        return delay

    def execute_with_retry(
        self,
        func: Callable[[], T],
        *args,
        **kwargs
    ) -> T:
        """
        Execute a function with retry logic.

        Args:
            func: Function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the function

        Raises:
            The last exception if all retries fail
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(f"Executing function (attempt {attempt + 1})")
                result = func(*args, **kwargs)

                if attempt > 0:
                    logger.info(f"Function succeeded after {attempt} retries")

                return result

            except Exception as e:
                last_exception = e

                if attempt < self.max_retries and self.should_retry(e, attempt):
                    delay = self.get_delay(attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Function failed after {attempt + 1} attempts: {e}"
                    )
                    raise

        # This should never be reached due to the raise above,
        # but included for type safety
        raise last_exception


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: Optional[tuple] = None,
    retryable_status_codes: Optional[list[int]] = None
):
    """
    Decorator for adding retry logic to a function.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential calculation
        retryable_exceptions: Tuple of exception types to retry
        retryable_status_codes: List of HTTP status codes to retry

    Returns:
        Decorated function with retry logic

    Example:
        @retry(max_retries=3, base_delay=1.0)
        def call_api():
            return client.generate_speech(...)
    """
    strategy = RetryStrategy(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        retryable_exceptions=retryable_exceptions,
        retryable_status_codes=retryable_status_codes
    )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            return strategy.execute_with_retry(func, *args, **kwargs)
        return wrapper

    return decorator


class CircuitBreaker:
    """
    Circuit breaker pattern for preventing cascading failures.

    When error rate exceeds threshold, the circuit "opens" and
    requests fail immediately without attempting the operation.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Type[Exception] = Exception
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Time in seconds before attempting recovery
            expected_exception: Exception type to catch
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half_open

        logger.info(
            f"CircuitBreaker initialized: threshold={failure_threshold}, "
            f"timeout={recovery_timeout}s"
        )

    def call(self, func: Callable[[], T]) -> T:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute

        Returns:
            Result of the function

        Raises:
            Exception: If circuit is open or function fails
        """
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half_open"
                logger.info("Circuit breaker entering half-open state")
            else:
                logger.warning("Circuit breaker is open, rejecting request")
                raise Exception("Circuit breaker is open")

        try:
            result = func()
            self._on_success()
            return result

        except self.expected_exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful execution."""
        if self.state == "half_open":
            logger.info("Circuit breaker recovered, closing circuit")
            self.state = "closed"

        self.failure_count = 0
        self.last_failure_time = None

    def _on_failure(self):
        """Handle failed execution."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures"
            )

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self.last_failure_time is None:
            return False

        return (time.time() - self.last_failure_time) >= self.recovery_timeout

    def reset(self):
        """Manually reset the circuit breaker."""
        self.state = "closed"
        self.failure_count = 0
        self.last_failure_time = None
        logger.info("Circuit breaker manually reset")
