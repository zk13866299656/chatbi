"""全局配置:环境变量驱动,默认零配置可跑(SQLite + 降级模式)。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ChatBI 智能经营分析平台"

    # 数据库:默认 SQLite;可切换 MySQL(mysql+pymysql://...)
    db_url: str = "sqlite:///data/chatbi.db"

    # LLM(OpenAI 兼容接口):未配置 key 时进入降级模式
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.1
    llm_timeout: float = 60.0
    llm_max_tokens: int = 2000

    # 检索与 SQL 安全
    retriever_top_k: int = 4
    sql_max_rows: int = 200
    sql_timeout_seconds: float = 10.0

    # 语义检索后端: auto(优先 embedding,不可用回退 tfidf) | tfidf | embedding
    embedding_backend: str = "auto"
    # embedding 提供方: local(fastembed 本地 ONNX, 默认) | api(OpenAI 兼容 /embeddings)
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    log_level: str = "INFO"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
