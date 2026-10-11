import math
from types import SimpleNamespace

import numpy as np
import pytest

from cereal import car, log
import openpilot.selfdrive.controls.lib.honda_eps_rack_map as rack
import openpilot.selfdrive.controls.lib.honda_eps_firmware_ff as eps_ff
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
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
CLA = eps_ff.CLARITY_TRW_A020  # the reference calibration these law tests were written on
KP_BP, KP_V, KI_V = [0.0, 11.175, 11.176, 22.352], [0.018, 0.024, 0.048, 0.060], [0.006, 0.008, 0.016, 0.020]


# --- firmware model and feedforward -------------------------------------------------------------

@pytest.mark.parametrize("output", [-1.0, -0.4, -0.05, 0.0, 0.02, 0.3, 0.9])
def test_command_map_round_trips(output):
  r5 = eps_ff.r5_from_output(output, 20.0, CLA)
  assert eps_ff.output_from_r5(r5, CLA) == pytest.approx(output, abs=2e-3)


def test_command_map_matches_the_measured_gain():
  # route 00000352: R5 = 7.7 * E4 and E4 = -3840 * output
  assert eps_ff.r5_from_output(0.1, 20.0, CLA) == pytest.approx(-0.1 * 3840 * 7.7, rel=0.03)


@pytest.mark.parametrize("load,rate", [(500, 0), (-1500, 0), (800, 40), (-800, -40), (300, -60), (-4000, 120),
                                       (100, -216), (-6000, 0), (0, 0)])
@pytest.mark.parametrize("guess", [0.0, 15000.0, -15000.0])
def test_inversion_reproduces_the_requested_load(load, rate, guess):
  r5 = eps_ff.r5_for_motion(load, rate, CLA, guess)
  assert eps_ff.firmware_output(r5, rate, CLA) == pytest.approx(load, abs=1e-6)


@pytest.mark.parametrize("angle", [0.0, 45.0, 150.0, -300.0])
@pytest.mark.parametrize("load,rate", [(800, 40), (-4000, 120), (300, -60)])
def test_inversion_reproduces_the_requested_load_at_an_angle(load, rate, angle):
  r5 = eps_ff.r5_for_motion(load, rate, CLA, 0.0, angle)
  assert eps_ff.firmware_output(r5, rate, CLA, angle) == pytest.approx(load, abs=1e-6)


def test_firmware_damping_grows_with_angle_like_its_table():
  # R6 is taken before the firmware's angle table: per deg/s of the published rate it is -119 near centre
  # and -141..-146 past 60 deg on routes 363/365/366/369, flat per count of the pre-table 0x18F rate
  assert eps_ff.firmware_r6(10.0, 0.0, CLA) == pytest.approx(-1220.0, rel=0.01)
  assert eps_ff.firmware_r6(10.0, 5.0, CLA) == pytest.approx(-1220.0, rel=0.02)
  assert eps_ff.firmware_r6(10.0, 200.0, CLA) == pytest.approx(-1220.0 * 1.19, rel=0.02)
  assert eps_ff.firmware_r6(10.0, -200.0, CLA) == eps_ff.firmware_r6(10.0, 200.0, CLA)
  assert eps_ff.firmware_r6(-10.0, 200.0, CLA) == -eps_ff.firmware_r6(10.0, 200.0, CLA)


def test_turn_in_asks_more_than_a_hold_and_an_exit_less():
  # left turn (positive angle and output) at 60 deg, 8 m/s
  def out(rate):
    return eps_ff.output_from_r5(eps_ff.r5_for_motion(eps_ff.column_load(60.0, rate, 8.0, 0.0, CLA.load), rate, CLA), CLA)
  turn_in, hold, unwind = out(40.0), out(0.0), out(-40.0)
  assert turn_in > hold > unwind
  assert hold > 0.0


@pytest.mark.parametrize("v_kph,cap", [(40.0, eps_ff.R5_CAP), (130.0, 0.9 * 24000)])
def test_target_stays_clear_of_the_rail_and_the_speed_ceiling(v_kph, cap):
  ff = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, CLA)
  for k in range(200):
    ff.update(400.0 + k, v_kph / 3.6, 0.0)
  assert abs(ff.r5) <= cap + 1e-6


def test_desired_rate_tracks_a_ramp_and_resets():
  ff = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, CLA)
  for k in range(150):
    ff.update(50.0 * k * DT_CTRL, 10.0, 0.0)
  assert ff.rate == pytest.approx(50.0, abs=1.0)
  ff.reset()
  assert ff.rate == 0.0 and ff.output == 0.0 and ff.prev_angle is None


