"""Evaluation harness (design §10, D16).

Runs scenarios (a team and the tasks posted to it one after the other, see mas/scenario.py) and
reports what the course asks for, measured by code:

  task completion rate   of the requests (overarching goals) and of the sub-tasks, without crashes
  execution time         from the task being posted to the final reply, per request
  failure modes          how the requests that did not complete ended
  memory evolution       the same scenario run again with the agents' memory kept (keep_memory)

Every scenario starts from a fresh system (its own bus, workspaces and, unless asked otherwise,
memory), and a run's records can be graded by a model on top (mas/eval/judge.py), the way the
course grades. Nothing here takes a value from an LLM's description of itself.
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from mas.app import build_system
from mas.config import Settings
from mas.core.human import AutoResponder, HumanIO
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.core.task import TaskStatus
from mas.eval.judge import judge_task, read_deliverables
from mas.llm.base import LLMClient
from mas.scenario import Scenario

log = logging.getLogger(__name__)


@dataclass
class EvalRecord:
    """One task of one scenario, as it ended."""
    scenario: str
    run: int                          # 1 for the first run of the scenario, 2 for the repeat, ...
    task_index: int                   # 1-based position in the scenario
    task_file: str
    title: str
    completed: bool                   # the lead reported success and nothing crashed or timed out
    failure_mode: str | None = None   # llm_format, tool_error, timeout, max_steps, wrong_output, crash, or no_result
    subtask_total: int = 0            # tasks the lead delegated, declined ones left out
    subtask_done: int = 0
    duration: float = 0.0             # seconds, from posting the task to the final reply
    lead: str = ""
    hitl_count: int = 0               # questions the team asked the human during this task
    lead_steps: int = 0
    deliverables: list[str] = field(default_factory=list)
    output_dir: str = ""
    summary: str = ""                 # the lead's final answer, clipped
    judged: bool | None = None        # a model's verdict on whether the request was met (None: not graded)
    score: int | None = None
    judge_notes: str = ""
    # Where the time went, measured by the workers: "lead" is the lead's own time (llm_s, tool_s, delegation_s =
    # waiting for teammates, human_s = waiting for the human, other_s); "team" adds up every member
    # (llm_s, llm_calls, tool_s, by_tool {name: {calls, s}}). Members work at the same time, so the team's
    # seconds add up to more than the wall clock.
    timing: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _timing(system, root_id: str, duration: float) -> dict:
    """The time composition of one request, from the metrics each worker put in its result."""
    tasks = system.state.by_root(root_id)
    team: dict = {"llm_s": 0.0, "llm_calls": 0, "tool_s": 0.0, "by_tool": {}}
    lead: dict = {}
    lead_steps: dict = {}
    lead_tools: dict = {}
    for task in tasks:
        result = system.state.result(task.id)
        m = getattr(result, "metrics", None) or {}
        if not m:
            continue
        team["llm_s"] += m.get("llm_s", 0.0)
        team["llm_calls"] += m.get("llm_calls", 0)
        team["tool_s"] += m.get("tool_s", 0.0)
        for name, v in (m.get("by_tool") or {}).items():
            entry = team["by_tool"].setdefault(name, {"calls": 0, "s": 0.0})
            entry["calls"] += v.get("calls", 0)
            entry["s"] += v.get("s", 0.0)
        if task.parent_id is None:
            lead = {k: m.get(k, 0.0) for k in ("llm_s", "tool_s", "delegation_s", "human_s")}
            lead_steps = dict(m.get("steps_by_kind") or {})
            lead_tools = {name: v.get("calls", 0) for name, v in (m.get("by_tool") or {}).items()}
    if lead:
        lead["other_s"] = max(0.0, duration - sum(lead.values()))
    team["llm_s"], team["tool_s"] = round(team["llm_s"], 2), round(team["tool_s"], 2)
    for v in team["by_tool"].values():
        v["s"] = round(v["s"], 2)
    return {"lead": {k: round(v, 2) for k, v in lead.items()}, "team": team,
            "lead_steps": lead_steps, "lead_tools": lead_tools}


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


async def run_scenario(scenario: Scenario, settings: Settings, llm: LLMClient, *,
                       out_dir: Path, run: int = 1, human: HumanIO | None = None,
                       judge_llm: LLMClient | None = None, timeout: float | None = None,
                       keep_memory: bool = False, **build_options) -> list[EvalRecord]:
    """Run every task of `scenario` in one fresh system and return one record per task.

    out_dir     where this scenario's files go (workspaces, data, transcript, outputs)
    human       who answers the team's questions (default: AutoResponder with its fixed answers);
                a SimulatedHuman is told each request before it is posted
    judge_llm   if given, a model grades each task's dialogue and deliverables
    timeout     seconds for the whole scenario; tasks not finished by then are failures
    keep_memory the agents' memory lives in out_dir/data and is shared by the runs of this scenario
                (otherwise every run starts with empty memory)
    build_options  passed to build_system (worker_factory, sandbox_factory), for tests
    """
    base = Path(out_dir) / scenario.name.strip().replace("/", "_")
    data_dir = base / "data" if keep_memory else base / f"run{run}" / "data"
    run_settings = replace(settings, data_dir=data_dir, workspaces_dir=base / f"run{run}" / "workspaces",
                           auto_hitl=True)
    human = human or AutoResponder()
    system = build_system(run_settings, llm, human, roles=scenario.team,
                          run_name=f"{scenario.name}-run{run}", **build_options)
    posted: list[tuple[float, float]] = []                   # (wall clock, monotonic) when each task was posted

    async def drive(sys) -> None:
        ends = asyncio.Event()

        def on_message(msg: Message) -> None:
            if msg.type == MsgType.CHAT and (msg.payload.get("final") or msg.payload.get("cancelled_roots")):
                ends.set()
        sys.bus.add_observer(on_message)
        for task in scenario.tasks:
            ends.clear()
            if hasattr(human, "set_request"):
                human.set_request(task.prompt)
            posted.append((time.time(), time.monotonic()))
            await sys.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, task.prompt))
            await ends.wait()

    crash, crash_mode = "", ""
    try:
        await asyncio.wait_for(system.run(drive, until_driver_done=True), timeout)
    except asyncio.TimeoutError:
        crash, crash_mode = f"the scenario did not finish within {timeout:g}s", "timeout"
    except Exception as exc:                                  # the harness must report, not die
        log.exception("Scenario %s crashed", scenario.name)
        crash, crash_mode = f"{type(exc).__name__}: {exc}", "crash"

    outcomes = list(system.requests.outcomes.values())
    records: list[EvalRecord] = []
    for i, task in enumerate(scenario.tasks):
        rec = EvalRecord(scenario=scenario.name, run=run, task_index=i + 1, task_file=task.file,
                         title=task.title, completed=False)
        if i < len(outcomes):
            o = outcomes[i]
            delegated = [t for t in system.state.by_root(o.root_id)
                         if t.parent_id is not None and t.status != TaskStatus.DECLINED]
            hitl = [m for m in system.bus.history(GROUP_MAIN, 1_000_000)
                    if m.type == MsgType.HITL_REQUEST and m.payload.get("root_id") == o.root_id]
            rec.completed = bool(o.success)
            rec.failure_mode = o.failure_mode.value if o.failure_mode else None
            if crash and not rec.completed and rec.failure_mode is None:
                rec.failure_mode = crash_mode                  # it was cut short when the scenario was stopped
                rec.notes.append(crash)
            rec.subtask_total = len(delegated)
            rec.subtask_done = sum(1 for t in delegated if t.status == TaskStatus.DONE)
            rec.duration = round(o.duration, 3)
            rec.lead, rec.lead_steps = o.lead, o.rounds
            rec.hitl_count = len(hitl)
            rec.timing = _timing(system, o.root_id, o.duration)
            rec.deliverables, rec.output_dir = list(o.deliverables), o.output_dir
            rec.summary = _clip(o.summary, 600)
            if judge_llm is not None:
                since = posted[i][0] if i < len(posted) else 0.0
                until = posted[i + 1][0] if i + 1 < len(posted) else None
                dialogue = system.transcript.dialogue(since, until) if system.transcript else ""
                verdict = await judge_task(judge_llm, task.prompt, dialogue, read_deliverables(o.output_dir))
                rec.judged, rec.score, rec.judge_notes = verdict.passed, verdict.score, verdict.notes
        else:
            rec.failure_mode = "no_result"
            rec.notes.append(crash or "the request never ended")
        records.append(rec)
    return records


async def run_suite(scenarios: list[Scenario], settings: Settings, llm: LLMClient, *, out_dir: Path,
                    repeat: int = 1, keep_memory: bool = False, human_factory=None,
                    judge_llm: LLMClient | None = None, timeout: float | None = None,
                    **build_options) -> list[EvalRecord]:
    """Every scenario, `repeat` times each, one after the other. With `keep_memory` the repeats of a
    scenario share the agents' memory, so run 2 shows what run 1 taught them."""
    records: list[EvalRecord] = []
    for scenario in scenarios:
        for run in range(1, repeat + 1):
            human = human_factory() if human_factory else None
            records += await run_scenario(scenario, settings, llm, out_dir=out_dir, run=run, human=human,
                                          judge_llm=judge_llm, timeout=timeout, keep_memory=keep_memory,
                                          **build_options)
    return records


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "max": 0.0}
    return {"mean": round(statistics.fmean(values), 2), "median": round(statistics.median(values), 2),
            "max": round(max(values), 2)}


