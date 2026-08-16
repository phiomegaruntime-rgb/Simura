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

Segments may carry :mod:`~simura.wires.faults` -- a corroded run, a loose joint, a
nicked conductor, aged insulation, a leak to ground. A faulted segment's effect is
folded into the same solve: it changes the conductance the network sees, so the
*whole* network re-settles around it. One bad joint therefore shows up as a
voltage the far end never gets, not just as a hot spot on one wire.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .environment import WireEnvironmentCoupling, apply_to_effect
from .faults import Fault, accumulate
from .wire import Wire, WireSpec


# How far two paralleled sources may disagree before it is called a mistake.
#
# A source node here is an *ideal* voltage source -- the model gives it no
# internal impedance, because a pack's own resistance belongs to the pack model,
# not to the wiring. Two ideal sources joined by a milliohm of copper is a
# degenerate circuit: the only thing limiting the current between them is the
# cable, so even a small disagreement drives an enormous circulating current,
# which cooks the segment in the thermal fixed point below until its resistance
# overflows and the conductance matrix loses rank. Diagnosing that as "singular"
# is true but useless, so it is caught up front instead.
#
# A quarter of a volt is comfortably above the numerical noise of two genuinely
# matched sources and far below any real pack-to-pack mismatch.
SOURCE_MISMATCH_TOL_V = 0.25


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
    faults: list[Fault] = field(default_factory=list)


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
    temp_rating_c: float = 0.0   # effective rating (aged insulation lowers it)
    leakage_a: float = 0.0       # current lost to ground by a fault
    faulted: bool = False        # a fault was active on this segment

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


def _effective_resistance(wire: Wire, effect) -> float:
    """The resistance the network actually sees for a segment, faults included.

    Mirrors :meth:`simura.wires.wire.Wire.step`: a fault can scale the conductor's
    own resistance (corrosion, lost cross-section) and/or add a lump in series (a
    loose joint). Floored so a solve never divides by zero.
    """
    base = wire.resistance_ohm(wire.temp_c) * effect.resistance_mult
    return max(base + effect.extra_resistance_ohm, 1e-12)