def test_feedforward_output_is_smoothed():
  raw = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, CLA, output_tau=0.0)
  smooth = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, CLA)
  for ff in (raw, smooth):
    ff.update(0.0, 10.0, 0.0)
    ff.update(30.0, 10.0, 0.0)   # a step in the target
  assert abs(smooth.output) < 0.2 * abs(raw.output)


# --- control core ---------------------------------------------------------------------------------

def _core():
  return eps_ff.HondaEpsLateralCore(KP_BP, KP_V, KP_BP, KI_V, DT_CTRL, ff=eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, CLA))


def _hold(core, frames, des=20.0, angle=20.0, v=10.0, pressed=False):
  for _ in range(frames):
    core.update(des, 0.0, angle, v, 0.0, pressed, False)


def _wound_up_core(fade_up_s=0.5):
  """9 m/s, target 0.5 deg left of the wheel for 3 s: a live integrator into the error."""
  core = _core()
  core.override_fade_up_s = fade_up_s
  for _ in range(300):
    core.update(0.5, 0.0, 0.0, 9.0, 0.0, False, False)
  assert core.pid.i > 0.005
  return core


def _step_core(core, frames, pressed=False, limited=False):
  for _ in range(frames):
    core.update(0.5, 0.0, 0.0, 9.0, 0.0, pressed, limited)


def test_integrator_bleeds_through_the_override_fade():
  core = _wound_up_core(fade_up_s=0.5)
  _step_core(core, 50, pressed=True, limited=True)
  held = core.pid.i
  assert held > 0.005                       # frozen, not bled, while the driver holds the wheel
  _step_core(core, 50, limited=True)        # the carcontroller fading torque back in trips the limit
  assert 0.0 < core.pid.i < held * 0.45     # a bleed (0.5 s at tau 0.5 s leaves 37 %), not a reset
  after = core.pid.i
  _step_core(core, 100, limited=True)       # past the fade: a limit with no recent press still just freezes
  assert core.pid.i == after


def test_a_limit_without_a_press_still_freezes_the_integrator():
  core = _wound_up_core()
  held = core.pid.i
  _step_core(core, 100, limited=True)
  assert core.pid.i == held


def test_reset_forgets_the_press():
  core = _wound_up_core()
  _step_core(core, 10, pressed=True, limited=True)
  core.reset()
  assert core.pid.i == 0.0 and core.since_press_s == math.inf


def test_controller_logs_its_calibration_and_both_delays(monkeypatch):
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsFirmwareVgr": "1"})
  CS = car.CarState.new_message(vEgo=8.0)
  params = log.LiveParametersData.new_message(steerRatio=16.0, stiffnessFactor=1.0)
  lac.update(True, CS, VM, params, False, 0.01, False, 0.33, None, None, SimpleNamespace())
  st = lac.starpilot_lateral_state
  assert st.epsCalibration == "clarity_trw_a020"
  assert st.epsCommandDelay == pytest.approx(0.12) and st.epsModelDelay == pytest.approx(0.33)


def test_controller_reads_the_override_fade_time(monkeypatch):
  lac, _, _ = _controller(monkeypatch, {"HondaOverrideFadeUpSecs": "0.8"})
  assert lac.core.override_fade_up_s == 0.8
  lac, _, _ = _controller(monkeypatch)
  assert lac.core.override_fade_up_s == eps_ff.OVERRIDE_FADE_UP_S_DEFAULT == 1.5


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
  city = eps_ff.column_load(0.0, 5.0, 8.0, 0.0, CLA.load, eps_ff.friction_width(8.0)) - eps_ff.column_load(0.0, 5.0, 8.0, 0.0, CLA.load, 1e9)
  fast = eps_ff.column_load(0.0, 5.0, 8.0, 0.0, CLA.load, eps_ff.friction_width(20.0)) - eps_ff.column_load(0.0, 5.0, 8.0, 0.0, CLA.load, 1e9)
  assert abs(city) < 0.4 * abs(fast)
  turn = [eps_ff.column_load(0.0, 100.0, 8.0, 0.0, CLA.load, w) - eps_ff.column_load(0.0, 100.0, 8.0, 0.0, CLA.load, 1e9) for w in (20.0, 5.0)]
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
  CP = CarInterface.get_params(candidate, {0: {}, 1: {}, 2: {}}, car_fw, False, False, False, TOGGLES)
  # car_helpers.get_car() stores the queried firmware on the CarParams the controllers see
  fw = CP.init("carFw", 1)[0]
  fw.ecu, fw.fwVersion, fw.address, fw.subAddress = "eps", fw_version, 0x18DA30F1, 0
  return CP


