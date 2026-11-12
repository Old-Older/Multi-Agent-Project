# Test Results & Performance Report

## 第一阶段验收报告（2026-11-13）

范围：LI Heyang 的 LocalSandbox、四个文件工具、现有系统接线及相关测试。
基线为本次开发开始前 fetch 核对的 `origin/main = 216191e`，分支为
`feat/heyang-sandbox-tools`。本批按沙箱/工具与 Agent 计时修复拆成两次提交；
交付至功能分支供审阅，不直接合并 main。

结论：**本阶段指定验收通过，接口和接线方式与 JIAN 已合并代码兼容；
全仓回归存在一项原有 Windows 耗时断言失败，将在单独的计时修复提交中处理。**
本报告不表示 Worker、真实模型调用或完整课程评测已经完成。

### 1. 完成内容

| 内容 | 结果 |
|---|---|
| LocalSandbox | 文件读写、删除、列表、存在性、实际路径边界、inbox 导入、命令执行及清理均已实现 |
| 文件工具 | read_file、write_file、delete_file、list_files；错误转 ToolResult，写入报告真实产物 |
| 系统接线 | 沿用 build_tools/build_system；按角色顺序构造工具，已知待实现项警告并跳过，未知项报错 |
| 跨 agent 交接 | 真实 Bus、StateTable、Router 与 LocalSandbox；上游 artifact 可在下游 inbox 读取 |
| 文档与示例 | [详细交接说明](sandbox_tools_handoff.md)、[可运行示例](../examples/sandbox_tools.py)、接口说明更新 |

未扩展 Worker、DeepSeekClient、run_python、网络/Git 工具、Docker 执行或课程评测框架。
未修改 JIAN 负责的 Bus、Router、StateTable、SessionBoard、Agent 基类、Orchestrator 和记忆实现。

### 2. 验证结果

环境：Windows，Python 3.11.15；使用 unittest，未安装新依赖。测试使用临时目录、短命令和替身，
不调用真实 API，不需要人工输入。以下均为实际执行记录。

| 验证集合 | 总数 | 通过 | 失败 | 跳过 | 耗时 |
|---|---:|---:|---:|---:|---:|
| 文件阶段新增 + interfaces/app/Router 指定回归（此前） | 130 | 128 | 0 | 2 | 20.905s |
| 全项目 unittest discovery（duration 修复前，历史记录） | 284 | 281 | 1 | 2 | 32.585s |

上述集合有重叠，不能将数量相加。示例、compileall 和 git diff --check 已通过。

本阶段指定回归的实际命令：

```powershell
python -u -c "import faulthandler, unittest; faulthandler.dump_traceback_later(90, exit=True); unittest.main(module=None, argv=['unittest', 'tests.test_sandbox', 'tests.test_process_cleanup', 'tests.test_tools', 'tests.test_router_files', 'tests.test_interfaces', 'tests.test_app', 'tests.test_router', '-q'])"
```

全项目的实际命令（本提交仍有一项原有 duration 断言失败）：

```powershell
python -u -c "import faulthandler, unittest; faulthandler.dump_traceback_later(90, exit=True); unittest.main(module=None, argv=['unittest', 'discover', '-s', 'tests', '-q'])"
```

普通终端可使用 `python -m unittest discover -s tests -q`。本工具的受限执行环境曾阻塞 Windows asyncio
初始化的本地 socketpair；允许本地回环连接后完成验证。最初挂起的执行未计为通过。

**待修复的 Windows 耗时问题：** 原有 `RunLoopTest.test_task_roundtrip` 要求
`duration > 0`，但 Agent 使用 `time.monotonic()` 测量极短任务，本机时钟分辨率为 15.625ms，
可能得到 0.0。对应 Agent 代码和测试在本提交未改；计划在单独的 fix 提交中改用高精度时钟，
保持公共接口不变，并保留原断言及补充回归测试。

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
4. **审阅测试边界。** 指定回归 128 通过、2 项跳过；全量 281 通过、1 项原有 duration 断言失败、2 项跳过。
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
| 各自模块分工 | 接线使用预留 build_tools，未另建系统或改 Router、Agent 基类 |
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
- **待复核事项：** 原有 Agent duration 断言的 Windows 计时问题；POSIX/符号链接补验；重复交接命名策略。

可复制发送的交接摘要（发送前补齐 PR 链接）：

> 第一阶段 LocalSandbox + 四个文件工具 + build_tools 接线已完成，基线 216191e，功能分支
> feat/heyang-sandbox-tools。现有 Router 可根据上游 TaskResult.artifacts 完成真实文件交接，
> 公共接口和 Agent 基类没有改动。Windows 计时问题将通过独立的修复提交处理。
> Coder 获得四个文件工具，Researcher/Writer 获得读写和列表工具。
> 需注意 inbox 同名拒绝覆盖；Task.files 保留源名称，下游读取 inbox/<basename>。
> 指定回归 130 项：128 通过、2 项符号链接权限跳过。全仓 284 项：281 通过、1 项原有计时断言失败、
> 2 项跳过；POSIX 也请在你的环境补验。
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
