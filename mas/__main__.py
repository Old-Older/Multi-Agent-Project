"""Command line entry: `python -m mas` (the real system) or `python -m mas --demo`."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from mas.app import build_system, make_human, make_llm
from mas.config import Settings
from mas.demo import build_demo_system, demo_settings, reset_demo_data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m mas", description="Multi-agent collaboration system.")
    p.add_argument("--demo", action="store_true",
                   help="run a demo that needs no API key (stand-in LLM and workers)")
    p.add_argument("--data-dir", type=Path, default=None,
                   help="where memory, sessions and outputs go (default: ./data; the demo uses <data-dir>/demo)")
    p.add_argument("--delay", type=float, default=0.4, help="demo only: seconds each demo step takes")
    p.add_argument("--fresh", action="store_true", help="demo only: delete the demo's old memory and files first")
    p.add_argument("-v", "--verbose", action="store_true", help="show log messages (default: warnings only)")
    return p.parse_args(argv)


def load_dotenv_if_available() -> None:
    """Read .env into the environment if python-dotenv is installed (it never overrides
    variables that are already set)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    load_dotenv_if_available()
    overrides = {"data_dir": args.data_dir} if args.data_dir else {}
    settings = Settings.from_env(**overrides)
    if args.demo:
        if args.fresh:
            reset_demo_data(settings.data_dir)
        system = build_demo_system(demo_settings(settings, settings.data_dir), delay=args.delay)
    else:
        system = build_system(settings, make_llm(settings), make_human(settings))
    try:
        asyncio.run(system.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
