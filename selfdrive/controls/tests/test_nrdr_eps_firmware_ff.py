import math
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import car, custom, log
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as clarity_eps
import openpilot.selfdrive.controls.lib.latcontrol_pid as latcontrol_pid
import openpilot.selfdrive.controls.lib.nrdr_eps_firmware_ff as eps_ff
from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.values import CAR as HONDA, HondaFlags
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID, _lat_pid_scale_banded

# Ported from JamesL787/openpilot vfn-controller-shadow: the firmware-model tests are upstream's (fd815ef3), the
# shadow tests are 52618f42's with the final field names, the core and controller tests fd815ef3's; the C020 tests
# and the Civic variants are this branch's (STATUS 163-166).
C020 = eps_ff.CIVIC_BOSCH_C020
CRV_A040 = eps_ff.CRV_5G_A040_FF45


# --- firmware model and feedforward (upstream, Clarity calibration) ------------------------------

@pytest.mark.parametrize("output", [-1.0, -0.4, -0.05, 0.0, 0.02, 0.3, 0.9])
def test_command_map_round_trips(output):
  r5 = eps_ff.r5_from_output(output, 20.0)
  assert eps_ff.output_from_r5(r5) == pytest.approx(output, abs=2e-3)


def test_command_map_matches_the_measured_gain():
  # route 00000352: R5 = 7.7 * E4 and E4 = -3840 * output
  assert eps_ff.r5_from_output(0.1, 20.0) == pytest.approx(-0.1 * 3840 * 7.7, rel=0.03)


@pytest.mark.parametrize("load,rate", [(500, 0), (-1500, 0), (800, 40), (-800, -40), (300, -60), (-4000, 120),
                                       (100, -216), (-6000, 0), (0, 0)])
@pytest.mark.parametrize("guess", [0.0, 15000.0, -15000.0])
def test_inversion_reproduces_the_requested_load(load, rate, guess):
  r5 = eps_ff.r5_for_motion(load, rate, guess)
  assert eps_ff.firmware_output(r5, rate) == pytest.approx(load, abs=1e-6)


def test_turn_in_asks_more_than_a_hold_and_an_exit_less():
  # left turn (positive angle and output) at 60 deg, 8 m/s
  def out(rate):
    return eps_ff.output_from_r5(eps_ff.r5_for_motion(eps_ff.column_load(60.0, rate, 8.0, 0.0), rate))
  turn_in, hold, unwind = out(40.0), out(0.0), out(-40.0)
  assert turn_in > hold > unwind
  assert hold > 0.0


@pytest.mark.parametrize("v_kph,cap", [(40.0, eps_ff.R5_CAP), (130.0, 0.9 * 24000)])
def test_target_stays_clear_of_the_rail_and_the_speed_ceiling(v_kph, cap):
  ff = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL)
  for k in range(200):
    ff.update(400.0 + k, v_kph / 3.6, 0.0)
  assert abs(ff.r5) <= cap + 1e-6


def test_desired_rate_tracks_a_ramp_and_resets():
  ff = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL)
  for k in range(150):
    ff.update(50.0 * k * DT_CTRL, 10.0, 0.0)
  assert ff.rate == pytest.approx(50.0, abs=1.0)
  ff.reset()
  assert ff.rate == 0.0 and ff.output == 0.0 and ff.prev_angle is None


def test_feedforward_output_is_smoothed():
  raw = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, output_tau=0.0)
  smooth = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL)
  for ff in (raw, smooth):
    ff.update(0.0, 10.0, 0.0)
    ff.update(30.0, 10.0, 0.0)   # a step in the target
  assert abs(smooth.output) < 0.2 * abs(raw.output)


# --- Civic Bosch C020 calibration ----------------------------------------------------------------

# E4 4096 is key 1773, past the 1663 clamp: on the Civic |output| above 0.938 all lands on the same R5
@pytest.mark.parametrize("output", [-0.93, -0.4, -0.05, 0.0, 0.02, 0.3, 0.93])
def test_c020_command_map_round_trips(output):
  r5 = eps_ff.r5_from_output(output, 20.0, C020)
  assert eps_ff.output_from_r5(r5, C020) == pytest.approx(output, abs=2e-3)


