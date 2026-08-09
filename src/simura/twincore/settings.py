"""Twin-core configuration, read from environment variables (12-factor).

All variables are prefixed ``SIMURA_`` so they compose cleanly in docker
compose and Kubernetes. Defaults target a local ``docker compose up``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIMURA_", env_file=".env", extra="ignore")

    # MQTT broker
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_reconnect_s: float = 3.0

    # CORS: allowed browser origins for the dashboard in dev (comma-separated,
    # or "*" for any). In the docker stack nginx proxies same-origin, so this
    # mainly matters when running the Vite dev server against the twin core.
    cors_origins: str = "*"

    # Optional API key. Empty = auth disabled (the default, so the demo stack is
    # frictionless). When set, /api/* and the WebSocket require it; /health stays
    # open. Present it as `Authorization: Bearer <key>`, `X-API-Key: <key>`, or
    # `?api_key=<key>` (WebSocket).
    api_key: str = ""

    # A system is considered "live" in the fleet rollup if its latest telemetry
    # frame is no older than this many seconds.
    fleet_stale_after_s: float = 15.0

    # Max size (MB) for a dataset uploaded to /api/validation/upload. Keep the
    # dashboard's nginx `client_max_body_size` at or above this.
    validation_max_upload_mb: float = 25.0

    # Default real-time multiplier for twin-core-run simulations (Component 10):
    # 10.0 plays a simulated minute per ~6 real seconds.
    sim_default_speed: float = 10.0

    # TimescaleDB / Postgres
    database_url: str = "postgresql://simura:simura@localhost:5432/simura"
    db_min_pool: int = 1
    db_max_pool: int = 5
    db_connect_retries: int = 30
    db_connect_retry_s: float = 2.0

    # How long the twin core waits (seconds) for dependencies at startup is
    # db_connect_retries * db_connect_retry_s.


def get_settings() -> Settings:
    return Settings()
