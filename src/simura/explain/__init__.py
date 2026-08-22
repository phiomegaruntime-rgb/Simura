"""Getting familiar with a simulation without becoming an expert in all of it.

This is the layer Simura's mission actually names. The physics components answer
*is this faithful?*; this one answers *can somebody who did not build it
understand what it is doing, and why?*

The design decision everything follows from
-------------------------------------------

**An explanation is attributed, never asserted.** Nothing in this package says
"high current makes a pack hot", "long runs drop voltage", or "a dirty lens
costs you lux". Instead it evaluates each term of the model's *own* governing
equation at the operating point in front of you, ranks the terms by how much
they actually contributed, and builds the sentence from whichever one won.
Change a coefficient in :mod:`simura.sim.pack` and the sentence changes with it,
because the sentence **is** the physics read out loud.

That is the same commitment that made efficacy computed rather than tabulated in
:mod:`simura.lights`, applied to prose. It is what stops this layer from
becoming a pile of plausible text that slowly stops matching the model.

Four pieces
-----------

:mod:`~simura.explain.attribution`
    The two decompositions — things that add, things that multiply — that every
    explanation in the project is one of.
:mod:`~simura.explain.cards` and :mod:`~simura.explain.glossary`
    The plain-language layer, checked against the code it describes: a parameter
    with no card is a failing test, not a silent gap.
:mod:`~simura.explain.domains` and :mod:`~simura.explain.levels`
    Who is reading, and how deep they want to go — two separate knobs, because a
    domain expert reading someone else's field wants *their own* vocabulary and
    *more* depth, not less.
:mod:`~simura.explain.narrate`
    Grammar. It decides the verb; the physics decides the claim.

Usage
-----

Explaining a live pack::

    from simura.explain import explain_pack, render_all

    for e in render_all(explain_pack(sim.pack), domain="operations", level="working"):
        print(e.headline)

Explaining a telemetry frame you received over the wire::

    from simura.explain import explain_frame, brief

    print(brief(explain_frame(frame, spec), domain="newcomer"))

Looking up what a form field means::

    from simura.explain import find_param

    card, param = find_param("cooling_conductance_w_per_k")
    print(param.why)
"""

from .attribution import Attribution, Term, additive, multiplicative
from .battery import (
    CellPoint,
    cell_of_interest,
    charge_rate,
    explain_frame,
    explain_pack,
    heat_balance,
    imbalance,
    imbalance_from_pack,
    operating_point_from_frame,
    operating_point_from_pack,
    voltage_sag,
)
from .cards import (
    ALL_CARDS,
    COMPONENTS,
    ModelCard,
    ParamCard,
    coverage,
    find_param,
    get_card,
    list_cards,
)
from .domains import DOMAINS, Domain, get_domain, list_domains, rank_for, translate
from .lights import explain_installation
from .wires import explain_run
from .glossary import GLOSSARY, GlossaryEntry, define, list_terms
from .levels import LEVELS, LEVEL_INFO, at_least, deeper, get_level
from .narrate import Explanation, brief, quantity, render, render_all

__all__ = [
    # attribution core
    "Attribution",
    "Term",
    "additive",
    "multiplicative",
    # batteries
    "CellPoint",
    "cell_of_interest",
    "charge_rate",
    "explain_frame",
    "explain_pack",
    "heat_balance",
    "imbalance",
    "imbalance_from_pack",
    "operating_point_from_frame",
    "operating_point_from_pack",
    "voltage_sag",
    # wires and lights (their per-quantity functions share names with the
    # battery ones -- import the submodules for those:
    #   from simura.explain import wires as wire_explain
    "explain_installation",
    "explain_run",
    # cards & glossary
    "ALL_CARDS",
    "COMPONENTS",
    "GLOSSARY",
    "GlossaryEntry",
    "ModelCard",
    "ParamCard",
    "coverage",
    "define",
    "find_param",
    "get_card",
    "list_cards",
    "list_terms",
    # lenses
    "DOMAINS",
    "Domain",
    "LEVELS",
    "LEVEL_INFO",
    "at_least",
    "deeper",
    "get_domain",
    "get_level",
    "list_domains",
    "rank_for",
    "translate",
    # narration
    "Explanation",
    "brief",
    "quantity",
    "render",
    "render_all",
]
