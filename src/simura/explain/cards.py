"""Model cards: what a model is, in words, for someone from another domain.

Every model and every parameter a user can set carries a card -- *what is this,
and why does it matter* -- written so that the battery person can read the wire
model without a cable-pulling background, and the electrician can read the
battery model without an electrochemistry one.

The hard part of a layer like this is not writing it. It is that six months
later the code has three new parameters and the prose has none, and nobody
notices, because nothing breaks. So the cards are **checked against the code
they describe**: :func:`coverage` reflects over the real dataclasses and the
real option registries and reports every parameter that exists in code but has
no card, and every card that describes a parameter the code no longer has. The
test suite asserts both lists are empty. A new parameter without a card is a
failing build, not a silent gap.

Cards deliberately carry a ``limits`` list. A model card that only says what a
model does is marketing; the useful half is what it cannot do, which is the
thing a newcomer has no way to find out for themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Components a card can belong to. Matches the dashboard's landing cards, plus
# "twin" for the machinery that serves all three.
COMPONENTS = ("batteries", "wires", "lights", "twin")


@dataclass(frozen=True)
class ParamCard:
    """One settable parameter, explained."""

    key: str
    """The field name as it appears in code and in the API. Checked by
    :func:`coverage` -- this is the join between prose and model."""
    label: str
    unit: str
    what: str
    why: str
    """Why anybody should care. The half most parameter tables leave out."""
    typical: str = ""
    feel: str = ""
    """Optional intuition: turn it up, and what happens? Written as cause and
    effect so a reader can predict the model before running it."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "unit": self.unit,
            "what": self.what,
            "why": self.why,
            "typical": self.typical,
            "feel": self.feel,
        }


