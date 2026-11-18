<p align="right"><b>English</b> | <a href="README.zh-CN.md">简体中文</a></p>

# Evolutionary Multi-Agent Collaboration System

A backend framework where several agents with different roles talk to a human, split a task up
among themselves, run tools in private workspaces, and learn from earlier tasks. It is the final
project of HKUST MAIE5221 (NLP).

You describe a **team** (who is in it and what each member is responsible for) in a Markdown file.
When you give the team a request, one member **leads** it: asks you questions when something is
unclear, hands parts of the work to teammates, checks the results and reports back. Every agent has
its own workspace and its own memory.

## Contents

- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [Requirements and setup](#requirements-and-setup)
- [Running it](#running-it)
- [Defining your own team](#defining-your-own-team)
- [What a run leaves behind](#what-a-run-leaves-behind)
- [Configuration](#configuration)
- [Tests](#tests)
- [Documentation](#documentation)
- [Project rules and workflow](#project-rules-and-workflow)
- [Status](#status)

## How it works

```
 you ──"Build a booking system"──▶ group chat (message bus)
                                        │
                              RequestTracker        bookkeeping only, no LLM: opens a request,
                                        │           handles /status and /cancel, collects files,
                                        │           records the outcome
                              LeadSelector          one LLM call picks the lead (cached per session,
                                        │           falls back to the first member of the team)
                                        ▼
                                 the lead (a WorkerAgent)
              ┌─────────────────────────┼──────────────────────────┐
         ask_human                 call_<teammate>             its own tools
     (asks you in the chat)    (delegates through the Router)   (files, Python, web, git)
                                        │
                          teammates work in their own sandboxes,
                          and may delegate or ask you in turn
```

- **Team, not a boss.** There is no fixed coordinator. The lead is chosen per request, so a different
  team or a different request needs no code change. Follow-up requests in the same chat keep the lead.
- **Router.** All delegation goes through one piece of plain code that enforces limits (depth, cycles,
  retries, timeouts), keeps the task state table, hands files from one workspace to another, and
  routes questions to the human. It never calls an LLM.
- **Human in the loop.** Agents ask you for clarification and before risky actions (deleting files,
  `git` operations). `/cancel` stops a request; agents check for cancellation at every step.
- **Memory.** Each agent keeps a JSONL log of its tasks and lessons from failures. Relevant lessons are
  recalled when a similar task starts, and a short performance profile of each teammate is shown to
  whoever decides whom to delegate to.
- **Isolation.** Every agent has its own workspace directory (`workspaces/<agent>/`); files only move
  between agents through the Router.
- **Tools.** `read_file`, `write_file`, `delete_file`, `list_files`, `run_python`, `web_search`
  (Brave Search when you give it a key, otherwise a keyless stop-gap search), `fetch_url`, `git` (clone, add, commit, push; each call needs your approval).
- **LLM.** The course HKGAI gateway (default) or DeepSeek, the two the course allows; both are
  OpenAI-compatible chat endpoints. OpenAI and Anthropic APIs are not allowed.

## Repository layout

```
.
├── mas/                       the system
│   ├── __main__.py            command line entry: python -m mas
│   ├── app.py                 build_system(): wires everything together; build_tools()
│   ├── config.py              Settings: every tunable limit and path in one place
│   ├── team.py                loads a team from a role file
│   ├── scenario.py            loads a scenario and posts its tasks one after another
│   ├── demo.py                offline demo (stand-in LLM and workers, no API key)
│   ├── core/
│   │   ├── message.py         Message and payload types, channels
│   │   ├── bus.py             message bus (in memory)
│   │   ├── router.py          delegation, limits, files, human questions, cancel (no LLM)
│   │   ├── state.py           task state table
│   │   ├── board.py           shared session board (progress, files, the human's words)
│   │   ├── requests.py        RequestTracker: one request from arrival to final reply
│   │   ├── lead.py            LeadSelector: who leads a request
│   │   ├── human.py           command line (CliHumanIO) and AutoResponder
│   │   └── transcript.py      the whole conversation as a Markdown file
│   ├── agents/
│   │   ├── base.py            Agent base class (messages, status, asking the human)
│   │   ├── worker.py          WorkerAgent: ReAct loop, delegation, approval, memory
│   │   ├── roles.py           RoleConfig, and a sample team for the demo and tests
│   │   └── virtual_tools.py   schemas of call_<teammate>, decline, read_group, ask_human
│   ├── tools/                 files, Python, web search and fetch, git
│   ├── sandbox/               per-agent workspace (LocalSandbox; DockerSandbox is a stub)
│   ├── memory/                JsonlMemory: add, recall, capability profile
│   ├── llm/                   HKGAIClient, DeepSeekClient, MockLLM, the LLMClient contract
│   └── eval/                  evaluation harness, simulated human, grader (python -m mas.eval)
├── tests/                     unit and end-to-end tests (python -m unittest)
├── examples/                  small runnable examples (sandbox, execution tools, HKGAI chat)
├── docs/                      design decisions, interfaces, architecture, report, hand-over notes
├── code_tour.html             animated walk through the code (open in a browser)
├── pyproject.toml             package metadata and dependencies
├── .env.example               template for your API keys
└── README.md / README.zh-CN.md
```

At run time the system also creates `workspaces/` (one directory per agent) and `data/` (memory,
output, transcripts, log). Both are git-ignored.

## Requirements and setup

- Python **3.10 or newer**
- `git` on your `PATH` (only if agents use the git tool)
- An **HKGAI API key** from the course, or a **DeepSeek API key** (for real runs; the demo needs none)
- Optional: a [Brave Search](https://brave.com/search/api/) API key for better `web_search` results
  (search works without one), and a GitHub token for pushing

```bash
git clone https://github.com/Old-Older/Multi-Agent-Project.git
cd Multi-Agent-Project

python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
python -m pip install -e .

cp .env.example .env                # then edit .env
```

`.env` (never commit it):

| Variable | Needed for | Notes |
|---|---|---|
| `LLM_PROVIDER` | optional | `hkgai` (default) or `deepseek`; `--llm` on the command line overrides it |
| `HKGAI_API_KEY` | real runs with `hkgai` | key for the course gateway |
| `HKGAI_BASE_URL`, `HKGAI_MODEL` | optional | default `https://api1.hkgai.net/v1` and `t2_hkgai-v3_fp8_1m_e7` |
| `DEEPSEEK_API_KEY` | real runs with `deepseek` | your DeepSeek key |
| `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` | optional | default `https://api.deepseek.com` and `deepseek-chat` |
| `DEEPSEEK_THINKING` | optional | `off` (default) asks DeepSeek not to think before answering: faster, and the agents call tools at every step; `default` leaves it to the service |
| `SEARCH_API_KEY` | optional | Brave Search token. Without it `web_search` uses a keyless stop-gap (DuckDuckGo and others via `ddgs`: no key or account, but slower and unreliable, so some searches fail and the agents carry on without them); with it Brave is used first, and the stop-gap takes over if Brave refuses or is down |
| `GITHUB_TOKEN` | `git push` to GitHub | sent only to github.com over HTTPS |

## Running it

**1. Try it without a key.** A stand-in LLM and stand-in workers drive the real bus, router, request
tracker and command line:

```bash
python -m mas --demo
```

Type `write a python script and a document`, `run the tests`, `write a script and push it` (asks for
your approval), `/status`, `/cancel` or `/dm researcher find out about decorators`.

**2. Run a team of your own** (needs a key for the LLM you chose):

```bash
python -m mas --team path/to/01_role_initialization.md      # the file, or the folder that holds it
```

**3. Run a scenario**: a folder with a role file and task files (the course's test data has this shape).
The first task is posted, and when it has ended the next one is posted to the same group, so the team
keeps its context. You answer the team's questions as they come; type `/quit` to finish.

```bash
python -m mas --scenario "scenario_1_software_engineering 2"
python -m mas --scenario "scenario_1_software_engineering 2" --auto     # unattended
```

Add `--llm deepseek` to use DeepSeek instead of the course gateway.

With `--auto` an `AutoResponder` answers every question with a fixed default ("proceed as described",
"yes", ...) and the run ends after the last task.

Command line options:

| Option | Meaning |
|---|---|
| `--demo` | the offline demo (every start is clean unless `--keep`) |
| `--team PATH` | the team: a role file or a folder containing `01_role_initialization.md` |
| `--scenario DIR` | a scenario folder: team and tasks |
| `--llm hkgai\|deepseek` | which LLM to use (default: `LLM_PROVIDER`, else `hkgai`) |
| `--auto` | unattended; needs `--scenario` |
| `--data-dir DIR` | where memory, output and transcripts go (default `./data`) |
| `--keep`, `--delay S` | demo only |
| `-v` | also print the log on the screen (it always goes to `<data-dir>/mas.log`) |

Commands you can type while it runs:

| Command | What it does |
|---|---|
| *text* | say it to the team (it becomes a request, or an addition to the running one) |
| `@dev text` | give a task straight to one agent |
| `/dm <agent> <text>` | private chat with one agent |
| `/status` | show where the current tasks are |
| `/cancel`, `/cancel <agent>` | cancel the running request / the tasks in a private chat |
| `/reply <id> <answer>` | answer a question (`/reply <answer>` when only one is open) |
| `/help`, `/quit` | |

## Defining your own team

A team file is Markdown in the format of the course's `01_role_initialization.md`: a table fixes the
order of the members, and each member has a heading `## Role name (agent_id)` followed by a fenced block
with their prompt.

````markdown
| Agent ID | Role |
|---|---|
| `lead` | Technical Lead |
| `dev` | Software Developer |

## Technical Lead (lead)

```text
You are the technical lead of a software development team. You are responsible for ...
```

## Software Developer (dev)

```text
You are the software developer on a software development team. You are responsible for ...
```
````

Any number of members works. The first one is the fallback lead. Every member gets all eight tools.
A scenario folder adds task files (`02_task_1.md`, `03_task_2.md`, ...), each with the human's words
in a fenced block.

## What a run leaves behind

| Path | Content |
|---|---|
| `data/transcripts/<scenario>-<time>.md` | the whole conversation: what you said, who led, who delegated what, what the team asked you and what you answered, every result, how each request ended, and a summary table. Rewritten whenever a request ends, so a crash loses nothing. |
| `data/output/<request>-<time>/` | the deliverables of each request, collected from the agents' workspaces |
| `data/memory/<agent>.jsonl` | each agent's memory |
| `workspaces/<agent>/` | each agent's private files |
| `data/mas.log` | log, with stack traces of internal errors |

## Configuration

Every limit is a field of `Settings` in `mas/config.py`. The ones you may want to change:

| Setting | Default | Meaning |
|---|---|---|
| `max_worker_steps` | 30 | ReAct steps of a worker for one task |
| `max_lead_steps` | 40 | ReAct steps of the lead of a request |
| `subtask_timeout_s` | 900 | time limit for one delegated task (waiting for a human does not count) |
| `lead_timeout_s` | 2400 | time limit for a whole request |
| `max_delegation_depth`, `max_delegations_per_task`, `max_retries_same_goal` | 2, 2, 2 | guards against runaway delegation (a worker re-delegating one task, same goal retried) |
| `max_lead_delegations` | 16 | how many times the lead of a request may delegate |
| `early_stop_nudges`, `research_note_after`, `research_note_every` | on, 12, 6 | reminders that help a member stop once it has enough; `EARLY_STOP_NUDGES=0` turns them off |
| `memory_recall_k` | 3 | lessons recalled when a task starts |
| `sandbox_backend` | `local` | `docker` is not implemented yet |

> `LocalSandbox` runs commands with your own user's permissions; it separates the agents' files but is
> not a security boundary. Do not run an untrusted team on a machine you care about.

## Tests

```bash
python -m unittest                      # everything
python -m unittest tests.test_lead      # one module
```

The tests need no API key: the LLM is scripted (`MockLLM`). `tests/test_lead.py`,
`tests/test_requests.py` and `tests/test_scenario.py` run whole systems with real workspaces.

## Documentation

| Document | What is in it |
|---|---|
| [`code_tour.html`](code_tour.html) | animated walk through the code, one chapter per module |
| [`docs/design_decisions.md`](docs/design_decisions.md) | the design decisions with their reasons (D1 to D18), and which are still current |
| [`docs/interfaces.md`](docs/interfaces.md) | the interface of each module, who owns it, how a request flows |
| [`docs/README.md`](docs/README.md) | index of the documents, and which ones describe the code as it is today |
| [`docs/architecture.md`](docs/architecture.md) ([中文](docs/architecture.zh-CN.md)) | system architecture: routing and delegation, human in the loop, memory, sandboxes, tools |
| [`docs/report.md`](docs/report.md) | test results and performance report, phase by phase |
| [`docs/sandbox_tools_handoff.md`](docs/sandbox_tools_handoff.md), [`docs/execution_tools_handoff.md`](docs/execution_tools_handoff.md) | the sandbox, the file tools, and the Python / web / git tools |
| [`docs/team_notes.md`](docs/team_notes.md) | interface changes announced between the two members |

## Project rules and workflow

From the course specification:

- LLM: the course HKGAI (or DeepSeek) gateway only. No OpenAI or Anthropic API.
- Documents and outputs are plain text (`.md`, `.txt`) or code; no PDF, Word or PowerPoint handling.
- The UI is minimal: command line, a bot, or a simple text box.
- Every agent has its own memory and its own workspace.
- The harness reports the task completion rate and the execution time.

Workflow: `main` is protected; work on `feat/<name>-<topic>` branches and merge by pull request.
Commit small and often, from both members, every week; the history is graded.

## Status

Working: messaging, routing, task state, session board, human in the loop, per-agent memory with
failure lessons, workers with eight tools, lead selection and delegation, team and scenario loading,
transcript export, unattended runs.

Not finished: the Docker sandbox, and the evaluation on all scenarios. The evaluation harness exists
(`python -m mas.eval`), but real runs have only been made on scenario 3 (first: 0 of 2 requests completed; after
fixes: 2 of 2, 83% of sub-tasks, about 26 minutes per request, graded 7.0/10 by a model), so there are no reliable completion-rate or timing results yet; see
[`docs/report.md`](docs/report.md) for exactly what has been measured.
