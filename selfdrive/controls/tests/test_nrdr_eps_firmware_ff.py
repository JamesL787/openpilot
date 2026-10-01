import math
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import car, log
import openpilot.selfdrive.controls.lib.clarity_rack_map as rack
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
import openpilot.selfdrive.controls.lib.nrdr_eps_firmware_ff as eps_ff
from opendbc.car import structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, vgr_linear_to_physical, vgr_physical_to_linear
from opendbc.car.honda.values import CAR, HondaFlags
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol_pid import _lat_pid_scale_banded

TOGGLES = SimpleNamespace(force_torque_controller=False, nnff=False, nnff_lite=False)
CLARITY_MODIFIED_FW = b'39990-TRW,A020\x00\x00'
CLARITY_STOCK_FW = b'39990-TRW-A020\x00\x00'
KP_BP, KP_V, KI_V = [0.0, 11.175, 11.176, 22.352], [0.018, 0.024, 0.048, 0.060], [0.006, 0.008, 0.016, 0.020]


# --- firmware model and feedforward -------------------------------------------------------------

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


@pytest.mark.parametrize("angle", [0.0, 45.0, 150.0, -300.0])
@pytest.mark.parametrize("load,rate", [(800, 40), (-4000, 120), (300, -60)])
def test_inversion_reproduces_the_requested_load_at_an_angle(load, rate, angle):
  r5 = eps_ff.r5_for_motion(load, rate, 0.0, angle)
  assert eps_ff.firmware_output(r5, rate, angle) == pytest.approx(load, abs=1e-6)


def test_firmware_damping_grows_with_angle_like_its_table():
  # R6 is taken before the firmware's angle table: per deg/s of the published rate it is -119 near centre
  # and -141..-146 past 60 deg on routes 363/365/366/369, flat per count of the pre-table 0x18F rate
  assert eps_ff.firmware_r6(10.0, 0.0) == pytest.approx(-1220.0, rel=0.01)
  assert eps_ff.firmware_r6(10.0, 5.0) == pytest.approx(-1220.0, rel=0.02)
  assert eps_ff.firmware_r6(10.0, 200.0) == pytest.approx(-1220.0 * 1.19, rel=0.02)
  assert eps_ff.firmware_r6(10.0, -200.0) == eps_ff.firmware_r6(10.0, 200.0)
  assert eps_ff.firmware_r6(-10.0, 200.0) == -eps_ff.firmware_r6(10.0, 200.0)


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


# --- control core ---------------------------------------------------------------------------------

def _core():
  return eps_ff.HondaEpsLateralCore(KP_BP, KP_V, KP_BP, KI_V, DT_CTRL)


def _hold(core, frames, des=20.0, angle=20.0, v=10.0, pressed=False):
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
  (20.0, 0.5, 1.0),    # at speed it never applies
])
def test_crawl_gate_holds_the_feedforward_off_near_straight(v, des, weight):
  core = _core()
  _hold(core, 80, des=des, angle=des, v=v)
  assert core.ff_weight == pytest.approx(weight)


def test_friction_knee_is_wide_in_the_city_and_sharp_at_speed():
  assert eps_ff.friction_width(0.0) == eps_ff.friction_width(8.0) == 20.0
  assert eps_ff.friction_width(15.0) == eps_ff.friction_width(30.0) == eps_ff.FRICTION_WIDTH_DEG_S == 5.0
  # a slow desired rate asks for less friction in the city than at speed; a turn-in rate gets it all either way
  city = eps_ff.column_load(0.0, 5.0, 8.0, 0.0, eps_ff.friction_width(8.0)) - eps_ff.column_load(0.0, 5.0, 8.0, 0.0, 1e9)
  fast = eps_ff.column_load(0.0, 5.0, 8.0, 0.0, eps_ff.friction_width(20.0)) - eps_ff.column_load(0.0, 5.0, 8.0, 0.0, 1e9)
  assert abs(city) < 0.4 * abs(fast)
  turn = [eps_ff.column_load(0.0, 100.0, 8.0, 0.0, w) - eps_ff.column_load(0.0, 100.0, 8.0, 0.0, 1e9) for w in (20.0, 5.0)]
  assert turn[0] == pytest.approx(turn[1], rel=0.01)


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


# --- controller shell -----------------------------------------------------------------------------

def _params(fw_version, candidate=CAR.HONDA_CLARITY):
  car_fw = [structs.CarParams.CarFw(ecu=structs.CarParams.Ecu.eps, fwVersion=fw_version, address=0x18DA30F1, subAddress=0)]
  return CarInterface.get_params(candidate, {0: {}, 1: {}, 2: {}}, car_fw, False, False, False, TOGGLES)


class _Params:
  def __init__(self, values=None):
    self.values = values or {}

  def get(self, key, *args, **kwargs):
    return self.values.get(key)

  def get_bool(self, key, *args, **kwargs):
    return self.values.get(key) == "1"


def _controller(monkeypatch, values=None):
  monkeypatch.setattr(honda_eps, "Params", lambda: _Params(values))
  CP = _params(CLARITY_MODIFIED_FW)
  return honda_eps.LatControlHondaEps(CP, None, DT_CTRL), VehicleModel(CP), CP


def test_only_the_modified_eps_clarity_gets_this_controller():
  assert honda_eps.use_honda_eps_controller(_params(CLARITY_MODIFIED_FW))
  assert not honda_eps.use_honda_eps_controller(_params(CLARITY_STOCK_FW))
  assert not honda_eps.use_honda_eps_controller(_params(b'39990-TBA,A030\x00\x00', CAR.HONDA_CIVIC_BOSCH))


