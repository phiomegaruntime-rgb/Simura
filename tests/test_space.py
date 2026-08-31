"""Tests for :mod:`simura.space` -- BIM in, floor plan out.

Five things are asserted, in the shape the rest of the suite uses:

* **geometry** -- a room's measurements are the measurements, including for the
  shapes a rectangle cannot describe.
* **import** -- each format is read, in its own units, with its own semantics.
* **fidelity** -- the commitment: every value the importer supplied rather than
  read is recorded, with a basis, and a plan that assumed nothing says so.
* **coupling** -- a plan produces exactly the arguments the physics already takes.
* **routing** -- a cable length computed from the building, with its legs visible.

The fixtures are written out in full rather than shipped as files: a reader
should be able to see the input that produces every assertion below without
opening anything else, and a BIM fixture is the one kind of test data where
"trust me, it's in the folder" is least acceptable.
"""

from __future__ import annotations

import json
import math

import pytest

from simura.space import (
    DxfProvider,
    FloorPlan,
    Opening,
    GbxmlProvider,
    IfcProvider,
    JsonPlanProvider,
    PlanError,
    RectangleProvider,
    Space,
    Wall,
    ambient_for,
    build_provider,
    classify,
    detect_format,
    lighting_targets,
    route,
    summary,
    task_grid,
    weather_spec,
)
from simura.space.geometry import (
    oriented_extents,
    point_in_polygon,
    polygon_area,
    polygon_centroid,
    rectangle,
)
from simura.space.units import guess_scale, plausible_building

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

GBXML = """<?xml version="1.0" encoding="UTF-8"?>
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
      </PolyLoop></PlanarGeometry>
    </Surface>
  </Campus>
</gbXML>
"""


def _dxf(*pairs: tuple[int, str]) -> str:
    return "".join(f"{code}\n{value}\n" for code, value in pairs)


# A drawing in millimetres: two rooms on A-AREA, their labels, walls on A-WALL,
# and two entities the importer must decline to guess about.
DXF = (
    _dxf(
        (0, "SECTION"), (2, "HEADER"),
        (9, "$ACADVER"), (1, "AC1015"),
        (9, "$INSUNITS"), (70, "4"),
        (9, "$EXTMIN"), (10, "0.0"), (20, "0.0"),
        (9, "$EXTMAX"), (10, "11000.0"), (20, "4000.0"),
        (0, "ENDSEC"),
        (0, "SECTION"), (2, "ENTITIES"),
        (0, "LWPOLYLINE"), (8, "A-AREA"), (90, "4"), (70, "1"),
        (10, "0.0"), (20, "0.0"), (10, "6000.0"), (20, "0.0"),
        (10, "6000.0"), (20, "4000.0"), (10, "0.0"), (20, "4000.0"),
        (0, "TEXT"), (8, "A-AREA-IDEN"), (10, "3000.0"), (20, "2000.0"), (1, "Office 1"),
        (0, "LWPOLYLINE"), (8, "A-AREA"), (90, "4"), (70, "1"),
        (10, "6000.0"), (20, "0.0"), (10, "11000.0"), (20, "0.0"),
        (10, "11000.0"), (20, "4000.0"), (10, "6000.0"), (20, "4000.0"),
        (0, "MTEXT"), (8, "A-AREA-IDEN"), (10, "8500.0"), (20, "2000.0"), (1, "Store 2"),
        (0, "LINE"), (8, "A-WALL"), (10, "0.0"), (20, "0.0"), (11, "11000.0"), (21, "0.0"),
        (0, "LINE"), (8, "A-WALL"), (10, "6000.0"), (20, "0.0"), (11, "6000.0"), (21, "4000.0"),
        (0, "CIRCLE"), (8, "A-FURN"), (10, "3000.0"), (20, "2000.0"), (40, "400.0"),
        (0, "SPLINE"), (8, "A-DETL"),
        (0, "ENDSEC"), (0, "EOF"),
    )
)


