"""Tests for the optional API-key guard (pure functions + the dependency).

Auth is off by default (empty configured key), and when on, accepts the key via
Bearer header, ``X-API-Key``, or an ``?api_key=`` query param. All checked here
with no running app, DB, or broker.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from simura.twincore.auth import extract_key, is_authorized, require_api_key
from fastapi import HTTPException


# -- is_authorized ---------------------------------------------------------
def test_disabled_allows_everything():
    # Empty configured key => auth disabled, any (or no) key is fine.
    assert is_authorized("", None) is True
    assert is_authorized("", "whatever") is True


def test_enabled_requires_exact_match():
    assert is_authorized("s3cret", "s3cret") is True
    assert is_authorized("s3cret", "wrong") is False
    assert is_authorized("s3cret", None) is False
    assert is_authorized("s3cret", "") is False
    # No accidental prefix/substring acceptance.
    assert is_authorized("s3cret", "s3cre") is False
    assert is_authorized("s3cret", "s3cret-extra") is False


# -- extract_key -----------------------------------------------------------
def test_extract_bearer_header():
    assert extract_key({"Authorization": "Bearer abc123"}) == "abc123"
    # Case-insensitive header name and scheme.
    assert extract_key({"authorization": "bearer abc123"}) == "abc123"


def test_extract_x_api_key_header():
    assert extract_key({"X-API-Key": "abc123"}) == "abc123"
    assert extract_key({"x-api-key": "  abc123  "}) == "abc123"


def test_extract_query_param():
    assert extract_key({}, {"api_key": "abc123"}) == "abc123"


def test_bearer_takes_precedence_over_query():
    key = extract_key({"Authorization": "Bearer header-key"}, {"api_key": "query-key"})
    assert key == "header-key"


def test_extract_missing_returns_none():
    assert extract_key({}) is None
    assert extract_key({"Authorization": "Basic xyz"}) is None
    assert extract_key({"Authorization": "Bearer   "}) is None
    assert extract_key({}, {}) is None


# -- require_api_key dependency --------------------------------------------
def _fake_request(api_key: str, headers=None, query=None):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(api_key=api_key))),
        headers=headers or {},
        query_params=query or {},
    )


def test_require_api_key_passes_when_disabled():
    require_api_key(_fake_request(""))  # no exception


def test_require_api_key_passes_with_valid_key():
    require_api_key(_fake_request("s3cret", headers={"X-API-Key": "s3cret"}))


def test_require_api_key_rejects_missing_and_wrong():
    with pytest.raises(HTTPException) as exc:
        require_api_key(_fake_request("s3cret"))
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException):
        require_api_key(_fake_request("s3cret", headers={"X-API-Key": "nope"}))
