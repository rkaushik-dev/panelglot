"""A machine translation provider described by configuration.

Every engine anybody has asked for is the same shape: post some text to a
URL with a key in a header and read the answers out of a JSON reply. Writing
a class per vendor would mean this package tracks four vendors' API changes
forever, which is not a thing a localisation tool should be doing.

So the shape is configuration and there is one implementation. A project that
wants an engine describes it:

    [provider.deepl]
    endpoint = "https://api-free.deepl.com/v2/translate"
    auth_header = "Authorization"
    auth_prefix = "DeepL-Auth-Key "
    auth_env = "DEEPL_API_KEY"
    text_field = "text"
    target_field = "target_lang"
    target_style = "upper-language"
    response_path = "translations[].text"

The key is never in the config. It comes from the environment, named by
``auth_env``, because a config file goes in the repository and a key must not.

Standard library only. urllib is enough for a POST with a JSON body, and a
dependency on a HTTP client would be a dependency the panel build machines
have to have.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..errors import ConfigError
from ..locales import Locale
from .base import ProviderResult, protect_placeholders, restore_placeholders
from .retry import RateLimiter, RetryPolicy, with_retries

__all__ = ["HttpProviderConfig", "HttpProvider", "target_code", "extract_path"]

#: How a vendor wants a language named. Every one of them is different and
#: none of them takes a BCP-47 tag.
TARGET_STYLES = {
    "tag": lambda locale: locale.tag,
    "language": lambda locale: locale.language,
    "upper-language": lambda locale: locale.language.upper(),
    "upper-tag": lambda locale: locale.tag.upper(),
    "underscore": lambda locale: locale.tag.replace("-", "_"),
}


def target_code(locale: Locale, style: str) -> str:
    """The language code this engine wants."""
    render = TARGET_STYLES.get(style)
    if render is None:
        raise ConfigError(
            f"unknown target_style {style!r}. Known: {', '.join(sorted(TARGET_STYLES))}"
        )
    return render(locale)


@dataclass
class HttpProviderConfig:
    """Everything needed to talk to one engine."""

    name: str
    endpoint: str

    text_field: str = "text"
    source_field: str = ""
    target_field: str = "target"
    target_style: str = "tag"

    auth_header: str = ""
    auth_prefix: str = ""
    auth_env: str = ""

    response_path: str = "translations[].text"
    batch_size: int = 50
    timeout: float = 20.0
    extra: dict[str, Any] = field(default_factory=dict)
    """Fields sent with every request, for the ones that want a model name."""

    attempts: int = 3
    """Tries per batch, including the first. 1 turns retrying off."""

    requests_per_second: float = 0.0
    """Ceiling on the request rate. 0 means no limit.

    Set it below whatever the plan allows. The free DeepL tier answers 429
    above a handful a second, and the point of this is never to see one.
    """

    def retry_policy(self) -> RetryPolicy:
        return RetryPolicy(attempts=max(1, self.attempts))

    def token(self) -> str:
        """The key, out of the environment. Never out of the config."""
        if not self.auth_env:
            return ""
        value = os.environ.get(self.auth_env, "")
        if not value:
            raise ConfigError(
                f"{self.name} needs {self.auth_env} in the environment and it is "
                f"not set"
            )
        return value


def extract_path(payload: Any, path: str) -> list[str]:
    """Pull the translations out of a reply, following a dotted path.

    ``translations[].text`` means "the text field of every item in the
    translations list". One notation, because the four engines anybody has
    asked about all reply in that shape and a full query language here would
    be a second thing to learn.
    """
    current: Any = payload

    for part in path.split("."):
        if part.endswith("[]"):
            key = part[:-2]
            current = current.get(key) if isinstance(current, dict) else current
            if not isinstance(current, list):
                raise ConfigError(f"the reply has no list at {key!r}")
            continue

        if isinstance(current, list):
            current = [item.get(part) if isinstance(item, dict) else None
                       for item in current]
            continue

        if not isinstance(current, dict) or part not in current:
            raise ConfigError(f"the reply has no {part!r}")
        current = current[part]

    if isinstance(current, str):
        return [current]
    if isinstance(current, list):
        return [item if isinstance(item, str) else "" for item in current]
    raise ConfigError(f"the reply at {path!r} is not text")


class HttpProvider:
    """Talks to whatever the configuration describes."""

    def __init__(self, config: HttpProviderConfig, *, opener=None,
                 sleeper=None) -> None:
        self.config = config
        self.name = config.name
        # Injected so the tests never touch a network, and never wait. A
        # provider that can only be tested against a live endpoint is a
        # provider nobody tests, and one that sleeps for real turns a retry
        # test into a slow one.
        self._opener = opener or urllib.request.urlopen
        self._sleeper = sleeper
        self._limiter = RateLimiter(config.requests_per_second, sleeper=sleeper)

    def translate(self, texts: list[str], source: Locale,
                  target: Locale) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        if not texts:
            return result

        # Resolved once, up front, so a missing key raises rather than
        # arriving as a warning on every batch. A key that is not set is
        # something to fix, not a transient failure to work around.
        headers = self._headers()
        policy = self.config.retry_policy()

        for batch in _batched(texts, self.config.batch_size):
            protected: list[tuple[str, list[str]]] = [
                protect_placeholders(text) for text in batch
            ]
            sent = [text for text, _ in protected]

            def attempt(sent: list[str] = sent) -> list[str]:
                return self._call(sent, source, target, headers)

            try:
                answers = with_retries(
                    attempt, policy,
                    limiter=self._limiter,
                    sleeper=self._sleeper,
                    on_retry=lambda n, delay, exc: result.warnings.append(
                        f"{self.name}: {exc}, retrying in {delay:.1f}s "
                        f"(attempt {n} of {policy.attempts})"
                    ),
                )
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                result.warnings.append(f"{self.name}: {exc}")
                result.texts.extend([""] * len(batch))
                continue
            except (ConfigError, json.JSONDecodeError) as exc:
                result.warnings.append(f"{self.name}: unreadable reply, {exc}")
                result.texts.extend([""] * len(batch))
                continue

            if len(answers) != len(batch):
                result.warnings.append(
                    f"{self.name} answered {len(answers)} of {len(batch)}, so the "
                    f"batch was dropped"
                )
                result.texts.extend([""] * len(batch))
                continue

            for answer, (_, placeholders) in zip(answers, protected, strict=True):
                result.texts.append(
                    restore_placeholders(answer, placeholders) if answer else ""
                )

        return result

    def _call(self, texts: list[str], source: Locale, target: Locale,
              headers: dict[str, str]) -> list[str]:
        config = self.config

        body: dict[str, Any] = dict(config.extra)
        body[config.text_field] = texts
        body[config.target_field] = target_code(target, config.target_style)
        if config.source_field:
            body[config.source_field] = target_code(source, config.target_style)

        request = urllib.request.Request(
            config.endpoint,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )

        with self._opener(request, timeout=config.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

        return extract_path(payload, config.response_path)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "v4t-translate",
        }
        token = self.config.token()
        if token and self.config.auth_header:
            headers[self.config.auth_header] = f"{self.config.auth_prefix}{token}"
        return headers


def _batched(items: list[str], size: int):
    step = max(1, size)
    for start in range(0, len(items), step):
        yield items[start : start + step]