@pytest.mark.parametrize("v, delay", [(0.0, 0.12), (3.5, 0.12), (7.0, 0.12), (12.0, 0.15), (20.0, 0.20), (30.0, 0.30), (40.0, 0.30)])
def test_lateral_delay_follows_the_measured_execution_delay(v, delay):
  assert honda_eps.clarity_lateral_delay(v) == pytest.approx(delay)


def test_lateral_delay_rises_with_speed():
  delays = [honda_eps.clarity_lateral_delay(v) for v in np.linspace(0.0, 40.0, 81)]
  assert all(b >= a for a, b in zip(delays, delays[1:], strict=False))


def test_nrdr_settings_are_read(monkeypatch):
  lac, _, _ = _controller(monkeypatch, {
    "NrdrLatUseFirmwareVgr": "1", "NrdrLatAngleRateLimit": "219", "HondaTorqueOutputLowPassFilter": "1",
    "HondaTorqueOutputLpfTauLowSpeed": "0.07", "HondaTorqueOutputLpfTauStandard": "0.05", "HondaTorqueOutputLpfTauHighway": "0.01",
  })
  assert lac.use_firmware_vgr and lac.vgr_inverse is not None
  assert lac.angle_rate_limit_deg_s == 219.0
  assert lac.core.output_lpf_enabled
  assert lac.core.output_lpf_tau == (0.07, 0.05, 0.01)


def _drive(lac, VM, frames=400, v=9.0):
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


def test_controller_steers_logs_and_rests(monkeypatch):
  lac, VM, _ = _controller(monkeypatch, {"NrdrLatUseFirmwareVgr": "1"})
  outs = _drive(lac, VM)
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


def test_target_honours_the_angle_rate_limit(monkeypatch):
  lac, VM, _ = _controller(monkeypatch, {"NrdrLatUseFirmwareVgr": "1", "NrdrLatAngleRateLimit": "100"})
  outs = _drive(lac, VM, frames=120)
  steps = [abs(b[2] - a[2]) for a, b in zip(outs[20:], outs[21:], strict=False)]
  assert max(steps) <= 100.0 * DT_CTRL + 1e-6


def _rack_map():
  rack_map = honda_eps.get_clarity_rack_map(_params(CLARITY_MODIFIED_FW))
  assert rack_map is not None
  return rack_map


def test_rack_map_is_only_built_for_the_identified_car():
  _rack_map()
  assert honda_eps.get_clarity_rack_map(_params(CLARITY_STOCK_FW)) is None


@pytest.mark.parametrize("v", [0.0, 7.0, 15.0, 30.0])
@pytest.mark.parametrize("roll", [0.0, 0.03, -0.03])
def test_rack_map_round_trips(v, roll):
  rack_map = _rack_map()
  for angle in (-430.0, -154.0, -40.0, -3.0, 0.0, 2.0, 25.0, 90.0, 300.0):
    curvature = rack_map.curvature_from_angle(angle, v, roll)
    assert rack_map.angle_from_curvature(curvature, v, roll) == pytest.approx(angle, abs=1e-3)


def test_rack_map_signs_follow_openpilot():
  rack_map = _rack_map()
  assert rack_map.angle_from_curvature(0.05, 7.0, 0.0) < 0.0   # right-positive curvature, left-positive wheel
  assert rack_map.curvature_from_angle(120.0, 7.0, 0.0) < 0.0
  curvatures = [rack_map.curvature_from_angle(a, 7.0, 0.0) for a in np.linspace(-430.0, 430.0, 861)]
  assert all(b < a for a, b in zip(curvatures, curvatures[1:], strict=False))


def test_rack_map_reproduces_the_identified_ratio():
  # measured at 154 deg / 7 m/s (the Sanitarium Rd right turn): R 16.4, slip -0.0005
  rack_map = _rack_map()
  angle, v = 154.0, 7.0
  lin = math.radians(vgr_physical_to_linear(angle, get_honda_vgr_inverse(HondaFlags.VGR_CLARITY_TRW_A020)))
  ratio = float(np.interp(angle, rack.CLARITY_RATIO_BP, rack.CLARITY_RATIO_V))
  expected = -lin / (ratio * 2.75 * (1.0 - rack.CLARITY_SLIP_FACTOR * v ** 2))
  assert rack_map.curvature_from_angle(angle, v, 0.0) == pytest.approx(expected, rel=1e-3)


def test_controller_steers_through_the_rack_map(monkeypatch):
  lac, VM, _ = _controller(monkeypatch, {"NrdrLatUseFirmwareVgr": "1"})
  VM.update_params(1.0, 17.3)   # a paramsd ratio must no longer change the target
  for curvature, v, roll in ((0.06, 7.0, 0.0), (-0.002, 30.0, 0.02), (0.0, 12.0, 0.0)):
    assert lac._desired_angle_no_offset(VM, v, roll, curvature) == pytest.approx(
      lac.rack_map.angle_from_curvature(curvature, v, roll))


def test_rack_map_asks_less_wheel_than_the_paramsd_ratio_in_tight_turns(monkeypatch):
  # the city over-steer: paramsd's single ratio over VGR asks 3.5-6% too much wheel at 100-250 deg
  lac, VM, _ = _controller(monkeypatch, {"NrdrLatUseFirmwareVgr": "1"})
  VM.update_params(1.0, 17.3)
  for curvature in (0.04, 0.06, 0.1):
    old = vgr_linear_to_physical(math.degrees(VM.get_steer_from_curvature(-curvature, 7.0, 0.0)), lac.vgr_inverse)
    new = lac.rack_map.angle_from_curvature(curvature, 7.0, 0.0)
    assert 0.93 < new / old < 0.97
