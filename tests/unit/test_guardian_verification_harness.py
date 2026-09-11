"""No production device registrations may enter the Guardian model probe."""
from importlib.util import find_spec

import pytest


def harness():
    assert find_spec('scripts.verify_guardian_decisions') is not None, 'Guardian non-actuating probe is missing'
    from scripts import verify_guardian_decisions
    return verify_guardian_decisions


def test_virtual_registry_rejects_motion_and_preserves_scope():
    module = harness()
    state = module.make_state('normal', 'probe-one')
    tools, calls = module.virtual_tools(state)
    result = tools.call('device.health', {})
    assert result['ok'] is True
    assert result['robot'] == 'ready'
    with pytest.raises(KeyError):
        tools.call('printer.start', {})
    with pytest.raises(KeyError):
        tools.call('lerobot.replay.start', {})
    assert calls == ['device.health']


def test_probe_does_not_count_bypassed_model_as_success():
    module = harness()
    guardian = {'action': 'continue', 'llm_decision': {'llm_used': False, 'status': 'skipped'}}
    assert module.expectation('normal', guardian, []) is False


def test_probe_requires_expected_actual_backend():
    module = harness()
    calls = [{'backend': 'openai', 'model': 'api-model'}]
    assert module.backend_matches(calls, 'vllm', 'local-model') is False
    assert module.backend_matches(calls, 'openai', 'api-model') is True
    assert module.backend_matches([], 'vllm', 'local-model') is False


def test_conflict_requires_accepted_reasoning_not_format_failure():
    module = harness()
    guardian = {'action': 'recover', 'llm_decision': {'llm_used': True, 'status': 'review_required'}}
    assert module.expectation('conflict', guardian, []) is False
    guardian['llm_decision']['status'] = 'accepted'
    guardian['llm_decision']['action'] = 'continue'
    assert module.expectation('conflict', guardian, []) is False
    guardian['llm_decision']['action'] = 'review'
    assert module.expectation('conflict', guardian, []) is True


def test_virtual_queue_rejects_foreign_run():
    module = harness()
    tools, _ = module.virtual_tools(module.make_state('normal', 'probe-one'))
    with pytest.raises(ValueError):
        tools.call('experiment.queue.status', {'run_id': 'another-run'})


def test_probe_requires_served_model_receipts_to_match():
    module = harness()
    assert module.responses_match([{'model': 'different-model'}], 'requested-model') is False
    assert module.responses_match([], 'requested-model') is False
    assert module.responses_match([{'model': 'requested-model'}], 'requested-model') is False
    assert module.responses_match([{'model': 'requested-model', 'provider_model': 'different-model'}], 'requested-model') is False
    assert module.responses_match([{'model': 'requested-model', 'provider_model': 'requested-model'}], 'requested-model') is True
    assert module.responses_match([{'model': 'gpt-5.5', 'provider_model': 'gpt-5.5-2026-04-23'}], 'gpt-5.5') is True
    assert module.responses_match([{'model': 'gpt-5.5', 'provider_model': 'gpt-5.5-unknown'}], 'gpt-5.5') is False


def test_cli_requires_opt_in():
    module = harness()
    with pytest.raises(SystemExit):
        module.parse_args([])


@pytest.mark.asyncio
async def test_model_receipt_keeps_response_text_without_provider_raw_payload():
    from backends.mock_llm import MockLLMBackend
    module = harness()
    provider = module.RecordingBackend(MockLLMBackend())
    response = await provider.complete(model='fixture-model', system_prompt='review', user_prompt='test')
    assert provider.responses == [{'model': 'fixture-model', 'provider_model': None, 'text': response.text}]
    assert 'raw' not in provider.responses[0]
