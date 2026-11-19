# HKGAI 与执行工具联调交接

从仓库根目录运行下列命令即可开始。示例创建临时工作区，用 `MockLLM` 把一次 `unittest` 调用交给通用 Worker；打印的是该测试进程的退出码和输出。安装项目已有依赖后，离线联调无需密钥。

```console
python -X utf8 -m examples.execution_tools
```

## 把工具交给自己的 Worker

默认的 `mas.app.build_tools` 已按角色配置注册全部九个工具：`read_file`、`write_file`、`edit_file`、`delete_file`、`list_files`、`run_python`、`web_search`、`fetch_url`、`git`。`web_search` 用 DeepSeek 模型时走 DeepSeek 的搜索接口（同一把 key），否则（或 DeepSeek 答不了时）改用无需 key 的应急搜索（`ddgs` 包，只调一次，12 秒期限，连续失败 3 次后停手 30 秒），`git` 使用 `GITHUB_TOKEN`（`git push` 等操作执行前会向人类请求批准）。角色配置里出现不认识的工具名会直接报错。没有搜索 key 时 `web_search` 不会失败；所有引擎都没有响应时才返回错误，提示换个说法或稍后重试。

`examples.execution_tools.execution_worker_factory` 仍可使用，现在只是直接调用 `default_worker_factory`。

```python
from mas.app import build_system

system = build_system(settings, llm, human, roles=roles)    # 默认工厂就会注册这些工具
```

## HKGAIClient

`mas.app.make_llm(Settings.from_env())` 默认创建实现 `LLMClient` 的 `HKGAIClient`。直接导入使用 `from mas.llm.hkgai import HKGAIClient`。课程密钥通过 `HKGAI_API_KEY` 读取；`LLM_PROVIDER=deepseek`（或命令行 `--llm deepseek`）时改用 `DEEPSEEK_*` 并创建 `DeepSeekClient`，两套配置互不参与对方的认证和选模型。配置可放在进程环境或本地 `.env` 中，命令行与下方示例会读取仓库根目录的 `.env`。自写脚本直接调用 `Settings.from_env()` 时，可先调用 `dotenv.load_dotenv()`。

| 配置项 | 用途 |
| --- | --- |
| `LLM_PROVIDER` | 默认 `hkgai`，可省略。使用旧版 `.env` 的队友应更新此项。 |
| `HKGAI_API_KEY` | 必填，使用课程网关分配的模型密钥。 |
| `HKGAI_MODEL` | 默认 `t2_hkgai-v3_fp8_1m_e7`，可覆盖为该账号有权访问的其他模型。 |
| `HKGAI_BASE_URL` | 默认 `https://api1.hkgai.net/v1`。也可填课程发放的裸域名，客户端会补上 `/v1`；带路径的部署地址会保留该路径。 |