def test_c020_command_map_matches_the_telemetry():
  # route 00000284 telemetry: E4 = -4096 * output, the 1663 key clamp gives the largest R5 seen (28497)
  assert eps_ff.r5_from_output(-1.0, 20.0, C020) == pytest.approx(28497, abs=15)
  assert eps_ff.r5_from_output(-0.94, 20.0, C020) == eps_ff.r5_from_output(-1.0, 20.0, C020)
  # row 1: key 115 -> 1926, E4 = 115 * 4 * 32768 / 56756 = 265.6 -> key 115
  assert eps_ff.r5_from_output(-266 / 4096, 20.0, C020) == pytest.approx(1926, abs=20)


@pytest.mark.parametrize("r5", [0.0, 500.0, 1926.0, 3000.0, 8455.0, 15000.0, 22000.0, 28497.0, 31000.0])
def test_c020_kp_follows_the_p_row_through_the_command_map(r5):
  key = float(eps_ff.np.interp(min(r5, 30000.0), C020.r5_v, C020.r5_key_bp))
  assert eps_ff.firmware_kp(r5, C020) == pytest.approx(float(eps_ff.np.interp(key, eps_ff.KP_KEY_BP, eps_ff.KP_V)), abs=1e-9)
  assert eps_ff.firmware_kp(-r5, C020) == eps_ff.firmware_kp(r5, C020)


def test_clarity_kp_is_upstreams():
  for r5 in (0.0, 1000.0, 7000.0, 19000.0, 29000.0, 40000.0):
    assert eps_ff.firmware_kp(r5) == pytest.approx(float(eps_ff.np.interp(r5 / eps_ff.R5_PER_KEY, eps_ff.KP_KEY_BP, eps_ff.KP_V)))


@pytest.mark.parametrize("load,rate", [(500, 0), (-1500, 0), (800, 40), (-800, -40), (300, -60), (-4000, 120),
                                       (100, -216), (-6000, 0), (0, 0)])
@pytest.mark.parametrize("guess", [0.0, 15000.0, -15000.0])
def test_c020_inversion_reproduces_the_requested_load(load, rate, guess):
  r5 = eps_ff.r5_for_motion(load, rate, guess, C020)
  assert eps_ff.firmware_output(r5, rate, C020) == pytest.approx(load, abs=1e-6)


def test_c020_rate_damping_is_the_c020s():
  # same R5, same rate: the C020's larger R6 scale means more damping to cancel on a turn-in
  assert eps_ff.firmware_output(5000.0, 0.0, C020) < eps_ff.firmware_output(5000.0, 30.0, C020)
  d_c020 = eps_ff.firmware_output(5000.0, 30.0, C020) - eps_ff.firmware_output(5000.0, 0.0, C020)
  d_clarity = eps_ff.firmware_output(5000.0, 30.0) - eps_ff.firmware_output(5000.0, 0.0)
  assert d_c020 / d_clarity == pytest.approx(173.0 / 138.6, rel=0.05)


def test_c020_target_stays_clear_of_the_rail():
  ff = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, cal=C020)
  for k in range(200):
    ff.update(400.0 + k, 40.0 / 3.6, 0.0)
  assert abs(ff.r5) <= eps_ff.R5_CAP + 1e-6
  assert abs(ff.output) <= 1.0


# --- CR-V 5G A040 FF45 calibration ---------------------------------------------------------------

def test_crv_a040_ff45_exact_firmware_constants():
  assert CRV_A040.e4_per_output == 4096.0
  assert CRV_A040.r5_key_bp == [0, 219, 443, 662, 887, 1108, 1330, 1552, 1663]
  assert CRV_A040.r5_v == [0, 1926, 4938, 8455, 12036, 15926, 20138, 26955, 30000]
  assert CRV_A040.key_clamp == 1774 and CRV_A040.scale_q8 == 256.0 and CRV_A040.kff == 45.0
  # least squares on route 82bb (norm 1450), scaled to the FF45 image's norm 1650 (STATUS 227 / D-093)
  assert CRV_A040.r6_per_deg_s == pytest.approx(-121.6051 * 1650.0 / 1450.0, rel=1e-6)
  assert CRV_A040.r6_per_deg_s == pytest.approx(-138.378, abs=0.01)


