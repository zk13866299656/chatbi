# ChatBI · 智能经营分析问数平台

> 面向"业务取数依赖数据组排期、响应以天计"的传统瓶颈,构建自然语言问数系统:
> 业务人员用一句中文提问,系统自动完成 **意图解析 → 语义检索 → SQL 生成 → 安全校验 → 执行 → 图表推荐 → 结论/归因**,
> 取数响应从天级压到秒级。基于 LangGraph 多 Agent 编排 + RAG 语义层 + SSE 流式交互 + MCP 开放生态。

---

## 一、解决什么问题

| | 传统方式 | ChatBI |
|---|---|---|
| 取数流程 | 提需求 → 数据组排期 → 写 SQL → 导 Excel → 回传 | 自然语言直接问,秒级返回图表 |
| 指标口径 | 各写各的 SQL,同名指标数字对不上 | 口径统一维护在语义层,LLM 强制遵循 |
| 异动分析 | 事后人工拆维度找原因 | 自动对比上期、分品类/区域计算贡献度 |
| 结果可信度 | 黑盒导出 | 生成 SQL 全程透明可核查,安全层硬校验 |

## 二、架构

```text
                            ┌──────────────────────────────────────────────┐
        用户提问             │                FastAPI (SSE 流式)             │
  ┌──────────────────┐       │  ┌────────────────────────────────────────┐  │
  │ Vue3 + Element+  │───▶│  │          LangGraph 工作流编排            │  │
  │ ECharts 对话/看板 │◀───│  │                                        │  │
  │ 会话管理/数据字典  │       │  │  supervisor(意图解析/时间窗/改写)        │  │
  └──────────────────┘       │  │    ├─ query ──→ [表结构检索 ∥ 口径检索]  │  │
        ▲                    │  │    │              └─→ SQL 生成          │  │
        │ MCP 协议            │  │    │                └─→ 安全校验 ─┐      │  │
  ┌─────┴────────────┐       │  │    │                  ↑(失败修复) │      │  │
  │ MCP Server       │       │  │    │              执行 → 图表 → 结论      │  │
  │ 4 个标准工具       │◀──────│  │    ├─ attribution → 归因拆解(模板 SQL) │  │
  │ (Cursor 等可接入)  │       │  │    └─ chitchat ──→ 闲聊应答            │  │
  └──────────────────┘       │  └────────────────────────────────────────┘  │
                             │  Hybrid 检索: Embedding + TF-IDF 融合 + 拒答   │
                             │  安全层: 白名单/黑名单/EXPLAIN/行数上限/占位符   │
                             └───────────────┬──────────────────────────────┘
                                             │ SQLAlchemy
                                      SQLite / MySQL(10 万级订单)
                                      语义层: 内置 or YAML 配置化
```

## 三、技术栈

- **Agent 编排**: LangGraph(StateGraph、条件路由、并行屏障汇合、修复环)
- **LLM**: OpenAI 兼容接口(DeepSeek / Qwen / GLM),JSON 结构化输出 + 失败重试
- **检索(RAG)**: 语义层语料(表结构/指标口径/few-shot 示例);三后端可选——TF-IDF、Embedding(fastembed 本地 ONNX / API)、**Hybrid 混合检索(默认)**
- **MCP**: FastMCP(官方 SDK)暴露 4 个标准工具,支持 stdio / streamable-http
- **后端**: FastAPI + SQLAlchemy 2.0 + Pydantic v2,SSE 流式输出,asyncio 线程池执行 SQL
- **数据**: 自建中文电商仿真数据集(10.7 万订单 / 17.9 万明细,内置 618/双11 季节性与品类差异)
- **前端**: Vue3 + TypeScript + Element Plus + ECharts,SSE 时间线 + 图表自动渲染 + 看板联动
- **评测**: 50 条标注用例,执行准确率(execution accuracy)离线回归 + CI 门禁模式

## 四、功能特性

