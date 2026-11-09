"""Message bus (design §3).

Owner: JIAN Yimin.

Delivery rule: a message on a channel is delivered to every member of that
channel. Receiving is cheap; agents only act on messages whose `receiver` is
themselves (or that @mention them), so delivery never costs an LLM call.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

from mas.core.message import Message, dm_members, is_group

log = logging.getLogger(__name__)


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
    """asyncio.Queue based implementation used for development and evaluation.

    Every member of the channel, including the sender, gets the message in its
    inbox (agents filter their own messages in Agent.should_handle). Inboxes are
    created lazily, so a message published before an agent calls subscribe()
    is not lost. Observers run synchronously before delivery; one failing
    observer is logged and never blocks delivery or the other observers.
    """

    def __init__(self) -> None:
        self._members: dict[str, list[str]] = {}
        self._history: dict[str, list[Message]] = {}
        self._inboxes: dict[str, asyncio.Queue[Message]] = {}
        self._observers: list[Callable[[Message], None]] = []

    def add_observer(self, fn: Callable[[Message], None]) -> None:
        self._observers.append(fn)

    async def publish(self, msg: Message) -> None:
        if not is_group(msg.channel):
            for member in dm_members(msg.channel):
                self.join(member, msg.channel)
        self._history.setdefault(msg.channel, []).append(msg)
        for fn in list(self._observers):
            try:
                fn(msg)
            except Exception:
                log.exception("bus observer failed on message %s", msg.id)
        for member in self.members(msg.channel):
            self.subscribe(member).put_nowait(msg)

    def subscribe(self, agent_id: str) -> asyncio.Queue[Message]:
        if agent_id not in self._inboxes:
            self._inboxes[agent_id] = asyncio.Queue()
        return self._inboxes[agent_id]

    def join(self, agent_id: str, channel: str) -> None:
        members = self._members.setdefault(channel, [])
        if agent_id not in members:
            members.append(agent_id)

    def members(self, channel: str) -> list[str]:
        return list(self._members.get(channel, []))

    def history(self, channel: str, limit: int = 50) -> list[Message]:
        if limit <= 0:
            return []
        return list(self._history.get(channel, [])[-limit:])
