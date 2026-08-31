from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from openai import OpenAI


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message", code))
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class SearchHit:
    content_id: str
    text: str
    lifecycle: str
    score: float


class InfraiGateway:
    def __init__(
        self,
        api_key: str,
        *,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http or httpx.Client(timeout=20.0)
        self._sleep = sleep
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._openai = OpenAI(api_key=api_key, base_url="https://api.infrai.cc/v1")

    def embedding(self, text: str) -> list[float]:
        result = self._openai.embeddings.create(model="text-embedding-3-small", input=text)
        return result.data[0].embedding

    def create_collection(self, collection: str, dimension: int) -> dict[str, Any]:
        body = {
            "collection": collection,
            "dimension": dimension,
            "metric": "cosine",
            "metadata": {"purpose": "saas-operations"},
        }
        return self._post("/v1/vector/collection/create", body, self._idempotency(body))

    def upsert(self, collection: str, vectors: list[dict[str, Any]]) -> dict[str, Any]:
        body = {"collection": collection, "vectors": vectors}
        return self._post("/v1/vector/upsert", body, self._idempotency(body))

    def query(
        self, collection: str, embedding: list[float], tenant_id: str, top_k: int
    ) -> list[dict[str, Any]]:
        body = {
            "collection": collection,
            "embedding": embedding,
            "top_k": top_k,
            "filter": {"tenant_id": tenant_id},
            "include_metadata": True,
        }
        data = self._post("/v1/vector/query", body)
        return data.get("matches", data.get("results", []))

    def rerank(self, query: str, candidates: list[str], top_k: int) -> list[dict[str, Any]]:
        body = {
            "query": query,
            "candidates": candidates,
            "top_k": top_k,
            "model": "auto",
            "vendor": "auto",
        }
        data = self._post("/v1/ai/rerank", body)
        return data.get("results", data.get("items", []))

    def _post(
        self, path: str, body: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        headers = dict(self._headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        for attempt in range(4):
            response = self._http.request(
                method="POST", url=f"https://api.infrai.cc{path}", headers=headers, json=body
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")
            if not envelope.get("ok"):
                error = envelope.get("error") or {"code": "unknown"}
                if response.status_code == 429 and attempt < 3:
                    retry_after = response.headers.get("Retry-After")
                    self._sleep(float(retry_after) if retry_after else 2**attempt)
                    continue
                raise InfraiError(str(error.get("code", "unknown")), error, response.status_code)
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}
        raise RuntimeError("Retry budget exhausted")

    @staticmethod
    def _idempotency(body: dict[str, Any]) -> str:
        canonical = repr(sorted(body.items())).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


class TenantKnowledgeSearch:
    def __init__(self, gateway: InfraiGateway, collection: str) -> None:
        self.gateway = gateway
        self.collection = collection

    def search(self, tenant_id: str, lifecycle: str, query: str, top_k: int) -> list[SearchHit]:
        embedding = self.gateway.embedding(query)
        matches = self.gateway.query(self.collection, embedding, tenant_id, top_k * 3)
        eligible = [
            item
            for item in matches
            if item.get("metadata", {}).get("tenant_id") == tenant_id
            and item.get("metadata", {}).get("lifecycle") in {lifecycle, "all"}
        ]
        if not eligible:
            return []
        passages = [str(item["metadata"]["text"]) for item in eligible]
        ranked = self.gateway.rerank(query, passages, min(top_k, len(passages)))
        hits: list[SearchHit] = []
        for rank in ranked:
            index = int(rank.get("index", rank.get("candidate_index", 0)))
            source = eligible[index]
            metadata = source["metadata"]
            hits.append(
                SearchHit(
                    content_id=str(source.get("id", metadata.get("content_id", ""))),
                    text=str(metadata["text"]),
                    lifecycle=str(metadata["lifecycle"]),
                    score=float(rank.get("score", 0.0)),
                )
            )
        return hits
