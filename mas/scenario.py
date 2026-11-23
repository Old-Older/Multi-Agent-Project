"""Running a scenario: a team and the tasks that are posted to it, one after the other.

Owner: JIAN Yimin.

A scenario is a folder in the course's format:

    01_role_initialization.md   the team (see mas/team.py)
    02_task_1.md                the first task: a fenced block holding what the human says
    03_task_2.md                the second task, posted to the same group when the first has ended

Any number of tasks works; they are the other `*.md` files that hold a fenced block, in file name
order. The human answers the team's questions as they come: a person at the command line, or
the AutoResponder when the run is unattended.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mas.agents.roles import RoleConfig
from mas.core.message import GROUP_MAIN, HUMAN, Message, MsgType
from mas.team import ROLE_FILE, load_team

log = logging.getLogger(__name__)

_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.M)


@dataclass
class ScenarioTask:
    file: str
    title: str
    prompt: str                       # exactly what the human says to the team


@dataclass
class Scenario:
    name: str
    team: dict[str, RoleConfig]
    tasks: list[ScenarioTask]


def load_scenario(folder: str | Path) -> Scenario:
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"scenario folder not found: {folder}")
    team = load_team(folder)
    tasks = []
    for path in sorted(folder.glob("*.md")):
        if path.name == ROLE_FILE or path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8")
        task = parse_task_markdown(text, path.name)
        if task:
            tasks.append(task)
    if not tasks:
        raise ValueError(f"no task found in {folder}: expected files such as 02_task_1.md with the task in a fenced block")
    return Scenario(folder.name.strip() or "scenario", team, tasks)


def parse_task_markdown(text: str, filename: str) -> ScenarioTask | None:
    """Read the course task format from a file or a pasted Markdown document."""
    prompt = _first_fenced(text)
    if not prompt:
        return None
    title = _TITLE.search(text)
    return ScenarioTask(filename, title.group(1) if title else Path(filename).stem, prompt)


def _first_fenced(text: str) -> str:
    lines, body, inside = text.splitlines(), [], False
    for line in lines:
        if line.strip().startswith("```"):
            if inside:
                break
            inside = True
        elif inside:
            body.append(line)
    return "\n".join(body).strip()


class _Ends:
    """Tells when a request has ended: its final reply was posted, or it was cancelled."""

    def __init__(self, bus) -> None:
        self.event = asyncio.Event()
        bus.add_observer(self._on_message)

    def _on_message(self, msg: Message) -> None:
        if msg.type == MsgType.CHAT and (msg.payload.get("final") or msg.payload.get("cancelled_roots")):
            self.event.set()


def driver_for(scenario: Scenario, *, announce: Callable[[str], None] = print, pause_s: float = 0.0):
    """A driver for System.run(): posts the scenario's tasks as the human, each one when the
    previous request has ended, in the same group, so the team keeps its context."""
    async def drive(system) -> None:
        ends = _Ends(system.bus)
        for n, task in enumerate(scenario.tasks, 1):
            if n > 1 and pause_s:
                await asyncio.sleep(pause_s)
            ends.event.clear()
            announce(f"\n=== Task {n}/{len(scenario.tasks)}: {task.title} ===\n{task.prompt}\n")
            await system.bus.publish(Message(MsgType.CHAT, HUMAN, GROUP_MAIN, task.prompt))
            await ends.event.wait()
    return drive
