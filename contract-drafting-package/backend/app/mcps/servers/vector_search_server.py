"""
VectorSearch MCP Server - 相似合同检索(简化版向量检索)
MCP 工具:
- search_similar:    按合同类型/金额范围/关键词查相似历史合同
- embed_text:        文本向量化(简化:长度+关键词指纹向量,生产可换 bge-large)
"""
from __future__ import annotations
from typing import Dict, Any, Optional, List
import re
import logging
import hashlib
from collections import Counter
import math

from sqlalchemy import or_, and_

from app.mcps.base_server import BaseMCPServer
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.contract import Contract

logger = logging.getLogger(__name__)
_BGE_MODEL = None
_BGE_LOAD_ATTEMPTED = False

# 合同向量缓存：{contract_id: (content_signature, vector)}，内容未变时复用，避免每次检索重复 encode
_CONTRACT_VECTOR_CACHE: Dict[int, tuple] = {}


# 简化版 embedding:文本前 128 个汉字做 token 频率统计 + Jaccard
STOP_TOKENS = {"的", "了", "和", "与", "或", "以及", "本合同", "甲方", "乙方", "签订", "履行",
               "约定", "应当", "有权", "双方", "条款", "金额", "人民币", "元", "签字", "盖章"}


def _tokenize(text: str) -> List[str]:
    """极简中文分词:2-gram + 关键词过滤"""
    text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]+", "", text or "")
    ngrams = []
    for i in range(len(text) - 1):
        ng = text[i:i + 2]
        if ng not in STOP_TOKENS and not all(c in "0123456789" for c in ng):
            ngrams.append(ng)
    return ngrams


def _embedding(text: str, dim: int = 128) -> Dict[str, float]:
    """优先使用本地 BGE，未配置或未安装时降级到哈希向量。"""
    global _BGE_MODEL, _BGE_LOAD_ATTEMPTED
    if settings.BGE_MODEL_PATH and not _BGE_LOAD_ATTEMPTED:
        _BGE_LOAD_ATTEMPTED = True
        try:
            from sentence_transformers import SentenceTransformer
            _BGE_MODEL = SentenceTransformer(settings.BGE_MODEL_PATH)
            logger.info("Loaded local BGE model: %s", settings.BGE_MODEL_PATH)
        except Exception as exc:
            logger.warning("BGE model unavailable, using hash fallback: %s", exc)

    if _BGE_MODEL is not None:
        values = _BGE_MODEL.encode(
            text or "",
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return {f"f{i}": float(value) for i, value in enumerate(values)}

    tokens = _tokenize(text)
    if not tokens:
        return {f"f{i}": 0.0 for i in range(dim)}
    vec = {}
    for t in tokens:
        idx = hash(t) % dim
        vec[f"f{idx}"] = vec.get(f"f{idx}", 0.0) + 1.0
    # 归一化
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def _embedding_provider() -> str:
    return "local_bge" if _BGE_MODEL is not None else "hash_fallback"


def _content_signature(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def _embedding_cached(contract_id: int, text: str) -> Dict[str, float]:
    """带缓存的合同向量：内容签名未变时复用缓存，避免重复 encode。"""
    sig = _content_signature(text)
    cached = _CONTRACT_VECTOR_CACHE.get(contract_id)
    if cached and cached[0] == sig:
        return cached[1]
    vec = _embedding(text or "")
    _CONTRACT_VECTOR_CACHE[contract_id] = (sig, vec)
    return vec


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    keys = set(a.keys()) | set(b.keys())
    return sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)


class VectorSearchServer(BaseMCPServer):
    """相似合同检索 MCP server(简化向量)"""

    def __init__(self):
        super().__init__(name="vector_search_server", description="历史合同相似检索 (内置简化向量)")

        self.register_tool(
            name="search_similar",
            description="按合同类型/金额范围/文本相似度检索历史合同,返回 top_k 条及相似度分数",
            input_schema={"type": "object",
                          "properties": {
                              "query_text": {"type": "string", "description": "待检索的合同正文/摘要"},
                              "contract_type": {"type": "string", "description": "可选,限定类型"},
                              "amount_min": {"type": "number"},
                              "amount_max": {"type": "number"},
                              "top_k": {"type": "integer", "default": 5},
                              "min_similarity": {"type": "number", "default": 0.05},
                          },
                          "required": ["query_text"]},
            handler=self._search_similar,
        )
        self.register_tool(
            name="embed_text",
            description="对文本做向量嵌入(返回 dim=128 的稀疏向量)",
            input_schema={"type": "object",
                          "properties": {"text": {"type": "string"}},
                          "required": ["text"]},
            handler=self._embed_text,
        )

    async def _search_similar(
        self,
        query_text: str,
        contract_type: Optional[str] = None,
        amount_min: Optional[float] = None,
        amount_max: Optional[float] = None,
        top_k: int = 5,
        min_similarity: float = 0.05,
    ) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            q = db.query(Contract).filter(Contract.content.isnot(None))
            if contract_type:
                # 数据库存储的是枚举(如 sales/sales),过滤掉 enum 失败情况
                q = q.filter(Contract.contract_type == contract_type)
            if amount_min is not None:
                q = q.filter(Contract.amount >= amount_min)
            if amount_max is not None:
                q = q.filter(Contract.amount <= amount_max)
            rows = q.limit(200).all()
            if not rows:
                return {"ok": True, "total_found": 0, "similar_contracts": [],
                        "query_embedding_dim": len(_embedding(query_text or ""))}

            qvec = _embedding(query_text or "")
            scored = []
            for c in rows:
                if not c.content:
                    continue
                score = _cosine(qvec, _embedding_cached(c.id, c.content))
                if score >= min_similarity:
                    scored.append((score, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:top_k]

            out = []
            for score, c in top:
                out.append({
                    "contract_id": c.id,
                    "contract_number": c.contract_number,
                    "title": c.title,
                    "contract_type": str(c.contract_type.value if hasattr(c.contract_type, "value") else c.contract_type),
                    "amount": float(c.amount) if c.amount is not None else None,
                    "status": str(c.status.value if hasattr(c.status, "value") else c.status),
                    "similarity_score": round(score, 4),
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "summary": (c.content[:80] + "...") if c.content and len(c.content) > 80 else c.content,
                })
            return {
                "ok": True,
                "total_found": len(out),
                "total_scanned": len(rows),
                "similar_contracts": out,
                "search_criteria": {
                    "contract_type": contract_type,
                    "amount_range": [amount_min, amount_max],
                    "min_similarity": min_similarity,
                    "top_k": top_k,
                    "embedding_provider": _embedding_provider(),
                },
            }
        except Exception as e:
            logger.exception("search_similar failed")
            return {"ok": False, "error": str(e), "similar_contracts": [], "total_found": 0}
        finally:
            db.close()

    async def _embed_text(self, text: str) -> Dict[str, Any]:
        vec = _embedding(text or "")
        return {
            "ok": True,
            "dim": len(vec),
            "embedding": vec,
            "provider": _embedding_provider(),
            "note": "配置 BGE_MODEL_PATH 后使用本地 BGE；未配置时使用 hash_fallback",
        }