def _fault_heat_w(wire: Wire, effect, current_a: float) -> float:
    """Heat a fault adds beyond the clean conductor's own ``I^2*R``.

    ``steady_state_temp_c`` computes ``I^2*R(T)`` from the *unfaulted* resistance,
    so the extra dissipation from a raised or added resistance is handed to it as
    an external heat term (as is absorbed sunlight, via ``extra_heat_w``).
    """
    clean = wire.resistance_ohm(wire.temp_c)
    return effect.extra_heat_w + current_a * current_a * (
        _effective_resistance(wire, effect) - clean
    )


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

    def add_segment(
        self,
        id: str,
        from_node: str,
        to_node: str,
        spec: WireSpec,
        faults: list[Fault] | None = None,
    ) -> Segment:
        for n in (from_node, to_node):
            if n not in self.nodes:
                raise ValueError(f"segment '{id}' references unknown node '{n}'")
        seg = Segment(id=id, from_node=from_node, to_node=to_node, spec=spec, faults=faults or [])
        self.segments.append(seg)
        return seg

    # -- diagnosis --------------------------------------------------------
    def _groups(self) -> list[set[str]]:
        """Node ids partitioned into conductively connected groups."""
        adjacency: dict[str, list[str]] = {}
        for seg in self.segments:
            adjacency.setdefault(seg.from_node, []).append(seg.to_node)
            adjacency.setdefault(seg.to_node, []).append(seg.from_node)

        groups: list[set[str]] = []
        seen: set[str] = set()
        for start in self.nodes:
            if start in seen:
                continue
            members = {start}
            queue = [start]
            while queue:
                current = queue.pop()
                for nxt in adjacency.get(current, ()):
                    if nxt not in members:
                        members.add(nxt)
                        queue.append(nxt)
            seen |= members
            groups.append(members)
        return groups

    def paralleled_source_conflicts(
        self, tol_v: float = SOURCE_MISMATCH_TOL_V
    ) -> list[tuple[str, float, str, float]]:
        """Sources wired together that disagree about the voltage they are holding.

        Returns ``(low_id, low_v, high_id, high_v)`` for the widest disagreement in
        each conductive group -- empty when every group's sources agree, which is
        the only case nodal analysis can answer. See
        :data:`SOURCE_MISMATCH_TOL_V` for why this is fatal rather than merely
        inaccurate.
        """
        conflicts: list[tuple[str, float, str, float]] = []
        for members in self._groups():
            sources = [
                (nid, self.nodes[nid].voltage)
                for nid in members
                if self.nodes[nid].voltage is not None
            ]
            if len(sources) < 2:
                continue
            low = min(sources, key=lambda s: s[1])
            high = max(sources, key=lambda s: s[1])
            if high[1] - low[1] > tol_v:
                conflicts.append((low[0], low[1], high[0], high[1]))
        return conflicts

    def _isolated_free_nodes(self) -> list[str]:
        """Free nodes with no conductive path to any fixed-voltage node."""
        stranded: list[str] = []
        for members in self._groups():
            if any(self.nodes[nid].voltage is not None for nid in members):
                continue
            stranded.extend(nid for nid in members if self.nodes[nid].voltage is None)
        return sorted(stranded)

    # -- solve ------------------------------------------------------------
    def solve(
        self,
        max_iter: int = 8,
        tol_v: float = 1e-6,
        elapsed_s: float = 0.0,
        weather=None,  # noqa: ANN001 - any object with the WeatherSample fields
        coupling: WireEnvironmentCoupling | None = None,
    ) -> NetworkResult:
        """Solve for node voltages and per-segment operating point.

        Iterates resistance<->temperature to a fixed point (self-heating).
        ``elapsed_s`` is the time any segment fault has been active for -- it only
        matters for faults that develop (corrosion growing a run's resistance);
        instantaneous ones (a loose joint, a nicked conductor) ignore it.

        With ``weather`` supplied the whole network is solved for that day's
        conditions, exactly as :func:`simura.wires.planning.evaluate_run` does for a
        single run: every conductor cools toward the real ambient, wind multiplies
        its convective cooling, absorbed sunlight adds heat, and each segment's
        ampacity is **derated for ambient** (the conservative standard correction --
        it does not credit the wind, which shows up only in the temperature).
        Because resistance rises with temperature, a hot still day genuinely costs
        more voltage at the far end of a run than a cold windy one.
        """
        if not any(n.voltage is not None for n in self.nodes.values()):
            raise ValueError("network needs at least one source node (a fixed voltage)")

        # Two sources of different voltage tied together is not a hard network to
        # solve -- it is a network with no answer, because nothing here limits the
        # current between them. Say so before the fixed point below turns it into
        # an overflowed resistance and an unhelpfully "singular" matrix.
        conflicts = self.paralleled_source_conflicts()
        if conflicts:
            low_id, low_v, high_id, high_v = conflicts[0]
            raise ValueError(
                f"sources '{high_id}' ({high_v:.2f} V) and '{low_id}' ({low_v:.2f} V) are "
                f"paralleled onto the same conductive group -- sources at different voltages "
                f"cannot be tied together, because with no impedance between them the "
                f"{high_v - low_v:.2f} V difference drives an unbounded circulating current. "
                f"Match their voltages, or wire them to separate groups."
            )

        wires = {seg.id: Wire(seg.spec) for seg in self.segments}

        # Each segment's active fault contributions, collapsed into one effect.
        effects = {
            seg.id: accumulate(seg.faults, wires[seg.id], elapsed_s) for seg in self.segments
        }

        # Weather rides the same effect channels faults do -- wind on `cooling_mult`,
        # absorbed sun on `extra_heat_w` -- exactly as WireSimulator folds it in, so
        # the solve below needs no special case for it. Solar gain scales with each
        # run's own sun-facing silhouette, so a long fat cable picks up more heat
        # than a short thin one.
        if weather is not None:
            coupling = coupling or WireEnvironmentCoupling()
            for seg in self.segments:
                wire = wires[seg.id]
                env = coupling.apply(weather, wire.diameter_m * wire.length_m)
                wire.ambient_c = env.ambient_c
                wire.temp_c = env.ambient_c  # start the fixed point at the real ambient
                apply_to_effect(effects[seg.id], env)
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
            # A ground fault leaks current out at the far end of its segment, so
            # the segment carries it (and heats for it) while the load beyond
            # never sees it.
            for seg in self.segments:
                leak = effects[seg.id].extra_current_a
                if leak and seg.to_node in idx:
                    b[idx[seg.to_node]] -= leak

            for seg in self.segments:
                wire = wires[seg.id]
                r = _effective_resistance(wire, effects[seg.id])
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
                    # Name what actually went wrong. A stranded node is the common
                    # cause and is checkable directly; but the matrix can also lose
                    # rank part-way through the fixed point, when a runaway current
                    # drives a conductor's temperature -- and so its resistance --
                    # far enough that its conductance underflows to zero. Reporting
                    # the second as the first has sent people looking for a missing
                    # cable that was never missing.
                    stranded = self._isolated_free_nodes()
                    if stranded:
                        named = ", ".join(f"'{nid}'" for nid in stranded[:4])
                        more = "" if len(stranded) <= 4 else f" (+{len(stranded) - 4} more)"
                        detail = (
                            f"{named}{more} have no conductive path to any source -- "
                            f"every free node needs one"
                        )
                    else:
                        hottest = max(
                            (w.temp_c for w in wires.values()), default=float("nan")
                        )
                        detail = (
                            f"the conductance matrix lost rank during the "
                            f"resistance/temperature fixed point (hottest conductor "
                            f"{hottest:.3g} °C) -- a runaway current has driven a "
                            f"segment's resistance out of range"
                        )
                    raise ValueError(f"network is singular -- {detail}") from exc
                for nid in free:
                    voltages[nid] = float(v_free[idx[nid]])

            # Update segment temperatures from the currents just found.
            converged = n == 0 or np.max(np.abs(v_free - prev_free)) < tol_v
            if n > 0:
                prev_free = v_free
            for seg in self.segments:
                wire, effect = wires[seg.id], effects[seg.id]
                r = _effective_resistance(wire, effect)
                current = (voltages[seg.from_node] - voltages[seg.to_node]) / r
                wire.temp_c = wire.steady_state_temp_c(
                    current,
                    cooling_mult=effect.cooling_mult,
                    extra_heat_w=_fault_heat_w(wire, effect, current),
                )
            if converged:
                break

        # Assemble results at the converged operating point.
        seg_results: list[SegmentResult] = []
        problems: list[str] = []
        total_loss = 0.0
        worst = None
        worst_util = -1.0
        for seg in self.segments:
            wire, effect = wires[seg.id], effects[seg.id]
            r = _effective_resistance(wire, effect)
            current = (voltages[seg.from_node] - voltages[seg.to_node]) / r
            drop = current * r
            loss = current * current * r
            total_loss += loss
            # A fault derates the rating the operating point is judged against:
            # less copper carries less current, aged insulation tolerates less heat.
            # On a hot day the rating falls too -- there is simply less headroom to
            # the insulation limit. Wind is deliberately not credited here; it shows
            # up in the temperature, which is the honest, conservative convention.
            base_ampacity = (
                wire.derated_ampacity_a(wire.ambient_c) if weather is not None else wire.ampacity_a
            )
            ampacity = base_ampacity * effect.ampacity_mult
            temp_rating = wire.effective_temp_rating_c(effect)
            util = abs(current) / ampacity if ampacity > 0 else float("inf")
            over_a = abs(current) > ampacity
            over_t = wire.temp_c > temp_rating
            if over_a:
                problems.append(f"segment '{seg.id}' over ampacity ({abs(current):.1f}/{ampacity:.0f} A)")
            if over_t:
                problems.append(f"segment '{seg.id}' over temp ({wire.temp_c:.0f}/{temp_rating:.0f} C)")
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
                    ampacity_a=round(ampacity, 2),
                    ampacity_utilization=round(util, 4),
                    over_ampacity=bool(over_a),
                    over_temp=bool(over_t),
                    temp_rating_c=round(temp_rating, 2),
                    leakage_a=round(effect.extra_current_a, 4),
                    faulted=bool(seg.faults),
                )
            )

        return NetworkResult(
            node_voltages={k: round(v, 5) for k, v in voltages.items()},
            segments=seg_results,
            total_loss_w=round(total_loss, 4),
            worst_segment=worst,
            problems=problems,
        )
