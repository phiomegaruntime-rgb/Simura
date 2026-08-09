"""A multi-node DC wiring network solved by nodal analysis.

Connect nodes with wire segments, fix one or more nodes to a source voltage,
draw loads at others, and solve the whole thing with standard **nodal analysis**:
each segment is a conductance ``1/R`` between two nodes, and Kirchhoff's current
law at every free node gives a linear system ``G V = b`` that ``numpy.linalg``
solves for the node voltages. From there every segment's current, voltage drop,
loss, temperature and ampacity utilisation follow.

Because resistance depends on temperature and temperature depends on current, the
solve is repeated a few times as a fixed point (segments warm up, resistance
rises, currents re-settle).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .wire import Wire, WireSpec


@dataclass
class Node:
    id: str
    voltage: float | None = None   # fixed source voltage; None == a free node
    load_a: float = 0.0            # current drawn out of this node (a load)


@dataclass
class Segment:
    id: str
    from_node: str
    to_node: str
    spec: WireSpec


@dataclass
class SegmentResult:
    id: str
    from_node: str
    to_node: str
    current_a: float
    voltage_drop_v: float
    power_loss_w: float
    temp_c: float
    resistance_ohm: float
    ampacity_a: float
    ampacity_utilization: float
    over_ampacity: bool
    over_temp: bool

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


@dataclass
class NetworkResult:
    node_voltages: dict[str, float]
    segments: list[SegmentResult]
    total_loss_w: float
    worst_segment: str | None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {
            "node_voltages": self.node_voltages,
            "segments": [s.to_dict() for s in self.segments],
            "total_loss_w": self.total_loss_w,
            "worst_segment": self.worst_segment,
            "problems": self.problems,
        }


class WireNetwork:
    """A graph of nodes joined by wire segments, solvable for its DC operating point."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.segments: list[Segment] = []

    # -- construction -----------------------------------------------------
    def add_node(self, id: str, voltage: float | None = None, load_a: float = 0.0) -> Node:
        node = Node(id=id, voltage=voltage, load_a=load_a)
        self.nodes[id] = node
        return node

    def add_segment(self, id: str, from_node: str, to_node: str, spec: WireSpec) -> Segment:
        for n in (from_node, to_node):
            if n not in self.nodes:
                raise ValueError(f"segment '{id}' references unknown node '{n}'")
        seg = Segment(id=id, from_node=from_node, to_node=to_node, spec=spec)
        self.segments.append(seg)
        return seg

    # -- solve ------------------------------------------------------------
    def solve(self, max_iter: int = 8, tol_v: float = 1e-6) -> NetworkResult:
        """Solve for node voltages and per-segment operating point.

        Iterates resistance<->temperature to a fixed point (self-heating).
        """
        if not any(n.voltage is not None for n in self.nodes.values()):
            raise ValueError("network needs at least one source node (a fixed voltage)")

        wires = {seg.id: Wire(seg.spec) for seg in self.segments}
        free = [nid for nid, n in self.nodes.items() if n.voltage is None]
        idx = {nid: i for i, nid in enumerate(free)}
        n = len(free)

        voltages: dict[str, float] = {
            nid: node.voltage for nid, node in self.nodes.items() if node.voltage is not None
        }
        prev_free = np.zeros(n)

        for _ in range(max_iter):
            g_mat = np.zeros((n, n))
            b = np.zeros(n)
            # Load injections (current drawn out of a node -> negative injection).
            for nid, node in self.nodes.items():
                if nid in idx:
                    b[idx[nid]] -= node.load_a

            for seg in self.segments:
                wire = wires[seg.id]
                r = max(wire.resistance_ohm(wire.temp_c), 1e-12)
                g = 1.0 / r
                a, c = seg.from_node, seg.to_node
                a_free, c_free = a in idx, c in idx
                if a_free and c_free:
                    i, j = idx[a], idx[c]
                    g_mat[i, i] += g
                    g_mat[j, j] += g
                    g_mat[i, j] -= g
                    g_mat[j, i] -= g
                elif a_free and not c_free:
                    i = idx[a]
                    g_mat[i, i] += g
                    b[i] += g * voltages[c]
                elif c_free and not a_free:
                    j = idx[c]
                    g_mat[j, j] += g
                    b[j] += g * voltages[a]
                # both fixed -> no unknown contribution

            if n > 0:
                try:
                    v_free = np.linalg.solve(g_mat, b)
                except np.linalg.LinAlgError as exc:
                    raise ValueError(
                        "network is singular -- a free node is not connected to any source"
                    ) from exc
                for nid in free:
                    voltages[nid] = float(v_free[idx[nid]])

            # Update segment temperatures from the currents just found.
            converged = n == 0 or np.max(np.abs(v_free - prev_free)) < tol_v
            if n > 0:
                prev_free = v_free
            for seg in self.segments:
                wire = wires[seg.id]
                r = wire.resistance_ohm(wire.temp_c)
                current = (voltages[seg.from_node] - voltages[seg.to_node]) / max(r, 1e-12)
                wire.temp_c = wire.steady_state_temp_c(current)
            if converged:
                break

        # Assemble results at the converged operating point.
        seg_results: list[SegmentResult] = []
        problems: list[str] = []
        total_loss = 0.0
        worst = None
        worst_util = -1.0
        for seg in self.segments:
            wire = wires[seg.id]
            r = wire.resistance_ohm(wire.temp_c)
            current = (voltages[seg.from_node] - voltages[seg.to_node]) / max(r, 1e-12)
            drop = current * r
            loss = current * current * r
            total_loss += loss
            util = wire.ampacity_utilization(current)
            over_a = abs(current) > wire.ampacity_a
            over_t = wire.temp_c > wire.temp_rating_c
            if over_a:
                problems.append(f"segment '{seg.id}' over ampacity ({abs(current):.1f}/{wire.ampacity_a:.0f} A)")
            if over_t:
                problems.append(f"segment '{seg.id}' over temp ({wire.temp_c:.0f}/{wire.temp_rating_c:.0f} C)")
            if util > worst_util:
                worst_util, worst = util, seg.id
            seg_results.append(
                SegmentResult(
                    id=seg.id,
                    from_node=seg.from_node,
                    to_node=seg.to_node,
                    current_a=round(current, 4),
                    voltage_drop_v=round(drop, 5),
                    power_loss_w=round(loss, 4),
                    temp_c=round(wire.temp_c, 3),
                    resistance_ohm=round(r, 8),
                    ampacity_a=round(wire.ampacity_a, 2),
                    ampacity_utilization=round(util, 4),
                    over_ampacity=bool(over_a),
                    over_temp=bool(over_t),
                )
            )

        return NetworkResult(
            node_voltages={k: round(v, 5) for k, v in voltages.items()},
            segments=seg_results,
            total_loss_w=round(total_loss, 4),
            worst_segment=worst,
            problems=problems,
        )
