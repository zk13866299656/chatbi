# ChatBI MCP Server 接入指南

ChatBI 的问数能力已封装为标准 MCP(Model Context Protocol)服务,任何支持 MCP 的
Agent(Cursor、Claude Desktop、自研 LangGraph Agent 等)接入后即可直接查数。

## 暴露的工具

| 工具 | 作用 |
|---|---|
| `ask_data(question)` | 完整问数:自然语言进,返回结论 + 生成的 SQL + 结果数据(内部走完整 LangGraph 工作流) |
| `execute_validated_sql(sql)` | 执行只读 SQL(强制过六道安全闸门:单条 SELECT / 表名白名单 / 黑名单 / 行数上限 / 占位符检查 / EXPLAIN) |
| `list_semantic_layer()` | 列出所有表、字段业务含义与关联关系 |
| `get_metric_definition(metric)` | 查询指标精确口径(GMV / 退款率 / 客单价 / 复购率…) |

安全边界:外部 Agent **拿不到数据库连接**,所有访问必须过安全闸门——能力放出去,风险关在里面。

## 接入 Cursor / Claude Desktop

在 MCP 配置中添加(Cursor: `Settings → MCP → Add server`,或项目下 `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "chatbi": {
      "command": "E:/chatbi/backend/.venv/Scripts/python.exe",
      "args": ["-m", "app.mcp_server"],
      "cwd": "E:/chatbi/backend"
    }
  }
}
```

重启客户端后即可在对话中直接问:"咱们数仓里 2026 年 6 月各品类的销售额怎么样?"

## 调试:MCP Inspector

```bash
cd backend
npx @modelcontextprotocol/inspector .venv/Scripts/python -m app.mcp_server
```

浏览器会打开调试界面,可查看工具列表、参数 schema,手动调用验证。

## 私有化部署:接入"你自己的数据库"

MCP Server 与数据源解耦,部署到对方环境后两步即可接入对方数据库:

1. **连接**:`.env` 中把 `DB_URL` 指向对方数据库(MySQL/PostgreSQL/SQLite 均可)
2. **语义层**:复制 `semantic_layer.example.yaml` 为 `semantic_layer.yaml`,
   按对方的表结构填写表说明、指标口径、常用示例,并在 `.env` 中指向它:

   ```env
   SEMANTIC_LAYER_FILE="semantic_layer.yaml"
   ```

重启后,检索语料、Prompt 上下文与工具返回的元数据全部切换为对方的业务语义。
这是 Text2SQL 落地别人库的关键:引擎可以通用,**语义必须跟数据走**。

## 传输方式

- `stdio`(默认):客户端拉起子进程,适合本机/内网
- `streamable-http`:设置 `MCP_TRANSPORT=http` 后启动,适合集中部署、多客户端共享
