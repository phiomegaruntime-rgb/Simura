"""Where efficacy comes from: the spectrum, and what dimming does to it.

Every lumen in :mod:`simura.lights` is computed from the spectral power
distribution a source actually radiates, integrated against the CIE observer.
Nothing is looked up. This script shows what that buys you:

1. **Every technology's spectrum**, side by side, and the efficacy of radiation
   that falls out of each -- from sodium's single yellow line (over 500 lm per
   radiated watt, and no colour at all) to a filament's Planck curve (15, most of
   it infrared).
2. **Dimming an incandescent lamp**, where the filament cools, the Planck curve
   slides into the infrared, and the light goes orange while the efficacy
   collapses. None of that is coded; it emerges.
3. **Warm white versus cool white**, the same LED under more phosphor, paying for
   its colour in lumens per watt.

Usage:
    python examples/light_spectrum.py

Needs nothing but the standard library.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Windows consoles default to cp1252; force UTF-8 so the units never crash it.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from simura.lights import Light, LightSpec, list_lamp_types  # noqa: E402


def spark(spd, width: int = 46) -> str:
    """A one-line sketch of a spectrum across the visible band."""
    blocks = " .:-=+*#%@"
    peak = max(spd.values) or 1.0
    out = []
    for i in range(width):
        nm = 380.0 + (700.0 - 380.0) * i / (width - 1)
        v = spd.values[int(round(nm - 360.0))] / peak
        out.append(blocks[min(len(blocks) - 1, int(v * (len(blocks) - 1) + 0.5))])
    return "".join(out)


def main() -> None:
    print("1) One lamp per technology: the spectrum, and what it is worth")
    print("=" * 78)
    print(f"  {'lamp':<18}{'380 ————— spectrum ————— 700 nm':<48}{'LER':>6}{'lm/W':>7}{'CCT':>7}")
    print("  " + "-" * 76)

    seen: set[str] = set()
    for lamp in list_lamp_types():
        if lamp.technology in seen:
            continue
        seen.add(lamp.technology)
        light = Light(LightSpec(lamp_type=lamp.id))
        light.time_lit_s = 1e9              # warmed up
        point = light.operating_point(1.0, 25.0)
        cct = f"{point.color_temp_k:.0f}" if point.color_temp_k > 0 else "—"
        print(
            f"  {lamp.id:<18}{spark(light.spectrum()):<48}"
            f"{point.ler_lm_per_w:>6.0f}{point.efficacy_lm_per_w:>7.1f}{cct:>7}"
        )

    print("\n  LER is the efficacy of *radiation* — the ceiling this spectrum could")
    print("  reach if every watt became light of exactly this colour. Sodium's one")
    print("  yellow line sits 3 nm from the eye's peak sensitivity and scores over")
    print("  500; a filament's Planck curve puts 90% of its power in the infrared")
    print("  and scores 22. A lamp's real efficacy is that ceiling times the share")
    print("  of its input that becomes radiation at all.")

    print("\n\n2) Dimming a 60 W incandescent lamp")
    print("=" * 78)
    light = Light(LightSpec(lamp_type="inc-60-e27"))
    print(f"  {'dim':>5}{'filament':>10}{'power':>9}{'flux':>9}{'lm/W':>8}{'CCT':>7}  spectrum")
    print("  " + "-" * 76)
    for pct in (100, 80, 60, 40, 20):
        point = light.operating_point(pct / 100.0)
        filament_k = point.source_temp_c + 273.15
        cct = f"{point.color_temp_k:.0f}" if point.color_temp_k > 0 else "—"
        print(
            f"  {pct:>4}%{filament_k:>9.0f}K{point.input_power_w:>8.1f}W"
            f"{point.luminous_flux_lm:>8.0f}l{point.efficacy_lm_per_w:>8.2f}{cct:>7}  "
            f"{spark(light.spectrum(filament_k), 28)}"
        )
    print("\n  At 80% on the dimmer the lamp still draws 71% of its power and")
    print("  delivers 40% of its light. Half the dimmer's 'saving' is heat.")

    print("\n\n3) The colour-versus-efficacy trade, in the same LED")
    print("=" * 78)
    print(f"  {'lamp':<18}{'CCT':>7}{'CRI':>6}{'lm/W':>8}  what changed")
    print("  " + "-" * 76)
    for lamp_id, note in [
        ("led-100-flood", "least phosphor — cool white, most efficacious"),
        ("led-15-e27", "more phosphor — neutral white"),
        ("led-9-e27", "more still — warm white, more Stokes loss"),
        ("led-12-cri95", "a red phosphor as well — CRI 95, and it costs"),
    ]:
        light = Light(LightSpec(lamp_type=lamp_id))
        point = light.operating_point(1.0, 25.0)
        print(
            f"  {lamp_id:<18}{point.color_temp_k:>7.0f}{light.tech.cri:>6.0f}"
            f"{point.efficacy_lm_per_w:>8.1f}  {note}"
        )
    print("\n  Nothing in the model states that warm white is less efficacious.")
    print("  The phosphor blend is chosen to land the lamp on the Planckian locus")
    print("  at its rated colour temperature, and the efficacy is whatever the")
    print("  resulting spectrum gives.")


if __name__ == "__main__":
    main()
