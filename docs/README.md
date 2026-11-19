# 文档索引

先读哪个，取决于你要做什么。**"现行"表示描述的是今天的代码；"历史"表示保留作过程记录，不要当作现状。**

| 文档 | 状态 | 读它来…… |
|---|---|---|
| [architecture.md](architecture.md)（[中文](architecture.zh-CN.md)） | 现行，课程要求的架构文档 | 了解系统怎么工作：路由与委派、人在回路、记忆与进化、沙箱、工具 |
| [report.md](report.md) | 现行，课程要求的测试与性能报告 | 看测过什么、结果如何、还没测什么；按时间顺序，最新的在后面 |
| [interfaces.md](interfaces.md) | 现行 | 写代码时查某个模块的接口、负责人、约定 |
| [design_decisions.md](design_decisions.md) | 历史（顶部有每项决定的现状表） | 了解某个设计为什么这么定，以及哪些后来被取代 |
| [sandbox_tools_handoff.md](sandbox_tools_handoff.md) | 历史交接（沙箱行为描述仍有效） | 沙箱与文件工具的细节、验证记录 |
| [execution_tools_handoff.md](execution_tools_handoff.md) | 现行 | `run_python`、网络、`git` 工具与 HKGAI 客户端的用法和验证记录 |
| [team_notes.md](team_notes.md) | 历史 | 两位成员之间公布过的接口变更 |

仓库根目录的 [README.md](../README.md)（[中文](../README.zh-CN.md)）讲怎么安装和运行；
[code_tour.html](../code_tour.html) 是代码导览动画，**写于取消 Orchestrator 之前，其中关于 Orchestrator 的章节已过时**。

## 写文档的约定

- 现行文档只写代码**现在**的样子；改了代码就改文档，不在文档里留"以前是……"。过程和理由放进 `design_decisions.md`。
- 测试结果只写**实际跑过**的：命令、环境、数字、没测的东西。
- 英文代码注释和提交标题；文档中文，面向课程的文档（架构、README）提供中英两版。