def test_crv_load_is_in_the_controllers_units():
  # D-093: fitted in m/s with the offset-corrected angle and roll. The D-091 set was fitted on the compact
  # drive's mph speed, which made k1 5.0x too weak; this pins the m/s fit and keeps roll in the model.
  k0, k1, c, friction, bias, kroll = eps_ff.CRV_5G_EPS_LOAD
  assert (k0, k1, c, friction, bias, kroll) == pytest.approx((-7.29446, -0.143159, -4.60337, -297.83, -19.899, -3.58048))
  assert -0.25 < k1 < -0.10       # Clarity -0.219, TEG -0.325 per m/s^2; the mph fit gave -0.0226
  assert kroll < 0.0              # roll is fitted, not left at zero
  # at 30 m/s and 5 deg the speed term carries more than the angle term, as on the Clarity
  assert abs(k1 * 5.0 * 30.0 ** 2) > abs(k0 * 5.0)


@pytest.mark.parametrize("output", [-0.93, -0.4, -0.05, 0.0, 0.02, 0.3, 0.93])
def test_crv_a040_command_map_round_trips(output):
  r5 = eps_ff.r5_from_output(output, 20.0, CRV_A040)
  assert eps_ff.output_from_r5(r5, CRV_A040) == pytest.approx(output, abs=2e-3)


@pytest.mark.parametrize("load,rate", [(500, 0), (-1500, 0), (800, 40), (-800, -40), (0, 0)])
def test_crv_a040_inversion_reproduces_the_requested_load(load, rate):
  r5 = eps_ff.r5_for_motion(load, rate, cal=CRV_A040)
  assert eps_ff.firmware_output(r5, rate, CRV_A040) == pytest.approx(load, abs=1e-6)


# --- shadow in LatControlPID (upstream 52618f42) ------------------------------------------------

class _Params:
  def get(self, key, *args, **kwargs):
    return None

  def get_bool(self, key, *args, **kwargs):
    raise KeyError(key)   # -> the controller's own default


def _car(monkeypatch, candidate=HONDA.HONDA_CLARITY, modified=True):
  monkeypatch.setattr(latcontrol_pid, "Params", lambda: _Params())
  CarInterface = interfaces[candidate]
  CP = CarInterface.get_non_essential_params(candidate)
  if modified:
    CP.flags |= int(HondaFlags.EPS_MODIFIED)
  CP.dashcamOnly = True
  CI = CarInterface(CP, custom.StarPilotCarParams.new_message())
  lac = LatControlPID(CP.as_reader(), CI, DT_CTRL)
  params = log.LiveParametersData.new_message()
  params.steerRatio = CP.steerRatio
  params.stiffnessFactor = 1.0
  params.angleOffsetDeg = 0.0
  return lac, VehicleModel(CP), params


def _drive(lac, VM, params, frames=400):
  CS = car.CarState.new_message()
  CS.vEgo = 9.0
  outputs = []
  for k in range(frames):
    active = k >= 20
    curvature = 0.02 * math.sin(k * 0.02)
    CS.steeringAngleDeg = 10.0 * math.sin(k * 0.02 - 0.3)
    out, _, _ = lac.update(active, CS, VM, params, False, curvature, False, 0.2, None, None, SimpleNamespace())
    outputs.append(out)
  return outputs


SHADOW_CARS = [(HONDA.HONDA_CLARITY, eps_ff.CLARITY_A020), (HONDA.HONDA_CIVIC_BOSCH, C020),
               (HONDA.HONDA_CRV_5G, CRV_A040)]


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_shadow_is_logged(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate)
  assert lac.eps_shadow_ff is not None and lac.eps_shadow_ff.cal is cal
  _drive(lac, VM, params)
  state = lac.starpilot_lateral_state
  assert state.epsFfActive and state.epsFfWeight == 0.0
  assert state.epsFfR5 != 0.0 and math.isfinite(state.epsFfFeedforward)
  msg = log.Event.new_message(starpilotLateralState=state)   # what controlsd publishes
  assert msg.starpilotLateralState.epsFfR5 == pytest.approx(state.epsFfR5)


@pytest.mark.parametrize("candidate,load", [(HONDA.HONDA_CLARITY, None), (HONDA.HONDA_CIVIC_BOSCH, eps_ff.CIVIC_PID_LOAD),
                                             (HONDA.HONDA_CRV_5G, eps_ff.CRV_5G_EPS_LOAD)])
def test_pid_feedforward_uses_the_cars_own_load_fit(monkeypatch, candidate, load):
  lac, _, _ = _car(monkeypatch, candidate)
  assert lac.eps_shadow_ff.load_coef == load


