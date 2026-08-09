"""Tests for the hardware connectors.

Decode logic is unit-tested directly; each protocol is round-tripped against an
in-process device sim: simulator telemetry -> device (registers/nodes) ->
connector -> decoded telemetry, proving real-protocol data lands as the same
contract the simulator emits. No external broker or hardware needed.
"""

from __future__ import annotations

import asyncio

from simura.connect import DeviceMapping, SourceFrame, build_telemetry
from simura.connect.decode import build_telemetry as decode
from simura.sim import ChargeDischargeCycle, InternalShort, PackConfig, SimConfig, Simulator


# --- decode unit tests -------------------------------------------------------

def _raw_frame():
    # 4S1P device: 4 cell voltages (mV), 4 temps (deci-C), current (deci-A), soc (x1000)
    return SourceFrame(
        scalars={"pack_current": 200, "pack_soc": 800},
        arrays={"cell_voltage": [3700, 3710, 3690, 3705], "cell_temp": [250, 251, 400, 249]},
    )


def test_decode_scaling_and_topology():
    m = DeviceMapping(series=4, parallel=1, voltage_scale=0.001, temp_scale=0.1,
                      current_scale=0.1, soc_scale=0.001, temp_mode="per_cell")
    tel = decode(_raw_frame(), m)
    assert len(tel.cells) == 4
    assert abs(tel.cells[0].voltage_v - 3.700) < 1e-6
    assert abs(tel.pack_current_a - 20.0) < 1e-6
    assert abs(tel.pack_soc - 0.800) < 1e-6
    assert abs(tel.max_temp_c - 40.0) < 1e-6           # 400 deci-C on cell 2
    # Series string: each cell carries the pack current.
    assert abs(tel.cells[0].current_a - 20.0) < 1e-6


def test_decode_per_series_temp_expansion():
    # 2 series x 2 parallel, one temperature per module.
    m = DeviceMapping(series=2, parallel=2, temp_mode="per_series")
    frame = SourceFrame(
        scalars={"pack_current": 10.0, "pack_soc": 0.5},
        arrays={"cell_voltage": [3.7, 3.7, 3.6, 3.6], "cell_temp": [30.0, 45.0]},
    )
    tel = decode(frame, m)
    temps = {(c.series_index, c.parallel_index): c.temp_c for c in tel.cells}
    assert temps[(0, 0)] == 30.0 and temps[(0, 1)] == 30.0
    assert temps[(1, 0)] == 45.0 and temps[(1, 1)] == 45.0
    # Parallel group splits pack current across its cells.
    assert abs(tel.cells[0].current_a - 5.0) < 1e-6


def test_decode_soc_from_voltage():
    m = DeviceMapping(series=2, parallel=1, soc_mode="from_voltage")
    frame = SourceFrame(scalars={"pack_current": 0.0},
                        arrays={"cell_voltage": [4.07, 3.55], "cell_temp": [25.0, 25.0]})
    tel = decode(frame, m)
    # 4.07 V ~ 90% SoC, 3.55 V ~ 10% on the NMC curve.
    assert tel.cells[0].soc > tel.cells[1].soc
    assert tel.cells[0].soc > 0.8 and tel.cells[1].soc < 0.2


# --- Modbus round-trip -------------------------------------------------------

def _sample_telemetry():
    pack = PackConfig(series=12, parallel=2, initial_soc=0.9)
    sim = SimConfig(dt_s=1.0, duration_s=900.0)
    faults = [InternalShort(cell=(3, 0), r_short_ohm=2.0, start_s=600.0)]
    last = None
    for last in Simulator(pack, sim, ChargeDischargeCycle(20.0, 15.0), faults).run():
        pass
    return last


