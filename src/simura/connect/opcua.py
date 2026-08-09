"""OPC-UA connector -- the modern industrial-interoperability standard.

Reads a small set of OPC-UA nodes: array nodes for per-cell voltage and
temperature, and scalar nodes for pack current and SoC. Node ids are given as
strings (e.g. ``ns=2;s=CellVoltages``).
"""

from __future__ import annotations

from dataclasses import dataclass

from asyncua import Client

from .base import PollingConnector
from .frame import SourceFrame


@dataclass
class OpcUaSource:
    pack_current_node: str
    cell_voltage_node: str
    cell_temp_node: str
    pack_soc_node: str | None = None


class OpcUaConnector(PollingConnector):
    source_kind = "opcua"

    def __init__(self, *args, url: str, source: OpcUaSource, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.url = url
        self.source = source
        self._client: Client | None = None

    async def open(self) -> None:
        if self._client is None:
            self._client = Client(url=self.url)
            await self._client.connect()

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            finally:
                self._client = None

    async def read_frame(self) -> SourceFrame | None:
        assert self._client is not None
        c, src = self._client, self.source
        volts = await c.get_node(src.cell_voltage_node).read_value()
        temps = await c.get_node(src.cell_temp_node).read_value()
        current = await c.get_node(src.pack_current_node).read_value()

        scalars: dict[str, float] = {"pack_current": float(current)}
        if src.pack_soc_node is not None:
            scalars["pack_soc"] = float(await c.get_node(src.pack_soc_node).read_value())

        return SourceFrame(
            scalars=scalars,
            arrays={
                "cell_voltage": [float(v) for v in volts],
                "cell_temp": [float(t) for t in temps],
            },
        )