@dataclass(frozen=True)
class ModelCard:
    """One model, explained at three depths and from several domains at once."""

    id: str
    component: str
    title: str
    one_line: str
    """A tooltip. Must survive being read on its own, with no surrounding text."""
    what: str
    why: str
    source: str
    """The module this card documents, so a curious reader can go and look."""
    equation: str = ""
    assumptions: tuple[str, ...] = ()
    limits: tuple[str, ...] = ()
    """What this model cannot tell you. Non-negotiable; a card with no limits
    listed is a card that has not been thought about."""
    params: tuple[ParamCard, ...] = ()
    reads_like: dict[str, str] = field(default_factory=dict)
    """domain key -> the same model restated in that domain's own vocabulary."""
    see_also: tuple[str, ...] = ()

    def param(self, key: str) -> ParamCard | None:
        return next((p for p in self.params if p.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "component": self.component,
            "title": self.title,
            "one_line": self.one_line,
            "what": self.what,
            "why": self.why,
            "source": self.source,
            "equation": self.equation,
            "assumptions": list(self.assumptions),
            "limits": list(self.limits),
            "params": [p.to_dict() for p in self.params],
            "reads_like": dict(self.reads_like),
            "see_also": list(self.see_also),
        }


# --------------------------------------------------------------------------
# Batteries
# --------------------------------------------------------------------------

_CELL_PARAMS = (
    ParamCard(
        key="capacity_ah",
        label="Cell capacity",
        unit="Ah",
        what="How much charge one cell holds when full.",
        why=(
            "It sets how long the system runs before it is empty, and — because "
            "current is shared between parallel cells by impedance, not by "
            "capacity — a cell that is smaller than its neighbours empties first "
            "and drags the whole module's usable range down with it."
        ),
        typical="2–5 Ah for a cylindrical cell, 50–300 Ah for a prismatic one",
        feel="Double it and the system runs roughly twice as long at the same load.",
    ),
    ParamCard(
        key="r0_ohm",
        label="Internal resistance",
        unit="Ω",
        what="The cell's instantaneous resistance — the part of the voltage that "
        "disappears the moment current flows, and comes back the moment it stops.",
        why=(
            "It is the single most consequential number in the cell. It sets how "
            "much voltage you lose under load, it is where most of the heat comes "
            "from (heating goes as the square of current), and it grows as the "
            "cell ages — which is how the twin measures state of health at all."
        ),
        typical="10–30 mΩ for a healthy small cell",
        feel="Double it and you lose twice the voltage and make four times the heat "
        "at the same current.",
    ),
    ParamCard(
        key="r1_ohm",
        label="Polarisation resistance",
        unit="Ω",
        what="The slow part of the cell's resistance: the voltage sag that builds "
        "over seconds rather than instantly.",
        why=(
            "It is why a cell's voltage keeps drooping after the load is applied "
            "and keeps recovering after it is removed. Without it a simulated cell "
            "would snap between voltages in a way no real cell does, and any "
            "resistance you estimated from a live measurement would be wrong."
        ),
        typical="about half the internal resistance",
        feel="Turn it up and the voltage takes longer to settle, and settles lower.",
    ),
    ParamCard(
        key="c1_farad",
        label="Polarisation capacitance",
        unit="F",
        what="Sets how *long* the slow sag takes: together with the polarisation "
        "resistance it gives a time constant, τ = R₁·C₁.",
        why="It decides whether the cell's slow response happens over seconds or "
        "over minutes, which is the difference between a load step you can see in "
        "the data and one you cannot.",
        typical="1000–3000 F, giving τ ≈ 10–30 s",
        feel="Turn it up and the same sag arrives more gradually.",
    ),
    ParamCard(
        key="coulombic_eff",
        label="Charge efficiency",
        unit="fraction",
        what="The share of charge you put in that you get back out.",
        why="Charging is slightly lossy and discharging is not, so a cell cycled "
        "endlessly drifts down in state of charge. This is the number that makes "
        "that drift happen instead of a system that cycles forever for free.",
        typical="0.98–0.995",
        feel="Lower it and repeated cycling walks the pack downward.",
    ),
    ParamCard(
        key="thermal_capacity_j_per_k",
        label="Thermal mass",
        unit="J/K",
        what="How much energy it takes to warm one cell by one degree.",
        why="It sets how *fast* a fault becomes visible. A heavy cell absorbs a "
        "fault's heat for minutes before its temperature says anything; a light "
        "one shows it in seconds. Detection lead time is mostly this number.",
        typical="60–90 J/K for a 21700 cell",
        feel="Turn it up and everything thermal happens more slowly, in both "
        "directions.",
    ),
    ParamCard(
        key="cooling_conductance_w_per_k",
        label="Cooling conductance",
        unit="W/K",
        what="How many watts the cell sheds to its surroundings for each degree it "
        "sits above them.",
        why=(
            "It is the other side of every thermal question: a cell is hot not "
            "because it makes heat but because it makes more than it sheds. Halve "
            "this and an unchanged load doubles the temperature rise — which is "
            "exactly what a cooling fault is."
        ),
        typical="0.3–1.0 W/K with modest airflow",
        feel="Turn it down and steady-state temperature rises in proportion.",
    ),
    ParamCard(
        key="v_min",
        label="Minimum cell voltage",
        unit="V",
        what="The bottom of the cell's safe window.",
        why="Below it a cell degrades quickly and permanently. The twin flags it "
        "rather than enforcing it, so you can watch a design walk past its own "
        "limits instead of being silently protected from them.",
        typical="2.5 V for NMC, 2.0 V for LFP",
    ),
    ParamCard(
        key="v_max",
        label="Maximum cell voltage",
        unit="V",
        what="The top of the cell's safe window.",
        why="Above it a cell plates lithium and ages fast. Combined with the "
        "minimum it defines the band a balancing system is trying to keep every "
        "cell inside.",
        typical="4.2 V for NMC, 3.65 V for LFP",
    ),
    ParamCard(
        key="temp_max_c",
        label="Maximum cell temperature",
        unit="°C",
        what="The temperature above which the cell is outside its safe operating "
        "envelope.",
        why="It is the line the safety assessment measures time-to-critical "
        "against — the answer to 'how long have I got' is 'how long until this'.",
        typical="55–60 °C",
    ),
)

_PACK_PARAMS = (
    ParamCard(
        key="series",
        label="Cells in series",
        unit="count",
        what="How many cells (or modules) are stacked end to end.",
        why="Series count sets voltage: the pack's voltage is the sum of theirs. "
        "It is the first thing you choose, because it has to match whatever the "
        "system is wired to.",
        typical="12–200",
        feel="Double it and the pack voltage doubles at the same current.",
    ),
    ParamCard(
        key="parallel",
        label="Cells in parallel",
        unit="count",
        what="How many cells sit side by side at each position in the stack.",
        why=(
            "Parallel count sets current and capacity. It also sets how much "
            "trouble one bad cell can cause: its neighbours share a node with it, "
            "so a cell that starts drawing current pulls it away from the others "
            "rather than failing quietly on its own."
        ),
        typical="1–20",
        feel="Double it and each cell carries half the current — and makes a "
        "quarter of the heat.",
    ),
    ParamCard(
        key="capacity_spread",
        label="Capacity spread",
        unit="fraction",
        what="How much cell capacity varies across the pack, as a fraction of "
        "nominal.",
        why="Real cells are never identical, and a perfectly uniform pack is the "
        "one case where imbalance can never appear. This is what makes imbalance "
        "a thing the model can produce rather than a thing you have to inject.",
        typical="0.01–0.03 for graded cells",
    ),
    ParamCard(
        key="resistance_spread",
        label="Resistance spread",
        unit="fraction",
        what="How much internal resistance varies across the pack.",
        why="Within a parallel group, current divides by conductance — so the "
        "lowest-resistance cell takes the largest share, works hardest, and runs "
        "hottest. Resistance spread is where 'one cell is always the hot one' "
        "comes from.",
        typical="0.03–0.08",
    ),
    ParamCard(
        key="initial_soc",
        label="Starting charge",
        unit="fraction",
        what="How full the pack is when the simulation begins.",
        why="It decides how much of the run happens in the flat middle of the "
        "voltage curve versus the steep ends, which changes how legible everything "
        "else is.",
        typical="0.2–0.9",
    ),
    ParamCard(
        key="initial_soc_spread",
        label="Starting imbalance",
        unit="fraction",
        what="How unevenly charged the cells are at the start.",
        why="A pack that starts perfectly matched hides how quickly small "
        "differences grow. Start it slightly uneven and you can watch balance "
        "behaviour actually do something.",
        typical="0.005–0.02",
    ),
    ParamCard(
        key="ambient_temp_c",
        label="Ambient temperature",
        unit="°C",
        what="The temperature the pack cools toward when no weather source is "
        "attached.",
        why="Every thermal result is a rise *above* this. Change it and every "
        "temperature in the run moves with it, which is why a design that is fine "
        "in a lab is not automatically fine on a roof.",
        typical="15–35 °C",
    ),
    ParamCard(
        key="seed",
        label="Random seed",
        unit="",
        what="Fixes which particular random spread of cells you get.",
        why="Same seed, same pack, every time — so a result you found once can be "
        "reproduced by someone else, and a change you make is the only thing that "
        "changed.",
        typical="any integer",
    ),
)

_RUN_PARAMS = (
    ParamCard(
        key="system_id",
        label="System id",
        unit="",
        what="The unique handle this system is known by across the whole stack.",
        why="It is what the telemetry topic, the database rows, the dashboard "
        "selector and the API path all agree on. Two systems with the same id are "
        "one system.",
        typical="a short slug, e.g. bess-site-a-01",
    ),
    ParamCard(
        key="name",
        label="Display name",
        unit="",
        what="A human-readable label for the system.",
        why="The id is for machines; this is the one a person reads in a fleet of "
        "thirty.",
        typical="free text",
    ),
    ParamCard(
        key="chemistry",
        label="Cell chemistry",
        unit="",
        what="Which chemistry the cell is, which selects its voltage-versus-charge "
        "curve.",
        why=(
            "The curve is the chemistry's fingerprint and it changes how the whole "
            "system behaves. LFP is famously flat, so voltage tells you almost "
            "nothing about how full it is; NMC slopes, so it does. Everything that "
            "estimates charge from voltage lives or dies on this."
        ),
        typical="NMC, LFP, LCO or NCA",
    ),
    ParamCard(
        key="dt_s",
        label="Timestep",
        unit="s",
        what="How much simulated time passes per calculation step.",
        why="Small steps resolve fast events and cost more compute. Too large and "
        "the thermal integration starts lying — the step has to be well under the "
        "fastest time constant in the model.",
        typical="0.1–1 s",
    ),
    ParamCard(
        key="duration_s",
        label="Duration",
        unit="s",
        what="How much simulated time a run covers.",
        why="It has to be long enough for the thing you want to see. A fault that "
        "starts at 600 s is invisible in a 300 s run.",
        typical="600–86400 s",
    ),
)

BATTERY_CARDS: tuple[ModelCard, ...] = (
    ModelCard(
        id="battery.cell",
        component="batteries",
        title="The cell model",
        one_line="One cell as a voltage source behind two resistances, plus a "
        "temperature.",
        what=(
            "Each cell is modelled as an ideal voltage that depends only on how "
            "full it is, minus two losses: one instantaneous, one that builds and "
            "fades over seconds. Separately, it warms up from its own losses and "
            "cools toward its surroundings. That is the whole model — five state "
            "variables and no lookup tables."
        ),
        why=(
            "It is small enough to reason about and rich enough to produce the "
            "behaviours that actually matter: voltage sag under load, recovery at "
            "rest, self-heating that grows with the square of current, and cells "
            "that drift apart from each other."
        ),
        source="simura.sim.pack",
        equation="V = OCV(SoC) − I·R₀ − V_rc",
        assumptions=(
            "One temperature per cell — no internal gradients.",
            "Parameters do not change with temperature or age within a run.",
            "One RC pair, so one slow time constant rather than a spectrum of them.",
        ),
        limits=(
            "It will not predict calendar ageing, gas generation, or anything "
            "chemical. Degradation is something you inject, not something it grows.",
            "The voltage-versus-charge curves are realistic in shape but are not "
            "any specific manufacturer's cell. Fit your own before trusting a "
            "number.",
            "Above the safe envelope it keeps integrating rather than modelling "
            "what a real cell would actually do, which is stop being a cell.",
        ),
        params=_CELL_PARAMS,
        reads_like={
            "electrical": "A DC source with series resistance and one RC lag, "
            "where the source voltage drifts as the thing discharges.",
            "thermal": "A single lumped mass with an internal heat source "
            "proportional to I² and a linear loss to ambient.",
            "operations": "A battery that sags when you load it, recovers when you "
            "stop, and warms up while you use it.",
        },
        see_also=("battery.pack", "battery.thermal", "battery.ocv"),
    ),
    ModelCard(
        id="battery.ocv",
        component="batteries",
        title="Open-circuit voltage",
        one_line="A cell's resting voltage as a function of how full it is — the "
        "chemistry's fingerprint.",
        what=(
            "The voltage a cell settles at with nothing connected, plotted against "
            "state of charge. Every chemistry has its own shape, and the shape is "
            "what distinguishes them from the outside."
        ),
        why=(
            "It is the only route from a voltage you can measure to a charge level "
            "you cannot. A sloped curve means voltage tells you where you are; a "
            "flat one means it barely does, which is why LFP systems need coulomb "
            "counting far more than NMC ones."
        ),
        source="simura.sim.ocv",
        equation="OCV = f(SoC), interpolated from the chemistry's table",
        assumptions=(
            "No hysteresis between charge and discharge.",
            "No temperature dependence.",
        ),
        limits=(
            "The bundled curves are illustrative — right in shape and range, not "
            "traceable to a datasheet.",
        ),
        reads_like={
            "electrical": "The source voltage of the equivalent circuit, as a "
            "function of remaining charge.",
            "operations": "A fuel gauge that reads voltage — accurate for some "
            "chemistries and nearly useless for others.",
        },
        see_also=("battery.cell",),
    ),
    ModelCard(
        id="battery.thermal",
        component="batteries",
        title="The heat balance",
        one_line="A cell's temperature is the running total of the heat it makes "
        "minus the heat it sheds.",
        what=(
            "Heat comes from three places: resistance to the current flowing "
            "through the cell, the slow polarisation loss, and anything a fault "
            "adds. It leaves one way: conduction to the surroundings, in "
            "proportion to how far above them the cell already is. Temperature is "
            "just the integral of the difference."
        ),
        why=(
            "Almost every failure worth catching is thermal, and this equation is "
            "why they are catchable: because cooling scales with temperature rise "
            "while ohmic heating does not, a healthy cell always finds an "
            "equilibrium, and a cell that does not find one is telling you "
            "something. This is the equation the explainer decomposes."
        ),
        source="simura.sim.pack",
        equation="C_th·dT/dt = I²·R₀ + I·V_rc + Q_fault − k·(T − T_ambient)",
        assumptions=(
            "Cells do not heat each other — each one only sees ambient.",
            "Cooling is linear in temperature difference (no radiation term).",
            "Reversible entropic heat is ignored; only irreversible losses count.",
        ),
        limits=(
            "Cell-to-cell thermal coupling is absent, so it will not show you "
            "propagation from one cell to the next.",
            "Thermal runaway is injected as a temperature-dependent heat source, "
            "not derived from decomposition chemistry.",
        ),
        reads_like={
            "thermal": "A first-order lumped-capacitance node with an I²R source "
            "and a linear sink.",
            "safety": "The margin between heat in and heat out — and how fast it "
            "is closing.",
            "operations": "Why a cell gets hot, and whether it will level off.",
        },
        see_also=("battery.cell", "battery.faults"),
    ),
    ModelCard(
        id="battery.pack",
        component="batteries",
        title="Series and parallel assembly",
        one_line="Cells in parallel share a node and divide current by "
        "conductance; modules in series carry the same current.",
        what=(
            "Every cell in a parallel group is wired to the same two points, so "
            "they all sit at one voltage and the current divides between them "
            "according to how easily each conducts. Each series module then "
            "carries the whole pack current, and pack voltage is the sum of the "
            "module voltages. The solve is exact, not an average."
        ),
        why=(
            "This is what makes a pack behave differently from one big cell. A "
            "weak cell in a parallel group is not simply a smaller cell — it takes "
            "less current, its neighbours take more, and the group's imbalance "
            "feeds back on itself. Nothing about that is visible in a model that "
            "averages."
        ),
        source="simura.sim.pack",
        equation="Σₚ (OCV − V_rc − V_module)/R₀ = I_module",
        assumptions=(
            "Interconnect resistance is zero — the busbars are perfect.",
            "Every series module carries exactly the pack current.",
        ),
        limits=(
            "No busbar or weld resistance, so real-world module-to-module "
            "imbalance from interconnects is not represented.",
            "No balancing hardware. Cells drift apart and nothing brings them back.",
        ),
        params=_PACK_PARAMS,
        reads_like={
            "electrical": "A ladder of parallel current dividers solved node by "
            "node.",
            "operations": "Why one slot in a module is always the hot one.",
        },
        see_also=("battery.cell", "battery.imbalance"),
    ),
    ModelCard(
        id="battery.imbalance",
        component="batteries",
        title="Voltage imbalance",
        one_line="The spread between the highest and lowest cell voltage — the "
        "cheapest early warning a pack gives you.",
        what=(
            "One number: highest cell voltage minus lowest. It grows when cells "
            "differ in charge, in resistance, or in what is being done to them."
        ),
        why=(
            "It is the pack's usable range, expressed as a defect. A pack stops "
            "charging when its highest cell is full and stops discharging when its "
            "lowest is empty, so spread is capacity you own and cannot reach. It "
            "also rises before anything else does when a single cell starts "
            "misbehaving."
        ),
        source="simura.sim.telemetry",
        equation="ΔV = max(V_cell) − min(V_cell)",
        assumptions=("Measured at the terminals, so it includes IR differences, "
                     "not only charge differences.",),
        limits=(
            "It says a pack is uneven, never which cell is at fault or why — that "
            "is what the anomaly and diagnosis layers are for.",
        ),
        reads_like={
            "operations": "How much of the pack you can't use.",
            "safety": "The first number that moves when one cell starts to go.",
        },
        see_also=("battery.pack", "twin.anomaly"),
    ),
    ModelCard(
        id="battery.faults",
        component="batteries",
        title="Fault injection",
        one_line="Five ways a cell goes wrong, each one a change to a term the "
        "model already has.",
        what=(
            "A fault is not a special case bolted onto the simulator. Each one "
            "moves a coefficient that was already in the equations: an internal "
            "short adds a parasitic current path, resistance growth multiplies R₀, "
            "a cooling fault scales the cooling term down, runaway adds a "
            "temperature-dependent heat source, and sensor drift biases what is "
            "*reported* without touching what the cell does."
        ),
        why=(
            "Because faults act through the ordinary terms, their consequences "
            "come out of the physics rather than being scripted. That is what "
            "makes the resulting data honest enough to develop detection against "
            "— and it is why sensor drift is applied at the telemetry boundary and "
            "nowhere else: a faulty sensor changes the measurement, not the cell."
        ),
        source="simura.sim.faults",
        assumptions=("A fault begins at a scheduled time and then persists.",),
        limits=(
            "Faults are per-cell. There is no fault that affects the pack as a "
            "whole, and none that propagate.",
        ),
        params=(
            ParamCard(
                key="internal_short",
                label="Internal short",
                unit="",
                what="A resistive path inside the cell that drains it and heats it "
                "from within.",
                why="The classic dangerous failure. Its signature is a cell that is "
                "both losing charge faster than its neighbours and hotter than "
                "them — which is what makes it distinguishable from anything else.",
                feel="Lower the short resistance and it drains and heats harder.",
            ),
            ParamCard(
                key="resistance_growth",
                label="Resistance growth",
                unit="",
                what="The cell's internal resistance multiplied up, as ageing or a "
                "bad connection would.",
                why="It is what state-of-health estimation is actually measuring. "
                "It costs voltage under load and makes extra heat, but unlike a "
                "short it does not drain the cell at rest.",
                feel="Turn the multiplier up and the cell sags and heats, but "
                "keeps its charge.",
            ),
            ParamCard(
                key="cooling_fault",
                label="Cooling loss",
                unit="",
                what="The cell's ability to shed heat, scaled down — a blocked "
                "duct, a failed fan, a dry thermal pad.",
                why="It generates no extra heat at all, and still overheats the "
                "cell. That is the diagnostic distinction: hot, but with normal "
                "voltage and normal charge behaviour.",
                feel="Cut effectiveness to a fifth and steady-state rise goes up "
                "roughly fivefold.",
            ),
            ParamCard(
                key="thermal_runaway",
                label="Thermal runaway",
                unit="",
                what="A heat source that grows with temperature past a trigger "
                "point, so heating feeds itself.",
                why="It is the one fault where the balance never closes: above the "
                "trigger, heat generated rises faster than heat shed, and there is "
                "no equilibrium to find. This is what the safety alarm exists for.",
                feel="Lower the trigger temperature and an ordinary run tips over "
                "into it.",
            ),
            ParamCard(
                key="sensor_drift",
                label="Sensor drift",
                unit="",
                what="A bias added to a reported voltage or temperature. The cell "
                "is fine; the measurement is not.",
                why="It is the fault that teaches you not to trust telemetry "
                "uncritically, and the reason diagnosis has to weigh several "
                "signals — a drifting sensor looks alarming on one channel and "
                "perfectly normal on every other.",
                feel="Add an offset and one channel diverges while the physics "
                "stays put.",
            ),
        ),
        reads_like={
            "safety": "The five failure modes, and the fingerprint each leaves.",
            "operations": "What breaking it on purpose looks like.",
        },
        see_also=("battery.thermal", "twin.diagnosis"),
    ),
    ModelCard(
        id="battery.profile",
        component="batteries",
        title="Load profiles",
        one_line="What the system is being asked to do: a steady current, a steady "
        "power, a cycle, or a swell.",
        what=(
            "The load profile is the demand side of the simulation — the current "
            "the pack has to supply at each instant. Four shapes cover most of "
            "what people want to see."
        ),
        why=(
            "Nothing in a battery is interesting at rest. The profile is what "
            "produces the heat, the sag and the imbalance, and choosing it "
            "carelessly is the most common way to run a simulation that shows "
            "nothing."
        ),
        source="simura.sim.profiles",
        limits=(
            "Profiles are open-loop: the pack is asked for a current regardless of "
            "whether it can safely deliver it. There is no BMS saying no.",
        ),
        params=(
            ParamCard(
                key="constant_current",
                label="Constant current",
                unit="A",
                what="A fixed current, positive to discharge.",
                why="The cleanest way to see one effect at a time, and the basis "
                "of most characterisation tests.",
            ),
            ParamCard(
                key="constant_power",
                label="Constant power",
                unit="W",
                what="A fixed power draw, so current rises as voltage falls.",
                why="What a real load actually does — and it means the end of a "
                "discharge is harder on the pack than the start, which constant "
                "current never shows you.",
            ),
            ParamCard(
                key="cycle",
                label="Charge–discharge cycle",
                unit="",
                what="Discharge, rest, charge, rest, repeat.",
                why="The shape almost every storage system really lives, and the "
                "one where imbalance and drift accumulate visibly.",
            ),
            ParamCard(
                key="sinusoidal",
                label="Sinusoidal",
                unit="",
                what="A mean current with a sine swing on top.",
                why="Stands in for a fluctuating grid or duty load, and excites the "
                "slow polarisation branch in a way steady current cannot.",
            ),
        ),
        see_also=("battery.cell",),
    ),
    ModelCard(
        id="battery.run",
        component="batteries",
        title="Running a system",
        one_line="Identity, chemistry, and how long to simulate at what timestep.",
        what="The bookkeeping around a run: what the system is called, which "
        "chemistry it uses, and the time grid the solver walks.",
        why="These settle before any physics does, and getting the timestep or "
        "duration wrong is the quickest way to a result that means nothing.",
        source="simura.builder.spec",
        limits=("The integrator is explicit, so too large a timestep degrades "
                "quietly rather than failing loudly.",),
        params=_RUN_PARAMS,
        see_also=("battery.cell", "battery.pack"),
    ),
)


# --------------------------------------------------------------------------
# Wires
# --------------------------------------------------------------------------

_WIRE_PARAMS = (
    ParamCard(
        key="material",
        label="Conductor material",
        unit="",
        what="What the conductor is made of, which sets its resistivity and how "
        "much that resistivity changes with temperature.",
        why="Aluminium is roughly 60% as conductive as copper, so the same job "
        "needs about two gauge sizes more of it. It is also cheaper and lighter, "
        "which is why the trade is worth making at all.",
        typical="copper or aluminium",
    ),
    ParamCard(
        key="awg",
        label="Gauge (AWG)",
        unit="AWG",
        what="American Wire Gauge — a size number that runs backwards: smaller "
        "number, thicker wire.",
        why="It is the lever with the most leverage. Resistance is inversely "
        "proportional to area, and each three gauge sizes roughly doubles the area "
        "— so dropping three sizes halves your losses.",
        typical="18 to 4/0",
        feel="Go down three gauge numbers and voltage drop and heating halve.",
    ),
    ParamCard(
        key="area_mm2",
        label="Cross-section",
        unit="mm²",
        what="The conductor's cross-sectional area, stated directly instead of as "
        "a gauge number.",
        why="It is what the physics actually uses — gauge is only a naming scheme "
        "over it, and most of the world sizes cable this way.",
        typical="1.5–240 mm²",
        feel="Double it and resistance halves.",
    ),
    ParamCard(
        key="length_m",
        label="Run length",
        unit="m",
        what="How far the conductor runs.",
        why=(
            "The most under-considered number in wiring. Resistance is directly "
            "proportional to it, so a run that is twice as long has twice the "
            "voltage drop and twice the loss — and on long low-voltage runs, "
            "length rather than current is usually what decides the gauge."
        ),
        typical="1–200 m",
        feel="Double it and both the voltage drop and the wasted power double.",
    ),
    ParamCard(
        key="insulation",
        label="Insulation class",
        unit="",
        what="The jacket type, which sets the temperature the conductor is allowed "
        "to reach.",
        why="It does not change the physics at all — it changes what counts as a "
        "failure. A 90 °C jacket lets the same copper carry meaningfully more "
        "current than a 60 °C one.",
        typical="PVC-70, PVC-90, XLPE-90, silicone-200",
    ),
    ParamCard(
        key="ampacity_a",
        label="Ampacity",
        unit="A",
        what="The current this conductor is rated to carry continuously.",
        why="It is a thermal limit wearing an electrical disguise: the current at "
        "which the conductor reaches its insulation's temperature rating in the "
        "reference conditions. Left unset, it comes from the catalog.",
        typical="set by gauge and insulation",
    ),
    ParamCard(
        key="ambient_temp_c",
        label="Ambient temperature",
        unit="°C",
        what="The temperature around the conductor.",
        why=(
            "It attacks twice. It is the baseline the conductor's own heating adds "
            "to, and it eats the headroom to the insulation rating — so ampacity "
            "must be derated for it. A cable that is fine in a basement can be "
            "over its limit in a hot roof space at the same current."
        ),
        typical="20–45 °C",
    ),
    ParamCard(
        key="thermal_capacity_j_per_k",
        label="Thermal mass",
        unit="J/K",
        what="How much energy it takes to warm the whole run by one degree. "
        "Estimated from the conductor's own mass if left unset.",
        why="It decides whether a surge is survivable. A heavy cable rides out a "
        "short overload that would take a thin one straight to its rating.",
        typical="estimated from geometry",
    ),
    ParamCard(
        key="cooling_conductance_w_per_k",
        label="Cooling conductance",
        unit="W/K",
        what="How many watts the run sheds per degree above ambient. Estimated "
        "from surface area if left unset.",
        why="It sets the steady-state temperature for a given loss, so it is half "
        "of what ampacity means. Bundling cables or burying them cuts it sharply.",
        typical="estimated from geometry",
    ),
    ParamCard(
        key="convection_coeff_w_m2_k",
        label="Convection coefficient",
        unit="W/m²K",
        what="How effectively the surrounding air carries heat off the surface.",
        why="It is the one knob that says whether this run is in still air, in a "
        "breeze, or in a conduit — and the difference between them is a factor of "
        "several in how hot the cable gets.",
        typical="5–25 W/m²K",
    ),
    ParamCard(
        key="wire_type",
        label="Catalog wire type",
        unit="",
        what="A named catalog entry that fills in material, gauge, insulation and "
        "ampacity in one go.",
        why="It saves you from specifying a real cable field by field, and any "
        "field you do set explicitly still wins.",
        typical="e.g. thhn-12-cu",
    ),
)

WIRE_CARDS: tuple[ModelCard, ...] = (
    ModelCard(
        id="wires.resistance",
        component="wires",
        title="Conductor resistance",
        one_line="Resistivity times length over area — and resistivity depends on "
        "temperature.",
        what=(
            "A conductor's resistance is its material's resistivity multiplied by "
            "how far the current has to travel, divided by how much metal it has "
            "to travel through. The resistivity itself rises with temperature, "
            "which is why the answer depends on how hard the cable is working."
        ),
        why=(
            "Every wiring question reduces to this number. Voltage drop is current "
            "times it; wasted power is current squared times it; the heat that "
            "sets the cable's temperature is that same wasted power. Get this "
            "right and the rest follows."
        ),
        source="simura.wires.wire",
        equation="R = ρ₂₀·[1 + α·(T − 20)]·L / A",
        assumptions=(
            "DC — no skin effect and no proximity effect.",
            "Resistivity varies linearly with temperature.",
            "Uniform temperature along the whole run.",
        ),
        limits=(
            "Not valid at high AC frequencies, where current stops using the "
            "middle of the conductor.",
            "Solid-conductor geometry; stranding and lay length are ignored.",
        ),
        params=_WIRE_PARAMS,
        reads_like={
            "electrical": "R = ρL/A with a linear temperature coefficient.",
            "thermal": "The source term of the cable's heat balance, and one that "
            "grows as the cable heats.",
            "operations": "Why a long thin cable wastes power and a short fat one "
            "doesn't.",
        },
        see_also=("wires.drop", "wires.thermal", "wires.ampacity"),
    ),
    ModelCard(
        id="wires.drop",
        component="wires",
        title="Voltage drop",
        one_line="The voltage the load never sees, because the cable used it up.",
        what=(
            "Current through resistance loses voltage. What arrives at the load is "
            "what left the source minus that loss — and on a round trip you pay it "
            "twice, once out and once back."
        ),
        why=(
            "On low-voltage systems this, not ampacity, is almost always what "
            "decides the gauge. Three percent of 400 V is 12 V and nobody notices; "
            "three percent of 12 V is 360 mV and your equipment browns out. The "
            "same cable that is thermally fine can be electrically useless."
        ),
        source="simura.wires.planning",
        equation="ΔV = I·R·(2 if round-trip else 1)",
        assumptions=("Resistive drop only — no inductive component.",),
        limits=(
            "The percentage is against a nominal system voltage you supply, not "
            "against a measured source voltage.",
        ),
        reads_like={
            "electrical": "I·R across the run, doubled for the return conductor.",
            "operations": "How much voltage goes missing between the source and "
            "the thing you plugged in.",
        },
        see_also=("wires.resistance",),
    ),
    ModelCard(
        id="wires.thermal",
        component="wires",
        title="Conductor heat balance",
        one_line="The cable's temperature rise is its own losses divided by how "
        "well it sheds them.",
        what=(
            "The cable heats itself with the power it wastes, sheds heat to the "
            "air in proportion to how far above ambient it has got, and settles "
            "where the two match. Sun adds heat; wind takes it away faster."
        ),
        why=(
            "It is the same balance as the battery's, and it is why ampacity is a "
            "real limit rather than a conservative guess: the rated current is "
            "simply the current at which this balance settles at the insulation's "
            "temperature. There is also a feedback here — a hotter conductor is a "
            "more resistive one, which wastes more power, which heats it further."
        ),
        source="simura.wires.wire",
        equation="I²·R(T) + Q_solar = k·(T − T_ambient)",
        assumptions=(
            "The whole run is at one temperature.",
            "Convective cooling only; no radiation term.",
        ),
        limits=(
            "No conduit fill, bundling or burial derating — a cable in free air is "
            "the only case modelled.",
        ),
        reads_like={
            "thermal": "A steady-state balance with a temperature-dependent source.",
            "electrical": "Why the resistance you measured cold is not the one "
            "you'll run at.",
        },
        see_also=("wires.resistance", "wires.ampacity"),
    ),
    ModelCard(
        id="wires.ampacity",
        component="wires",
        title="Ampacity and derating",
        one_line="The safe continuous current — and why it falls on a hot day.",
        what=(
            "The rated current that brings this conductor to its insulation's "
            "temperature limit under reference conditions, corrected for the "
            "ambient you actually have."
        ),
        why=(
            "The correction is not a safety fudge, it falls straight out of the "
            "heat balance: if allowed heating is proportional to the headroom "
            "between ambient and the rating, and heating goes as current squared, "
            "then safe current goes as the square root of the headroom. Lose half "
            "your headroom and you lose 30% of your ampacity."
        ),
        source="simura.wires.wire",
        equation="I_derated = I_rated · √[(T_rating − T_ambient) / (T_rating − T_ref)]",
        assumptions=("The reference ambient behind the catalog rating is 30 °C.",),
        limits=(
            "Ambient derating only. Grouping, conduit fill and burial factors are "
            "not applied.",
            "Wind is deliberately not credited to the rating — it lowers the "
            "predicted temperature but does not raise the safe current.",
        ),
        reads_like={
            "safety": "The current above which the jacket is being cooked.",
            "operations": "How much current this cable can carry where it actually "
            "is, not where it was tested.",
        },
        see_also=("wires.thermal",),
    ),
    ModelCard(
        id="wires.faults",
        component="wires",
        title="Wiring faults",
        one_line="The ways cable installations really fail — mostly slowly.",
        what=(
            "Corrosion and loose joints add resistance where the model already has "
            "resistance; conductor damage removes cross-section; insulation ageing "
            "lowers the temperature the cable is allowed to reach; a ground fault "
            "leaks current away before it reaches the load."
        ),
        why=(
            "Wiring rarely fails suddenly. It develops — which means the "
            "interesting question is not 'is it broken' but 'how far along is it', "
            "and that only has an answer if the fault grows with time, which these "
            "do."
        ),
        source="simura.wires.faults",
        limits=("Faults act on a whole run or segment, not at a located point "
                "along it.",),
        reads_like={
            "safety": "Where a run stops being the run you designed.",
            "operations": "Why a circuit that was fine last year isn't.",
        },
        see_also=("wires.resistance",),
    ),
)


# --------------------------------------------------------------------------
# Lights
# --------------------------------------------------------------------------

_LIGHT_PARAMS = (
    ParamCard(
        key="technology",
        label="Source technology",
        unit="",
        what="What kind of light source this is — a filament, a semiconductor "
        "junction, or an arc in a gas.",
        why="It selects which of three completely different electrical laws "
        "applies. Everything photometric downstream is the same chain; the way the "
        "source turns watts into a spectrum is not.",
        typical="led, halogen, fluorescent, metal_halide, …",
    ),
    ParamCard(
        key="lamp_type",
        label="Catalog lamp",
        unit="",
        what="A named real lamp, which fills technology, power, beam and published "
        "flux at once.",
        why="It is also how the model gets checked: the published flux is carried "
        "for comparison and never used in the calculation.",
        typical="e.g. led-a19-9w",
    ),
    ParamCard(
        key="power_w",
        label="Rated power",
        unit="W",
        what="System power drawn from the supply, including any control gear.",
        why="It is the denominator of efficacy and the number an energy code is "
        "written against. Including the gear matters — a fluorescent ballast can be "
        "10% of the total.",
        typical="5–400 W",
    ),
    ParamCard(
        key="supply_voltage_v",
        label="Supply voltage",
        unit="V",
        what="The voltage the lamp is actually running on.",
        why="A filament on low volts is dramatically worse than proportionally "
        "dimmer: it runs cooler, so it radiates less and shifts what it does "
        "radiate into the infrared where the eye cannot use it.",
        typical="12, 120, or 230 V",
        feel="Drop a filament lamp 10% in voltage and lose about 30% of its light.",
    ),
    ParamCard(
        key="beam_angle_deg",
        label="Beam angle",
        unit="°",
        what="The full cone the light is emitted into; 360° means all directions.",
        why="It converts lumens into candela. The same lamp in a narrow beam is "
        "far brighter where it points and useless everywhere else — beam angle is "
        "the difference between a spotlight and a room light.",
        typical="15–120°, or 360",
        feel="Halve the angle and roughly quadruple the intensity on-axis.",
    ),
    ParamCard(
        key="ambient_temp_c",
        label="Ambient temperature",
        unit="°C",
        what="The temperature around the lamp.",
        why=(
            "Different technologies respond in opposite directions, which is the "
            "single most counter-intuitive thing in lighting. An LED loses output "
            "as it warms because its junction gets hotter; a fluorescent lamp "
            "*gains* output up to about 25 °C because its mercury vapour pressure "
            "is still climbing to the optimum."
        ),
        typical="0–45 °C",
    ),
    ParamCard(
        key="thermal_resistance_k_per_w",
        label="Thermal resistance",
        unit="K/W",
        what="How many degrees the source rises above ambient per watt of heat it "
        "has to get rid of.",
        why="For an LED this is the heatsink, and it is the whole ballgame: a "
        "junction that runs hot is dimmer, shifts colour, and dies sooner. A "
        "heatsink fault is modelled by making this number worse.",
        typical="2–15 K/W for an LED",
    ),
    ParamCard(
        key="thermal_mass_j_per_k",
        label="Thermal mass",
        unit="J/K",
        what="How much energy it takes to warm the source by a degree.",
        why="It sets warm-up time. It is why an LED is at full output instantly, a "
        "fluorescent takes a minute, and a metal halide takes several.",
        typical="0.5–50 J/K",
    ),
    ParamCard(
        key="envelope_transmission",
        label="Envelope transmission",
        unit="fraction",
        what="The fraction of light that gets out through the glass or lens.",
        why="A straightforward multiplier on everything the source makes, and one "
        "of the few places where a lamp loses light for purely mechanical reasons.",
        typical="0.85–0.97",
    ),
    ParamCard(
        key="radiant_efficiency",
        label="Radiant efficiency",
        unit="fraction",
        what="The share of electrical power that leaves as radiation of any "
        "wavelength, visible or not.",
        why=(
            "It is the first of the two factors that make up efficacy, and it is "
            "worth separating from the second. A filament is actually excellent at "
            "this — most of its power does leave as radiation. It is just that "
            "almost all of it is infrared."
        ),
        typical="0.1–0.9",
    ),
    ParamCard(
        key="control_gear_loss_frac",
        label="Control gear loss",
        unit="fraction",
        what="The share of input power the driver or ballast consumes before the "
        "source sees any of it.",
        why="It is pure overhead that still counts against the system efficacy, "
        "and it is why lamp-only numbers flatter a fixture.",
        typical="0.0–0.15",
    ),
    ParamCard(
        key="design_filament_k",
        label="Design filament temperature",
        unit="K",
        what="The temperature the filament is meant to run at, from which the "
        "model back-solves the filament's geometry.",
        why=(
            "It is the whole incandescent trade-off in one number. Hotter is more "
            "efficacious and whiter, because more of the blackbody curve lands in "
            "the visible — and it is also shorter-lived, because tungsten "
            "evaporates faster. Halogen exists precisely to move this number up."
        ),
        typical="2700–3200 K",
        feel="Raise it and you get more light per watt, and fewer hours.",
    ),
    ParamCard(
        key="operating_hours_h",
        label="Operating hours",
        unit="h",
        what="Hours the lamp has already been lit when the simulation starts.",
        why="It lets you evaluate an installation as it will be in five years "
        "without simulating five years. Lighting is designed for the end of the "
        "maintenance cycle, so this is usually the number that matters.",
        typical="0–50000 h",
    ),
    ParamCard(
        key="switch_cycles",
        label="Switch cycles",
        unit="count",
        what="How many times the lamp has been switched on.",
        why="Some technologies age by the hour and some by the switch. A "
        "fluorescent lamp in a toilet with an occupancy sensor dies of cycles long "
        "before it dies of hours.",
        typical="0–20000",
    ),
    ParamCard(
        key="dirt_depreciation_frac",
        label="Dirt depreciation",
        unit="fraction",
        what="How much light the luminaire has lost to dirt on its lens and "
        "housing.",
        why="It is the least glamorous and most reliable way an installation loses "
        "light — and unlike lamp depreciation, it is entirely recoverable by "
        "someone with a cloth.",
        typical="0.05–0.25 depending on how dirty the space is",
    ),
)

LIGHT_CARDS: tuple[ModelCard, ...] = (
    ModelCard(
        id="lights.spectrum",
        component="lights",
        title="Spectrum and efficacy",
        one_line="Light is a spectrum; how bright it looks is that spectrum "
        "weighted by what the eye can see.",
        what=(
            "The model describes a source as power spread across wavelengths, then "
            "weights it by the standard curve of human visual sensitivity to get "
            "lumens. Colour and colour temperature come out of the same spectrum, "
            "by the same route."
        ),
        why=(
            "This is the decision the whole lighting component is built on: "
            "efficacy is **computed, never looked up**. Nothing in the code says a "
            "dimmed filament goes orange or that sodium renders colour badly — "
            "those fall out of the spectrum. It is what makes the model predict "
            "lamps it has never been shown, rather than recite ones it has."
        ),
        source="simura.lights.spectrum",
        equation="Φ = 683 · ∫ P(λ)·V(λ) dλ",
        assumptions=(
            "The CIE 1931 standard observer represents the eye.",
            "Photopic (daylight-adapted) vision throughout.",
        ),
        limits=(
            "No scotopic or mesopic weighting, so night-adapted vision is not "
            "represented.",
            "Colour rendering is estimated rather than computed from the full "
            "test-colour sample method.",
        ),
        reads_like={
            "lighting": "Luminous efficacy of radiation from the SPD, via V(λ).",
            "electrical": "How many watts of the right kind of radiation you got "
            "for your watts of electricity.",
            "newcomer": "Two lamps can use the same power and one still looks "
            "twice as bright, because brightness is about which colours the power "
            "came out as.",
        },
        see_also=("lights.lamp", "lights.lumen_method"),
    ),
    ModelCard(
        id="lights.lamp",
        component="lights",
        title="The lamp model",
        one_line="Three electrical laws — filament, junction, arc — feeding one "
        "shared photometric chain.",
        what=(
            "How a source turns electricity into a spectrum depends on what it is. "
            "A filament solves a heat balance and glows at whatever temperature it "
            "settles at. A junction obeys a diode law and loses output as it heats. "
            "An arc holds a roughly fixed voltage and needs time to warm up before "
            "it reaches full output. After that, all three go through the same "
            "spectral chain."
        ),
        why=(
            "Keeping the electrical part separate from the photometric part is "
            "what lets one model span a fifteen-fold range of efficacy without "
            "special cases, and it is why the emergent behaviours are right: a "
            "dimmed filament losing far more light than power, an LED and a "
            "fluorescent derating in opposite directions, a hot arc lamp refusing "
            "to restrike."
        ),
        source="simura.lights.lamp",
        assumptions=(
            "One temperature for the whole source.",
            "Lamps are driven at or near their rated operating point unless told "
            "otherwise.",
        ),
        limits=(
            "No flicker waveform or modulation depth — a lamp is either lit or not.",
            "Lamp lifetime is modelled as depreciation, not as a failure "
            "distribution.",
        ),
        params=_LIGHT_PARAMS,
        reads_like={
            "electrical": "Three source laws — resistive, diode, and constant-"
            "voltage-with-ballast.",
            "thermal": "Every one of the three is really a heat balance wearing "
            "different clothes.",
        },
        see_also=("lights.spectrum", "lights.faults"),
    ),
    ModelCard(
        id="lights.lumen_method",
        component="lights",
        title="The lumen method",
        one_line="Average light on a work surface: total lumens, times what "
        "reaches it, times what survives, over the floor area.",
        what=(
            "The standard way to size a lighting installation. Take every "
            "luminaire's lumens, keep the fraction that reaches the working plane "
            "(the utilisation factor, which depends on the room's shape and how "
            "reflective its surfaces are), multiply by the fraction still working "
            "at the end of the maintenance cycle, and divide by the floor area."
        ),
        why=(
            "It is how lighting is actually designed, and it is a product of four "
            "independent factors — which means when a room is underlit, exactly one "
            "of them is usually to blame, and it is often not the one people reach "
            "for. Buying brighter lamps does not fix a dirty luminaire."
        ),
        source="simura.lights.photometry",
        equation="E_avg = (N · Φ · UF · LLF) / A",
        assumptions=(
            "Luminaires are spread evenly over the ceiling.",
            "Surfaces are diffuse reflectors.",
            "The utilisation factor is a fitted curve, not a manufacturer's "
            "photometric file.",
        ),
        limits=(
            "It gives an average and says nothing about uniformity — use the "
            "illuminance field for that.",
            "It is good to a few percent for ordinary rooms and quite wrong for "
            "unusual ones. Design real installations from the luminaire's own "
            "photometric data.",
        ),
        params=(
            ParamCard(
                key="room_index",
                label="Room index",
                unit="",
                what="The room's shape as one number: floor area over the "
                "perimeter times the mounting height above the working plane.",
                why="A tall narrow room wastes light on its walls; a wide shallow "
                "one uses it. This is the number that says which you have, and it "
                "is why raising the luminaires costs you light twice over.",
                typical="0.6–5",
            ),
            ParamCard(
                key="utilisation_factor",
                label="Utilisation factor",
                unit="fraction",
                what="The share of a luminaire's lumens that actually lands on the "
                "working plane.",
                why="It is where most of the light goes missing, and it depends on "
                "the room rather than the fitting — the same luminaire is far more "
                "effective in a wide bright room than a tall dark one.",
                typical="0.3–0.7",
            ),
            ParamCard(
                key="light_loss_factor",
                label="Light loss factor",
                unit="fraction",
                what="What is left after lamp depreciation, dirt, and the lamps "
                "that have failed.",
                why="Lighting is designed for the *end* of the maintenance cycle, "
                "not day one. Ignore this and every installation you design is "
                "underlit for most of its life.",
                typical="0.7–0.9",
            ),
            ParamCard(
                key="target_lux",
                label="Target illuminance",
                unit="lux",
                what="How much light the task actually needs.",
                why="It is a property of the work, not of the room — 500 lux for "
                "an office, 100 for a corridor, 1000 for detailed inspection. "
                "Design to the task and the rest is arithmetic.",
                typical="100–1000 lux",
            ),
        ),
        reads_like={
            "lighting": "The standard lumen-method calculation.",
            "operations": "Whether the room will be bright enough, and which of "
            "four things to fix if it isn't.",
            "newcomer": "Lumens are how much light a lamp makes; lux is how much "
            "of it lands where you are working.",
        },
        see_also=("lights.spectrum", "lights.field"),
    ),
    ModelCard(
        id="lights.field",
        component="lights",
        title="The illuminance field",
        one_line="Light at every point, not just on average — which is where "
        "uniformity lives.",
        what=(
            "Two contributions summed across a grid: light arriving straight from "
            "each luminaire (which falls off with the square of distance and with "
            "the cosine of the angle it strikes at), and light that has bounced off "
            "the room's surfaces, added uniformly."
        ),
        why=(
            "An average hides the thing people actually complain about. A room can "
            "hit its target lux on average and still be unpleasant, because half "
            "of it is in pools of glare and the other half in gloom. The minimum "
            "over the average — the uniformity ratio — is the number that catches "
            "it, and only a field can give you one."
        ),
        source="simura.lights.layout",
        equation="E = Σᵢ (Iᵢ·cos θ / d²) + E_interreflected",
        assumptions=(
            "Point sources with a symmetric distribution.",
            "The bounced component is uniform over the plane.",
            "No obstructions or shadowing.",
        ),
        limits=(
            "No aiming, no asymmetric or roadway distributions, no real "
            "photometric file import.",
            "Interreflection is a single uniform term, not a radiosity solve.",
        ),
        reads_like={
            "lighting": "Direct component from inverse-square and cosine, plus a "
            "split-flux interreflected term.",
            "newcomer": "Bright directly under each fitting, dimmer between them — "
            "and the gap between the two is what makes a room feel badly lit.",
        },
        see_also=("lights.lumen_method",),
    ),
    ModelCard(
        id="lights.faults",
        component="lights",
        title="Lighting faults",
        one_line="How installations lose light — nearly always gradually, and "
        "nearly always unnoticed.",
        what=(
            "Lamp lumen depreciation, phosphor degradation, a failed heatsink, a "
            "driver fault, supply sag, flicker, a fouled lens, and outright "
            "burnout."
        ),
        why=(
            "Lighting is the domain where failure is least visible, because eyes "
            "adapt. A room that has lost 40% of its light over three years looks "
            "normal to everyone in it. Modelling the gradual modes is the point — "
            "the sudden one is the easy case."
        ),
        source="simura.lights.faults",
        limits=("Faults apply per luminaire; there is no supply-level or "
                "circuit-level fault.",),
        reads_like={
            "operations": "Why the room is dimmer than the design said, and which "
            "of these to check first.",
        },
        see_also=("lights.lamp", "lights.lumen_method"),
    ),
)


# --------------------------------------------------------------------------
# The twin itself
# --------------------------------------------------------------------------

TWIN_CARDS: tuple[ModelCard, ...] = (
    ModelCard(
        id="twin.anomaly",
        component="twin",
        title="Peer-consensus anomaly detection",
        one_line="A cell is suspicious when it stops behaving like its neighbours "
        "— no thresholds, no training.",
        what=(
            "For each metric, the pack's own median is the expected value and its "
            "median absolute deviation is the expected scatter. A cell's score is "
            "how many scatters away from the median it sits, smoothed over time so "
            "only sustained deviation counts."
        ),
        why=(
            "It needs no training data and no per-asset tuning, because the pack is "
            "its own reference. And it fires early: a cell can be clearly abnormal "
            "relative to its peers while every absolute limit still reads healthy, "
            "which is exactly the window where intervention is cheap."
        ),
        source="simura.detect",
        equation="z = (x − median) / (1.4826 · MAD)",
        assumptions=(
            "Most cells in the pack are healthy at any moment.",
            "Cells are nominally interchangeable, so peer comparison is fair.",
        ),
        limits=(
            "If a fault affects the whole pack uniformly there is no peer left to "
            "notice it.",
            "It says a cell is odd, never why. Diagnosis is a separate step.",
        ),
        reads_like={
            "safety": "Early warning, before any absolute limit is crossed.",
            "operations": "Which cell isn't keeping up with the others.",
        },
        see_also=("twin.diagnosis", "battery.imbalance"),
    ),
    ModelCard(
        id="twin.diagnosis",
        component="twin",
        title="Diagnosis, health and safety",
        one_line="Not just that something is wrong — what, how healthy, how long, "
        "and how dangerous.",
        what=(
            "Each fault type leaves a distinct pattern across the anomaly scores "
            "and health features, and diagnosis matches the live pattern against "
            "those fingerprints. State of health comes from tracking resistance "
            "measured online; time-to-critical comes from the smoothed heating "
            "rate; the safety state is the worst of what all of it implies."
        ),
        why=(
            "'Something is wrong with cell 3' is not actionable. 'Cell 3 has an "
            "internal short, you have eleven minutes' is. The fingerprints are what "
            "separate a hot cell that is losing charge from a hot cell that isn't — "
            "which is the difference between a short and a cooling fault, and "
            "between two entirely different responses."
        ),
        source="simura.health",
        assumptions=(
            "One dominant fault at a time.",
            "Resistance is estimated from the terminal law, so it needs current "
            "flowing to mean anything.",
        ),
        limits=(
            "Time-to-critical extrapolates the current heating rate; it assumes the "
            "future looks like the last few minutes.",
            "No calendar ageing, so state of health tracks resistance growth only.",
        ),
        reads_like={
            "safety": "What is failing, how confident we are, and how long there is.",
            "operations": "Whether to act now or watch it.",
        },
        see_also=("twin.anomaly", "battery.faults"),
    ),
    ModelCard(
        id="twin.weather",
        component="twin",
        title="Weather coupling",
        one_line="Real conditions reaching the model through the terms it already "
        "had.",
        what=(
            "Ambient temperature sets what everything cools toward, wind scales the "
            "cooling term up, and absorbed sunlight adds a heat source. The same "
            "three channels serve batteries, conductors and luminaires — and for "
            "lighting there is a fourth, because daylight is light."
        ),
        why=(
            "It is what makes a simulation about a real place rather than a "
            "laboratory. And because weather acts through the ordinary terms — the "
            "same ones faults act through — the two compose with no special case: a "
            "cooling fault on a hot day is simply both."
        ),
        source="simura.weather",
        assumptions=("Conditions are uniform over the whole system.",),
        limits=(
            "No precipitation, no snow loading, no humidity effect on cooling.",
            "Live weather needs network access; everything else runs offline.",
        ),
        reads_like={
            "operations": "Why the same system behaves differently in July.",
        },
        see_also=("battery.thermal", "wires.thermal"),
    ),
)


ALL_CARDS: tuple[ModelCard, ...] = (
    BATTERY_CARDS + WIRE_CARDS + LIGHT_CARDS + TWIN_CARDS
)

_BY_ID = {c.id: c for c in ALL_CARDS}


def list_cards(component: str | None = None) -> list[ModelCard]:
    """Every card, optionally narrowed to one component."""
    if component is None:
        return list(ALL_CARDS)
    if component not in COMPONENTS:
        raise KeyError(f"unknown component {component!r}; expected one of {COMPONENTS}")
    return [c for c in ALL_CARDS if c.component == component]


def get_card(card_id: str) -> ModelCard:
    try:
        return _BY_ID[card_id]
    except KeyError:
        raise KeyError(f"unknown model card {card_id!r}") from None


def find_param(key: str) -> tuple[ModelCard, ParamCard] | None:
    """The card documenting a parameter, and the parameter's own entry.

    This is the lookup the dashboard uses to put a "why does this matter" next
    to a form field, given only the field's name.
    """
    for card in ALL_CARDS:
        p = card.param(key)
        if p is not None:
            return card, p
    return None


# --------------------------------------------------------------------------
# Coverage: the mechanism that stops the prose drifting from the code
# --------------------------------------------------------------------------

# Fields that exist in the specs but are not user-facing parameters: they are
# structure (nested spec objects) rather than numbers somebody sets, and are
# documented by the card they belong to rather than by a ParamCard.
_STRUCTURAL_FIELDS = {
    "profile",   # documented by battery.profile as a whole
    "faults",    # documented by battery.faults as a whole
    "weather",   # documented by twin.weather as a whole
}


def _spec_fields(cls: type) -> set[str]:
    from dataclasses import fields as dc_fields

    return {f.name for f in dc_fields(cls)} - _STRUCTURAL_FIELDS


def _code_surface() -> dict[str, set[str]]:
    """Every parameter name the code actually exposes, grouped by surface.

    Imported lazily so :mod:`simura.explain` stays importable on its own.
    """
    from ..builder.options import FAULT_PARAMS, PROFILE_PARAMS
    from ..builder.spec import SystemSpec
    from ..lights.lamp import LightSpec
    from ..wires.wire import WireSpec

    return {
        "battery-spec": _spec_fields(SystemSpec),
        "battery-profiles": set(PROFILE_PARAMS),
        "battery-faults": set(FAULT_PARAMS),
        "wire-spec": _spec_fields(WireSpec),
        "light-spec": _spec_fields(LightSpec),
    }


# Which cards are allowed to satisfy which surface. Keeping this explicit means
# a wire parameter cannot be "covered" by a battery card that happens to use the
# same field name (``ambient_temp_c`` appears in all three).
_SURFACE_CARDS: dict[str, tuple[str, ...]] = {
    "battery-spec": ("battery.cell", "battery.pack", "battery.run"),
    "battery-profiles": ("battery.profile",),
    "battery-faults": ("battery.faults",),
    "wire-spec": ("wires.resistance",),
    "light-spec": ("lights.lamp",),
}


def coverage() -> dict[str, Any]:
    """Compare the cards against the code, in both directions.

    Returns ``missing`` (parameters the code exposes with no card) and
    ``orphaned`` (cards describing parameters the code no longer has). The test
    suite asserts both are empty, which is what keeps this layer honest: adding
    a parameter without explaining it fails the build.
    """
    surfaces = _code_surface()
    missing: list[dict[str, str]] = []
    orphaned: list[dict[str, str]] = []

    for surface, code_keys in surfaces.items():
        card_ids = _SURFACE_CARDS[surface]
        documented: dict[str, str] = {}
        for cid in card_ids:
            for p in get_card(cid).params:
                documented[p.key] = cid
        for key in sorted(code_keys - set(documented)):
            missing.append({"surface": surface, "key": key})
        for key in sorted(set(documented) - code_keys):
            orphaned.append({"surface": surface, "key": key, "card": documented[key]})

    total = sum(len(v) for v in surfaces.values())
    return {
        "surfaces": {k: sorted(v) for k, v in surfaces.items()},
        "parameters_in_code": total,
        "documented": total - len(missing),
        "missing": missing,
        "orphaned": orphaned,
        "complete": not missing and not orphaned,
    }
