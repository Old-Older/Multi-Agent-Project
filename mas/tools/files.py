"""Text file tools; all filesystem access is delegated to the supplied Sandbox."""
from __future__ import annotations

import difflib
import json
import re
from typing import Any

from mas.sandbox.base import Sandbox
from mas.tools.base import Tool, ToolResult


# What one read_file call returns at most. The worker clips tool output at tool_output_max_chars (4000),
# and a cut that loses the "keep reading" note would leave the model guessing, so the window is smaller.
READ_WINDOW = 3500

# What one write_file call should carry at most. A reply ends at the model's output limit (8192 tokens with
# DeepSeek, about 26 000 characters of arguments); a call that is cut off there cannot be parsed and is lost whole.
WRITE_PART_CHARS = 12_000

_CUT_PATH = re.compile(r'"path"\s*:\s*"((?:[^"\\]|\\.)*)"')
_CUT_CONTENT = re.compile(r'"content"\s*:\s*"')


def cut_write(raw: str) -> tuple[str, str, bool] | None:
    """What arrived of a write_file call whose JSON stops inside `content`: (path, the content so far, append).

    A reply that ends at the output limit stops in the middle of the content string. None unless `path` is complete
    and comes before `content`, and `content` is still open where `raw` ends. The content is cut back to its last
    complete line when that keeps at least half of it, so that what follows can start on a new line."""
    path, start = _CUT_PATH.search(raw), _CUT_CONTENT.search(raw)
    if path is None or start is None or path.start() > start.start():
        return None
    body, escaped = raw[start.end():], False
    for char in body:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return None                            # the string was closed: something else is wrong with this call
    if escaped:
        body = body[:-1]                           # half an escape sequence
    body = re.sub(r"\\u[0-9a-fA-F]{0,3}$", "", body)
    try:
        name, content = json.loads(f'"{path.group(1)}"'), json.loads(f'"{body}"')
    except ValueError:
        return None
    if not name or not content:
        return None
    line_end = content.rfind("\n") + 1
    if line_end and line_end >= len(content) // 2:
        content = content[:line_end]
    return name, content, bool(re.search(r'"append"\s*:\s*true', raw[:start.start()]))


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
                if name == "append":
                    if type(value) is not bool:
                        raise ValueError("append must be true or false")
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
    description = ("Create or overwrite a UTF-8 text file, creating parent directories as needed. One reply can carry only "
                   f"so much: write a file longer than about {WRITE_PART_CHARS} characters in parts, the first part with a "
                   "plain call and each further part with `append` set to true (the answer says how long the file is "
                   "now). Of a call that is cut off at the output limit, at most the part that arrived is kept, and only "
                   "for a new file.")
    parameters = _parameters(content=True)
    parameters["properties"] = {**parameters["properties"], "append": {
        "type": "boolean", "default": False,
        "description": "Add `content` to the end of the existing file instead of replacing the file."}}

    def _run(self, sandbox: Sandbox, *, path: str, content: str, append: bool = False) -> ToolResult:
        relative = sandbox.resolve(path).relative_to(sandbox.resolve(".")).as_posix()
        if not append:
            sandbox.write_text(path, content)
            return ToolResult(True, f"Wrote {relative}", files_written=[relative])
        if not sandbox.exists(path):
            raise ValueError(f"cannot append: {relative} does not exist yet; write its first part without append")
        text = sandbox.read_text(path) + content
        sandbox.write_text(path, text)
        return ToolResult(True, f"Appended {len(content)} characters to {relative}: it now has {len(text)} characters, "
                                f"{len(text.splitlines())} lines.", files_written=[relative])


