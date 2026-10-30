"""Worker agent: ReAct loop (design §6).

Owner: LI Heyang.
"""
from __future__ import annotations

from mas.agents.base import Agent
from mas.agents.roles import RoleConfig
from mas.config import Settings
from mas.core.bus import MessageBus
from mas.core.message import Message
from mas.core.router import Router
from mas.core.task import Task, TaskResult
from mas.llm.base import FunctionSpec, LLMClient
from mas.memory.base import Memory
from mas.sandbox.base import Sandbox
from mas.tools.base import Tool


class WorkerAgent(Agent):
    def __init__(self, role: RoleConfig, bus: MessageBus, router: Router,
                 settings: Settings, llm: LLMClient, tools: list[Tool],
                 sandbox: Sandbox, memory: Memory) -> None:
        super().__init__(role.agent_id, bus, router, settings)
        self.role = role
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.sandbox = sandbox
        self.memory = memory

    async def handle_task(self, task: Task) -> TaskResult:
        """ReAct loop.

        prompt = role.system_prompt + recalled lessons (memory.recall) + board_text(task)
                 + goal / context / inbox files
        loop up to settings.max_worker_steps:
          - LLM chooses tools from function_specs(task)
          - decline -> return TaskResult(declined=True, suggest=...)
          - call_<agent> -> self.call_agent(...)
          - requires_approval tool -> self.ask_human(..., HitlKind.APPROVAL) first
          - tool errors become observations; same tool failing twice -> HitlKind.ADVICE
          - new human messages on the board are appended before the next step
        On return: fill artifacts / refs from ToolResult.files_written / refs,
        write an Experience, and on failure schedule reflect() without awaiting it.
        """
        raise NotImplementedError

    async def handle_chat(self, msg: Message) -> None:
        """Human DM or @mention: register with router.open_direct_task and run
        handle_task; the reply goes back to msg.channel."""
        raise NotImplementedError

    def function_specs(self, task: Task) -> list[FunctionSpec]:
        """Real tools + call_<other agents> (not self) + decline + read_group."""
        raise NotImplementedError

    async def reflect(self, task: Task, result: TaskResult) -> None:
        """Failure only, run after returning: one LLM call -> one-sentence lesson
        -> memory.add(...)."""
        raise NotImplementedError

    def profile(self) -> str:
        return self.memory.profile(self.settings.profile_max_chars)
