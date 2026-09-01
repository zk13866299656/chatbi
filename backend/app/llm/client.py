"""LLM 客户端封装(OpenAI 兼容协议)。

统一处理:
1. 异步客户端单例与实例缓存;
2. JSON 输出提取(兼容纯 JSON / ```json 围栏 / 文本夹带);
3. 瞬时错误(超时 / 5xx / 限流)应用层重试;
4. 未配置 API Key 时 available=False,工作流节点自动走降级逻辑。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from ..config import get_settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None
_retry_terms = ("TIMEOUT", "TIMED OUT", "RATE LIMIT", "429", "502", "503", "504", "CONNECTION")


class LLMError(RuntimeError):
    pass


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
            max_retries=1,
        )
    return _client


async def chat_text(system_prompt: str, user_prompt: str, *, max_tokens: int | None = None) -> str:
    settings = get_settings()
    if not settings.llm_enabled:
        raise LLMError("LLM 未配置(降级模式)")

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = await get_client().chat.completions.create(
                model=settings.llm_model,
                temperature=settings.llm_temperature,
                max_tokens=max_tokens or settings.llm_max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            text = f"{exc.__class__.__name__}: {exc}".upper()
            if attempt >= 1 or not any(term in text for term in _retry_terms):
                raise LLMError(str(exc)) from exc
            await asyncio.sleep(0.8)
    raise LLMError(str(last_error))


async def chat_json(system_prompt: str, user_prompt: str, *, max_tokens: int | None = None) -> Any:
    raw = await chat_text(system_prompt, user_prompt, max_tokens=max_tokens)
    return extract_json_payload(raw)


def extract_json_payload(text: str) -> Any:
    """从模型输出中提取 JSON,兼容围栏/夹带两种脏格式。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("模型未返回内容")

    fenced = re.search(r"```json\s*(.*?)```", raw, re.IGNORECASE | re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1).strip())
    if raw.startswith("{") or raw.startswith("["):
        return json.loads(raw)
    embedded = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
    if embedded:
        return json.loads(embedded.group(1).strip())
    raise ValueError(f"无法从模型输出提取 JSON: {raw[:200]}")
