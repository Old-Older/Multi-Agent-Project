# 团队交接记录

两位成员之间的接口变更说明，按时间倒序，保留原文。读 README 不需要看这里。

## 2026-11-18 的结构变更（请先读，下面 2026-11-09 的表里提到 Orchestrator 的地方以这里为准）

设计决定见 [docs/design_decisions.md](design_decisions.md) D18。**没有 Orchestrator agent 了，团队由用户定义，每个请求由团队里的一个角色牵头。**

| 变了什么 | 你需要知道 / 做什么 |
|---|---|
| `mas/agents/orchestrator.py` 删除（git tag `pre-lead-central` 可取回）。换成 `mas/core/requests.py` 的 `RequestTracker`：**不是 agent、不调 LLM**，作为总线观察者接住没 @ 任何人的人类消息，处理 `/status`、`/cancel`，开关 root，收集交付物，记录 `outcomes[root_id]`。 | 评测框架读 `System.requests.outcomes[root_id]`（`RootOutcome`：success、failure_mode、duration、deliverables、output_dir、lead），或等最终回复：它是一条 `CHAT`，`sender` 是**牵头角色**，`payload` 带 `final, root_id, success, rounds, failure_mode, deliverables, output_dir, lead, duration`。 |
| 牵头者由 `mas/core/lead.py` 的 `LeadSelector` 选：一次 LLM 调用，按会话缓存，失败退回角色表第一个。牵头者就是普通 `WorkerAgent`，任务的 `chain == ["orchestrator"]`、`parent_id is None`。 | `WorkerAgent` 新增可选参数 `peers`（全队角色）和 `peer_memories`；有 `peers` 时多了 `call_<队友>` 和 `ask_human` 两个工具，牵头任务的步数和时间预算用 `max_lead_steps` / `lead_timeout_s`。你自己建 Worker 时（如 `examples/execution_tools.py`）请传 `peers=parts.peers, peer_memories=parts.memories`。 |
| 没有内置角色：`build_system(..., roles=...)` 必须传入。`mas/team.py` 的 `load_team()` 读课程的 `01_role_initialization.md` 格式；`python -m mas --team <文件或文件夹>` 或 `--scenario <文件夹>`（按文件顺序依次发任务）。`ROLES`（researcher/coder/writer）只剩演示和测试用。 | 八个工具（含 `run_python`、`web_search`、`fetch_url`、`git`）已全部接进 `app.build_tools`（`web_search` 读 `SEARCH_API_KEY`，`git` 读 `GITHUB_TOKEN`）。`AutoResponder` 已实现；`eval/harness.py` 还是空的。运行时完整对话写到 `data/transcripts/`。 |
| `Router`：`dispatch(..., timeout=)`、`locate_file` 能找到同一会话里**更早的** root 的产出（后续任务能用前一个任务的文件）、新增 `root_artifacts()`。`httpx` 请加进 `pyproject.toml` 的依赖。 | `mas/llm/hkgai.py` 的 `_arguments` 在 Python 3.14 下修不掉尾逗号（`JSONDecodeError.pos` 指向逗号本身；3.13 未测），已兼容两种行为。 |

## 2026-11-09

以下为历史接线记录，当前运行方式见下文「怎么运行」。更新于 2026-11-09，分支 `feat/jian-comms-orchestration`。下面这些约定会影响 `WorkerAgent`、桩 Router 和 `AutoResponder`。完整说明见 [docs/interfaces.md](interfaces.md) §3.4。

