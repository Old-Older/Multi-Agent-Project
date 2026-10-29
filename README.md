# Evolutionary Multi-Agent Collaboration System

Course final project. A backend framework where multiple heterogeneous agents chat with humans,
decompose and delegate tasks, run tools inside isolated sandboxes, and learn from past executions.

## Hard constraints (from the spec)

- LLM: DeepSeek or HKGAI only. No OpenAI / Anthropic APIs.
- Outputs: plain text only (`.md` / `.txt`). No PDF / DOCX / PPT handling.
- UI: minimal (CLI, or a simple bot / Gradio / Streamlit text box). Frontend earns no credit.
- Every agent needs its own memory and its own isolated workspace.
- Required tools: web search, file read/write/update/delete, write + run Python, git commit + push.
- Harness must report task completion rate and execution time.

## Deliverables

1. GitHub repo with continuous commits from every member (history is graded).
2. System architecture document: `docs/architecture.md`
3. Test results and performance report: `docs/report.md`
4. Presentation in week 13.

## To be decided (first team meeting)

- Code layout and module boundaries
- Core interfaces: LLM call, Agent, Tool, Message, Memory
- Memory backend: JSON log vs. vector DB
- Sandbox approach: per-agent directory vs. containers
- Ownership of modules between members

## Workflow

- `main` is protected. Work on `feat/<name>-<topic>` branches and merge via PR.
- Small, frequent commits from both members every week.
- Copy `.env.example` to `.env` for API keys. Never commit `.env`.
