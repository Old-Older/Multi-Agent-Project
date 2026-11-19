"""Grading a finished task with a model.

The course grades by giving the whole dialogue and the outputs to a model. This does the same
for our own runs, so that a task's quality is a number in the report and not just "the system did
not crash". It reads the task, what happened while the team worked on it, and the files it
delivered, and answers whether the request was met.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from mas.llm.base import LLMClient

log = logging.getLogger(__name__)

# What the grader is shown. The limits are only there so that one call fits the model's context (a file is about 3 to 4
# characters a token): every delivered file of the runs so far (the largest is 42,000 characters) is shown whole.
MAX_DIALOGUE_CHARS = 60000
MAX_FILE_CHARS = 60000
MAX_FILES_CHARS = 160000
_TEXT_SUFFIXES = {".md", ".txt", ".html", ".htm", ".py", ".json", ".csv", ".js", ".css", ".yaml", ".yml", ".toml"}

_SYSTEM = """You are a strict grader of the work of a team of AI agents. You are given the request a human \
made, the conversation of the team while it worked on that request, and the files it delivered. Decide \
whether the request was met. First list the concrete requirements stated or clearly implied by the request \
(including every format, audience and content requirement), and mark each one as met or not met from the \
evidence in the files and the conversation, not from what the team claims. Be strict: a claim without the \
file to back it up is not met, and so is a deliverable that is empty, a placeholder or only an outline.

Reply with ONE JSON object and nothing else:
{"requirements": [{"item": "...", "met": true}], "passed": true, "score": 7, "notes": "two or three sentences"}
"passed" is true only if all the important requirements are met. "score" is an integer from 1 to 10.

A line of the form [... N characters of this file are not shown to you: the reader omitted them to save space ...] (or \
"(earlier part of the conversation not shown)") means that YOU are not shown that part. It says nothing about the \
delivered file, which is complete: never mark a requirement as not met, or a file as truncated or unfinished, because of \
such a line. Judge from what you can see, and say in "notes" if the part you cannot see stopped you from checking \
something."""


@dataclass
class Verdict:
    passed: bool | None               # None: the grader gave no usable answer
    score: int | None
    notes: str
    requirements: list[dict]


def _shown(text: str, limit: int) -> str:
    """`text` if it fits, else its beginning and its end with a line that says plainly that the middle is not shown to the
    grader (the file itself is whole)."""
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.7), max(0, limit - int(limit * 0.7))
    omitted = len(text) - head - tail
    return (text[:head] + f"\n[... {omitted} characters of this file are not shown to you: the reader omitted them to save "
            f"space; the delivered file is complete ...]\n" + (text[-tail:] if tail else ""))


def read_deliverables(output_dir: str | Path) -> dict[str, str]:
    """The text of the delivered files by file name (whole unless very long: see _shown). Binary files are only named."""
    out: dict[str, str] = {}
    folder = Path(output_dir) if output_dir else None
    if folder is None or not folder.is_dir():
        return out
    budget = MAX_FILES_CHARS
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        name = path.relative_to(folder).as_posix()
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            out[name] = "(not a text file)"
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        shown = _shown(text, max(500, min(MAX_FILE_CHARS, budget)))
        budget -= min(len(text), MAX_FILE_CHARS)
        out[name] = shown
    return out


def parse_verdict(text: str) -> Verdict:
    """Pull the JSON object out of a reply (it may be fenced or have words around it)."""
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            passed = data.get("passed")
            score = data.get("score")
            reqs = data.get("requirements")
            return Verdict(passed if isinstance(passed, bool) else None,
                           score if isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 10 else None,
                           str(data.get("notes") or "")[:600],
                           [r for r in reqs if isinstance(r, dict)] if isinstance(reqs, list) else [])
        except (ValueError, TypeError):
            pass
    return Verdict(None, None, "the grader did not return a usable verdict", [])


async def judge_task(llm: LLMClient, request: str, dialogue: str, deliverables: dict[str, str]) -> Verdict:
    files = "\n\n".join(f"### {name}\n{text}" for name, text in deliverables.items()) or "(no files were delivered)"
    if len(dialogue) > MAX_DIALOGUE_CHARS:
        dialogue = "(earlier part of the conversation not shown)\n" + dialogue[-MAX_DIALOGUE_CHARS:]
    try:
        response = await llm.chat([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"REQUEST:\n{request}\n\nCONVERSATION:\n{dialogue or '(nothing)'}\n\n"
                                        f"DELIVERED FILES:\n{files}"},
        ], temperature=0.0)
    except Exception:
        log.warning("The grader failed", exc_info=True)
        return Verdict(None, None, "the grader call failed", [])
    return parse_verdict(response.text)
