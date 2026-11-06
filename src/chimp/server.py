"""Run the router from a config file."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import uvicorn

from chimp.app import build_app
from chimp.config import ConfigError, load_settings


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("CHIMP_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config_path = Path(os.environ.get("CHIMP_CONFIG", "config.yaml"))
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"chimp: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    app = build_app(settings)
    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port, log_level="info")


if __name__ == "__main__":
    main()
