"""A demo that runs without an API key and without the parts other people are still writing.

`python -m mas --demo` assembles the real bus, router, state table, memory, Orchestrator
and command line, and replaces three things with small stand-ins:

  DemoBrain    a rule-based "LLM" for the Orchestrator (a function MockLLM can call)
  DemoWorker   a worker that pretends to work, writes one file and records a memory
  DemoSandbox  a workspace that can only read and write files

It shows the whole flow: delegation, parallel agents, an agent declining and the job being
reassigned, asking the human for approval, /status, /cancel, deliverables, and memory
(a lesson from one run shows up in the next).
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from mas.agents.base import Agent
from mas.agents.roles import RoleConfig
from mas.app import System, WorkerParts, build_system
from mas.config import Settings
from mas.core.human import CANCELLED_ANSWER, CliHumanIO, HitlKind
from mas.core.task import Task, TaskResult, TaskStatus
from mas.llm.base import ChatMessage, FunctionSpec, LLMResponse, ToolCall
from mas.llm.mock import MockLLM
from mas.memory.base import Experience, tags_for_tools
from mas.sandbox.base import INBOX, ExecResult, Sandbox

_RESEARCH = re.compile(r"research|search|find|look up|investigate|调研|搜索|查找", re.I)
_CODE = re.compile(r"script|code|python|program|函数|脚本|代码|程序", re.I)
_DOC = re.compile(r"\bdocs?\b|document|write.?up|summar|report|readme|文档|总结|报告", re.I)
_RUNS_CODE = re.compile(r"\b(run|execute)\b|运行|执行", re.I)
_RISKY = re.compile(r"push|delete|publish|deploy|推送|删除|发布", re.I)

_DEMO_FILE = {"researcher": ("notes", "md"), "coder": ("script", "py"), "writer": ("document", "md")}
_DEMO_TOOLS = {"researcher": ["web_search", "write_file"], "coder": ["run_python", "write_file"],
               "writer": ["write_file"]}


# ---- the Orchestrator's "LLM" ----------------------------------------------------------

def _request_of(messages: list[ChatMessage]) -> str:
    first_user = next(m["content"] for m in messages if m["role"] == "user")
    return first_user.removeprefix("Human request:").split("\n\n")[0].strip()


def _pick_agents(request: str) -> list[str]:
    picked = [name for name, pattern in (("researcher", _RESEARCH), ("coder", _CODE), ("writer", _DOC))
              if pattern.search(request)]
    return picked or ["writer"]                      # nothing recognised: the writer, who may decline


def demo_brain(messages: list[ChatMessage], tools: list[FunctionSpec] | None = None) -> LLMResponse:
    """Decide like an Orchestrator would, from the messages only: round 1 sends the request to
    the agents it mentions (in parallel); a declined job goes to the agent that was suggested;
    when nothing is left it calls finish with the files that were produced."""
    request = _request_of(messages)
    tool_messages = [m for m in messages if m["role"] == "tool"]
    if not tool_messages:
        agents = _pick_agents(request)
        calls = [ToolCall(f"c{i}", f"call_{a}", {"goal": f"{request}" if len(agents) == 1 else f"{a}'s part of: {request}"})
                 for i, a in enumerate(agents)]
        return LLMResponse(f"Remaining steps: {', '.join(agents)}, then finish", calls)
    asked = {tc["id"]: json.loads(tc["function"]["arguments"])
             for m in messages if m["role"] == "assistant" for tc in m.get("tool_calls") or []}
    last_assistant = max(i for i, m in enumerate(messages) if m["role"] == "assistant")
    latest = [(m["tool_call_id"], json.loads(m["content"])) for m in messages[last_assistant + 1:]
              if m["role"] == "tool"]
    redo = [ToolCall(f"r{n}", f"call_{obs['suggest']}", {"goal": asked[cid]["goal"]})
            for n, (cid, obs) in enumerate(latest) if obs.get("declined") and obs.get("suggest")]
    if redo:
        return LLMResponse("Remaining steps: reassign, then finish", redo)
    observations = [json.loads(m["content"]) for m in tool_messages]
    files = list(dict.fromkeys(a for o in observations for a in o.get("artifacts", [])))
    said = [o["summary"] for o in observations if o.get("success") and o.get("summary")]
    failed = [o.get("error") or o.get("reason") or "unknown" for o in observations
              if not o.get("success") and not o.get("declined")]
    summary = " ".join(said) or "Nothing was produced."
    if failed:
        summary += f" (did not work out: {'; '.join(failed)})"
    return LLMResponse("", [ToolCall("done", "finish", {"summary": summary, "deliverables": files})])


# ---- the workspace -------------------------------------------------------------------------

class DemoSandbox(Sandbox):
    """Files only: no commands, and nothing can leave the workspace."""

    def resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root.resolve() and self.root.resolve() not in path.parents:
            raise PermissionError(f"{rel!r} is outside the workspace")
        return path

    def read_text(self, rel: str) -> str:
        return self.resolve(rel).read_text(encoding="utf-8")

    def write_text(self, rel: str, content: str) -> None:
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete(self, rel: str) -> None:
        self.resolve(rel).unlink()

    def list_dir(self, rel: str = ".") -> list[str]:
        return sorted(p.name for p in self.resolve(rel).iterdir())

    def exists(self, rel: str) -> bool:
        return self.resolve(rel).exists()

    async def exec(self, cmd: list[str], timeout: float = 60.0, env: dict[str, str] | None = None) -> ExecResult:
        return ExecResult(1, "", "the demo sandbox cannot run commands")

    def import_file(self, src: Path, name: str | None = None) -> str:
        rel = f"{INBOX}/{name or src.name}"
        self.write_text(rel, src.read_text(encoding="utf-8"))
        return rel


# ---- the worker ----------------------------------------------------------------------------

class DemoWorker(Agent):
    """Pretends to work in three steps, then writes one file into its workspace. It shows the
    things a real worker has to do: decline what it cannot do, ask before risky steps, stop
    when cancelled, and remember (recall at the start, a record at the end)."""

    def __init__(self, role: RoleConfig, parts: WorkerParts, delay: float = 0.4) -> None:
        super().__init__(role.agent_id, parts.bus, parts.router, parts.settings)
        self.role, self.sandbox, self.memory, self.delay = role, parts.sandbox, parts.memory, delay

    async def handle_task(self, task: Task) -> TaskResult:
        name = self.role.agent_id
        remembered = [e.lesson for e in self.memory.recall(task.goal, self.settings.memory_recall_k) if e.lesson]
        if name == "writer" and _RUNS_CODE.search(task.goal):
            return TaskResult(task.id, False, "I only write documents", declined=True, suggest="coder",
                              error="I cannot run code")
        for step in ("planning", "working", "finishing"):
            if self.is_cancelled(task):
                return TaskResult(task.id, False, "", error="cancelled")
            await self.report_status(task, TaskStatus.RUNNING, step)
            await asyncio.sleep(self.delay)
        if _RISKY.search(task.goal):
            answer = await self.ask_human(task, f"{name} is about to: {task.goal[:70]}. Go ahead?",
                                          HitlKind.APPROVAL, ["yes", "no"])
            if answer == CANCELLED_ANSWER or self.is_cancelled(task):
                return TaskResult(task.id, False, "", error="cancelled")
            if answer.strip().lower() not in ("yes", "y"):
                self._remember(task, False, "not approved", ["git"],
                               "the human did not approve a risky step; explain what it does before asking")
                return TaskResult(task.id, False, "", error="the human did not approve")
        stem, ext = _DEMO_FILE[name]
        file = f"{stem}-{task.id}.{ext}"
        self.sandbox.write_text(file, f"# {name}\n\nGoal: {task.goal}\n"
                                + (f"\nLessons from earlier: {'; '.join(remembered)}\n" if remembered else ""))
        summary = f"{name} finished '{_clip(task.goal)}'" + (f" (remembering: {remembered[0]})" if remembered else "")
        self._remember(task, True, summary, _DEMO_TOOLS[name], "", [file])
        return TaskResult(task.id, True, summary, artifacts=[file])

    def _remember(self, task: Task, success: bool, summary: str, tools: list[str], lesson: str,
                  files: list[str] | None = None) -> None:
        self.memory.add(Experience(task.id, task.goal, tags_for_tools(tools, files or []), success, summary, lesson))


def _clip(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


# ---- putting it together ------------------------------------------------------------------

def demo_settings(base: Settings, data_dir: Path) -> Settings:
    """Settings that keep everything the demo writes under data_dir/demo."""
    root = Path(data_dir) / "demo"
    return Settings.from_env(data_dir=root, workspaces_dir=root / "workspaces", subtask_timeout_s=60.0,
                             max_orchestrator_rounds=base.max_orchestrator_rounds)


def build_demo_system(settings: Settings, *, delay: float = 0.4, read_line=None, write=None) -> System:
    """The demo system. `read_line` and `write` replace the terminal (the tests use them)."""
    return build_system(
        settings, MockLLM(responder=demo_brain), CliHumanIO(read_line=read_line, write=write),
        worker_factory=lambda role, parts: DemoWorker(role, parts, delay),
        sandbox_factory=lambda agent_id, root: DemoSandbox(agent_id, root))


def reset_demo_data(data_dir: Path) -> None:
    """Start the demo from nothing (delete data_dir/demo)."""
    shutil.rmtree(Path(data_dir) / "demo", ignore_errors=True)
