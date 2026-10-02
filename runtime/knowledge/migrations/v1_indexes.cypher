CREATE INDEX atr_knowledge_run_id IF NOT EXISTS
FOR (n:ATRKnowledgeNode) ON (n.run_id);

CREATE INDEX atr_knowledge_cycle_id IF NOT EXISTS
FOR (n:ATRKnowledgeNode) ON (n.cycle_id);

CREATE INDEX atr_knowledge_status IF NOT EXISTS
FOR (n:ATRKnowledgeNode) ON (n.status);

CREATE INDEX atr_knowledge_occurred_at IF NOT EXISTS
FOR (n:ATRKnowledgeNode) ON (n.occurred_at);

CREATE INDEX atr_knowledge_ontology_version IF NOT EXISTS
FOR (n:ATRKnowledgeNode) ON (n.ontology_version);
