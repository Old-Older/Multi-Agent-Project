# Evolutionary Multi-Agent Collaboration System

Course final project. A backend framework where multiple heterogeneous agents chat with humans,
decompose and delegate tasks, run tools inside isolated sandboxes, and learn from past executions.

> ## ⚠️ 给 LI Heyang：接口约定（请先读）
>
> 更新于 2026-11-09，分支 `feat/jian-comms-orchestration`。下面这些约定会影响 `WorkerAgent`、桩 Router 和 `AutoResponder`。完整说明见 [docs/interfaces.md](docs/interfaces.md) §3.4。
>
> | # | 约定 | 你需要做什么 |
> |---|---|---|
> | 1 | **`Task.chain` 只记委派者，不含执行者。** Orchestrator 派给你的任务 `chain == ["orchestrator"]`、`depth == 0`；你再委派出去的任务，`chain` 末尾是你自己。 | 如果 Worker 读 `task.chain`，注意最后一项是"谁委派给我"，不是我自己。 |
> | 2 | **取消要 Worker 自己配合。** `/cancel` 后 Router 只能标记任务、唤醒等待者，**停不住正在运行的 agent**。 | 每一步 ReAct 开始前、执行 `requires_approval` 工具（`git push`、删除文件）前，先 `if self.is_cancelled(task): return TaskResult(task.id, False, "", error="cancelled")`。`ask_human` 返回 `CANCELLED_ANSWER`（`from mas.core.human import CANCELLED_ANSWER`，值 `"cancelled"`）时按中止处理，**不要当成同意**。 |
> | 3 | **`Router.request_human` 的签名变了**（关键字参数：`session_id, root_id, origin_channel, requester, kind, question, options, task_id`）。`HITL_REQUEST` 的 payload 新增 `root_id`，`task_id` 可能为 `None`（Orchestrator 澄清时）。 | Worker 照旧调 `self.ask_human(task, question, kind, options)`，不用改。但**如果你的桩 Router 实现了 `request_human`，要改成新签名**（或测试里直接替换 `ask_human`）。`CliHumanIO` / `AutoResponder` 读 payload 时要容忍 `task_id is None`。 |
> | 4 | **被拒绝的 `call_<agent>`**（超限、未知 agent、文件找不到、root 已取消）返回 `success=False`、`failure_mode=TOOL_ERROR`、`error` 以 `refused:` 开头，并在状态表里登记成 `FAILED` 任务。 | 当作普通的失败结果回给 LLM，由它决定换目标或放弃。 |
> | 5 | **任务在等人类时，`dispatch` 不会超时。** | 无需改动，知道就行。 |
> | 6 | **同一目标最多试 3 次**（首次 + 2 次重试，同一 root、同一 agent、同一目标）；被 `decline` 的不占次数。再委派最多 2 层，每个任务最多再委派 2 次，链上已有的 agent 不能再被委派。 | 无需改动；撞到限制时会按第 4 条收到 `refused:` 结果。 |
> | 7 | **`HumanIO` 新增了两个共用方法**：`HumanIO.request_from(msg)` 和 `handle_incoming(bus, msg)`（跳过人类自己的消息、调 `show`、遇到 `HITL_REQUEST` 就调 `answer` 并发回 `HITL_RESPONSE`）。`HitlRequest.task_id` 在 Orchestrator 澄清时是 `""`。 | 写 `AutoResponder` 时，`run` 里只需要"从 inbox 取消息 → `await self.handle_incoming(bus, msg)`"，`answer` 直接返回默认答案；不用自己拼 `HITL_RESPONSE`。 |
> | 8 | **私聊里的 `/cancel` 由 `Agent.handle_chat` 处理**（取消这个私聊里未结束的任务，并发一条带 `cancelled_roots` 的"Cancelled R1" 通知）。**root id 现在全局唯一**（R1、R2……跨会话递增）。新增依赖 `prompt_toolkit`（命令行用，`pip install -e .` 会装）。 | 如果你重写 `WorkerAgent.handle_chat`，对不认识的消息请调用 `super().handle_chat(msg)`，否则私聊里的 `/cancel` 会失效。不要自己假设 root id 在每个会话里从 R1 开始。 |
> | 9 | **评测框架读什么**：Orchestrator 的最终回复是一条 `CHAT`（`receiver` 是 human），`payload` 是 `{"final": True, "root_id", "success", "rounds", "failure_mode", "deliverables", "output_dir"}`；也可以直接读 `Orchestrator.outcomes[root_id]`。交付物在 `data/output/<root_id>-<启动时间>/`，完整路径就在 `payload["output_dir"]` 里（检查器读这个，不要自己拼路径）。`success` 只表示"LLM 调用了 finish"，对不对由 checker 判断。 | 写 `run_case` 时等这条消息即可，轮数、失败模式、输出目录都在里面。 |
> | 10 | **记忆已经能用了**：`JsonlMemory.for_agent(settings.memory_dir, agent_id)` 得到每个 agent 自己的记忆；`add(exp)`、`recall(query, k)`、`profile(max_chars)` 都已实现。还有一个现成的 `tags_for_tools(tool_names, artifacts)` 帮你打标签。同一个 `task_id` 可以 `add` 两次，后写的算数。`JsonlMemory.clear()` 清空一个 agent 的记忆（评测要从空记忆开始时用）。 | `WorkerAgent`：开始任务时 `recall(goal, settings.memory_recall_k)` 注入 prompt；每个子任务结束 `add` 一次（失败时等异步反思出教训后再 `add` 一次带 `lesson` 的）。**建议不要记录被 `decline` 的和被 `/cancel` 的任务**：它们不是"尝试后失败"，记进去会拉低成功率、污染能力档案。 |
> | 11 | **系统可以跑起来了**：`python -m mas --demo`（不需要你的部分）。组装在 `mas/app.py`，**你要接的地方**：`build_tools(role, settings)`（返回真实工具，现在返回空列表）；`default_worker_factory` 建 `WorkerAgent`；`default_sandbox_factory` 用 `LocalSandbox`/`DockerSandbox`；`make_llm` 建 `DeepSeekClient`。`mas/demo.py` 里的 `DemoWorker` 是个完整的例子，演示了一个 Worker 该做的事：拒绝做不了的、危险步骤前 `ask_human`、每步检查 `is_cancelled`、开始前 `recall`、结束时 `add`。 | 写好 `WorkerAgent`、工具、`LocalSandbox`、`DeepSeekClient` 后，`python -m mas` 就是真系统；评测框架用 `build_system(..., human=AutoResponder())` + `System.start()`。 |

## 怎么运行

```bash
# 演示：不需要 API key，也不需要 LI 的部分（stand-in LLM 和 worker，其余都是真的）
~/.virtualenvs/agents/bin/python -m mas --demo            # 想从头开始加 --fresh

# 真实系统：需要 .env 里的 DEEPSEEK_API_KEY，以及 WorkerAgent、工具、DeepSeekClient（LI 的部分）写好
~/.virtualenvs/agents/bin/python -m mas

# 全部测试
~/.virtualenvs/agents/bin/python -m unittest
```

演示里可以试：`write a python script and a document`、`run the tests`（writer 拒绝，改派给 coder）、`write a script and push it`（要你批准，`/reply yes`）、`/status`、`/cancel`、`/dm researcher find out about decorators`。命令行里输入 `/help` 看全部命令。组装代码在 `mas/app.py`，LI 要接的地方见 `docs/interfaces.md` §3.17。

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
