# Getting familiar

Simura's mission is *a CRM for simulations, so that anybody can simulate*, and
the literal crux of it is this: **get familiar with a simulation without
becoming an expert in all of it.** Phase 1 built physics faithful enough to be
worth understanding. The `simura.explain` package is where the understanding
part lives.

It is deliberately not a documentation site bolted on beside the code. It is a
library that reads the models.

## The design decision everything follows from

**An explanation is attributed, never asserted.**

Nothing in this package contains the sentence "high current makes a pack hot",
or "long runs drop voltage", or "a dirty lens costs you lux". Instead it
evaluates each term of the model's *own* governing equation at the operating
point in front of you, ranks the terms by how much they actually contributed,
and builds the sentence from whichever one won.

Change a coefficient in `simura.sim.pack` and the sentence changes with it,
because the sentence **is** the physics read out loud. This is the same
commitment that made [efficacy computed, never looked up](lights.md) in the
lighting component, applied to prose — and for the same reason. A layer of
plausible text that slowly stops matching the model is worse than no layer at
all, because nobody can tell.

## Physics comes in two shapes

So the package has exactly two decompositions, and every explanation in Simura
is one of them.

**Things that add.** A cell's heat balance, a conductor's heat balance, a
terminal-voltage law, a split-flux illuminance field. The terms carry the
outcome's own unit and they sum to it.

```
C_th·dT/dt = I²·R₀ + I·V_rc + Q_fault − k·(T − T_ambient)
```

The interesting cases are the ones where the terms *cancel*: a pack holding
steady is not a pack with nothing happening, and an attribution that reports
`0.4 W net, of which cooling is 50%` says something a single number cannot.

**Things that multiply.** A conductor's resistance, a lumen-method illuminance,
a lamp's efficacy. No factor carries the outcome's unit; each scales it.

```
efficacy = 683 · (LER/683) · (P_radiant/P_source) · (P_source/P_input) · optical
```

Shares come from `|ln factor|`, which is the only measure of "how much did this
move the answer" that does not depend on the order the factors are written in. A
factor of 2 and a factor of ½ score the same; a factor of 1 scores zero.

**A factor of zero takes the whole share.** The logarithm does not reach it, but
the physics does: a zero factor annihilates the outcome, so it is not merely the
largest contribution, it is the only one that matters. Without this rule a
burnt-out lamp is reported as dark because of its supply voltage — true of the
arithmetic, absurd as an explanation.

### A special case worth its own name: counterfactual chains

One multiplicative attribution does not read its factors off a formula, because
the question has no formula. `lamp.output` answers *this fitting is rated for so
many lumens and is producing fewer — which of dimming, supply voltage, ambient,
wear and faults did it?* Those effects are not separable terms; they are
conditions, and they interact.

So each factor is obtained by **re-running the lamp model with exactly one
condition changed**, in a chain from the rated point to the real one:

```
rated → drive → supply → ambient → age and dirt → faults
```

Each factor is the ratio of two consecutive runs, so the product telescopes to
the true ratio of actual output to rated — exactly, with no residual and nothing
counted twice. Nothing asserts that a filament suffers on a sagging supply while
a driven LED does not; both go through the identical five runs and come out
different because the *lamp model* is different.

**The order is part of the answer** and the docstring says so: a lamp that is
already hot loses a different amount to a voltage sag than a cold one, so each
factor is conditional on the ones before it. The chain runs outward from the
electrical cause to the physical condition of the fitting, because that is the
order in which somebody would act on it.

!!! note "Multiplicative attributions state their reference"
    "How much does length contribute to resistance?" has no answer until you say
    *compared to what*. The wire attributions state theirs explicitly — one
    metre of one square millimetre of annealed copper at 20 °C — and carry it in
    the operating point. The efficacy one does not need to: its reference is
    683 lm/W, which is a physical constant rather than a convention.

## The two knobs

Depth and domain are separate, because a lighting designer reading a battery
model wants **their own vocabulary** and **more** depth, and a single
beginner-to-expert slider cannot express that.

### Domains — whose words

| Lens | For |
| --- | --- |
| `newcomer` | Never run a simulation; wants to know what is happening and whether it is fine |
| `battery` | Cells, packs, electro-thermal behaviour |
| `thermal` | Heat in, heat out, where it settles — in any of the three components |
| `safety` | Margins, alarms, how long there is |
| `operations` | Is it healthy, does anyone need to go and look at it |
| `electrical` | Conductors, circuits, drop and ampacity |
| `lighting` | Lux on the task, colour, uniformity, installed power |

