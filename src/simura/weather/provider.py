"""The provider interface every weather source implements.

A :class:`WeatherProvider` answers one question -- "what was the weather at this
instant?" -- via :meth:`at`. Keeping the contract this small means a static
constant, a synthetic model, a replayed CSV, and a live API are all
interchangeable, and any consumer depends only on the protocol, never on a
concrete source.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .sample import WeatherSample


@runtime_checkable
class WeatherProvider(Protocol):
    """Anything that can report weather at a given Unix-epoch timestamp."""

    def at(self, timestamp: float) -> WeatherSample:
        """Return the :class:`WeatherSample` for ``timestamp`` (epoch seconds)."""
        ...
