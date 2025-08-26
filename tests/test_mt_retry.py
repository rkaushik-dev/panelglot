import io
import json
import random
import urllib.error

import pytest

from v4t_translate.errors import ConfigError
from v4t_translate.locales import resolve
from v4t_translate.mt.http import HttpProvider, HttpProviderConfig
from v4t_translate.mt.retry import (
    RETRYABLE_STATUS,
    RateLimiter,
    RetryPolicy,
    is_retryable,
    with_retries,
)

EN = resolve("en-US")
DE = resolve("de-DE")


class Clock:
    """A monotonic clock a test drives by hand."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def http_error(code, *, retry_after=None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return urllib.error.HTTPError("http://x", code, "boom", headers, None)


def reply(texts):
    body = json.dumps({"translations": [{"text": t} for t in texts]}).encode()

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return Response(body)


def provider(opener, clock, **settings):
    config = HttpProviderConfig(name="engine", endpoint="http://x", **settings)
    return HttpProvider(config, opener=opener, sleeper=clock.sleep)


# -- what is worth retrying ---------------------------------------------


@pytest.mark.parametrize("code", sorted(RETRYABLE_STATUS))
def test_transient_statuses_are_retryable(code):
    assert is_retryable(http_error(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404, 413, 422])
def test_the_rest_are_not(code):
    assert not is_retryable(http_error(code))


def test_a_dropped_connection_is_retryable():
    assert is_retryable(urllib.error.URLError("connection reset"))


def test_a_timeout_is_retryable():
    assert is_retryable(TimeoutError())


def test_a_programming_error_is_not():
    assert not is_retryable(ValueError("bad path"))


# -- the backoff --------------------------------------------------------


def test_the_first_attempt_never_waits():
    assert RetryPolicy().delay_for(1) == 0.0


def test_the_delay_doubles():
    policy = RetryPolicy(base_delay=0.5, jitter=0)
    assert policy.delay_for(2) == 0.5
    assert policy.delay_for(3) == 1.0
    assert policy.delay_for(4) == 2.0


def test_the_delay_is_capped():
    policy = RetryPolicy(base_delay=0.5, max_delay=1.0, jitter=0)
    assert policy.delay_for(9) == 1.0


def test_jitter_moves_the_delay_both_ways():
    policy = RetryPolicy(base_delay=1.0, jitter=0.5)
    seen = {policy.delay_for(2, rng=random.Random(seed)) for seed in range(30)}
    assert min(seen) < 1.0
    assert max(seen) > 1.0


def test_jitter_never_goes_negative():
    policy = RetryPolicy(base_delay=1.0, jitter=2.0)
    assert all(policy.delay_for(2, rng=random.Random(s)) >= 0 for s in range(50))


def test_a_retry_after_header_is_read():
    assert RetryPolicy().retry_after(http_error(429, retry_after=30)) == 30.0


def test_a_missing_retry_after_is_none():
    assert RetryPolicy().retry_after(http_error(429)) is None


def test_an_http_date_retry_after_falls_back():
    error = http_error(429, retry_after="Wed, 21 Oct 2026 07:28:00 GMT")
    assert RetryPolicy().retry_after(error) is None


def test_a_non_http_failure_has_no_retry_after():
    assert RetryPolicy().retry_after(TimeoutError()) is None


# -- with_retries -------------------------------------------------------


def test_a_call_that_works_is_made_once():
    calls = []
    with_retries(lambda: calls.append(1), RetryPolicy())
    assert len(calls) == 1


def test_a_transient_failure_is_retried():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise http_error(503)
        return "done"

    clock = Clock()
    assert with_retries(flaky, RetryPolicy(), sleeper=clock.sleep) == "done"
    assert len(calls) == 3


def test_a_permanent_failure_is_not():
    calls = []

    def broken():
        calls.append(1)
        raise http_error(401)

    with pytest.raises(urllib.error.HTTPError):
        with_retries(broken, RetryPolicy())
    assert len(calls) == 1


def test_the_attempts_run_out():
    calls = []

    def always():
        calls.append(1)
        raise http_error(503)

    clock = Clock()
    with pytest.raises(urllib.error.HTTPError):
        with_retries(always, RetryPolicy(attempts=3), sleeper=clock.sleep)
    assert len(calls) == 3


def test_the_last_failure_is_what_comes_out():
    # Not a wrapper. Whoever reads the warning wants to know it was a 503.
    def always():
        raise http_error(504)

    clock = Clock()
    with pytest.raises(urllib.error.HTTPError) as caught:
        with_retries(always, RetryPolicy(attempts=2), sleeper=clock.sleep)
    assert caught.value.code == 504


def test_one_attempt_means_no_retrying():
    calls = []

    def always():
        calls.append(1)
        raise http_error(503)

    with pytest.raises(urllib.error.HTTPError):
        with_retries(always, RetryPolicy(attempts=1))
    assert len(calls) == 1


def test_the_engines_own_delay_wins_when_it_is_longer():
    def always():
        raise http_error(429, retry_after=30)

    clock = Clock()
    with pytest.raises(urllib.error.HTTPError):
        with_retries(always, RetryPolicy(attempts=2, base_delay=0.5, jitter=0),
                     sleeper=clock.sleep)
    assert clock.slept == [30.0]


def test_our_delay_wins_when_it_is_longer():
    def always():
        raise http_error(429, retry_after=0)

    clock = Clock()
    with pytest.raises(urllib.error.HTTPError):
        with_retries(always, RetryPolicy(attempts=2, base_delay=4.0, jitter=0),
                     sleeper=clock.sleep)
    assert clock.slept == [4.0]


def test_the_caller_is_told_about_each_retry():
    seen = []

    def flaky():
        if len(seen) < 2:
            raise http_error(503)
        return "done"

    clock = Clock()
    with_retries(flaky, RetryPolicy(attempts=4), sleeper=clock.sleep,
                 on_retry=lambda n, delay, exc: seen.append((n, exc.code)))
    assert [n for n, _ in seen] == [1, 2]
    assert all(code == 503 for _, code in seen)


# -- the rate limiter ---------------------------------------------------


def test_no_limit_never_waits():
    clock = Clock()
    limiter = RateLimiter(0, clock=clock, sleeper=clock.sleep)
    assert limiter.wait() == 0.0
    assert clock.slept == []


def test_the_first_call_goes_straight_through():
    clock = Clock()
    limiter = RateLimiter(2, clock=clock, sleeper=clock.sleep)
    assert limiter.wait() == 0.0


def test_the_second_call_waits_the_interval():
    clock = Clock()
    limiter = RateLimiter(2, clock=clock, sleeper=clock.sleep)
    limiter.wait()
    assert limiter.wait() == pytest.approx(0.5)


def test_a_slow_caller_is_never_delayed():
    clock = Clock()
    limiter = RateLimiter(2, clock=clock, sleeper=clock.sleep)
    limiter.wait()
    clock.now += 10
    assert limiter.wait() == 0.0


def test_the_interval_is_the_reciprocal():
    assert RateLimiter(4).interval == 0.25
    assert RateLimiter(0).interval == 0.0


def test_a_burst_is_spread_out():
    clock = Clock()
    limiter = RateLimiter(10, clock=clock, sleeper=clock.sleep)
    for _ in range(5):
        limiter.wait()
    assert len(clock.slept) == 4
    assert all(delay == pytest.approx(0.1) for delay in clock.slept)


# -- through the provider -----------------------------------------------


def test_a_batch_that_fails_once_still_lands():
    calls = []

    def opener(request, timeout=None):
        calls.append(request)
        if len(calls) == 1:
            raise http_error(503)
        return reply(["Balkenhöhe"])

    clock = Clock()
    result = provider(opener, clock).translate(["Bar Height"], EN, DE)
    assert result.texts == ["Balkenhöhe"]
    assert len(calls) == 2


def test_the_retry_is_reported_as_a_warning():
    calls = []

    def opener(request, timeout=None):
        calls.append(request)
        if len(calls) == 1:
            raise http_error(429, retry_after=1)
        return reply(["Balkenhöhe"])

    clock = Clock()
    result = provider(opener, clock).translate(["Bar Height"], EN, DE)
    assert any("retrying in" in w for w in result.warnings)


def test_a_bad_key_is_not_retried():
    calls = []

    def opener(request, timeout=None):
        calls.append(request)
        raise http_error(401)

    clock = Clock()
    result = provider(opener, clock).translate(["Bar Height"], EN, DE)
    assert len(calls) == 1
    assert result.texts == [""]


def test_a_batch_that_never_recovers_is_dropped_once():
    calls = []

    def opener(request, timeout=None):
        calls.append(request)
        raise http_error(503)

    clock = Clock()
    result = provider(opener, clock, attempts=3).translate(["a", "b"], EN, DE)
    assert len(calls) == 3
    assert result.texts == ["", ""]


def test_retrying_can_be_turned_off():
    calls = []

    def opener(request, timeout=None):
        calls.append(request)
        raise http_error(503)

    clock = Clock()
    provider(opener, clock, attempts=1).translate(["a"], EN, DE)
    assert len(calls) == 1


def test_the_rate_limit_paces_the_batches():
    def opener(request, timeout=None):
        return reply(["x"])

    clock = Clock()
    engine = provider(opener, clock, batch_size=1, requests_per_second=2)
    engine._limiter = RateLimiter(2, clock=clock, sleeper=clock.sleep)
    engine.translate(["a", "b", "c"], EN, DE)
    assert clock.slept == [pytest.approx(0.5), pytest.approx(0.5)]


def test_the_settings_are_config_fields():
    import dataclasses

    names = {f.name for f in dataclasses.fields(HttpProviderConfig)}
    assert {"attempts", "requests_per_second"} <= names


def test_an_unknown_setting_is_still_rejected():
    from pathlib import Path

    from v4t_translate.config import ProjectConfig, ProviderEntry
    from v4t_translate.locales import resolve as resolve_locale
    from v4t_translate.ops.pretranslate import build_provider

    config = ProjectConfig(name="p", root=Path("."),
                           source_locale=resolve_locale("en-US"))
    config.providers["x"] = ProviderEntry(name="x", endpoint="http://x",
                                          settings={"retries": 5})
    with pytest.raises(ConfigError, match="retries"):
        build_provider(config, "x")


def test_the_new_settings_are_accepted():
    from pathlib import Path

    from v4t_translate.config import ProjectConfig, ProviderEntry
    from v4t_translate.ops.pretranslate import build_provider

    config = ProjectConfig(name="p", root=Path("."), source_locale=EN)
    config.providers["x"] = ProviderEntry(
        name="x", endpoint="http://x",
        settings={"attempts": 5, "requests_per_second": 2.0},
    )
    built = build_provider(config, "x")
    assert built.config.attempts == 5