def test_clarity_eps_controller_runs_the_c020_on_its_own_eps_load(monkeypatch):
  # the PID-shadow fit (CIVIC_PID_LOAD, from 25 mph) stays out; the firmware-output fit applies at every speed
  lac, _, _ = _controller(monkeypatch, HONDA.HONDA_CIVIC_BOSCH, {"NrdrLatEpsFirmwareFF": "1"})
  assert lac.core.ff.cal is C020 and lac.core.ff.load_coef is eps_ff.CIVIC_EPS_LOAD and lac.core.ff.load_min_v == 0.0
  lac, _, _ = _controller(monkeypatch, HONDA.HONDA_CLARITY, {"NrdrLatEpsFirmwareFF": "1"})
  assert lac.core.ff.load_coef is None


def test_load_fit_defaults_to_the_clarity_constants():
  args = (30.0, 5.0, 15.0, 0.04)
  assert eps_ff.column_load(*args) == eps_ff.column_load(*args, load=eps_ff.CLARITY_LOAD)
  # the Civic fit asks less load in a sharp 25-50 mph corner (28f: the Clarity fit ~1.5x what the car used)
  assert abs(eps_ff.column_load(*args, load=eps_ff.CIVIC_PID_LOAD)) < abs(eps_ff.column_load(*args))


@pytest.mark.parametrize("v", [8.0, 15.0])
def test_civic_load_fit_applies_from_25_mph(v):
  civic = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, cal=C020, load=eps_ff.CIVIC_PID_LOAD,
                                               load_min_v=eps_ff.CIVIC_PID_LOAD_MIN_V)
  clarity = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, cal=C020)
  civic.update(30.0, v, 0.04)
  clarity.update(30.0, v, 0.04)
  assert (civic.load == clarity.load) == (v < eps_ff.CIVIC_PID_LOAD_MIN_V)
  if v > eps_ff.CIVIC_PID_LOAD_MIN_V + eps_ff.LOAD_BLEND_V:
    assert civic.load == pytest.approx(eps_ff.column_load(30.0, 0.0, v, 0.04, load=eps_ff.CIVIC_PID_LOAD))


def test_civic_load_fit_blends_in_without_a_step():
  # crossing 25 mph mid-corner must not step the column load (a hard switch steps it by ~100 at 40 deg;
  # the load's own speed term moves it ~2 per 0.01 m/s)
  loads = []
  for v in np.arange(10.5, 14.0, 0.01):
    ff = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, cal=C020, load=eps_ff.CIVIC_PID_LOAD,
                                              load_min_v=eps_ff.CIVIC_PID_LOAD_MIN_V)
    ff.update(40.0, float(v), 0.0)
    loads.append(ff.load)
  assert np.max(np.abs(np.diff(loads))) < 5.0


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH, HONDA.HONDA_CRV_5G])
def test_no_shadow_on_a_stock_eps(monkeypatch, candidate):
  lac, _, _ = _car(monkeypatch, candidate, modified=False)
  assert lac.eps_shadow_ff is None and not hasattr(lac, "starpilot_lateral_state")


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_shadow_never_changes_the_steering_command(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate)
  twin, _, _ = _car(monkeypatch, candidate)
  twin.eps_shadow_ff = None
  assert _drive(lac, VM, params) == _drive(twin, VM, params)


@pytest.mark.parametrize("candidate,cal", SHADOW_CARS)
def test_a_shadow_failure_cannot_reach_the_command(monkeypatch, candidate, cal):
  lac, VM, params = _car(monkeypatch, candidate)
  twin, _, _ = _car(monkeypatch, candidate)
  twin.eps_shadow_ff = None

  def boom(*args, **kwargs):
    raise ValueError("shadow failure")
  monkeypatch.setattr(lac.eps_shadow_ff, "update", boom)
  assert _drive(lac, VM, params) == _drive(twin, VM, params)
  assert not lac.starpilot_lateral_state.epsFfActive


# --- control core (upstream fd815ef3) -------------------------------------------------------------------

KP_BP, KP_V, KI_V = [0.0, 11.175, 11.176, 22.352], [0.018, 0.024, 0.048, 0.060], [0.006, 0.008, 0.016, 0.020]


def _core():
  return eps_ff.HondaEpsLateralCore(KP_BP, KP_V, KP_BP, KI_V, DT_CTRL)


def _hold(core, frames, des=40.0, angle=40.0, v=10.0, pressed=False):
  for _ in range(frames):
    core.update(des, 0.0, angle, v, 0.0, pressed, False)


