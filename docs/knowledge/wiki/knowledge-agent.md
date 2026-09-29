---
{"topic_id":"knowledge-agent","owner":"knowledge","source_refs":["docs/knowledge/wiki_memory.md","docs/knowledge/publication.md","docs/agents/knowledge_agent.md"],"source_revision":{"docs/knowledge/wiki_memory.md":"102fd79452f7183129dd55319c0b9c12755a6b52fedef8d1150ceec644d1a387","docs/knowledge/publication.md":"e97dab54bf4de8be668589091b6fd06e2cfbd9307b56f3db527e90f780734371","docs/agents/knowledge_agent.md":"50fb0e895786e33459075f47d6471374edd2e41922d8a4498f5df2a4d64d776d"},"verified_at":"2026-09-18T00:00:00+09:00","applicability":"Public AX4LAB reference: knowledge-agent","status":"reviewed"}
---

# Knowledge Stores — Wiki, Memory and Source Library

Platform explanations, private context, literature and experimental results have different ownership, privacy and lifecycles. They are not a single chat-history store.

| Store | Contents | Reading criteria |
|---|---|---|
| AX4LAB Wiki | Reviewed platform explanations | Source hashes and freshness |
| Private Memory | Confirmed preferences, research context and decisions | Trusted identity and permitted scope |
| Source Library | Original literature and curated material | Source, page and block citations |
| Execution Knowledge | Run/loop observations and interpretations | Specimen, run and evidence identity |

## Wiki sources

The Wiki is a reviewed guide, not an automatic copy of every document. Source references and SHA-256 revisions determine fresh/stale status. Changed sources require content review; updating hashes alone is not review.

## Private memory lifecycle

A memory proposal is a candidate, not an active instruction before confirmation. Edits require revision-aware confirmation; temporary memories have expiry limits. Forget removes stored memory and its private history, not original conversations or experiment artifacts.

Without trusted user identity, the default installation exposes only public Wiki access. A local connection does not authorize private memory.

## Workspace views

Wiki explains the platform; Memory manages permitted memories; Source Library exposes literature. Agent Delivery distinguishes retrieval, delivery and citation. Ontology presents categories and relationships. Sharing a workspace does not imply one unified retrieval pipeline.

Private conversations, raw experiment data and device secrets must not enter public documentation.

Retired Evolution/graph execution records are historical material. Their presence in a store does not require the current Knowledge owner to execute those retired workflows.

[Publication boundary](../publication.md), [Knowledge role](knowledge-role.md), [Wiki and Memory reference](../wiki_memory.md).
