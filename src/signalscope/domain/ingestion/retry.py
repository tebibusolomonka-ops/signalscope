from dataclasses import dataclass

from signalscope.domain.ingestion.errors import FetchError

# Rate limits and gateway problems usually pass. Other statuses mean the request
# itself is wrong, so trying again gives the same answer.
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})

# Bigger exponents only matter after the delay has hit its cap.
MAX_EXPONENT = 32


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many times a failed ingestion is tried, and how long to wait in between.

    Attempts are numbered from 1. After failed attempt n the wait is
    base_delay_seconds * 2 ** (n - 1), capped at max_delay_seconds.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must not be negative")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must not be smaller than base_delay_seconds")

    def allows_retry_after(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def delay_after(self, attempt: int) -> float:
        """Seconds to wait after the given failed attempt before the next one."""
        if attempt < 1:
            raise ValueError("attempt numbers start at 1")
        exponent = min(attempt - 1, MAX_EXPONENT)
        return float(min(self.base_delay_seconds * 2**exponent, self.max_delay_seconds))


def is_retryable(error: BaseException) -> bool:
    """Whether a failed ingestion attempt is likely to work when tried again."""
    if isinstance(error, FetchError):
        return error.network_error or error.status_code in RETRYABLE_STATUS_CODES
    return False
