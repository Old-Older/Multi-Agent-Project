"""All tunable parameters in one place.

Open items in the design (subtask timeout, Docker vs Local, model choice) are
settings here, so deciding them later never changes an interface.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    # LLM (design §11)
    llm_provider: str = "deepseek"            # "deepseek" | "mock"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    orchestrator_model: str = ""              # empty = same as deepseek_model
    temperature: float = 0.1

    # loop limits (D10, D11, §5)
    max_orchestrator_rounds: int = 8
    max_worker_steps: int = 12
    subtask_timeout_s: float = 180.0          # 待确认
    max_delegation_depth: int = 2
    max_delegations_per_task: int = 2
    max_retries_same_goal: int = 2

    # context sizes (§2.1, §3.1, §6, §8)
    result_summary_max_chars: int = 1500
    board_max_chars: int = 2000
    tool_output_max_chars: int = 4000
    memory_recall_k: int = 3
    profile_max_chars: int = 300

    # sandbox and paths (§9)
    sandbox_backend: str = "local"            # "local" | "docker"   待确认
    docker_image: str = "python:3.11-slim"
    workspaces_dir: Path = Path("workspaces")
    data_dir: Path = Path("data")             # memory/, sessions/, output/ live under here

    # human side (§7)
    auto_hitl: bool = False                   # True = AutoResponder (evaluation)

    # tools
    github_token: str = ""
    search_api_key: str = ""

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
            "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY"),
            "deepseek_base_url": os.getenv("DEEPSEEK_BASE_URL"),
            "deepseek_model": os.getenv("DEEPSEEK_MODEL"),
            "github_token": os.getenv("GITHUB_TOKEN"),
            "search_api_key": os.getenv("SEARCH_API_KEY"),
        }
        values = {k: v for k, v in env.items() if v}
        values.update(overrides)
        known = {f.name for f in fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise TypeError(f"unknown settings: {sorted(unknown)}")
        return cls(**values)  # type: ignore[arg-type]
