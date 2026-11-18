# Test Results & Performance Report

本报告按时间顺序记录**实际跑过**的测试，最新的在后面。每一节写明环境、命令、数字和没有测的东西。
LI Heyang 的两节保持原样；JIAN Yimin 的一节接在后面，并在最后一节汇总课程要求的评测指标现在测到了哪一步。

| 阶段 | 日期 | 负责人 | 环境 | 全仓测试 |
|---|---|---|---|---|
| [第一阶段：沙箱与文件工具](#第一阶段验收报告2026-11-13) | 2026-11-13 | LI Heyang | Windows，Python 3.11.15 | 286 项，284 通过，2 跳过，0 失败 |
| [第二阶段：Worker、HKGAI 与执行工具](#第二阶段worker-hkgai-客户端与执行工具2026-11-17-至-2026-11-18) | 2026-11-17 至 11-18 | LI Heyang | Windows，Python 3.11.15 | 386 项，384 通过，2 跳过，0 失败 |
| [第三阶段：牵头协作与场景运行](#第三阶段牵头协作请求层场景运行搜索与-deepseek2026-11-18) | 2026-11-18 | JIAN Yimin | macOS，Python 3.14.3 | 421 项，419 通过，2 跳过，0 失败 |
| [课程评测指标的现状](#课程评测指标的现状) | 2026-11-18 | | | **端到端评测尚未进行** |

单元测试通过率不是任务完成率，测试套件的秒数也不是任务的执行时间；这两项课程指标要用真实模型在测试集上测，见最后一节。

---

## 第一阶段验收报告（2026-11-13）

> LI Heyang 的原文，未改动。其中 §6 的"仍待完成"是当时的状态，现状见最后一节。

范围：LI Heyang 的 LocalSandbox、四个文件工具、现有系统接线及相关测试；
按后续请求补修 Windows 下 Agent 内部耗时统计，保持公共接口不变。
基线为本次开发开始前 fetch 核对的 `origin/main = 216191e`，分支为
`feat/heyang-sandbox-tools`。本批按沙箱/工具与 Agent 计时修复拆成两次提交；
交付至功能分支供审阅，不直接合并 main。

结论：**本阶段指定验收通过，Windows 耗时问题已修复；最新全仓回归 286 项中 284 通过、
2 项因符号链接权限跳过，0 失败。公共接口保持兼容，可以进入代码审查。**
本报告不表示 Worker、真实模型调用或完整课程评测已经完成。

### 1. 完成内容

| 内容 | 结果 |
|---|---|
| LocalSandbox | 文件读写、删除、列表、存在性、实际路径边界、inbox 导入、命令执行及清理均已实现 |
| 文件工具 | read_file、write_file、delete_file、list_files；错误转 ToolResult，写入报告真实产物 |
| 系统接线 | 沿用 build_tools/build_system；按角色顺序构造工具，已知待实现项警告并跳过，未知项报错 |
| 跨 agent 交接 | 真实 Bus、StateTable、Router 与 LocalSandbox；上游 artifact 可在下游 inbox 读取 |
| Windows duration 修复 | Agent 内部使用 perf_counter 测量短任务耗时，保留 Worker 自报值，公共接口不变 |
| 文档与示例 | [详细交接说明](sandbox_tools_handoff.md)、[可运行示例](../examples/sandbox_tools.py)、接口说明更新 |

未扩展 Worker、DeepSeekClient、run_python、网络/Git 工具、Docker 执行或课程评测框架。
未修改 JIAN 负责的 Bus、Router、StateTable、SessionBoard、Orchestrator 和记忆实现。
Agent 基类只调整内部耗时统计使用的时钟，方法签名和 TaskResult 字段保持不变。

### 2. 验证结果

环境：Windows，Python 3.11.15；使用 unittest，未安装新依赖。测试使用临时目录、短命令和替身，
不调用真实 API，不需要人工输入。以下均为实际执行记录。

| 验证集合 | 总数 | 通过 | 失败 | 跳过 | 耗时 |
|---|---:|---:|---:|---:|---:|
| 文件阶段新增 + interfaces/app/Router 指定回归（此前） | 130 | 128 | 0 | 2 | 20.905s |
| 全项目 unittest discovery（duration 修复前，历史记录） | 284 | 281 | 1 | 2 | 32.585s |
| Agent 定向回归（duration 修复后） | 22 | 22 | 0 | 0 | 1.083s |
| 全项目 unittest discovery（最新复查，duration 修复后） | 286 | 284 | 0 | 2 | 31.957s |

上述集合有重叠，不能将数量相加。新增两项耗时回归使全仓总数从 284 增至 286。
示例此前已通过；本次也通过 compileall 和 git diff --check。

本阶段指定回归的实际命令：

```powershell
python -u -c "import faulthandler, unittest; faulthandler.dump_traceback_later(90, exit=True); unittest.main(module=None, argv=['unittest', 'tests.test_sandbox', 'tests.test_process_cleanup', 'tests.test_tools', 'tests.test_router_files', 'tests.test_interfaces', 'tests.test_app', 'tests.test_router', '-q'])"
```

最新全项目的实际命令（退出码 0，`OK (skipped=2)`）：

```powershell
python -u -c "import faulthandler, unittest; faulthandler.dump_traceback_later(90, exit=True); unittest.main(module=None, argv=['unittest', 'discover', '-s', 'tests', '-q'])"
```

普通终端可使用 `python -m unittest discover -s tests -q`。本工具的受限执行环境曾阻塞 Windows asyncio
初始化的本地 socketpair；允许本地回环连接后完成验证。最初挂起的执行未计为通过。

**已修复的 Windows 耗时问题：** 修复前 `tests/test_agent_base.py` 的
`RunLoopTest.test_task_roundtrip` 断言 `r.duration > 0`，实测得到 `0.0`。
当时 `mas/agents/base.py` 用两次 `time.monotonic()` 相减计算耗时。本机
`time.get_clock_info('monotonic')` 显示实现为 `GetTickCount64()`、分辨率 `0.015625s`，
短任务可能在同一时钟刻度完成。按用户后续请求，内部起止计时改为 `time.perf_counter()`，
本机实现为 `QueryPerformanceCounter()`、分辨率 `1e-7s`。duration 仍为浮点秒，
仅在 Worker 未提供非零 duration 时补齐，不填造最小耗时、不加入 sleep。
Agent 的全部 14 个方法签名经静态比较与基线一致，TaskResult 源文件未改。

保留原有 `duration > 0` 断言，新增两项回归：粗时钟未前进时仍能记录 0.4ms 短任务；
Worker 自报的 2.5s duration 不被覆盖。两项同时检查返回值和 TASK_RESULT 消息中的 duration。
定向 Agent 回归 22 项全部通过，1.083 秒，实际命令为：

```powershell
python -u -c "import faulthandler, unittest; faulthandler.dump_traceback_later(30, exit=True); unittest.main(module=None, argv=['unittest', 'tests.test_agent_base', '-v'])"
```

**两项跳过：** workspace 符号链接越界与 inbox 符号链接重定向测试。
本机创建链接报 `WinError 1314`，缺少权限。需要在允许创建符号链接的环境补验。
POSIX 命令执行分支也尚未实测。

### 3. LI Heyang 现在需要检查什么

1. **亲自跑一次最小示例。** 在本工作树根目录运行
   `python -X utf8 -m examples.sandbox_tools`。
   应看到 `Wrote notes.md`、`inbox/notes.md`、中文笔记和四个 Coder 工具名称。
   run_python/git 的未实现警告属于预期。示例用临时目录，结束后自动清理，不留下演示产物。
2. **检查两条交接约定。** inbox 同名目标拒绝覆盖；现有 Router 保留 Task.files 源名称，
   下游实际读取 `inbox/<basename>`。确认理解后续 Worker 如何使用它们。
3. **检查结果而非只看工具名称。** `tests/test_router_files.py` 验证文件在 TASK_ASSIGN 前已复制；
   `tests/test_app.py` 用默认组装得到的真实工具写入并读回中文；`tests/test_tools.py` 验证 schema 与产物。
4. **审阅测试边界。** 最新全量回归为 284 通过、2 项权限跳过、0 失败，历史 duration 失败已修复。
   不把 demo 通过当成 LocalSandbox 验收，也不要求尚未实现的 Worker 驱动完整真实系统。
5. **审阅 GitHub 交付。** 本批分为 `feat: implement local sandbox and wire file tools` 与
   `fix: use high-resolution clock for agent duration` 两次提交。核对功能分支上的代码、测试、示例和文档，
   后续通过 PR 审阅；合并 main 另行决定。

### 4. 与 partner 之前 push 的标准是否一致

核对依据：合并基线 `216191e`、README Workflow、接口文档、`.gitattributes`，
以及 JIAN 的 `f4d0dcf`（统一代码运行文案/注释/测试说明语言）和近期提交记录。

| 约定 | 当前情况 |
|---|---|
| 公共签名及数据结构保持兼容 | Sandbox、ExecResult、Tool、ToolResult 原有签名/字段未改；文件同步、exec/Tool.run 异步 |
| 各自模块分工 | 接线使用预留 build_tools，未另建系统或改 Router；按后续明确请求修复 Agent 内部计时 |
| 既有测试风格 | 符合；unittest / IsolatedAsyncioTestCase / 临时目录；无新增依赖 |
| 英文代码说明、中文 README/docs | 符合主体风格；中文输入/路径/断言数据专门用于本次明确要求的 UTF-8 验证 |
| feat/<name>-<topic> 分支、PR 合并 main | 功能分支命名符合；main 的合并需经后续 PR 审阅 |
| 英文 feat:/fix: 提交标题 | 两次提交分别对应沙箱/工具实现与内部计时修复 |
| LF 行尾 | 沿用 .gitattributes；已检查修改源码行尾与 diff 空白检查 |
| CI / formatter / PR 模板 | 已检查的仓库未配置这些门禁，不能声称已通过远端 CI |

`tests/test_app.py` 的旧“工具为空”断言已更新为真实工具断言。
另将只适用于 socket 的 select 管道读取改成队列/线程，并为自动测试提供非交互 stdin，
解决 Windows 测试环境问题，原行为断言保留。这些是测试适配，不是修改 JIAN 的生产通信逻辑。

### 5. 需要交接给 JIAN 的内容

- **交付入口：** 功能分支 `feat/heyang-sandbox-tools` 的两次提交、本文、详细交接说明和可运行示例；
  后续创建 PR 时附上提交 hash 与测试结果。
- **可用工具：** Coder 四个文件工具；Researcher/Writer 为 read_file、write_file、list_files。
  所有路径参数叫 `path`；写入另需 `content`；列表 path 可省略，默认 `.`。
- **结果协议：** 预期错误为 ToolResult(ok=False)；write_file.files_written 是 workspace 相对路径，
  失败不报告产物；文件更新用覆盖写入。
- **文件交接：** Router 负责来源选择，import_file 接受可信外部源并复制到 inbox；
  源保留、目标不越界、同名拒绝覆盖。Task.files 原名称与 inbox 实际路径的映射必须让后续 Worker 知晓。
- **职责边界：** delete_file 只声明 requires_approval，后续 Worker 执行前负责 HITL 与取消检查。
  LocalSandbox 是开发执行基础，exec 仍有宿主权限，Docker 隔离留待后续。
- **已修复事项：** Agent 内部耗时使用高精度时钟，保留非零 Worker duration；公共接口不变，原断言保留。
- **待复核事项：** POSIX/符号链接补验；重复交接或不同源同 basename 的命名策略。

可复制发送的交接摘要（发送前补齐 PR 链接）：

> 第一阶段 LocalSandbox + 四个文件工具 + build_tools 接线已完成，基线 216191e，功能分支
> feat/heyang-sandbox-tools。现有 Router 可根据上游 TaskResult.artifacts 完成真实文件交接，
> 公共接口没有改动；按后续请求将 Agent 内部耗时统计改为 perf_counter，修复 Windows 短任务计时问题。
> Coder 获得四个文件工具，Researcher/Writer 获得读写和列表工具。
> 需注意 inbox 同名拒绝覆盖；Task.files 保留源名称，下游读取 inbox/<basename>。
> 最新全仓 286 项：284 通过、2 项符号链接权限跳过、0 失败。原 duration > 0 断言保留，
> 两项新增回归验证短任务耗时和 Worker 自报耗时保留；POSIX 也请在你的环境补验。
> 详细说明见 docs/report.md 和 docs/sandbox_tools_handoff.md；最小示例为
> python -X utf8 -m examples.sandbox_tools。PR 链接待补；后续再实现 Worker、DeepSeekClient 等。

### 6. 课程系统评测仍待完成

| 指标 | 当前状态 |
|---|---|
| Task completion rate | 未测；单元测试通过率不是任务完成率 |
| End-to-end execution time | 未测；上面的秒数是测试套件耗时 |
| Task failure modes | 尚未开展课程任务集评测 |
| Memory evolution | 本批未评估记忆进化效果 |
| Commit history screenshots | 待完成本批提交及后续持续开发后整理 |

---

## 第二阶段：Worker、HKGAI 客户端与执行工具（2026-11-17 至 2026-11-18）

记录人：LI Heyang。以下数字转录自 [execution_tools_handoff.md](execution_tools_handoff.md) 的"验证记录"，
环境 Windows / Python 3.11.15；原始命令和细节以该文件为准。第三阶段在另一台机器上重跑了全仓测试，见下一节。

| 交付 | 提交 | 专项回归 | 全仓 |
|---|---|---|---|
| 通用 Worker、拒绝与超时修复 | `9d65e30`、`75425e9`（PR #5、#6） | `tests/test_worker*.py`、`tests/test_task_lifecycle.py` | 主线 `8a62a7c`：337 通过，2 跳过 |
| `run_python`、`web_search`、`fetch_url`、`git`（上轮工具交付） | `67f0c71` | 42 项通过 | 381 项：379 通过，2 跳过 |
| HKGAI 客户端、两轮工具交互、应用接线（本轮） | `88ec982`、`666315e`（PR #7） | 52 项通过 | 386 项：384 通过，2 跳过 |

做了什么验证：HKGAI 客户端用真实的 `openai` SDK 加模拟 HTTP 响应，覆盖请求构造、文本和多工具响应、错误与取消；
两轮联调用例让真实 Worker 调用 `read_file`，断言匹配的 `tool_call_id` 和实际文件内容被送回模型；
工具用模拟 DNS、搜索服务、临时 Git 仓库及裸库；示例通过真实 Worker 和 LocalSandbox 运行了一个 Python 单元测试，
并覆盖人工拒绝 Git 后不启动命令；`fetch_url` 做过一次真实的免费 HTTPS 冒烟（从 Cloudflare 公网端点取得正文），
对 `example.com` 的解析返回保留地址，工具按地址检查返回失败。

当时没有验证：匿名 `GET /v1/models` 返回 HTTP 401；课程账户的权限、配额和模型的真实工具调用能力没有用密钥验证；
Brave 的实时搜索没有用凭据验证。

---

## 第三阶段：牵头协作、请求层、场景运行、搜索与 DeepSeek（2026-11-18）

记录人：JIAN Yimin。基线：LI Heyang 的 PR #7 合并后的主线 `295e441`，在此之上的未提交改动。

### 1. 范围

| 内容 | 说明 |
|---|---|
| 牵头协作（D18） | 删除 Orchestrator agent 和中心化循环；`LeadSelector` 选牵头者（一次 LLM 调用、按会话缓存、失败退回第一位成员）；牵头者是普通 `WorkerAgent`，多了 `call_<队友>` 和 `ask_human` |
| 请求层 | `RequestTracker`：总线观察者，处理未指定对象的人类消息、`/status`、`/cancel`，收集交付物，记录 `RootOutcome` |
| 团队与场景 | `mas/team.py` 读 `01_role_initialization.md` 格式；`mas/scenario.py` 依次发任务；`--team`、`--scenario`、`--auto` |
| 对话导出、`AutoResponder` | `data/transcripts/` 下完整对话；`AutoResponder` 从空壳实现为可用 |
| 工具接线 | 八个工具全部接入 `build_tools` |
| 搜索 | 有 key 用 Brave；没有或 Brave 不可用时用无 key 的多引擎搜索（`ddgs`） |
| DeepSeek | `DeepSeekClient`，`--llm deepseek` |
| 跨任务文件 | `Router.locate_file` 能找到同一会话里更早的 root 的产出 |
| 缺陷修复 | 见 §4 |

### 2. 验证环境与结果

环境：macOS（Darwin 25.4.0），Python 3.14.3；依赖 `openai` 3.55.0、`httpx` 0.28.1、`ddgs` 9.16.1、`prompt_toolkit` 3.0.53、
`python-dotenv` 1.2.4。测试使用临时目录、脚本化的 `MockLLM` 和模拟 HTTP，不调用真实模型，不需要人工输入。以下均为实际执行记录。

| 验证 | 命令 | 总数 | 通过 | 失败 | 跳过 | 耗时 |
|---|---|---:|---:|---:|---:|---:|
| 全仓 | `python -m unittest` | 421 | 419 | 0 | 2 | 22.6 s |
| 全仓（与第一阶段相同的发现方式） | `python -m unittest discover -s tests -q` | 421 | 419 | 0 | 2 | 22.6 s |

两项跳过都是 Windows 专用的测试（`test_preserves_high_bit_windows_exit_status`、
`test_root_is_canonical_after_windows_directory_creation`），在 Windows 上由第一、二阶段的环境覆盖。

本阶段新增或重写的测试：

| 模块 | 测试数 | 覆盖 |
|---|---:|---|
| `tests/test_lead.py` | 12 | 选牵头者（缓存、失败兜底、无效答案）；真实系统里牵头者委派、以自己的名义提问和汇报、Task 2 读到 Task 1 的文件；牵头失败的汇报 |
| `tests/test_requests.py` | 22 | 一个请求的完整流程、交付物收集和重名、缺失文件、牵头者崩溃、`/status`、`/cancel`、补充消息、取消后的新请求 |
| `tests/test_scenario.py` | 9 | 读场景、`AutoResponder`、无人值守地依次发两个任务并写对话记录、命令行选项 |
| `tests/test_team.py` | 8 | 团队文件解析（顺序、提示词、各种错误） |
| `tests/test_transcript.py` | 4 | 对话导出的内容与顺序、失败与私聊、自动保存、写不了时不报错 |
| `tests/test_memory_across_sessions.py` | 3 | 两次完整的程序运行之间记忆保留；失败教训保留；换数据目录就是另一份记忆 |
| `tests/test_web_tools.py` | 22（其中新增 8） | Brave 失败后的无 key 搜索、各引擎依次尝试、时间范围映射、缺少依赖时的提示 |
| `tests/test_app.py`、`test_router.py`、`test_human.py`、`test_memory.py` 等 | 改写 | 去掉 Orchestrator 后的接线、八个工具、DeepSeek 选择、牵头者的委派次数上限 |

对 Heyang 在第一阶段留下的**待复核项**的结果：他在 Windows 上因没有符号链接权限而跳过的两项
（`test_symlink_escape_including_nonexistent_child`、`test_symlink_cannot_redirect_target_outside_inbox`）
在 macOS 上**实际运行并通过**；POSIX 的进程组清理测试和 `run_python`、`git`、沙箱的 POSIX 命令执行测试也都通过。
两台机器合起来，所有平台专用测试都至少跑过一次。

### 3. 冒烟与其他检查

| 检查 | 结果 |
|---|---|
| `python -m mas --demo`，依次输入一个需要两个角色的请求、`run the tests`、`/status` | 牵头者把部分工作委派给队友并汇总，最终回复署牵头者的名字，交付物收集到 `output/`，对话记录写出；命令行不再显示请求层与牵头者之间的内部消息 |
| `python -m examples.sandbox_tools`、`python -m examples.execution_tools` | 通过（后者在真实 Worker 和沙箱里运行了一个 Python 单元测试） |
| 读取课程的三个场景文件夹（软件、新闻、基金） | 每个都读出 4 个成员和 2 个任务 |
| 真实的无 key 网络搜索，3 个查询（一个带"过去一年"，一个带"过去一个月"） | 每个返回 3 条结果；单个引擎时好时坏，所以做成多个引擎依次尝试 |
| `python -m compileall -q mas tests examples` | 通过 |
| `git diff --check` | 发现一个文件末尾多余的空行，已修复，重跑通过 |

### 4. 过程中发现并修复的问题

这些是自查和代码走读发现的，**不是**真实模型运行暴露的。

| 问题 | 后果 | 修复 |
|---|---|---|
| 文件交接只在同一个 root 里找 | Task 2 找不到 Task 1 的产出（"在现有系统上加看板"会失败） | `locate_file` 同时查同一会话里更早的 root，更晚的不会反向泄露 |
| 每个任务最多委派 2 次，牵头者也一样 | 牵头者协调 4 个角色、复核、返工很快就会撞上限 | 牵头者单独的上限 `max_lead_delegations`（16） |
| 单任务时限默认 180 秒 | 真实模型下一个任务做不完会被误判超时 | 默认改为 600 秒 |
| HKGAI 参数修复依赖 JSON 错误位置指向括号 | 在 Python 3.14 里该位置指向尾逗号本身（3.13 未测），两个测试失败，运行时带尾逗号的工具参数会被丢成 `{}` | 同时兼容两种行为 |
| 命令行显示 `[orchestrator] ...` 内部消息 | 对话里出现不属于团队的发言人 | 内部消息不显示，系统消息显示为 `[system]` |

### 5. 没有验证的

- **没有用真实模型运行过任何场景。** 牵头者会不会好好拆任务、该问老师时会不会问、真实的工具调用格式是否稳定，都没有数据。
  `.env` 里有 DeepSeek 的 key，但没有用它调用过；HKGAI 的 key 也没有验证。
- Brave 的实时搜索没有用 key 验证；无 key 搜索只测了 3 个查询，没有测在老师的网络下的表现。
- 新代码没有在 Windows 上重跑；Python 3.10 至 3.13 没有跑过（`requires-python >= 3.10`）。
- `DockerSandbox` 没有实现；`LocalSandbox` 不是安全边界。
- 记忆的**效果**（重复运行后是否变好）没有评估，只验证了它被保存和召回。
- 评测框架 `mas/eval/harness.py` 仍是空的。

---

## 课程评测指标的现状

| 指标 | 状态 |
|---|---|
| 任务完成率（Task completion rate） | **未测。** 单元测试通过率不是任务完成率。要用真实模型跑三个场景（各两个任务）及之后发布的测试集 |
| 端到端执行时间 | **未测。** 上面的秒数是测试套件的耗时。每个请求的耗时已经由 `RootOutcome` 和对话记录里的汇总表记录，等有真实运行即可得到 |
| 失败模式 | **未测。** 失败模式的分类（`llm_format`、`tool_error`、`timeout`、`max_steps`、`wrong_output`、`crash`）和记录都已实现，但还没有真实的失败样本；上节 §4 是自查发现的问题，不是运行统计 |
| 记忆进化 | 保存与召回已验证；**效果未评估**。需要对同一批任务在空记忆和有记忆两种情况下各跑一次 |
| 提交历史截图 | 待整理（课程要求每位成员的持续提交） |

### 下一步怎么测

1. 用真实模型跑三个场景：`python -m mas --scenario "<场景文件夹>" [--llm deepseek] [--auto]`。每次运行产生
   `data/transcripts/<场景>-<时间>.md`，里面有每个请求的成败、耗时、牵头者、交付物的汇总表。
2. 把完整对话和交付物交给模型评分（课程的做法），把"是否达成"填回报告。
3. 对同一场景在清空和保留 `data/memory/` 两种条件下各跑一次，比较完成情况和耗时，作为记忆进化的证据。
4. 实现 `mas/eval/harness.py`，对测试集自动汇总完成率、耗时的均值/中位数/最大值和失败模式计数。
5. 在 Windows 上重跑全仓测试，确认新代码在 Heyang 的环境下同样通过。
