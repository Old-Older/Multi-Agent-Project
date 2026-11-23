"""Bridge the local web server's request threads to the existing async scenario runner."""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path, PureWindowsPath

from mas.app import build_system, make_llm
from mas.config import Settings
from mas.core.bus import MessageBus
from mas.core.human import HitlRequest, HumanIO
from mas.core.message import HUMAN, Message, MsgType
from mas.llm.base import ChatMessage, FunctionSpec, LLMClient, LLMError, LLMResponse
from mas.scenario import Scenario, ScenarioTask, driver_for, parse_task_markdown
from mas.team import parse_team
from mas.web_config import resolve_config

log = logging.getLogger(__name__)


def _safe_error(exc: BaseException, settings: Settings) -> str:
    message = str(exc) or type(exc).__name__
    secrets = (settings.hkgai_api_key, settings.deepseek_api_key, settings.hkgai_search_api_key,
               settings.github_token)
    if any(secret and secret in message for secret in secrets):
        return "模型服务调用失败，请检查配置。"
    return message


class _WebLLM(LLMClient):
    """Remove credential-bearing diagnostics before workers can log or record them."""

    def __init__(self, client: LLMClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def chat(self, messages: list[ChatMessage], tools: list[FunctionSpec] | None = None,
                   temperature: float = 0.2) -> LLMResponse:
        try:
            return await self.client.chat(messages, tools, temperature)
        except LLMError as exc:
            raise LLMError(_safe_error(exc, self.settings)) from None
        except Exception:
            # Third-party transport exceptions can include their request headers.
            raise LLMError("模型服务调用失败，请检查模型和连接。") from None


def _scenario(roles: str, tasks: list[str]) -> Scenario:
    if not isinstance(roles, str) or not roles.strip():
        raise ValueError("请填写角色 Markdown。")
    team = parse_team(roles.lstrip("\ufeff"))
    if len({name.casefold() for name in team}) != len(team):
        raise ValueError("角色 ID 不能仅有大小写差异。")
    if any(PureWindowsPath(name).is_reserved() for name in team):
        raise ValueError("角色 ID 不能使用系统保留文件名。")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("请至少填写一个任务。")
    rounds = []
    for index, document in enumerate(tasks, 1):
        title = f"任务 {index}"
        if not isinstance(document, str) or not document.strip():
            raise ValueError(f"{title} 的内容为空。")
        doc = document.lstrip("\ufeff").strip()
        if doc.startswith(("#", "```")) and any(line.strip().startswith("```") for line in doc.splitlines()):
            task = parse_task_markdown(doc, title)
            if not task:
                raise ValueError(f"{title} 的代码块中没有任务内容。")
        else:
            task = ScenarioTask(title, title, doc)
        if task.prompt.startswith("/"):
            raise ValueError(f"{title} 以 / 开头，会被系统当作聊天命令。请填写任务指令。")
        rounds.append(task)
    return Scenario("web", team, rounds)


class _Run(HumanIO):
    """The bus and workers live on one event loop. HTTP reads and answers use a lock."""

    def __init__(self, base_dir: Path, scenario: Scenario, roles: str, tasks: list[str], config: dict) -> None:
        self.id = uuid.uuid4().hex
        self.directory = base_dir.resolve() / "web-runs" / self.id
        self.config = config
        self.scenario = scenario
        self.roles = roles
        self.tasks = tuple(tasks)
        self.lock = threading.Lock()
        self.status = "running"
        self.error = ""
        self.events: list[dict] = []
        self.results: list[dict] = []
        self.pending: dict[str, tuple[HitlRequest, Future[str]]] = {}
        self.files: dict[str, Path] = {}
        self._task: asyncio.Task | None = None
        self._stopping = False

    def execute(self, llm: LLMClient, settings: Settings) -> None:
        try:
            asyncio.run(self._execute(llm, settings))
            if len(self.results) != len(self.scenario.tasks):
                raise RuntimeError("运行提前结束。")
            status = "completed" if all(result["success"] for result in self.results) else "failed"
            error = "" if status == "completed" else "有任务未成功完成，请查看各任务结果。"
        except asyncio.CancelledError:
            status, error = "failed", "本地服务已停止，运行中断。"
        except Exception as exc:
            status, error = "failed", _safe_error(exc, settings)
            log.error("web run %s failed: %s", self.id, error)
        with self.lock:
            self.status = status
            self.error = error

    async def _execute(self, llm: LLMClient, settings: Settings) -> None:
        with self.lock:
            if self._stopping:
                raise asyncio.CancelledError()
            self._task = asyncio.current_task()
        try:
            system = build_system(settings, llm, self, roles=self.scenario.team, run_name="web")
            system.bus.add_observer(self.observe)
            await system.run(driver_for(self.scenario, announce=lambda text: None), until_driver_done=True)
        finally:
            with self.lock:
                self._task = None

    def stop(self) -> None:
        with self.lock:
            self._stopping = True
            if self._task:
                self._task.get_loop().call_soon_threadsafe(self._task.cancel)

    async def run(self, bus: MessageBus) -> None:
        inbox = bus.subscribe(HUMAN)
        try:
            while True:
                await self.handle_incoming(bus, await inbox.get())
        finally:
            await self._stop_answering()

    async def show(self, msg: Message) -> None:
        # The observer also receives delegation and status messages from other channels.
        pass

    async def answer(self, req: HitlRequest) -> str:
        choice: Future[str] = Future()
        with self.lock:
            self.pending[req.request_id] = req, choice
        try:
            return await asyncio.wrap_future(choice)
        finally:
            with self.lock:
                self.pending.pop(req.request_id, None)

    def reply(self, question_id: str, answer: str) -> None:
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("请输入回复。")
        with self.lock:
            question = self.pending.get(question_id)
            if not question or question[1].done():
                raise ValueError("这个问题已经结束。")
            question[1].set_result(answer.strip())

    def observe(self, msg: Message) -> None:
        payload = msg.payload
        kind = "final" if payload.get("final") else msg.type.value
        text = msg.content
        if msg.type == MsgType.STATUS:
            text = payload.get("note") or payload.get("status", "")
        with self.lock:
            self.events.append({"kind": kind, "sender": msg.sender, "text": text, "time": msg.ts})
            if kind == "final":
                self._finish_round(msg)

    def _finish_round(self, msg: Message) -> None:
        payload = msg.payload
        for req, future in self.pending.values():
            if req.root_id == payload.get("root_id"):
                future.cancel()
        files = []
        for name in payload.get("deliverables", []):
            path = Path(payload["output_dir"]) / name
            if self._is_delivery(path):
                file_id = uuid.uuid4().hex
                self.files[file_id] = path
                files.append({"id": file_id, "name": path.name})
        task = self.scenario.tasks[len(self.results)]
        self.results.append({"title": task.title, "success": bool(payload.get("success")),
                             "text": msg.content, "files": files})

    def _is_delivery(self, path: Path) -> bool:
        return path.resolve().is_relative_to(self.directory / "output") and path.is_file()

    def artifact(self, file_id: str) -> Path:
        with self.lock:
            path = self.files[file_id]
        if not self._is_delivery(path):
            raise KeyError(file_id)
        return path

    def snapshot(self) -> dict:
        with self.lock:
            questions = [{"id": req.request_id, "sender": req.agent_id, "kind": req.kind.value,
                          "text": req.question, "options": list(req.options)}
                         for req, future in self.pending.values() if not future.done()]
            return {"id": self.id, "status": self.status, "events": list(self.events),
                    "questions": questions, "results": list(self.results), "error": self.error}


class RunManager:
    """One active scenario at a time. Finished runs stay inspectable until server exit."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._runs: dict[str, _Run] = {}
        self._lock = threading.Lock()
        self._active: threading.Thread | None = None

    def start(self, roles: str, tasks: list[str], config: dict | None = None) -> str:
        scenario = _scenario(roles, tasks)
        with self._lock:
            if self._active and self._active.is_alive():
                raise RuntimeError("当前已有任务正在运行。")
            settings, public = resolve_config(self.settings, config)
            run = _Run(settings.data_dir, scenario, roles, tasks, public)
            settings = replace(settings, data_dir=run.directory, workspaces_dir=run.directory / "workspaces")
            try:
                llm = _WebLLM(make_llm(settings), settings)
            except (SystemExit, Exception) as exc:
                raise ValueError(_safe_error(exc, settings)) from None
            thread = threading.Thread(target=run.execute, args=(llm, settings), name=f"web-{run.id}", daemon=True)
            thread.start()
            self._active = thread
            self._runs[run.id] = run
            return run.id

    def _get(self, run_id: str) -> _Run:
        with self._lock:
            return self._runs[run_id]

    def active_id(self) -> str | None:
        with self._lock:
            return next(reversed(self._runs)) if self._active and self._active.is_alive() else None

    def inputs(self, run_id: str) -> dict:
        run = self._get(run_id)
        return {"roles": run.roles, "tasks": list(run.tasks), "config": dict(run.config)}

    def snapshot(self, run_id: str) -> dict:
        return self._get(run_id).snapshot()

    def reply(self, run_id: str, question_id: str, answer: str) -> None:
        self._get(run_id).reply(question_id, answer)

    def artifact(self, run_id: str, file_id: str) -> Path:
        return self._get(run_id).artifact(file_id)

    def close(self) -> None:
        with self._lock:
            if self._active and self._active.is_alive():
                self._runs[next(reversed(self._runs))].stop()
                self._active.join()
