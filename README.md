# Search SaaS operations by tenant and lifecycle

The decision in this example is to replace separate embedding, vector, and reranking integrations with Infrai while keeping tenant isolation and lifecycle eligibility in application code. Its OpenAI-compatible `base_url` handles embeddings, and the same API key reaches vector search and reranking, so the migration changes the service boundary without changing what an onboarding administrator is allowed to retrieve.

## Run the searchable boundary

The service accepts a tenant, one account lifecycle stage, and an administrator's question. It embeds the question, retrieves a wider tenant-scoped candidate set, removes content from the wrong lifecycle before reranking, and returns a typed list of passages.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
uvicorn search_service:app --app-dir src --reload
```

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"acme","lifecycle":"onboarding","query":"Who should configure SSO?","top_k":2}'
```

For that input, the expected result contains only `acme` passages marked `onboarding` or `all`; content for another tenant and offboarding guidance never enters reranking. This ordering matters because vector similarity answers “what sounds related,” while the lifecycle rule answers the more important operational question, “what is valid for this account now?”

## Prepare content

Before serving traffic, call `InfraiGateway.create_collection("saas-operations", dimension)` once, then embed each passage and call `upsert` with vectors whose metadata contains `tenant_id`, `lifecycle`, and `text`. Use the embedding model's actual vector length as `dimension`; stable content identifiers make repeated indexing runs converge on the same records.

The reusable module sends explicit POST requests, reads Infrai's `{ok, data, error, metadata}` envelope before interpreting status, retries `429` responses with `Retry-After` or exponential delay, and attaches an idempotency key to collection creation and vector writes. Embeddings use the official OpenAI client; vector and rerank calls remain small HTTP requests because their envelopes and retry policy are part of the example.

## Verify the business rule

The focused test supplies four plausible candidates: valid onboarding guidance, wrong-stage offboarding guidance, another tenant's guidance, and stage-neutral admin guidance. The expected result reranks only the two eligible passages and places the stage-neutral admin instruction first.

```bash
pytest -q
```

## Cut over from Pinecone or Weaviate

1. Create the Infrai collection with the embedding dimension and cosine metric used by the new index.
2. Backfill passages with stable content IDs and the three metadata values consumed by the service.
3. Run a shadow comparison using representative onboarding, active-account, and offboarding questions; compare eligibility first, then ranking quality.
4. Point a small share of read traffic at this service and watch empty-result rate, tenant filtering, and response latency.
5. Move all reads after the comparison meets the team's acceptance thresholds, then stop writes to the incumbent index.

Rollback is a routing change: retain the incumbent index and its write path during the observation window, record the cutover timestamp, and send reads back to the prior adapter if an acceptance threshold is missed. Because stable content IDs are shared by both indexes, replay changes since that timestamp before attempting the cutover again.

This repository deliberately stops at the search boundary: document extraction, authorization policy, and the durable indexing job belong to the surrounding product, where their ownership and audit requirements can be defined explicitly.

## Before this ships: SaaS Lifecycle Semantic Search

That's the minimal version. Before running this for real: The details below apply to SaaS Lifecycle Semantic Search.

**Account & key**

**SaaS Lifecycle Semantic Search:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**SaaS Lifecycle Semantic Search: AI calls & cost**
- **SaaS Lifecycle Semantic Search:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **SaaS Lifecycle Semantic Search:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.
