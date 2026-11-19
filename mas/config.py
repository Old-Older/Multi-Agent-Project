"""All tunable parameters in one place.

Open items in the design (subtask timeout, Docker vs Local, model choice) are
settings here, so deciding them later never changes an interface.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path


DEFAULT_HKGAI_BASE_URL = "https://api1.hkgai.net/v1"
DEFAULT_HKGAI_MODEL = "t2_hkgai-v3_fp8_1m_e7"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"


@dataclass
class Settings:
    # LLM (design §11)
    llm_provider: str = "hkgai"               # "hkgai" | "deepseek": the two the course allows
    hkgai_api_key: str = ""
    hkgai_base_url: str = DEFAULT_HKGAI_BASE_URL
    hkgai_model: str = DEFAULT_HKGAI_MODEL
    deepseek_api_key: str = ""
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    deepseek_thinking: str = "off"            # "off": ask DeepSeek not to think; "default": leave it to the service
    temperature: float = 0.1

    # loop limits (D10, D11, §5)
    max_worker_steps: int = 30
    subtask_timeout_s: float = 900.0          # one delegated task, human waits excluded
    max_delegation_depth: int = 2
    max_delegations_per_task: int = 2         # a worker's re-delegations of one task
    max_parallel_per_teammate: int = 3        # jobs one teammate works on at the same time for one requester
    max_lead_delegations: int = 16            # the lead of a request delegates more often
    # Nudges that help a member stop once it has enough (a note after many searches, a progress check halfway when
    # nothing has been written). Off for experiments: the budget warning and the tool-less last step stay on.
    early_stop_nudges: bool = True
    research_note_after: int = 6              # searches and page fetches in one task before the first note...
    research_note_every: int = 2              # ...and between the notes after that
    research_max_calls: int = 14              # a hard stop: the 15th search or page fetch of one task is refused (0: no limit)
    max_retries_same_goal: int = 2

    # leading a request (design D18): the lead's own budget, delegated work included
    max_lead_steps: int = 60                  # a lead's ReAct step limit (a worker keeps max_worker_steps)
    lead_timeout_s: float = 2400.0            # budget of the lead's whole task, delegated work included

    # time budget of one request (0: none). 270 s is the "fast" configuration chosen in round 11 (docs/report.md §11);
    # the "full" configuration is 900 / research_max_calls 28 / finish_not_before 0.
    # Every member shares it: members stop starting new work `worker_wrapup_s` /
    # `lead_wrapup_s` before it ends and hand in what they have, nobody starts a delegation with less than
    # `min_delegation_s` left, and `budget_grace_s` after it ends whatever still runs is cut off.
    request_budget_s: float = 270.0
    lead_wrapup_s: float = 30.0
    worker_wrapup_s: float = 50.0
    min_delegation_s: float = 80.0
    budget_grace_s: float = 45.0
    finish_not_before: float = 0.5            # a lead that hands in with less than this share of the budget used is sent back (0: off)
    review_reserve_s: float = 120.0           # when a review does not pass, the time left is topped up to this, for the fix and the re-check
    max_review_extensions: int = 2            # how often that can happen in one request (0: never)
    requirements_check: bool = True           # list what the request explicitly requires; the lead reports each one before it hands in
    max_requirements: int = 12
    max_review_rounds: int = 3                # reviews of the same file by the same reviewer in one request (0: no limit)
    lead_summary_max_chars: int = 6000        # the message the human reads is not cut as short as a teammate's report
    review_final: bool = True                 # a lead may not hand in a deliverable no reviewer has seen (needs closing_check)
    closing_check: bool = True                # before a lead's final answer, one more step to check the loose ends

    # context sizes (§2.1, §3.1, §6, §8)
    result_summary_max_chars: int = 1500
    board_max_chars: int = 2000
    tool_output_max_chars: int = 4000
    memory_recall_k: int = 3
    profile_max_chars: int = 300

    # sandbox and paths (§9)
    sandbox_backend: str = "local"            # "local" | "docker"   to be confirmed
    docker_image: str = "python:3.11-slim"
    workspaces_dir: Path = Path("workspaces")
    data_dir: Path = Path("data")             # memory/, sessions/, output/ live under here

    # human side (§7)
    auto_hitl: bool = False                   # True = AutoResponder (evaluation)

    # tools
    github_token: str = ""
    # Which service web_search and fetch_url may use besides this machine and the keyless search. "auto": DeepSeek's own
    # search and fetch (same key) while the DeepSeek model is in use, nothing else (the HKGAI model: the course's search
    # service is not known yet, so only the keyless search). "deepseek" forces DeepSeek's, "keyless" forbids any key.
    # Whichever is chosen, a search that cannot be answered falls back to the keyless one.
    search_provider: str = "auto"

    def __post_init__(self) -> None:
        if self.search_provider not in ("auto", "deepseek", "keyless"):
            raise ValueError(f"search_provider must be auto, deepseek or keyless, not {self.search_provider!r}")

    def deepseek_search_key(self) -> str:
        """The DeepSeek key that web_search and fetch_url may use, or "" when the setting does not allow it. It is never
        used for search while the HKGAI model is the one in use."""
        mode = self.search_provider
        allowed = mode == "deepseek" or (mode == "auto" and self.llm_provider == "deepseek")
        return self.deepseek_api_key if allowed else ""

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @classmethod
    def from_env(cls, **overrides: object) -> Settings:
        """Read from environment variables (see .env.example), then apply overrides."""
        env = {
            "llm_provider": os.getenv("LLM_PROVIDER"),
            "hkgai_api_key": os.getenv("HKGAI_API_KEY"),
            "hkgai_base_url": os.getenv("HKGAI_BASE_URL"),
            "hkgai_model": os.getenv("HKGAI_MODEL"),
            "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY"),
            "deepseek_base_url": os.getenv("DEEPSEEK_BASE_URL"),
            "deepseek_model": os.getenv("DEEPSEEK_MODEL"),
            "deepseek_thinking": os.getenv("DEEPSEEK_THINKING"),
            "github_token": os.getenv("GITHUB_TOKEN"),
            "search_provider": os.getenv("SEARCH_PROVIDER"),
        }
        values = {k: v for k, v in env.items() if v}
        nudges = os.getenv("EARLY_STOP_NUDGES")
        if nudges is not None:
            values["early_stop_nudges"] = nudges.strip().lower() not in ("0", "false", "no", "off", "")
        budget = os.getenv("REQUEST_BUDGET_S")
        if budget:
            values["request_budget_s"] = float(budget)
        values.update(overrides)
        known = {f.name for f in fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise TypeError(f"unknown settings: {sorted(unknown)}")
        return cls(**values)  # type: ignore[arg-type]
