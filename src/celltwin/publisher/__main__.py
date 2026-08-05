"""CLI entry point:  python -m celltwin.publisher [options]"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os

from ..builder import SystemSpec
from .run import publish_run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Publish simulated BESS telemetry to MQTT.")
    parser.add_argument("--system-id", default=None,
                        help="override the system id (defaults to the spec's, or 'bess-01')")
    parser.add_argument("--scenario", default="fault", choices=["healthy", "fault"])
    parser.add_argument("--spec", default=None,
                        help="path to a SystemSpec JSON (from the builder); defines the whole "
                             "system and overrides --scenario")
    parser.add_argument("--mqtt-host", default=os.environ.get("CELLTWIN_MQTT_HOST", "localhost"))
    parser.add_argument("--mqtt-port", type=int, default=int(os.environ.get("CELLTWIN_MQTT_PORT", "1883")))
    parser.add_argument("--speed", type=float, default=float(os.environ.get("CELLTWIN_SPEED", "10.0")),
                        help="real-time multiplier (1=wall clock, 10=10x faster)")
    parser.add_argument("--loop", action="store_true", default=os.environ.get("CELLTWIN_LOOP") == "1",
                        help="restart the scenario forever")
    args = parser.parse_args()

    spec = None
    if args.spec:
        with open(args.spec, "r", encoding="utf-8") as fh:
            spec = SystemSpec.from_dict(json.load(fh))

    system_id = (
        args.system_id
        or (spec.system_id if spec is not None else None)
        or os.environ.get("CELLTWIN_SYSTEM_ID", "bess-01")
    )

    asyncio.run(
        publish_run(
            system_id=system_id,
            scenario=args.scenario,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            speed=args.speed,
            loop=args.loop,
            spec=spec,
        )
    )


if __name__ == "__main__":
    main()