A lens changes two things: the **vocabulary** (canonical phrase → this reader's
phrase) and the **priority** (which attribution they read first). It never
drops anything — a reader handed a partial picture cannot tell that they have
been.

A vocabulary entry is a *synonym, not a definition*. Replacements are dropped
into the middle of prose written with the canonical term in it, so mapping
`ampacity → the current this cable can safely carry` reads fine alone and turns
the label "Rated ampacity" into nonsense. The full gloss belongs in the
glossary, which is what the tooltip beside the word is for. A test enforces the
rule.

### Levels — how deep

| Level | Shows |
| --- | --- |
| `overview` | What is happening, whether it is fine, the one cause that matters. No symbols. |
| `working` | Every cause that matters, how much each contributes, the numbers. |
| `physics` | The equation, **every** term including the negligible ones, the operating point, and the model's assumptions and limits. |

The rule the levels enforce is that **depth adds, never contradicts**. Every
figure quoted at `overview` reappears, unrounded, at `physics`, and the headline
is byte-identical at all three. A reader who clicks deeper must never discover
that the simple version was a different claim.

One thing deliberately does *not* vary with depth: a caveat. An inexact answer
says so at every level, because trustworthiness is not a detail that deeper
levels reveal.

## Exact, and inferred

There are two ways to explain a battery, and the difference matters enough that
the API reports which one it used.

**From the running model** (`explain_pack`, and `GET /api/systems/{id}/explain`
when the twin core owns the simulation). Every quantity is the one the solver is
using, including each cell's own manufacturing spread and the fault and weather
coefficients that telemetry deliberately cannot carry — a real BMS could not
report a cell's fault current either. Exact.

**From a telemetry frame** (`explain_frame`). The internal states the equations
need are recovered by *inverting the model*: the chemistry's curve gives the
open-circuit voltage at the reported charge, and the terminal law then gives the
polarisation voltage as what is left over. This is the honest thing to do with a
measurement, and it is also why such an attribution is marked `exact=False` —
per-cell resistance spread is not observable from outside, so it lands in the
polarisation term.

The consequence is worth knowing rather than hiding, so the caveat says it:
if a cell sits well above the equilibrium temperature a frame-derived heat
balance predicts, **that gap is the size of the heat source the frame cannot
see**.

## Model cards, checked against the code

Every model and every parameter a user can set carries a card — *what is this,
and why does it matter* — written so that the battery person can read the wire
model without a cable-pulling background.

The hard part of a layer like this is not writing it. It is that six months
later the code has three new parameters and the prose has none, and nothing
breaks. So the cards are **checked against the code they describe**:

```bash
python -m simura.explain --coverage
```

`coverage()` reflects over the real dataclasses and option registries and
reports every parameter that exists in code with no card, and every card
describing a parameter the code no longer has. The test suite asserts both lists
are empty, and the report is served at `GET /api/explain/coverage` so the claim
is checkable from outside. **A new parameter without a card is a failing build.**

Cards also carry a `limits` list, and it is not optional. A model card that only
says what a model does is marketing; the useful half is what it cannot tell you,
which is the thing a newcomer has no way to find out for themselves.

## Using it

```python
from simura.builder import SystemSpec, ProfileSpec, build_simulator
from simura.explain import brief, explain_pack, render_all

sim = build_simulator(SystemSpec(series=4, parallel=3, duration_s=900))
for _ in sim.run():
    pass

# One paragraph, for anybody.
print(brief(explain_pack(sim), domain="newcomer"))

# The working detail, for a safety lead.
for e in render_all(explain_pack(sim), domain="safety", level="working"):
    print(e.headline)
    for cause in e.causes:
        print("  -", cause)
```

Wires and lights work the same way, from their own submodules:

```python
from simura.wires import WireSpec
from simura.explain.wires import explain_run
from simura.explain import brief

print(brief(explain_run(WireSpec(awg=12, length_m=40), 18.0, 12.0, round_trip=True),
            domain="electrical"))
```

Looking up what a form field means:

```python
from simura.explain import find_param, define

card, param = find_param("cooling_conductance_w_per_k")
print(param.why)
print(define("ampacity").short)
```

## CLI

