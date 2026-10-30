"""Per-agent sandbox (design §9, D14, D15).

Owner: LI Heyang.

Tools never touch the file system or a shell directly; they go through the
Sandbox they are given. All paths are relative to the agent's workspace root.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

INBOX = "inbox"


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class Sandbox(ABC):
    def __init__(self, agent_id: str, root: Path) -> None:
        self.agent_id = agent_id
        self.root = root

    @abstractmethod
    def resolve(self, rel: str) -> Path:
        """Absolute path inside root. Raises PermissionError if it escapes root."""

    @abstractmethod
    def read_text(self, rel: str) -> str: ...

    @abstractmethod
    def write_text(self, rel: str, content: str) -> None:
        """Create parent directories as needed; overwrite existing files."""

    @abstractmethod
    def delete(self, rel: str) -> None: ...

    @abstractmethod
    def list_dir(self, rel: str = ".") -> list[str]: ...

    @abstractmethod
    def exists(self, rel: str) -> bool: ...

    @abstractmethod
    async def exec(self, cmd: list[str], timeout: float = 60.0,
                   env: dict[str, str] | None = None) -> ExecResult:
        """Run a command with cwd = root. Never raises on non-zero exit or timeout."""

    @abstractmethod
    def import_file(self, src: Path, name: str | None = None) -> str:
        """Copy a file from outside (another agent's workspace) into inbox/.
        Only the Router calls this. Returns the path relative to root."""


class LocalSandbox(Sandbox):
    """Directory + subprocess with cwd and timeout. Used for development."""

    def resolve(self, rel: str) -> Path:
        raise NotImplementedError

    def read_text(self, rel: str) -> str:
        raise NotImplementedError

    def write_text(self, rel: str, content: str) -> None:
        raise NotImplementedError

    def delete(self, rel: str) -> None:
        raise NotImplementedError

    def list_dir(self, rel: str = ".") -> list[str]:
        raise NotImplementedError

    def exists(self, rel: str) -> bool:
        raise NotImplementedError

    async def exec(self, cmd: list[str], timeout: float = 60.0,
                   env: dict[str, str] | None = None) -> ExecResult:
        raise NotImplementedError

    def import_file(self, src: Path, name: str | None = None) -> str:
        raise NotImplementedError


class DockerSandbox(LocalSandbox):
    """Same file operations as LocalSandbox (the workspace is a bind mount);
    exec runs inside one long-lived container per agent via `docker exec`."""

    async def exec(self, cmd: list[str], timeout: float = 60.0,
                   env: dict[str, str] | None = None) -> ExecResult:
        raise NotImplementedError