def test_feedforward_waits_for_the_wheel_to_join_the_path():
  core = _core()
  _hold(core, 100, des=60.0, angle=20.0)   # engaged 40 deg off the path
  assert core.ff_weight == 0.0
  _hold(core, 25, des=60.0, angle=58.0)    # on the path: fades in over FF_FADE_IN_S
  assert 0.0 < core.ff_weight < 1.0
  _hold(core, 40, des=60.0, angle=58.0)
  assert core.ff_weight == 1.0
  _hold(core, 10, des=60.0, angle=20.0)    # once in, a later error does not throw it out
  assert core.ff_weight == 1.0


def test_driver_press_and_standstill_take_the_feedforward_out():
  core = _core()
  _hold(core, 80)
  assert core.ff_weight == 1.0
  _hold(core, 1, pressed=True)
  assert core.ff_weight == 0.0
  _hold(core, 80)
  _hold(core, 1, v=1.0)
  assert core.ff_weight == 0.0
  _hold(core, 80, v=3.0)
  assert core.ff_weight == pytest.approx(0.5)   # faded in with speed between 2 and 4 m/s


@pytest.mark.parametrize("v, des, weight", [
  (3.0, 2.0, 0.0),     # crawling near straight: the model's wiggles do not reach the wheel through the feedforward
  (3.0, -12.5, 0.25),  # joins with |desired angle| between 5 and 20 deg (0.5 from the 2-4 m/s speed fade)
  (4.5, 12.5, 0.5),
  (4.5, -30.0, 1.0),   # every real crawl turn gets all of it
  (6.5, 2.0, 0.5),     # the crawl gate fades out of effect between 5 and 8 m/s
  (8.0, 0.0, 1.0),
  (20.0, 0.5, 1.0),    # at speed it never applies, so the highway keeps the feedforward
])
def test_crawl_gate_holds_the_feedforward_off_near_straight(v, des, weight):
  core = _core()
  _hold(core, 80, des=des, angle=des, v=v)
  assert core.ff_weight == pytest.approx(weight)


def test_crawl_gate_does_not_reset_the_join_ramp():
  core = _core()
  _hold(core, 80, des=40.0, angle=40.0, v=4.5)
  _hold(core, 1, des=1.0, angle=1.0, v=4.5)
  assert core.ff_weight == 0.0
  _hold(core, 1, des=-40.0, angle=-40.0, v=4.5)
  assert core.ff_weight == 1.0


def test_friction_knee_is_wide_in_the_city_and_sharp_at_speed():
  assert eps_ff.friction_width(0.0) == eps_ff.friction_width(8.0) == 20.0
  assert eps_ff.friction_width(15.0) == eps_ff.friction_width(30.0) == eps_ff.FRICTION_WIDTH_DEG_S == 5.0
  # a slow desired rate asks for less friction in the city than at speed; a turn-in rate gets it all either way
  city = eps_ff.column_load(0.0, 5.0, 8.0, 0.0, eps_ff.friction_width(8.0)) - eps_ff.column_load(0.0, 5.0, 8.0, 0.0, 1e9)
  fast = eps_ff.column_load(0.0, 5.0, 8.0, 0.0, eps_ff.friction_width(20.0)) - eps_ff.column_load(0.0, 5.0, 8.0, 0.0, 1e9)
  assert abs(city) < 0.4 * abs(fast)
  turn = [eps_ff.column_load(0.0, 100.0, 8.0, 0.0, w) - eps_ff.column_load(0.0, 100.0, 8.0, 0.0, 1e9) for w in (20.0, 5.0)]
  assert turn[0] == pytest.approx(turn[1], rel=0.01)


def test_c020_eps_load_is_its_own_at_every_speed():
  assert eps_ff.CIVIC_EPS_LOAD == pytest.approx(tuple(c * eps_ff.SCALE_Q8 / 256.0 for c in eps_ff.CIVIC_EPS_LOAD_PRESCALE))
  for v in (3.0, 10.0, 25.0):
    ff = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, cal=eps_ff.CIVIC_BOSCH_C020, load=eps_ff.CIVIC_EPS_LOAD)
    ff.update(30.0, v, 0.02)
    assert ff.load == pytest.approx(eps_ff.column_load(30.0, 0.0, v, 0.02, eps_ff.friction_width(v), eps_ff.CIVIC_EPS_LOAD))


