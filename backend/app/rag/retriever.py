"""语义层检索器(RAG 的 R)。

两种实现,同一接口,可按环境变量切换并支持离线对比评测:

- TfidfRetriever:   char n-gram TF-IDF。零依赖、确定性强,适合小语料 + 术语规范的场景;
                    示例索引/查询做时间数字归一化,避免日期字符的高 IDF 干扰结构匹配。
- EmbeddingRetriever: 语义向量检索。双后端:
                      local = fastembed(ONNX, bge-small-zh, 无需 GPU);
                      api   = OpenAI 兼容 /embeddings 接口。
                    语义相近的问法(同义词/口语)在向量空间天然接近。

选型不是二选一:语料小且术语规范时 TF-IDF 足够;口语化问法多时 embedding 优势明显。
evals/retriever_benchmark.py 会在同一评测集上对两者跑执行准确率,用数据说话。
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..config import get_settings
from ..db.schema_docs import CorpusDoc, build_corpus

logger = logging.getLogger(__name__)


class BaseRetriever:
    # 示例复用的相似度门槛(降级模式),不同检索器的分数量纲不同,各自声明
    example_threshold: float = 0.35
    backend_name: str = "tfidf"

    def search_with_scores(self, query: str, kind: str | None = None, top_k: int | None = None) -> list[tuple[CorpusDoc, float]]:
        raise NotImplementedError

    def search(self, query: str, kind: str | None = None, top_k: int | None = None) -> list[CorpusDoc]:
        return [doc for doc, _ in self.search_with_scores(query, kind=kind, top_k=top_k)]


class TfidfRetriever(BaseRetriever):
    """中文 char n-gram TF-IDF 检索,小语料场景下效果稳定。"""

    example_threshold = 0.35
    backend_name = "tfidf"

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
    """语义向量检索:句子 → 向量,余弦相似度排序。

    bge 系模型的余弦分布:相关问对多在 0.5+,无关对多在 0.45 以下,
    示例复用门槛相应取 0.5(与 TF-IDF 的 0.35 分数量纲不同,各自声明)。
    """

    example_threshold = 0.5
    backend_name = "embedding"

    # 与 TF-IDF 同源的教训:示例匹配必须时间无关(时间窗由占位符机制统一处理),
    # 否则"2026年6月"的时间前缀相似度会压过"品类排名 vs 每天趋势"的结构差异
    _TIME_RE = re.compile(
        r"\d{4}\s*年|\d{4}-\d{2}(-\d{2})?|\d{1,2}\s*月|最近\s*\d+\s*天|近\s*\d+\s*天|上(个)?月|本月|本周|当天|每日|每天"
    )

    def __init__(self) -> None:
        settings = get_settings()
        self._docs = build_corpus()
        # 与 TF-IDF 同一索引策略:example 只按问题文本(且做时间归一化),其余按全文
        texts = [
            self._normalize_example(doc.title) if doc.kind == "example" else doc.text + doc.title
            for doc in self._docs
        ]
        self._embedder = self._pick_backend(settings)
        vectors = np.asarray(self._embedder(texts), dtype=np.float32)
        self._matrix = self._normalize_rows(vectors)
        logger.info(
            "Embedding 检索器就绪: model=%s dim=%d docs=%d",
            settings.embedding_model, self._matrix.shape[1], len(self._docs),
        )

    @classmethod
    def _normalize_example(cls, text: str) -> str:
        return cls._TIME_RE.sub("", text or "")

    def _pick_backend(self, settings):
        if settings.embedding_provider == "api":
            return self._api_embedder(settings)
        return self._local_embedder(settings)

    @staticmethod
    def _local_embedder(settings):
        from fastembed import TextEmbedding  # 延迟导入:未安装时保持 TF-IDF 可用

        model = TextEmbedding(model_name=settings.embedding_model)

        def embed(texts: list[str]) -> list[list[float]]:
            return [v.tolist() for v in model.embed(texts)]

        embed.model_name = settings.embedding_model  # type: ignore[attr-defined]
        return embed

    @staticmethod
    def _api_embedder(settings):
        from openai import OpenAI

        if not settings.embedding_api_key:
            raise ValueError("embedding_provider=api 但未配置 EMBEDDING_API_KEY")
        client = OpenAI(api_key=settings.embedding_api_key, base_url=settings.embedding_base_url or None)

        def embed(texts: list[str]) -> list[list[float]]:
            response = client.embeddings.create(model=settings.embedding_model, input=texts)
            return [item.embedding for item in response.data]

        embed.model_name = settings.embedding_model  # type: ignore[attr-defined]
        return embed

    @staticmethod
    def _normalize_rows(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def search_with_scores(self, query: str, kind: str | None = None, top_k: int | None = None) -> list[tuple[CorpusDoc, float]]:
        settings = get_settings()
        top_k = top_k or settings.retriever_top_k
        if kind == "example":
            query = self._normalize_example(query)
        query_vec = self._normalize_rows(
            np.asarray(self._embedder([query]), dtype=np.float32)
        )[0]  # (dim,)
        scores = self._matrix @ query_vec  # 归一化后的点积即余弦相似度

        candidates = [
            (doc, float(score))
            for doc, score in zip(self._docs, scores)
            if kind is None or doc.kind == kind
        ]
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return candidates[:top_k]


class HybridRetriever(BaseRetriever):
    """混合检索:Embedding 语义召回 + TF-IDF 字面召回,校准置信度融合排序。

    解决检索对比报告发现的两个问题:
    1. Embedding 余弦普遍偏高 → "自信地答错":把语义余弦按实测分布线性校准到 [0,1]
       (0.40 以下视为无关,0.95 以上视为满分),分数恢复可比性;
    2. TF-IDF 对口语化问法失明 → 仅字面命中的候选以打折置信度参与,并给
       "双路同时命中"的候选加分(两路都认,才更可信)。

    拒答语义:校准置信度低于 example_threshold 时宁可弃权——
    宁可说"这个问题我不会",不给自信的错答案。
    """

    example_threshold = 0.35
    backend_name = "hybrid"

    _EMB_FLOOR = 0.40  # 语义余弦低于此值视为无关
    _EMB_CEIL = 0.95   # 高于此值视为满分

    def __init__(self, embedding: EmbeddingRetriever | None = None, tfidf: TfidfRetriever | None = None) -> None:
        self._embedding = embedding or EmbeddingRetriever()
        self._tfidf = tfidf or TfidfRetriever()
        self._docs = self._embedding._docs
        if [d.doc_id for d in self._docs] != [d.doc_id for d in self._tfidf._docs]:
            raise ValueError("双路检索器语料不一致")

    def _calibrate(self, cos: float) -> float:
        conf = (cos - self._EMB_FLOOR) / (self._EMB_CEIL - self._EMB_FLOOR)
        return max(0.0, min(1.0, conf))

    def search_with_scores(self, query: str, kind: str | None = None, top_k: int | None = None) -> list[tuple[CorpusDoc, float]]:
        settings = get_settings()
        top_k = top_k or settings.retriever_top_k
        recall_k = max(top_k * 2, 6)

        emb_hits = self._embedding.search_with_scores(query, kind=kind, top_k=recall_k)
        tfidf_hits = self._tfidf.search_with_scores(query, kind=kind, top_k=recall_k)

        calibrated: dict[str, float] = {}
        merged: dict[str, CorpusDoc] = {}
        tfidf_top3 = {d.doc_id for d, _ in tfidf_hits[:3]}

        for doc, cos in emb_hits:
            score = self._calibrate(cos)
            if doc.doc_id in tfidf_top3:
                score = min(1.0, 0.85 * score + 0.15)  # 双路同时命中:加分
            else:
                score = 0.85 * score
            calibrated[doc.doc_id] = score
            merged[doc.doc_id] = doc

        # 仅 TF-IDF 命中的(字面精确、语义模型失明的场景):置信度打折后补入
        for doc, raw in tfidf_hits:
            if doc.doc_id not in merged and raw >= self._tfidf.example_threshold:
                merged[doc.doc_id] = doc
                calibrated[doc.doc_id] = 0.8 * raw

        ranked = sorted(merged.values(), key=lambda d: calibrated.get(d.doc_id, 0.0), reverse=True)
        return [(doc, calibrated[doc.doc_id]) for doc in ranked[:top_k] if calibrated[doc.doc_id] > 0.02]


class UnavailableRetriever(TfidfRetriever):
    """embedding 强制启用但初始化失败时的兜底,行为同 TF-IDF 并保留日志线索。"""

    backend_name = "tfidf(fallback)"


@lru_cache
def get_retriever() -> BaseRetriever:
    settings = get_settings()
    backend = settings.embedding_backend
    if backend == "tfidf":
        return TfidfRetriever()
    try:
        if backend == "embedding":
            return EmbeddingRetriever()
        return HybridRetriever()  # hybrid 与 auto(兼容旧配置)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s 检索器初始化失败(%s),已回退 TF-IDF", backend, exc)
        return UnavailableRetriever()


def reset_retriever() -> None:
    """切换后端后重建检索器(评测/配置变更用)。"""
    get_retriever.cache_clear()
    from ..config import get_settings as _gs

    _gs.cache_clear()
