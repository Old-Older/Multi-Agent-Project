<p align="right"><b>English</b> | <a href="architecture.zh-CN.md">简体中文</a></p>

# System Architecture

This document describes the system **as it is implemented**. It is the architecture deliverable of the
course. The reasoning behind each choice, including the ones we later replaced, is in
[`design_decisions.md`](design_decisions.md); the exact interfaces are in [`interfaces.md`](interfaces.md).

Contents: [1 Overview](#1-overview) · [2 Components](#2-components) ·
[3 Communication](#3-communication-topologies) · [4 Routing and delegation](#4-routing-and-delegation) ·
[5 Human in the loop](#5-human-in-the-loop) · [6 Memory and evolution](#6-memory-and-evolution) ·
[7 Sandboxes](#7-sandboxes-and-workspace-isolation) · [8 Tools](#8-tools) ·
[9 Shared context and transcript](#9-shared-context-and-transcript) · [10 Evaluation](#10-evaluation) ·
[11 LLM backends](#11-llm-backends) · [12 Data layout](#12-configuration-and-data-layout) ·
[13 Limitations](#13-limitations)

## 1. Overview

The user describes a **team** in a Markdown file: who is in it and what each member is responsible for.
Nothing about the roles is fixed in code. A human talks to the team in a group chat or in private chats.
For each request one member of the team **leads**: it clarifies what is wanted, splits the work, delegates
to teammates, checks what comes back and reports. Each agent has its own workspace, its own tools and its
own persistent memory.

```
  human ──────────────▶  message bus (group chat, private chats)
                            │  every message is seen by observers:
                            │    Router (results, human answers)   SessionBoard (shared progress)
                            │    RequestTracker (new requests)     Transcript (the whole dialogue)
                            ▼
  RequestTracker ── LeadSelector ──▶  the lead (a WorkerAgent)
   (bookkeeping, no LLM)  (1 LLM call,      │
                           cached)          ├─ ask_human ──▶ human
                                            ├─ call_<teammate> ──▶ Router.dispatch ──▶ teammate (a WorkerAgent)
                                            └─ its own tools ──▶ its Sandbox (private workspace)
```

Design principles:

1. **Coordination is done by team members, not by a hidden scheduler.** What the code does around the
   LLMs (routing, limits, state, files, bookkeeping) is plain deterministic code.
2. **One code path for delegation.** Every delegation, whoever makes it and wherever it is made, goes
   through `Router.dispatch`, so limits, state, file hand-over and statistics cannot be bypassed.
3. **Failures are observations, not exceptions.** A failed tool, a refused call or a failed teammate is
   returned to the LLM that made the call, which decides what to do. Nothing crashes a run.
4. **Everything evaluation needs is recorded by code**, never taken from an LLM's description of itself.

## 2. Components

| Component | File | Role | Calls an LLM? |
|---|---|---|---|
| `MessageBus` / `InMemoryBus` | `mas/core/bus.py` | channels, history, observers | no |
| `Router` | `mas/core/router.py` | delegation, limits, files, human questions, cancel | no |
| `StateTable` | `mas/core/state.py` | the state of every task | no |
| `SessionBoard` | `mas/core/board.py` | shared progress of a session, built by code | no |
| `RequestTracker` | `mas/core/requests.py` | one request from arrival to final reply; `/status`, `/cancel` | no |
| `LeadSelector` | `mas/core/lead.py` | picks the lead of a request | once per session |
| `WorkerAgent` | `mas/agents/worker.py` | a team member: ReAct loop, tools, delegation, memory | yes |
| `Agent` | `mas/agents/base.py` | message handling, status, asking the human | no |
| `HumanIO` | `mas/core/human.py` | command line (`CliHumanIO`), unattended (`AutoResponder`) | no |
| `Transcript` | `mas/core/transcript.py` | whole conversation as Markdown | no |
| `Sandbox` | `mas/sandbox/` | a private workspace and process execution | no |
| `JsonlMemory` | `mas/memory/base.py` | each agent's persistent memory | no |
| tools | `mas/tools/` | files, Python, web search and fetch, git | no |
| `team`, `scenario` | `mas/team.py`, `mas/scenario.py` | load a team and post a scenario's tasks | no |
| `build_system` | `mas/app.py` | wires all of the above | no |

## 3. Communication topologies

- **Group chat** (`group:main`): the human and all agents are members. Task hand-overs, results,
  questions to the human and answers are public, so the human sees who asked whom for what.
- **Private chats** (`dm:<human>:<agent>`): the human can talk to one agent, which then executes the task
  itself (it may still delegate). Delegations made inside a private task stay in that private channel.
- **Addressing.** A message is *delivered* to every member of its channel, but an agent *acts* only on a
  message whose `receiver` is itself or that `@mentions` it, so receiving costs no LLM call. A human
  message that mentions nobody is a **request** and is handled by the `RequestTracker`; `@dev ...` gives
  the task straight to `dev`; `/dm dev ...` opens a private chat.
- **Message types**: `CHAT`, `TASK_ASSIGN`, `TASK_RESULT`, `HITL_REQUEST`, `HITL_RESPONSE`, `STATUS`.
  Payloads are plain JSON, so every message can be logged and replayed.
- **Observers.** The bus calls registered observers synchronously before delivery. The Router uses this
  to complete waiting delegations and human questions, the board to record progress, the
  `RequestTracker` to notice new requests, and the `Transcript` to write the dialogue.

## 4. Routing and delegation

### 4.1 From a human message to a lead

| The human says | What happens |
|---|---|
| plain text in the group | a **request**: a new *root* (`R1`, `R2`, ...) is opened and a lead is chosen. If a request is already running, the text is an **addition** to it. |
| `@dev ...` or `/dm dev ...` | a direct task for `dev` (its own root); `dev` leads it and may still delegate |
| `/status`, `/cancel` | answered by the `RequestTracker` from the state table, without an LLM |

### 4.2 Choosing the lead

`LeadSelector.choose(session, request)` makes **one LLM call** with a single tool, `choose_lead`. The
prompt lists every member's agent id, role name and prompt, and asks for the member best placed to
*coordinate* this request (the one responsible for understanding goals and taking decisions, not for
carrying out one part). Then:

- the answer is **cached per session**, so the follow-up request of a conversation (Task 2 after Task 1)
  keeps its lead and costs no call;
- if the call fails, the answer is not a member, or the model does not call the tool, the **first member
  of the team** leads, and the fallback is not cached (the next request asks again);
- a team of one member needs no call.

### 4.3 What the lead does

The lead is an ordinary `WorkerAgent` whose task has no parent. It differs from other members only in
budget (`max_lead_steps` 60 steps, `lead_timeout_s` 2400 s, up to `max_lead_delegations` 16 delegations)
and in a short extra instruction: understand the request, ask the human if it is unclear, split the work,
delegate, have important results reviewed by a teammate and returned for fixing, finish only when the
result is good, and write a final answer the human can read. Its tools are the team's `call_<teammate>`
tools, `ask_human`, and its own tools. What it replies at the end is the message the human reads, and the
files it lists are the deliverables.

Its budget and when it stops are in [4.5](#45-budgets-parallelism-and-stopping).

### 4.4 Delegation (`Router.dispatch`)

Every `call_<teammate>` becomes `Router.dispatch(requester, target, goal, context, files, parent, ...)`:

1. **Limits are checked first**; a refused call is still registered (as `FAILED`, error `refused: ...`) so
   it appears in `/status` and in statistics, and it returns to the caller as an ordinary failed result.

   | Limit | Default | Refused when |
   |---|---:|---|
   | unknown target | | the target is not a member of the group |
   | cycle | | the target is already in the delegation chain (including the caller) |
   | depth | 2 | the chain below the lead would be deeper than `max_delegation_depth` |
   | delegations per task | 2 (lead: 16) | a worker's task has already delegated that often |
   | same-goal retries | 2 | the same goal was already tried 3 times on the same agent in this root; declines do not count |
   | cancelled | | the root was cancelled |

2. The task is **registered** in the `StateTable`, its `files` are **copied** from the requester's workspace
   (or from the workspace of the agent that produced them, searched in this root first and then in the
   earlier roots of the session) into the target's `inbox/`.
3. A `TASK_ASSIGN` is published (in the group, or in the private channel the task belongs to).
4. The router **waits** for the matching `TASK_RESULT`, with a time limit (`subtask_timeout_s` 900 s, the
   lead's request `lead_timeout_s`). Time spent **waiting for a human does not count**.

The target runs the task in its own ReAct loop. At its first step it may **decline** a task outside its
abilities and suggest a better member; a decline is returned to the caller (with the suggestion) and is
not a failure, so the caller can reassign. Teammates can delegate in turn, within the limits above.
Delegations a member sends together in one reply run in parallel; see [4.5](#45-budgets-parallelism-and-stopping).

### 4.5 Budgets, parallelism and stopping

**Limits.** All are fields of `Settings` (`mas/config.py`).

| Limit | Default | What it bounds |
|---|---:|---|
| `max_worker_steps` | 30 | ReAct steps (model calls) of a member for one task |
| `max_lead_steps` | 60 | the same, for the lead of a request |
| `subtask_timeout_s` | 900 s | one delegated task; time spent waiting for a human does not count |
| `lead_timeout_s` | 2400 s | a whole request |
| `max_lead_delegations` | 16 | delegations made by the lead of a request |
| `max_delegations_per_task` | 2 | delegations made by any other member for one task |
| `max_delegation_depth` | 2 | how deep delegations can nest below the lead |
| `max_retries_same_goal` | 2 | retries of the same goal on the same agent in one request |
| `research_max_calls` | 14 | searches and page fetches one task may make; the next one is refused (0: no limit) |
| `repeat_limit` | 2 | the same call with the same answer and nothing changed in between: after this many it is no longer run (0: no limit) |
| `max_parallel_per_teammate` | 3 | jobs of one teammate that run at the same time for one requester |
| `max_review_rounds` | 3 | how often one reviewer is asked to review the same file in one request (0: no limit) |
| `request_budget_s` | 0 (off) | time budget of one request, see 4.8 |
| `lead_summary_max_chars` | 6000 | length of the lead's reply to the human (a teammate's report is cut at `result_summary_max_chars`, 1500) |

**Parallel delegation.** Delegations a member sends together in one reply run **at the same time**: jobs for
different teammates in parallel, several jobs for one teammate too, at most `max_parallel_per_teammate` at a time (they share its workspace, so each is told to start its file names with `job1_`, `job2_`, ... and they cannot overwrite each other's files). The answers
come back in the order asked; if one of the jobs ends the task (cancelled, timed out), the others are stopped. Any other tool
call in the reply keeps its order, because a later delegation may depend on a file an earlier call wrote. A job that needs
another's result goes in a later reply; the instructions say so. The time a member waits for teammates is recorded as the wall clock of
the wait, not the sum of the jobs.

**When a member stops.** A task ends when the member answers without calling a tool. The step limit is only a cap, and
a member that has what it needs is told to write the result and finish. Several nudges push it to stop early instead of
researching until the cap. They are suggestions in the conversation, not rules, and can be switched off together
(`early_stop_nudges`: `EARLY_STOP_NUDGES=0`, or `python -m mas.eval --early-stop off`) to measure what they change.

| Nudge | When | What the member sees |
|---|---|---|
| repeat note | a successful search or page fetch is repeated | "same call as step N, same result: use what you have" (the call still runs; searches and fetches are cached, so it costs nothing) |
| research note | after `research_note_after` (6) searches or fetches, then every `research_note_every` (2) | "stop researching unless one specific fact is missing; write up what you have" |
| progress check, worker | half the steps used and no file written | "write what you have and finish, or say what is missing" |
| progress check, lead | half the steps used and no file exists anywhere in the request | "make sure the deliverable is being written: assign it now before more research or review" |

A failed call never counts as done, so it can always be retried.

**Going round in circles.** The other tools have a rule of their own, and it is not a suggestion: when the same call (same
arguments) gets the same answer a second time and nothing changed in between, the answer says "same as step N; the next one
will not be run", and from the third on it is not run: the member is told it was made twice with the same answer, and is
shown that answer (`repeat_limit`, 0 to switch it off). "Nothing changed" is judged cautiously: any write, any other call
that is not read-only (another script, say), a teammate's reply and an answer from the human all count as a change, so the
same check run again after a file was changed is not a repeat, even when it fails in exactly the same way. Tools that need
the human's approval are left out.

The safety net is not switchable: with 3 steps left the
member is told so, and its last step has no tools, so it must answer with what it has and say what is missing, instead of
ending with "step limit reached".

### 4.6 Finishing a request

When the lead's task returns, the `RequestTracker`:

- copies the deliverables (the files the lead listed, and only those: its helper scripts and drafts are not added behind
  its back; if it listed nothing, every file the successful tasks of the root wrote) from the writing agents' workspaces to `data/output/<root>-<time>/` (name clashes get an
  `<agent>_` prefix; a listed file that does not exist is reported, not hidden). A listed file that both the lead and a
  teammate have is taken from whoever revised it last: the lead's copy if it was written after the teammate's, unless it is
  exactly what that teammate was handed to work on (`Router.delivery_owner`);
- records a `RootOutcome` (success, failure mode, duration, lead, deliverables, output directory);
- posts the final reply **in the lead's name**, with a payload evaluation can read:
  `{"final": true, "root_id", "success", "failure_mode", "rounds", "duration", "lead", "deliverables", "output_dir"}`.

A lead that fails, times out or crashes still produces a reply, with the failure mode (`llm_format`,
`tool_error`, `timeout`, `max_steps`, `wrong_output`, `crash`). A cancelled request produces no reply
(`/cancel` has already said what was cancelled).

### 4.7 Cancellation

`/cancel` marks every unfinished task of the root as cancelled, wakes everything that waits for it
(delegations, human questions) and refuses further calls. The router cannot stop a running agent, so
**workers check for cancellation before every step and before any tool that needs approval**; a human
question that returns "cancelled" is treated as "stop", never as consent.

### 4.8 Time budget and quality gates

Added after the first real runs (`docs/report.md`, stage 4). The principle: **quality gates are hard requirements, and time is
minimised subject to them**. The time budget is a safety net and is off by default.

**Time budget.** `request_budget_s` (`--time-budget`, `REQUEST_BUDGET_S`) is shared by every member of a request; time spent
waiting for the human does not count. A lead is reminded at half and at three quarters of it. A member within
`worker_wrapup_s` (50 s; for the lead `lead_wrapup_s`, 30 s) of the end gets no tools and must answer with what it has. No
delegation starts with less than `min_delegation_s` (80 s) left, and `budget_grace_s` (45 s) after the end whatever still runs is
cut off. A lead that hands in with less than `finish_not_before` (0.5) of the budget used is sent back (twice at most;
`--min-use 0` switches it off).

**Requirements.** When a lead starts, one model call lists what the request explicitly requires (counts, sizes, formats, what must
be covered, not what is only permitted). The list goes to the lead and into every teammate's context. Before the lead hands in it
must report each requirement as met, not met or unverified against the final files (counting with `run_python` when it can be
counted; it may add `OWN1`, `OWN2`, ... for a target it set a teammate). It is sent back twice at most; what stays unmet or
unverified is appended to the reply the human reads and to `open_issues`. What the human answered when asked is added to the list
before the check (`requirements_check`). An invitation to consult the requester ("you can discuss ... with me") becomes ONE
requirement ("Consult the requester about ..."): the lead is told to ask the human a single question before handing out work
(covering every topic, with its own defaults), a first delegation made without asking is held back once, and the system, not the
lead, records whether the human was asked.

**Reviews.** A reviewer answers PASS or FAIL first and lists every problem at once. The `Router` reads a verdict from the wording
(`review_verdict`, only for a task whose goal opens with a review verb) and keeps each reviewer's latest one. Gates before a lead
hands in: (1) a deliverable no reviewer was ever given is sent back to be reviewed (`review_final`; the time left is first topped up
to `review_reserve_s`, 120 s, at most `max_review_extensions` (2) times, so that the fix and the re-check fit); (2) a reviewer whose
latest verdict is a fail is "not cleared" and is listed by the closing check, which asks twice; (3) work done on an earlier
version of a file that has changed since (content fingerprints are taken at every hand-over) is listed as out of date. Reviews
run in rounds, not as a ping-pong: all reviewers in one reply, one revision that applies every item, one re-check; one reviewer is
asked at most `max_review_rounds` (3) times to review the same file. A gate needs steps to act on it: with too few steps left
(3 or 4) a final answer is handed in as it is, instead of being sent back and lost.

**Files.** Besides the files listed in a call, the `Router` hands over the files the goal names that exist in the requester's
workspace, and replaces an older copy of the same name in the teammate's inbox (`import_file` itself never overwrites). The files
a teammate reports (code included, at most 6; when there are more, the helper scripts the task neither named nor handed over
stay behind first) are copied back into the requester's inbox, because a reply is cut at 1500 characters.

**Closing check.** Before a lead's final answer is accepted: failed tasks, open issues, "could not read the file" reports,
uncleared reviews and out-of-date work are put to it, with one more step to put them right (`closing_check`).

## 5. Human in the loop

Agents pause and ask the human in three situations; all arrive in the chat where the request started,
numbered (`h1`, `h2`, ...) so several can be open at once:

| Situation | Kind | Who asks |
|---|---|---|
| the request or a step is ambiguous | `clarify` | any member, with the `ask_human` tool (the lead mostly) |
| before a tool marked `requires_approval` (`git`, `delete_file`); deleting a file the task itself wrote (a scratch script) needs no approval | `approval` | the worker, automatically |
| the same tool failed twice in a row | `advice` | the worker, automatically |

The human answers with `/reply <id> <answer>` (just `/reply <answer>` when only one is open). Waiting for
a human stops the clock of the task. The command line is `CliHumanIO`; for unattended runs the
`AutoResponder` answers every question with a fixed default for its kind (a limitation, see §13). A human
message sent while a request runs is recorded on the board and read by the workers at their next step.

## 6. Memory and evolution

**Storage.** Each agent has its own file `data/memory/<agent_id>.jsonl`, one JSON record per task:
goal, task-type tags (derived from the tools used), success, a summary, and, for failures, a one-sentence
**lesson**. The file is read on every use, so memory survives restarts: a new run with the same data directory
starts with what the agents learned before. We tested this by running two complete programs against one data
directory (`tests/test_memory_across_sessions.py`).

**Learning from experience.**

| Mechanism | What happens |
|---|---|
| record | when a task ends (not for declined or cancelled ones) the worker writes a record |
| reflect | after a **failure** the worker asks the LLM once, in the background and off the critical path, for a lesson, and replaces the record with one that has it |
| recall | when a task starts, the `memory_recall_k` (3) most relevant records are put in the prompt. Relevance is keyword overlap (goal and tags count double, summary and lesson once; Chinese is matched by character runs); a record with a lesson scores one more; ties go to the newer one |
| profile | from the latest 20 records: success counts per task type and the lessons of the most recent failures, e.g. `Recent performance: code 8/10 succeeded, search 1/2 succeeded. Known weak spots: ...` |

**Memory changes the division of work.** A member's profile is appended to its `call_<member>` tool
description, so whoever delegates sees how each teammate has been doing and what to avoid.

**Isolation.** An agent reads only its own file; teammates see only the short profile.

**Limits.** Records hold goals, outcomes and lessons, not the content of conversations; recall is
keyword-based (no embeddings); lessons are written only after failures. Whether this improves results
over repeated runs is measured in the test report, not assumed here.

## 7. Sandboxes and workspace isolation

Each agent has a private directory `workspaces/<agent>/` and a `Sandbox` object bound to it. **Tools never
touch the file system or run commands directly**; they call the sandbox, which

- **resolves every path** against the workspace root, follows symbolic links, and rejects anything that
  ends up outside (`PermissionError`); on Windows it also rejects device names and alternate data streams;
- **writes UTF-8 and keeps newlines unchanged**; deletes only files;
- **runs commands** (`exec`) with the workspace as working directory, a timeout and a given
  environment; what a tool shows the LLM is clipped to `tool_output_max_chars` (4000); the process is started in its own session (POSIX) or a kill-on-close job
  (Windows), so a timeout or cancellation kills the whole process tree;
- **imports files into `inbox/`** only on the Router's request: the source is a file in another agent's
  workspace, the destination must stay inside this workspace's `inbox/`, and an existing file is never
  overwritten (the copy is exclusive, so concurrent imports cannot clobber each other).

Files move between agents only through the Router, which copies them on `dispatch`. Data therefore
cannot leak between agents by accident: a teammate sees a file only if the delegating agent handed it over.

`LocalSandbox` is what runs. It separates the agents' files but **commands run with the host user's
permissions**, so it is not a security boundary. `DockerSandbox` (one long-lived container per agent, only
its workspace mounted) is the planned stronger isolation and is not implemented.

## 8. Tools

| Tool | Does | Notes |
|---|---|---|
| `read_file`, `write_file`, `list_files` | read, create or overwrite, list | relative paths inside the workspace; `write_file` takes `append: true` to add to the end of a file, so a long file is written in parts. One reply ends at the model's output limit: of a `write_file` cut off there, the part that arrived is kept when it is a new file (or an append to an existing one), cut back to its last whole line, and the member is told which line the file now ends with and to go on from there with append; when it would replace an existing file nothing is written, and the member is told why and how to write in parts. The answers of `write_file` and `edit_file` give the size of the whole file in characters, words and lines (a word is a run of letters or digits, or one CJK character), so nobody has to write a script to count |
| `edit_file` | change a file by exact replacement | `{old, new}` pairs (or one `old`/`new`), applied in order all or nothing; a failure says which edit and why, with the closest line; success confirms the new size. Members are told to use it instead of rewriting a file or patching it with a script |
| `delete_file` | delete a file | needs the human's approval |
| `run_python` | run a script or a module (`unittest`, `pytest`) in the workspace | timeout (default 60 s), output returned with the exit code |
| `web_search` | titles, URLs and snippets | With `SEARCH_PROVIDER=auto`, HKGAI uses Studio Quick search with the optional `HKGAI_SEARCH_API_KEY`. DeepSeek uses its model key for search, adds `after:` for freshness and `lang:en` for English queries, and limits queries to 128 characters. When the selected key is missing or its service is unavailable, search falls back to `ddgs`. |
| `fetch_url` | the text of a public web page | public HTTP(S) only: private and mixed addresses are refused on every redirect hop, 20 s and 1 MiB limits, text, HTML, JSON and XML. When the site refuses this machine (401, 403, 406, 429, 451 or a server error) and the DeepSeek model is in use, DeepSeek's fetch API reads the page with the same key (`"via": "deepseek"`) |
| `git` | `init`, `clone`, `status`, `diff`, `add`, `commit`, `log`, `push` | every call needs the human's approval; the GitHub token is sent only to github.com over HTTPS and kept out of the output |

Plain-text outputs only: documents are `.md` and `.txt` (HTML and code are allowed as files). Every tool
returns a `ToolResult` (`ok`, text for the LLM, files written, references such as a commit id) and never
raises for an expected failure. The files a tool writes become the task's artifacts automatically.

## 9. Shared context and transcript

**Session board.** One board per session (the group, or one private chat) is maintained **by code** from
structured messages, never summarized by an LLM, so file names and ids are not lost: the human's own
words, what is done (with files and key points), what failed or was declined, the human's decisions, what
is still open, and one line per earlier request. It is injected into a worker's prompt when a task starts,
within a size budget, which is how Task 2 sees the results of Task 1. Boards live in memory for the run.

**Transcript.** A bus observer writes the whole conversation to `data/transcripts/<scenario>-<time>.md`:
what the human said, which member led, who delegated what to whom, what the team asked and what the human
answered, each result, how each request ended, and a summary table. It is rewritten whenever a request
ends. This is the file to hand to a model for grading the dialogue.

## 10. Evaluation

`python -m mas.eval <scenario folders>` (`mas/eval/harness.py`) runs each scenario's tasks in a fresh system
and measures, in code: the **task completion rate** (requests, and sub-tasks the lead delegated), the
**execution time** of each request (mean, median, maximum), failure-mode counts and the number of questions
the team asked. It writes `report.md` and `results.json`, and the transcript and deliverables of every run.

- `--human llm` (default) has a `SimulatedHuman` answer the team's clarifying questions as the person who made
  the request; `--human auto` uses the `AutoResponder`'s fixed answers.
- `--judge` has a model grade each task's dialogue and deliverables (`mas/eval/judge.py`), as the course does.
- `--repeat N --keep-memory` runs a scenario again with the agents' memory kept, to measure whether memory helps.
- A scenario that does not finish in time is reported as a failure, never as a hang.
- `python -m mas.eval.rejudge <archived run>` grades an archived run again from its transcript and delivered files (old and new mark side by side). The grader is shown every delivered file whole (up to 60,000 characters each, 160,000 in all, the dialogue 60,000); a longer file keeps its beginning and end with a line saying the middle is omitted from its view only. `report.md` also has a table of where the lead's steps went (tools, delegations, each kind of push).
- `--time-budget SECONDS` (per request), `--research-limit N` (searches and fetches per task) and `--min-use FRACTION` (when a lead may hand in) set the profile; the report records them.

Also recorded for every request, outside the harness: the `RootOutcome` and the final reply payload, and the
transcript. `docs/report.md` states what has been measured so far.

## 11. LLM backends

Both course-approved backends speak the OpenAI chat-completions protocol with function calling:
HKGAI (default, `HKGAIClient`) and DeepSeek (`DeepSeekClient`, the same client with DeepSeek's defaults),
chosen with `LLM_PROVIDER` or `--llm`. DeepSeek is asked not to think (`DEEPSEEK_THINKING=off`): every step of an agent
is a tool call, thinking makes each call slower, and a thinking model's reasoning text must be sent back with every later request or the API
refuses it. The client retries timeouts, rate limits and server errors with
exponential backoff and `Retry-After`, repairs tool-call arguments that are fenced or have trailing commas,
validates every response, and returns an `LLMError` only after the retries are exhausted. OpenAI and
Anthropic APIs are not used. Tests use `MockLLM`, a scripted stand-in.

## 12. Configuration and data layout

All limits are fields of `Settings` (`mas/config.py`): step limits (`max_worker_steps` 30,
`max_lead_steps` 60), time limits (`subtask_timeout_s` 900, `lead_timeout_s` 2400), delegation limits,
memory recall size, sandbox backend, paths. Keys come from `.env`.

```
workspaces/<agent>/        each agent's private files, and inbox/ for files handed over
data/memory/<agent>.jsonl  each agent's memory
data/output/<root>-<time>/ the deliverables of each request
data/transcripts/          the conversation of each run
data/mas.log               the log (stack traces of internal errors)
```

## 13. Limitations

- `LocalSandbox` is not a security boundary; the Docker sandbox is not implemented.
- The session board is kept in memory: a restarted program remembers what each agent learned (memory)
  but not the earlier requests of the conversation.
- The unattended `AutoResponder` answers every question with a fixed default, so it cannot stand in for a
  human who has real preferences (for example an investor's risk tolerance).
- Keyless search depends on third-party engines that rate-limit or change (2 failures in 8 queries on one network). Each `ddgs` search has a 12 s deadline. After 3 consecutive failures it pauses for 30 s and tells the member to carry on.
- Recall is keyword-based, and lessons are only learned from failures.
- Real-model evaluations so far use the DeepSeek model only, are single runs and are graded by the same model; scenario 3 was tuned on. The HKGAI model has not been run. Open problems are listed in `docs/report.md` (stage 4, section 9).
