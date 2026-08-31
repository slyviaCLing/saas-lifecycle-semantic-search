from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from saas_retrieval import InfraiError, InfraiGateway, SearchHit, TenantKnowledgeSearch


class SearchRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    lifecycle: str = Field(pattern="^(onboarding|active|offboarding)$")
    query: str = Field(min_length=2)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResponse(BaseModel):
    tenant_id: str
    lifecycle: str
    hits: list[SearchHit]


app = FastAPI(title="SaaS lifecycle semantic search")


def build_search() -> TenantKnowledgeSearch:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set INFRAI_API_KEY before starting the service")
    return TenantKnowledgeSearch(InfraiGateway(api_key), "saas-operations")


@app.post("/search", response_model=SearchResponse)
def search_content(request: SearchRequest) -> SearchResponse:
    try:
        hits = build_search().search(
            request.tenant_id, request.lifecycle, request.query, request.top_k
        )
    except InfraiError as exc:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(status_code=status, detail=exc.detail) from exc
    return SearchResponse(tenant_id=request.tenant_id, lifecycle=request.lifecycle, hits=hits)
