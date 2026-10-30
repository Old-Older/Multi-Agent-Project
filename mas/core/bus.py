"""Message bus (design §3).

Owner: JIAN Yimin.

Delivery rule: a message on a channel is delivered to every member of that
channel. Receiving is cheap; agents only act on messages whose `receiver` is
themselves (or that @mention them), so delivery never costs an LLM call.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable

from mas.core.message import Message


class MessageBus(ABC):
    @abstractmethod
    async def publish(self, msg: Message) -> None:
        """Store msg in the channel history and deliver it to every channel member."""

    @abstractmethod
    def subscribe(self, agent_id: str) -> asyncio.Queue[Message]:
        """Return the inbox queue of agent_id (created on first call)."""

    @abstractmethod
    def join(self, agent_id: str, channel: str) -> None:
        """Add agent_id to channel. DM channels are joined automatically on first publish."""

    @abstractmethod
    def members(self, channel: str) -> list[str]: ...

    @abstractmethod
    def history(self, channel: str, limit: int = 50) -> list[Message]:
        """Most recent messages of channel, oldest first. Backs the read_group tool."""

    @abstractmethod
    def add_observer(self, fn: Callable[[Message], None]) -> None:
        """fn sees every published message on every channel, synchronously, before
        delivery. Used by the Router (results, HITL), session boards and logging."""


class InMemoryBus(MessageBus):
    """asyncio.Queue based implementation used for development and evaluation."""

    def add_observer(self, fn: Callable[[Message], None]) -> None:
        raise NotImplementedError

    async def publish(self, msg: Message) -> None:
        raise NotImplementedError

    def subscribe(self, agent_id: str) -> asyncio.Queue[Message]:
        raise NotImplementedError

    def join(self, agent_id: str, channel: str) -> None:
        raise NotImplementedError

    def members(self, channel: str) -> list[str]:
        raise NotImplementedError

    def history(self, channel: str, limit: int = 50) -> list[Message]:
        raise NotImplementedError