class EditFile(Tool):
    """Replace exact pieces of a file's text, all or nothing, and say what happened.

    Without it a member that wants to change a sentence in a long document has to write the whole file again, or a
    script that patches it; in the fifth real run one lead wrote the same 12 KB patch script ten times and none of its 44
    changes reached the deliverable. Here a change that cannot be made is an error that says why, and nothing is written."""

    name = "edit_file"
    description = ("Change a file by replacing exact pieces of its text, without rewriting it. Give `edits`, a list of "
                   "{old, new} pairs (or just one `old` and `new`): every `old` must occur exactly once in the file, or "
                   "set `all` to replace every occurrence; `new` may be empty to delete. The edits are applied in order; "
                   "if one cannot be applied nothing is changed and the answer says which one and why (with the closest "
                   "line when `old` is not found). On success it says how many edits were made and how long the file is "
                   "now. Use it instead of writing the whole file again or a script that patches the file: an edit it "
                   "does not confirm was not made.")
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "description": "Path relative to this agent's workspace."},
            "old": {"type": "string", "description": "The text to replace (for a single edit)."},
            "new": {"type": "string", "description": "The text to put in its place (for a single edit)."},
            "edits": {"type": "array", "description": "Several edits, applied in order.", "items": {
                "type": "object",
                "properties": {"old": {"type": "string"}, "new": {"type": "string"}, "all": {"type": "boolean"}},
                "required": ["old", "new"], "additionalProperties": False}},
            "all": {"type": "boolean", "description": "For a single edit: replace every occurrence."},
        },
        "required": ["path"], "additionalProperties": False,
    }

    async def run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult:
        try:
            return self._run(sandbox, **kwargs)
        except (OSError, ValueError, TypeError) as exc:
            return ToolResult(False, f"{self.name}: {type(exc).__name__}: {exc}")

    @staticmethod
    def _edits(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        unknown = set(kwargs) - EditFile.parameters["properties"].keys()
        if unknown:
            raise ValueError(f"unknown arguments: {', '.join(sorted(unknown))}")
        if not isinstance(kwargs.get("path"), str) or not kwargs["path"]:
            raise ValueError("path must be a non-empty string")
        edits = kwargs.get("edits")
        if edits is None:
            if "old" not in kwargs or "new" not in kwargs:
                raise ValueError("give `edits`, or `old` and `new`")
            edits = [{"old": kwargs["old"], "new": kwargs["new"], "all": kwargs.get("all", False)}]
        elif "old" in kwargs or "new" in kwargs:
            raise ValueError("give `edits`, or `old` and `new`, not both")
        if not isinstance(edits, list) or not edits:
            raise ValueError("edits must be a non-empty list")
        for n, edit in enumerate(edits, 1):
            if (not isinstance(edit, dict) or not isinstance(edit.get("old"), str) or not isinstance(edit.get("new"), str)
                    or set(edit) - {"old", "new", "all"} or not isinstance(edit.get("all", False), bool)):
                raise ValueError(f"edit {n} must be {{old: text, new: text}} (and optionally all: true or false)")
            if not edit["old"]:
                raise ValueError(f"edit {n}: old must not be empty")
        return edits

    @staticmethod
    def _closest(text: str, old: str) -> str:
        """The line of `text` most like the first line of `old`, to show where an edit that was not found went wrong."""
        wanted = " ".join(old.strip().split("\n")[0].split())[:200]
        lines = [" ".join(line.split()) for line in text.split("\n") if line.strip()]
        found = difflib.get_close_matches(wanted, lines, n=1, cutoff=0.5)
        return f" The closest line in the file is: {found[0][:200]!r}." if found else ""

    def _run(self, sandbox: Sandbox, **kwargs: Any) -> ToolResult:
        edits = self._edits(kwargs)
        path = kwargs["path"]
        relative = sandbox.resolve(path).relative_to(sandbox.resolve(".")).as_posix()
        before = sandbox.read_text(path)
        text = before
        for n, edit in enumerate(edits, 1):
            found = text.count(edit["old"])
            if found == 0:
                return ToolResult(False, f"{self.name}: edit {n} of {len(edits)} not applied: the text to replace is not in "
                                         f"{relative} (it must match exactly, whitespace included; an earlier edit of this "
                                         f"call may have changed it).{self._closest(text, edit['old'])} Nothing was changed.")
            if found > 1 and not edit.get("all", False):
                return ToolResult(False, f"{self.name}: edit {n} of {len(edits)} not applied: the text occurs {found} times in "
                                         f"{relative}. Make `old` longer so that it occurs once, or set all to true. "
                                         "Nothing was changed.")
            text = text.replace(edit["old"], edit["new"])
        sandbox.write_text(path, text)
        if sandbox.read_text(path) != text:                    # the answer must be true: say so if the write did not hold
            return ToolResult(False, f"{self.name}: {relative} does not hold the edited text after writing it")
        return ToolResult(True, f"Applied {len(edits)} edit{'s' if len(edits) != 1 else ''} to {relative}: "
                                f"{len(before)} -> {len(text)} characters, {len(text.splitlines())} lines.",
                          files_written=[relative])


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
