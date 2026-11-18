"""Run an evaluation: python -m mas.eval <scenario folder> [<scenario folder> ...]

Posts each scenario's tasks to its team in a fresh system, measures completion and time, and writes
results.json and report.md (and every run's transcript and deliverables) under --out.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from mas.app import make_llm
from mas.config import Settings
from mas.eval.harness import render_report, run_suite, save_results, summarize
from mas.eval.simulated_human import SimulatedHuman
from mas.scenario import load_scenario


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m mas.eval", description="Evaluate the system on scenarios.")
    p.add_argument("scenarios", nargs="+", type=Path, help="scenario folders (role file and task files)")
    p.add_argument("--llm", choices=("hkgai", "deepseek"), default=None, help="which LLM the team uses")
    p.add_argument("--human", choices=("auto", "llm"), default="llm",
                   help="who answers the team's questions: 'llm' plays the requester, 'auto' gives fixed answers")
    p.add_argument("--judge", action="store_true", help="have a model grade each task's dialogue and deliverables")
    p.add_argument("--repeat", type=int, default=1, help="run every scenario this many times")
    p.add_argument("--keep-memory", action="store_true",
                   help="the repeats of a scenario share the agents' memory (to see whether it helps)")
    p.add_argument("--timeout", type=float, default=3600.0, help="seconds allowed for one scenario run")
    p.add_argument("--out", type=Path, default=None, help="where results go (default eval_results/<time>)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    overrides: dict[str, object] = {"llm_provider": args.llm} if args.llm else {}
    settings = Settings.from_env(**overrides)
    logging.basicConfig(level=logging.WARNING)
    try:
        scenarios = [load_scenario(path) for path in args.scenarios]
    except ValueError as exc:
        raise SystemExit(f"cannot load a scenario: {exc}")
    llm = make_llm(settings)
    out = args.out or Path("eval_results") / time.strftime("%Y%m%d-%H%M%S")
    print(f"Evaluating {len(scenarios)} scenario(s) x {args.repeat} run(s) with {settings.llm_provider}; results in {out}")

    async def go():
        human_factory = (lambda: SimulatedHuman(llm)) if args.human == "llm" else None
        return await run_suite(scenarios, settings, llm, out_dir=out, repeat=args.repeat,
                               keep_memory=args.keep_memory, human_factory=human_factory,
                               judge_llm=llm if args.judge else None, timeout=args.timeout)

    started = time.monotonic()
    records = asyncio.run(go())
    info = {"model provider": settings.llm_provider, "answers to questions": args.human,
            "graded by a model": args.judge, "runs per scenario": args.repeat, "memory kept between runs": args.keep_memory,
            "wall time (s)": round(time.monotonic() - started)}
    save_results(records, out, info=info)
    print(render_report(records, info=info))
    print(f"Written: {out / 'report.md'} and {out / 'results.json'}")
    return 0 if summarize(records)["overall"]["completed"] == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
