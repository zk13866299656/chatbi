# ChatBI · 智能经营分析问数平台

> 面向"业务取数依赖数据组排期、响应以天计"的传统瓶颈,构建自然语言问数系统:
> 业务人员用一句中文提问,系统自动完成 **意图解析 → 语义检索 → SQL 生成 → 安全校验 → 执行 → 图表推荐 → 结论/归因**,
> 取数响应从天级压到秒级。基于 LangGraph 多 Agent 编排 + RAG 语义层 + SSE 流式交互。

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
                          ┌────────────────────────────────────────────┐
        用户提问           │              FastAPI (SSE 流式)             │
  ┌──────────────────┐    │  ┌──────────────────────────────────────┐  │
  │ Vue3 + Element+  │───▶│  │        LangGraph 工作流编排           │  │
  │ ECharts 对话/看板 │◀───│  │                                      │  │
  └──────────────────┘    │  │ supervisor(意图解析/时间窗/改写)      │  │
                          │  │   ├─ query ──→ [表结构检索 ∥ 口径检索] │  │
                          │  │   │               └─→ SQL生成        │  │
                          │  │   │                 └─→ 安全校验 ─┐   │  │
                          │  │   │                   ↑(失败修复)│   │  │
                          │  │   │                执行 → 图表 → 结论   │  │
                          │  │   ├─ attribution → 归因拆解(模板SQL)  │  │
                          │  │   └─ chitchat ──→ 闲聊应答            │  │
                          │  └──────────────────────────────────────┘  │
                          │   RAG: TF-IDF 语义层检索(可升级 Embedding)  │
                          │   安全层: 白名单/黑名单/EXPLAIN/行数上限      │
                          └───────────────┬────────────────────────────┘
                                          │ SQLAlchemy
                                   MySQL / SQLite(10万级订单)
```

## 三、技术栈

- **Agent 编排**: LangGraph(StateGraph、条件路由、并行分支、屏障汇合、修复环)
- **LLM**: OpenAI 兼容接口(DeepSeek / Qwen / GLM),JSON 结构化输出 + 失败重试
- **RAG**: 语义层语料(表结构/指标口径/few-shot 示例)+ TF-IDF char n-gram 检索,预留 Embedding 升级位
- **后端**: FastAPI + SQLAlchemy 2.0 + Pydantic v2,SSE 流式输出,asyncio 线程池执行 SQL
- **数据**: 自建中文电商仿真数据集(10.7 万订单 / 17.9 万明细,内置 618/双11 季节性与品类差异)
- **前端**: Vue3 + TypeScript + Element Plus + ECharts,SSE 时间线 + 图表自动渲染
- **评测**: 10 条标注用例,执行准确率(execution accuracy)离线回归

## 四、快速开始

**Windows 一键启动**(推荐):

```bat
E:\chatbi\start_chatbi.bat
```

双击即可:自动清理旧实例 → 启动后端和前端(各自独立窗口)→ 打开浏览器。
关闭那两个窗口即停止服务。

**手动启动**:

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

## 五、评测

```bash
cd backend
python evals/eval_runner.py --no-gate          # 执行准确率回归(50 条用例)
python evals/eval_runner.py --gate-threshold 0.6   # CI 门禁模式
python evals/retriever_benchmark.py            # TF-IDF vs Embedding 检索对比
```

- 评测集 50 条:多表 JOIN / 聚合 / 时间窗 / 口径计算 / 口语化改写(4 条)
- 降级模式(LLM 关闭,检索直接决定 SQL):TF-IDF 30% vs Embedding 36%,
  示例库可覆盖题上 15/18 vs 18/18,差异与结论见 `evals/comparison_report.md`
- 报告输出至 `evals/report_*.md` / `evals/comparison_report.md`

## 六、工程亮点

1. **安全层是硬约束**: 只允许单条 SELECT、表名白名单、DDL/DML 黑名单、强制行数上限、执行前 EXPLAIN,LLM 生成的 SQL 不可信默认
2. **降级全链路**: LLM 不可用时,意图规则解析 + 时间窗规则提取 + 示例 SQL 相似度匹配,系统零配置可跑通
3. **语义层 = 口径统一**: 指标口径(GMV/退款率/客单价/复购率)文档化并强制注入 Prompt,杜绝"同名不同数"
4. **示例检索的时间归一化**: 示例匹配在时间无关语义上进行(数字归一化),避免日期字符的高 IDF 干扰结构匹配
5. **SSE 过程透出**: 前端实时渲染每个 Agent 节点的进度时间线,长查询不再黑盒等待
6. **归因模板化**: "为什么涨/跌"走模板 SQL + 贡献度计算,数字全部来自真实查询,不让 LLM 编造
7. **会话持久化**: 对话与最终结果(图表/SQL/数据)落库,UUID 主键规避自增方言差异,刷新/重开不丢,支撑多轮追问
8. **检索三后端 + 对比评测 + 域外拒答**: TF-IDF / Embedding(bge-small-zh, ONNX 本地推理)/ Hybrid(双路召回+置信度校准)同接口可切换,Hybrid 为默认;50 条评测集三方实测(28% / 34% / 34%,可覆盖题 14/17 vs 17/17 vs 17/17),含"品类/品牌"混淆、时间归一化等实证发现与域外拒答机制,详见 `evals/comparison_report.md`
9. **自建 MCP Server**: 问数能力按 MCP 协议暴露(ask_data / execute_validated_sql / list_semantic_layer / get_metric_definition),Cursor 等外部 Agent 一段配置即可接入;配合语义层 YAML 配置化,支持私有化部署接入自己的数据库——能力放出去,风险关在里面

## 七、Roadmap

- [ ] 自建 MCP Server 封装数据查询能力,支持 Cursor/其他 Agent 复用
- [ ] Embedding + rerank 升级语义检索,构建百条级评测集
- [ ] 多轮上下文指代消解("那上个月呢")
- [ ] MySQL 部署 + Docker Compose 一键起
- [ ] 用户体系与数据权限(行级过滤)

## License

MIT
