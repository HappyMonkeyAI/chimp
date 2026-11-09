"""Run the router from a config file."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import uvicorn

from chimp.app import build_app
from chimp.config import ConfigError, load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="chimp", description="Local OpenAI-compatible VRAM-sticky router")
    parser.add_argument(
        "--config",
        default=os.environ.get("CHIMP_CONFIG", "config.yaml"),
        help="Path to config.yaml (or set CHIMP_CONFIG)",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip startup affinity scoring of live inventory (also CHIMP_NO_ENRICH=1)",
    )
    args = parser.parse_args(argv)

    if args.no_enrich:
        os.environ["CHIMP_NO_ENRICH"] = "1"

    logging.basicConfig(
        level=os.environ.get("CHIMP_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config_path = Path(args.config)
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"chimp: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    app = build_app(settings)
    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port, log_level="info")


if __name__ == "__main__":
    main()
