"""Resilience wrapper: cache samples and never let a bad fetch crash the caller.

A live provider should not be queried once per simulation step (that would hammer
the API), nor should a transient network error take down a long-running twin.
:class:`CachedProvider` wraps any provider, memoises by a coarse time bucket, and
on *any* error from the inner provider falls back to an offline provider (a
:class:`~simura.weather.providers.synthetic.SyntheticProvider` by default) so
``at`` always returns something usable.
"""

from __future__ import annotations

import logging

from .provider import WeatherProvider
from .providers.synthetic import SyntheticProvider
from .sample import WeatherSample

log = logging.getLogger("simura.weather")


class CachedProvider:
    """Bucketed cache + offline fallback around any :class:`WeatherProvider`."""

    def __init__(
        self,
        inner: WeatherProvider,
        bucket_s: float = 600.0,
        fallback: WeatherProvider | None = None,
    ) -> None:
        self.inner = inner
        self.bucket_s = max(1.0, bucket_s)
        self.fallback = fallback or SyntheticProvider()
        self._cache: dict[int, WeatherSample] = {}
        self._degraded = False

    def at(self, timestamp: float) -> WeatherSample:
        key = int(timestamp // self.bucket_s)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            sample = self.inner.at(timestamp)
            self._degraded = False
        except Exception as exc:  # any failure -> stay up on the fallback
            if not self._degraded:
                log.warning("weather provider failed (%s); using offline fallback", exc)
                self._degraded = True
            sample = self.fallback.at(timestamp)
        self._cache[key] = sample
        return sample

    @property
    def degraded(self) -> bool:
        """True if the last inner fetch failed and the fallback is in use."""
        return self._degraded
