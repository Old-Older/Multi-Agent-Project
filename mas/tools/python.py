"""Run Python scripts and test modules through the worker's sandbox."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

from mas.sandbox.base import Sandbox
from mas.tools.base import Tool, ToolResult


class RunPython(Tool):
    name = "run_python"
    description = (
        "Run a Python script in the workspace or an installed/workspace module "
        "(e.g. unittest or pytest) with the current Python interpreter. "
        "Supply exactly one of path and module."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1,
                     "description": "Workspace-relative script path."},
            "module": {"type": "string", "minLength": 1,
                       "description": "Dotted Python module name to run with -m."},
            "args": {"type": "array", "items": {"type": "string"},
                     "description": "Arguments to the script or module, one item per argument."},
            "timeout": {"type": "number", "exclusiveMinimum": 0, "default": 60,
                        "description": "Execution timeout in seconds."},
        },
        "oneOf": [{"required": ["path"]}, {"required": ["module"]}],
        "additionalProperties": False,
    }

    async def run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult:
        try:
            unknown = kwargs.keys() - self.parameters["properties"].keys()
            if unknown:
                raise ValueError(f"unknown arguments: {', '.join(sorted(unknown))}")
            if ("path" in kwargs) == ("module" in kwargs):
                raise ValueError("provide exactly one of path and module")
            args = kwargs.get("args", [])
            if not isinstance(args, list) or any(
                not isinstance(arg, str) or "\0" in arg for arg in args
            ):
                raise ValueError("args must be a list of strings without NUL characters")
            timeout = kwargs.get("timeout", 60)
            if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                    or not math.isfinite(timeout) or timeout <= 0):
                raise ValueError("timeout must be a positive finite number of seconds")

            if "path" in kwargs:
                path = kwargs["path"]
                if not isinstance(path, str) or not path or Path(path).anchor:
                    raise ValueError("path must be a nonempty workspace-relative path")
                relative = sandbox.resolve(path).relative_to(sandbox.resolve("."))
                # Spell even a file named "-" as a path, never as Python's stdin shortcut.
                target = ["--", "./" + relative.as_posix()]
            else:
                module = kwargs["module"]
                if not isinstance(module, str) or not all(
                    part.isidentifier() for part in module.split(".")
                ):
                    raise ValueError("module must be a dotted Python module name")
                target = ["-m", module]

            # Flush output before timeouts; LocalSandbox decodes captured streams as UTF-8.
            result = await sandbox.exec(
                [sys.executable, "-u", *target, *args], timeout=timeout,
                env={"PYTHONIOENCODING": "utf-8"},
            )
        except NotImplementedError:
            return ToolResult(False, f"{self.name}: this sandbox does not support exec")
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            return ToolResult(False, f"{self.name}: {type(exc).__name__}: {exc}")

        status = f"exit code {result.returncode}"
        if result.timed_out:
            status = f"timed out after {timeout}s ({status})"
        output = f"{status}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        return ToolResult(not result.timed_out and result.returncode == 0, output)
