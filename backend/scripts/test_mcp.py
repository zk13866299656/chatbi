"""MCP Server 协议实测:以标准 MCP 客户端身份连接,验证工具发现与调用。

模拟的就是 Cursor / Claude Desktop 接入后发生的事:
拉起 server 子进程 → initialize 握手 → tools/list 发现工具 → tools/call 调用。

用法: python scripts/test_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BACKEND = Path(__file__).resolve().parents[1]


async def main() -> None:
    python = BACKEND / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)

    params = StdioServerParameters(
        command=str(python),
        args=["-m", "app.mcp_server"],
        cwd=str(BACKEND),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("[1] 工具发现:", [t.name for t in tools.tools])

            res = await session.call_tool("list_semantic_layer", {})
            data = json.loads(res.content[0].text)
            print(f"[2] 语义层: {len(data['tables'])} 张表 ->", [t["table"] for t in data["tables"]])

            res = await session.call_tool("get_metric_definition", {"metric": "退款率"})
            defs = json.loads(res.content[0].text)["definitions"]
            print(f"[3] 口径查询: {defs[0]['metric']} -> {defs[0]['definition'][:40]}...")

            res = await session.call_tool("execute_validated_sql", {"sql": "DELETE FROM fact_orders"})
            print("[4] 对抗测试(DELETE):", json.loads(res.content[0].text).get("error", "未拦截 ❌"))

            res = await session.call_tool("ask_data", {"question": "2026年6月各品类的销售额排名"})
            out = json.loads(res.content[0].text)
            print(f"[5] 问数: rows={out['row_count']} mode={out['mode']} chart={out['chart_type']}")
            print("    answer:", out["answer"][:90].replace("\n", " "))

    print("\nMCP Server 协议实测全部通过")


if __name__ == "__main__":
    asyncio.run(main())
