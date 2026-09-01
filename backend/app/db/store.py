"""会话持久化存储(对话管理)。

对话与消息与业务数据同库(SQLite/MySQL 一套 DDL):
- 主键用 UUID,规避 SQLite AUTOINCREMENT 与 MySQL AUTO_INCREMENT 的方言差异;
- assistant 消息的 payload 存最终结果 JSON(答案/SQL/图表/数据/节点事件),
  刷新页面或切换设备后重新拉取即可完整还原;
- 用户消息在工作流启动前先落库,异常中断也能保留提问记录。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text

from .database import engine

_PAYLOAD_TYPE = "MEDIUMTEXT" if engine.url.get_backend_name() == "mysql" else "TEXT"


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS conversations ("
            "id VARCHAR(40) PRIMARY KEY, "
            "title VARCHAR(120) NOT NULL, "
            "created_at VARCHAR(32) NOT NULL)"
        ))
        conn.execute(text(
            f"CREATE TABLE IF NOT EXISTS chat_messages ("
            "id VARCHAR(40) PRIMARY KEY, "
            "conversation_id VARCHAR(40) NOT NULL, "
            "role VARCHAR(16) NOT NULL, "
            f"content {_PAYLOAD_TYPE}, "
            f"payload {_PAYLOAD_TYPE}, "
            "created_at VARCHAR(32) NOT NULL)"
        ))
        try:
            conn.execute(text(
                "CREATE INDEX idx_messages_conv ON chat_messages (conversation_id)"
            ))
        except Exception:  # 已存在(MySQL 重启场景)
            pass


def create_conversation(title: str) -> dict[str, Any]:
    conv_id = uuid.uuid4().hex
    now = datetime.now().isoformat(timespec="microseconds")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO conversations (id, title, created_at) VALUES (:id, :title, :created_at)"
        ), {"id": conv_id, "title": title[:100], "created_at": now})
    return {"id": conv_id, "title": title[:100], "created_at": now}


def list_conversations() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT c.id, c.title, c.created_at, COUNT(m.id) AS message_count "
            "FROM conversations c LEFT JOIN chat_messages m ON m.conversation_id = c.id "
            "GROUP BY c.id, c.title, c.created_at "
            "ORDER BY c.created_at DESC"
        )).mappings().all()
    return [dict(row) for row in rows]


def get_messages(conversation_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, role, content, payload, created_at FROM chat_messages "
            "WHERE conversation_id = :cid ORDER BY created_at ASC, id ASC"
        ), {"cid": conversation_id}).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item["payload"]) if item.get("payload") else None
        result.append(item)
    return result


def append_messages(conversation_id: str, items: list[tuple[str, str, dict[str, Any] | None]]) -> None:
    # 微秒精度:同秒内多条消息按时间排序才稳定,否则 UUID 主键顺序随机
    now = datetime.now().isoformat(timespec="microseconds")
    with engine.begin() as conn:
        for role, content, payload in items:
            conn.execute(text(
                f"INSERT INTO chat_messages (id, conversation_id, role, content, payload, created_at) "
                "VALUES (:id, :cid, :role, :content, :payload, :created_at)"
            ), {
                "id": uuid.uuid4().hex,
                "cid": conversation_id,
                "role": role,
                "content": content,
                "payload": json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
                "created_at": now,
            })


def delete_conversation(conversation_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM chat_messages WHERE conversation_id = :cid"), {"cid": conversation_id})
        conn.execute(text("DELETE FROM conversations WHERE id = :cid"), {"cid": conversation_id})
