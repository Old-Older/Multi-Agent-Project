# 第一阶段交接：LocalSandbox 与文件工具

本批以已 fetch 核对的 `origin/main = 216191e` 为基线，在
`feat/heyang-sandbox-tools` 实现。公共方法签名、ExecResult、ToolResult、角色完整工具清单和
Router 均未改动。Worker、DeepSeekClient、run_python、网络/Git 工具、Docker 执行和评测框架留待后续。

## 最小调用

从仓库根目录执行：

```powershell
python -m examples.sandbox_tools
```

示例使用临时目录，无 API、网络或人工输入；完整代码见
[`examples/sandbox_tools.py`](../examples/sandbox_tools.py)。核心调用为：

```python
from pathlib import Path
from mas.sandbox import LocalSandbox
from mas.tools import WriteFile, ReadFile
from mas.agents.roles import ROLES
from mas.app import build_tools
from mas.config import Settings

# 放在 async 函数中；root 由调用方选择。
researcher = LocalSandbox("researcher", Path("workspaces/researcher"))
coder = LocalSandbox("coder", Path("workspaces/coder"))
result = await WriteFile().run(researcher, path="notes.md", content="中文笔记")
if not result.ok:
    raise RuntimeError(result.output)
assert result.files_written == ["notes.md"]
imported = coder.import_file(researcher.resolve(result.files_written[0]))
assert imported == "inbox/notes.md"
observation = await ReadFile().run(coder, path=imported)
print(observation.ok, observation.output)
tools = {t.name: t for t in build_tools(ROLES["coder"], Settings())}
```

同一个目标名第二次导入会失败；可显式传入另一个 `name`，或由上层按授权流程管理旧文件。

## 路径、文件与导入约定

- 构造时自动创建 workspace，`root` 保存为解析后的绝对路径。`agent_id` 不自动拼接路径；
  `build_system` 已将各角色分配到 `settings.workspaces_dir/<agent_id>`。
- 文件方法保持同步，`exec` 和 `Tool.run` 保持异步。正常使用 workspace 相对路径；
  绝对路径只有解析后仍在 workspace 内才接受。`resolve` 先解析 `..`、符号链接等实际路径，再检查边界；
  越界抛 `PermissionError`，不使用字符串前缀比较。
- UTF-8 文本读写保留换行；`write_text` 自动创建父目录，覆盖已有文件，允许空内容。
  `delete` 只删除文件，不递归删除目录。文件方法跟随 workspace 内的符号链接，删除也作用于解析后的目标。
- `list_dir` 返回按 Python 字符串顺序排序的**直接子项名称**（文件、目录、隐藏项），不递归、无绝对路径。
  `exists` 对缺失路径返回 False，目录返回 True；越界仍抛异常。
- 读取/删除缺失文件、列出缺失目录抛 `FileNotFoundError`；把文件当目录抛 `NotADirectoryError`；
  删除目录抛 `IsADirectoryError`。读写目录或其他 OS 权限错误抛相应 `OSError` 子类。
  非 UTF-8 内容读取抛 `UnicodeDecodeError`。空/NUL 路径抛 `ValueError`，非字符串路径/内容抛 `TypeError`。
  Windows 设备名、NTFS 备用数据流以及末尾带点/空格的文件路径分量不支持（避免 OS 静默改名）。
- `import_file(src, name=None)` 允许**可信调用方**提供 workspace 外的源路径；这是文件 API 的显式来源边界例外，
  不是给模型任意外部文件访问权限。Router 负责根据 requester、root 和 `TaskResult.artifacts` 选择源。
  源必须是已存在的普通文件，按字节复制，源保持不变；缺失抛 `FileNotFoundError`，目录抛 `IsADirectoryError`。
- 默认目标为 `inbox/<src.name>`，自定义 `name` 可含子目录，但必须为相对路径，解析后严格留在实际
  `workspace/inbox/` 内。不能用 `../`、绝对路径或符号链接将目标重定向到 inbox 外，哪怕仍在 workspace 内。
  返回规范化的 workspace 相对路径，分隔符为 `/`。
- **同名冲突拒绝覆盖**：目标已存在时抛 `FileExistsError`，保留源与原目标。
  用独占创建防止并发导入覆盖；复制失败清除本次未完成的目标文件。创建过的空父目录可保留。

## 工具 schema 和结果

工具类从 `mas.tools` 导入：`ReadFile`、`WriteFile`、`DeleteFile`、`ListFiles`。
各 schema 的根为 `type: object`，`additionalProperties: false`；`path` 为非空字符串
（`type: string, minLength: 1`）。运行时检查与 schema 一致，额外参数、缺失参数或错误类型都返回失败。

