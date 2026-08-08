CREATE CONSTRAINT atr_knowledge_entity_id IF NOT EXISTS
FOR (n:ATRKnowledgeNode) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT atr_knowledge_event_id IF NOT EXISTS
FOR (n:ATRKnowledgeEvent) REQUIRE n.event_id IS UNIQUE;

CREATE CONSTRAINT atr_knowledge_relation_id IF NOT EXISTS
FOR ()-[r:ATR_KNOWLEDGE_REL]-() REQUIRE r.id IS UNIQUE;

CREATE CONSTRAINT atr_ontology_version_id IF NOT EXISTS
FOR (n:ATROntologyVersion) REQUIRE n.version_id IS UNIQUE;
