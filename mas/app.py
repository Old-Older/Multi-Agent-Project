"""Assembling the system: bus, router, state table, memories, agents and the human side.

build_system() is the one place that knows how the parts fit together. Everything that
belongs to someone else's work is a plug-in point with a default:

  llm              any LLMClient (make_llm() builds the DeepSeek one from the settings)
  worker_factory   how a Worker is built (default: WorkerAgent with build_tools())
  sandbox_factory  how a workspace is built (default: LocalSandbox or DockerSandbox)
  human            CliHumanIO for a person, AutoResponder for evaluation

so a test, the demo (mas/demo.py) and the real system all go through the same wiring.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mas.agents.base import Agent
from mas.agents.orchestrator import Orchestrator
from mas.agents.roles import ROLES, RoleConfig
from mas.agents.worker import WorkerAgent
from mas.config import Settings
from mas.core.bus import InMemoryBus, MessageBus
from mas.core.human import AutoResponder, CliHumanIO, HumanIO
from mas.core.message import GROUP_MAIN, HUMAN, ORCHESTRATOR
from mas.core.router import Router
from mas.core.state import StateTable
from mas.llm.base import LLMClient
from mas.llm.deepseek import DeepSeekClient
from mas.memory.base import JsonlMemory, Memory
from mas.sandbox.base import DockerSandbox, LocalSandbox, Sandbox
from mas.tools.base import Tool

log = logging.getLogger(__name__)


@dataclass
class WorkerParts:
    """What a worker needs from the system when it is built."""
    bus: MessageBus
    router: Router
    settings: Settings
    llm: LLMClient
    sandbox: Sandbox
    memory: Memory


WorkerFactory = Callable[[RoleConfig, WorkerParts], Agent]
SandboxFactory = Callable[[str, Path], Sandbox]


def build_tools(role: RoleConfig, settings: Settings) -> list[Tool]:
    """The Tool objects for the names in role.tool_names.

    TODO(LI Heyang): return the real tools (web_search, fetch_url, read_file, write_file,
    delete_file, list_files, run_python, git). Until they exist a worker has no tools."""
    return []


def default_worker_factory(role: RoleConfig, parts: WorkerParts) -> Agent:
    return WorkerAgent(role, parts.bus, parts.router, parts.settings, parts.llm,
                       build_tools(role, parts.settings), parts.sandbox, parts.memory)


def default_sandbox_factory(settings: Settings) -> SandboxFactory:
    """LocalSandbox or DockerSandbox, as Settings.sandbox_backend says."""
    cls = DockerSandbox if settings.sandbox_backend == "docker" else LocalSandbox
    return lambda agent_id, root: cls(agent_id, root)


def make_llm(settings: Settings) -> LLMClient:
    """The LLM client the settings ask for. Raises SystemExit with a readable message
    if it cannot be built."""
    if settings.llm_provider != "deepseek":
        raise SystemExit(f"unsupported LLM provider: {settings.llm_provider!r} (supported: deepseek)")
    if not settings.deepseek_api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set. Copy .env.example to .env and fill it in, "
                         "or try `python -m mas --demo` which needs no key.")
    return DeepSeekClient(settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model)


def make_human(settings: Settings) -> HumanIO:
    """AutoResponder for unattended runs (Settings.auto_hitl), else the command line."""
    return AutoResponder() if settings.auto_hitl else CliHumanIO()


@dataclass
class System:
    settings: Settings
    bus: MessageBus
    state: StateTable
    router: Router
    orchestrator: Orchestrator
    workers: dict[str, Agent]
    memories: dict[str, Memory]
    sandboxes: dict[str, Sandbox]
    human: HumanIO
    _tasks: list[asyncio.Task] = field(default_factory=list, repr=False)

    def start(self) -> list[asyncio.Task]:
        """Start the Orchestrator and the workers (each runs its own loop). Must be called
        inside a running event loop."""
        for agent in [self.orchestrator, *self.workers.values()]:
            task = asyncio.create_task(agent.run(), name=f"agent:{agent.agent_id}")
            task.add_done_callback(self._report_crash)
            self._tasks.append(task)
        return self._tasks

    @staticmethod
    def _report_crash(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            log.error("%s stopped with an error", task.get_name(), exc_info=task.exception())

    async def stop(self) -> None:
        """Stop the agents and whatever they were doing."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def run(self) -> None:
        """Start everything and run the human side until it ends (/quit, end of input)."""
        self.start()
        try:
            await self.human.run(self.bus)
        finally:
            await self.stop()


def build_system(settings: Settings, llm: LLMClient, human: HumanIO, *,
                 roles: dict[str, RoleConfig] | None = None,
                 worker_factory: WorkerFactory = default_worker_factory,
                 sandbox_factory: SandboxFactory | None = None) -> System:
    """Wire the bus, the router, one workspace and one memory per role, the Orchestrator and
    the workers, and put everybody into the group chat."""
    roles = roles or ROLES
    sandbox_factory = sandbox_factory or default_sandbox_factory(settings)
    bus = InMemoryBus()
    state = StateTable()
    sandboxes = {r: sandbox_factory(r, settings.workspaces_dir / r) for r in roles}
    memories: dict[str, Memory] = {r: JsonlMemory.for_agent(settings.memory_dir, r) for r in roles}
    router = Router(bus, state, sandboxes, settings)
    orchestrator = Orchestrator(bus, router, settings, llm, roles, memories)
    workers = {r: worker_factory(role, WorkerParts(bus, router, settings, llm, sandboxes[r], memories[r]))
               for r, role in roles.items()}
    for member in (HUMAN, ORCHESTRATOR, *workers):
        bus.join(member, GROUP_MAIN)
    return System(settings, bus, state, router, orchestrator, workers, memories, sandboxes, human)