def test_without_the_feedforward_the_core_is_the_banded_pid():
  core = _core()
  eps_ff.FF_JOIN_ERROR_DEG, saved = -1.0, eps_ff.FF_JOIN_ERROR_DEG
  try:
    out = core.update(10.0, 0.0, 5.0, 15.0, 0.0, False, False)
  finally:
    eps_ff.FF_JOIN_ERROR_DEG = saved
  p = float(np.interp(15.0, KP_BP, KP_V)) * 5.0 * 1.00    # 15 m/s is the standard band: LatPScale 100
  i = float(np.interp(15.0, KP_BP, KI_V)) * 0.95 * DT_CTRL * 5.0
  assert out == pytest.approx((p + i) * DT_CTRL / (0.05 + DT_CTRL))


MPH = 0.44704
SPEEDS = [0.0, 3.0, 25 * MPH - 1e-6, 25 * MPH, 25 * MPH + 1e-6, 15.0, 50 * MPH - 1e-6, 50 * MPH, 50 * MPH + 1e-6, 30.0]


@pytest.mark.parametrize("v", SPEEDS)
def test_output_lpf_bands_switch_exactly_where_latcontrol_pids_do(v):
  taus = (0.07, 0.05, 0.01)
  assert eps_ff.speed_band(v, taus) == _lat_pid_scale_banded(v, *taus)


def test_output_lpf_is_latcontrol_pids_filter():
  # The car controller does not filter (see carcontroller.py), so this LPF must be exactly the one
  # LatControlPID runs: FirstOrderFilter from 0, update_alpha with the banded tau every frame, then clip.
  taus = (0.07, 0.05, 0.01)
  filtered, raw = _core(), _core()
  filtered.output_lpf_tau = raw.output_lpf_tau = taus
  raw.output_lpf_enabled = False
  reference = FirstOrderFilter(0.0, 0.1, DT_CTRL)
  speeds = np.concatenate([np.linspace(3.0, 30.0, 300), np.linspace(30.0, 3.0, 300)])
  for k, v in enumerate(speeds):
    args = (40.0 * math.sin(k * 0.05), 0.5, 38.0 * math.sin(k * 0.05 - 0.1), float(v), 0.0, False, False)
    out = filtered.update(*args)
    u = raw.update(*args)
    reference.update_alpha(_lat_pid_scale_banded(float(v), *taus))
    assert out == max(min(reference.update(u), 1.0), -1.0)
  filtered.reset()
  assert filtered.output_lpf.x == 0.0 and filtered.output == 0.0


def test_output_lpf_setting_is_honoured():
  core = _core()
  core.output_lpf_enabled = False
  out = core.update(10.0, 0.0, 5.0, 15.0, 0.0, False, False)
  assert out == pytest.approx(core.pid.p + core.pid.i + core.pid.f)


def test_civic_core_is_the_banded_pid_on_the_civic_trims():
  core = eps_ff.HondaEpsLateralCore(KP_BP, KP_V, KP_BP, KI_V, DT_CTRL, ff=eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, cal=C020),
                                      p_scale=eps_ff.CIVIC_P_SCALE, i_scale=eps_ff.CIVIC_I_SCALE)
  eps_ff.FF_JOIN_ERROR_DEG, saved = -1.0, eps_ff.FF_JOIN_ERROR_DEG
  try:
    out = core.update(10.0, 0.0, 5.0, 15.0, 0.0, False, False)
  finally:
    eps_ff.FF_JOIN_ERROR_DEG = saved
  p = float(np.interp(15.0, KP_BP, KP_V)) * 5.0 * 1.25    # standard band: the owner's LatPScaleStandard 125 on 284
  i = float(np.interp(15.0, KP_BP, KI_V)) * 0.95 * DT_CTRL * 5.0
  assert out == pytest.approx((p + i) * DT_CTRL / (0.05 + DT_CTRL))
  assert eps_ff.speed_band(30.0, eps_ff.CIVIC_I_SCALE) == 1.00   # highway I is not reset on the Civic


# --- controller shell (upstream fd815ef3, both cars) -----------------------------------------------------

class _ValueParams:
  def __init__(self, values=None):
    self.values = values or {}

  def get(self, key, *args, **kwargs):
    return self.values.get(key)

  def get_bool(self, key, *args, **kwargs):
    return self.values.get(key) == "1"


def _cp(candidate, modified=True):
  CarInterface = interfaces[candidate]
  CP = CarInterface.get_non_essential_params(candidate)
  if modified:
    CP.flags |= int(HondaFlags.EPS_MODIFIED)
  return CP


