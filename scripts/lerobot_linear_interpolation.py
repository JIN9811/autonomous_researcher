"""Optional transmit-only adapter shared by ordinary and RTC rollout wrappers."""
import json
import os
from pathlib import Path
import sys


def install_linear_if_enabled():
    if os.environ.get('ATR_LINEAR_ENABLED') != '1':
        return False
    config = json.loads(os.environ['ATR_LINEAR_CONFIG'])
    source = Path(__file__).resolve().parents[1] / 'libs/joint_linear_interpolation/src'
    sys.path.insert(0, str(source))
    from joint_linear_interpolation import LinearTransmit, finite
    input_hz, output_hz = finite(config['input_hz']), finite(config['output_hz'])
    if not 0 < input_hz <= output_hz <= 100:
        raise ValueError('require 0 < input Hz <= output Hz <= 100')
    from lerobot.robots.omx_follower.omx_follower import OmxFollower
    if getattr(OmxFollower, '_atr_linear_installed', False):
        return True
    original_connect, original_disconnect = OmxFollower.connect, OmxFollower.disconnect

    def connect(self, *args, **kwargs):
        original_connect(self, *args, **kwargs)
        try:
            self._atr_linear = LinearTransmit(self.bus, input_hz=input_hz,
                output_hz=output_hz, session_id=config.get('session_id', ''),
                log_dir=os.environ.get('ATR_LEROBOT_OMX_ACTION_LOG_DIR'))
        except BaseException:
            original_disconnect(self)
            raise

    def disconnect(self, *args, **kwargs):
        sender = getattr(self, '_atr_linear', None)
        if sender:
            sender.close()
        return original_disconnect(self, *args, **kwargs)

    OmxFollower.connect, OmxFollower.disconnect = connect, disconnect
    OmxFollower._atr_linear_installed = True
    return True