def _rate(done: int, total: int) -> float:
    return round(done / total, 4) if total else 0.0


def summarize(records: list[EvalRecord]) -> dict[str, object]:
    """Completion rate (requests and sub-tasks, overall and per scenario and per run), execution time
    (mean, median, maximum), failure-mode counts, and the graders' verdicts when there are any."""
    def block(rows: list[EvalRecord]) -> dict[str, object]:
        graded = [r for r in rows if r.judged is not None]
        scores = [r.score for r in rows if r.score is not None]
        return {
            "requests": len(rows),
            "completed": sum(r.completed for r in rows),
            "completion_rate": _rate(sum(r.completed for r in rows), len(rows)),
            "subtasks": sum(r.subtask_total for r in rows),
            "subtasks_done": sum(r.subtask_done for r in rows),
            "subtask_completion_rate": _rate(sum(r.subtask_done for r in rows), sum(r.subtask_total for r in rows)),
            "duration_s": _stats([r.duration for r in rows if r.failure_mode != "no_result"]),
            "hitl_questions": sum(r.hitl_count for r in rows),
            "judged": len(graded),
            "judged_passed": sum(1 for r in graded if r.judged),
            "judged_pass_rate": _rate(sum(1 for r in graded if r.judged), len(graded)),
            "mean_score": round(statistics.fmean(scores), 2) if scores else None,
        }
    failures: dict[str, int] = {}
    for r in records:
        if not r.completed:
            failures[r.failure_mode or "unknown"] = failures.get(r.failure_mode or "unknown", 0) + 1
    by_scenario = {s: block([r for r in records if r.scenario == s]) for s in dict.fromkeys(r.scenario for r in records)}
    by_run = {n: block([r for r in records if r.run == n]) for n in sorted({r.run for r in records})}
    return {"overall": block(records), "failure_modes": failures, "by_scenario": by_scenario, "by_run": by_run}


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def render_report(records: list[EvalRecord], *, title: str = "Evaluation report", info: dict | None = None) -> str:
    """The results as Markdown: the summary, then one line per task."""
    s = summarize(records)
    o = s["overall"]
    out = [f"# {title}", ""]
    for key, value in (info or {}).items():
        out.append(f"- {key}: {value}")
    out += ["", "## Summary", "",
            f"- Requests: **{o['completed']}/{o['requests']} completed ({_pct(o['completion_rate'])})**",
            f"- Sub-tasks: {o['subtasks_done']}/{o['subtasks']} done ({_pct(o['subtask_completion_rate'])})",
            f"- Execution time per request: mean {o['duration_s']['mean']} s, median {o['duration_s']['median']} s, "
            f"max {o['duration_s']['max']} s",
            f"- Questions the team asked the human: {o['hitl_questions']}"]
    if o["judged"]:
        out.append(f"- Graded by a model: {o['judged_passed']}/{o['judged']} requests met "
                   f"({_pct(o['judged_pass_rate'])}), mean score {o['mean_score']}/10")
    if s["failure_modes"]:
        out.append("- Failure modes: " + ", ".join(f"{k} {v}" for k, v in sorted(s["failure_modes"].items())))
    if len(s["by_run"]) > 1:
        out += ["", "## By run (memory kept between runs)", "", "| run | completed | sub-tasks | mean time (s) | graded passed | mean score |",
                "|---|---|---|---|---|---|"]
        for n, b in s["by_run"].items():
            out.append(f"| {n} | {b['completed']}/{b['requests']} | {b['subtasks_done']}/{b['subtasks']} | "
                       f"{b['duration_s']['mean']} | {b['judged_passed']}/{b['judged']} | {b['mean_score'] or '-'} |")
    out += ["", "## By scenario", "", "| scenario | completed | sub-tasks | mean time (s) | graded passed | mean score |",
            "|---|---|---|---|---|---|"]
    for name, b in s["by_scenario"].items():
        out.append(f"| {name} | {b['completed']}/{b['requests']} | {b['subtasks_done']}/{b['subtasks']} | "
                   f"{b['duration_s']['mean']} | {b['judged_passed']}/{b['judged']} | {b['mean_score'] or '-'} |")
    out += ["", "## Every task", "",
            "| scenario | run | task | lead | result | failure | seconds | sub-tasks | questions | files | graded |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        graded = "-" if r.judged is None else f"{'met' if r.judged else 'not met'} ({r.score}/10)"
        out.append(f"| {r.scenario} | {r.run} | {r.task_index}. {r.title} | {r.lead or '-'} | "
                   f"{'completed' if r.completed else 'FAILED'} | {r.failure_mode or '-'} | {r.duration} | "
                   f"{r.subtask_done}/{r.subtask_total} | {r.hitl_count} | {len(r.deliverables)} | {graded} |")
    timed = [r for r in records if r.timing.get("lead") or r.timing.get("team", {}).get("llm_calls")]
    if timed:
        out += ["", "## Where the time went", "",
                "The lead's own seconds are on the critical path (they add up to the request's time). The team columns add up "
                "every member, and members work at the same time, so they can exceed it.", "",
                "| scenario | run | task | seconds | lead: model | lead: tools | lead: waiting for teammates | "
                "lead: waiting for the human | team: model calls | team: model s | team: tool s | web_search calls | web_search s |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in timed:
            lead, team = r.timing.get("lead", {}), r.timing.get("team", {})
            search = team.get("by_tool", {}).get("web_search", {})
            out.append(f"| {r.scenario} | {r.run} | {r.task_index} | {r.duration:.0f} | {lead.get('llm_s', 0):.0f} | "
                       f"{lead.get('tool_s', 0):.0f} | {lead.get('delegation_s', 0):.0f} | {lead.get('human_s', 0):.0f} | "
                       f"{team.get('llm_calls', 0)} | {team.get('llm_s', 0):.0f} | {team.get('tool_s', 0):.0f} | "
                       f"{search.get('calls', 0)} | {search.get('s', 0):.0f} |")
    stepped = [r for r in records if r.timing.get("lead_steps")]
    if stepped:
        out += ["", "## Where the lead's steps went", "",
                "Each step is one model call of the lead. `tools` are its own tool calls (the second column lists them), "
                "`delegate` the steps that handed work to teammates, `push_*` the steps it was sent back (to have a "
                "deliverable reviewed, to check the requirements, to use more of the time, to check the loose ends), "
                "`final` the answer that was accepted.", "",
                "| scenario | run | task | steps | delegate | tools | push_review | push_requirements | push_early | "
                "push_closing | format_error | final | the lead's own tool calls |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in stepped:
            k = r.timing["lead_steps"]
            tools = ", ".join(f"{n} {c}" for n, c in sorted(r.timing.get("lead_tools", {}).items(), key=lambda x: -x[1]))
            out.append(f"| {r.scenario} | {r.run} | {r.task_index} | {r.lead_steps} | {k.get('delegate', 0)} | {k.get('tools', 0)} | "
                       f"{k.get('push_review', 0)} | {k.get('push_requirements', 0)} | {k.get('push_early', 0)} | "
                       f"{k.get('push_closing', 0)} | {k.get('format_error', 0)} | {k.get('final', 0)} | {tools or '-'} |")
    notes = [r for r in records if r.judge_notes or r.notes]
    if notes:
        out += ["", "## Notes", ""]
        for r in notes:
            text = " ".join(filter(None, [r.judge_notes, *r.notes]))
            out.append(f"- {r.scenario} run {r.run}, task {r.task_index}: {text}")
    return "\n".join(out) + "\n"


def save_results(records: list[EvalRecord], out_dir: Path, *, title: str = "Evaluation report",
                 info: dict | None = None) -> tuple[Path, Path]:
    """Write results.json (every record and the summary) and report.md into out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = out_dir / "results.json"
    data.write_text(json.dumps({"info": info or {}, "summary": summarize(records),
                                "records": [asdict(r) for r in records]}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    report = out_dir / "report.md"
    report.write_text(render_report(records, title=title, info=info), encoding="utf-8")
    return data, report