def _controller(monkeypatch, candidate, values=None):
  monkeypatch.setattr(clarity_eps, "Params", lambda: _ValueParams(values))
  CP = _cp(candidate)
  return clarity_eps.LatControlHondaEps(CP.as_reader(), None, DT_CTRL), VehicleModel(CP), CP


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH, HONDA.HONDA_CRV_5G])
def test_the_toggle_selects_this_controller_on_a_modified_eps(candidate):
  on, off = _ValueParams({"NrdrLatEpsFirmwareFF": "1"}), _ValueParams()
  assert clarity_eps.use_honda_eps_controller(_cp(candidate), on)
  assert not clarity_eps.use_honda_eps_controller(_cp(candidate), off)
  assert not clarity_eps.use_honda_eps_controller(_cp(candidate, modified=False), on)


@pytest.mark.parametrize("v, delay", [(0.0, 0.12), (3.5, 0.12), (7.0, 0.12), (12.0, 0.15), (20.0, 0.20), (30.0, 0.30), (40.0, 0.30)])
def test_the_clarity_tells_the_model_its_speed_scheduled_delay(v, delay):
  schedule = clarity_eps.eps_lateral_delay_schedule(_cp(HONDA.HONDA_CLARITY), _ValueParams({"NrdrLatEpsFirmwareFF": "1"}))
  assert clarity_eps.eps_lateral_delay(schedule, v, 0.5) == pytest.approx(delay)


def test_cars_without_a_measured_schedule_keep_live_delay():
  on, off = _ValueParams({"NrdrLatEpsFirmwareFF": "1"}), _ValueParams()
  assert clarity_eps.eps_lateral_delay_schedule(_cp(HONDA.HONDA_CIVIC_BOSCH), on) is None      # not measured yet
  assert clarity_eps.eps_lateral_delay_schedule(_cp(HONDA.HONDA_CRV_5G), on) is None            # measured late; no added delay
  assert clarity_eps.eps_lateral_delay_schedule(_cp(HONDA.HONDA_CLARITY), off) is None         # controller off
  assert clarity_eps.eps_lateral_delay_schedule(_cp(HONDA.HONDA_CLARITY, modified=False), on) is None
  assert clarity_eps.eps_lateral_delay(None, 12.0, 0.27) == 0.27


def test_other_modified_eps_hondas_keep_latcontrol_pid():
  assert not clarity_eps.use_honda_eps_controller(_cp(HONDA.HONDA_CIVIC), _ValueParams({"NrdrLatEpsFirmwareFF": "1"}))


def test_the_civic_runs_its_own_calibration_and_trims(monkeypatch):
  lac, _, _ = _controller(monkeypatch, HONDA.HONDA_CIVIC_BOSCH)
  assert lac.core.ff.cal is C020
  assert lac.core.p_scale == eps_ff.CIVIC_P_SCALE and lac.core.i_scale == eps_ff.CIVIC_I_SCALE
  clarity, _, _ = _controller(monkeypatch, HONDA.HONDA_CLARITY)
  assert clarity.core.ff.cal is eps_ff.CLARITY_A020
  assert clarity.core.p_scale == eps_ff.P_SCALE and clarity.core.i_scale == eps_ff.I_SCALE


def test_the_crv_runs_its_own_calibration_load_and_neutral_trims(monkeypatch):
  crv, _, _ = _controller(monkeypatch, HONDA.HONDA_CRV_5G)
  assert crv.core.ff.cal is CRV_A040 and crv.core.ff.load_coef is eps_ff.CRV_5G_EPS_LOAD
  assert crv.core.p_scale == (1.0, 1.0, 1.0) and crv.core.i_scale == (1.0, 1.0, 1.0)
  assert crv.cmd_delay_schedule == ([0.0], [0.0])


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH, HONDA.HONDA_CRV_5G])
def test_nrdr_settings_are_read(monkeypatch, candidate):
  lac, _, _ = _controller(monkeypatch, candidate, {"NrdrLatUseFirmwareVgr": "1", "NrdrLatAngleRateLimit": "219"})
  assert lac.use_firmware_vgr
  assert lac.angle_rate_limit_deg_s == 219.0
  assert lac.core.output_lpf_enabled and lac.core.output_lpf_tau == eps_ff.OUTPUT_LPF_TAU


