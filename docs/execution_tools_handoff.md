# DeepSeek 与执行工具联调交接

从仓库根目录运行下列命令即可开始。示例创建临时工作区，用 `MockLLM` 把一次 `unittest` 调用交给通用 Worker；打印的是该测试进程的退出码和输出。安装项目已有依赖后，离线联调无需密钥。

```console
python -X utf8 -m examples.execution_tools
```

## 把工具交给自己的 Worker

从仓库源码运行时，可把示例中的工厂传给现有 `build_system`。`roles` 使用调用方的角色配置，每个 Worker 只拿到自身 `tool_names` 选中的工具。工厂同时支持已有的四个文件工具。[完整可运行示例](../examples/execution_tools.py)

```python
from examples.execution_tools import execution_worker_factory
from mas.app import build_system

system = build_system(settings, llm, human, roles=roles,
                      worker_factory=execution_worker_factory)
```

`make_llm(settings)` 已接入 `DeepSeekClient`。默认 `mas.app.build_tools` 仍将 `run_python`、`web_search`、`fetch_url` 和 `git` 列为待实现并跳过，直接启动 CLI 会看到对应警告。以后启用默认接线的最小改动为在 `mas/app.py` 的 `build_tools` 按原顺序实例化这四个工具，并更新 `tests/test_app.py` 中断言跳过工具及默认工厂工具清单的用例。这两处留待团队确认。

## DeepSeekClient

```python
from mas.app import make_llm
from mas.config import Settings
from mas.tools.python import RunPython

# 在已有 async 函数中运行；真实调用会使用 DeepSeek 账户。
settings = Settings.from_env()
llm = make_llm(settings)
reply = await llm.chat(
    [{"role": "user", "content": "怎样运行工作区里的 unittest？"}],
    tools=[RunPython().spec()], temperature=settings.temperature,
)
for call in reply.tool_calls:
    print(call.id, call.name)  # 参数对象在 call.arguments
```

- `Settings.from_env()` 读取进程环境。若在自写脚本里使用本地 `.env`，先调用 `dotenv.load_dotenv()`。真实服务使用 `LLM_PROVIDER=deepseek`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）和 `DEEPSEEK_MODEL`。安装时沿用项目声明的 `openai` 兼容 SDK，请求发往配置的 DeepSeek 地址。
- 原项目模型默认值是 `deepseek-chat`，客户端会原样发送模型名。截至 2026-11-18，官方文档列出 `deepseek-flash` 和 `deepseek-v4-pro`；连接当前官方服务时可在环境里设置 `DEEPSEEK_MODEL=deepseek-flash`。请求显式使用非思考模式，以匹配共享消息历史的字段。[DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion/)
- `LLMResponse.text` 可以与多个 `tool_calls` 同时出现。每个调用保留 `id`、`name`、`raw_arguments` 及解析后的 `arguments` 字典。客户端可修复 JSON 代码围栏和尾逗号；无法恢复或顶层不是对象时返回空字典。整数用量计数在 `usage`，停止原因在 `finish_reason`。
- 直接构造时可设置 `timeout`（默认每次请求 60 秒）及 `max_retries`（默认首次请求后最多重试 3 次）。连接、超时、408/409/429 及服务端错误指数退避重试，永久 HTTP 错误或损坏的响应返回 `LLMError`。调用方取消会向上传播。错误信息省略服务响应正文和认证数据。

## 工具参数与结果

四个工具均为 `await tool.run(sandbox, **kwargs) -> ToolResult`。模型通过 `tool.spec()` 获取参数 schema。成功时读取 `output`；网络工具的 `output` 为 JSON 字符串，可用 `json.loads` 解析。预期失败返回 `ok=False` 与诊断文本。

| 工具 | 参数 | 成功结果 |
| --- | --- | --- |
| `run_python` | `path` 或 `module` 二选一。可选 `args: list[str]`、`timeout`（正数秒，默认 60）。 | `output` 含退出码、stdout、stderr。非零退出与超时都返回失败。 |
| `web_search` | `query`（最多 600 字符、75 个词），可选 `count`（1–10，默认 5）、`freshness`（`pd` 近一天、`pw` 近一周、`pm` 近一月、`py` 近一年）。 | JSON 数组，每项有 `title`、`url`、`description`；未命中返回 `[]`。 |
| `fetch_url` | `url`，可选 `max_chars`（1–20000，默认 3000）。 | JSON 对象 `{url, title, text, truncated}`。`url` 为重定向后的来源，纯文本的 `title` 为空。 |
| `git` | `action` 为 `init / clone / status / diff / add / commit / log / push`。`clone` 必须带 `url`；`diff` 可带 `staged: bool`；`add` 必须带 `paths: list[str]`；`commit` 必须带 `message`；`push` 可带已配置的 `remote` 名，默认 `origin`。 | `output` 为结果文本；提交成功还返回 `refs["commit"]`，值为本次提交的完整哈希。`log` 读取最近 10 次提交。 |