class _Params:
  def __init__(self, values=None):
    self.values = values or {}

  def get(self, key, *args, **kwargs):
    return self.values.get(key)

  def get_bool(self, key, *args, **kwargs):
    return self.values.get(key) == "1"


def _clarity_lat_delay(v):
  return honda_eps.scheduled_lateral_delay(eps_ff.CLARITY_TRW_A020_LAT_DELAY_SCHEDULE, v)


def _get_rack_map(fw):
  CP = _params(fw)
  return honda_eps.get_rack_map(CP, honda_eps.eps_firmware_calibration(CP, _Params()))


def _controller(monkeypatch, values=None):
  monkeypatch.setattr(honda_eps, "Params", lambda: _Params(values))
  CP = _params(CLARITY_MODIFIED_FW)
  return honda_eps.LatControlHondaEps(CP, None, DT_CTRL), VehicleModel(CP), CP


def test_only_the_modified_eps_clarity_gets_this_controller_by_default():
  assert honda_eps.use_honda_eps_controller(_params(CLARITY_MODIFIED_FW), _Params())
  assert not honda_eps.use_honda_eps_controller(_params(CLARITY_STOCK_FW), _Params())
  assert not honda_eps.use_honda_eps_controller(_params(b'39990-TBA,A030\x00\x00', CAR.HONDA_CIVIC_BOSCH), _Params())


@pytest.mark.parametrize("v, delay", [(0.0, 0.15), (3.5, 0.15), (7.0, 0.08), (12.0, 0.10), (20.0, 0.20), (30.0, 0.30), (40.0, 0.30)])
def test_lateral_delay_follows_the_measured_execution_delay(v, delay):
  assert _clarity_lat_delay(v) == pytest.approx(delay)


def test_every_vehicle_tells_the_model_the_measured_schedule():
  # the Clarity's measured schedule is every car's until a measurement on that car says otherwise
  for _, cal in eps_ff.EPS_FIRMWARE_CALIBRATIONS.values():
    assert cal.lat_delay_schedule == eps_ff.CLARITY_TRW_A020_LAT_DELAY_SCHEDULE, cal.name
  CP = _params(b'39990-TBA,C020\x00\x00', CAR.HONDA_CIVIC_BOSCH)
  assert honda_eps.lateral_delay_schedule(CP, _Params({"HondaEpsController": "1"})) == eps_ff.CLARITY_TRW_A020_LAT_DELAY_SCHEDULE
  assert honda_eps.lateral_delay_schedule(CP, _Params()) is None   # not on this controller: liveDelay


def test_lateral_delay_dips_in_town_and_rises_from_there():
  # measured: the crawl is slower than town (small targets), and from town up the delay rises with speed
  assert _clarity_lat_delay(3.5) > _clarity_lat_delay(7.0)
  delays = [_clarity_lat_delay(v) for v in np.linspace(7.0, 40.0, 67)]
  assert all(b >= a for a, b in zip(delays, delays[1:], strict=False))


