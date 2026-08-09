"""Simulated BMS devices: expose the simulator's telemetry over Modbus / OPC-UA.

The analog of the physics simulator, one layer out: it lets anyone exercise the
connectors (and the whole twin) without owning hardware. A device sim runs the
Component-1 simulator and continuously encodes its telemetry into device
registers / nodes, standing in for a real BMS gateway.

Register map (holding registers, matching examples/connectors/modbus.yaml):

    0        pack current   (0.1 A, signed)
    1        pack SoC       (x1000)
    100..    cell voltage   (mV), one per cell in (series, parallel) order
    200..    module temp    (0.1 C, signed), one per series module
"""

from __future__ import annotations

import asyncio
import logging

from ..publisher.run import build_simulator
from ..sim.telemetry import PackTelemetry

log = logging.getLogger("simura.devsim")

V_REG, T_REG = 100, 200


def _u16(value: int) -> int:
    return value & 0xFFFF


def encode_registers(tel: PackTelemetry, series: int, parallel: int) -> dict[int, int]:
    """Encode telemetry into a {address: register_value} map."""
    regs: dict[int, int] = {}
    regs[0] = _u16(int(round(tel.pack_current_a * 10)))
    regs[1] = _u16(int(round(tel.pack_soc * 1000)))

    module_temp_sum = [0.0] * series
    module_temp_n = [0] * series
    for c in tel.cells:
        idx = c.series_index * parallel + c.parallel_index
        regs[V_REG + idx] = _u16(int(round(c.voltage_v * 1000)))
        module_temp_sum[c.series_index] += c.temp_c
        module_temp_n[c.series_index] += 1
    for s in range(series):
        mean_t = module_temp_sum[s] / max(module_temp_n[s], 1)
        regs[T_REG + s] = _u16(int(round(mean_t * 10)))
    return regs


async def run_modbus_device(
    host: str = "0.0.0.0", port: int = 5020, scenario: str = "fault", speed: float = 10.0
) -> None:
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusServerContext,
        ModbusSlaveContext,
    )
    from pymodbus.server import StartAsyncTcpServer

    block = ModbusSequentialDataBlock(0, [0] * 300)
    store = ModbusSlaveContext(hr=block)
    context = ModbusServerContext(slaves=store, single=True)

    async def updater() -> None:
        while True:
            simulator, pack_cfg, sim_cfg = build_simulator(scenario)
            for tel in simulator.run():
                regs = encode_registers(tel, pack_cfg.series, pack_cfg.parallel)
                for addr, val in regs.items():
                    store.setValues(3, addr, [val])
                await asyncio.sleep(sim_cfg.dt_s / speed if speed > 0 else 0)

    task = asyncio.create_task(updater())
    log.info("modbus device serving on %s:%s (scenario=%s)", host, port, scenario)
    try:
        await StartAsyncTcpServer(context=context, address=(host, port))
    finally:
        task.cancel()


async def run_opcua_device(
    url: str = "opc.tcp://0.0.0.0:4840/simura/", scenario: str = "fault", speed: float = 10.0
) -> tuple:
    """Start an OPC-UA server and return (server, node_ids) for tests/demo."""
    from asyncua import Server, ua

    server = Server()
    await server.init()
    server.set_endpoint(url)
    idx = await server.register_namespace("simura")
    bms = await server.nodes.objects.add_object(idx, "BMS")

    simulator, pack_cfg, _ = build_simulator(scenario)
    n = pack_cfg.series * pack_cfg.parallel
    v_node = await bms.add_variable(ua.NodeId("CellVoltages", idx), "CellVoltages", [0.0] * n)
    t_node = await bms.add_variable(ua.NodeId("CellTemps", idx), "CellTemps", [0.0] * pack_cfg.series)
    i_node = await bms.add_variable(ua.NodeId("PackCurrent", idx), "PackCurrent", 0.0)
    soc_node = await bms.add_variable(ua.NodeId("PackSoC", idx), "PackSoC", 0.0)

    await server.start()

    async def updater() -> None:
        while True:
            sim, cfg, sc = build_simulator(scenario)
            for tel in sim.run():
                await v_node.write_value([float(c.voltage_v) for c in tel.cells])
                temps = [0.0] * cfg.series
                counts = [0] * cfg.series
                for c in tel.cells:
                    temps[c.series_index] += c.temp_c
                    counts[c.series_index] += 1
                await t_node.write_value([temps[s] / max(counts[s], 1) for s in range(cfg.series)])
                await i_node.write_value(float(tel.pack_current_a))
                await soc_node.write_value(float(tel.pack_soc))
                await asyncio.sleep(sc.dt_s / speed if speed > 0 else 0)

    task = asyncio.create_task(updater())
    node_ids = {
        "cell_voltage_node": f"ns={idx};s=CellVoltages",
        "cell_temp_node": f"ns={idx};s=CellTemps",
        "pack_current_node": f"ns={idx};s=PackCurrent",
        "pack_soc_node": f"ns={idx};s=PackSoC",
    }
    return server, node_ids, task


def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Simulated BMS device (Modbus/OPC-UA).")
    parser.add_argument("--protocol", default="modbus", choices=["modbus", "opcua"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5020)
    parser.add_argument("--scenario", default="fault", choices=["healthy", "fault"])
    parser.add_argument("--speed", type=float, default=10.0)
    args = parser.parse_args()

    if args.protocol == "modbus":
        asyncio.run(run_modbus_device(args.host, args.port, args.scenario, args.speed))
    else:
        async def _serve() -> None:
            await run_opcua_device(f"opc.tcp://{args.host}:{args.port}/simura/", args.scenario, args.speed)
            while True:
                await asyncio.sleep(3600)

        asyncio.run(_serve())


if __name__ == "__main__":
    main()
