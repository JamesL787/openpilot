from openpilot.cereal import log
from openpilot.starpilot.longitudinal import human_acceleration

P = log.LongitudinalPersonality


def test_applies_relaxed_and_standard_only():
  assert human_acceleration.applies(P.relaxed)
  assert human_acceleration.applies(P.standard)
  assert not human_acceleration.applies(P.aggressive)


def test_cap_unchanged():
  # 30 mph set speed, 15 mph ego: between half and full max accel, ramp-off not reached.
  assert abs(human_acceleration.cap(2.0, 13.4, 6.7) - (1.0 + 1.0 * (13.4 - 12.5) / 12.5)) < 1e-6
