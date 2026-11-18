<p align="right"><a href="README.md">English</a> | <b>简体中文</b></p>

# 进化型多智能体协作系统

一个后端框架：几个角色不同的 agent 与人类对话，自己拆分任务、互相委派，在各自的私有工作区里使用工具，
并从以往的任务中学习。这是香港科技大学 MAIE5221（NLP）的期末项目。

你用一份 Markdown 文件描述一个**团队**（有谁，各自负责什么）。你给团队一个请求，团队里会有一位成员**牵头**：
需求不清楚时向你提问，把工作的一部分交给队友，检查结果，最后向你汇报。每个 agent 都有自己的工作区和自己的记忆。

## 目录

- [工作原理](#工作原理)
- [仓库结构](#仓库结构)
- [环境与安装](#环境与安装)
- [如何启动](#如何启动)
- [定义你自己的团队](#定义你自己的团队)
- [一次运行留下什么](#一次运行留下什么)
- [配置](#配置)
- [测试](#测试)
- [文档](#文档)
- [项目规则与协作流程](#项目规则与协作流程)
- [当前状态](#当前状态)

## 工作原理

```
 你 ──"做一个订房系统"──▶ 群聊（消息总线）
                              │
                    RequestTracker（请求层）   只做记账，不调 LLM：开启请求，处理 /status 和 /cancel，
                              │                收集文件，记录结果
                    LeadSelector               一次 LLM 调用选出牵头者（按会话缓存，
                              │                失败时退回团队里的第一位成员）
                              ▼
                       牵头者（一个 WorkerAgent）
           ┌──────────────────┼───────────────────┐
      ask_human          call_<队友>            它自己的工具
   （在群里向你提问）   （通过 Router 委派）   （文件、Python、网络、git）
                              │
                 队友在各自的沙箱里工作，
                 也可以继续委派或向你提问
```

- **团队，不是老板。** 没有固定的协调者，牵头者按请求选出，所以换一个团队或换一种请求不需要改代码。
  同一个群里的后续请求沿用同一位牵头者。
- **Router。** 所有委派都经过同一段纯代码：检查限制（深度、循环、重试、超时），维护任务状态表，把文件从一个工作区交给另一个，
  把提问转给人类。它从不调用 LLM。
- **人在回路。** agent 在需求不清楚时、以及做有风险的事之前（删除文件、`git` 操作）会向你提问或请求批准。
  `/cancel` 可以终止一个请求，agent 在每一步都会检查是否已被取消。
- **记忆。** 每个 agent 有一份 JSONL 记录，保存任务和失败后总结的教训。类似的任务开始时会召回相关教训；
  决定把活交给谁的 agent 还能看到每位队友的近期表现简介。
- **隔离。** 每个 agent 有自己的工作区目录（`workspaces/<agent>/`），文件只能通过 Router 在 agent 之间流转。
- **工具。** `read_file`、`write_file`、`delete_file`、`list_files`、`run_python`、`web_search`（给了 key 就用 Brave Search，否则用无需 key 的应急搜索）、
  `fetch_url`、`git`（clone、add、commit、push，每次调用都需要你批准）。
- **LLM。** 课程的 HKGAI 网关（默认）或 DeepSeek，这是课程允许的两种，都是兼容 OpenAI 接口的对话服务。
  课程禁止使用 OpenAI 和 Anthropic 的 API。

## 仓库结构

```
.
├── mas/                       系统本体
│   ├── __main__.py            命令行入口：python -m mas
│   ├── app.py                 build_system()：把各部分组装起来；build_tools()
│   ├── config.py              Settings：所有可调的上限和路径
│   ├── team.py                从角色文件读入团队
│   ├── scenario.py            读入场景，并依次发出其中的任务
│   ├── demo.py                离线演示（替身 LLM 和替身 worker，不需要 API key）
│   ├── core/
│   │   ├── message.py         Message 与各类 payload、频道
│   │   ├── bus.py             消息总线（内存实现）
│   │   ├── router.py          委派、限制、文件交接、向人提问、取消（不调 LLM）
│   │   ├── state.py           任务状态表
│   │   ├── board.py           共享会话看板（进展、文件、人类原话）
│   │   ├── requests.py        RequestTracker：一个请求从到达到最终回复
│   │   ├── lead.py            LeadSelector：谁来牵头
│   │   ├── human.py           命令行（CliHumanIO）和 AutoResponder
│   │   └── transcript.py      把整场对话导出成 Markdown
│   ├── agents/
│   │   ├── base.py            Agent 基类（消息、状态、向人提问）
│   │   ├── worker.py          WorkerAgent：ReAct 循环、委派、审批、记忆
│   │   ├── roles.py           RoleConfig，以及演示和测试用的示例团队
│   │   └── virtual_tools.py   call_<队友>、decline、read_group、ask_human 的 schema
│   ├── tools/                 文件、Python、网络搜索与抓取、git
│   ├── sandbox/               每个 agent 的工作区（LocalSandbox；DockerSandbox 还是空壳）
│   ├── memory/                JsonlMemory：写入、召回、能力简介
│   ├── llm/                   HKGAIClient、DeepSeekClient、MockLLM、LLMClient 约定
│   └── eval/                  评测框架：harness、模拟人类、评分器；python -m mas.eval
├── tests/                     单元测试与端到端测试（python -m unittest）
├── examples/                  可直接运行的小例子（沙箱、执行工具、HKGAI 对话）
├── docs/                      设计决策、接口、架构、报告、交接记录
├── code_tour.html             代码导览动画（用浏览器打开）
├── pyproject.toml             包信息与依赖
├── .env.example               API key 模板
└── README.md / README.zh-CN.md
```

运行时系统还会创建 `workspaces/`（每个 agent 一个目录）和 `data/`（记忆、输出、对话记录、日志），
两者都已被 git 忽略。

## 环境与安装

- Python **3.10 或更高**
- `git` 在 `PATH` 里（仅当 agent 使用 git 工具时需要）
- 课程发放的 **HKGAI API key**，或你自己的 **DeepSeek API key**（真实运行需要；演示模式不需要）
- 可选：[Brave Search](https://brave.com/search/api/) 的 API key（让 `web_search` 结果更好，不配也能搜索），以及推送代码用的 GitHub token

```bash
git clone https://github.com/Old-Older/Multi-Agent-Project.git
cd Multi-Agent-Project

python3 -m venv .venv
source .venv/bin/activate           # Windows：.venv\Scripts\activate
python -m pip install -e .

cp .env.example .env                # 然后编辑 .env
```

`.env`（不要提交）：

| 变量 | 用途 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | 可选 | `hkgai`（默认）或 `deepseek`；命令行的 `--llm` 优先 |
| `HKGAI_API_KEY` | 使用 `hkgai` 的真实运行 | 课程网关的 key |
| `HKGAI_BASE_URL`、`HKGAI_MODEL` | 可选 | 默认 `https://api1.hkgai.net/v1` 和 `t2_hkgai-v3_fp8_1m_e7` |
| `DEEPSEEK_API_KEY` | 使用 `deepseek` 的真实运行 | 你的 DeepSeek key |
| `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` | 可选 | 默认 `https://api.deepseek.com` 和 `deepseek-chat` |
| `DEEPSEEK_THINKING` | 可选 | `off`（默认）要求 DeepSeek 不先思考再回答：更快，而且 agent 每一步都在调用工具；`default` 交给服务自己决定 |
| `SEARCH_API_KEY` | 可选 | Brave Search 令牌。没有它 `web_search` 用无 key 的应急搜索（通过 `ddgs` 走 DuckDuckGo 等：不需要 key 和账号，但更慢也不可靠，有些搜索会失败，agent 会绕过继续做）；有它就优先用 Brave，Brave 拒绝或不可用时自动改用无 key 搜索 |
| `GITHUB_TOKEN` | `git push` 到 GitHub | 只会通过 HTTPS 发给 github.com |

## 如何启动

**1. 没有 key 也能试。** 替身 LLM 和替身 worker 驱动真实的总线、Router、请求层和命令行：

```bash
python -m mas --demo
```

可以输入 `write a python script and a document`、`run the tests`、`write a script and push it`（会请求你批准）、
`/status`、`/cancel`，或 `/dm researcher find out about decorators`。

**2. 运行你自己的团队**（需要所选 LLM 的 key）：

```bash
python -m mas --team path/to/01_role_initialization.md      # 文件，或包含它的文件夹
```

**3. 运行一个场景**：一个文件夹，里面有角色文件和任务文件（课程的测试数据就是这个形状）。
先发出第一个任务，它结束后在同一个群里发出下一个，团队因此保留上下文。团队提问时你照常回答，输入 `/quit` 结束。

```bash
python -m mas --scenario "scenario_1_software_engineering 2"
python -m mas --scenario "scenario_1_software_engineering 2" --auto     # 无人值守
```

加 `--llm deepseek` 就用 DeepSeek 而不是课程网关。

加 `--auto` 时由 `AutoResponder` 用固定的默认答案回答所有提问（"proceed as described"、"yes" 等），
最后一个任务结束后自动退出。

命令行选项：

| 选项 | 含义 |
|---|---|
| `--demo` | 离线演示（除非加 `--keep`，每次启动都从干净状态开始） |
| `--team PATH` | 团队：角色文件，或包含 `01_role_initialization.md` 的文件夹 |
| `--scenario DIR` | 场景文件夹：团队和任务 |
| `--llm hkgai\|deepseek` | 用哪个 LLM（默认取 `LLM_PROVIDER`，否则 `hkgai`） |
| `--auto` | 无人值守；必须配合 `--scenario` |
| `--data-dir DIR` | 记忆、输出、对话记录放在哪里（默认 `./data`） |
| `--keep`、`--delay S` | 仅演示模式 |
| `-v` | 同时把日志打到屏幕上（日志总会写到 `<data-dir>/mas.log`） |

运行时可以输入的命令：

| 命令 | 作用 |
|---|---|
| *文字* | 对团队说话（成为一个新请求，或对正在进行的请求的补充） |
| `@dev 文字` | 直接给某一个 agent 派任务 |
| `/dm <agent> <文字>` | 与某个 agent 私聊 |
| `/status` | 查看当前任务进展 |
| `/cancel`、`/cancel <agent>` | 取消当前请求 / 取消与某个 agent 私聊里的任务 |
| `/reply <id> <答案>` | 回答一个提问（只有一个待答问题时可写 `/reply <答案>`） |
| `/help`、`/quit` | |

## 定义你自己的团队

团队文件是 Markdown，格式与课程的 `01_role_initialization.md` 相同：一张表确定成员的顺序，
每位成员有一个 `## 角色名 (agent_id)` 标题，后面跟一个围栏代码块，写他的提示词。

````markdown
| Agent ID | Role |
|---|---|
| `lead` | Technical Lead |
| `dev` | Software Developer |

## Technical Lead (lead)

```text
You are the technical lead of a software development team. You are responsible for ...
```

## Software Developer (dev)

```text
You are the software developer on a software development team. You are responsible for ...
```
````

成员数量不限，第一位是备用牵头者，每位成员都拥有全部八个工具。场景文件夹在此基础上增加任务文件
（`02_task_1.md`、`03_task_2.md` ……），每个文件用一个围栏代码块写人类要说的话。

## 一次运行留下什么

| 路径 | 内容 |
|---|---|
| `data/transcripts/<场景>-<时间>.md` | 完整对话：你说了什么、谁牵头、谁把什么委派给谁、团队问了你什么你怎么答、每个结果、每个请求怎么结束，末尾有汇总表。每个请求结束时重写一次，崩溃也不会丢。 |
| `data/output/<请求>-<时间>/` | 每个请求的交付物，从各 agent 的工作区收集而来 |
| `data/memory/<agent>.jsonl` | 每个 agent 的记忆 |
| `workspaces/<agent>/` | 每个 agent 的私有文件 |
| `data/mas.log` | 日志，内部错误的堆栈在这里 |

## 配置

所有上限都是 `mas/config.py` 里 `Settings` 的字段。可能需要调整的：

| 设置 | 默认值 | 含义 |
|---|---|---|
| `max_worker_steps` | 30 | worker 完成一个任务的 ReAct 步数 |
| `max_lead_steps` | 40 | 牵头者处理一个请求的 ReAct 步数 |
| `subtask_timeout_s` | 900 | 一个被委派任务的时限（等待人类的时间不计） |
| `lead_timeout_s` | 2400 | 一个完整请求的时限 |
| `max_delegation_depth`、`max_delegations_per_task`、`max_retries_same_goal` | 2、2、2 | 防止委派失控（worker 再委派的次数、同一目标的重试） |
| `max_lead_delegations` | 16 | 一个请求的牵头者可以委派的次数 |
| `early_stop_nudges`、`research_note_after`、`research_note_every` | 开、12、6 | 帮成员"够了就停"的提醒；`EARLY_STOP_NUDGES=0` 关闭 |
| `memory_recall_k` | 3 | 任务开始时召回的教训条数 |
| `sandbox_backend` | `local` | `docker` 尚未实现 |

> `LocalSandbox` 以你自己用户的权限执行命令，它把各 agent 的文件分开，但不是安全边界。
> 不要在重要的机器上运行不可信的团队。

## 测试

```bash
python -m unittest                      # 全部
python -m unittest tests.test_lead      # 单个模块
```

测试不需要 API key：LLM 由脚本（`MockLLM`）代替。`tests/test_lead.py`、`tests/test_requests.py`、
`tests/test_scenario.py` 会用真实的工作区跑完整的系统。

## 文档

| 文档 | 内容 |
|---|---|
| [`code_tour.html`](code_tour.html) | 代码导览动画，每个模块一章 |
| [`docs/design_decisions.md`](docs/design_decisions.md) | 设计决策及理由（D1 至 D18），以及哪些仍然现行 |
| [`docs/interfaces.md`](docs/interfaces.md) | 每个模块的接口、负责人、一个请求如何流转 |
| [`docs/README.md`](docs/README.md) | 文档索引，以及哪些文档描述的是今天的代码 |
| [`docs/architecture.zh-CN.md`](docs/architecture.zh-CN.md)（[English](docs/architecture.md)） | 系统架构：路由与委派、人在回路、记忆、沙箱、工具 |
| [`docs/report.md`](docs/report.md) | 测试结果与性能报告，按阶段记录 |
| [`docs/sandbox_tools_handoff.md`](docs/sandbox_tools_handoff.md)、[`docs/execution_tools_handoff.md`](docs/execution_tools_handoff.md) | 沙箱、文件工具，以及 Python / 网络 / git 工具 |
| [`docs/team_notes.md`](docs/team_notes.md) | 两位成员之间公布过的接口变更 |

## 项目规则与协作流程

课程规格要求：

- LLM 只能用课程的 HKGAI（或 DeepSeek）网关，不得使用 OpenAI 或 Anthropic 的 API。
- 文档和产出只用纯文本（`.md`、`.txt`）或代码，不处理 PDF、Word、PowerPoint。
- 界面保持极简：命令行、聊天机器人或简单的文本框。
- 每个 agent 有自己的记忆和自己的工作区。
- 评测框架要报告任务完成率和执行时间。

协作流程：`main` 受保护，在 `feat/<名字>-<主题>` 分支上开发并通过 pull request 合并。
两位成员每周都要小步、频繁地提交，提交历史会被评分。

## 当前状态

已可用：消息、路由、任务状态、会话看板、人在回路、带失败教训的每 agent 记忆、拥有八个工具的 worker、
牵头者选择与委派、团队与场景加载、对话导出、无人值守运行。

未完成：Docker 沙箱，以及在所有场景上的评测。评测框架已经有了（`python -m mas.eval`），但真实运行只做过场景 3（第一次：2 个请求都没完成；修复后：2/2 完成，子任务 83%，每个请求平均约 26 分钟，模型评分 7.0/10），所以还没有可靠的完成率和耗时结果（到底测过什么，见 [`docs/report.md`](docs/report.md)）。
