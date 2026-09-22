"""Align upstream RTC queue replacement with actions actually consumed.

Inference wall time is a prediction for guidance, not evidence that the actor
advanced. In particular, model cold-start time must not skip the first motion.
This hook is installed only in RTC subprocesses; it never changes motor limits.
"""
import logging
import threading


def install_rtc_queue_alignment():
    from lerobot.policies.rtc.action_queue import ActionQueue

    if getattr(ActionQueue, '_atr_consumed_alignment', False):
        return
    original_merge = ActionQueue.merge
    original_index = ActionQueue.get_action_index
    original_left_over = ActionQueue.get_left_over
    logger = logging.getLogger('atr.lerobot.rtc')

    def get_action_index(self):
        if not self.cfg.enabled:
            return original_index(self)
        # The installed RTC driver calls index then leftovers as a pair. Pin
        # both to one origin even if the actor consumes between those calls.
        # Each producer thread gets its own one-use snapshot; a subsequent
        # index read replaces it and merge clears an unused snapshot.
        with self.lock:
            if not hasattr(self, '_atr_prefix_snapshot'):
                self._atr_prefix_snapshot = threading.local()
            self._atr_prefix_snapshot.value = (
                None if self.original_queue is None
                else self.original_queue[self.last_index:].clone()
            )
            return self.last_index

    def get_left_over(self):
        if self.cfg.enabled:
            with self.lock:
                snapshot = getattr(self, '_atr_prefix_snapshot', None)
                if snapshot is not None and hasattr(snapshot, 'value'):
                    value = snapshot.value
                    del snapshot.value
                    return value
        return original_left_over(self)

    def merge(self, original_actions, processed_actions, real_delay,
              action_index_before_inference=0):
        if not self.cfg.enabled or action_index_before_inference is None:
            return original_merge(self, original_actions, processed_actions,
                                  real_delay, action_index_before_inference)
        # Read consumption and replace under the SAME lock used by get().
        # Taking the count and calling original_merge outside this lock races
        # the actor; calling original_merge inside it deadlocks its plain Lock.
        with self.lock:
            snapshot = getattr(self, '_atr_prefix_snapshot', None)
            if snapshot is not None and hasattr(snapshot, 'value'):
                del snapshot.value
            consumed = self.last_index - action_index_before_inference
            if consumed < 0:
                raise RuntimeError('RTC action queue changed during inference')
            if consumed != real_delay:
                count = getattr(self, '_atr_alignment_corrections', 0) + 1
                self._atr_alignment_corrections = count
                if count == 1 or count % 100 == 0:
                    logger.info('[RTC_ALIGNMENT] estimated=%s consumed=%s corrections=%s',
                                real_delay, consumed, count)
            self._replace_actions_queue(original_actions, processed_actions, consumed)

    ActionQueue.merge = merge
    ActionQueue.get_action_index = get_action_index
    ActionQueue.get_left_over = get_left_over
    ActionQueue._atr_consumed_alignment = True
