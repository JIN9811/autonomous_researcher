"""Bounded Chat management grammar; identity and grants only come from the server."""
import re
from uuid import uuid4

_ID = r'(mem-[0-9a-f]{32})'
_READ = re.compile(r'(?:read|show) memory ' + _ID + r'\s*$', re.I)
_CHANGE = re.compile(r'(confirm )?(edit|forget|confirm) memory ' + _ID + r' revision ([1-9][0-9]{0,8})(?::\s*(.+))?\s*$', re.I | re.S)


def proposal_scope(text, principal):
    """Never convert an unresolved temporary/project request to user persistence."""
    lowered = text.casefold()
    if any(term in lowered for term in ('session', 'this run', '세션', '이번 실행', 'today only', '오늘만')):
        raise ValueError('Clarify the authorized session/run scope and explicit expiry in Memory Workspace; no memory was retained.')
    if any(term in lowered for term in ('project', '프로젝트')):
        if len(principal.project_ids) != 1:
            raise ValueError('Clarify the authorized project scope in Memory Workspace; no memory was retained.')
        return {'kind': 'project', 'project_id': next(iter(principal.project_ids))}
    return {'kind': 'user'}


def manage_memory(controller, message, session_id):
    lowered = message.casefold()
    read = _READ.fullmatch(message)
    change = _CHANGE.fullmatch(message)
    list_request = lowered in {'show memories', 'list memories', 'what do you remember?', '기억 목록', '저장된 기억 보여줘'}
    related = list_request or read or change or lowered.startswith(('read memory', 'show memory', 'edit memory', 'forget memory', 'confirm edit memory', 'confirm forget memory', 'confirm memory'))
    if not related: return None
    ctx = controller._deps.agent_context
    service, principal = getattr(ctx, 'knowledge_service', None), getattr(ctx, 'knowledge_principal', None)
    scope = (session_id, principal)
    pending = getattr(controller, '_knowledge_memory_pending', None)
    if pending and pending['scope'] != scope:
        controller._knowledge_memory_pending = None
        pending = None
    if service is None or principal is None:
        return {'ok': False, 'answer': 'Private memory requires a trusted server identity.', 'memory_receipt': {'status': 'unavailable'}}
    try:
        if list_request or read:
            rows = service.memory.query(principal, '', limit=10, include_content=True)['items'] if list_request else [service.memory.read(principal, read[1])]
            if any(item is None for item in rows): raise KeyError('unavailable')
            answer = '\n'.join(f"{item['record_id']} revision {item['revision']} ({item['scope']['kind']}, {item['status']}): {item['content']}" for item in rows) or 'No retained memories in this authorized scope.'
            return {'ok': True, 'answer': answer[:12_000], 'memory_records': rows}
        if not change:
            return {'ok': False, 'answer': 'Use Read memory <record ID>, or Edit/Forget memory <record ID> revision <number>. Edits require : new text, then separate confirmation.'}
        confirm, action, record_id, revision, content = change.groups()
        revision = int(revision)
        item = service.memory.read(principal, record_id)
        if item is None: raise KeyError('unavailable')
        if item['revision'] != revision: raise ValueError('revision conflict')
        if action.casefold() == 'confirm' and not confirm and content is None:
            receipt = service.memory.command(principal, action='confirm', target_id=record_id,
                expected_revision=revision, payload={}, idempotency_key='chat-' + uuid4().hex)
            return {'ok': True, 'answer': 'Memory confirmed; this grants no Setup or execution permission.', 'memory_receipt': receipt}
        action = action.casefold()
        if action not in {'edit', 'forget'} or (action == 'forget' and content) or (action == 'edit' and not confirm and not content):
            raise ValueError('invalid command')
        if confirm:
            if content or not pending or any(pending[key] != value for key, value in {'action': action, 'target_id': record_id, 'expected_revision': revision}.items()):
                raise ValueError('confirmation does not match the pending memory change')
            receipt = service.memory.command(principal, action=action, target_id=record_id,
                expected_revision=revision, payload=pending['payload'], idempotency_key=pending['request_id'])
            controller._knowledge_memory_pending = None
            return {'ok': True, 'answer': 'Memory change applied; Setup and execution were not changed.', 'memory_receipt': receipt}
        controller._knowledge_memory_pending = {'scope': scope, 'action': action, 'target_id': record_id,
            'expected_revision': revision, 'payload': {'content': content} if action == 'edit' else {}, 'request_id': 'chat-' + uuid4().hex}
        return {'ok': True, 'answer': f'Review this exact memory change, then reply: Confirm {action} memory {record_id} revision {revision}. No change has been applied.',
            'memory_pending_command': {'action': action, 'target_id': record_id, 'expected_revision': revision}}
    except (PermissionError, KeyError):
        controller._knowledge_memory_pending = None
        return {'ok': False, 'answer': 'Memory record unavailable in this authorized scope.'}
    except (ValueError, OSError):
        return {'ok': False, 'answer': 'Memory change not applied. Review the exact record, revision, and pending confirmation; retry from the current record.'}