| 工具名 | 参数与 required | 成功 output | files_written | requires_approval |
|---|---|---|---|---|
| read_file | `path`，必填 | 原始文本 | `[]` | False |
| write_file | `path`、`content`，均必填；content 为字符串，可为空 | `Wrote <相对路径>` | 实际目标的规范相对路径 | False |
| delete_file | `path`，必填 | `Deleted <传入路径>` | `[]` | True |
| list_files | `path` 可选，默认 `.` | JSON 字符串数组，保留中文 | `[]` | False |

所有文件操作经过 Sandbox。预期的路径、权限、编码、参数和 I/O 错误返回
`ToolResult(ok=False, output="工具名: 异常类型: 说明", files_written=[])`，不声称产出了文件；
`refs` 默认为空。`delete_file` 本身不询问人类；后续 Worker 执行前负责取消检查与 HITL 授权。

## exec 行为和隔离限制

`await sandbox.exec([executable, arg1, ...], timeout=60.0, env={...})` 不通过 shell，cwd 为 workspace，
stdin 关闭；继承宿主环境并用 env 覆盖，不修改父进程环境。使用绝对可执行文件路径更便于跨平台复现。
stdout/stderr 按 UTF-8 解码（无效字节替换）；需要中文输出的 Python 命令可传 `-X utf8`。

| 情况 | returncode | timed_out | 输出/异常 |
|---|---|---|---|
| 正常/非零退出 | 实际退出码 | False | 捕获 stdout 和 stderr |
| 超时 | -1 | True | 保留截至清理时收集的输出 |
| 无法启动命令或建立进程清理设施 | 127 | False | stderr 说明原因 |
| 无效 cmd、非正/非有限 timeout、非法 env | — | — | ValueError，未启动命令 |
| 调用方取消协程 | — | — | 清理后继续抛 CancelledError |

Windows 使用带 stdin 启动门的独立 Python 引导进程：加入 kill-on-close Job Object 后才启动请求命令，
关闭 Job 清理整棵进程树。POSIX 使用新会话/进程组并在清理时 killpg。父进程退出但子进程仍占用输出管道时，
超时仍能触发清理。正常结束也清理留在相同 Job/进程组中的后台进程，不支持有意留下后台服务。

LocalSandbox 是开发用目录边界，不是 OS 安全沙箱。exec 仍以宿主用户权限运行，可以访问 workspace 外的文件、
网络和继承的环境变量；无容器、资源配额或输出大小限制。文件检查不抵抗并发恶意替换链接（TOCTOU）或硬链接别名，
POSIX 主动脱离进程组的恶意子进程也不在保证范围。处理不可信代码需后续 DockerSandbox；其 exec 本次仍未实现。

## 系统接线与 Router 接入

`build_tools` 按 `role.tool_names` 顺序创建新实例，保留配置完整清单：

| 角色 | 当前实际工具 | 已知待实现，WARNING 后跳过 |
|---|---|---|
| Coder | read_file、write_file、delete_file、list_files | run_python、git |
| Researcher | read_file、write_file、list_files | web_search、fetch_url |
| Writer | read_file、write_file、list_files | 无 |

未知名称抛 `ValueError`，不注册成功占位工具。沿用 `build_system`、`default_worker_factory`、
`default_sandbox_factory`，未改通信、路由、状态、看板、Agent 基类、Orchestrator 或记忆模块。

Router 先查请求者 workspace，再查当前 root 中报告对应 artifact 的 agent（最新结果优先）。
导入目标使用源名称的 basename；**`Task.files` 仍保留原始源名称**，不会更新为 `import_file` 的返回路径。
后续 Worker 应读取 `inbox/<basename>`。源不存在/越界在来源查找阶段被拒绝；目标冲突等复制错误返回
`TaskResult(success=False, failure_mode=TOOL_ERROR, error="cannot hand over files: ...")`，不会派发下游。
多文件导入不是事务，后面的导入失败不会撤销前面已经复制的文件。

无需公共接口变更即可完成本批。下一阶段需要双方落实的具体事项：Worker 对源名称到 inbox 路径的映射，
重复交接/不同源同 basename 的命名策略，以及 Worker 在删除前遵守 `is_cancelled`、`CANCELLED_ANSWER`
和现有 `request_human` 约定。本批的拒绝覆盖策略已实现并测试；若以后希望自动覆盖或改写 Task.files，应双方另行对齐。

## 验证与 PR 说明

