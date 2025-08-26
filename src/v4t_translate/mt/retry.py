"""Backing off, and not hammering an engine we are paying for.

A pretranslate run posts several thousand strings in batches of fifty. Two
things go wrong at that size and neither of them is a bug in the request.

The engine rate limits. DeepL free allows a handful of requests a second and
answers 429 above that, and the first version of this treated a 429 like any
other failure: it dropped the batch, wrote an empty translation, and carried
straight on into the next 429. A run against a two thousand string catalog
came back eleven percent translated and looked like the engine was broken.

Or the engine has a bad minute. A 502 from a load balancer means try again in
a second, and dropping fifty strings for it costs a round trip through a
translator who then has to be told which fifty.

So: retry the failures that are worth retrying, back off with jitter, and
never retry the ones that are not. A 401 will be a 401 the third time as well,
and hammering an endpoint with a bad key is how a key gets suspended.

Jitter matters more than it looks. Two build machines starting the same
project at the same time back off in lockstep without it, and arrive together
at every retry.
"""

from __future__ import annotations

import random
import time
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

__all__ = [
    "RetryPolicy",
    "RateLimiter",
    "with_retries",
    "is_retryable",
    "RETRYABLE_STATUS",
]

T = TypeVar("T")

#: Statuses worth trying again. 429 is the rate limit, the 5xx are the
#: engine having a bad minute, and 408 is its own timeout.
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


def is_retryable(error: BaseException) -> bool:
    """Whether this failure is worth another attempt.

    A timeout or a dropped connection always is. An HTTP status is only when
    it is one of the transient ones: a 401 will be a 401 the third time too,
    and retrying it is how a key gets suspended.
    """
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRYABLE_STATUS
    return isinstance(error, urllib.error.URLError | TimeoutError | OSError)


@dataclass(frozen=True)
class RetryPolicy:
    """How hard to try, and how long to wait between goes."""

    attempts: int = 3
    """Total attempts including the first. 1 means no retrying."""

    base_delay: float = 0.5
    max_delay: float = 8.0

    jitter: float = 0.25
    """Fraction of the delay to randomise, up and down."""

    def delay_for(self, attempt: int, *, rng: random.Random | None = None) -> float:
        """How long to wait before attempt number ``attempt``, one-based.

        Doubling, capped, then jittered. Two build machines that started the
        same project at the same moment back off in lockstep without the
        jitter and arrive together at every retry.
        """
        if attempt < 2:
            return 0.0

        plain = min(self.base_delay * (2 ** (attempt - 2)), self.max_delay)
        if not self.jitter:
            return plain

        spread = plain * self.jitter
        source = rng or random
        return max(0.0, plain + source.uniform(-spread, spread))

    def retry_after(self, error: BaseException) -> float | None:
        """The engine's own Retry-After, in seconds, when it sent one.

        Honoured over our own backoff whenever it is longer. An engine that
        says wait thirty seconds means it, and arriving early just spends
        another request on another 429.
        """
        if not isinstance(error, urllib.error.HTTPError):
            return None

        header = error.headers.get("Retry-After") if error.headers else None
        if not header:
            return None

        try:
            seconds = float(str(header).strip())
        except ValueError:
            # The header also allows an HTTP date. Nobody we talk to sends
            # one, and guessing at a date format here would be worse than
            # falling back on our own backoff.
            return None

        return max(0.0, seconds)


class RateLimiter:
    """Keeps requests to a rate the engine will accept.

    A minimum gap between calls rather than a token bucket. The bucket lets a
    burst through, which is exactly what produces the first 429 of a run, and
    the whole point here is to never see one.
    """

    def __init__(self, per_second: float = 0.0, *,
                 clock: Callable[[], float] | None = None,
                 sleeper: Callable[[float], None] | None = None) -> None:
        self.per_second = per_second
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._last: float | None = None

    @property
    def interval(self) -> float:
        return 1.0 / self.per_second if self.per_second > 0 else 0.0

    def wait(self) -> float:
        """Block until the next call is allowed. Returns how long that took."""
        if self.interval <= 0:
            return 0.0

        now = self._clock()
        if self._last is None:
            self._last = now
            return 0.0

        due = self._last + self.interval
        delay = due - now

        if delay > 0:
            self._sleep(delay)
            self._last = due
            return delay

        self._last = now
        return 0.0


def with_retries(call: Callable[[], T], policy: RetryPolicy, *,
                 limiter: RateLimiter | None = None,
                 sleeper: Callable[[float], None] | None = None,
                 on_retry: Callable[[int, float, BaseException], None] | None = None,
                 rng: random.Random | None = None) -> T:
    """Run ``call``, retrying the failures that are worth retrying.

    The last exception is raised when the attempts run out, not a wrapper
    around it. Whoever is reading the warning wants to know it was a 503, and
    a RetriesExhausted in front of that just makes them dig.
    """
    sleep = sleeper or time.sleep
    last: BaseException | None = None

    for attempt in range(1, max(1, policy.attempts) + 1):
        if limiter is not None:
            limiter.wait()

        try:
            return call()
        except BaseException as exc:
            if not is_retryable(exc) or attempt >= policy.attempts:
                raise

            last = exc
            delay = max(
                policy.delay_for(attempt + 1, rng=rng),
                policy.retry_after(exc) or 0.0,
            )

            if on_retry is not None:
                on_retry(attempt, delay, exc)
            if delay:
                sleep(delay)

    # Unreachable: the loop either returns or raises. Kept so a future edit
    # that changes the loop bounds fails loudly rather than returning None.
    raise last if last is not None else RuntimeError("no attempts were made")
