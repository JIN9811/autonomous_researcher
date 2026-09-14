"""Measured observations must not depend on retired simulation services."""
import pytest

from agents.analysis.agent import AnalysisAgent
from tests.unit.test_analysis_agent import _CtxStub, _state


@pytest.mark.asyncio
async def test_measured_analysis_has_only_processing_and_validation_decisions(tmp_path, monkeypatch):
    monkeypatch.setattr('agents.analysis.agent.resolve_path', lambda value: tmp_path / value)
    result = await AnalysisAgent().run(_state(), _CtxStub(force_real_llm_in_test=True))
    assert result.success
    analysis = result.data['analysis']
    assert [d['phase'] for d in analysis['decisions']] == ['data_processing', 'data_validation']
    assert result.data['metrics']['peak_force_N'] == 520.0
    assert result.data['bo_observation']
    assert not {'model_pin', 'improvement', 'fem_job', 'fem_result', 'cae_result'} & analysis.keys()


def test_analysis_advertises_no_computation_bridge_dependency():
    from agents.analysis.module import MODULE
    descriptor = MODULE.describe()
    assert descriptor['dependencies']['bridge_modules'] == []
    assert descriptor['dependencies']['tools'] == []