验证日期：2026-11-13（Asia/Shanghai）。Windows / Python 3.11.15，当前解释器已有
openai 2.24.0、python-dotenv 1.2.2、prompt_toolkit 3.0.52；没有 pip/pytest，使用标准库 unittest，
未安装或改动依赖。所有新增测试使用临时目录、本地短命令或 Worker 替身，不访问真实 API、网络服务或人工输入。

文件阶段指定回归命令（此前执行，faulthandler 用于诊断意外挂起）：

```powershell
python -u -c "import faulthandler, unittest; faulthandler.dump_traceback_later(90, exit=True); unittest.main(module=None, argv=['unittest', 'tests.test_sandbox', 'tests.test_process_cleanup', 'tests.test_tools', 'tests.test_router_files', 'tests.test_interfaces', 'tests.test_app', 'tests.test_router', '-q'])"
```

结果：**130 项，128 通过，2 跳过，0 失败/错误，20.905 秒**。两项跳过为真实符号链接越界测试，
本机创建符号链接报 `WinError 1314`（缺少权限），未将它们计为通过。其余包含中文文件操作、实际路径边界、
缺失/冲突/复制与关闭失败、命令输出与环境、超时与子进程清理、连续取消、Windows 高位退出码、
工具 schema/产物、组装后文件操作、真实 Router 交接及指定的接口/app/Router 回归。

另外执行并通过：

```powershell
python -X utf8 -m examples.sandbox_tools
python -m compileall -q mas tests examples
git diff --check
```

环境定位记录：最初受限执行的异步测试在 Windows asyncio 初始化的 `socket._fallback_socketpair -> accept`
挂起，已诊断并终止，未报告为通过。允许本地回环连接后，上述汇总测试正常完成，无需改业务层事件循环。
POSIX 执行分支未在本机实测；真实 API、Worker、Docker 等后续能力未验证。
全仓 discovery 结果：284 项，281 通过、2 跳过、1 项原有 Agent duration 断言失败，32.585 秒。
本机 `time.monotonic()` 分辨率为 15.625ms，短任务可能得到零耗时；此问题留给单独的 fix 提交，
不改本批文件接口。详见 [验收报告](report.md)。全量实际命令：

```powershell
python -u -c "import faulthandler, unittest; faulthandler.dump_traceback_later(90, exit=True); unittest.main(module=None, argv=['unittest', 'discover', '-s', 'tests', '-q'])"
```

修改文件：

| 文件 | 内容 |
|---|---|
| `mas/sandbox/base.py`、`mas/sandbox/_process.py`、`mas/sandbox/__init__.py` | 文件操作、导入、执行及清理、导出 |
| `mas/tools/files.py`、`mas/tools/__init__.py` | 四个文件工具、schema、错误转换与导出 |
| `mas/app.py` | 现有 build_tools 接线 |
| `tests/test_sandbox.py`、`tests/test_process_cleanup.py` | 真实文件、导入与进程测试 |
| `tests/test_tools.py`、`tests/test_router_files.py` | 工具契约、真实 Router 交接测试 |
| `tests/test_app.py` | 真实工具断言、接线验证及 Windows 测试适配 |
| `examples/sandbox_tools.py` | 可直接运行的最小示例 |
| `README.md`、`docs/interfaces.md`、`docs/report.md`、本文 | 更新实施状态、约定、验收结果和交接说明 |

占位断言更新：`tests/test_app.py` 的 `coder.tools == {}` 改为验证三个角色真实工具集合，
另用默认组装的工具在真实 LocalSandbox 中写入/读回中文。原有 CLI 子进程测试使用的
`select.select(pipe)` 不支持 Windows，测试改用队列与读取线程，保留原断言并确认线程和进程退出。
app 自动测试还显式提供非交互 stdin，避免有 isatty 标记但无 Windows 控制台缓冲区的宿主触发 CLI 初始化错误。

建议 PR 标题：`feat: implement local sandbox and wire file tools`

PR 内容：实现 workspace 边界、UTF-8 文件操作、inbox 独占导入和带进程树清理的本地命令执行；
新增四个文件工具，按角色接入现有 build_tools，跳过并警告已知未实现工具，拒绝未知工具名。
指定回归与新增测试共 130 项：128 通过，2 项因本机符号链接权限跳过；可运行示例、编译和 diff 检查通过。
全仓回归 284 项：281 通过、2 项符号链接权限跳过、1 项原有 Windows duration 断言失败，待单独修复。
覆盖真实 Router 文件交接、工具参数/产物、超时和回归测试；POSIX 执行未实测。后续范围为 Worker、DeepSeekClient、
run_python、网络/Git 工具及容器隔离，不在本 PR 扩展。
