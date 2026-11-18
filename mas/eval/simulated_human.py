"""A simulated human for unattended evaluation.

The AutoResponder answers every question with a fixed sentence, which cannot stand in for a
person who has real preferences (an investor's risk tolerance, a deadline, an audience). This
one answers clarifying questions with an LLM that plays the person who made the request, and
keeps what it said so its answers stay consistent. Approvals are granted and advice is generic,
by rule: those need no judgement.
"""
from __future__ import annotations

import logging

from mas.core.human import AutoResponder, HitlKind, HitlRequest
from mas.llm.base import LLMClient

log = logging.getLogger(__name__)

_SYSTEM = """You play the human who gave a team of AI agents the request below. A member of the team asks \
you a question. Answer as that person would: briefly (one to three sentences), concretely, in the language \
of the request. If you are asked for preferences or facts the request does not give (budget, deadline, \
risk tolerance, audience, format), decide something reasonable and stay consistent with your earlier \
answers. If options are listed, choose one of them. Never do the team's work yourself and never ask a \
question back."""

APPROVAL_ANSWER = "yes"
ADVICE_ANSWER = ("Try a simpler approach. If it still does not work, deliver what you have and say clearly "
                 "what is missing.")
FALLBACK_ANSWER = "proceed as described"


class SimulatedHuman(AutoResponder):
    def __init__(self, llm: LLMClient, temperature: float = 0.3) -> None:
        super().__init__()
        self.llm = llm
        self.temperature = temperature
        self.request = ""                                    # what the human originally asked for
        self.exchanges: list[tuple[str, str]] = []           # (question, answer), for consistency
        self.llm_calls = 0

    def set_request(self, request: str) -> None:
        """Called by the harness before each task, so the answers match the request being worked on."""
        self.request = request

    async def answer(self, req: HitlRequest) -> str:
        self.hitl_count += 1
        if req.kind == HitlKind.APPROVAL:
            return APPROVAL_ANSWER
        if req.kind == HitlKind.ADVICE:
            return ADVICE_ANSWER
        history = "\n".join(f"Q: {q}\nA: {a}" for q, a in self.exchanges[-8:]) or "(none yet)"
        options = f"\nOptions: {' / '.join(req.options)}" if req.options else ""
        try:
            self.llm_calls += 1
            response = await self.llm.chat([
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Your request:\n{self.request}\n\nWhat you have already told the team:\n"
                                            f"{history}\n\nQuestion from {req.agent_id}: {req.question}{options}"},
            ], temperature=self.temperature)
            text = " ".join(response.text.split())
        except Exception:
            log.warning("The simulated human could not answer; using the default", exc_info=True)
            text = ""
        text = text or FALLBACK_ANSWER
        self.exchanges.append((req.question, text))
        return text
