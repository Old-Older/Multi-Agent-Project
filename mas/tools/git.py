"""Version control for a standalone repository rooted at the agent's workspace."""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

from mas.sandbox.base import ExecResult, Sandbox
from mas.tools.base import Tool, ToolResult


_OPTIONS = {
    "init": (), "clone": ("url",), "status": (), "diff": ("staged",), "add": ("paths",),
    "commit": ("message",), "log": (), "push": ("remote",),
}


def _https_url(url: Any) -> SplitResult | None:
    if not isinstance(url, str) or any(c in url for c in "\\?#"):
        return None
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username is not None:
            return None
        if parts.port == 0:  # Accessing port also rejects malformed/out-of-range port numbers.
            return None
        return parts
    except ValueError:
        return None


def _github_https(url: str) -> bool:
    parts = _https_url(url)
    return parts is not None and parts.netloc.lower() in {"github.com", "github.com:443"}


class Git(Tool):
    name = "git"
    description = (
        "Clone an HTTPS repository into an empty workspace, stage explicit paths, commit the index, "
        "or push the current branch to a configured remote. Each call needs human approval."
    )
    requires_approval = True
    parameters = {
        "type": "object", "required": ["action"], "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": list(_OPTIONS)},
            "url": {"type": "string", "minLength": 1,
                    "description": "clone only. HTTPS repository URL without credentials, query or fragment."},
            "staged": {"type": "boolean", "default": False, "description": "diff only"},
            "paths": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1},
                      "description": "Required for add. Literal workspace-relative paths."},
            "message": {"type": "string", "minLength": 1, "description": "Required for commit."},
            "remote": {"type": "string", "default": "origin",
                       "description": "push only. Name of a remote already configured in this repository."},
        },
    }

    def __init__(self, github_token: str = "") -> None:
        self._github_token = github_token

    async def _transfer(self, sandbox: Sandbox, command: list[str], env: dict[str, str],
                        args: list[str], urls: list[str]) -> ToolResult:
        options = []
        if self._github_token and urls and all(_github_https(url) for url in urls):
            basic = base64.b64encode(f"x-access-token:{self._github_token}".encode()).decode("ascii")
            env = {**env, "MAS_GIT_AUTH_HEADER": f"Authorization: Basic {basic}",
                   "GIT_TRACE_CURL": "0", "GIT_TRACE_REDACT": "1",
                   "GIT_TRACE2_ENV_VARS": "", "GIT_TRACE2_CONFIG_PARAMS": ""}
            options = ["--config-env=http.https://github.com/.extraHeader=MAS_GIT_AUTH_HEADER",
                       "-c", "http.https://github.com/.followRedirects=false"]
        result = await sandbox.exec([*command, *options, *args], env=env)
        # Remote diagnostics can contain credentials, even when supplied by the user's Git helper.
        action = args[0]
        if result.timed_out:
            return ToolResult(False, f"git {action} timed out; inspect the repository before retrying")
        if result.returncode:
            return ToolResult(False, f"git {action} failed (exit {result.returncode}); "
                              "check the repository, remote access and authentication")
        return ToolResult(True, "Cloned into the workspace" if action == "clone"
                          else f"Pushed current branch to {args[-2]}")

    async def run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult:
        try:
            action = kwargs.pop("action", None)
            if not isinstance(action, str) or action not in _OPTIONS:
                raise ValueError("action must be one of " + ", ".join(_OPTIONS))
            unknown = kwargs.keys() - _OPTIONS[action]
            if unknown:
                raise ValueError(f"unexpected arguments for {action}: {', '.join(sorted(unknown))}")
            env = {"LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"}
            if action == "clone":
                url = kwargs.get("url")
                if _https_url(url) is None:
                    raise ValueError("clone requires an HTTPS URL without credentials, query or fragment")
                if sandbox.list_dir("."):
                    raise ValueError("clone requires an empty workspace")
                return await self._transfer(sandbox, ["git"], env,
                                            ["clone", "--no-recurse-submodules", "--", url, "."], [url])
            # Prevent discovery of a parent repository (e.g. workspaces/ inside the project).
            git_dir = sandbox.resolve(".git")
            if sandbox.exists(".git"):
                sandbox.list_dir(".git")  # reject gitfiles pointing at another checkout
                if sandbox.exists(".git/commondir"):
                    raise ValueError("use a standalone workspace repository")
            elif action != "init":
                raise ValueError("workspace has no .git directory; use init first")
            command = ["git", "--no-pager", "--literal-pathspecs",
                       f"--git-dir={git_dir}", f"--work-tree={sandbox.resolve('.')}",
                       "-c", "color.ui=false", "-c", "core.abbrev=no"]
            if action == "push":
                remote = kwargs.get("remote", "origin")
                if not isinstance(remote, str) or not re.fullmatch(r"[\w][\w.-]*", remote):
                    raise ValueError("remote must be a configured name, e.g. origin")
                urls = await sandbox.exec([*command, "remote", "get-url", "--push", "--all", remote], env=env)
                if urls.timed_out or urls.returncode or not urls.stdout.strip():
                    return ToolResult(False, f"git: could not resolve push URLs for remote {remote!r}")
                return await self._transfer(sandbox, command, env,
                                            ["push", "--no-follow-tags", "--recurse-submodules=no",
                                             remote, "HEAD"], urls.stdout.splitlines())

            args = self._local_args(sandbox, action, kwargs)
            result = await sandbox.exec([*command, *args], env=env)
            return self._local_result(action, result)
        except NotImplementedError:
            return ToolResult(False, "git: this sandbox does not support exec")
        except (OSError, TypeError, ValueError) as exc:
            return ToolResult(False, f"git: {exc}")

    @staticmethod
    def _local_args(sandbox: Sandbox, action: str, options: dict[str, Any]) -> list[str]:
        if action == "add":
            paths = options.get("paths")
            if not isinstance(paths, list) or not paths:
                raise ValueError("add requires a nonempty list of paths")
            for path in paths:
                if not isinstance(path, str) or not path or Path(path).anchor:
                    raise ValueError("paths must be nonempty workspace-relative strings")
                sandbox.resolve(path)
            return ["add", "--", *paths]
        if action == "commit":
            message = options.get("message")
            if not isinstance(message, str) or not message.strip() or "\0" in message:
                raise ValueError("commit requires a nonempty message without NUL characters")
            return ["commit", "-m", message]
        if action == "diff":
            staged = options.get("staged", False)
            if not isinstance(staged, bool):
                raise ValueError("staged must be a boolean")
            return ["diff", "--no-ext-diff", "--no-textconv", *(["--cached"] if staged else [])]
        if action == "status":
            return ["status", "--short"]
        if action == "log":
            return ["log", "-10", "--oneline", "--no-decorate"]
        return ["init"]

    @staticmethod
    def _local_result(action: str, result: ExecResult) -> ToolResult:
        output = "\n".join(part.rstrip() for part in (result.stdout, result.stderr) if part.strip())
        if result.timed_out:
            return ToolResult(False, f"git {action} timed out\n{output}".rstrip())
        if result.returncode:
            return ToolResult(False, f"git {action} exited {result.returncode}\n{output}".rstrip())
        refs = {}
        if action == "commit":
            # Read this process's commit summary. HEAD can change between two commands.
            match = re.search(r"^\[[^\n]+ ([0-9a-f]{40}|[0-9a-f]{64})\] ", result.stdout, re.M)
            if not match:
                return ToolResult(False, "git commit succeeded but returned no commit ID; check git log")
            refs["commit"] = match[1]
        if not output:
            output = "Staged requested paths" if action == "add" else f"git {action}: no changes"
        return ToolResult(True, output, refs=refs)
