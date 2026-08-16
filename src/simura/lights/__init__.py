"""Reusable, domain-agnostic simulation of light sources and lighting design.

This subpackage knows **light and the human eye, not batteries** -- the same
deliberate independence as :mod:`simura.weather` and :mod:`simura.wires`. It
models a light source from its spectrum up: Planck's law and the CIE observer give
luminous efficacy, an electro-thermal model gives what the source is actually
doing, and photometry turns the lumens into lux on a surface.

Every light source people use is here, across four physical families:

* **Thermal radiators** -- incandescent and tungsten halogen. A hot filament, a
  Planck spectrum, and about five percent of the input as visible light.
* **Solid state** -- white LEDs (a blue die under a phosphor) and laser diodes.
  A diode law, efficiency droop, and a junction temperature that decides
  everything.
* **Low-pressure discharge** -- fluorescent, CFL, induction, low-pressure sodium,
  neon. Sharply temperature-dependent, because ambient sets the vapour pressure.
* **High-pressure discharge** -- metal halide, high-pressure sodium, mercury
  vapour, xenon short-arc. Minutes to warm up, and a restrike delay once hot.

Efficacy is never looked up. It is computed from the spectrum each source
actually radiates, which is why dimming an incandescent lamp costs far more light
than power, why warm-white LEDs lose to cool-white ones, and why low-pressure
sodium beats everything ever built and renders no colour at all.

    from simura.lights import LightSpec, Light, evaluate_installation

    lamp = Light(LightSpec(lamp_type="led-9-e27"))
    point = lamp.operating_point(drive=1.0, ambient_c=25.0)
    print(point.luminous_flux_lm, point.efficacy_lm_per_w, point.color_temp_k)

    a = evaluate_installation(LightSpec(lamp_type="led-15-e27"), n_luminaires=6,
                              length_m=8, width_m=6, task="office")
    print(a.maintained_lux, a.problems)
"""

from .catalog import (
    FAMILIES,
    LAMP_CATALOG,
    TECHNOLOGIES,
    LampType,
    LightTechnology,
    lamp_type_for,
    list_lamp_types,
    list_technologies,
    technology_for,
)
from .config import (
    LIGHT_CONTROL_TYPES,
    LIGHT_FAULT_TYPES,
    LIGHT_PROFILE_TYPES,
    LIGHT_TECHNOLOGIES,
    build_control,
    build_coupling,
    build_fault,
    build_light,
    build_profile,
    catalog_options,
)
from .environment import (
    K_DAYLIGHT_LM_PER_W,
    DaylightHarvesting,
    LightEnvironmentCoupling,
    LightEnvironmentEffect,
    PhotocellControl,
    apply_to_effect as apply_weather_to_effect,
    clear_sky_ghi_w_m2,
    daylight_illuminance_lux,
    solar_declination_deg,
    solar_elevation_deg,
)
from .faults import (
    Burnout,
    DriverFault,
    Fault,
    Flicker,
    HeatsinkLoss,
    LensFouling,
    LightFaultEffect,
    LumenDepreciation,
    PhosphorDegradation,
    SupplyVoltageFault,
    accumulate,
)
from .lamp import Light, LightSpec, OperatingPoint, SupplyPoint
from .layout import Layout, LayoutResult, Luminaire, LuminaireResult, build_layout
from .photometry import (
    TASK_ILLUMINANCE_LUX,
    RoomLighting,
    beam_solid_angle_sr,
    illuminance_lux,
    light_loss_factor,
    lumen_method,
    luminaires_for_target,
    luminous_intensity_cd,
    point_illuminance_lux,
    room_index,
    task_lux,
    utilisation_factor,
)
from .planning import (
    InstallationAssessment,
    Recommendation,
    evaluate_installation,
    recommend_lamp,
)
from .profiles import (
    CallableDrive,
    ConstantDrive,
    DriveProfile,
    OccupancyCycle,
    PwmDrive,
    Ramp,
    Schedule,
    sinusoidal,
)
from .simulator import LightSimConfig, LightSimulator
from .spectrum import (
    K_M,
    SIGMA_SB,
    Spectrum,
    arc_continuum,
    blackbody,
    emission_lines,
    gaussian_band,
    phosphor_led,
    photopic,
    planck_exitance,
    selective_thermal,
    thermal_radiator,
    wien_peak_nm,
)

__all__ = [
    # spectrum
    "Spectrum",
    "blackbody",
    "selective_thermal",
    "arc_continuum",
    "gaussian_band",
    "emission_lines",
    "phosphor_led",
    "planck_exitance",
    "photopic",
    "wien_peak_nm",
    "thermal_radiator",
    "K_M",
    "SIGMA_SB",
    # catalog
    "LightTechnology",
    "LampType",
    "TECHNOLOGIES",
    "LAMP_CATALOG",
    "FAMILIES",
    "technology_for",
    "lamp_type_for",
    "list_technologies",
    "list_lamp_types",
    # core model
    "LightSpec",
    "Light",
    "OperatingPoint",
    "SupplyPoint",
    "LightSimulator",
    "LightSimConfig",
    # profiles
    "DriveProfile",
    "ConstantDrive",
    "Schedule",
    "Ramp",
    "PwmDrive",
    "OccupancyCycle",
    "CallableDrive",
    "sinusoidal",
    # faults
    "Fault",
    "LightFaultEffect",
    "LumenDepreciation",
    "PhosphorDegradation",
    "HeatsinkLoss",
    "DriverFault",
    "SupplyVoltageFault",
    "Flicker",
    "LensFouling",
    "Burnout",
    "accumulate",
    # photometry
    "beam_solid_angle_sr",
    "luminous_intensity_cd",
    "illuminance_lux",
    "point_illuminance_lux",
    "room_index",
    "utilisation_factor",
    "light_loss_factor",
    "lumen_method",
    "luminaires_for_target",
    "task_lux",
    "RoomLighting",
    "TASK_ILLUMINANCE_LUX",
    # planning
    "evaluate_installation",
    "recommend_lamp",
    "InstallationAssessment",
    "Recommendation",
    # layout
    "Layout",
    "Luminaire",
    "LuminaireResult",
    "LayoutResult",
    "build_layout",
    # declarative
    "build_light",
    "build_fault",
    "build_profile",
    "build_control",
    "build_coupling",
    "catalog_options",
    "LIGHT_TECHNOLOGIES",
    "LIGHT_FAULT_TYPES",
    "LIGHT_PROFILE_TYPES",
    "LIGHT_CONTROL_TYPES",
    # environment / weather + daylight coupling
    "LightEnvironmentCoupling",
    "LightEnvironmentEffect",
    "apply_weather_to_effect",
    "PhotocellControl",
    "DaylightHarvesting",
    "solar_elevation_deg",
    "solar_declination_deg",
    "clear_sky_ghi_w_m2",
    "daylight_illuminance_lux",
    "K_DAYLIGHT_LM_PER_W",
]
