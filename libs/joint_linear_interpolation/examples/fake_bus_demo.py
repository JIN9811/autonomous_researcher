"""No hardware: show how a 30 Hz target is transmitted as smaller steps."""
import time

from joint_linear_interpolation import LinearTransmit


class FakeBus:
    def __init__(self):
        self.positions = {'joint_1': 0.}

    def sync_read(self, register):
        return dict(self.positions)

    def sync_write(self, register, values):
        self.positions.update(values)
        print(f'{time.monotonic():.4f} {values}')


if __name__ == '__main__':
    bus = FakeBus()
    sender = LinearTransmit(bus, input_hz=30, output_hz=100)
    try:
        bus.sync_write('Goal_Position', {'joint_1': 1.})
        time.sleep(.1)
    finally:
        sender.close()
