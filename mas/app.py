"""Assembling the system: bus, router, state table, memories, agents and the human side.

build_system() is the one place that knows how the parts fit together. Everything that
belongs to someone else's work is a plug-in point with a default:

  llm              any LLMClient (make_llm() builds the HKGAI one from the settings)
  worker_factory   how a Worker is built (default: WorkerAgent with build_tools())
  sandbox_factory  how a workspace is built (default: LocalSandbox or DockerSandbox)
  human            CliHumanIO for a person, AutoResponder for evaluation

so a test, the demo (mas/demo.py) and the real system all go through the same wiring.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from mas.agents.base import Agent
from mas.agents.roles import RoleConfig
from mas.agents.worker import WorkerAgent
from mas.config import Settings
from mas.core.bus import InMemoryBus, MessageBus
from mas.core.human import AutoResponder, CliHumanIO, HumanIO
from mas.core.message import GROUP_MAIN, HUMAN
from mas.core.requests import RequestTracker
from mas.core.router import Router
from mas.core.transcript import Transcript
from mas.core.state import StateTable
from mas.llm.base import LLMClient
from mas.llm.deepseek import DeepSeekClient
from mas.llm.hkgai import HKGAIClient
from mas.memory.base import JsonlMemory, Memory
from mas.sandbox.base import DockerSandbox, LocalSandbox, Sandbox
from mas.tools.base import Tool
from mas.tools.files import DeleteFile, ListFiles, ReadFile, WriteFile
from mas.tools.git import Git
from mas.tools.python import RunPython
from mas.tools.web import FetchURL, WebSearch

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
    peers: dict[str, RoleConfig] | None = None     # the whole team, for call_<teammate> (None: works alone)
    memories: dict[str, Memory] | None = None      # everybody's memory, read-only, for the teammates' profiles


WorkerFactory = Callable[[RoleConfig, WorkerParts], Agent]
SandboxFactory = Callable[[str, Path], Sandbox]


def build_tools(role: RoleConfig, settings: Settings) -> list[Tool]:
    """Fresh instances of the tools a role is configured with, in the order of `role.tool_names`.

    Every tool is built from the settings it needs (the Git tool the GitHub token, web search the
    search key). A name that is not a tool is a mistake in the team file and fails loudly."""
    constructors: dict[str, Callable[[], Tool]] = {
        ReadFile.name: ReadFile, WriteFile.name: WriteFile,
        DeleteFile.name: DeleteFile, ListFiles.name: ListFiles,
        RunPython.name: RunPython,
        FetchURL.name: lambda: FetchURL(allow_fake_ip=settings.fetch_allow_fake_ip),
        WebSearch.name: lambda: WebSearch(api_key=settings.search_api_key),
        Git.name: lambda: Git(github_token=settings.github_token),
    }
    result: list[Tool] = []
    for name in role.tool_names:
        if name not in constructors:
            raise ValueError(f"unknown tool {name!r} configured for {role.agent_id}")
        result.append(constructors[name]())
    if WebSearch.name in role.tool_names and not settings.search_api_key:
        log.info("%s has web_search and no SEARCH_API_KEY: it uses the keyless search (DuckDuckGo, Bing, ...)",
                 role.agent_id)
    return result


def default_worker_factory(role: RoleConfig, parts: WorkerParts) -> Agent:
    return WorkerAgent(role, parts.bus, parts.router, parts.settings, parts.llm,
                       build_tools(role, parts.settings), parts.sandbox, parts.memory, peers=parts.peers,
                       peer_memories=parts.memories)


def default_sandbox_factory(settings: Settings) -> SandboxFactory:
    """LocalSandbox or DockerSandbox, as Settings.sandbox_backend says."""
    cls = DockerSandbox if settings.sandbox_backend == "docker" else LocalSandbox
    return lambda agent_id, root: cls(agent_id, root)


def make_llm(settings: Settings) -> LLMClient:
    """The LLM client the settings ask for: HKGAI (default) or DeepSeek, the two the course
    allows. Raises SystemExit with a readable message if it cannot be built."""
    provider = settings.llm_provider.strip().lower()
    if provider == "hkgai":
        key, model, name, var = settings.hkgai_api_key, settings.hkgai_model, "HKGAI", "HKGAI"
    elif provider == "deepseek":
        key, model, name, var = settings.deepseek_api_key, settings.deepseek_model, "DeepSeek", "DEEPSEEK"
    else:
        raise SystemExit(f"Unsupported LLM provider {settings.llm_provider!r}. Set LLM_PROVIDER=hkgai or LLM_PROVIDER=deepseek.")
    if not key.strip():
        raise SystemExit(f"{var}_API_KEY is not set. Copy .env.example to .env and fill it in, "
                         "or try `python -m mas --demo` which needs no key.")
    if not model.strip():
        raise SystemExit(f"{var}_MODEL is not set. Set it to a model ID available to your {name} account.")
    if provider == "deepseek":
        return DeepSeekClient(api_key=key, base_url=settings.deepseek_base_url, model=model)
    return HKGAIClient(api_key=key, base_url=settings.hkgai_base_url, model=model)


def make_human(settings: Settings) -> HumanIO:
    """AutoResponder for unattended runs (Settings.auto_hitl), else the command line."""
    return AutoResponder() if settings.auto_hitl else CliHumanIO()


@dataclass
class System:
    settings: Settings
    bus: MessageBus
    state: StateTable
    router: Router
    requests: RequestTracker
    workers: dict[str, Agent]
    memories: dict[str, Memory]
    sandboxes: dict[str, Sandbox]
    human: HumanIO
    transcript: Transcript | None = None
    _tasks: list[asyncio.Task] = field(default_factory=list, repr=False)

    def start(self) -> list[asyncio.Task]:
        """Start the workers (each runs its own loop). The RequestTracker needs no loop of its
        own: it reacts to the human's messages as a bus observer. Must be called inside a
        running event loop."""
        for agent in self.workers.values():
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
        await self.requests.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def run(self, driver: Callable[[System], Awaitable[object]] | None = None, *,
                  until_driver_done: bool = False) -> None:
        """Start everything and run the human side until it ends (/quit, end of input).

        `driver` is something that talks to the system as the human while it runs (the scenario
        runner posts its tasks this way). Interactive runs go on until the human ends them;
        with `until_driver_done` (unattended runs) the run ends when the driver does. The
        transcript is written at the end either way."""
        self.start()
        human = asyncio.create_task(self.human.run(self.bus), name="human")
        driving = asyncio.create_task(driver(self), name="driver") if driver else None
        if driving is not None:
            driving.add_done_callback(self._report_crash)
        main = driving if (driving is not None and until_driver_done) else human
        try:
            await main
        finally:
            for task in (human, driving):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (human, driving) if t is not None), return_exceptions=True)
            await self.stop()
            if self.transcript is not None:
                self.transcript.save()


def build_system(settings: Settings, llm: LLMClient, human: HumanIO, *,
                 roles: dict[str, RoleConfig],
                 worker_factory: WorkerFactory = default_worker_factory,
                 sandbox_factory: SandboxFactory | None = None,
                 run_name: str = "session") -> System:
    """Wire the bus, the router, one workspace and one memory per role, the request tracker and
    the workers, and put everybody into the group chat. `roles` is the team: the user defines
    who is in it."""
    if not roles:
        raise ValueError("a team needs at least one role")
    sandbox_factory = sandbox_factory or default_sandbox_factory(settings)
    bus = InMemoryBus()
    state = StateTable()
    sandboxes = {r: sandbox_factory(r, settings.workspaces_dir / r) for r in roles}
    memories: dict[str, Memory] = {r: JsonlMemory.for_agent(settings.memory_dir, r) for r in roles}
    router = Router(bus, state, sandboxes, settings)
    requests = RequestTracker(bus, router, settings, llm, roles)
    transcript = Transcript(bus, title=f"Transcript: {run_name}", team={r: c.display_name for r, c in roles.items()},
                            path=settings.data_dir / "transcripts" / f"{run_name}-{time.strftime('%Y%m%d-%H%M%S')}.md",
                            outcomes=lambda: requests.outcomes)
    workers = {r: worker_factory(role, WorkerParts(bus, router, settings, llm, sandboxes[r], memories[r], roles, memories))
               for r, role in roles.items()}
    for member in (HUMAN, *workers):
        bus.join(member, GROUP_MAIN)
    return System(settings, bus, state, router, requests, workers, memories, sandboxes, human, transcript)
