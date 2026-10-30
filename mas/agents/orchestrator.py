"""Orchestrator: agent-as-a-tool ReAct loop (design §2, D1, D3–D6).

Owner: JIAN Yimin.
"""
from __future__ import annotations

from mas.agents.base import Agent
from mas.agents.roles import RoleConfig
from mas.config import Settings
from mas.core.bus import MessageBus
from mas.core.message import ORCHESTRATOR, Message
from mas.core.router import Router
from mas.core.task import Task, TaskResult
from mas.llm.base import FunctionSpec, LLMClient
from mas.memory.base import Memory


class Orchestrator(Agent):
    def __init__(self, bus: MessageBus, router: Router, settings: Settings,
                 llm: LLMClient, roles: dict[str, RoleConfig],
                 memories: dict[str, Memory]) -> None:
        super().__init__(ORCHESTRATOR, bus, router, settings)
        self.llm = llm
        self.roles = roles
        self.memories = memories      # read-only, for capability profiles

    def should_handle(self, msg: Message) -> bool:
        """Also handles human group messages that @mention nobody (D7 rule 2)."""
        raise NotImplementedError

    async def handle_chat(self, msg: Message) -> None:
        """/status -> state table text; /cancel -> router.cancel_root;
        interjection while a root runs -> append to the running loop;
        otherwise -> run_root(msg)."""
        raise NotImplementedError

    async def run_root(self, msg: Message) -> None:
        """One human request.

        up to settings.max_orchestrator_rounds:
          resp = llm.chat(messages, function_specs(session))
          resp.text -> board.set_plan (the "剩余步骤" line)
          run all call_<agent> tool calls concurrently (asyncio.gather) via
            router.dispatch; feed back summary + artifacts + success only
          ask_human -> router.request_human(HitlKind.CLARIFY)
          finish -> board.finish_root, copy deliverables to output/<root_id>/,
            post the final reply in msg.channel
        When rounds run out, report what is done (MAX_ROUNDS).
        """
        raise NotImplementedError

    def function_specs(self, session_id: str) -> list[FunctionSpec]:
        """call_<agent> for every role with its memory profile, + ask_human + finish."""
        raise NotImplementedError

    def system_prompt(self) -> str:
        raise NotImplementedError

    async def handle_task(self, task: Task) -> TaskResult:
        raise NotImplementedError("the Orchestrator is never assigned tasks")
