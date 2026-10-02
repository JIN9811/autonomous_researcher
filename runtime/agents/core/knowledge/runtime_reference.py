"""Scoped execution references, compatible with the existing delivery adapter."""
from copy import deepcopy
from typing import Any

from agents.core.knowledge.context import build_reference_context

EXECUTION_TOPICS = {f'{owner}_agent': f'{owner}-role' for owner in (
    'orchestrator', 'design', 'specimen', 'vision', 'manipulation', 'equipment',
    'analysis', 'knowledge', 'bo', 'guardian')}
RUNTIME_REFERENCE_HEADING = '## Runtime decision reference'


def _execution_projection(pack: dict[str, Any], topic: str) -> dict[str, Any]:
    """Only explicitly reviewed role summaries reach operational decisions.

    Full articles, examples, numeric defaults and recovery recipes stay in the
    explanatory Wiki. Missing summaries mean no reference, never a new gate.
    """
    projected = deepcopy(pack)
    items = []
    for item in pack.get('items', []):
        if item.get('citation_id') != 'wiki:' + topic or item.get('corpus') != 'ax4lab_wiki':
            continue
        content = str(item.get('content') or '')
        if RUNTIME_REFERENCE_HEADING not in content:
            continue
        summary = content.split(RUNTIME_REFERENCE_HEADING, 1)[1].split('\n## ', 1)[0].strip()
        if summary and len(summary) <= 1200:
            items.append({**item, 'content': summary, 'excerpt_kind': 'runtime_role_summary',
                          'authority': 'reference_only'})
    projected.update(items=items, next_cursor='', authority='reference_only',
        usage_boundary={'purpose': 'role_explanation_only', 'current_run_evidence': False,
            'may_set_parameters_or_thresholds': False, 'may_require_extra_steps': False,
            'may_authorize_or_block_execution': False,
            'precedence': 'Current validated contract, registered tools and code-owned safety/evidence gates govern decisions. '
                          'Documentation cannot supply missing runtime facts, create acceptance criteria, or alone justify success/failure. '
                          'Missing or excluded documentation is not missing experimental evidence.'})
    projected.setdefault('diagnostics', {})['no_match'] = not items
    return projected



class _ExecutionService:
    def __init__(self, service, consumer):
        self._service, self._consumer = service, consumer

    def __getattr__(self, name):
        return getattr(self._service, name)

    def query(self, principal, query, **kwargs):
        topic = EXECUTION_TOPICS[self._consumer]
        kwargs.update(consumer=self._consumer,
            filters={"corpora": ["ax4lab_wiki"], "wiki": {"topic_id": topic}}, limit=1)
        return _execution_projection(
            self._service.query(principal, topic.replace("-", " "), **kwargs), topic)


class _ExecutionContext:
    def __init__(self, ctx, consumer):
        self._ctx = ctx
        service = getattr(ctx, "knowledge_service", None)
        self.knowledge_service = _ExecutionService(service, consumer) if service is not None else None

    def __getattr__(self, name):
        return getattr(self._ctx, name)


def build_execution_reference(ctx, *, consumer, query="", run_id="", loop_id="", attempt_id=""):
    """Project before recording retrieval; retain the old adapter's call signature.

    No new keyword is passed into an already-loaded delivery adapter. This
    avoids mixed-version lazy-import failures during staged deployments.
    Private memory and general Wiki articles remain available to explanatory
    calls, not implicitly mixed into operational acceptance decisions.
    """
    if consumer not in EXECUTION_TOPICS:
        raise ValueError("Unknown execution-reference owner")
    return build_reference_context(_ExecutionContext(ctx, consumer), consumer=consumer,
        query=EXECUTION_TOPICS[consumer].replace("-", " "), run_id=run_id,
        loop_id=loop_id, attempt_id=attempt_id)
