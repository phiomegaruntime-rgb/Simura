"""Modbus TCP connector -- the workhorse protocol for BMS/PLC integration.

Polls a register map: a block of per-cell voltage registers, a block of
temperature registers, and scalar registers for pack current and SoC. Values are
raw 16-bit registers in the device's units; the :class:`DeviceMapping` scales
them to SI. Current and temperature are decoded as signed.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymodbus.client import AsyncModbusTcpClient

from .base import PollingConnector
from .frame import SourceFrame


@dataclass
class ModbusSource:
    pack_current_reg: int
    cell_voltage_start: int
    cell_temp_start: int
    cell_voltage_count: int
    cell_temp_count: int
    pack_soc_reg: int | None = None
    register_type: str = "holding"  # holding | input
    signed_current: bool = True
    signed_temp: bool = True
    slave: int = 1


def _to_signed(v: int) -> int:
    return v - 65536 if v >= 32768 else v


class ModbusConnector(PollingConnector):
    source_kind = "modbus"

    def __init__(self, *args, host: str, port: int = 502, source: ModbusSource, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.host = host
        self.port = port
        self.source = source
        self._client: AsyncModbusTcpClient | None = None

    async def open(self) -> None:
        if self._client is None:
            self._client = AsyncModbusTcpClient(self.host, port=self.port)
        if not self._client.connected:
            await self._client.connect()

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()

    async def _read(self, address: int, count: int) -> list[int]:
        assert self._client is not None
        if self.source.register_type == "input":
            rr = await self._client.read_input_registers(address, count=count, slave=self.source.slave)
        else:
            rr = await self._client.read_holding_registers(address, count=count, slave=self.source.slave)
        if rr.isError():
            raise IOError(f"modbus read error at {address}: {rr}")
        return list(rr.registers)

    async def read_frame(self) -> SourceFrame | None:
        src = self.source
        volts = await self._read(src.cell_voltage_start, src.cell_voltage_count)
        temps_raw = await self._read(src.cell_temp_start, src.cell_temp_count)
        current_raw = (await self._read(src.pack_current_reg, 1))[0]

        temps = [_to_signed(t) if src.signed_temp else t for t in temps_raw]
        current = _to_signed(current_raw) if src.signed_current else current_raw

        scalars: dict[str, float] = {"pack_current": float(current)}
        if src.pack_soc_reg is not None:
            scalars["pack_soc"] = float((await self._read(src.pack_soc_reg, 1))[0])

        return SourceFrame(
            scalars=scalars,
            arrays={"cell_voltage": [float(v) for v in volts], "cell_temp": [float(t) for t in temps]},
        )
