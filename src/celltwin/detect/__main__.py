"""CLI entry point:  python -m celltwin.detect [options]"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from .service import run_detector


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Peer-consensus anomaly detector for CellTwin.")
    parser.add_argument("--mqtt-host", default=os.environ.get("CELLTWIN_MQTT_HOST", "localhost"))
    parser.add_argument(
        "--mqtt-port", type=int, default=int(os.environ.get("CELLTWIN_MQTT_PORT", "1883"))
    )
    args = parser.parse_args()
    asyncio.run(run_detector(mqtt_host=args.mqtt_host, mqtt_port=args.mqtt_port))


if __name__ == "__main__":
    main()