**Python 和产物。** 先用 `write_file` 写脚本，再以工作区相对路径运行。测试可用 `module="unittest", args=["discover", "-s", "tests"]`；也可选当前解释器已安装的 `pytest`。脚本处理中文文件时可指定 `encoding="utf-8"`。参数逐项传给 `Sandbox.exec`。这四个工具均不填 `files_written`，Python 脚本自行生成的报告需由 Worker 在完成结果的 `artifacts` 中列出。当前执行后端用 `LocalSandbox`，子进程拥有宿主用户权限，适用于可信代码。

**网络与引用。** `WebSearch(api_key=settings.search_api_key)` 使用 `SEARCH_API_KEY` 作为 Brave Search 订阅令牌，只发往固定搜索端点。`FetchURL()` 无需密钥，接受公开 HTTP(S) 的文本、静态 HTML、JSON、XML；HTML 提取可见文本并保留标题。每次操作限时 20 秒，支持 gzip 和未压缩响应，传输数据与解压正文各限 1 MiB。网页超出字节或字符上限会置 `truncated=true`。网络读取直接连接经过检查的 IP，每次重定向重新校验地址；仅提供内部代理或将公网域名解析成保留 IP 的环境可能无法取页。搜索可取少量结果、抓取可调小 `max_chars`，以适配 Worker 的 `tool_output_max_chars` 观察长度。引用使用搜索项的 `url` 或抓取返回的最终 `url`。[Brave Web Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get)

**Git 与审批。** 使用系统 `git`，仓库根目录为该 Worker 的 workspace。`clone` 接受不含凭据、查询参数或片段的 HTTPS 仓库 URL，目标须为空目录；克隆后可直接使用 `origin`。也可以 `init` 后由维护者配置远端。提交需要 Git 用户名和邮箱。`push` 将当前分支的 `HEAD` 推到指定远端。示例工厂把现有 `GITHUB_TOKEN` 配置传给 `Git`；GitHub HTTPS 认证由子进程通过环境读取，请使用支持 `--config-env` 的 Git。其他远端沿用 Git 自身的认证设置。凭据应只保存在本地配置环境中。`Git.requires_approval=True` 覆盖全部动作，Worker 负责询问、取消及拒绝。直接调用底层 `Git.run` 的测试须自行管理授权。[Git 命令行配置文档](https://git-scm.com/docs/git/2.31.0)

下例展示工具参数。`box` 为调用方提供的 `LocalSandbox`，`settings` 为其运行配置。

```python
from mas.llm.base import LLMResponse, ToolCall
from mas.tools.python import RunPython
from mas.tools.web import FetchURL, WebSearch
import json

tests = await RunPython().run(box, module="unittest", args=["discover", "-s", "tests"])
print(tests.ok, tests.output)
found = await WebSearch(settings.search_api_key).run(box, query="open data research", count=3, freshness="pm")
if found.ok:
    sources = json.loads(found.output)
    if sources:
        page = await FetchURL().run(box, url=sources[0]["url"], max_chars=2000)
        if page.ok:
            article = json.loads(page.output)
            print(article["url"], article["text"])

# 仓库已暂存 notes.md 时，可把这个响应放入 MockLLM 的脚本以测试 Worker 审批。
commit_request = LLMResponse("", [ToolCall("save-notes", "git", {
    "action": "commit", "message": "Add research notes",
})])
```

## 验证记录

```console
python -X utf8 -m unittest tests.test_deepseek tests.test_run_python tests.test_web_tools tests.test_git_tool tests.test_execution_tools_example
python -X utf8 -m unittest
```

Windows / Python 3.11.15，主线基线 `8a62a7c`。基线 337 通过、2 跳过。客户端测试使用真实 SDK 与模拟 HTTP 传输；网络工具模拟 DNS、搜索服务和网页；Git 测试使用临时本地仓库和裸库；示例通过真实 Worker 和 LocalSandbox 运行 Python 测试，另有人工拒绝 Git 后不启动命令的回归。新增专项回归 42 项全部通过。最终全量 381 项，379 通过、2 跳过。

另做一次免费的公开 HTTPS 冒烟，`fetch_url` 成功从 Cloudflare 公网端点取得正文。当前网络对 `example.com` 返回保留地址，该次请求按地址检查返回失败。DeepSeek 和 Brave 的账号、额度、模型可用性及实时搜索质量尚待持有相应凭据的队友验证。项目远端推送未参与测试。
