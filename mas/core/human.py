"""Human side of the bus (design §7, D12).

HumanIO base and CliHumanIO: JIAN Yimin. AutoResponder: LI Heyang.

The human is a bus participant with id HUMAN. Switching between an
interactive CLI and unattended evaluation is a config change only.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from enum import Enum

from mas.core.bus import MessageBus
from mas.core.message import (GROUP_MAIN, HUMAN, ORCHESTRATOR, Message, MsgType,
                              dm_channel, dm_members, is_group)

log = logging.getLogger(__name__)


class HitlKind(str, Enum):
    APPROVAL = "approval"   # before a requires_approval tool (delete, git push)
    CLARIFY = "clarify"     # task description is ambiguous
    ADVICE = "advice"       # same tool failed twice in a row


# What Router.request_human returns when the request is cancelled with /cancel.
# Callers must treat it as "stop", never as an approval.
CANCELLED_ANSWER = "cancelled"


@dataclass
class HitlRequest:
    request_id: str         # "h1", "h2", ... unique within a session
    agent_id: str
    task_id: str            # "" when the Orchestrator asks for clarification
    channel: str            # the task's origin_channel
    kind: HitlKind
    question: str
    options: list[str] = field(default_factory=list)
    root_id: str = ""       # the request (root) it belongs to; lets /cancel drop it


class HumanIO(ABC):
    agent_id = HUMAN

    @abstractmethod
    async def run(self, bus: MessageBus) -> None:
        """Main loop: show incoming messages, answer HITL requests, send human input."""

    @abstractmethod
    async def show(self, msg: Message) -> None: ...

    @abstractmethod
    async def answer(self, req: HitlRequest) -> str:
        """Return the human's answer to a HITL request."""

    # ---- shared by every implementation ---------------------------------------

    @staticmethod
    def request_from(msg: Message) -> HitlRequest:
        """The HitlRequest carried by a HITL_REQUEST message."""
        p = msg.payload
        return HitlRequest(
            request_id=p["request_id"], agent_id=msg.sender, task_id=p.get("task_id") or "",
            channel=msg.channel, kind=HitlKind(p["kind"]), question=p["question"],
            options=list(p.get("options") or []), root_id=p.get("root_id") or "")

    async def handle_incoming(self, bus: MessageBus, msg: Message) -> None:
        """What to do with one message from the human's inbox: show it (the human's own
        messages are skipped) and, for a HITL_REQUEST, start answering it in the
        background so that several requests can be open at the same time. The answer is
        published as HITL_RESPONSE in the channel the request came from. A run() loop is
        just `for each inbox message: await self.handle_incoming(bus, msg)`."""
        if msg.sender == HUMAN:
            return
        await self.show(msg)
        if msg.type == MsgType.HITL_REQUEST:
            task = asyncio.create_task(self._respond(bus, msg, self.request_from(msg)))
            self._answering().add(task)
            task.add_done_callback(self._answering().discard)

    async def _respond(self, bus: MessageBus, request: Message, req: HitlRequest) -> None:
        answer = await self.answer(req)
        await bus.publish(Message(
            MsgType.HITL_RESPONSE, sender=HUMAN, channel=req.channel,
            content=f"/reply {req.request_id} {answer}", receiver=req.agent_id,
            payload={"request_id": req.request_id, "answer": answer}, reply_to=request.id))

    def _answering(self) -> set[asyncio.Task]:
        return self.__dict__.setdefault("_answering_tasks", set())

    async def _stop_answering(self) -> None:
        """Cancel the requests still waiting for an answer (called when run() ends)."""
        tasks = list(self._answering())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _stdin_line() -> str | None:
    """Read one line from a pipe or file without blocking the event loop. None at EOF.
    (The reading thread cannot be interrupted, so a program that stops while waiting for
    input needs to exit the process, e.g. with Ctrl-D or /quit.)"""
    try:
        return await asyncio.to_thread(input, "> ")
    except EOFError:
        return None


class PromptReader:
    """Reads a line with prompt_toolkit, so the prompt stays at the bottom and messages
    that arrive while the human is typing are printed above it (run() has to be wrapped
    in prompt_toolkit's patch_stdout for that). Ctrl-D and Ctrl-C end the input."""

    def __init__(self, session=None) -> None:
        if session is None:
            from prompt_toolkit import PromptSession
            session = PromptSession()
        self._session = session

    async def __call__(self) -> str | None:
        try:
            return await self._session.prompt_async("> ")
        except (EOFError, KeyboardInterrupt):
            return None


def default_reader():
    """(read_line, stdout_patch) for a real terminal: prompt_toolkit when it is installed
    and stdin is a terminal, otherwise plain input() (pipes, files, no prompt_toolkit)."""
    if sys.stdin.isatty():
        try:
            from prompt_toolkit.patch_stdout import patch_stdout
            return PromptReader(), patch_stdout
        except ImportError:
            pass
    return _stdin_line, nullcontext


