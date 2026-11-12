# Test Results & Performance Report

## 第一阶段验收报告（2026-11-13）

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