| # | 约定 | 你需要做什么 |
|---|---|---|
| 1 | **`Task.chain` 只记委派者，不含执行者。** Orchestrator 派给你的任务 `chain == ["orchestrator"]`、`depth == 0`；你再委派出去的任务，`chain` 末尾是你自己。 | 如果 Worker 读 `task.chain`，注意最后一项是"谁委派给我"，不是我自己。 |
| 2 | **取消要 Worker 自己配合。** `/cancel` 后 Router 只能标记任务、唤醒等待者，**停不住正在运行的 agent**。 | 每一步 ReAct 开始前、执行 `requires_approval` 工具（`git push`、删除文件）前，先 `if self.is_cancelled(task): return TaskResult(task.id, False, "", error="cancelled")`。`ask_human` 返回 `CANCELLED_ANSWER`（`from mas.core.human import CANCELLED_ANSWER`，值 `"cancelled"`）时按中止处理，**不要当成同意**。 |
| 3 | **`Router.request_human` 的签名变了**（关键字参数：`session_id, root_id, origin_channel, requester, kind, question, options, task_id`）。`HITL_REQUEST` 的 payload 新增 `root_id`，`task_id` 可能为 `None`（Orchestrator 澄清时）。 | Worker 照旧调 `self.ask_human(task, question, kind, options)`，不用改。但**如果你的桩 Router 实现了 `request_human`，要改成新签名**（或测试里直接替换 `ask_human`）。`CliHumanIO` / `AutoResponder` 读 payload 时要容忍 `task_id is None`。 |
| 4 | **被拒绝的 `call_<agent>`**（超限、未知 agent、文件找不到、root 已取消）返回 `success=False`、`failure_mode=TOOL_ERROR`、`error` 以 `refused:` 开头，并在状态表里登记成 `FAILED` 任务。 | 当作普通的失败结果回给 LLM，由它决定换目标或放弃。 |
| 5 | **任务在等人类时，`dispatch` 不会超时。** | 无需改动，知道就行。 |
| 6 | **同一目标最多试 3 次**（首次 + 2 次重试，同一 root、同一 agent、同一目标）；被 `decline` 的不占次数。再委派最多 2 层，每个任务最多再委派 2 次，链上已有的 agent 不能再被委派。 | 无需改动；撞到限制时会按第 4 条收到 `refused:` 结果。 |
| 7 | **`HumanIO` 新增了两个共用方法**：`HumanIO.request_from(msg)` 和 `handle_incoming(bus, msg)`（跳过人类自己的消息、调 `show`、遇到 `HITL_REQUEST` 就调 `answer` 并发回 `HITL_RESPONSE`）。`HitlRequest.task_id` 在 Orchestrator 澄清时是 `""`。 | 写 `AutoResponder` 时，`run` 里只需要"从 inbox 取消息 → `await self.handle_incoming(bus, msg)`"，`answer` 直接返回默认答案；不用自己拼 `HITL_RESPONSE`。 |
| 8 | **私聊里的 `/cancel` 由 `Agent.handle_chat` 处理**（取消这个私聊里未结束的任务，并发一条带 `cancelled_roots` 的"Cancelled R1" 通知）。**root id 现在全局唯一**（R1、R2……跨会话递增）。新增依赖 `prompt_toolkit`（命令行用，`pip install -e .` 会装）。 | 如果你重写 `WorkerAgent.handle_chat`，对不认识的消息请调用 `super().handle_chat(msg)`，否则私聊里的 `/cancel` 会失效。不要自己假设 root id 在每个会话里从 R1 开始。 |
| 9 | **评测框架读什么**：Orchestrator 的最终回复是一条 `CHAT`（`receiver` 是 human），`payload` 是 `{"final": True, "root_id", "success", "rounds", "failure_mode", "deliverables", "output_dir"}`；也可以直接读 `Orchestrator.outcomes[root_id]`。交付物在 `data/output/<root_id>-<启动时间>/`，完整路径就在 `payload["output_dir"]` 里（检查器读这个，不要自己拼路径）。`success` 只表示"LLM 调用了 finish"，对不对由 checker 判断。 | 写 `run_case` 时等这条消息即可，轮数、失败模式、输出目录都在里面。 |
| 10 | **记忆已经能用了**：`JsonlMemory.for_agent(settings.memory_dir, agent_id)` 得到每个 agent 自己的记忆；`add(exp)`、`recall(query, k)`、`profile(max_chars)` 都已实现。还有一个现成的 `tags_for_tools(tool_names, artifacts)` 帮你打标签。同一个 `task_id` 可以 `add` 两次，后写的算数。`JsonlMemory.clear()` 清空一个 agent 的记忆（评测要从空记忆开始时用）。 | `WorkerAgent`：开始任务时 `recall(goal, settings.memory_recall_k)` 注入 prompt；每个子任务结束 `add` 一次（失败时等异步反思出教训后再 `add` 一次带 `lesson` 的）。**建议不要记录被 `decline` 的和被 `/cancel` 的任务**：它们不是"尝试后失败"，记进去会拉低成功率、污染能力档案。 |
| 11 | **系统组装**在 `mas/app.py`。`default_worker_factory` 创建通用 `WorkerAgent`，`build_tools` 为默认入口注册文件工具，`make_llm` 按课程配置创建 `HKGAIClient`。`python -m mas --demo` 可离线运行。 | Python、网络与 Git 工具可通过示例的 `execution_worker_factory` 接入；评测仍可通过 `build_system(..., human=AutoResponder())` 和 `System.start()` 组装。 |