HELP_TEXT = """命令：
  直接输入文字              在群里发给大家（没有 @ 谁，就由 Orchestrator 处理；@coder 则直接交给 coder）
  /dm <agent> <内容>        私聊某个 agent，直接交给它一个任务
  /status                   看当前任务进度
  /cancel                   取消群里当前的请求
  /cancel <agent>           取消和某个 agent 私聊里还在做的任务
  /reply <编号> <回答>      回答一个请求，如 /reply h1 yes；私聊里的请求用 coder:h1
                            只有一个请求在等待时，可以省略编号：/reply yes
  /help                     显示这段说明
  /quit                     退出"""

_KIND_LABEL = {HitlKind.APPROVAL: "请求批准", HitlKind.CLARIFY: "需要澄清", HitlKind.ADVICE: "请求帮助"}
_ID_TOKEN = re.compile(r"^(?:([A-Za-z_][\w-]*):)?(h\d+)$")
_MENTION = re.compile(r"@([A-Za-z_][\w-]*)")


class CliHumanIO(HumanIO):
    """Terminal UI. Commands: /dm <agent> <text>, /status, /cancel, /reply <hid> <answer>.

    `read_line` (async, returns a line or None at end of input) and `write` (prints one
    block of text) can be replaced, which is how the tests drive it.

    What is shown: CHAT, TASK_ASSIGN, TASK_RESULT, HITL_REQUEST, and STATUS messages
    marked public. Messages in a DM are tagged with the agent's name."""

    def __init__(self, read_line: Callable[[], Awaitable[str | None]] | None = None,
                 write: Callable[[str], None] | None = None) -> None:
        if read_line is None:
            read_line, self._patch_stdout = default_reader()
        else:
            self._patch_stdout = nullcontext
        self._read_line = read_line
        self._write = write or print
        self._bus: MessageBus | None = None
        # open HITL requests: (channel, request id) -> (future holding the answer, request)
        self._pending: dict[tuple[str, str], tuple[asyncio.Future[str], HitlRequest]] = {}

    # ---- main loop ---------------------------------------------------------------

    async def run(self, bus: MessageBus) -> None:
        """Show incoming messages and read the human's input at the same time, until
        /quit or end of input."""
        self._bus = bus
        bus.join(HUMAN, GROUP_MAIN)
        inbox = bus.subscribe(HUMAN)
        shower = asyncio.create_task(self._show_loop(bus, inbox))
        try:
            with self._patch_stdout():
                self._write(HELP_TEXT)
                while True:
                    line = await self._read_line()
                    if line is None or not await self.handle_input(line):
                        break
        finally:
            shower.cancel()
            await asyncio.gather(shower, return_exceptions=True)
            await self._stop_answering()

    async def _show_loop(self, bus: MessageBus, inbox: asyncio.Queue[Message]) -> None:
        while True:
            msg = await inbox.get()
            try:
                await self.handle_incoming(bus, msg)
            except Exception:
                log.exception("cli failed to show message %s", msg.id)

    async def handle_incoming(self, bus: MessageBus, msg: Message) -> None:
        await super().handle_incoming(bus, msg)
        roots = msg.payload.get("cancelled_roots") if msg.type == MsgType.CHAT else None
        if roots:
            self._drop_requests(msg.channel, roots)

    def _drop_requests(self, channel: str, roots: list[str]) -> None:
        """After /cancel: forget the open requests of the cancelled roots in `channel`
        (their agents have already been released, so nobody waits for the answer)."""
        for key, (fut, req) in list(self._pending.items()):
            if req.channel == channel and req.root_id in roots:
                fut.cancel()
                self._pending.pop(key, None)

    # ---- output ------------------------------------------------------------------

    async def show(self, msg: Message) -> None:
        text = self.format(msg)
        if text:
            self._write(text)

    @staticmethod
    def format(msg: Message) -> str | None:
        """The text shown for `msg`, or None if the CLI does not show it."""
        if msg.sender == HUMAN:
            return None
        tag = "" if is_group(msg.channel) else f"(私聊·{_other(msg.channel)}) "
        if msg.type in (MsgType.CHAT, MsgType.TASK_ASSIGN, MsgType.TASK_RESULT):
            return f"{tag}[{msg.sender}] {msg.content}"
        if msg.type == MsgType.STATUS:
            return f"{tag}· {msg.content}" if msg.payload.get("public") and msg.content else None
        if msg.type == MsgType.HITL_REQUEST:
            req = HumanIO.request_from(msg)
            line = f"{tag}? [{req.request_id}] {msg.sender} {_KIND_LABEL[req.kind]}：{req.question}"
            if req.options:
                line += f"　可选：{' / '.join(req.options)}"
            return f"{line}\n   回复：/reply {_reply_token(req)} <回答>"
        return None

    # ---- input -------------------------------------------------------------------

    async def handle_input(self, line: str) -> bool:
        """Handle one line typed by the human. Returns False to stop (/quit)."""
        text = line.strip()
        if not text:
            return True
        if not text.startswith("/"):
            await self._send(GROUP_MAIN, text, self._single_mention(text))
            return True
        cmd, _, rest = text.partition(" ")
        rest = rest.strip()
        cmd = cmd.lower()
        if cmd == "/dm":
            await self._dm(rest)
        elif cmd == "/cancel" and rest in self._agents():
            await self._send(dm_channel(HUMAN, rest), "/cancel", rest)   # that agent cancels its DM tasks
        elif cmd in ("/status", "/cancel"):
            await self._send(GROUP_MAIN, text, ORCHESTRATOR)       # the Orchestrator answers these
        elif cmd == "/reply":
            self._reply(rest)
        elif cmd == "/help":
            self._write(HELP_TEXT)
        elif cmd in ("/quit", "/exit"):
            return False
        else:
            self._write(f"不认识的命令 {cmd}，输入 /help 查看可用命令。")
        return True

    def _agents(self) -> list[str]:
        return [a for a in (self._bus.members(GROUP_MAIN) if self._bus else []) if a != HUMAN]

    def _single_mention(self, text: str) -> str | None:
        """The agent @mentioned in `text`, if exactly one is."""
        found = self._mentions(text)
        return found[0] if len(found) == 1 else None

    def _mentions(self, text: str) -> list[str]:
        known = self._agents()
        return list(dict.fromkeys(m for m in _MENTION.findall(text) if m in known))

    async def _send(self, channel: str, text: str, receiver: str | None) -> None:
        assert self._bus is not None, "run() has not been started"
        await self._bus.publish(Message(
            MsgType.CHAT, sender=HUMAN, channel=channel, content=text, receiver=receiver,
            mentions=self._mentions(text)))

    async def _dm(self, rest: str) -> None:
        agent, _, text = rest.partition(" ")
        text = text.strip()
        if not agent or not text:
            self._write("用法：/dm <agent> <内容>")
        elif agent not in self._agents():
            self._write(f"没有这个 agent：{agent}。可选：{', '.join(self._agents())}")
        else:
            await self._send(dm_channel(HUMAN, agent), text, agent)

    # ---- HITL --------------------------------------------------------------------

    async def answer(self, req: HitlRequest) -> str:
        """Wait until the human answers this request with /reply."""
        key = (req.channel, req.request_id)
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending[key] = (fut, req)
        try:
            return await fut
        finally:
            self._pending.pop(key, None)

    def _reply(self, rest: str) -> None:
        """/reply <id> <answer>, or /reply <answer> when only one request is open."""
        token, _, tail = rest.partition(" ")
        if _ID_TOKEN.match(token):
            key = self._find_request(token)
            answer = tail.strip()
        elif len(self._pending) == 1 and rest:
            key, answer = next(iter(self._pending)), rest
        elif not self._pending:
            self._write("现在没有等待回答的请求。")
            return
        else:
            self._write("有多个请求在等待，请写上编号：/reply <编号> <回答>。等待中：" + self._waiting())
            return
        if key is None:
            return
        if not answer:
            self._write("请写上回答：/reply <编号> <回答>")
            return
        fut, req = self._pending[key]
        if not fut.done():
            fut.set_result(answer)
        self._write(f"已回复 {_reply_token(req)}：{answer}")

    def _find_request(self, token: str) -> tuple[str, str] | None:
        """The open request `token` refers to, or None (after telling the human why).
        "h1" is the group's h1 if the group has one, else the only open h1; "coder:h1"
        is the h1 of the DM with coder."""
        who, rid = _ID_TOKEN.match(token).groups()
        if who:
            key = (dm_channel(HUMAN, who), rid)
            if key in self._pending:
                return key
            candidates: list[tuple[str, str]] = []
        else:
            candidates = [k for k in self._pending if k[1] == rid]
            if (GROUP_MAIN, rid) in self._pending:
                return (GROUP_MAIN, rid)
            if len(candidates) == 1:
                return candidates[0]
        if candidates:
            self._write(f"{rid} 不止一个，请写成 " + " 或 ".join(_reply_token(self._pending[k][1]) for k in candidates))
        else:
            self._write(f"没有等待回答的请求 {token}。等待中：" + self._waiting())
        return None

    def _waiting(self) -> str:
        return "、".join(_reply_token(req) for _, req in self._pending.values()) or "（无）"


def _other(channel: str) -> str:
    """The agent on the other side of a DM channel."""
    a, b = dm_members(channel)
    return b if a == HUMAN else a


def _reply_token(req: HitlRequest) -> str:
    """What the human types to answer `req`: "h1" in the group, "coder:h1" in a DM."""
    return req.request_id if is_group(req.channel) else f"{_other(req.channel)}:{req.request_id}"


class AutoResponder(HumanIO):
    """Unattended mode for evaluation: answers every HITL request immediately."""

    DEFAULT_ANSWERS = {
        HitlKind.APPROVAL: "yes",
        HitlKind.CLARIFY: "按原描述执行",
        HitlKind.ADVICE: "换一种方法",
    }

    def __init__(self) -> None:
        self.hitl_count = 0

    async def run(self, bus: MessageBus) -> None:
        raise NotImplementedError

    async def show(self, msg: Message) -> None:
        raise NotImplementedError

    async def answer(self, req: HitlRequest) -> str:
        raise NotImplementedError

    async def submit(self, bus: MessageBus, text: str, channel: str) -> str:
        """Post a task as the human (used by the eval harness); returns the message id."""
        raise NotImplementedError
