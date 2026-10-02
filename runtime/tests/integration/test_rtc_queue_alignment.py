"""RTC wrapper contract using the installed queue, without robot/model access."""
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def restore_rtc_queue_hooks(monkeypatch):
    module = pytest.importorskip('lerobot.policies.rtc.action_queue')
    for name in ('merge', 'get_action_index', 'get_left_over'):
        monkeypatch.setattr(module.ActionQueue, name, getattr(module.ActionQueue, name))
    monkeypatch.setattr(module.ActionQueue, '_atr_consumed_alignment', False, raising=False)


@pytest.mark.parametrize('consumed,estimated,expected', [(0, 13, 0), (4, 5, 4), (2, 1, 2)])
def test_rtc_wrapper_does_not_skip_unexecuted_actions(monkeypatch, consumed, estimated, expected):
    torch = pytest.importorskip('torch')
    module = pytest.importorskip('lerobot.policies.rtc.action_queue')
    from lerobot.policies.rtc.configuration_rtc import RTCConfig
    from scripts import lerobot_live_rollout_wrapper as wrapper

    # Restore the class hook after each test; only script launch is substituted.
    monkeypatch.setattr(module.ActionQueue, 'merge', module.ActionQueue.merge)
    monkeypatch.setattr(module.ActionQueue, '_atr_consumed_alignment', False, raising=False)

    def run_script(*args, **kwargs):
        queue = module.ActionQueue(RTCConfig(enabled=True))
        if consumed:
            prior = torch.arange(50.).reshape(-1, 1)
            queue.merge(prior, prior, 0, 0)
        index = queue.get_action_index()
        for _ in range(consumed):
            assert queue.get() is not None
        chunk = torch.arange(50.).reshape(-1, 1)
        queue.merge(chunk, chunk + 100, estimated, index)
        assert queue.qsize() == 50 - expected
        assert queue.get().item() == 100 + expected
        assert queue.get_left_over()[0].item() == expected + 1

    monkeypatch.setattr(wrapper.runpy, 'run_path', run_script)
    monkeypatch.setattr(sys, 'argv', ['rollout', '--rtc.enabled=true'])
    wrapper._lerobot_rtc_main()()


@pytest.mark.parametrize('output_hz', [None, 60, 100])
def test_rtc_startup_targets_reach_existing_bus_with_interpolation_on_or_off(monkeypatch, output_hz):
    torch = pytest.importorskip('torch')
    module = pytest.importorskip('lerobot.policies.rtc.action_queue')
    from lerobot.policies.rtc.configuration_rtc import RTCConfig
    from scripts.lerobot_rtc_queue_alignment import install_rtc_queue_alignment
    monkeypatch.setattr(module.ActionQueue, 'merge', module.ActionQueue.merge)
    monkeypatch.setattr(module.ActionQueue, '_atr_consumed_alignment', False, raising=False)
    install_rtc_queue_alignment()
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] /
                                   'libs/joint_linear_interpolation/src'))
    from joint_linear_interpolation import LinearTransmit

    class Bus:
        def __init__(self):
            self.position = {'joint': 0.}
            self.commands = []
        def sync_read(self, register):
            return dict(self.position)
        def sync_write(self, register, values):
            self.commands.append(dict(values))
            self.position.update(values)

    queue = module.ActionQueue(RTCConfig(enabled=True))
    chunk = torch.tensor([[1.], [2.], [3.]])
    # Cold-start estimate exceeds the entire chunk: the old path sent nothing.
    queue.merge(chunk, chunk, 13, 0)
    bus = Bus()
    sender = LinearTransmit(bus, input_hz=15, output_hz=output_hz) if output_hz else None
    try:
        for target in [1., 2., 3.]:
            action = queue.get()
            assert action is not None
            assert action.item() == target
            bus.sync_write('Goal_Position', {'joint': action.item()})
            deadline = time.monotonic() + 1
            while bus.position['joint'] != target and time.monotonic() < deadline:
                time.sleep(.002)
            assert bus.sync_read('Present_Position')['joint'] == target
        assert queue.get() is None
    finally:
        if sender:
            sender.close()
    assert bus.commands[-1] == {'joint': 3.}
    assert len(bus.commands) > 3 if sender else len(bus.commands) == 3


def test_non_rtc_queue_still_appends_without_alignment(monkeypatch):
    torch = pytest.importorskip('torch')
    module = pytest.importorskip('lerobot.policies.rtc.action_queue')
    from lerobot.policies.rtc.configuration_rtc import RTCConfig
    from scripts.lerobot_rtc_queue_alignment import install_rtc_queue_alignment
    monkeypatch.setattr(module.ActionQueue, 'merge', module.ActionQueue.merge)
    monkeypatch.setattr(module.ActionQueue, '_atr_consumed_alignment', False, raising=False)
    install_rtc_queue_alignment()
    queue = module.ActionQueue(RTCConfig(enabled=False))
    first = torch.tensor([[1.], [2.]])
    queue.merge(first, first, 13, 0)
    assert queue.get().item() == 1.
    next_chunk = torch.tensor([[3.], [4.]])
    queue.merge(next_chunk, next_chunk, 5, 0)
    assert [queue.get().item() for _ in range(3)] == [2., 3., 4.]


def test_rtc_prefix_and_index_are_one_snapshot_even_if_actor_advances(monkeypatch):
    torch = pytest.importorskip('torch')
    from lerobot.policies.rtc.action_queue import ActionQueue
    from lerobot.policies.rtc.configuration_rtc import RTCConfig
    from scripts.lerobot_rtc_queue_alignment import install_rtc_queue_alignment
    install_rtc_queue_alignment()
    queue = ActionQueue(RTCConfig(enabled=True))
    seed = torch.arange(5.).reshape(-1, 1)
    queue.merge(seed, seed, 0, 0)
    index = queue.get_action_index()
    assert queue.get().item() == 0.  # actor interleaves between the two reads
    prefix = queue.get_left_over()
    assert prefix[0].item() == 0.  # snapshot corresponds to saved index, not 1
    assert queue.get_left_over()[0].item() == 1.  # paired snapshot is one-use
    queue.merge(prefix, prefix, 2, index)
    assert queue.get().item() == 1.  # never skip the still-unexecuted action
    assert queue.get().item() == 2.
    next_index = queue.get_action_index()
    assert next_index == 2
    next_prefix = queue.get_left_over()
    assert next_prefix[0].item() == 3.
    assert queue.get().item() == 3.
    queue.merge(next_prefix, next_prefix, 2, next_index)
    assert queue.get().item() == 4.