```bash
python -m simura.explain --coverage
python -m simura.explain --cards --component lights
python -m simura.explain --card battery.thermal
python -m simura.explain --define ampacity
python -m simura.explain --battery --short --domain safety --level working
python -m simura.explain --wire --awg 12 --length 40 --current 18 --voltage 12
python -m simura.explain --lamp led-9-e27 --domain newcomer
```

The `--battery --short` run is the one to try: it simulates a real pack with a
real internal short and prints the ranking. The fault-heat term appears because
the fault put heat into the model's heat balance — not because anything in the
explainer knows what a short is.

## API

All pure compute except the last, which reads live state.

| Route | What |
| --- | --- |
| `GET /api/explain/cards` | Every model card, optionally `?component=` |
| `GET /api/explain/cards/{id}` | One card in full |
| `GET /api/explain/glossary` | The glossary, or `?term=` for one entry (aliases work) |
| `GET /api/explain/lenses` | Domains and levels — both pickers in one call |
| `GET /api/explain/coverage` | Which parameters have a card, and which do not |
| `POST /api/explain/battery` | Explain a telemetry frame you already have |
| `POST /api/explain/wires` | Explain a wire run — same body as `/api/wires/evaluate` |
| `POST /api/explain/lights` | Explain a lighting *design* — same body as `/api/lights/evaluate` |
| `POST /api/explain/lamp` | Explain one *luminaire* on the supply it actually has — same body as one entry of `/api/lights/operate` |
| `GET /api/systems/{id}/explain` | Explain a live twin. Reports `source: model \| telemetry` |

Each `POST` route deliberately takes the *same body* as the check it explains,
so a caller that has just run the check can ask for the explanation of it
without reshaping anything — and the two can never end up describing different
systems. That is why there are two lighting routes rather than one: a caller
designing a *room* has a lumen-method body, and a caller solving a *site* has a
per-fitting one, and neither should have to translate into the other's shape to
get an explanation.

### Agreeing with a solve that already happened

`POST /api/explain/wires` accepts `at_temp_c`, which pins the conductor
temperature instead of letting the route re-derive it.

This matters more than it sounds. A whole-network solve owns that temperature:
it reflects the rest of the circuit, the weather and any faults, none of which a
single conductor spec carries. Left to work it out alone, the explanation would
sit next to a voltage drop it quietly disagreed with — and a reader has no way
to tell which of two numbers to believe. **Being slightly wrong is recoverable;
contradicting the panel beside you is not.** Pass the solved temperature and the
two agree to the precision the API serialises at.

## In the dashboard

- **Every running system** opens with an explanation panel *above* the stat
  tiles. A newcomer arriving at a live pack meets a sentence they can read
  before they meet a DCIR figure; the numbers are one click deeper, and the
  expert loses nothing because the panel starts at overview.
- **The wiring planner and the lighting planner** show the same panel beside
  their results, decomposing the check that is on screen.
- **A Learn section** browses every model card and the glossary, with each card
  re-readable in another field's words.
- **Glossary terms are underlined** wherever they appear in explanation prose,
  with the one-line definition on hover. A link to a glossary is a page nobody
  visits mid-sentence.
- **`ExplainPanel` is reusable by optional modules**, which import it from
  `src/components/` like any other shared component and pass `bare` to drop the
  card chrome when they already have a surface of their own. An installed module
  that solves something can offer the same explanation, with the same two
  controls, without restyling anything or reimplementing a word of it.

!!! warning "Explain what is on screen, not what you would have computed"
    Any caller placing an explanation beside numbers it did not produce should
    pass the solved values rather than letting the route re-derive them —
    `at_temp_c` on a wire, the voltage that actually arrived at a fitting. Two
    panels describing the same component and disagreeing is worse than either
    being slightly off, because the reader cannot tell which to believe.

## Limits

- Explanations are of *one operating point*. Nothing here reasons about a
  trajectory, so "it has been getting worse for ten minutes" is not something it
  can say.
- The battery explainer decomposes one cell at a time (plus pack-wide
  imbalance). It does not rank cells against each other — that is what
  [anomaly detection](analytics.md) is for, and the two are complementary.
- Domain lenses are vocabulary and priority, not re-derivation. A lens does not
  change which quantities exist, only the order and the words.
- Attribution says *what is contributing*, not *what to do*. It will tell you
  that dirt on the luminaires is 61% of your shortfall; deciding to clean them
  is still yours.
