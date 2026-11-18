"""Text file tools; all filesystem access is delegated to the supplied Sandbox."""
from __future__ import annotations

import json
from typing import Any

from mas.sandbox.base import Sandbox
from mas.tools.base import Tool, ToolResult


# What one read_file call returns at most. The worker clips tool output at tool_output_max_chars (4000),
# and a cut that loses the "keep reading" note would leave the model guessing, so the window is smaller.
READ_WINDOW = 3500


def _parameters(*, content: bool = False, optional_path: bool = False) -> dict[str, Any]:
    path: dict[str, Any] = {
        "type": "string", "minLength": 1,
        "description": "Path relative to this agent's workspace.",
    }
    if optional_path:
        path["default"] = "."
    properties = {"path": path}
    required = [] if optional_path else ["path"]
    if content:
        properties["content"] = {"type": "string", "description": "Complete UTF-8 text to write."}
        required.append("content")
    return {"type": "object", "properties": properties,
            "required": required, "additionalProperties": False}


class _FileTool(Tool):
    async def run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult:
        try:
            unknown = set(kwargs) - self.parameters["properties"].keys()
            if unknown:
                raise ValueError(f"unknown arguments: {', '.join(sorted(unknown))}")
            for name in self.parameters["required"]:
                if name not in kwargs:
                    raise ValueError(f"missing required argument: {name}")
            for name, value in kwargs.items():
                if name == "offset":
                    if type(value) is not int or value < 0:
                        raise ValueError("offset must be a non-negative integer")
                    continue
                if not isinstance(value, str):
                    raise TypeError(f"{name} must be a string")
                if name == "path" and not value:
                    raise ValueError("path must not be empty")
            return self._run(sandbox, **kwargs)
        except (OSError, ValueError, TypeError) as exc:
            return ToolResult(False, f"{self.name}: {type(exc).__name__}: {exc}")

    def _run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult:
        raise NotImplementedError


class ReadFile(_FileTool):
    name = "read_file"
    description = ("Read a UTF-8 text file from this agent's workspace. A long file comes back in pieces of "
                   f"{READ_WINDOW} characters: the end of each piece says which offset to pass to read the next one.")
    parameters = _parameters()
    parameters["properties"] = {**parameters["properties"], "offset": {
        "type": "integer", "minimum": 0, "default": 0,
        "description": "Character position to start reading from (to continue a long file)."}}

    def _run(self, sandbox: Sandbox, *, path: str, offset: int = 0) -> ToolResult:
        text = sandbox.read_text(path)
        if offset == 0 and len(text) <= READ_WINDOW:
            return ToolResult(True, text)                      # the usual case: the whole file, unchanged
        if offset >= len(text) and text:
            raise ValueError(f"offset {offset} is past the end of the file ({len(text)} characters)")
        end = min(offset + READ_WINDOW, len(text))
        shown = text[offset:end]
        if end < len(text):
            shown += (f"\n[showing characters {offset}-{end} of {len(text)}; "
                      f"call read_file again with offset={end} to continue]")
        elif offset:
            shown += f"\n[end of file: characters {offset}-{end} of {len(text)}]"
        return ToolResult(True, shown)


class WriteFile(_FileTool):
    name = "write_file"
    description = "Create or overwrite a UTF-8 text file, creating parent directories as needed."
    parameters = _parameters(content=True)

    def _run(self, sandbox: Sandbox, *, path: str, content: str) -> ToolResult:
        relative = sandbox.resolve(path).relative_to(sandbox.resolve(".")).as_posix()
        sandbox.write_text(path, content)
        return ToolResult(True, f"Wrote {relative}", files_written=[relative])


class DeleteFile(_FileTool):
    name = "delete_file"
    description = "Delete one file from this agent's workspace. Requires human approval."
    parameters = _parameters()
    requires_approval = True

    def _run(self, sandbox: Sandbox, *, path: str) -> ToolResult:
        sandbox.delete(path)
        return ToolResult(True, f"Deleted {path}")


class ListFiles(_FileTool):
    name = "list_files"
    description = "List immediate file and directory names as a JSON array; defaults to the workspace root."
    parameters = _parameters(optional_path=True)

    def _run(self, sandbox: Sandbox, *, path: str = ".") -> ToolResult:
        return ToolResult(True, json.dumps(sandbox.list_dir(path), ensure_ascii=False))
