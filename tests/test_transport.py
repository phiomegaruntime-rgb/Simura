"""Tests for the transport contract (no broker/DB required).

These lock down the message envelope and topic conventions -- the agreement the
publisher and twin core must share exactly.
"""

from __future__ import annotations

import json

from celltwin.publisher.run import build_simulator
from celltwin.transport import (
    config_topic,
    system_id_from_topic,
    telemetry_topic,
    telemetry_wildcard,
)


def test_topic_roundtrip():
    assert telemetry_topic("bess-01") == "celltwin/telemetry/bess-01"
    assert config_topic("bess-01") == "celltwin/config/bess-01"
    assert system_id_from_topic(telemetry_topic("bess-01")) == "bess-01"
    assert system_id_from_topic(config_topic("xyz")) == "xyz"


def test_wildcard_matches_prefix():
    assert telemetry_wildcard() == "celltwin/telemetry/+"


def test_scenarios_build():
    healthy, _, _ = build_simulator("healthy")
    faulted, _, _ = build_simulator("fault")
    assert healthy.faults == []
    assert len(faulted.faults) == 2


def test_telemetry_envelope_is_json_serializable():
    sim, _, _ = build_simulator("healthy")
    tel = next(sim.run())
    envelope = {"system_id": "bess-01", "timestamp": "2026-01-01T00:00:00+00:00",
                "telemetry": tel.to_dict()}
    # Round-trips through JSON exactly as it will over MQTT.
    decoded = json.loads(json.dumps(envelope))
    assert decoded["system_id"] == "bess-01"
    assert "pack_soc" in decoded["telemetry"]
    assert len(decoded["telemetry"]["cells"]) == 12 * 2  # 12S2P