def test_command_delay_hands_over_the_value_issued_that_long_ago():
  d = clarity_eps.CommandDelay(DT_CTRL, 0.2)
  outs = [d.update(float(k), 0.12) for k in range(40)]
  assert outs[30] == pytest.approx(18.0)
  assert outs[0] == 0.0 and outs[5] == 0.0              # not enough history yet: the oldest value
  half = clarity_eps.CommandDelay(DT_CTRL, 0.2)
  assert [half.update(float(k), 0.125) for k in range(40)][30] == pytest.approx(17.5)
  assert clarity_eps.CommandDelay(DT_CTRL, 0.2).update(3.0, 0.0) == 3.0


TOWN_DELAY = {HONDA.HONDA_CLARITY: 0.12, HONDA.HONDA_CIVIC_BOSCH: 0.15}   # measured per car, see EPS_CMD_DELAY


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH])
def test_command_delay_is_for_town_speeds_only(candidate):
  bp, v = clarity_eps.EPS_CMD_DELAY[candidate]
  assert np.interp(8.0, bp, v) == pytest.approx(TOWN_DELAY[candidate]) and np.interp(15.0, bp, v) == 0.0 and np.interp(30.0, bp, v) == 0.0


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH])
@pytest.mark.parametrize("v, in_town", [(8.0, True), (20.0, False)])
def test_target_follows_the_curvature_one_command_delay_late(monkeypatch, candidate, v, in_town):
  late_frames = round(TOWN_DELAY[candidate] / DT_CTRL) if in_town else 0
  lac, VM, _ = _controller(monkeypatch, candidate, {"NrdrLatUseFirmwareVgr": "1"})
  CS = car.CarState.new_message()
  CS.vEgo = v
  params = log.LiveParametersData.new_message()
  params.steerRatio, params.stiffnessFactor = 16.0, 1.0
  targets = []
  for k in range(100):
    _, angle_des, _ = lac.update(True, CS, VM, params, False, 0.0 if k < 50 else 0.02, False, 0.2, None, None, SimpleNamespace())
    targets.append(angle_des)
  assert next(k for k, a in enumerate(targets) if abs(a) > 1e-6) == 50 + late_frames


def _drive_eps(lac, VM, frames=400, v=9.0):
  CS = car.CarState.new_message()
  CS.vEgo = v
  params = log.LiveParametersData.new_message()
  params.steerRatio, params.stiffnessFactor = 16.0, 1.0
  outs = []
  for k in range(frames):
    active = k >= 20
    CS.steeringAngleDeg = 30.0 * math.sin(k * 0.02 - 0.05)
    out, angle_des, pid_log = lac.update(active, CS, VM, params, False, 0.02 * math.sin(k * 0.02), False, 0.2,
                                         None, None, SimpleNamespace())
    outs.append((active, out, angle_des, pid_log))
  return outs


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH])
def test_controller_steers_logs_and_rests(monkeypatch, candidate):
  lac, VM, _ = _controller(monkeypatch, candidate, {"NrdrLatUseFirmwareVgr": "1"})
  outs = _drive_eps(lac, VM)
  assert all(out == 0.0 and not pid_log.active for active, out, _, pid_log in outs if not active)
  assert max(abs(out) for _, out, _, _ in outs) > 0.05
  assert all(abs(out) <= 1.0 and math.isfinite(out) for _, out, _, _ in outs)
  state = lac.starpilot_lateral_state
  assert state.epsFfActive and state.epsFfWeight == 1.0 and state.epsFfR5 != 0.0
  msg = log.Event.new_message(starpilotLateralState=state)   # what controlsd publishes
  assert msg.starpilotLateralState.epsFfWeight == 1.0
  lac.update(False, car.CarState.new_message(), VM, log.LiveParametersData.new_message(), False, 0.0, False, 0.2,
             None, None, SimpleNamespace())
  assert lac.core.ff_weight == 0.0 and lac.core.output == 0.0


@pytest.mark.parametrize("candidate", [HONDA.HONDA_CLARITY, HONDA.HONDA_CIVIC_BOSCH])
def test_target_honours_the_angle_rate_limit(monkeypatch, candidate):
  lac, VM, _ = _controller(monkeypatch, candidate, {"NrdrLatUseFirmwareVgr": "1", "NrdrLatAngleRateLimit": "100"})
  outs = _drive_eps(lac, VM, frames=120)
  steps = [abs(b[2] - a[2]) for a, b in zip(outs[20:], outs[21:], strict=False)]
  assert max(steps) <= 100.0 * DT_CTRL + 1e-6
