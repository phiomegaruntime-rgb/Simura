"""Import somebody else's building, and let four simulations stand inside it.

A BIM model arrives from an architect. By the end of this script it has told the
weather where the building is, told the lighting planner how big every room is
and what it is for, told the wiring planner how long a cable between two rooms
actually runs, and told a battery rack whether the sun reaches it.

    python examples/import_a_building.py

The thing to watch for: **the import says what it could not read.** Every value
the importer supplied rather than found is listed, with the basis it came from,
and the couplings carry that through -- a lighting design for a room whose
ceiling height was assumed reports the assumption rather than quietly resting on
it. Silent geometry loss is the characteristic way BIM interoperability fails,
and refusing to commit it is what makes the numbers below worth having.

The same model is inspectable from the shell::

    python -m simura.space --import building.xml --fidelity
    python -m simura.space --import building.xml --light
    python -m simura.space --import building.xml --route 3,3 21,3
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from simura.builder import SystemSpec, WeatherSpec, preview  # noqa: E402
from simura.builder.spec import SpaceSpec  # noqa: E402
from simura.lights.planning import recommend_lamp  # noqa: E402
from simura.space import (  # noqa: E402
    GbxmlProvider,
    ambient_for,
    lighting_targets,
    route,
    weather_spec,
)
from simura.weather import StaticProvider  # noqa: E402
from simura.wires import WireSpec, evaluate_run  # noqa: E402

# Windows consoles default to cp1252; the prose has arrows and degree signs.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def rule(title: str) -> None:
    print(f"\n\n{title}\n{'=' * len(title)}")


# ---------------------------------------------------------------------------
# The model. Normally this is a file from an architect; here it is written out
# so the example runs with nothing downloaded. It is a real gbXML document --
# two rooms on a storey, one conditioned and one not, one of them L-shaped, with
# the site's coordinates on it.
# ---------------------------------------------------------------------------

MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<gbXML xmlns="http://www.gbxml.org/schema" lengthUnit="Meters">
  <Campus id="cmp-1">
    <Location>
      <Name>Bristol</Name>
      <Latitude>51.4545</Latitude>
      <Longitude>-2.5879</Longitude>
      <Elevation>11.0</Elevation>
    </Location>
    <CADModelAzimuth>17.0</CADModelAzimuth>
    <Building id="bld-1" buildingType="Office">
      <Name>Riverside Block A</Name>
      <BuildingStorey id="storey-0"><Name>Ground</Name><Level>0.0</Level></BuildingStorey>
      <BuildingStorey id="storey-1"><Name>First</Name><Level>3.4</Level></BuildingStorey>
      <Space id="sp-office" spaceType="OpenOffice" conditionType="HeatedAndCooled"
             buildingStoreyIdRef="storey-0">
        <Name>Open Plan Office 0.01</Name>
        <Area>24.0</Area>
        <Volume>67.2</Volume>
        <PlanarGeometry><PolyLoop>
          <CartesianPoint><Coordinate>0</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <CartesianPoint><Coordinate>6</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <CartesianPoint><Coordinate>6</Coordinate><Coordinate>4</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <CartesianPoint><Coordinate>0</Coordinate><Coordinate>4</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
        </PolyLoop></PlanarGeometry>
      </Space>
      <Space id="sp-plant" spaceType="Mechanical" conditionType="Unconditioned"
             buildingStoreyIdRef="storey-0">
        <Name>Plant Room 0.02</Name>
        <PlanarGeometry><PolyLoop>
          <CartesianPoint><Coordinate>6</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <CartesianPoint><Coordinate>14</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <CartesianPoint><Coordinate>14</Coordinate><Coordinate>2</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <CartesianPoint><Coordinate>10</Coordinate><Coordinate>2</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <CartesianPoint><Coordinate>10</Coordinate><Coordinate>4</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <CartesianPoint><Coordinate>6</Coordinate><Coordinate>4</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
        </PolyLoop></PlanarGeometry>
      </Space>
    </Building>
    <Surface id="srf-party" surfaceType="InteriorWall">
      <AdjacentSpaceId spaceIdRef="sp-office"/>
      <AdjacentSpaceId spaceIdRef="sp-plant"/>
      <PlanarGeometry><PolyLoop>
        <CartesianPoint><Coordinate>6</Coordinate><Coordinate>0</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
        <CartesianPoint><Coordinate>6</Coordinate><Coordinate>4</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
        <CartesianPoint><Coordinate>6</Coordinate><Coordinate>4</Coordinate><Coordinate>2.8</Coordinate></CartesianPoint>
        <CartesianPoint><Coordinate>6</Coordinate><Coordinate>0</Coordinate><Coordinate>2.8</Coordinate></CartesianPoint>
      </PolyLoop></PlanarGeometry>
      <Opening id="op-door" openingType="NonSlidingDoor">
        <RectangularGeometry>
          <CartesianPoint><Coordinate>1.5</Coordinate><Coordinate>0</Coordinate></CartesianPoint>
          <Width>0.9</Width><Height>2.1</Height>
        </RectangularGeometry>
      </Opening>
    </Surface>
    <Surface id="srf-roof" surfaceType="Roof">
      <AdjacentSpaceId spaceIdRef="sp-office"/>
      <PlanarGeometry><PolyLoop>
        <CartesianPoint><Coordinate>0</Coordinate><Coordinate>0</Coordinate><Coordinate>2.8</Coordinate></CartesianPoint>
        <CartesianPoint><Coordinate>6</Coordinate><Coordinate>0</Coordinate><Coordinate>2.8</Coordinate></CartesianPoint>
        <CartesianPoint><Coordinate>6</Coordinate><Coordinate>4</Coordinate><Coordinate>2.8</Coordinate></CartesianPoint>
        <CartesianPoint><Coordinate>0</Coordinate><Coordinate>4</Coordinate><Coordinate>2.8</Coordinate></CartesianPoint>
      </PolyLoop></PlanarGeometry>
    </Surface>
  </Campus>
</gbXML>
"""


