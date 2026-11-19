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
from mas.scenario import driver_for, load_scenario
from mas.team import load_team


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m mas", description="Multi-agent collaboration system.")
    p.add_argument("--demo", action="store_true",
                   help="run a demo that needs no API key (stand-in LLM and workers)")
    p.add_argument("--data-dir", type=Path, default=None,
                   help="where memory, sessions and outputs go (default: ./data; the demo uses <data-dir>/demo)")
    p.add_argument("--team", type=Path, default=None,
                   help="the team: a Markdown file (or a scenario folder) in the format of 01_role_initialization.md")
    p.add_argument("--scenario", type=Path, default=None,
                   help="a scenario folder (role file + task files): the team is loaded from it and its tasks are "
                        "posted to the group one after the other")
    p.add_argument("--llm", choices=("hkgai", "deepseek"), default=None,
                   help="which LLM to use (default: LLM_PROVIDER from .env, else hkgai)")
    p.add_argument("--auto", action="store_true",
                   help="unattended: the AutoResponder answers every question, the run ends after the last task")
    p.add_argument("--time-budget", type=float, default=None, metavar="SECONDS",
                   help="seconds one request may take (waiting for you not counted); the team hands in what it has "
                        "as it runs out (default 270; 0: no budget)")
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
    overrides: dict[str, object] = {"data_dir": args.data_dir} if args.data_dir else {}
    if args.auto:
        overrides["auto_hitl"] = True
    if args.llm:
        overrides["llm_provider"] = args.llm
    if args.auto and args.scenario is None:
        raise SystemExit("--auto runs a scenario unattended: add --scenario <folder>.")
    if args.time_budget is not None:
        overrides["request_budget_s"] = args.time_budget
    settings = Settings.from_env(**overrides)
    configure_logging(settings.data_dir / "mas.log", args.verbose)
    driver = None
    if args.demo:
        if not args.keep:
            reset_demo_data(settings.data_dir)
        system = build_demo_system(demo_settings(settings, settings.data_dir), delay=args.delay)
    else:
        scenario = None
        try:
            if args.scenario is not None:
                scenario = load_scenario(args.scenario)
                team, run_name = scenario.team, scenario.name
            elif args.team is not None:
                team, run_name = load_team(args.team), "session"
            else:
                raise SystemExit("Tell me who is in the team: --scenario <folder> or --team <01_role_initialization.md "
                                 "or its folder>. Or try `python -m mas --demo`.")
        except ValueError as exc:
            raise SystemExit(f"cannot load the team: {exc}")
        system = build_system(settings, make_llm(settings), make_human(settings), roles=team, run_name=run_name)
        if scenario is not None:
            announce = getattr(system.human, "_write", print)
            driver = driver_for(scenario, announce=announce)
    try:
        if driver is not None:
            asyncio.run(system.run(driver, until_driver_done=args.auto))
        else:
            asyncio.run(system.run())
    except KeyboardInterrupt:
        pass
    if system.transcript is not None and system.transcript.path is not None:
        print(f"Transcript: {system.transcript.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
