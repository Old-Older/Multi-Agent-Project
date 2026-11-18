"""Choosing who leads a request (coordination mode "lead", design D1).

Owner: JIAN Yimin.

Nobody is the coordinator by configuration: when the human gives the team a request, one LLM
call looks at what the request is and at what every role is responsible for, and names the
role that should lead it. The lead then plans, delegates to its teammates (call_<agent>),
asks the human when it must, and reports. A different request can have a different lead.

Two things keep this cheap and safe:
  cache     the choice is remembered per session, so the follow-up request of a conversation
            (Task 2 after Task 1) continues with the same lead and costs no LLM call;
  fallback  if the call fails, answers with something unusable, or names nobody, the first
            role of the team leads. A fallback is not cached, the next request asks again.
"""
from __future__ import annotations

import logging

from mas.agents.roles import RoleConfig
from mas.llm.base import FunctionSpec, LLMClient

log = logging.getLogger(__name__)

CHOOSE_LEAD = "choose_lead"

CHOOSE_LEAD_SPEC = FunctionSpec(
    name=CHOOSE_LEAD,
    description="Name the team member who should lead this request.",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "agent_id of the member who should lead."},
            "reason": {"type": "string", "description": "One short sentence."},
        },
        "required": ["agent_id"],
    },
)

_SYSTEM = """You assign the lead of a request in a team. The lead understands what the human wants, \
asks the human questions when needed, splits the work, delegates it to the other members, checks \
the results and reports back. Choose the one member whose responsibilities best fit coordinating \
THIS request: usually whoever is responsible for understanding the requester's goals, setting \
direction or taking decisions, not the member who would only carry out one part of it. \
Call choose_lead with that member's agent_id."""


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


class LeadSelector:
    def __init__(self, llm: LLMClient, roles: dict[str, RoleConfig], temperature: float = 0.0) -> None:
        if not roles:
            raise ValueError("a team needs at least one role")
        self.llm = llm
        self.roles = roles
        self.temperature = temperature
        self.cache: dict[str, str] = {}               # session id -> lead

    @property
    def fallback(self) -> str:
        return next(iter(self.roles))

    def forget(self, session_id: str) -> None:
        self.cache.pop(session_id, None)

    async def choose(self, session_id: str, request: str) -> str:
        """The lead of `request` in this session. Never raises."""
        cached = self.cache.get(session_id)
        if cached in self.roles:
            return cached
        if len(self.roles) == 1:
            return self.fallback
        try:
            lead = await self._ask(request)
        except Exception:
            log.warning("Choosing a lead failed; %s leads instead", self.fallback, exc_info=True)
            return self.fallback
        if lead is None:
            log.warning("The LLM did not name a team member; %s leads instead", self.fallback)
            return self.fallback
        self.cache[session_id] = lead
        return lead

    async def _ask(self, request: str) -> str | None:
        members = "\n".join(
            f"- {r.agent_id} ({r.display_name}): "
            f"{_clip(' '.join(filter(None, [r.system_prompt, r.capability])), 400)}"
            for r in self.roles.values())
        response = await self.llm.chat([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Team members:\n{members}\n\nRequest from the human:\n{request.strip()}"},
        ], [CHOOSE_LEAD_SPEC], temperature=self.temperature)
        for call in response.tool_calls:
            name = call.arguments.get("agent_id") if call.name == CHOOSE_LEAD else None
            if isinstance(name, str) and name.strip() in self.roles:
                return name.strip()
        text = response.text.strip().strip("`'\"*. ")        # a plain answer that is just an id
        return text if text in self.roles else None
