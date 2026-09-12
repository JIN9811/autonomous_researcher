"""Bounded orchestration decisions and semantic chat intake."""

from copy import deepcopy
import json
import math
from uuid import uuid4


TOOL_ARGUMENTS = {
    'inspect_context': {'evidence_ids': 'strings'},
    'inspect_availability': {'owner': 'text', 'capability': 'text'},
    'propose_setup_change': {'block_id': 'text', 'revision': 'revision', 'changes': 'object'},
    'request_owner_review': {'owner': 'text', 'issues': 'strings'},
    'prepare_handoff': {'candidate': 'text'},
    'defer': {'condition': 'text'},
}
TERMINAL = {'prepare_handoff': 'prepared', 'propose_setup_change': 'proposed',
            'request_owner_review': 'review_required', 'defer': 'deferred'}


def _json_response(text):
    """Match the single JSON envelope accepted by the other bounded owners.

    Extra prose, multiple blocks and trailing JSON remain invalid; schema and
    authorization validation still run after decoding.
    """
    raw = str(text or '').strip()
    if raw.startswith('```json\n') and raw.endswith('```'):
        raw = raw[8:-3].strip()
    return json.loads(raw)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _strings(value):
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value)


def validate_choice(payload: dict, allowed_tools: set[str], evidence_ids: set[str]) -> dict:
    """Reject all undeclared keys, argument shapes and unregistered references."""
    if not isinstance(payload, dict) or set(payload) != {'tool', 'arguments', 'reason', 'evidence_refs'}:
        raise ValueError('Choice must contain exactly tool, arguments, reason, evidence_refs')
    tool = payload['tool']
    if not isinstance(tool, str) or tool not in TOOL_ARGUMENTS or tool not in allowed_tools:
        raise ValueError('Unregistered tool')
    args = payload['arguments']
    schema = TOOL_ARGUMENTS[tool]
    if not isinstance(args, dict) or set(args) != set(schema):
        raise ValueError('Invalid tool argument keys')
    checks = {'text': _text, 'strings': _strings,
              'revision': lambda v: type(v) is int and v >= 0,
              'object': lambda v: isinstance(v, dict) and bool(v)}
    if not all(checks[kind](args[key]) for key, kind in schema.items()):
        raise ValueError('Invalid tool argument types')
    if not _text(payload['reason']) or not _strings(payload['evidence_refs']):
        raise ValueError('Nonempty reason and evidence references required')
    if not set(payload['evidence_refs']) <= evidence_ids:
        raise ValueError('Unknown evidence reference')
    if tool == 'inspect_context' and not set(args['evidence_ids']) <= evidence_ids:
        raise ValueError('Unknown context evidence')
    return deepcopy(payload)


def _scope(state, context):
    return {'run_id': state.run_id, 'loop': state.loop_count, 'stage': state.stage.value,
            'context': deepcopy(context['current_scope']() if context.get('current_scope') else context.get('scope', {}))}


def _validate_target(choice, context, evidence):
    tool, args = choice['tool'], choice['arguments']
    if tool == 'prepare_handoff':
        if args['candidate'] not in context.get('handoff_candidates', []):
            raise ValueError('Candidate is not admitted by the current dispatcher')
        if not set(context.get('required_evidence', [])) <= set(evidence):
            raise ValueError('Required handoff evidence is missing')
    if tool in {'inspect_availability', 'request_owner_review'}:
        if args['owner'] not in context.get('owners', []):
            raise ValueError('Unknown owner')
    if tool == 'inspect_availability':
        if args['capability'] not in context.get('capabilities', {}).get(args['owner'], []):
            raise ValueError('Unknown capability')
    if tool == 'propose_setup_change':
        block = context.get('setup_blocks', {}).get(args['block_id'])
        if not isinstance(block, dict) or args['revision'] != block.get('revision'):
            raise ValueError('Unknown or stale setup block')
        if not set(args['changes']) <= set(block.get('fields', [])):
            raise ValueError('Undeclared setup field')


