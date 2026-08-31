from saas_retrieval import TenantKnowledgeSearch


class RecordingGateway:
    def __init__(self) -> None:
        self.reranked: list[str] = []

    def embedding(self, text: str) -> list[float]:
        return [0.2, 0.8]

    def query(self, collection: str, embedding: list[float], tenant_id: str, top_k: int):
        return [
            {"id": "setup-sso", "metadata": {"tenant_id": "acme", "lifecycle": "onboarding", "text": "Configure SSO during setup."}},
            {"id": "close-account", "metadata": {"tenant_id": "acme", "lifecycle": "offboarding", "text": "Export data before closure."}},
            {"id": "other-tenant", "metadata": {"tenant_id": "globex", "lifecycle": "onboarding", "text": "Invite a workspace owner."}},
            {"id": "roles", "metadata": {"tenant_id": "acme", "lifecycle": "all", "text": "Assign the least privileged admin role."}},
        ]

    def rerank(self, query: str, candidates: list[str], top_k: int):
        self.reranked = candidates
        return [{"index": 1, "score": 0.96}, {"index": 0, "score": 0.81}][:top_k]


def test_search_excludes_other_tenants_and_wrong_lifecycle_before_reranking():
    gateway = RecordingGateway()
    search = TenantKnowledgeSearch(gateway, "saas-operations")

    hits = search.search("acme", "onboarding", "Who should configure SSO?", 2)

    assert gateway.reranked == [
        "Configure SSO during setup.",
        "Assign the least privileged admin role.",
    ]
    assert [hit.content_id for hit in hits] == ["roles", "setup-sso"]
