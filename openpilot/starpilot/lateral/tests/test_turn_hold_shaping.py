"""vfn's turn shaping on the turn hold (LatControlHondaEps cars): ramps, driver snap, no re-arm after an opposite release."""
from types import SimpleNamespace as NS

import pytest

from openpilot.starpilot.lateral.model_turn_assist import ModelTurnAssist, TURN_SHAPING_ALPHA


def model(curvature=0.0001, bend=0.05):
  # a plan bending right ahead (positive y), as at a stop line before a right turn
  return NS(position=NS(x=[float(x) for x in range(51)], y=[bend * x * x for x in range(51)]),
            meta=NS(laneChangeState=0), action=NS(desiredCurvature=curvature))


def car(v=0.0, pressed=False, torque=0.0):
  return NS(vEgo=v, standstill=v < 0.01, leftBlinker=False, rightBlinker=True, steeringPressed=pressed, steeringTorque=torque, aEgo=0.0)


def test_standstill_prewind_ramps_with_shaping_and_steps_without():
  cc = NS(latActive=True)
  plain, shaped = ModelTurnAssist(), ModelTurnAssist(shaping=True)
  step = [plain.update(car(), model(), cc, 0.0001) for _ in range(3)]
  ramp = [shaped.update(car(), model(), cc, 0.0001) for _ in range(200)]
  hold = shaped.turn_hold_curvature
  assert hold > 0.02 and plain.turn_hold_curvature == pytest.approx(hold)
  assert step[0] == pytest.approx(hold)                     # the Ioniq 6 port arms in one frame
  assert ramp[0] == pytest.approx(hold * TURN_SHAPING_ALPHA)  # shaped: 0.25 s low-pass
  assert all(b >= a for a, b in zip(ramp, ramp[1:])) and ramp[-1] == pytest.approx(hold, rel=0.01)


def test_driver_confirmed_capture_snaps():
  shaped = ModelTurnAssist(shaping=True)
  shaped.curvature = 0.05                                   # the wheel the driver has wound right
  out = shaped.update(car(v=1.5, pressed=True, torque=-500.0), model(bend=0.0), NS(latActive=True), 0.0001)
  assert out == pytest.approx(0.05)


def test_opposite_release_at_a_stop_does_not_rearm_with_shaping():
  cc = NS(latActive=True)
  for shaping, rearms in ((False, True), (True, False)):
    a = ModelTurnAssist(shaping=shaping)
    for _ in range(50):
      a.update(car(), model(), cc, 0.0001)
    assert a.turn_hold_curvature > 0.02
    a.update(car(), model(), cc, -0.02)                     # the model counter-steers at the stop
    assert a.turn_hold_curvature == 0.0
    a.update(car(), model(), cc, 0.0001)
    assert (a.turn_hold_curvature > 0.0) == rearms          # unshaped: the frame-rate hold/model flip-flop
  a.update(car(v=1.0), model(), cc, 0.0001)                 # moving off ends the stop: a fresh turn may arm
  a.update(car(v=0.0), model(), cc, 0.0001)
  assert a.turn_hold_curvature > 0.0
