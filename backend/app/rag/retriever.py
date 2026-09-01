"""语义层检索器(RAG 的 R)。

设计:
- 语料来自 db/schema_docs.py(表结构 / 指标口径 / few-shot 示例);
- 默认用 TF-IDF(char n-gram)做中文检索,零外部依赖、离线可跑;
- 预留 EmbeddingRetriever 接口,切换语义向量检索不影响上层节点。
"""

from __future__ import annotations

import re
from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..config import get_settings
from ..db.schema_docs import CorpusDoc, build_corpus


class BaseRetriever:
    def search_with_scores(self, query: str, kind: str | None = None, top_k: int | None = None) -> list[tuple[CorpusDoc, float]]:
        raise NotImplementedError

    def search(self, query: str, kind: str | None = None, top_k: int | None = None) -> list[CorpusDoc]:
        return [doc for doc, _ in self.search_with_scores(query, kind=kind, top_k=top_k)]


class TfidfRetriever(BaseRetriever):
    """中文 char n-gram TF-IDF 检索,小语料场景下效果稳定。"""

    def __init__(self) -> None:
        self._docs = build_corpus()
        self._vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 2))
        # example 类语料的索引与查询都做"时间归一化"(去掉数字):
        # 1. 时间窗由 __PSTART__/__PEND__ 占位符机制统一处理,与示例选择无关;
        # 2. 具体日期数字在示例库中 IDF 极高,会让"6月品类排名"错配到"6月每天趋势"。
        self._matrix = self._vectorizer.fit_transform(
            [self._normalize(doc.title) if doc.kind == "example" else doc.text + doc.title for doc in self._docs]
        )

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[0-9]+", "", text or "")

    def search_with_scores(self, query: str, kind: str | None = None, top_k: int | None = None) -> list[tuple[CorpusDoc, float]]:
        settings = get_settings()
        top_k = top_k or settings.retriever_top_k
        if kind == "example":
            query = self._normalize(query)
        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._matrix)[0]

        candidates = [
            (doc, float(score))
            for doc, score in zip(self._docs, scores)
            if kind is None or doc.kind == kind
        ]
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return [(doc, score) for doc, score in candidates[:top_k] if score > 0.01]


class EmbeddingRetriever(BaseRetriever):
    """语义向量检索(升级位)。

    接入方式:调用 OpenAI 兼容 /embeddings 接口,对语料与查询做向量化后余弦检索。
    当前骨架保留接口,便于后续把 TF-IDF 平滑升级为 bge/text-embedding,不影响工作流节点。
    """

    def __init__(self) -> None:
        raise NotImplementedError("EmbeddingRetriever 为预留升级位,当前请使用 TfidfRetriever")


@lru_cache
def get_retriever() -> BaseRetriever:
    return TfidfRetriever()
