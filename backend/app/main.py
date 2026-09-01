"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import chat, dashboard, meta
from .config import get_settings
from .rag.retriever import get_retriever

logging.basicConfig(
    level=get_settings().log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 预热:构建 TF-IDF 索引、探测数据集日期,避免首个请求变慢
    import asyncio

    from .agents.nodes import data_end_probe

    retriever = get_retriever()
    logger.info("语义层索引预热完成: %d 份语料", len(retriever._docs))
    await data_end_probe()
    yield


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meta.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