async def decide_orchestration(state, ctx, *, context: dict, handlers: dict) -> dict:
    """Run one bounded decision. Handlers own atomic endpoint validation and effects.

    No model/tool retries here. Cancellation propagates; tool errors are terminal.
    Required evidence means trusted, already-validated admission evidence IDs, not
    blanket availability requirements. A prepared handoff never declares readiness.

    Terminal handler dictionaries may contain status, success, ok and reason.
    Either explicit boolean success=False or ok=False overrides other fields and
    means failed. Negative status rejected/unknown/stale/blocked means failed;
    failed/deferred/review_required propagates. Otherwise a successfully returned
    dictionary maps to the selected terminal tool's status. Omitted success/ok
    flags are permitted for existing packet/store adapters. Adapters must expose
    owner denials using these normalized fields, not arbitrary nested payloads.
    """
    scope = {'run_id': state.run_id, 'loop': state.loop_count, 'stage': state.stage.value,
             'context': deepcopy(context.get('scope', {}))}
    result = dict(decision_id=str(uuid4()), status='failed', tool=None, arguments={},
                  reason='', evidence_refs=[], model=None, trace=[], scope=scope)
    evidence = deepcopy(context.get('evidence', {}))
    settings = context.get('settings', {})
    max_steps = settings.get('max_steps', 4)
    timeout = settings.get('timeout_s')
    if (type(max_steps) is not int or max_steps < 1 or
        (timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0))):
        result['reason'] = 'Invalid decision budget'
        return result
    public_context = {key: deepcopy(context[key]) for key in (
        'handoff_candidates', 'owners', 'capabilities', 'setup_blocks', 'required_evidence', 'request') if key in context}
    for _ in range(max_steps):
        try:
            prompt_packet = {
                'operation': 'decide_orchestration', 'scope': scope, 'context': public_context,
                'evidence': evidence, 'trace': result['trace'],
                'policy': 'Return only the decision JSON schema, never intake intent/classification fields. '
                          'Cite only enumerated top-level evidence keys; nested provenance references are not registered IDs.',
                'tools': {name: TOOL_ARGUMENTS[name] for name in handlers if name in TOOL_ARGUMENTS},
                'response_schema': {'tool': 'registered name', 'arguments': 'exact tool arguments',
                                    'reason': 'short explanation',
                                    'evidence_refs': {'type': 'array', 'items': {'enum': sorted(evidence)}}},
            }
            if context.get('prompt_projection'):
                prompt_packet = context['prompt_projection'](prompt_packet)
            response = await ctx.complete('orchestrator_plan', json.dumps(prompt_packet, ensure_ascii=False),
                timeout_s=settings.get('timeout_s'))
            result['model'] = response.model
            selected = validate_choice(_json_response(response.text), set(handlers), set(evidence))
            _validate_target(selected, context, evidence)
            if _scope(state, context) != scope:
                raise ValueError('Decision scope changed before effect')
        except Exception as exc:
            result['reason'] = f'{type(exc).__name__}: {exc}'
            return result
        result.update(selected)
        try:
            effect = await handlers[selected['tool']](deepcopy(selected['arguments']))
            if not isinstance(effect, dict):
                raise ValueError('Tool result must be an object')
        except Exception as exc:
            result['reason'] = f'Tool failed: {type(exc).__name__}: {exc}'
            result['trace'].append({'choice': selected, 'error': result['reason']})
            return result
        result['trace'].append({'choice': selected, 'result': deepcopy(effect)})
        if _scope(state, context) != scope:
            result['reason'] = 'Decision scope changed during effect; do not consume handoff'
            return result
        tool = selected['tool']
        if tool in TERMINAL:
            result['effect'] = deepcopy(effect)
            if (effect.get('status') in {'rejected', 'unknown', 'stale', 'blocked'}
                    or effect.get('success') is False or effect.get('ok') is False):
                result['status'] = 'failed'
                result['reason'] = str(effect.get('reason') or 'Handler did not authorize effect')
            elif effect.get('status') in {'failed', 'deferred', 'review_required'}:
                result['status'] = effect['status']
            else:
                result['status'] = TERMINAL[tool]
            return result
        additions = effect.get('evidence', {})
        if not isinstance(additions, dict) or not all(_text(key) for key in additions):
            result['reason'] = 'Invalid inspection evidence'
            return result
        evidence.update(deepcopy(additions))
    result.update(status='deferred', reason='Decision inspection budget exhausted')
    return result


async def classify_chat_request(state, ctx, *, message: str, pending_id: str | None = None,
                                context: dict | None = None) -> dict:
    """Semantic intake only; never performs actions or grants unbound approval."""
    context = context or {}
    unclear = {'intent': 'unclear', 'reason': 'Unable to establish a scoped request', 'pending_id': None}
    try:
        response = await ctx.complete('orchestrator_plan', json.dumps({
            'operation': 'classify_chat_request', 'message': message,
            'pending_id': pending_id, 'run_id': state.run_id,
            'context': context.get('request', {}),
            'policy': 'Classify semantics, not keyword substrings. Questions, negations, quoted commands '
                      'and hypothetical examples never authorize execution. An arbitrary yes/approval '
                      'without a server pending_id is unclear. pending_id MUST be null for every '
                      'intent except confirm_pending, even when asking about a pending task. '
                      'A conditional pending request is not ordinary approval: confirm_pending requires '
                      'the operator to explicitly request its described action. If fresh observation is '
                      'required, generic yes/continue is unclear; only an explicit fresh observation '
                      'request can confirm that pending action. '
                      'Do not extract execution arguments.',
            'response_schema': {'intent': ['question', 'change_setup', 'start_run', 'confirm_pending', 'out_of_scope', 'unclear'],
                                'reason': 'short explanation', 'pending_id': 'server pending ID or null'},
        }, ensure_ascii=False), timeout_s=context.get('settings', {}).get('timeout_s'))
        value = _json_response(response.text)
        if not isinstance(value, dict) or set(value) != {'intent', 'reason', 'pending_id'}:
            return unclear
        if value['intent'] not in ('question', 'change_setup', 'start_run', 'confirm_pending', 'out_of_scope', 'unclear') or not _text(value['reason']):
            return unclear
        if value['intent'] == 'confirm_pending':
            if not _text(pending_id) or value['pending_id'] != pending_id:
                return unclear
        elif value['pending_id'] is not None:
            return unclear
        return value
    except Exception:
        return unclear
