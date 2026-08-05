"""Optional API-key authentication for the twin core.

Off by default so the demo stack and dashboard stay frictionless. When
``CELLTWIN_API_KEY`` is set, every ``/api/*`` route and the live WebSocket
require the key; ``/health`` stays open for liveness probes.

The guard is a pure function (:func:`is_authorized`) plus a small header/query
extractor (:func:`extract_key`), so the auth logic is unit-tested with no app,
DB, or broker. :func:`require_api_key` is the thin FastAPI dependency wiring.

Callers may present the key three ways:

* ``Authorization: Bearer <key>``
* ``X-API-Key: <key>``
* ``?api_key=<key>`` in the query string (for WebSocket clients -- browsers
  can't set custom headers on a ``WebSocket`` handshake).
"""

from __future__ import annotations

import secrets
from typing import Mapping, Optional

from fastapi import HTTPException, Request


def extract_key(
    headers: Mapping[str, str], query_params: Optional[Mapping[str, str]] = None
) -> Optional[str]:
    """Pull an API key from request headers/query, or ``None`` if absent.

    Header lookup is case-insensitive (Starlette/``requests`` headers already
    are, but a plain dict may not be, so we normalise defensively).
    """
    lower = {k.lower(): v for k, v in headers.items()}

    auth = lower.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token

    api_key = lower.get("x-api-key")
    if api_key:
        return api_key.strip()

    if query_params:
        qk = query_params.get("api_key")
        if qk:
            return qk.strip()

    return None


def is_authorized(configured: str, provided: Optional[str]) -> bool:
    """True if the request may proceed.

    An empty ``configured`` key means auth is disabled -> always allowed. When a
    key is configured, compare in constant time to avoid leaking it via timing.
    """
    if not configured:
        return True
    if not provided:
        return False
    return secrets.compare_digest(provided, configured)


def require_api_key(request: Request) -> None:
    """FastAPI dependency guarding REST routes. 401s when unauthorized."""
    settings = request.app.state.settings
    provided = extract_key(request.headers, request.query_params)
    if not is_authorized(settings.api_key, provided):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
