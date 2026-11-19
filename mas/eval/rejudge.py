"""Grade archived runs again.

`python -m mas.eval.rejudge docs/runs/<run> [...]` reads what an archived run kept (its results.json, the transcript
and the delivered files of every request) and has the grader mark each task again, next to the mark it got when the run
was made. It exists because the grader used to be shown only the first 8000 characters of every delivered file, so the
marks of runs with long deliverables were given on an incomplete file.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from mas.eval.judge import Verdict, judge_task, read_deliverables

_HEADER = re.compile(r"^### .*$", re.M)
_HUMAN_TO_TEAM = re.compile(r"^### .* · human → the team\b", re.M)
_END = re.compile(r"^## How the requests ended", re.M)


def split_requests(transcript: str) -> list[tuple[str, str]]:
    """[(the human's request, the dialogue of that request)] from a transcript written by Transcript.render. A request
    starts at a human → the team entry and goes on until the next one (or the closing table)."""
    starts = [m.start() for m in _HUMAN_TO_TEAM.finditer(transcript)]
    end = _END.search(transcript)
    stop = end.start() if end else len(transcript)
    out = []
    for i, begin in enumerate(starts):
        finish = starts[i + 1] if i + 1 < len(starts) else stop
        section = transcript[begin:finish].strip()
        lines = section.split("\n")
        prompt = []
        for line in lines[1:]:
            if line.startswith("### "):
                break
            if line.startswith(">"):
                prompt.append(line[1:].removeprefix(" "))
            elif prompt and not line.strip():
                continue
            elif prompt:
                break
        out.append(("\n".join(prompt).strip(), section))
    return out


def locate(run_dir: Path, scenario: str, task_index: int) -> tuple[Path | None, Path | None]:
    """(transcript, delivered files folder) of one request in either archive layout: <run>/scenarioN/ or the run folder
    itself (the first archived runs)."""
    for base in (run_dir / f"scenario{scenario}", run_dir):
        transcript = base / "transcript.md"
        if transcript.is_file():
            folders = sorted(p for p in base.glob(f"R{task_index}-*") if p.is_dir())
            return transcript, (folders[0] if folders else None)
    return None, None


async def rejudge_run(run_dir: Path, llm) -> list[dict]:
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    rows = []
    for rec in results["records"]:
        scenario = re.search(r"scenario_(\d)", rec["scenario"])
        number = scenario.group(1) if scenario else ""
        transcript_path, files = locate(run_dir, number, rec["task_index"])
        row = {"scenario": rec["scenario"], "task_index": rec["task_index"], "title": rec.get("title", ""),
               "old_passed": rec.get("judged"), "old_score": rec.get("score"), "old_notes": rec.get("judge_notes", ""),
               "new_passed": None, "new_score": None, "new_notes": ""}
        if transcript_path is None:
            row["new_notes"] = "no transcript archived for this request"
        else:
            requests = split_requests(transcript_path.read_text(encoding="utf-8"))
            if rec["task_index"] > len(requests):
                row["new_notes"] = "the request is not in the archived transcript"
            else:
                prompt, dialogue = requests[rec["task_index"] - 1]
                verdict: Verdict = await judge_task(llm, prompt, dialogue, read_deliverables(files) if files else {})
                row.update(new_passed=verdict.passed, new_score=verdict.score, new_notes=verdict.notes)
        rows.append(row)
    return rows


def render(run_name: str, rows: list[dict]) -> str:
    def mark(passed, score):
        return "-" if score is None else f"{'met' if passed else 'not met'} ({score}/10)"
    out = [f"# Graded again: {run_name}", "",
           "The grader now sees every delivered file whole (before, only its first 8000 characters).", "",
           "| scenario | task | graded then | graded now |", "|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['scenario']} | {r['task_index']} | {mark(r['old_passed'], r['old_score'])} | "
                   f"{mark(r['new_passed'], r['new_score'])} |")
    out += ["", "## Notes of the new grading", ""]
    out += [f"- {r['scenario']} task {r['task_index']}: {r['new_notes']}" for r in rows]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mas.eval.rejudge", description=__doc__.split("\n")[0])
    parser.add_argument("runs", nargs="+", type=Path, help="archived run folders (they hold a results.json)")
    parser.add_argument("--llm", choices=("hkgai", "deepseek"), default=None, help="which model grades")
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    from mas.app import make_llm
    from mas.config import Settings
    settings = Settings.from_env(**({"llm_provider": args.llm} if args.llm else {}))
    llm = make_llm(settings)
    for run in args.runs:
        if not (run / "results.json").is_file():
            print(f"{run}: no results.json, skipped", file=sys.stderr)
            continue
        rows = asyncio.run(rejudge_run(run, llm))
        (run / "rejudged.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        (run / "rejudged.md").write_text(render(run.name, rows), encoding="utf-8")
        print(f"{run.name}: " + ", ".join(f"S{r['scenario'][9]}T{r['task_index']} {r['old_score']}->{r['new_score']}" for r in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
