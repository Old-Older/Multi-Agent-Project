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
    p.add_argument("--keep", action="store_true",
                   help="demo only: keep the memory and files of the previous run (default: start clean)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="also print the log on the screen (it always goes to <data-dir>/mas.log)")
    return p.parse_args(argv)


def configure_logging(log_path: Path, verbose: bool = False) -> None:
    """The log goes to a file, so that a stack trace does not land in the middle of the chat
    (the chat itself shows a one-line error). With `verbose` it is printed on the screen too."""
    handlers: list[logging.Handler] = []
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError as exc:
        print(f"cannot write the log file {log_path}: {exc}", file=sys.stderr)
    if verbose or not handlers:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


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
    load_dotenv_if_available()
    overrides = {"data_dir": args.data_dir} if args.data_dir else {}
    settings = Settings.from_env(**overrides)
    configure_logging(settings.data_dir / "mas.log", args.verbose)
    if args.demo:
        if not args.keep:
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
