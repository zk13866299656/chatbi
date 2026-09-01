# ChatBI 设计文档

## 1. 设计目标

解决"业务取数以天计"的传统瓶颈:让不会 SQL 的业务人员用自然语言获得可信的数据答案。
"可信"是第一原则——所有数字必须来自真实执行的 SQL,LLM 只负责语言层工作。

## 2. 工作流节点职责

| 节点 | 职责 | LLM | 降级策略 |
|---|---|---|---|
| supervisor | 意图分类(query/attribution/chitchat)、问题改写、时间窗解析 | 是 | 规则:关键词分类 + 正则时间解析(上个月/最近N天/具体月份) |
| dispatch_query | query 链路分发,扇出两个并行检索分支 | 否 | - |
| retrieve_schema | 检索相关表结构文档 | 否(TF-IDF) | - |
| retrieve_caliber | 检索指标口径 + few-shot 示例(带相似度) | 否(TF-IDF) | - |
| generate_sql | 基于 schema+口径+示例生成 SELECT | 是 | 示例相似度 ≥0.35 时复用其 SQL;否则 no_sql |
| validate_sql | 安全校验:单条 SELECT/白名单/黑名单/行数上限 | 否 | - |
| repair_sql | 校验/执行失败时带错误信息修复,限 1 次 | 是 | 降级模式直接走兜底 |
| execute_sql | EXPLAIN 预检 + 线程池执行 + 行数截断 | 否 | - |
| recommend_chart | 结果集形状规则推荐图表(时序→折线,少量类别→饼图,其余→柱状) | 否 | 纯规则 |
| summarize | 基于结果写 2-4 句结论 | 是 | 规则摘要(极值/合计)+ 数据表展示 |
| attribution_run | 归因:模板 SQL 对比上期,分品类/区域计算贡献度 | 润色可选 | 纯模板计算,数字真实 |
| small_talk / fallback_answer | 闲聊应答 / 失败兜底与引导 | 否 | - |

## 3. 关键设计决策

### 3.1 语义层(Semantic Layer)先行
Text2SQL 准确率的天花板不在模型,而在模型"知不知道":表结构文档、指标口径文档、
few-shot 示例共同构成注入 Prompt 的上下文。口径集中管理解决了"同名指标不同数"。

### 3.2 示例检索的时间归一化
示例问题中的具体日期(如"2026年6月")在 TF-IDF 语料中 IDF 极高,
会让"6月品类排名"错配到"6月每天趋势"。由于时间窗由 `__PSTART__/__PEND__` 占位符机制
统一处理,示例匹配应与时间无关——索引与查询两侧均做数字归一化后,结构关键词主导相似度。

### 3.3 SQL 不可信默认
LLM 产出的 SQL 视为不可信输入:语法形态校验(单条 SELECT)、表名白名单、
关键字黑名单、顶层分号检测、强制 LIMIT、EXPLAIN 预检,六道闸门后才会触达数据库。
修复环(生成→校验→修复→再校验)限一次,防止死循环。

### 3.4 降级模式 = 可用性边界
无 LLM Key 时系统仍完整可跑:意图规则分类、时间窗正则解析、示例 SQL 匹配、
规则图表推荐、规则摘要。这既是演示兜底,也界定了"检索复用"能力的上限
(降级模式评测 80%,两例无对应示例的用例失败,如实呈现在评测报告中)。

## 4. 评测方法

执行准确率(execution accuracy):生成 SQL 与标注 SQL 分别执行,
对比结果集的多重集合(数值四舍五入到 2 位,行序无关)。
gold SQL 中的 `__PSTART__/__PEND__` 占位符与系统解析出的时间窗对齐后再执行。

## 5. Roadmap

1. 自建 MCP Server 封装查询/口径能力,供外部 Agent 生态复用
2. Embedding 检索 + rerank;评测集扩到 100+ 条并按难度分层
3. 多轮指代消解(依赖 LangGraph checkpointer 持久化会话)
4. Docker Compose(MySQL + backend + frontend)、GitHub Actions 评测门禁
5. 行级数据权限与审计日志
