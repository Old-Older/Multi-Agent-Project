"""Schemas of the tools the LLM sees that are not Tool subclasses (design §2.1, §2.2, §5, §7).

Owner: JIAN Yimin.

They are handled by the agents themselves (through the Router), not by a
sandbox. Keeping the schemas here means the Orchestrator and the workers
expose exactly the same call_<agent> tool.
"""
from __future__ import annotations

from mas.agents.roles import RoleConfig
from mas.llm.base import FunctionSpec

CALL_PREFIX = "call_"
DECLINE = "decline"
READ_GROUP = "read_group"
ASK_HUMAN = "ask_human"
FINISH = "finish"


def call_agent_spec(role: RoleConfig, profile: str = "") -> FunctionSpec:
    desc = role.capability + (f"\n{profile}" if profile else "")
    return FunctionSpec(
        name=CALL_PREFIX + role.agent_id,
        description=desc,
        parameters={
            "type": "object",
            "properties": {
                "goal": {"type": "string",
                         "description": "One goal this agent can complete on its own."},
                "context": {"type": "string",
                            "description": "Notes specific to this call. Session progress is shared automatically."},
                "files": {"type": "array", "items": {"type": "string"},
                          "description": "Files from earlier results to hand over."},
            },
            "required": ["goal"],
        },
    )


def target_of(tool_name: str) -> str | None:
    """'call_coder' -> 'coder'; None for other tools."""
    return tool_name[len(CALL_PREFIX):] if tool_name.startswith(CALL_PREFIX) else None


DECLINE_SPEC = FunctionSpec(
    name=DECLINE,
    description="Refuse this task because it is outside your abilities. Use it as the first step only.",
    parameters={
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "suggest": {"type": "string", "description": "agent_id that fits better"},
        },
        "required": ["reason"],
    },
)

READ_GROUP_SPEC = FunctionSpec(
    name=READ_GROUP,
    description="Read recent raw messages of the current chat channel.",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 20}},
    },
)

ASK_HUMAN_SPEC = FunctionSpec(
    name=ASK_HUMAN,
    description="Ask the human to clarify an ambiguous request. Only when you cannot proceed otherwise.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question"],
    },
)

FINISH_SPEC = FunctionSpec(
    name=FINISH,
    description="Finish the request and report to the human.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "deliverables": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
)