- **对话问数**: 自然语言 → SQL → 图表 → 结论,全程节点时间线透出;支持"上个月/最近 N 天"等时间表达与"为什么涨跌"归因;域外问题基于置信度**拒答**而非瞎答
- **经营看板**: GMV/订单/客单价/退款率 KPI 环比、销售趋势、品类结构、**品类健康度四象限**(退款率 × 评分 × GMV);图表一键跳转对话追问
- **会话管理**: 对话与最终结果(图表/SQL/数据)持久化,刷新/重开不丢,支持多轮追问
- **数据字典**: 语义层可视化(表结构/指标口径/示例),支持 YAML 配置化切换
- **MCP Server**: Cursor 等外部 Agent 一段配置即可接入,接入指南见 [docs/mcp.md](docs/mcp.md)

## 五、快速开始

**Windows 一键启动**(推荐):双击 `start_chatbi.bat`——自动清理旧实例、启动前后端并打开浏览器。

手动启动:

```bash
# 1. 后端
cd backend
python -m venv .venv && .venv\Scripts\activate       # Windows
pip install -r requirements.txt

python scripts/generate_data.py    # 生成 10 万级中文电商数据
python scripts/init_db.py          # 建表导入(SQLite 默认,可切 MySQL)

python run.py                      # http://localhost:8000/docs

# 2. 前端
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

**LLM 配置(可选)**: 复制 `backend/.env.example` 为 `.env`,填入 `LLM_API_KEY` 即进入 LLM 模式;
不配置则自动进入**降级模式**(规则时间解析 + 示例 SQL 匹配兜底),全流程依然可演示。

**接入自己的数据库(私有化部署)**: `DB_URL` 指向目标库 + `SEMANTIC_LAYER_FILE` 指向语义层 YAML
(模板见 `backend/semantic_layer.example.yaml`),引擎通用、语义跟数据走。详见 [docs/mcp.md](docs/mcp.md)。

## 六、评测

```bash
cd backend
python evals/eval_runner.py --no-gate              # 执行准确率回归(50 条用例)
python evals/eval_runner.py --gate-threshold 0.6   # CI 门禁模式
python evals/retriever_benchmark.py                # TF-IDF vs Embedding vs Hybrid 对比
```

- **三方检索对比(降级模式,50 条)**: TF-IDF 28% / Embedding 34% / **Hybrid 34%(默认后端)**,
  可覆盖场景正确率 14/17 vs 17/17 vs 17/17;完整分析见 `evals/comparison_report.md`
- **LLM 模式**: 抽样 8 条 100% 通过,平均端到端 3.7 秒
- 报告输出至 `evals/report_*.md` / `evals/comparison_report.md`

## 七、工程亮点

1. **安全层是硬约束**: 只允许单条 SELECT、表名白名单、DDL/DML 黑名单、强制行数上限、执行前 EXPLAIN、占位符残留拦截——LLM 生成的 SQL 按"不可信输入"处理
2. **降级全链路**: LLM 不可用时,意图规则解析 + 时间窗规则提取 + 示例 SQL 相似度匹配,系统零配置可跑通
3. **语义层 = 口径统一**: 指标口径文档化并强制注入 Prompt;示例检索做**时间归一化**,消除日期高 IDF/高语义相似导致的结构错配
4. **混合检索 + 域外拒答**: 语义余弦按实测分布校准到 [0,1] 后双路融合;置信度不足宁可弃权,不给"自信的错答案"
5. **评测驱动迭代**: 时间归一化、近义结构混淆、拒答阈值——每个改进都由评测数据发现并验证
6. **归因模板化**: "为什么涨/跌"走模板 SQL + 贡献度计算,数字全部来自真实查询,不让 LLM 编造
7. **会话持久化**: UUID 主键规避 SQLite/MySQL 自增方言差异,最终结果整体落库,刷新/重开不丢
8. **自建 MCP Server**: 从 MCP 消费者到生产者;配合语义层配置化,支持私有化部署接入自有数据库

## 八、Roadmap

- [x] 混合检索(语义 + 字面融合)+ 域外拒答(默认后端)
- [x] Embedding 本地推理 + 三方检索对比评测
- [x] 自建 MCP Server + 语义层 YAML 配置化
- [ ] rerank 精排 + 评测集扩充至百条级
- [ ] Docker Compose 一键部署 + GitHub Actions 评测门禁
- [ ] 多轮指代消解(LangGraph Checkpointer)
- [ ] 用户体系与数据权限(行级过滤)

## License

MIT
