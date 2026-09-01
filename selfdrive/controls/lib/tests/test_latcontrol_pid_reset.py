"""LatControlPID must not carry integrator state across a disengagement.

controlsd calls LaC.reset() on every frame lateral is inactive
(selfdrive/controls/controlsd.py:589-591), but the inherited LatControl.reset()
(selfdrive/controls/lib/latcontrol.py:47-48) clears only the saturation timer. LatControlPID's
own inactive branch cleared stiction, the pressed filter, the centre taper, the unwind state and
the previous output, but never the PID controller itself, so self.pid.i survived a disengagement
and was re-injected whole on the first frame after re-engagement.

The fixtures below are the measured values from two logged drives on the modified-EPS Civic
Bosch; see REENGAGEMENTS.
"""
# LatControlPID pulls in common.transformations.transformations, a compiled extension that only
# exists for the device architecture. Try the real one first -- on a device or in CI this block is a
# no-op -- and only if it will not load, stand in a module of the same shape so this file can be
# collected on a development host. The stubs raise if anything ever calls them: this suite exercises
# the lateral controller, never the geometry, and a silently wrong rotation would be worse than an
# ImportError. Nothing else is stubbed, and this is deliberately NOT a conftest so it cannot reach
# any other suite.
try:
  import openpilot.common.transformations.transformations  # noqa: F401
except (ImportError, OSError):
  import sys
  import types

  def _needs_native_extension(name):
    def unavailable(*args, **kwargs):
      raise RuntimeError(f"{name} needs the compiled transformations extension; this suite never calls it")
    return unavailable

  _stub = types.ModuleType("openpilot.common.transformations.transformations")
  for _fn in ("ecef_euler_from_ned_single", "euler2quat_single", "euler2rot_single",
              "ned_euler_from_ecef_single", "quat2euler_single", "quat2rot_single",
              "rot2euler_single", "rot2quat_single"):
    setattr(_stub, _fn, _needs_native_extension(_fn))
  sys.modules["openpilot.common.transformations.transformations"] = _stub

import math
from types import SimpleNamespace

import pytest

from opendbc.car import structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID

CarParams = structs.CarParams

TOGGLES = SimpleNamespace(force_torque_controller=False, nnff=False, nnff_lite=False)

# a comma in the eps fw version is what marks a modified EPS -- this is the car that was driven
MODIFIED_FW = b'39990-TGG,A120\x00\x00'

# LatControlPID only reaches into CI for the feedforward function
STUB_CI = SimpleNamespace(get_steer_feedforward_function=lambda: (lambda angle, v_ego: angle))

DT = 0.01

# Real transitions, read out of the rlogs of two drives on 2026-09-01. Each row is
# (route, t_last_active, i_at_last_active, t_reengage, p_at_reengage).
# The integral logged on the first re-engaged frame equalled i_at_last_active to five decimals
# in both cases; drive 1's is the interesting one, because the carried-over integral is NEGATIVE
# while the proportional term on that first frame is strongly POSITIVE.
REENGAGEMENTS = [
  ("98a5b56c6d", 475.437, +0.19115, 475.638, -1.14554),
  ("5900224619", 147.988, -0.13616, 148.347, +0.44807),
]

# drive 3 98a5b56c6d: lateral went inactive at t=206.090 and did not come back until t=263.890.
LONGEST_LOGGED_INACTIVE_GAP_S = 57.811


class _CS:
  steeringAngleDeg = 0.0
  steeringRateDeg = 0.0
  vEgo = 20.0
  steeringPressed = False
  steeringTorque = 0.0
  leftBlinker = False
  rightBlinker = False


class _VM:
  sR = 15.38

  def get_steer_from_curvature(self, curv, v_ego, roll):
    return math.radians(curv * 1000.0 * self.sR)


_PARAMS = SimpleNamespace(roll=0.0, angleOffsetDeg=0.0)


@pytest.fixture
def lat():
  car_fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=MODIFIED_FW, address=0x18DA30F1, subAddress=0)]
  CP = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, {0: {}, 1: {}, 2: {}}, car_fw, False, False, False, TOGGLES)
  return LatControlPID(CP, STUB_CI, DT)


