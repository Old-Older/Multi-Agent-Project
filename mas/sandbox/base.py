"""Per-agent sandbox (design §9, D14, D15).

Owner: LI Heyang.

Tools never touch the file system or a shell directly; they go through the
Sandbox they are given. All paths are relative to the agent's workspace root.
"""
from __future__ import annotations

import math
import os
import shutil
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
    """Workspace-scoped file API and local processes, for trusted development.

    This is not an OS security boundary: commands run with the host user's
    permissions. File operations follow symlinks, then check the real path.
    """

    def __init__(self, agent_id: str, root: Path) -> None:
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        # Windows may normalize a newly created directory's trailing dots/spaces.
        super().__init__(agent_id, root.resolve())

    def resolve(self, rel: str) -> Path:
        if not isinstance(rel, str):
            raise TypeError("path must be a string")
        if not rel or "\0" in rel:
            raise ValueError("path must be nonempty and contain no NUL characters")
        path = Path(rel)
        if os.name == "nt":
            # Do not expose device files or NTFS alternate data streams as files.
            parts = path.parts[1:] if path.anchor else path.parts
            if any(Path(p).is_reserved() or ":" in p for p in parts):
                raise ValueError("device names and alternate data streams are not supported")
            if any(p not in (".", "..") and p.endswith((".", " ")) for p in parts):
                raise ValueError("Windows path components must not end in a dot or space")
        try:
            resolved = (self.root / path).resolve()
        except RuntimeError as exc:
            raise ValueError(f"cannot resolve path: {rel!r}") from exc
        if not resolved.is_relative_to(self.root):
            raise PermissionError(f"path is outside workspace: {rel!r}")
        return resolved

    def read_text(self, rel: str) -> str:
        with self.resolve(rel).open(encoding="utf-8", newline="") as stream:
            return stream.read()

    def write_text(self, rel: str, content: str) -> None:
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve newlines on Windows as well as POSIX.
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(content)

    def delete(self, rel: str) -> None:
        path = self.resolve(rel)
        if path.is_dir():
            raise IsADirectoryError(f"delete only accepts files: {rel!r}")
        path.unlink()

    def list_dir(self, rel: str = ".") -> list[str]:
        """Sorted immediate entry names, including directories and hidden files."""
        return sorted(path.name for path in self.resolve(rel).iterdir())

    def exists(self, rel: str) -> bool:
        return self.resolve(rel).exists()

    async def exec(self, cmd: list[str], timeout: float = 60.0,
                   env: dict[str, str] | None = None) -> ExecResult:
        if (not isinstance(cmd, list) or not cmd
                or any(not isinstance(arg, str) or "\0" in arg for arg in cmd)
                or not cmd[0]):
            raise ValueError("cmd must be a nonempty list of strings without NUL characters")
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be a positive finite number of seconds")
        if env is not None and (not isinstance(env, dict) or any(
                not isinstance(k, str) or not isinstance(v, str)
                or not k or "=" in k or "\0" in k or "\0" in v
                for k, v in env.items())):
            raise ValueError("env must map valid environment variable names to strings")
        from mas.sandbox._process import run_command
        return await run_command(cmd, self.root, timeout, env)

    def import_file(self, src: Path, name: str | None = None) -> str:
        """Copy a trusted source into inbox; never overwrite an existing target.

        Source paths may be outside this workspace. Destination names may contain
        subdirectories, but must resolve inside the workspace's actual inbox/.
        """
        src = Path(src).resolve(strict=True)
        if not src.is_file():
            raise IsADirectoryError(f"import source must be a regular file: {src}")
        name = src.name if name is None else name
        if not isinstance(name, str):
            raise TypeError("import name must be a string")
        if not name or "\0" in name:
            raise ValueError("import name must be nonempty and contain no NUL characters")
        if Path(name).anchor:
            raise PermissionError("import name must be relative to inbox")
        inbox = self.root / INBOX
        target = self.resolve(str(Path(INBOX) / name))
        if not target.is_relative_to(inbox) or target == inbox:
            raise PermissionError("import target must be a file inside inbox")
        if os.path.lexists(self.root / INBOX / name):
            raise FileExistsError(f"import target already exists: {name!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Opening exclusively also prevents overwrites from concurrent imports.
        created = False
        try:
            with src.open("rb") as source, target.open("xb") as destination:
                created = True
                shutil.copyfileobj(source, destination)
        except BaseException:
            # Include buffered flush/close failures, but never remove a target
            # that another importer created before our exclusive open.
            if created:
                target.unlink(missing_ok=True)
            raise
        return target.relative_to(self.root).as_posix()


class DockerSandbox(LocalSandbox):
    """Same file operations as LocalSandbox (the workspace is a bind mount);
    exec runs inside one long-lived container per agent via `docker exec`."""

    async def exec(self, cmd: list[str], timeout: float = 60.0,
                   env: dict[str, str] | None = None) -> ExecResult:
        raise NotImplementedError