def main() -> None:
    plan = GbxmlProvider(data=MODEL.encode(), name="block-a.xml").plan()

    # -- 1. what arrived ---------------------------------------------------
    rule("1. A building, reduced to the 2D layout a simulator can stand in")
    width, depth = plan.size_m()
    print(f"{plan.name}  [{plan.id}]")
    print(
        f"  {len(plan.spaces)} rooms, {len(plan.walls)} walls, "
        f"{len(plan.openings)} openings over {width:.0f} x {depth:.0f} m, "
        f"drawn in {plan.source_units}"
    )
    for space in plan.spaces:
        length, room_width, _ = space.extents()
        shape = "rectangle" if space.rectangular() else "irregular"
        print(
            f"  - {space.name:<24} {space.occupancy:<8} {space.area_m2:>5.1f} m² "
            f"({length:.1f} x {room_width:.1f} m, {space.height_m:.2f} m high, {shape})"
        )

    # -- 2. what it could not read ----------------------------------------
    rule("2. What the import could not read — the part that is usually silent")
    print(plan.fidelity.summary())
    print("\nEvery value the importer supplied rather than found:")
    for item in plan.fidelity.inferences:
        kind = "default" if item.provenance == "default" else "derived"
        print(f"  [{kind:>7}] {item.subject}.{item.field} = {item.value}")
        print(f"            because: {item.basis}")
    print("\nAnd what it did not turn into geometry:")
    for item in plan.fidelity.skipped:
        print(f"  {item.count}x {item.entity} — {item.reason}")
    print(
        "\nNote that the two rooms got their ceiling height by different routes:"
        "\none from a stated volume, one measured off its own wall surfaces. Those"
        "\nare different qualities of answer, and the record says which is which."
    )

    # -- 3. the weather ----------------------------------------------------
    rule("3. The model tells the weather where it is")
    source = weather_spec(plan)
    print(f"  IfcSite / gbXML Location  ->  {source}")
    print(
        f"  true north is {plan.georeference.north_deg:.0f}° off the model's +y axis, "
        f"which is what decides\n  which facade takes morning sun."
    )
    print(
        "\n  Nobody typed a latitude. The building already knew where it was, and"
        "\n  that is the whole join: a weather source you did not have to configure."
    )

    # -- 4. the lighting ---------------------------------------------------
    rule("4. Every room becomes a lighting design")
    total_w = 0.0
    total_area = 0.0
    for target in lighting_targets(plan):
        result = recommend_lamp(**target.kwargs())
        assessment = result.assessment
        if assessment is None:
            print(f"  {target.name}: no catalog lamp meets it")
            continue
        total_w += assessment.power_w
        total_area += target.area_m2
        lamp = result.lamp_type.name if result.lamp_type else "—"
        print(
            f"  {target.name:<24} {assessment.target_lux:>4.0f} lx  "
            f"{result.n_luminaires:>2} x {lamp:<26} "
            f"{assessment.power_density_w_per_m2:>5.1f} W/m²"
        )
        for problem in target.problems:
            print(f"       ! {problem}")
    print(f"\n  whole building: {total_w:.0f} W over {total_area:.0f} m²"
          f" = {total_w / total_area:.1f} W/m²")

    # -- 5. the cable ------------------------------------------------------
    rule("5. The cable is as long as the building makes it")
    run = route(plan, (3.0, 2.0), (12.0, 1.0))
    for leg in run.legs:
        print(f"  {leg.kind:<11} {leg.length_m:>6.2f} m   {leg.description}")
    print(f"  {'':<11} {'-' * 8}")
    print(
        f"  {'total':<11} {run.length_m:>6.2f} m   "
        f"({run.horizontal_m:.1f} horizontal + {run.vertical_m:.1f} vertical "
        f"+ {run.slack_m:.1f} slack)"
    )

    hot = StaticProvider(air_temp_c=34.0, solar_w_m2=850.0).at(0)
    hottest = run.hottest_ambient(plan, hot)
    spec = WireSpec(**run.wire_kwargs("cu-10-thhn90", hottest or 25.0))
    assessment = evaluate_run(spec, current_a=25.0, system_voltage_v=48.0)
    print(
        f"\n  10 AWG THHN at {spec.length_m:.1f} m, rated for the "
        f"{hottest:.0f} °C plant room\n  it passes through (not the 21 °C office it "
        f"starts in):"
    )
    print(
        f"    {assessment.voltage_drop_v:.2f} V drop "
        f"({assessment.voltage_drop_pct:.1f}%), "
        f"{assessment.power_loss_w:.1f} W lost, "
        f"conductor at {assessment.steady_state_temp_c:.0f} °C, "
        f"{assessment.ampacity_utilization * 100:.0f}% of its ampacity"
    )
    for problem in assessment.problems:
        print(f"    ! {problem}")

    # -- 6. the battery ----------------------------------------------------
    rule("6. The room decides whether the weather reaches the rack")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "block-a.json"
        path.write_text(plan.to_json(), encoding="utf-8")

        weather = WeatherSpec(type="static", params={"air_temp_c": 34.0, "solar_w_m2": 850.0})
        for room in ("sp-office", "sp-plant"):
            context = ambient_for(plan, room, hot)
            spec = SystemSpec(
                system_id=f"rack-{room}",
                name=f"Rack in {context.name}",
                series=16,
                parallel=4,
                duration_s=1800.0,
                weather=weather,
                space=SpaceSpec(
                    type="json", params={"path": str(path)}, space_id=room
                ),
            )
            result = preview(spec)
            print(f"\n  {context.name}")
            print(f"    {context.basis}")
            print(
                f"    ambient {context.ambient_c:.1f} °C, "
                f"sun {'excluded' if context.shading_frac >= 1 else 'reaching the cabinet'}"
                f"  ->  hottest cell {result.peak_temp_c:.1f} °C after 30 min"
            )

    print(
        "\n  Same rack, same 34 °C day, two rooms. The difference is not a number"
        "\n  somebody typed — it is what the building said about each room."
    )

    rule("What just happened")
    print(
        "One file, read once, and four separate simulations stopped needing a\n"
        "number typed from memory: where the weather is, how big each room is,\n"
        "how long the cable runs, and what ambient the rack sits in.\n\n"
        "And the import never pretended to know more than it did. Two of those\n"
        "ceiling heights were derived, two wall thicknesses were defaults, and a\n"
        "roof was skipped — all of it listed in section 2, none of it hidden\n"
        "behind a number that looks exactly like a measurement."
    )


if __name__ == "__main__":
    main()