def _inactive_update(controller):
  """One frame through update() with lateral inactive, the way controlsd would call it."""
  return controller.update(False, _CS(), _VM(), _PARAMS, False, 0.0, False, 0.0, None, None, TOGGLES)


@pytest.mark.parametrize("route, t_last, i_last, t_reengage, p_reengage", REENGAGEMENTS)
def test_reset_clears_a_logged_integral(lat, route, t_last, i_last, t_reengage, p_reengage):
  """The controlsd path. This is the one that was broken: controlsd calls reset(), not update()."""
  lat.pid.i = i_last
  lat.reset()
  assert lat.pid.i == 0.0, (
    f"{route}: integral {i_last:+.5f} logged at t={t_last:.3f} survived reset() and would be "
    f"re-injected at t={t_reengage:.3f}, where the proportional term was {p_reengage:+.5f}"
  )


@pytest.mark.parametrize("route, t_last, i_last, t_reengage, p_reengage", REENGAGEMENTS)
def test_inactive_update_clears_a_logged_integral(lat, route, t_last, i_last, t_reengage, p_reengage):
  """The update() path, so the two inactive paths cannot drift apart."""
  lat.pid.i = i_last
  _inactive_update(lat)
  assert lat.pid.i == 0.0, f"{route}: integral {i_last:+.5f} survived an inactive update() frame"


def test_integral_cannot_survive_a_long_inactive_gap(lat):
  """Drive 3's 57.8 s gap, run frame by frame through the path controlsd actually takes."""
  lat.pid.i = -0.01897
  for _ in range(int(LONGEST_LOGGED_INACTIVE_GAP_S / DT)):
    _inactive_update(lat)
    lat.reset()
  assert lat.pid.i == 0.0


def test_reset_clears_the_whole_pid_controller(lat):
  """p, d and f are recomputed at the top of PIDController.update() before anything reads them,
  so clearing them cannot change the first active frame -- but leaving them set would make
  pid_log and self.pid.control report last engagement's numbers while lateral is off."""
  lat.pid.p, lat.pid.i, lat.pid.d, lat.pid.f, lat.pid.control = 0.1, 0.2, 0.3, 0.4, 0.5
  lat.reset()
  assert (lat.pid.p, lat.pid.i, lat.pid.d, lat.pid.f, lat.pid.control) == (0.0, 0.0, 0.0, 0.0, 0)


def test_reset_still_clears_the_saturation_timer(lat):
  """The override must not lose what the base class did."""
  lat.sat_time = 1.5
  lat.reset()
  assert lat.sat_time == 0.0


def test_reset_clears_the_rest_of_the_inactive_state(lat):
  """Everything the inactive branch used to clear inline now has to come out of reset(), or
  moving it there would have been a regression."""
  lat.eps_modified_steering_pressed_filter_s = 0.4
  lat.eps_modified_steering_pressed_prev = True
  lat.center_taper_scale.x = 0.25
  lat.unwind_boost_elapsed = 0.7
  lat.prev_output_torque = 0.3
  lat.prev_saturated = True
  lat._stiction_delta = 0.05
  lat.reset()
  assert lat.eps_modified_steering_pressed_filter_s == 0.0
  assert lat.eps_modified_steering_pressed_prev is False
  assert lat.center_taper_scale.x == 1.0
  assert lat.unwind_boost_elapsed == 0.0
  assert lat.prev_output_torque == 0.0
  assert lat.prev_saturated is False
  assert lat._stiction_delta == 0.0


def test_active_frames_are_untouched(lat):
  """The normal path must not be affected: an active frame never calls reset(), and the
  integral it builds has to persist from one active frame to the next."""
  torque, _, pid_log = lat.update(True, _CS(), _VM(), _PARAMS, False, 5e-5, False, 0.0, None, None, TOGGLES)
  assert pid_log.active
  first_i = lat.pid.i
  assert first_i != 0.0, "an active frame with a standing error must integrate"
  lat.update(True, _CS(), _VM(), _PARAMS, False, 5e-5, False, 0.0, None, None, TOGGLES)
  assert lat.pid.i != first_i, "the integral must keep accumulating across active frames"
  assert torque != 0.0