课程提供网关 `https://api1.hkgai.net` 和上述模型 ID。客户端通过项目已有的 `openai` Python SDK，向 `https://api1.hkgai.net/v1/chat/completions` 发送兼容格式的请求，密钥通过 Bearer 头传递。联调 Worker 和 Orchestrator 时，所选模型需要能返回项目自定义工具的 `tool_calls`。HKGAI Studio 的公开文档可用于参考聊天协议；课程部署的实际响应需用其账号验证。[HKGAI Studio 模型指南](https://hkgai-studio.prod.hkchat.app/en/docs/modelhub)

配置就绪后可从仓库根目录分别发送一次真实请求。第一条显示文本回复，第二条把 `list_files` 的 schema 发给模型，打印它返回的调用 ID、工具名和参数。示例止于显示模型回复。实际执行和审批由 Worker 负责。[示例源码](../examples/hkgai_chat.py)

```console
python -X utf8 -m examples.hkgai_chat
python -X utf8 -m examples.hkgai_chat --with-tools
```

`LLMResponse.text` 可以与多个 `tool_calls` 同时出现。每个调用保留 `id`、`name`、`raw_arguments` 及解析后的 `arguments` 字典。客户端可修复 JSON 代码围栏和尾逗号；无法恢复或顶层不是对象时返回空字典。整数用量计数在 `usage`，停止原因在 `finish_reason`。

直接构造时可设置 `timeout`（默认每次请求 60 秒）和 `max_retries`（默认首次请求后最多重试 3 次）。连接超时、限流及瞬时服务错误使用有界重试，遇到 `Retry-After` 会遵守服务端要求的等待时间；超过单次超时预算则直接返回错误。请求格式错误、无效密钥或不可用的模型应先检查配置。最终失败抛出 `LLMError`。调用方取消会向上传播。

## 工具参数与结果

四个工具均为 `await tool.run(sandbox, **kwargs) -> ToolResult`。模型通过 `tool.spec()` 获取参数 schema。成功时读取 `output`；网络工具的 `output` 为 JSON 字符串，可用 `json.loads` 解析。预期失败返回 `ok=False` 与诊断文本。

| 工具 | 参数 | 成功结果 |
| --- | --- | --- |
| `run_python` | `path` 或 `module` 二选一。可选 `args: list[str]`、`timeout`（正数秒，默认 60）。 | `output` 含退出码、stdout、stderr。非零退出与超时都返回失败。 |
| `web_search` | `query`（最多 600 字符、75 个词），可选 `count`（1–10，默认 5）、`freshness`（`pd` 近一天、`pw` 近一周、`pm` 近一月、`py` 近一年）。 | JSON 数组，每项有 `title`、`url`、`description`；未命中返回 `[]`。 |
| `fetch_url` | `url`，可选 `max_chars`（1–20000，默认 3000）。 | JSON 对象 `{url, title, text, truncated}`。`url` 为重定向后的来源，纯文本的 `title` 为空。 |
| `git` | `action` 为 `init / clone / status / diff / add / commit / log / push`。`clone` 必须带 `url`；`diff` 可带 `staged: bool`；`add` 必须带 `paths: list[str]`；`commit` 必须带 `message`；`push` 可带已配置的 `remote` 名，默认 `origin`。 | `output` 为结果文本；提交成功还返回 `refs["commit"]`，值为本次提交的完整哈希。`log` 读取最近 10 次提交。 |

**Python 和产物。** 先用 `write_file` 写脚本，再以工作区相对路径运行。测试可用 `module="unittest", args=["discover", "-s", "tests"]`；也可选当前解释器已安装的 `pytest`。脚本处理中文文件时可指定 `encoding="utf-8"`。参数逐项传给 `Sandbox.exec`。这四个工具均不填 `files_written`，Python 脚本自行生成的报告需由 Worker 在完成结果的 `artifacts` 中列出。当前执行后端用 `LocalSandbox`，子进程拥有宿主用户权限，适用于可信代码。

**网络与引用。** `WebSearch(deepseek_key=…)` 有 key 时把它作为 DeepSeek 搜索接口的令牌，只发往固定的 `api.deepseek.com`；DeepSeek 返回非 2xx、超时或连接失败时，以及没有 key 时，改用 `ddgs` 的 `auto` 模式搜索一次（它自己并行问多个引擎；这个库里 bing、google 是被禁用的，指名它们只会悄悄退回 `auto`），无需密钥。`FetchURL()` 无需密钥（给了 `deepseek_key` 时，网站以 401、403、406、429、451 或服务器错误拒绝本机，会再请 DeepSeek 的抓取接口读一次），接受公开 HTTP(S) 的文本、静态 HTML、JSON、XML；HTML 提取可见文本并保留标题。每次操作限时 20 秒，支持 gzip 和未压缩响应，传输数据与解压正文各限 1 MiB。网页超出字节或字符上限会置 `truncated=true`。网络读取直接连接经过检查的 IP，每次重定向重新校验地址；仅提供内部代理或将公网域名解析成保留 IP 的环境可能无法取页。搜索可取少量结果、抓取可调小 `max_chars`，以适配 Worker 的 `tool_output_max_chars` 观察长度。引用使用搜索项的 `url` 或抓取返回的最终 `url`。[DeepSeek 搜索与抓取接口](https://api-docs.deepseek.com/zh-cn/guides/search/)

**Git 与审批。** 使用系统 `git`，仓库根目录为该 Worker 的 workspace。`clone` 接受不含凭据、查询参数或片段的 HTTPS 仓库 URL，目标须为空目录；克隆后可直接使用 `origin`。也可以 `init` 后由维护者配置远端。提交需要 Git 用户名和邮箱。`push` 将当前分支的 `HEAD` 推到指定远端。示例工厂把现有 `GITHUB_TOKEN` 配置传给 `Git`；GitHub HTTPS 认证由子进程通过环境读取，请使用支持 `--config-env` 的 Git。其他远端沿用 Git 自身的认证设置。凭据应只保存在本地配置环境中。`Git.requires_approval=True` 覆盖全部动作，Worker 负责询问、取消及拒绝。直接调用底层 `Git.run` 的测试须自行管理授权。[Git 命令行配置文档](https://git-scm.com/docs/git/2.31.0)

下例展示工具参数。`box` 为调用方提供的 `LocalSandbox`，`settings` 为其运行配置。

```python
from mas.llm.base import LLMResponse, ToolCall
from mas.tools.python import RunPython
from mas.tools.web import FetchURL, WebSearch
import json

tests = await RunPython().run(box, module="unittest", args=["discover", "-s", "tests"])
print(tests.ok, tests.output)
found = await WebSearch(settings.deepseek_search_key()).run(box, query="open data research", count=3, freshness="pm")
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
python -X utf8 -m unittest tests.test_hkgai tests.test_hkgai_integration tests.test_run_python tests.test_web_tools tests.test_git_tool tests.test_execution_tools_example
python -X utf8 -m unittest
```

HKGAI 客户端回归使用真实 SDK 与模拟 HTTP 响应，覆盖请求构造、文本及多工具响应、错误和取消。两轮联调用例还让真实 Worker 调用 `read_file`，断言匹配的 `tool_call_id` 和实际文件内容被送回模型。匿名 GET `/v1/models` 返回 HTTP 401；课程账户的权限、配额和模型的真实工具调用能力尚未使用密钥验证。

本轮在 Windows / Python 3.11.15 上复测，HKGAI 客户端、两轮工具交互和应用接线共 52 项通过；全量 386 项，384 通过、2 跳过。离线工具示例成功运行了一个真实的 Python 单元测试。

**上轮工具交付记录（Windows / Python 3.11.15）**  主线基线 `8a62a7c` 为 337 通过、2 跳过。工具采用模拟 DNS、搜索服务、临时 Git 仓库及裸库；示例通过真实 Worker 和 LocalSandbox 运行 Python 测试，并覆盖人工拒绝 Git 后不启动命令。上轮专项回归 42 项通过，全量 381 项中 379 通过、2 跳过。

上轮另做了一次免费 HTTPS 冒烟，`fetch_url` 从 Cloudflare 公网端点取得了正文。对 `example.com` 的解析返回保留地址，工具按地址检查返回失败。DeepSeek 的搜索和抓取接口已用真实 key 验证过（见 `docs/runs/`）。
