"""Build and preview your own battery system from a serializable spec.

The system builder lets a user describe a battery system -- chemistry, cell
parameters, topology, load profile, faults, sim settings -- as a
:class:`~celltwin.builder.spec.SystemSpec`, then:

* :func:`~celltwin.builder.validate.validate_spec` -- check it (list of problems),
* :func:`~celltwin.builder.preview.preview` -- run it offline and summarize,
* :func:`~celltwin.builder.build.build_simulator` -- get a live
  :class:`~celltwin.sim.simulator.Simulator`,

and stream it into the twin with ``python -m celltwin.publisher --spec my.json``.

    from celltwin.builder import SystemSpec, preview
    spec = SystemSpec(name="My LFP pack", chemistry="LFP", series=16, parallel=4)
    print(preview(spec).peak_temp_c)
"""

from .build import (
    FAULT_TYPES,
    PROFILE_TYPES,
    build_coupling,
    build_faults,
    build_pack_config,
    build_profile,
    build_sim_config,
    build_simulator,
    build_weather,
)
from .options import builder_options
from .preview import PreviewResult, SpecError, preview
from .spec import FaultSpec, ProfileSpec, SystemSpec, WeatherSpec
from .validate import validate_spec

__all__ = [
    "SystemSpec",
    "ProfileSpec",
    "FaultSpec",
    "WeatherSpec",
    "validate_spec",
    "build_simulator",
    "build_pack_config",
    "build_sim_config",
    "build_profile",
    "build_faults",
    "build_weather",
    "build_coupling",
    "preview",
    "PreviewResult",
    "SpecError",
    "builder_options",
    "PROFILE_TYPES",
    "FAULT_TYPES",
]