def test_modbus_roundtrip():
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusServerContext,
        ModbusSlaveContext,
    )
    from pymodbus.server import StartAsyncTcpServer

    from simura.connect.devsim import encode_registers
    from simura.connect.modbus import ModbusConnector, ModbusSource

    original = _sample_telemetry()
    port = 15021

    async def scenario():
        block = ModbusSequentialDataBlock(0, [0] * 300)
        store = ModbusSlaveContext(hr=block)
        context = ModbusServerContext(slaves=store, single=True)
        for addr, val in encode_registers(original, 12, 2).items():
            store.setValues(3, addr, [val])

        server_task = asyncio.create_task(StartAsyncTcpServer(context=context, address=("127.0.0.1", port)))
        await asyncio.sleep(0.6)

        conn = ModbusConnector(
            system_id="t", mapping=DeviceMapping(series=12, parallel=2, temp_mode="per_series",
                                                 voltage_scale=0.001, temp_scale=0.1,
                                                 current_scale=0.1, soc_scale=0.001),
            host="127.0.0.1", port=port,
            source=ModbusSource(pack_current_reg=0, pack_soc_reg=1,
                                cell_voltage_start=100, cell_voltage_count=24,
                                cell_temp_start=200, cell_temp_count=12),
        )
        await conn.open()
        tel = conn.decode(await conn.read_frame())
        await conn.close()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        return tel

    tel = asyncio.run(scenario())
    assert len(tel.cells) == 24
    assert abs(tel.pack_current_a - original.pack_current_a) < 0.05
    assert abs(tel.pack_soc - original.pack_soc) < 0.002
    assert abs(tel.pack_voltage_v - original.pack_voltage_v) < 0.1
    # The hot module (3) survives the per-module sensor granularity.
    hottest = max(tel.cells, key=lambda c: c.temp_c)
    assert hottest.series_index == 3
    assert tel.max_temp_c > 26


# --- OPC-UA round-trip -------------------------------------------------------

def test_opcua_roundtrip():
    from simura.connect.devsim import run_opcua_device
    from simura.connect.opcua import OpcUaConnector, OpcUaSource

    url = "opc.tcp://127.0.0.1:14841/simura/"

    async def scenario():
        server, node_ids, task = await run_opcua_device(url, scenario="fault", speed=40.0)
        await asyncio.sleep(1.0)  # let the device publish some frames

        conn = OpcUaConnector(
            system_id="t",
            mapping=DeviceMapping(series=12, parallel=2, temp_mode="per_series"),
            url=url, source=OpcUaSource(**node_ids),
        )
        await conn.open()
        tel = conn.decode(await conn.read_frame())
        await conn.close()
        task.cancel()
        await server.stop()
        return tel

    tel = asyncio.run(scenario())
    assert len(tel.cells) == 24
    assert all(2.5 < c.voltage_v < 4.3 for c in tel.cells)
    assert 0.0 <= tel.pack_soc <= 1.0
    assert tel.max_temp_c >= 20.0


# --- MQTT bridge mapping -----------------------------------------------------

def test_mqtt_bridge_extract_and_decode():
    from simura.connect.mqtt_bridge import MqttBridgeConnector, MqttSource

    conn = MqttBridgeConnector(
        system_id="t",
        mapping=DeviceMapping(series=2, parallel=2, temp_mode="per_series", soc_scale=0.01),
        source=MqttSource(topic="plant/x", pack_current_path="bms.current",
                          pack_soc_path="bms.soc", cell_voltage_path="bms.cells.v",
                          cell_temp_path="bms.cells.t"),
    )
    payload = {"bms": {"current": 20.0, "soc": 78.5, "cells": {"v": [3.9, 3.9, 3.8, 3.8], "t": [31.0, 33.0]}}}
    frame = conn._extract(payload)
    assert frame is not None
    tel = build_telemetry(frame, conn.mapping)
    assert len(tel.cells) == 4
    assert abs(tel.pack_soc - 0.785) < 1e-6      # percent -> fraction
    assert abs(tel.pack_current_a - 20.0) < 1e-6
