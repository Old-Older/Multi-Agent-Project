"""Per-agent memory (design §8, D13, D5).

Owner: JIAN Yimin.

Two uses of the same records:
  recall()  -> past lessons injected into the worker prompt ("how to do it")
  profile() -> capability profile shown to the Orchestrator ("who should do it")
Neither calls an LLM. The only LLM call is the async failure reflection that
produces Experience.lesson, done by the worker after it has returned.
"""
from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

PROFILE_WINDOW = 20               # the capability profile looks at the latest N experiences
PROFILE_MAX_LESSONS = 3           # ...and shows at most this many recent failure lessons


@dataclass
class Experience:
    task_id: str
    task_goal: str
    tags: list[str]                   # task type, derived from tools used, e.g. ["code", "git"]
    success: bool
    summary: str
    lesson: str = ""                  # empty on success; one sentence on failure
    ts: float = field(default_factory=time.time)


class Memory(ABC):
    @abstractmethod
    def add(self, exp: Experience) -> None: ...

    @abstractmethod
    def recall(self, query: str, k: int = 3) -> list[Experience]:
        """Most relevant past experiences for query (keyword overlap)."""

    @abstractmethod
    def profile(self, max_chars: int = 300) -> str:
        """Success counts per tag plus recent failure lessons, e.g.
        'Recent performance: code 8/10 succeeded, git 3/3 succeeded. Known weak spots: ...'"""


_STOPWORDS = frozenset("a an the to of and or in on for with is it this that please then".split())
_WORD = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")

# Tool name -> task type tag. The eval categories are code | doc | search | file | git.
_TOOL_TAGS = {"run_python": "code", "git": "git", "web_search": "search", "fetch_url": "search",
              "read_file": "file", "write_file": "file", "delete_file": "file", "list_files": "file"}


def tags_for_tools(tool_names: Iterable[str], artifacts: Iterable[str] = ()) -> list[str]:
    """Task type tags from the tools a task used, in order of first use, e.g. ["code", "git"];
    plus "doc" if it wrote a .md / .txt file. No LLM. Unknown tools add no tag."""
    tags = [_TOOL_TAGS[t] for t in tool_names if t in _TOOL_TAGS]
    if any(str(a).lower().endswith((".md", ".txt")) for a in artifacts):
        tags.append("doc")
    return list(dict.fromkeys(tags))


def keywords(text: str) -> set[str]:
    """Words for matching: lower-case ASCII words (without stop words), and for Chinese text
    every pair of neighbouring characters (a single Chinese character is too common to match on)."""
    text = text.lower()
    words = {w for w in _WORD.findall(text) if w not in _STOPWORDS}
    for run in _CJK_RUN.findall(text):
        words |= {run[i:i + 2] for i in range(len(run) - 1)}
    return words


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:max(n - 1, 0)] + "…"


class JsonlMemory(Memory):
    """One JSONL file per agent: <memory_dir>/<agent_id>.jsonl, one Experience per line.

    The file is read again on every call (it holds tens of records, not millions).
    If a task_id appears twice, the later line wins: a worker may first record a failure
    and add the lesson after the asynchronous reflection."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @classmethod
    def for_agent(cls, memory_dir: Path, agent_id: str) -> JsonlMemory:
        return cls(Path(memory_dir) / f"{agent_id}.jsonl")

    def add(self, exp: Experience) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(exp), ensure_ascii=False) + "\n")

    def clear(self) -> None:
        """Forget everything (delete the file). For the eval harness: an experiment that
        must start from an empty memory. Nothing to do if there is no file."""
        self.path.unlink(missing_ok=True)

    def all(self) -> list[Experience]:
        """Every experience, oldest first; a line that cannot be read is skipped."""
        if not self.path.exists():
            return []
        latest: dict[str, Experience] = {}
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                exp = Experience(**json.loads(line))
            except (ValueError, TypeError):
                log.warning("%s line %d is not a valid experience, skipped", self.path, n)
                continue
            latest.pop(exp.task_id, None)                    # a repeated task_id moves to the end
            latest[exp.task_id] = exp
        return list(latest.values())

    def recall(self, query: str, k: int = 3) -> list[Experience]:
        """The k past experiences sharing the most keywords with `query` (goal and tags count
        double, summary and lesson once). An experience with a lesson gets one extra point,
        since lessons are what recall is for; ties go to the newer one. Experiences sharing
        no keyword are not returned."""
        wanted = keywords(query)
        if not wanted or k <= 0:
            return []
        scored = []
        for order, exp in enumerate(self.all()):
            score = (2 * len(wanted & keywords(exp.task_goal + " " + " ".join(exp.tags)))
                     + len(wanted & keywords(exp.summary + " " + exp.lesson)))
            if score:
                scored.append((score + bool(exp.lesson), order, exp))
        scored.sort(key=lambda t: t[:2], reverse=True)
        return [exp for *_, exp in scored[:k]]

    def profile(self, max_chars: int = 300) -> str:
        """e.g. 'Recent performance: code 8/10 succeeded, git 3/3 succeeded. Known weak spots:
        pip install timed out; pages that need JS rendering.' Counts are over the latest
        PROFILE_WINDOW experiences, the weak spots are the lessons of the most recent
        failures. Empty if nothing has been recorded yet. At most `max_chars` long."""
        recent = self.all()[-PROFILE_WINDOW:]
        if not recent:
            return ""
        counts: dict[str, list[int]] = {}
        for exp in recent:
            for tag in exp.tags or ["other"]:
                done, total = counts.setdefault(tag, [0, 0])
                counts[tag] = [done + exp.success, total + 1]
        stats = ", ".join(f"{tag} {done}/{total} succeeded" for tag, (done, total)
                          in sorted(counts.items(), key=lambda kv: (-kv[1][1], kv[0])))
        text = f"Recent performance: {stats}."
        lessons: list[str] = []
        for exp in reversed(recent):
            lesson = " ".join(exp.lesson.split())
            if not exp.success and lesson and lesson not in lessons:
                lessons.append(lesson)
        shown = ""
        for lesson in lessons[:PROFILE_MAX_LESSONS]:
            candidate = shown + ("; " if shown else "") + lesson
            if len(text) + len(" Known weak spots: ") + len(candidate) + 1 <= max_chars:
                shown = candidate                              # one that does not fit is skipped
        if shown:
            text += f" Known weak spots: {shown}."
        return _clip(text, max_chars)