def test_nrdr_settings_are_read(monkeypatch):
  lac, _, _ = _controller(monkeypatch, {
    "HondaEpsFirmwareVgr": "1", "HondaEpsAngleRateLimit": "219", "HondaTorqueOutputLowPassFilter": "1",
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
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsFirmwareVgr": "1"})
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
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsFirmwareVgr": "1", "HondaEpsAngleRateLimit": "100"})
  outs = _drive(lac, VM, frames=120)
  steps = [abs(b[2] - a[2]) for a, b in zip(outs[20:], outs[21:], strict=False)]
  assert max(steps) <= 100.0 * DT_CTRL + 1e-6


# --- per-image profiles ----------------------------------------------------------------------------

# (candidate, modified EPS fwVersion, calibration) for every PTM image
CALIBRATION_CARS = [
  (CAR.HONDA_CLARITY, CLARITY_MODIFIED_FW, eps_ff.CLARITY_TRW_A020),
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C020\x00\x00', eps_ff.CIVIC_TBA_C020),
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C120\x00\x00', eps_ff.CIVIC_TBA_C120),
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TGG,A120\x00\x00', eps_ff.CIVIC_TGG_A120),
  (CAR.HONDA_CIVIC, b'39990-TBA,A030\x00\x00', eps_ff.CIVIC_TBA_A030),
  (CAR.HONDA_CIVIC, b'39990-TEG,A010\x00\x00', eps_ff.CIVIC_TEG_A010),
  (CAR.HONDA_INSIGHT, b'39990-TXM,A040\x00\x00', eps_ff.INSIGHT_TXM_A040),
  (CAR.HONDA_CRV_5G, b'39990-TLA,A040\x00\x00', eps_ff.CRV_TLA_A040),
  (CAR.HONDA_CRV_5G, b'39990-TLA,A220\x00\x00', eps_ff.CRV_TLA_A220),
]
ALL_PROFILES = [p for _, _, p in CALIBRATION_CARS]
ON = {"HondaEpsController": "1"}


@pytest.mark.parametrize("candidate,fw,cal", CALIBRATION_CARS, ids=[p.name for _, _, p in CALIBRATION_CARS])
def test_calibration_matches_the_cars_torque_map_and_is_selected_only_when_enabled(candidate, fw, cal):
  CP = _params(fw, candidate)
  assert list(CP.lateralParams.torqueBP) == [0, cal.e4_per_output] == list(CP.lateralParams.torqueV)
  assert honda_eps.eps_firmware_calibration(CP, _Params(ON)) is cal
  if candidate != CAR.HONDA_CLARITY:
    assert honda_eps.eps_firmware_calibration(CP, _Params()) is None


def test_clarity_always_steers_with_the_pminus5_build():
  # P-minus-5 is the Clarity standard; there is no build setting any more
  CP = _params(CLARITY_MODIFIED_FW)
  assert honda_eps.eps_firmware_calibration(CP, _Params()) is eps_ff.CLARITY_TRW_A020
  assert honda_eps.eps_firmware_calibration(CP, _Params({"HondaEpsClarityPminus5": "0"})) is eps_ff.CLARITY_TRW_A020
  assert not hasattr(eps_ff, "CLARITY_P123")


@pytest.mark.parametrize("candidate,fw", [
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA-C020\x00\x00'),   # stock EPS
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TGG,A020\x00\x00'),   # modified, but no PTM build exists
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,A030\x00\x00'),   # a known image on the wrong car
])
def test_cars_without_a_matching_profile_keep_latcontrol_pid(candidate, fw):
  assert honda_eps.eps_firmware_calibration(_params(fw, candidate), _Params(ON)) is None


def test_a_torque_map_the_profile_does_not_expect_keeps_latcontrol_pid():
  CP = _params(b'39990-TBA,C020\x00\x00', CAR.HONDA_CIVIC_BOSCH)
  CP.lateralParams.torqueV = [0, 3840]
  assert honda_eps.eps_firmware_calibration(CP, _Params(ON)) is None


def test_clarity_trw_a020_profile_is_the_validated_build():
  # the constants routes 352/353 and the closed-loop replay were validated with; R6 is the angle-scaled centre value
  # re-measured on routes 363/365/366/369, the scale word on routes 35e/360/361
  cal = eps_ff.CLARITY_TRW_A020
  assert cal.kp_v == (117, 148, 184, 220, 245, 257, 263, 265, 265) and cal.r5_per_key == 18.04
  assert cal.r6_per_deg_s == eps_ff.CLARITY_TRW_A020_R6_CENTRE == -122.0 and cal.scale_q8 == 256.0
  assert cal.r6_angle_bp is not None and cal.r6_angle_gain[0] == 1.0 and cal.r6_angle_gain[-1] > 1.15
  assert cal.load == eps_ff.CLARITY_TRW_A020_LOAD and cal.e4_per_output == 3840.0
  assert (cal.p_scale, cal.i_scale) == ((1.25, 1.00, 1.25), (0.70, 0.95, 0.35))


def test_nidec_civics_carry_the_teg_measurements():
  # the column load measured on the TEG-A010 telemetry drive and R6 from their own A table; tables stay the C020's
  for cal in (eps_ff.CIVIC_TBA_A030, eps_ff.CIVIC_TEG_A010):
    assert cal.r6_per_deg_s == eps_ff.CIVIC_TBA_C120_R6_CENTRE and cal.r6_angle_gain == eps_ff.CIVIC_TBA_C120_R6_GAIN and cal.load == eps_ff.CIVIC_TEG_A010_LOAD
    assert (cal.r5_key_bp, cal.kp_key_bp, cal.e4_per_output) == (eps_ff.CIVIC_TBA_C020.r5_key_bp, eps_ff.CIVIC_TBA_C020.kp_key_bp, 3840.0)
  # the Nidec column asks for more than the C020's at every speed it was measured over
  for v in (3.0, 8.0, 15.0):
    for load in (eps_ff.CIVIC_TEG_A010_LOAD, eps_ff.CIVIC_TBA_C020_LOAD):
      assert load.k0 + load.k1 * v ** 2 < 0.0
    teg, c020 = eps_ff.CIVIC_TEG_A010_LOAD, eps_ff.CIVIC_TBA_C020_LOAD
    assert teg.k0 + teg.k1 * v ** 2 < 1.4 * (c020.k0 + c020.k1 * v ** 2)


@pytest.mark.parametrize("cal", ALL_PROFILES, ids=[p.name for p in ALL_PROFILES])
def test_profile_tables_are_well_formed(cal):
  for bp in (cal.r5_key_bp, cal.r5_v, cal.envelope_bp, cal.kp_key_bp):
    assert all(b > a for a, b in zip(bp[:-1], bp[1:], strict=False))
  assert all(b >= a for a, b in zip(cal.kp_v[:-1], cal.kp_v[1:], strict=False))
  assert len(cal.r5_key_bp) == len(cal.r5_v) and len(cal.kp_key_bp) == len(cal.kp_v)
  assert len(cal.p_scale) == len(cal.i_scale) == 3 and cal.r6_per_deg_s < 0.0
  # the Kp pieces used by the solver agree with the Kp the firmware applies
  for lo, hi, kp_lo, slope in cal.kp_pieces:
    for r in (lo, 0.5 * (lo + min(hi, lo + 4000.0))):
      assert kp_lo + slope * (r - lo) == pytest.approx(eps_ff.firmware_kp(r, cal), abs=1e-6)


@pytest.mark.parametrize("cal", ALL_PROFILES, ids=[p.name for p in ALL_PROFILES])
@pytest.mark.parametrize("output", [-0.9, -0.3, -0.05, 0.02, 0.4, 0.8])
def test_every_profiles_command_map_round_trips(cal, output):
  r5 = eps_ff.r5_from_output(output, 15.0, cal)
  # truncation to an integer key is at most one key step of output
  assert eps_ff.output_from_r5(r5, cal) == pytest.approx(output, abs=8.0 * 32768.0 / 56756.0 / cal.e4_per_output)


@pytest.mark.parametrize("cal", ALL_PROFILES, ids=[p.name for p in ALL_PROFILES])
@pytest.mark.parametrize("load,rate", [(500, 0), (-1500, 0), (800, 40), (-800, -40), (300, -60), (-4000, 120), (0, 0)])
def test_every_profiles_inversion_reproduces_the_requested_load(cal, load, rate):
  r5 = eps_ff.r5_for_motion(load, rate, cal, 0.0)
  assert eps_ff.firmware_output(r5, rate, cal=cal) == pytest.approx(load, abs=1e-6)


def test_c020_full_output_lands_on_the_measured_rail():
  # route 00000284: the largest R5 the C020 ever ran was 28497, row 1 at the 1663 key clamp
  assert abs(eps_ff.r5_from_output(1.0, 20.0, eps_ff.CIVIC_TBA_C020)) == pytest.approx(28497, abs=1)
  # and its envelope takes the ceiling to key 1108 from 160 km/h
  assert eps_ff.CIVIC_TBA_C020.key_ceiling(170 / 3.6) == 1108


@pytest.mark.parametrize("candidate,fw,cal", CALIBRATION_CARS, ids=[p.name for _, _, p in CALIBRATION_CARS])
def test_every_ptm_car_steers_with_its_own_calibration(monkeypatch, candidate, fw, cal):
  monkeypatch.setattr(honda_eps, "Params", lambda: _Params(ON))
  CP = _params(fw, candidate)
  lac = honda_eps.LatControlHondaEps(CP, None, DT_CTRL)
  assert lac.calibration is cal and lac.core.ff.cal is cal
  assert (lac.core.p_scale, lac.core.i_scale) == (cal.p_scale, cal.i_scale)
  outs = _drive(lac, VehicleModel(CP))
  assert max(abs(out) for _, out, _, _ in outs) > 0.02
  assert all(abs(out) <= 1.0 and math.isfinite(out) for _, out, _, _ in outs)
  assert lac.starpilot_lateral_state.epsFfWeight == 1.0


def test_crv_carries_its_own_measured_r6_and_load():
  # route 00000006--82bb552a2c: R6 least squares at norm 1450 scaled to the image's 1650; load fitted in m/s with roll
  assert eps_ff.CRV_TLA_A040.r6_per_deg_s == eps_ff.CRV_TLA_A040_R6_CENTRE and eps_ff.CRV_TLA_A040.r6_angle_gain == eps_ff.CRV_TLA_A040_R6_GAIN
  # the owner's single V5 fit (-138.4 against 0x14A) sits inside the curve the A table gives
  assert eps_ff.firmware_r6(1.0, 0.0, eps_ff.CRV_TLA_A040) > -138.4 > eps_ff.firmware_r6(1.0, 180.0, eps_ff.CRV_TLA_A040)
  assert eps_ff.CRV_TLA_A040.load is eps_ff.CRV_TLA_A040_LOAD
  assert -0.25 < eps_ff.CRV_TLA_A040_LOAD.k1 < -0.10 and eps_ff.CRV_TLA_A040_LOAD.kroll < 0.0


def test_crv_a220_reads_its_own_command_axis_and_predicts_r6_from_the_a040():
  a220, a040 = eps_ff.CRV_TLA_A220, eps_ff.CRV_TLA_A040
  # selected by the fw string in either spelling, and not on another car
  assert eps_ff.select_eps_firmware_calibration("HONDA_CRV_5G", "39990-TLA-A220") is a220
  assert eps_ff.select_eps_firmware_calibration("HONDA_CIVIC", "39990-TLA-A220") is None
  # command axis read from the A220 image (row 0, 0x11AE0): ~2.5x the A040's R5 at the same key
  assert a220.r5_key_bp == (0, 161, 222, 322, 409, 534, 696, 998, 1663) and a220.key_clamp == 1774
  assert abs(eps_ff.r5_from_output(1.0, 20.0, a220)) == 30000          # full output saturates the map below 150 km/h
  assert abs(eps_ff.r5_from_output(1.0, 160 / 3.6, a220)) == pytest.approx(28475, abs=2)   # key 1330 envelope
  assert float(np.interp(443, a220.r5_key_bp, a220.r5_v)) == pytest.approx(13094, abs=1)
  assert float(np.interp(443, a040.r5_key_bp, a040.r5_v)) == pytest.approx(4938, abs=1)
  # P axis and table are the A040's; the envelope is the A220's own (1330 from 150 km/h, not flat)
  assert a220.kp_key_bp == a040.kp_key_bp and a220.kp_v == a040.kp_v
  assert a220.key_ceiling(120 / 3.6) == 1774 and a220.key_ceiling(160 / 3.6) == 1330
  assert a040.key_ceiling(160 / 3.6) == 1774
  # R6 is predicted from the A040 (shared 3121 / A-centre 16783 / NORM 1650), not measured; load is the CR-V's
  assert a220.r6_per_deg_s == a040.r6_per_deg_s == eps_ff.CRV_TLA_A040_R6_CENTRE and a220.r6_angle_gain == a040.r6_angle_gain
  assert a220.load is eps_ff.CRV_TLA_A040_LOAD and a220.e4_per_output == 4096.0
  assert (a220.p_scale, a220.i_scale) == (a040.p_scale, a040.i_scale) == (eps_ff.CRV_TLA_A040_P_SCALE, eps_ff.CRV_TLA_A040_I_SCALE) == ((1.0,) * 3,) * 2


def test_command_delay_hands_over_the_value_issued_that_long_ago():
  d = honda_eps.CommandDelay(DT_CTRL, 0.2)
  outs = [d.update(float(k), 0.12) for k in range(40)]
  assert outs[30] == pytest.approx(18.0)
  assert outs[0] == 0.0 and outs[5] == 0.0              # not enough history yet: the oldest value
  half = honda_eps.CommandDelay(DT_CTRL, 0.2)
  assert [half.update(float(k), 0.125) for k in range(40)][30] == pytest.approx(17.5)


def test_command_delay_is_for_town_speeds_only():
  cal = eps_ff.CLARITY_TRW_A020
  assert eps_ff.command_delay(cal, 0.0) == eps_ff.command_delay(cal, 10.0) == pytest.approx(0.12)
  assert eps_ff.command_delay(cal, 12.5) == pytest.approx(0.06)
  assert eps_ff.command_delay(cal, 15.0) == eps_ff.command_delay(cal, 30.0) == 0.0
  assert honda_eps.CommandDelay(DT_CTRL, 0.2).update(3.0, 0.0) == 3.0


def test_every_vehicle_has_its_own_command_delay():
  delays = {cal.name: cal.cmd_delay_s for _, cal in eps_ff.EPS_FIRMWARE_CALIBRATIONS.values()}
  measured = {"clarity_trw_a020": 0.12, "civic_tba_c020": 0.15}
  same_chassis_as_c020 = {"civic_tba_c120": 0.15, "civic_tgg_a120": 0.15}
  inferred = {"insight_txm_a040": 0.15}
  for name, delay in delays.items():
    assert delay == {**measured, **same_chassis_as_c020, **inferred}.get(name, eps_ff.CMD_DELAY_DEFAULT_S), name
  # the default is the smaller measured value, so an unmeasured car cannot be pushed late
  assert eps_ff.CMD_DELAY_DEFAULT_S == min(measured.values())


@pytest.mark.parametrize("v, late_frames", [(8.0, 12), (20.0, 0)])
def test_target_follows_the_curvature_one_command_delay_late(monkeypatch, v, late_frames):
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsFirmwareVgr": "1"})
  CS = car.CarState.new_message()
  CS.vEgo = v
  params = log.LiveParametersData.new_message()
  params.steerRatio, params.stiffnessFactor = 16.0, 1.0
  targets = []
  for k in range(100):
    _, angle_des, _ = lac.update(True, CS, VM, params, False, 0.0 if k < 50 else 0.02, False, 0.2, None, None, SimpleNamespace())
    targets.append(angle_des)
  first = next(k for k, a in enumerate(targets) if abs(a) > 1e-6)
  assert first == 50 + late_frames

def _rack_map():
  rack_map = _get_rack_map(CLARITY_MODIFIED_FW)
  assert rack_map is not None
  return rack_map


def test_rack_map_is_only_built_for_the_identified_car():
  _rack_map()
  assert _get_rack_map(CLARITY_STOCK_FW) is None


def _ptm_cp(candidate, fw):
  CP = _params(fw, candidate)
  return CP, honda_eps.eps_firmware_calibration(CP, _Params({"HondaEpsController": "1"}))


@pytest.mark.parametrize("candidate,fw,table", [
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C020\x00\x00', rack.CIVIC_TBA_C020_RACK),
  (CAR.HONDA_INSIGHT, b'39990-TXM,A040\x00\x00', rack.INSIGHT_TXM_A040_RACK),
])
def test_the_civic_c020_and_insight_have_their_own_yaw_fitted_rack_maps(candidate, fw, table):
  CP, cal = _ptm_cp(candidate, fw)
  assert cal.rack is table
  rack_map = honda_eps.get_rack_map(CP, cal)
  assert rack_map is not None
  assert all(b <= a for a, b in zip(table.ratio_v, table.ratio_v[1:], strict=False))   # a rack cannot quicken back
  for v in (3.0, 15.0):
    for angle in (-200.0, -30.0, 5.0, 90.0, 250.0):
      assert rack_map.angle_from_curvature(rack_map.curvature_from_angle(angle, v, 0.01), v, 0.01) == pytest.approx(angle, abs=1e-3)


@pytest.mark.parametrize("candidate,fw", [(CAR.HONDA_CIVIC, b'39990-TEG,A010\x00\x00'),
                                          (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C120\x00\x00'),
                                          (CAR.HONDA_CRV_5G, b'39990-TLA,A040\x00\x00')])
def test_cars_without_a_yaw_fit_have_no_rack_map(candidate, fw):
  CP, cal = _ptm_cp(candidate, fw)
  assert cal.rack is None and honda_eps.get_rack_map(CP, cal) is None


@pytest.mark.parametrize("firmware_vgr", ["0", "1"])
def test_a_rack_map_is_the_geometry_whatever_the_firmware_vgr_setting(monkeypatch, firmware_vgr):
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsFirmwareVgr": firmware_vgr})
  assert lac.use_firmware_vgr == (firmware_vgr == "1")
  for k in (-0.05, -0.01, 0.002, 0.03):
    assert lac._desired_angle_no_offset(VM, 8.0, 0.0, k) == pytest.approx(lac.rack_map.angle_from_curvature(k, 8.0, 0.0))


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
  ratio = float(np.interp(angle, rack.CLARITY_TRW_A020_RACK.ratio_bp, rack.CLARITY_TRW_A020_RACK.ratio_v))
  expected = -lin / (ratio * 2.75 * (1.0 - rack.CLARITY_TRW_A020_RACK.slip_factor * v ** 2))
  assert rack_map.curvature_from_angle(angle, v, 0.0) == pytest.approx(expected, rel=1e-3)


def test_controller_steers_through_the_rack_map(monkeypatch):
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsFirmwareVgr": "1"})
  VM.update_params(1.0, 17.3)   # a paramsd ratio must no longer change the target
  for curvature, v, roll in ((0.06, 7.0, 0.0), (-0.002, 30.0, 0.02), (0.0, 12.0, 0.0)):
    assert lac._desired_angle_no_offset(VM, v, roll, curvature) == pytest.approx(
      lac.rack_map.angle_from_curvature(curvature, v, roll))


def test_rack_map_asks_less_wheel_than_the_paramsd_ratio_in_tight_turns(monkeypatch):
  # the city over-steer: paramsd's single ratio over VGR asks 3.5-6% too much wheel at 100-250 deg
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsFirmwareVgr": "1"})
  VM.update_params(1.0, 17.3)
  for curvature in (0.04, 0.06, 0.1):
    old = vgr_linear_to_physical(math.degrees(VM.get_steer_from_curvature(-curvature, 7.0, 0.0)), lac.vgr_inverse)
    new = lac.rack_map.angle_from_curvature(curvature, 7.0, 0.0)
    assert 0.93 < new / old < 0.97


def test_insight_carries_its_own_measured_load_on_row_0():
  cal = eps_ff.INSIGHT_TXM_A040
  assert cal.load is eps_ff.INSIGHT_TXM_A040_LOAD and cal.load != eps_ff.CIVIC_TBA_C020_LOAD
  assert cal.r5_key_bp == (0, 111, 222, 333, 443, 665, 887, 1108, 1663)  # row 0, every Insight build and variant
  assert cal.e4_per_output == 3840.0 and cal.r6_per_deg_s == eps_ff.INSIGHT_TXM_A040_R6_CENTRE and cal.r6_angle_gain == eps_ff.INSIGHT_TXM_A040_R6_GAIN
  # the fitted column is lighter than the C020's at speed, which the carried-over load over-asked
  insight = eps_ff.column_load(10., 0., 25., 0., load=eps_ff.INSIGHT_TXM_A040_LOAD)
  assert abs(insight) < abs(eps_ff.column_load(10., 0., 25., 0., load=eps_ff.CIVIC_TBA_C020_LOAD))


@pytest.mark.parametrize("cal", [c for c in ALL_PROFILES if not c.name.startswith("clarity")], ids=lambda c: c.name)
def test_every_image_has_angle_dependent_r6(cal):
  # R6 is the pre-table column rate; per published deg/s it grows with the A table's slope on every image
  assert cal.r6_angle_bp is not None and cal.r6_angle_gain[0] == 1.0
  assert eps_ff.firmware_r6(1.0, 180.0, cal) < eps_ff.firmware_r6(1.0, 0.0, cal) < 0.0
  assert eps_ff.firmware_r6(1.0, -180.0, cal) == eps_ff.firmware_r6(1.0, 180.0, cal)


@pytest.mark.parametrize("band, measured", [(7.5, -153.2), (22.5, -152.2), (45.0, -155.0), (80.0, -162.2),
                                            (125.0, -167.4), (175.0, -168.9), (250.0, -168.9)])
def test_c020_r6_is_its_measured_curve(band, measured):
  # 0.1 s derivative of the published angle against 0x6A2 R6, routes 64/154/287/289/294
  assert eps_ff.firmware_r6(1.0, band, eps_ff.CIVIC_TBA_C020) == pytest.approx(measured, rel=0.01)


def test_a_table_r6_model_matches_the_clarity_and_the_c020_centre():
  # the A-table model, centre scaled by the divisor ratio, against telemetry: Clarity -121.5 at 0-15 deg,
  # C020 -153.2 at 0-15 deg (20647 / 16384 x -122 = -153.7)
  assert eps_ff.CLARITY_TRW_A020_R6_CENTRE * 20647 / 16384 == pytest.approx(eps_ff.CIVIC_TBA_C020_R6_CENTRE, rel=0.01)
  assert eps_ff.CIVIC_TBA_C120_R6_CENTRE == pytest.approx(-122.0 * 20972 / 16384, abs=0.01)
  assert eps_ff.INSIGHT_TXM_A040_R6_CENTRE == pytest.approx(-122.0 * 17613 / 16384, abs=0.01)
  assert eps_ff.CRV_TLA_A040_R6_CENTRE == pytest.approx(-122.0 * 16783 / 16384, abs=0.01)


@pytest.mark.parametrize("name", [cal.name for _, cal in eps_ff.EPS_FIRMWARE_CALIBRATIONS.values()])
def test_every_calibration_says_where_every_value_came_from(name):
  cal = next(c for _, c in eps_ff.EPS_FIRMWARE_CALIBRATIONS.values() if c.name == name)
  prov = eps_ff.provenance(cal)
  assert set(prov) == set(eps_ff.PROVENANCE_FIELDS)
  for key, value in prov.items():
    assert value.split(':')[0].split(' ')[0] in eps_ff.PROVENANCE_KINDS, (name, key, value)
  # consistency with the calibration itself
  assert (prov["rack"] == "none") == (cal.rack is None)
  if cal.cmd_delay_s == eps_ff.CMD_DELAY_DEFAULT_S and not prov["cmd_delay"].startswith("measured"):
    assert prov["cmd_delay"].startswith(("default", "inferred")), name
  assert eps_ff.provenance_summary(cal)
