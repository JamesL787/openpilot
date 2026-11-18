from opendbc.car import structs
from opendbc.car.honda.values import CAR, HondaFlags
from opendbc.car.honda.tests.test_modified_eps import eps, params
from opendbc.car.honda.tests.test_clarity_angle_mode import MODIFIED
from openpilot.starpilot.car.honda import clarity_angle_mode as startup


class Params:
  def __init__(self, value=None, error=None):
    self.value, self.error = value, error

  def get(self, key, return_default=False):
    assert key == "HondaClarityAngleMode" and return_default
    if self.error:
      raise self.error
    return self.value


ANGLE = structs.CarParams.SteerControlType.angle


def angle(cp):
  return bool(cp.flags & HondaFlags.CLARITY_ANGLE_MODE) and cp.steerControlType == ANGLE


def test_setting_on_picks_angle_mode_on_a_modified_clarity():
  assert angle(startup.prepare(params(CAR.HONDA_CLARITY, [eps(MODIFIED)]), Params(True)))


def test_setting_off_keeps_torque():
  assert not angle(startup.prepare(params(CAR.HONDA_CLARITY, [eps(MODIFIED)]), Params(False)))


def test_unreadable_or_unknown_setting_uses_the_default_on():
  assert startup.DEFAULT is True
  assert angle(startup.prepare(params(CAR.HONDA_CLARITY, [eps(MODIFIED)]), Params(None)))
  assert angle(startup.prepare(params(CAR.HONDA_CLARITY, [eps(MODIFIED)]), Params(error=KeyError("unknown"))))


def test_stock_eps_clarity_is_never_switched():
  assert not angle(startup.prepare(params(CAR.HONDA_CLARITY, [eps(b'39990-TRW-A020\x00\x00')]), Params(True)))