# An IFC model in millimetres, with a placement chain two deep, a stated material
# thickness, a door reached through the void-and-fill pair, a STEP comment above
# an instance, and a longitude of negative zero degrees.
IFC = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('sample.ifc','2026-08-26T09:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1= IFCPROJECT('0proj00000000000000001',$,'Harbour Works',$,$,$,$,(#20),#10);
#10= IFCUNITASSIGNMENT((#11));
#11= IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#20= IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.0E-5,#30,#21);
#21= IFCDIRECTION((0.30901699,0.95105652));
#30= IFCAXIS2PLACEMENT3D(#31,$,$);
#31= IFCCARTESIANPOINT((0.,0.,0.));
#40= IFCSITE('0site00000000000000001',$,'Harbour Site',$,$,#50,$,$,.ELEMENT.,(51,30,26,000000),(-0,-7,39,000000),12000.,$,$);
#50= IFCLOCALPLACEMENT($,#30);
#60= IFCBUILDING('0bldg00000000000000001',$,'Block A',$,$,#61,$,$,.ELEMENT.,$,$,$);
#61= IFCLOCALPLACEMENT(#50,#30);
#70= IFCBUILDINGSTOREY('0stry00000000000000001',$,'Ground',$,$,#71,$,$,.ELEMENT.,0.);
#71= IFCLOCALPLACEMENT(#61,#72);
#72= IFCAXIS2PLACEMENT3D(#73,$,$);
#73= IFCCARTESIANPOINT((0.,0.,0.));
#80= IFCBUILDINGSTOREY('0stry00000000000000002',$,'First',$,$,#81,$,$,.ELEMENT.,3600.);
#81= IFCLOCALPLACEMENT(#61,#82);
#82= IFCAXIS2PLACEMENT3D(#83,$,$);
#83= IFCCARTESIANPOINT((0.,0.,3600.));
/* the office, placed 2 m east of the storey origin */
#100= IFCSPACE('0spc000000000000000001',$,'0.01',$,$,#101,#110,'Drawing Office',.ELEMENT.,.NOTDEFINED.,$);
#101= IFCLOCALPLACEMENT(#71,#102);
#102= IFCAXIS2PLACEMENT3D(#103,$,$);
#103= IFCCARTESIANPOINT((2000.,0.,0.));
#110= IFCPRODUCTDEFINITIONSHAPE($,$,(#111));
#111= IFCSHAPEREPRESENTATION(#20,'Body','SweptSolid',(#112));
#112= IFCEXTRUDEDAREASOLID(#113,#116,#119,2800.);
#113= IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#114);
#114= IFCPOLYLINE((#1141,#1142,#1143,#1144));
#1141= IFCCARTESIANPOINT((0.,0.));
#1142= IFCCARTESIANPOINT((6000.,0.));
#1143= IFCCARTESIANPOINT((6000.,4000.));
#1144= IFCCARTESIANPOINT((0.,4000.));
#116= IFCAXIS2PLACEMENT3D(#117,$,$);
#117= IFCCARTESIANPOINT((0.,0.,0.));
#119= IFCDIRECTION((0.,0.,1.));
#200= IFCWALLSTANDARDCASE('0wal000000000000000001',$,'Partition',$,$,#201,#210,$);
#201= IFCLOCALPLACEMENT(#71,#202);
#202= IFCAXIS2PLACEMENT3D(#203,$,$);
#203= IFCCARTESIANPOINT((2000.,0.,0.));
#210= IFCPRODUCTDEFINITIONSHAPE($,$,(#211));
#211= IFCSHAPEREPRESENTATION(#20,'Axis','Curve2D',(#212));
#212= IFCPOLYLINE((#2121,#2122));
#2121= IFCCARTESIANPOINT((0.,0.));
#2122= IFCCARTESIANPOINT((6000.,0.));
#220= IFCRELASSOCIATESMATERIAL('0rel000000000000000001',$,$,$,(#200),#221);
#221= IFCMATERIALLAYERSETUSAGE(#222,.AXIS2.,.POSITIVE.,0.);
#222= IFCMATERIALLAYERSET((#223),'Partition 140');
#223= IFCMATERIALLAYER($,140.,$);
#230= IFCOPENINGELEMENT('0opn000000000000000001',$,'Doorway',$,$,#231,$,$);
#231= IFCLOCALPLACEMENT(#201,#232);
#232= IFCAXIS2PLACEMENT3D(#233,$,$);
#233= IFCCARTESIANPOINT((3000.,0.,0.));
#240= IFCRELVOIDSELEMENT('0rel000000000000000002',$,$,$,#200,#230);
#250= IFCDOOR('0dor000000000000000001',$,'Door 1',$,$,#251,$,$,2100.,900.);
#251= IFCLOCALPLACEMENT(#231,#232);
#260= IFCRELFILLSELEMENT('0rel000000000000000003',$,$,$,#230,#250);
#300= IFCSLAB('0slb000000000000000001',$,'Floor',$,$,#301,$,$,.FLOOR.);
#301= IFCLOCALPLACEMENT(#71,#72);
#400= IFCRELCONTAINEDINSPATIALSTRUCTURE('0rel000000000000000004',$,$,$,(#100,#200,#300),#70);
#500= IFCRELAGGREGATES('0rel000000000000000005',$,$,$,#60,(#70,#80));
ENDSEC;
END-ISO-10303-21;
"""

L_SHAPE = [(0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (4.0, 4.0), (4.0, 7.0), (0.0, 7.0)]


@pytest.fixture
def gbxml_plan() -> FloorPlan:
    return GbxmlProvider(data=GBXML.encode(), name="riverside.xml").plan()


@pytest.fixture
def ifc_plan() -> FloorPlan:
    return IfcProvider(data=IFC.encode(), name="harbour.ifc").plan()


@pytest.fixture
def dxf_plan() -> FloorPlan:
    return DxfProvider(data=DXF.encode(), name="floor.dxf").plan()


@pytest.fixture
def rect_plan() -> FloorPlan:
    return RectangleProvider().plan()


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

def test_a_rectangle_measures_as_itself():
    ring = rectangle(6.0, 4.0)
    assert polygon_area(ring) == pytest.approx(24.0)
    assert polygon_centroid(ring) == pytest.approx((3.0, 2.0))
    length, width, angle = oriented_extents(ring)
    assert (length, width) == pytest.approx((6.0, 4.0))
    assert angle % 90 == pytest.approx(0.0, abs=1e-6)


def test_an_l_shape_measures_its_own_area_not_its_bounding_box():
    # The whole reason `rectangular()` exists: the box is 56 m^2, the room is 44.
    assert polygon_area(L_SHAPE) == pytest.approx(44.0)
    length, width, _ = oriented_extents(L_SHAPE)
    assert length * width == pytest.approx(56.0, rel=1e-3)
    space = Space(id="s", polygon=L_SHAPE)
    assert not space.rectangular()


def test_a_rotated_rectangle_is_still_measured_as_a_rectangle():
    # The minimum-area rectangle is found on the room's own axis, not the
    # drawing's -- a building rotated 30 degrees off north is still rectangular.
    rad = math.radians(30.0)
    ring = [
        (x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad))
        for x, y in rectangle(6.0, 4.0)
    ]
    length, width, angle = oriented_extents(ring)
    assert (length, width) == pytest.approx((6.0, 4.0), abs=1e-6)
    # The hull rounds coordinates to micrometres, so the angle is exact to
    # about the same order -- far finer than any building is drawn to.
    assert angle == pytest.approx(30.0, abs=1e-3)
    assert Space(id="s", polygon=ring).rectangular()


def test_a_point_on_a_wall_line_counts_as_inside():
    # Grid points land exactly on round-number walls; excluding them would trim a
    # column off every room whose dimensions are whole metres.
    ring = rectangle(6.0, 4.0)
    assert point_in_polygon((6.0, 2.0), ring)
    assert point_in_polygon((3.0, 2.0), ring)
    assert not point_in_polygon((6.5, 2.0), ring)


def test_the_re_entrant_corner_of_an_l_shape_is_outside_it():
    assert point_in_polygon((2.0, 6.0), L_SHAPE)
    assert not point_in_polygon((6.0, 6.0), L_SHAPE)


def test_a_grid_covers_only_the_room():
    space = Space(id="s", polygon=L_SHAPE)
    plan = FloorPlan(spaces=[space])
    points = task_grid(plan, "s", spacing_m=0.5, inset_m=0.0)
    assert points
    assert all(point_in_polygon(p, L_SHAPE) for p in points)
    # No point in the notch the bounding box would have included.
    assert not any(p[0] > 4.0 and p[1] > 4.0 for p in points)


# ---------------------------------------------------------------------------
# occupancy
# ---------------------------------------------------------------------------

def test_occupancy_prefers_a_stated_type_over_a_name():
    result = classify(name="Room 12", gbxml_space_type="OpenOffice")
    assert result.occupancy == "office"
    assert "gbXML spaceType" in result.basis


def test_occupancy_falls_back_to_the_room_name_and_says_so():
    result = classify(name="Plant Room 3")
    assert result.occupancy == "storage"
    assert "contains 'plant'" in result.basis


def test_occupancy_matches_whole_words_only():
    # 'lab' must not match 'Elaborate', and 'plant' must not match 'Planting'.
    assert classify(name="Elaborate Suite").occupancy == "unknown"
    assert classify(name="Planting Terrace").occupancy == "unknown"


def test_occupancy_refuses_rather_than_guesses():
    result = classify(name="R-114")
    assert result.occupancy == "unknown"
    assert not result.known
    assert "no keyword" in result.basis


def test_a_more_specific_keyword_wins():
    assert classify(name="Drawing Office 2").occupancy == "drawing_office"
    assert classify(name="Office 2").occupancy == "office"


# ---------------------------------------------------------------------------
# the synthetic building
# ---------------------------------------------------------------------------

def test_the_generated_building_assumes_nothing(rect_plan: FloorPlan):
    # The control case: when the importer knows everything, the record says so,
    # which is what gives the warning meaning on a real model.
    assert rect_plan.fidelity.complete
    assert "nothing was assumed" in rect_plan.fidelity.summary()
    assert rect_plan.fidelity.coverage == pytest.approx(1.0)


def test_the_generated_building_has_rooms_a_corridor_and_doors(rect_plan: FloorPlan):
    assert len(rect_plan.spaces) == 5  # four rooms plus the corridor
    assert sum(1 for s in rect_plan.spaces if s.occupancy == "corridor") == 1
    assert sum(1 for o in rect_plan.openings if o.kind == "door") == 4
    assert rect_plan.floor_area_m2 == pytest.approx(4 * 24.0 + 24.0 * 1.8)


def test_two_identical_plans_have_the_same_id_and_a_changed_one_does_not():
    a = RectangleProvider().plan()
    b = RectangleProvider().plan()
    c = RectangleProvider(room_length_m=7.0).plan()
    assert a.id == b.id
    assert a.id != c.id


def test_the_id_ignores_how_much_the_importer_had_to_guess():
    # Two importers that produced the same building produced the same plan, even
    # if one had to assume more to get there. The hash identifies the building;
    # the fidelity record describes the import.
    plan = RectangleProvider().plan()
    from simura.space.fidelity import Fidelity, Inference

    noisier = FloorPlan(
        name=plan.name,
        georeference=plan.georeference,
        levels=plan.levels,
        spaces=plan.spaces,
        walls=plan.walls,
        openings=plan.openings,
        fidelity=Fidelity(
            inferences=[Inference("space:x", "height_m", 2.7, "a guess")]
        ),
    )
    assert noisier.content_hash() == plan.content_hash()


# ---------------------------------------------------------------------------
# gbXML
# ---------------------------------------------------------------------------

def test_gbxml_reads_rooms_their_type_and_their_conditioning(gbxml_plan: FloorPlan):
    office = gbxml_plan.space("sp-office")
    plant = gbxml_plan.space("sp-plant")
    assert office is not None and plant is not None
    assert office.occupancy == "office"
    assert office.conditioned is True
    assert plant.occupancy == "storage"
    assert plant.conditioned is False
    assert office.area_m2 == pytest.approx(24.0)


def test_gbxml_derives_a_height_from_volume_and_says_which_room_it_measured(
    gbxml_plan: FloorPlan,
):
    office = gbxml_plan.space("sp-office")
    assert office.height_m == pytest.approx(2.8)  # 67.2 m^3 / 24 m^2
    inferred = gbxml_plan.fidelity.inferred_fields("space:sp-office")
    assert "stated volume" in inferred["height_m"].basis

    # The plant room has no volume, so its height comes from its wall surfaces --
    # a different basis for the same field, which is the point of recording one.
    plant = gbxml_plan.fidelity.inferred_fields("space:sp-plant")
    assert "wall surfaces" in plant["height_m"].basis


def test_gbxml_reads_the_site_and_the_model_azimuth(gbxml_plan: FloorPlan):
    geo = gbxml_plan.georeference
    assert geo.located
    assert (geo.latitude, geo.longitude) == pytest.approx((51.4545, -2.5879))
    assert geo.north_deg == pytest.approx(17.0)


def test_gbxml_turns_a_vertical_surface_into_a_wall_and_skips_the_roof(
    gbxml_plan: FloorPlan,
):
    wall = gbxml_plan.wall("srf-party")
    assert wall is not None
    assert wall.axis == [(6.0, 0.0), (6.0, 4.0)]
    assert wall.length_m == pytest.approx(4.0)
    assert wall.height_m == pytest.approx(2.8)
    skipped = {s.entity: s for s in gbxml_plan.fidelity.skipped}
    assert any("Roof" in name for name in skipped)


def test_gbxml_positions_an_opening_along_its_wall(gbxml_plan: FloorPlan):
    door = next(o for o in gbxml_plan.openings if o.kind == "door")
    assert door.wall_id == "srf-party"
    assert door.width_m == pytest.approx(0.9)
    assert door.height_m == pytest.approx(2.1)
    # 1.5 m to the opening's near edge, so 1.95 m to its centre.
    assert door.along_m == pytest.approx(1.95)


def test_gbxml_records_that_wall_thickness_was_not_in_the_file(gbxml_plan: FloorPlan):
    wall = gbxml_plan.wall("srf-party")
    assert "thickness_m" in wall.inferred
    basis = gbxml_plan.fidelity.inferred_fields("wall:srf-party")["thickness_m"].basis
    assert "Construction" in basis


def test_gbxml_derives_a_storey_height_from_the_one_above(gbxml_plan: FloorPlan):
    ground = gbxml_plan.level("storey-0")
    assert ground.height_m == pytest.approx(3.4)


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------

def test_dxf_reads_its_unit_from_the_header(dxf_plan: FloorPlan):
    assert dxf_plan.source_units == "mm"
    assert dxf_plan.size_m() == pytest.approx((11.0, 4.0))


def test_dxf_makes_rooms_from_closed_polylines_named_by_the_text_inside_them(
    dxf_plan: FloorPlan,
):
    names = {s.name: s for s in dxf_plan.spaces}
    assert "Office 1" in names and "Store 2" in names
    assert names["Office 1"].occupancy == "office"
    assert names["Store 2"].occupancy == "storage"
    assert names["Office 1"].area_m2 == pytest.approx(24.0)


def test_dxf_admits_that_everything_about_a_room_but_its_outline_was_assumed(
    dxf_plan: FloorPlan,
):
    room = dxf_plan.spaces[0]
    assert "height_m" in room.inferred
    assert "occupancy" in room.inferred
    basis = dxf_plan.fidelity.inferred_fields(f"space:{room.id}")["height_m"].basis
    assert "2D drawing" in basis


def test_dxf_skips_what_it_cannot_turn_into_a_layout(dxf_plan: FloorPlan):
    skipped = {s.entity for s in dxf_plan.fidelity.skipped}
    assert "DXF CIRCLE" in skipped
    assert "DXF SPLINE" in skipped


def test_dxf_refuses_a_drawing_with_no_matching_layers():
    drawing = _dxf(
        (0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, "6"), (0, "ENDSEC"),
        (0, "SECTION"), (2, "ENTITIES"),
        (0, "LINE"), (8, "Layer1"), (10, "0.0"), (20, "0.0"), (11, "5.0"), (21, "0.0"),
        (0, "ENDSEC"), (0, "EOF"),
    )
    with pytest.raises(PlanError, match="wall_layers"):
        DxfProvider(data=drawing.encode(), name="unknown.dxf").plan()


def test_dxf_honours_a_caller_supplied_layer_convention():
    drawing = _dxf(
        (0, "SECTION"), (2, "HEADER"), (9, "$INSUNITS"), (70, "6"), (0, "ENDSEC"),
        (0, "SECTION"), (2, "ENTITIES"),
        (0, "LINE"), (8, "Layer1"), (10, "0.0"), (20, "0.0"), (11, "5.0"), (21, "0.0"),
        (0, "ENDSEC"), (0, "EOF"),
    )
    plan = DxfProvider(
        data=drawing.encode(), name="unknown.dxf", wall_layers=("layer1",)
    ).plan()
    assert len(plan.walls) == 1
    assert plan.walls[0].length_m == pytest.approx(5.0)


def test_an_unlabelled_drawing_gets_a_guessed_unit_with_a_stated_basis():
    factor, unit, basis = guess_scale(45000.0)
    assert (factor, unit) == (0.001, "mm")
    assert "assumed millimetres" in basis
    assert guess_scale(45.0)[1] == "m"


# ---------------------------------------------------------------------------
# IFC
# ---------------------------------------------------------------------------

def test_ifc_converts_millimetres_to_metres(ifc_plan: FloorPlan):
    assert ifc_plan.source_units == "mm"
    space = ifc_plan.space("#100")
    assert space.area_m2 == pytest.approx(24.0)
    assert space.height_m == pytest.approx(2.8)


def test_ifc_composes_the_placement_chain(ifc_plan: FloorPlan):
    # The space is drawn at the origin of its own frame and placed 2 m east; a
    # reader that ignores the chain puts it at x=0 and never notices.
    space = ifc_plan.space("#100")
    min_x, _, max_x, _ = space.bounds
    assert (min_x, max_x) == pytest.approx((2.0, 8.0))


def test_ifc_reads_a_negative_zero_longitude_into_the_right_hemisphere(
    ifc_plan: FloorPlan,
):
    # (-0, -7, 39) is 7'39" WEST. Summing the components, or testing `< 0` on a
    # degrees field of negative zero, puts the building in the wrong hemisphere.
    geo = ifc_plan.georeference
    assert geo.latitude == pytest.approx(51.507222, abs=1e-5)
    assert geo.longitude == pytest.approx(-0.1275, abs=1e-5)


def test_ifc_reads_true_north_as_a_bearing(ifc_plan: FloorPlan):
    assert ifc_plan.georeference.north_deg == pytest.approx(18.0, abs=0.01)


def test_ifc_classifies_a_space_from_its_long_name(ifc_plan: FloorPlan):
    space = ifc_plan.space("#100")
    assert space.occupancy == "drawing_office"
    assert "occupancy" in space.inferred


def test_ifc_takes_wall_thickness_from_the_material_layer_set(ifc_plan: FloorPlan):
    wall = ifc_plan.wall("#200")
    assert wall.thickness_m == pytest.approx(0.14)
    # Stated, not measured -- so it is not recorded as an inference.
    assert "thickness_m" not in wall.inferred


def test_ifc_finds_a_door_through_the_void_and_fill_pair(ifc_plan: FloorPlan):
    door = next(o for o in ifc_plan.openings if o.kind == "door")
    assert door.wall_id == "#200"
    assert door.width_m == pytest.approx(0.9)
    assert door.height_m == pytest.approx(2.1)
    # The opening is placed relative to the wall, not the storey: 3 m along a
    # 6 m wall whose own placement puts its start at x=2.
    assert door.along_m == pytest.approx(3.0)


def test_ifc_survives_a_comment_above_an_instance():
    # A `/* ... */` above an instance glues itself to the record; the instance
    # then vanishes with no error. A file with a comment above every storey would
    # lose every storey.
    from simura.space.providers.ifc import _parse_step

    entities = _parse_step(IFC)
    assert 100 in entities and entities[100].name == "IFCSPACE"


def test_ifc_names_the_element_types_it_did_not_read(ifc_plan: FloorPlan):
    skipped = {s.entity: s.count for s in ifc_plan.fidelity.skipped}
    assert skipped.get("IfcSlab") == 1
    # Coverage is measured against elements it could have used, not every
    # cartesian point in the file.
    assert ifc_plan.fidelity.coverage > 0.5


def test_ifc_stacks_its_storeys(ifc_plan: FloorPlan):
    assert [level.name for level in ifc_plan.levels] == ["Ground", "First"]
    assert ifc_plan.levels[0].height_m == pytest.approx(3.6)


def test_a_file_that_is_not_ifc_is_refused_with_a_useful_message():
    with pytest.raises(PlanError, match="not an IFC STEP file"):
        IfcProvider(data=b"<html><body>nope</body></html>", name="x.ifc").plan()


# ---------------------------------------------------------------------------
# round trip and provider construction
# ---------------------------------------------------------------------------

def test_a_plan_survives_a_round_trip_through_json(gbxml_plan: FloorPlan):
    restored = FloorPlan.from_json(gbxml_plan.to_json())
    assert restored.id == gbxml_plan.id
    assert restored.content_hash() == gbxml_plan.content_hash()
    assert len(restored.spaces) == len(gbxml_plan.spaces)
    assert restored.space("sp-office").area_m2 == pytest.approx(24.0)


def test_a_reloaded_plan_still_says_what_was_assumed(gbxml_plan: FloorPlan):
    # Re-recording provenance as "read from JSON, nothing assumed" would be true
    # about the read and a lie about the plan.
    provider = JsonPlanProvider(data=gbxml_plan.to_json().encode(), name="saved.json")
    restored = provider.plan()
    assert not restored.fidelity.complete
    assert restored.fidelity.inferred_fields("space:sp-office")["height_m"].value


def test_build_provider_turns_a_dict_into_a_source(tmp_path):
    assert build_provider({"type": "none"}) is None
    assert build_provider(None) is None
    provider = build_provider({"type": "rect", "rooms": 2})
    assert len(provider.plan().spaces) == 3

    path = tmp_path / "model.xml"
    path.write_text(GBXML, encoding="utf-8")
    plan = build_provider({"type": "gbxml", "path": str(path)}).plan()
    assert len(plan.spaces) == 2


def test_build_provider_rejects_a_type_it_does_not_know():
    with pytest.raises(PlanError, match="unknown plan provider type"):
        build_provider({"type": "revit"})


def test_detect_format_reads_the_contents_when_the_suffix_lies():
    assert detect_format("model.ifc") == "ifc"
    assert detect_format("anything.txt", IFC.encode()) == "ifc"
    assert detect_format("model.xml", GBXML.encode()) == "gbxml"
    assert detect_format("plan.dxf", DXF.encode()) == "dxf"


def test_detect_format_says_what_it_supports_when_it_cannot_tell():
    with pytest.raises(PlanError, match="Supported"):
        detect_format("model.rvt", b"\x00\x01")


def test_a_binary_dxf_is_named_rather_than_mangled():
    with pytest.raises(PlanError, match="ASCII DXF"):
        detect_format("plan.dxf", b"AutoCAD Binary DXF\r\n\x1a\x00")


def test_a_plan_the_size_of_a_desk_is_flagged_as_a_unit_error():
    ok, complaint = plausible_building(0.024, 0.006)
    assert not ok
    assert "millimetres" in complaint
    assert plausible_building(24.0, 12.0)[0]


# ---------------------------------------------------------------------------
# coupling: weather, lights, ambient
# ---------------------------------------------------------------------------

def test_a_georeferenced_model_configures_the_weather_provider(gbxml_plan: FloorPlan):
    spec = weather_spec(gbxml_plan)
    assert spec["type"] == "open_meteo"
    assert spec["latitude"] == pytest.approx(51.4545)
    assert spec["longitude"] == pytest.approx(-2.5879)
    # And it is a spec the weather package actually accepts.
    from simura.weather import build_provider as build_weather

    assert build_weather({**spec, "cached": False}) is not None


def test_a_model_with_no_coordinates_offers_no_weather(dxf_plan: FloorPlan):
    # Not a failure: a fact about the file. The caller keeps the weather it had
    # rather than being handed 0, 0 in the Gulf of Guinea.
    assert weather_spec(dxf_plan) is None


def test_every_room_becomes_a_lighting_problem(gbxml_plan: FloorPlan):
    targets = {t.name: t for t in lighting_targets(gbxml_plan)}
    office = targets["Open Plan Office 0.01"]
    assert office.task == "office"
    assert (office.length_m, office.width_m) == pytest.approx((6.0, 4.0))
    # Mounting height is ceiling minus the working plane, which is what the lumen
    # method means by it.
    assert office.mounting_height_m == pytest.approx(2.8 - 0.8)


def test_a_lighting_target_is_the_argument_list_the_planner_already_takes(
    gbxml_plan: FloorPlan,
):
    from simura.lights.planning import recommend_lamp

    target = next(t for t in lighting_targets(gbxml_plan) if t.task == "office")
    result = recommend_lamp(**target.kwargs())

    # The point is that the call goes through untranslated and the planner
    # designs to the room the model describes -- not that this particular room
    # passes. It does not: a 6 x 4 m office at 500 lux needs more installed
    # watts per square metre than the energy-code guideline allows, which is a
    # real finding about a real room and exactly what the coupling exists to
    # surface.
    assert result.n_luminaires > 0
    assert result.assessment is not None
    assert result.assessment.target_lux == pytest.approx(500.0)
    assert result.alternatives


def test_a_non_rectangular_room_says_the_lumen_method_is_an_approximation(
    gbxml_plan: FloorPlan,
):
    target = next(t for t in lighting_targets(gbxml_plan) if t.space_id == "sp-plant")
    assert not target.rectangular
    assert any("not rectangular" in p for p in target.problems)
    assert not target.designable


def test_a_room_with_no_occupancy_is_reported_rather_than_lit_to_500_lux():
    plan = FloorPlan(
        spaces=[Space(id="s", name="R-114", polygon=rectangle(6.0, 4.0), occupancy="unknown")]
    )
    target = lighting_targets(plan)[0]
    assert not target.designable
    assert any("no occupancy" in p for p in target.problems)


def test_a_conditioned_room_shields_the_equipment_from_the_weather(
    gbxml_plan: FloorPlan,
):
    from simura.weather import StaticProvider

    hot = StaticProvider(air_temp_c=38.0, solar_w_m2=900.0).at(0)

    office = ambient_for(gbxml_plan, "sp-office", hot)
    assert office.indoor
    assert office.ambient_c == pytest.approx(21.0)
    assert office.coupling_kwargs()["shading_frac"] == 1.0

    plant = ambient_for(gbxml_plan, "sp-plant", hot)
    assert not plant.indoor
    assert plant.ambient_c == pytest.approx(38.0)
    assert plant.coupling_kwargs()["shading_frac"] == 0.0


def test_a_room_the_model_says_nothing_about_is_left_unshielded_and_flagged():
    plan = FloorPlan(
        spaces=[Space(id="s", name="Yard", polygon=rectangle(6.0, 4.0), occupancy="storage")]
    )
    context = ambient_for(plan, "s")
    assert not context.stated
    assert "does not say" in context.basis


def test_the_ambient_a_room_gives_is_one_the_battery_coupling_accepts(
    gbxml_plan: FloorPlan,
):
    from simura.sim.environment import EnvironmentCoupling
    from simura.weather import StaticProvider

    hot = StaticProvider(air_temp_c=38.0, solar_w_m2=900.0).at(0)
    indoor = ambient_for(gbxml_plan, "sp-office", hot)
    coupling = EnvironmentCoupling(**indoor.coupling_kwargs())
    effect = coupling.apply(hot)
    # Fully shaded: the sun adds nothing to a cabinet standing indoors.
    assert effect.solar_heat_w == pytest.approx(0.0)


def test_a_summary_rolls_the_whole_import_up(gbxml_plan: FloorPlan):
    report = summary(gbxml_plan)
    assert report["spaces"] == 2
    assert report["located"] is True
    assert report["non_rectangular_rooms"] == 1
    assert report["occupancies"]["office"] == 1
    assert report["fidelity"]["complete"] is False
    assert json.loads(json.dumps(report))  # a summary is always serializable


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------

def test_a_route_is_traced_through_the_rooms_a_cable_would_cross(rect_plan: FloorPlan):
    result = route(rect_plan, (3.0, 3.8), (21.0, 3.8))
    assert result.ok
    # Out of the first room, along the corridor, into the last -- the corridor is
    # named, which is what lets the run's ambient vary along it.
    corridor = next(s for s in rect_plan.spaces if s.occupancy == "corridor")
    assert corridor.id in result.space_ids
    assert result.horizontal_m == pytest.approx(22.0)
    assert result.vertical_m == pytest.approx(5.2)  # two 2.6 m drops


def test_a_route_costs_more_than_the_straight_line_between_its_ends(
    rect_plan: FloorPlan,
):
    from simura.space.geometry import distance

    start, end = (3.0, 3.8), (21.0, 3.8)
    result = route(rect_plan, start, end)
    assert result.length_m > distance(start, end)


def test_route_slack_is_a_stated_fraction_not_a_hidden_one(rect_plan: FloorPlan):
    bare = route(rect_plan, (3.0, 3.8), (21.0, 3.8), slack_frac=0.0)
    slacked = route(rect_plan, (3.0, 3.8), (21.0, 3.8), slack_frac=0.10)
    assert bare.slack_m == pytest.approx(0.0)
    assert slacked.slack_m == pytest.approx(bare.length_m * 0.10)
    assert slacked.length_m == pytest.approx(bare.length_m * 1.10)


def test_two_points_in_the_same_room_are_a_straight_run(rect_plan: FloorPlan):
    result = route(rect_plan, (1.0, 3.0), (5.0, 3.0), slack_frac=0.0)
    assert result.ok
    assert result.horizontal_m == pytest.approx(4.0)


def test_a_route_across_storeys_uses_a_riser():
    plan = RectangleProvider(levels=2, rooms=2).plan()
    lower = plan.spaces_on("level-0")[0]
    upper = plan.spaces_on("level-1")[0]
    result = route(
        plan,
        lower.centroid,
        upper.centroid,
        start_level="level-0",
        end_level="level-1",
    )
    assert result.ok
    assert any(leg.kind == "riser" for leg in result.legs)
    assert result.vertical_m > 3.4


def test_an_unroutable_pair_returns_an_estimate_that_says_it_is_one():
    # A plan with two rooms and no doors between them. An exception here would be
    # useless; a silent straight line would be worse.
    plan = FloorPlan(
        levels=[],
        spaces=[
            Space(id="a", polygon=rectangle(4.0, 4.0, (0.0, 0.0))),
            Space(id="b", polygon=rectangle(4.0, 4.0, (10.0, 0.0))),
        ],
    )
    result = route(plan, (2.0, 2.0), (12.0, 2.0), slack_frac=0.0)
    assert not result.ok
    assert any("no path" in p for p in result.problems)
    assert result.horizontal_m == pytest.approx(10.0)


def test_a_route_reports_the_worst_ambient_along_it(gbxml_plan: FloorPlan):
    from simura.weather import StaticProvider

    hot = StaticProvider(air_temp_c=38.0).at(0)
    result = route(gbxml_plan, (3.0, 2.0), (12.0, 1.0))
    # The run passes through the unconditioned plant room, so it is rated for it,
    # not for the office it started in.
    assert result.hottest_ambient(gbxml_plan, hot) == pytest.approx(38.0)


def test_a_routed_length_drops_straight_into_the_wire_solve(rect_plan: FloorPlan):
    from simura.wires import WireSpec, evaluate_run

    result = route(rect_plan, (3.0, 3.8), (21.0, 3.8))
    spec = WireSpec(**result.wire_kwargs("cu-10-thhn90"))
    assessment = evaluate_run(spec, current_a=20.0, system_voltage_v=48.0)
    assert assessment.voltage_drop_v > 0


# ---------------------------------------------------------------------------
# a plan that travels in the spec that names it
# ---------------------------------------------------------------------------

def test_a_plan_can_be_carried_in_the_spec_rather_than_pointed_at(rect_plan: FloorPlan):
    from simura.space import InlinePlanProvider, one_room

    room_id = rect_plan.spaces[0].id
    payload = one_room(rect_plan, room_id)
    plan = InlinePlanProvider(payload).plan()
    assert len(plan.spaces) == 1
    assert plan.space(room_id) is not None
    assert plan.georeference.north_deg == rect_plan.georeference.north_deg


def test_one_room_is_a_fraction_of_the_whole_building(rect_plan: FloorPlan):
    # Embedding the whole plan in every rack would bloat every spec, every diff
    # and every library entry with geometry none of them read.
    whole = len(rect_plan.to_json(indent=None))
    room = len(json.dumps(one_room_payload(rect_plan)))
    assert room < whole / 3


def one_room_payload(plan: FloorPlan) -> dict:
    from simura.space import one_room

    return one_room(plan, plan.spaces[0].id)


def test_a_carried_room_still_says_what_was_assumed_about_it(gbxml_plan: FloorPlan):
    from simura.space import InlinePlanProvider, one_room

    carried = InlinePlanProvider(one_room(gbxml_plan, "sp-office")).plan()
    assert not carried.fidelity.complete
    assert carried.fidelity.inferred_fields("space:sp-office")["height_m"].basis
    assert "height_m" in carried.space("sp-office").inferred


def test_an_inline_provider_refuses_something_that_is_not_a_plan():
    from simura.space import InlinePlanProvider

    with pytest.raises(PlanError, match="not a floor plan"):
        InlinePlanProvider({"hello": "world"})
    with pytest.raises(PlanError, match="needs a 'plan'"):
        InlinePlanProvider()


def test_build_provider_understands_an_inline_plan(rect_plan: FloorPlan):
    from simura.space import one_room

    provider = build_provider(
        {"type": "inline", "plan": one_room(rect_plan, rect_plan.spaces[0].id)}
    )
    assert len(provider.plan().spaces) == 1


# ---------------------------------------------------------------------------
# the room a system stands in
# ---------------------------------------------------------------------------

def test_a_conditioned_room_drops_the_weather_source_rather_than_damping_it(
    gbxml_plan: FloorPlan,
):
    """Standing indoors is not a modifier on the weather.

    It is the statement that the weather does not reach this pack: no sun on the
    cabinet, no wind over it, and an ambient held at the room's setpoint. Dropping
    the source is both the truthful model and the one that needs no new
    coefficient nobody could justify.
    """
    from simura.builder import SystemSpec, build_simulator
    from simura.builder.spec import SpaceSpec, WeatherSpec
    from simura.space import one_room

    hot = WeatherSpec(type="static", params={"air_temp_c": 41.0, "solar_w_m2": 950.0})

    indoors = build_simulator(
        SystemSpec(
            weather=hot,
            space=SpaceSpec(
                type="inline",
                params={"plan": one_room(gbxml_plan, "sp-office")},
                space_id="sp-office",
            ),
        )
    )
    assert indoors.weather is None
    assert indoors.pack.config.ambient_temp_c == pytest.approx(21.0)

    outdoors = build_simulator(
        SystemSpec(
            weather=hot,
            space=SpaceSpec(
                type="inline",
                params={"plan": one_room(gbxml_plan, "sp-plant")},
                space_id="sp-plant",
            ),
        )
    )
    assert outdoors.weather is not None


def test_a_system_with_no_building_behaves_exactly_as_it_did_before():
    from simura.builder import SystemSpec, build_simulator
    from simura.builder.spec import WeatherSpec

    sim = build_simulator(
        SystemSpec(weather=WeatherSpec(type="static", params={"air_temp_c": 41.0}))
    )
    assert sim.weather is not None
    assert SystemSpec().space.type == "none"


def test_a_building_that_cannot_be_read_costs_the_system_its_room_and_nothing_else():
    """A floor plan is context, not a dependency.

    A system whose building file has moved should still run, minus what the
    building was telling it. The alternative — a spec that raises because a model
    is missing — makes every saved system hostage to a path.
    """
    from simura.builder import SystemSpec, build_simulator
    from simura.builder.spec import SpaceSpec

    sim = build_simulator(
        SystemSpec(
            space=SpaceSpec(
                type="gbxml", params={"path": "/nowhere/gone.xml"}, space_id="sp-1"
            )
        )
    )
    assert sim is not None


def test_the_room_is_site_so_the_same_design_runs_in_two_of_them(gbxml_plan: FloorPlan):
    from simura.builder import SystemSpec
    from simura.library.site import SITE_FIELDS, apply_site, restore_site
    from simura.space import one_room

    design = SystemSpec(series=16, parallel=4).to_dict()
    assert "space" in SITE_FIELDS

    plant = apply_site(
        design,
        {
            "space": {
                "type": "inline",
                "params": {"plan": one_room(gbxml_plan, "sp-plant")},
                "space_id": "sp-plant",
            }
        },
    )
    assert plant["space"]["space_id"] == "sp-plant"
    assert plant["series"] == 16
    # And carrying it into a room does not become a change to the design.
    assert restore_site(plant, design, ("space",))["space"]["type"] == "none"


# ---------------------------------------------------------------------------
# diagnosis: the import worked and the result is still not the building
# ---------------------------------------------------------------------------

def test_a_clean_plan_has_nothing_to_diagnose(rect_plan: FloorPlan):
    from simura.space.diagnose import report

    result = report(rect_plan)
    assert result["ok"]
    assert result["findings"] == []
    assert result["doors"] == 4


def test_one_stray_coordinate_is_found_and_named(rect_plan: FloorPlan):
    """The commonest reason an imported model renders as one huge flat shape.

    A single room left at a survey origin while everything else sits near zero.
    The room count looks right, the import reports no problems, and the plan is
    5,000 km across — so the real building becomes a speck in one corner of it.
    """
    from simura.space.diagnose import report

    strays = list(rect_plan.spaces) + [
        Space(
            id="stray",
            name="Site",
            level_id="level-0",
            polygon=rectangle(20.0, 20.0, (412_000.0, 5_790_000.0)),
        )
    ]
    broken = FloorPlan(
        name="With a stray",
        levels=rect_plan.levels,
        spaces=strays,
        walls=rect_plan.walls,
        openings=rect_plan.openings,
    )
    result = report(broken)
    assert not result["ok"]

    kinds = [f["what"] for f in result["findings"]]
    assert any("far from everything else" in k for k in kinds)
    assert any("spans" in k for k in kinds)
    # And it names the culprit, which is the whole point of reporting it.
    outlier = next(f for f in result["findings"] if "far from" in f["what"])
    assert any("stray" in s for s in outlier["subjects"])


def test_a_model_with_no_doorways_says_you_will_not_be_able_to_move():
    from simura.space.diagnose import report

    plan = FloorPlan(
        levels=[],
        spaces=[Space(id="a", polygon=rectangle(6.0, 4.0))],
        walls=[Wall(id="w", axis=[(0.0, 0.0), (6.0, 0.0)])],
    )
    result = report(plan)
    assert any("no doorways" in f["what"] for f in result["findings"])


def test_a_room_the_size_of_a_site_boundary_is_reported():
    from simura.space.diagnose import report

    plan = FloorPlan(
        spaces=[
            Space(id="real", polygon=rectangle(6.0, 4.0)),
            Space(id="boundary", polygon=rectangle(300.0, 300.0)),
        ]
    )
    findings = report(plan)["findings"]
    assert any("larger than" in f["what"] for f in findings)


def test_an_opening_whose_wall_never_arrived_is_reported():
    from simura.space.diagnose import report

    plan = FloorPlan(
        spaces=[Space(id="a", polygon=rectangle(6.0, 4.0))],
        walls=[Wall(id="w", axis=[(0.0, 0.0), (6.0, 0.0)])],
        openings=[
            Opening(id="d1", wall_id="w", kind="door", along_m=3.0),
            Opening(id="d2", wall_id="missing", kind="door", along_m=1.0),
        ],
    )
    findings = report(plan)["findings"]
    assert any("wall was not imported" in f["what"] for f in findings)


def test_the_diagnosis_is_always_serializable(gbxml_plan: FloorPlan):
    from simura.space.diagnose import report

    assert json.loads(json.dumps(report(gbxml_plan)))


# ---------------------------------------------------------------------------
# openings, positioned the way a viewer positions them
# ---------------------------------------------------------------------------

# An opening whose profile is a *vertical* rectangle (height x width, standing in
# the wall's elevation plane) with its corner — not its centre — on the local
# origin. This is what Revit writes, and it is the case a naive reader gets
# wrong: projecting the placement origin lands on an edge of the hole rather than
# in the middle of it, and the door comes out half a leaf-width off.
IFC_OPENING = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('o.ifc','2026-08-26T09:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC2X3'));
ENDSEC;
DATA;
#1= IFCPROJECT('0proj00000000000000001',$,'Openings',$,$,$,$,(#20),#10);
#10= IFCUNITASSIGNMENT((#11));
#11= IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#20= IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.0E-5,#30,$);
#30= IFCAXIS2PLACEMENT3D(#31,$,$);
#31= IFCCARTESIANPOINT((0.,0.,0.));
#70= IFCBUILDINGSTOREY('0stry00000000000000001',$,'Ground',$,$,#71,$,$,.ELEMENT.,0.);
#71= IFCLOCALPLACEMENT($,#30);
/* a 4 m wall along +x */
#200= IFCWALLSTANDARDCASE('0wal000000000000000001',$,'Wall',$,$,#201,#210,$);
#201= IFCLOCALPLACEMENT(#71,#30);
#210= IFCPRODUCTDEFINITIONSHAPE($,$,(#211));
#211= IFCSHAPEREPRESENTATION(#20,'Axis','Curve2D',(#212));
#212= IFCPOLYLINE((#2121,#2122));
#2121= IFCCARTESIANPOINT((0.,0.));
#2122= IFCCARTESIANPOINT((4.,0.));
/* the opening: 0.9 wide, 2.1 tall, centred at x=2.5, profile corner on the origin */
#230= IFCOPENINGELEMENT('0opn000000000000000001',$,'Doorway',$,$,#231,#235,$);
#231= IFCLOCALPLACEMENT(#201,#232);
#232= IFCAXIS2PLACEMENT3D(#233,#2341,#2342);
#233= IFCCARTESIANPOINT((2.05,0.,0.));
#2341= IFCDIRECTION((0.,-1.,0.));
#2342= IFCDIRECTION((0.,0.,1.));
#235= IFCPRODUCTDEFINITIONSHAPE($,$,(#236));
#236= IFCSHAPEREPRESENTATION(#20,'Body','SweptSolid',(#237));
#237= IFCEXTRUDEDAREASOLID(#238,#243,#245,0.3);
#238= IFCRECTANGLEPROFILEDEF(.AREA.,$,#239,2.1,0.9);
#239= IFCAXIS2PLACEMENT2D(#240,$);
#240= IFCCARTESIANPOINT((1.05,0.45));
#243= IFCAXIS2PLACEMENT3D(#244,$,$);
#244= IFCCARTESIANPOINT((0.,0.,0.));
#245= IFCDIRECTION((0.,0.,1.));
#250= IFCDOOR('0dor000000000000000001',$,'Door',$,$,#251,$,$,2.1,0.81);
#251= IFCLOCALPLACEMENT(#231,#232);
#260= IFCRELVOIDSELEMENT('0rel000000000000000002',$,$,$,#200,#230);
#261= IFCRELFILLSELEMENT('0rel000000000000000003',$,$,$,#230,#250);
#400= IFCRELCONTAINEDINSPATIALSTRUCTURE('0rel000000000000000004',$,$,$,(#200),#70);
ENDSEC;
END-ISO-10303-21;
"""


def test_an_opening_is_placed_from_its_own_solid_not_its_placement_origin():
    """The measurement a boolean subtraction would make.

    An IFC profile is positioned *within* its placement, so the placement origin
    is frequently a corner of the hole rather than its middle. Reading the
    solid's extent along the wall is immune to that, and to however the placement
    is turned — the two things that otherwise put a door half a leaf-width into
    the wall beside it.
    """
    plan = IfcProvider(data=IFC_OPENING.encode(), name="o.ifc").plan()
    opening = plan.openings[0]
    wall = plan.wall(opening.wall_id)
    assert wall is not None

    # The hole is the *opening's* 0.9 m, not the door leaf's 0.81 m.
    assert opening.width_m == pytest.approx(0.9, abs=0.02)
    assert opening.height_m == pytest.approx(2.1, abs=0.02)
    # And it sits wholly inside the wall it is cut in.
    assert opening.along_m - opening.width_m / 2 >= -0.01
    assert opening.along_m + opening.width_m / 2 <= wall.length_m + 0.01


def test_no_opening_hangs_off_the_end_of_its_wall(gbxml_plan: FloorPlan):
    """A frame in mid-air past the end of a wall reads as a bug in the viewer.

    It is usually a placement this importer read imperfectly, so the opening is
    pulled back inside and the move is recorded rather than quietly made.
    """
    for opening in gbxml_plan.openings:
        wall = gbxml_plan.wall(opening.wall_id)
        if wall is None or wall.length_m <= opening.width_m:
            continue
        assert opening.along_m - opening.width_m / 2 >= -0.01, opening.id
        assert opening.along_m + opening.width_m / 2 <= wall.length_m + 0.01, opening.id
