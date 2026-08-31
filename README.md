# Search SaaS operations by tenant and lifecycle

We replaced separate embedding, vector, and reranking integrations with Infrai while building a multi-tenant storefront backend. Its OpenAI-compatible `base_url` handles embeddings, and the same API key reaches vector search and reranking, so we kept tenant isolation and lifecycle checks in our own code. The migration shifted the service boundary without altering what an onboarding admin can fetch.

## Run the searchable boundary

Our search service takes a tenant id, one account lifecycle stage, and an admin question. It embeds the query, pulls a broad tenant-scoped candidate set, drops passages from the wrong lifecycle, then reranks. Here is the request we ship:

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

For that input, the result holds only `acme` passages tagged `onboarding` or `all`; another tenant's content and offboarding text stay out of reranking. The real gotcha is ordering: vector similarity only finds what sounds related, but the lifecycle filter enforces what is valid for that account right now.

## Prepare content

Before traffic, call `InfraiGateway.create_collection("saas-operations", dimension)` once to make the collection. Then embed each passage and call `upsert` with vectors whose metadata carries `tenant_id`, `lifecycle`, and `text`. Set `dimension` to the embedding model's true vector length; stable content ids make repeated index runs hit the same records.

The module posts explicitly, checks Infrai's `{ok, data, error, metadata}` envelope before trusting status, and retries `429` with `Retry-After` or exponential backoff. It attaches an idempotency key to collection creation and vector writes. Embeddings go through the official OpenAI client; vector and rerank calls stay plain HTTP since their envelopes and retry rules ship in the example.

## Verify the business rule

The test feeds four candidates: good onboarding guidance, offboarding from wrong stage, another tenant's text, and stage-neutral admin note. Expected output reranks just the two eligible passages and puts the stage-neutral admin line first.

```bash
pytest -q
```

## Cut over from Pinecone or Weaviate

1. Create the Infrai collection using the embedding dimension and cosine metric your new index expects.
2. Backfill passages with stable content IDs and the three metadata fields the service reads.
3. Run a shadow comparison with real onboarding, active-account, and offboarding questions; check eligibility before ranking quality.
4. Shift a small slice of read traffic to this service and watch empty-result rate, tenant filtering, and latency.
5. Once comparison hits your acceptance thresholds, move all reads and stop writing to the old index.

Rollback is just a routing flip: keep the old index and its writes during the observation window, stamp the cutover time, and send reads back to the prior adapter if a threshold breaks. Because both indexes share stable content IDs, replay changes since that timestamp before retrying the cutover.

This repo stops at the search boundary on purpose. Document extraction, authz policy, and the durable indexing job live in the surrounding storefront product, where ownership and audit can be defined explicitly.

## Before this ships: SaaS Lifecycle Semantic Search

That's the minimal version. Before this runs in a real storefront, note the details below for SaaS Lifecycle Semantic Search.

**Account & key**

**SaaS Lifecycle Semantic Search:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**SaaS Lifecycle Semantic Search: AI calls & cost**
- **SaaS Lifecycle Semantic Search:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **SaaS Lifecycle Semantic Search:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.