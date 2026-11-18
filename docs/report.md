# Test Results & Performance Report

本报告按时间顺序记录**实际跑过**的测试，最新的在后面。每一节写明环境、命令、数字和没有测的东西。
LI Heyang 的两节保持原样；JIAN Yimin 的一节接在后面，并在最后一节汇总课程要求的评测指标现在测到了哪一步。

| 阶段 | 日期 | 负责人 | 环境 | 全仓测试 |
|---|---|---|---|---|
| [第一阶段：沙箱与文件工具](#第一阶段验收报告2026-11-13) | 2026-11-13 | LI Heyang | Windows，Python 3.11.15 | 286 项，284 通过，2 跳过，0 失败 |
| [第二阶段：Worker、HKGAI 与执行工具](#第二阶段worker-hkgai-客户端与执行工具2026-11-17-至-2026-11-18) | 2026-11-17 至 11-18 | LI Heyang | Windows，Python 3.11.15 | 386 项，384 通过，2 跳过，0 失败 |
| [第三阶段：牵头协作与场景运行](#第三阶段牵头协作请求层场景运行搜索与-deepseek2026-11-18) | 2026-11-18 | JIAN Yimin | macOS，Python 3.14.3 | 445 项，443 通过，2 跳过，0 失败 |
| [课程评测指标的现状](#课程评测指标的现状) | 2026-11-18 | | | 场景 3 跑过两次真实运行；场景 1、2 未跑 |

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
| 搜索 | 有 key 用 Brave；没有或 Brave 不可用时用无 key 的应急搜索（`ddgs`，一次 `auto` 调用，有期限和停手机制） |
| DeepSeek | `DeepSeekClient`，`--llm deepseek` |
| 跨任务文件 | `Router.locate_file` 能找到同一会话里更早的 root 的产出 |
| 缺陷修复 | 见 §4 |

### 2. 验证环境与结果

环境：macOS（Darwin 25.4.0），Python 3.14.3；依赖 `openai` 3.55.0、`httpx` 0.28.1、`ddgs` 9.16.1、`prompt_toolkit` 3.0.53、
`python-dotenv` 1.2.4。测试使用临时目录、脚本化的 `MockLLM` 和模拟 HTTP，不调用真实模型，不需要人工输入。以下均为实际执行记录。

| 验证 | 命令 | 总数 | 通过 | 失败 | 跳过 | 耗时 |
|---|---|---:|---:|---:|---:|---:|
| 全仓 | `python -m unittest` | 445 | 443 | 0 | 2 | 23.8 s |
| 全仓（与第一阶段相同的发现方式） | `python -m unittest discover -s tests -q` | 445 | 443 | 0 | 2 | 23.9 s |

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
| `tests/test_web_tools.py` | 29（其中新增约 15） | Brave 失败后的无 key 搜索、搜索和网页缓存、一次 `auto` 调用与时间范围映射、连续失败后停手、期限、缺少依赖时的提示 |
| `tests/test_eval.py` | 17 | 评测框架：记录、汇总、报告、超时算失败、重复运行与共享记忆；模拟人类；评分器的解析 |
| `tests/test_tools.py` | 新增 3 | `read_file` 分段读取长文件 |
| `tests/test_worker.py` | 新增 1、改写 1 | 步数预算提醒与最后一步不给工具；工具连续失败给提示而不打扰人类 |
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
| 真实的无 key 网络搜索，3 个查询（一个带"过去一年"，一个带"过去一个月"） | 每个返回 3 条结果（当时的实现是多个引擎依次尝试；后来发现 bing 和 google 在库里是禁用的，改成现在的一次 `auto` 调用，见 §7） |
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

第一次真实运行（§6）又暴露了四个问题，修复写在 §6 末尾。

### 5. 没有验证的

- **真实模型只跑过场景 3，两次。** 见 §6 和 §8：DeepSeek；第二次由模型扮演老师、模型评分，用的是并行委派等改动之前的代码。场景 1 和 2、HKGAI、有真人回答的运行还没有。
- Brave 的实时搜索没有用 key 验证；无 key 搜索只测了 3 个查询，没有测在老师的网络下的表现。
- 新代码没有在 Windows 上重跑；Python 3.10 至 3.13 没有跑过（`requires-python >= 3.10`）。
- `DockerSandbox` 没有实现；`LocalSandbox` 不是安全边界。
- 记忆的**效果**（重复运行后是否变好）没有评估，只验证了它被保存和召回。
- 评测框架 `mas/eval/harness.py` 仍是空的。


### 6. 第一次真实运行：场景 3（基金团队），DeepSeek，2026-11-18

条件：`python -m mas --llm deepseek --scenario <场景 3> --auto`，模型 `deepseek-chat`，搜索用无 key 方案（没配 Brave），
**无人值守，团队的所有问题都由 `AutoResponder` 用固定句子回答**（"proceed as described"、"try a different approach"），
记忆从空开始。用的是 §4 的修复之后、本节末尾的修复之前的代码。没有模型评分，下面的"质量"是我读产出的印象，不是评分。
这是一次运行，不是统计；评测框架当时还没写，数字是从对话记录里读出的。完整对话和两个请求的交付物在 [`docs/runs/2026-11-18-scenario3-deepseek/`](runs/2026-11-18-scenario3-deepseek/)。

| 请求 | 牵头者 | 结果 | 失败模式 | 耗时 | 委派的子任务 | 向人类提问 | 交付物 |
|---|---|---|---|---:|---|---:|---|
| Task 1 投资方案 | fund_manager | **失败** | `max_steps` | 595 s | 0/4 完成 | 6（1 次澄清，5 次求助） | 英文方案（14 KB）、中文客户说明（9 KB）、`model.py` |
| Task 2 半导体 HTML 幻灯片 | fund_manager | **失败** | `max_steps` | 1161 s | 6/10 完成 | 11（1 次澄清，10 次求助） | `risk_memo.md`、`client_talking_points.md`；**没有幻灯片** |
| 合计 | | 请求 0/2 | | 均值 878 s，最大 1161 s | 6/14（43%） | 17 | |

**做得好的地方。** 牵头者两次一开始就向人类提出了条理清楚的澄清问题（投资目标、期限、风险承受、限制、实现方式；受众、分析范围、约束），
并给出了默认值；人类只回答"proceed as described"后，它在方案里写明了"我做了这些假设，不对请告诉我"。
联网搜索确实在用（日志里有对美国遗产税、UCITS 与美国 ETF 预扣税、各 ETF 费率和规模的查询）。Task 1 的英文方案结构完整，有假设、
市场现状、配置和风险。我没有核实方案里的行情数字。教训机制起作用了：失败的研究和风险任务各自写出了"下次把任务拆小"之类的教训。

**失败的原因，按影响排序。**

1. **步数不够。** worker 12 步、牵头者 24 步，研究类任务每次搜索算一步，写不出东西就被截断，最终回复只剩一句无用的
   "worker step limit reached"。Task 2 里研究任务连续三次因此失败，牵头者最后没有产出幻灯片，只让队友写了对一份不存在的文稿的审阅备忘。
2. **工具失败被一路上报给人类。** 17 次提问里 15 次是"某工具连续失败两次，怎么办"，答案只能是"换个方法"。真实的老师会被这些技术问题反复打断。
3. **`fetch_url` 在那次运行里完全不能用。** 当时这台机器的代理把所有网站解析成 `198.18.x.x`，工具把它当非公网地址拒绝了。这是当时网络环境的问题，不是代码的问题；代理关闭后域名解析回到真实地址，我没有为它改代码（曾加过一个放行该网段的选项，后来删除了）。
4. **读长文件没有办法。** 审阅者拿到 14 KB 的方案，`read_file` 的输出被截到 4000 字符，于是它们各写了 5 个 `inspect*.py` 脚本去读后半部分，白白消耗步数。

**这次运行之后做的修复**（提交 `b007e19` 以及之后的提交）：

| 问题 | 修复 |
|---|---|
| 步数不够 | worker 30 步、牵头者 40 步；剩 3 步时提醒"停止探索、先写文件"；最后一步不给工具，必须用已有的内容给出最终结果并说明缺什么；提示词要求"尽早把已有的内容写进文件" |
| 牵头者把所有时间花在研究和审阅上 | 牵头者提示词：给队友一次只能做几步的活，大研究拆成几次；先把人类要的东西做出第一个完整版本写进文件，再改进和审阅 |
| 工具失败打扰人类 | 改成在工具返回里加提示，让模型自己换办法，不再向人类提问 |
| 读不了长文件 | `read_file` 分段返回，末尾说明下一段的 `offset` |

### 7. 无 key 搜索的两次修改

第一次真实运行里，`web_search` 平均 19 秒一次（共约 54 次，占了总时间的大半）。我先把它改成"同时问 bing、yahoo、google、duckduckgo，谁先有结果用谁"，并加了缓存。
第二次运行的控制台里出现大量警告：`bing - backends do not exist or are disabled ... Using 'auto'`。原来这个版本的 `ddgs`（9.16.1）里 bing 和 google 是被禁用的，
指名它们只会悄悄退回 `auto`。所以那次"并行问四个引擎"其实是两次 `auto` 加 yahoo 和 duckduckgo，请求重复，而我之前量出的"bing 3/5 成功、google 2/5"实际是 `auto` 的结果。
搜索能用，但配置和我写下的说明都不对。

现在改成最简单的形式：对 `ddgs` 只调一次 `auto`（库自己会并行问它的引擎），12 秒期限，连续失败 3 次后停手 30 秒并明确告诉成员"别等它，用 `fetch_url` 或写下已有的"；搜索和网页抓取都有缓存。
这是应急方案，等老师的搜索 API 到了会被取代。同一个网络上 8 个真实查询：6 个成功，平均 6.4 秒，最慢 9 秒（当时另一个评测正在同一个网络上运行，会加重限流）；失败的两个也在 9 秒内返回，并带着下一步怎么办的提示。


### 8. 第二次真实运行：场景 3，评测框架，DeepSeek（2026-11-18）

条件：`python -m mas.eval <场景 3> --llm deepseek --judge`。团队的所有模型调用、扮演老师的模型、给结果打分的模型都是 DeepSeek（`deepseek-chat`，实际是 `deepseek-flash`）。
代码是提交 `76208c8`：包含 §6 末尾的修复（worker 30 步、牵头者 40 步、剩 3 步提醒、工具失败不再问人、`read_file` 分段、时间构成记录），
**不包含**之后的并行委派、早停提醒、简化后的搜索、显式关闭思考、"工作区私有"提示和删除自己文件免批准。这次 `fetch_url` 可以用（代理已关闭）。
完整的评测报告、对话记录和两个请求的交付物在 [`docs/runs/2026-11-18-scenario3-eval-run2/`](runs/2026-11-18-scenario3-eval-run2/)。

| | 第一次（§6，手工读出） | 第二次（评测框架） |
|---|---|---|
| 请求完成 | 0/2（都是 `max_steps`） | **2/2** |
| 子任务完成 | 6/14（43%） | **24/29（83%）** |
| Task 1 耗时 | 595 s（失败） | 852 s |
| Task 2 耗时 | 1161 s（失败） | 2263 s |
| 平均耗时 | 878 s | 1558 s |
| 向老师提问 | 17（其中 15 次是工具失败的求助） | 4 |
| 模型评分 | 无 | Task 1 未达到（6/10），Task 2 达到（8/10），平均 7.0 |
| 整个运行 | 约 29 分钟 | 52 分钟（3123 s，含评分和扮演老师的调用） |

**怎么读这些数字。** 完成率从 0 到 100%，说明修复起了作用。但耗时变长了，因为任务这次真的做完了：上次失败得早，所以短。Task 2 的 37 分钟太长，下面分析。
评分的模型、扮演老师的模型和团队用的是同一个模型，评分可能偏宽；这只是一次运行、两个任务，不能当作统计结论。

**时间花在哪里**（评测框架记录的时间构成）：

| | 耗时 | 牵头者等队友 | 全队模型调用 | 全队模型时间 | 搜索 | 网页抓取 |
|---|---:|---:|---:|---:|---|---|
| Task 1 | 852 s | 772 s | 162 次 | 549 s | 55 次，249 s | 65 次，47 s |
| Task 2 | 2263 s | 1897 s | 352 次 | 1840 s | 83 次，310 s | 107 次，108 s |

- **模型调用是大头**：Task 2 里 352 次调用占了 1840 秒，平均每次 5.2 秒，比搜索加抓取的 418 秒多得多。上次以为搜索是主要瓶颈，这次看是调用次数和历史长度。
- **几乎没有并行**：全队模型时间加工具时间（Task 1 为 846 秒，Task 2 为 2261 秒）几乎正好等于耗时（852、2263），说明各成员基本是一个接一个干的。这次的代码没有并行委派，符合预期，也说明并行委派有很大的潜力。
- 牵头者自己的模型时间只有 75 秒和 363 秒，其余几乎都在等队友。

**质量（模型评分的理由，原文节选）。**

- Task 1 未达到：文档之间不一致，风险评估审阅的是 7 只基金的配置，而方案和客户说明用的是 6 只；汇率在 7.80 和 7.846 之间混用；风险经理的审阅指出每月 5000 港币的复利数字被高估约 2.5 倍，方案里仍然保留着。
  这对应 §6 之后发现的"审阅者读不到文件"的问题（牵头者没有把文件通过 `files` 交过去，审阅者只能凭记忆审阅另一个版本），那个问题在提交 `2007e72` 里用提示词修复，这次运行没有包含。
- Task 2 达到：交付了 18 页、可在浏览器里逐页翻看的 2026 年底半导体展望，有来源的研究、明确的投资含义（仓位大小、对冲）和风险部分，还有监控面板；残留的小问题是风险审阅者最后一次验证没能直接读到修改后的幻灯片，以及部分说明（用建模而非实际波动率、一条英伟达领导层信息未核实、台湾的穿透没算）是披露了而没有解决。

**其他观察。**

- Task 2 的交付物目录里有 13 个文件，包含 `fix2.py`、`fix3.py`、`check.py` 这类临时脚本。牵头者没有明确列出交付物，系统就收集了整个请求里所有成功任务写的文件，对评分的人不友好。
- 老师的提问只有 4 次，比上次的 17 次少得多，工具失败不再打扰老师。
- 抓取网页 172 次（Task 1 和 Task 2 合计）是搜索的一倍多，这次 `fetch_url` 是可用的，研究质量也看得出差别。

---

## 课程评测指标的现状

评测框架（`python -m mas.eval`）已经用在真实模型上跑过一次（§8）。以下是目前的数据点：**只有场景 3 一次运行、两个任务**，场景 1 和 2 没跑，修复之后的最新代码也还没有重跑。

| 指标 | 状态 |
|---|---|
| 任务完成率 | 第二次运行：**请求 2/2，子任务 24/29（83%）**；第一次：0/2，6/14。其中模型评分认为 1/2 的请求达到了要求，平均 7.0/10 |
| 端到端执行时间 | Task 1：852 s；Task 2：2263 s（37.7 分钟）；平均 1558 s。**偏长**：几乎全是串行，模型调用占 80% 以上 |
| 失败模式 | 第二次没有失败；第一次两个都是 `max_steps`（§6）。子任务的失败（5 个）没有逐个分类 |
| 记忆进化 | 保存与召回已验证；**效果未评估**，需要 `--repeat 2 --keep-memory` 的对比运行 |
| 提交历史截图 | 待整理 |

### 下一步怎么测

1. 用最新的代码重跑场景 3，和 §8 对比：并行委派、早停提醒、简化搜索、工作区私有提示、显式关闭思考都在里面，主要看耗时是否明显下降、Task 1 的一致性问题是否消失。
2. 再跑场景 1 和 2。
3. 同一场景加 `--repeat 2 --keep-memory`，作为记忆进化的证据。
4. 单独看 `--early-stop off` 的对比，判断提醒到底有没有用。
5. 在 Windows 上重跑全仓测试。
6. 测试集发布后用同一条命令跑。
