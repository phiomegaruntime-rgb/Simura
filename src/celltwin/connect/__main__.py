"""CLI entry point:  python -m celltwin.connect --config <file>"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from .config import build_connector, load_config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Run a CellTwin hardware connector.")
    parser.add_argument("--config", required=True, help="path to a connector config (.yaml/.json)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    # Allow env overrides so one config works in dev and in docker compose.
    cfg.setdefault("mqtt", {})
    if os.environ.get("CELLTWIN_MQTT_HOST"):
        cfg["mqtt"]["host"] = os.environ["CELLTWIN_MQTT_HOST"]
    if os.environ.get("CELLTWIN_MQTT_PORT"):
        cfg["mqtt"]["port"] = int(os.environ["CELLTWIN_MQTT_PORT"])
    if os.environ.get("CELLTWIN_DEVICE_HOST") and "host" in cfg.get("source", {}):
        cfg["source"]["host"] = os.environ["CELLTWIN_DEVICE_HOST"]
    if os.environ.get("CELLTWIN_DEVICE_URL") and "url" in cfg.get("source", {}):
        cfg["source"]["url"] = os.environ["CELLTWIN_DEVICE_URL"]

    connector = build_connector(cfg)
    asyncio.run(connector.run())


if __name__ == "__main__":
    main()
