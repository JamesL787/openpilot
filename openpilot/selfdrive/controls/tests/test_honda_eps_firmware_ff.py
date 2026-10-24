import dataclasses
import math
from types import SimpleNamespace

import numpy as np
import pytest

from opendbc.car.structs import car
from openpilot.cereal import log
import openpilot.selfdrive.controls.lib.honda_eps_rack_map as rack
import openpilot.selfdrive.controls.lib.honda_eps_firmware_ff as eps_ff
import openpilot.selfdrive.controls.lib.honda_eps_calibrations as eps_cal
import openpilot.selfdrive.controls.lib.latcontrol_honda_eps as honda_eps
from opendbc.car import structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.steer_ratio import (
  HONDA_VGR_CENTRE_DIVISOR_BY_PROFILE, HONDA_VGR_CIVIC_TBA_C020, HONDA_VGR_CIVIC_TBA_C120, HONDA_VGR_CLARITY_TRW_A020,
  HONDA_VGR_CRV_TLA_A040, HONDA_VGR_INSIGHT_TXM_A040, get_honda_vgr_inverse, vgr_linear_to_physical, vgr_physical_to_linear,
)
from opendbc.car.honda.values import CAR, CarControllerParams, HondaFlags
from opendbc.car.vehicle_model import VehicleModel
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.latcontrol_honda_modified_pid import _lat_pid_scale_banded

CLARITY_MODIFIED_FW = b'39990-TRW,A020\x00\x00'
CLARITY_STOCK_FW = b'39990-TRW-A020\x00\x00'
CLA = eps_cal.CLARITY_TRW_A020  # the reference calibration these law tests were written on
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


@pytest.mark.parametrize("cal,ceiling", [(eps_cal.CLARITY_TRW_A020, 1.0), (eps_cal.CIVIC_TBA_C020, 1.0),
                                         (eps_cal.ACURA_RDX_TJB_A220, 1.0),
                                         (eps_cal.CRV_TLA_A040, 3841 / 4096), (eps_cal.CRV_TLA_A220, 3841 / 4096)])
def test_output_tops_out_where_the_command_row_ends(cal, ceiling):
  assert cal.output_ceiling() == pytest.approx(ceiling)
  # the ceiling reaches the firmware's last answer (within one key of truncation), and 1.0 gets no more R5 than it
  last = float(np.interp(min(cal.key_clamp, cal.r5_key_bp[-1]), cal.r5_key_bp, cal.r5_v))
  assert abs(eps_ff.r5_from_output(cal.output_ceiling(), 10.0, cal)) == pytest.approx(last, rel=2e-3)
  assert eps_ff.r5_from_output(1.0, 10.0, cal) == eps_ff.r5_from_output(cal.output_ceiling(), 10.0, cal)


def test_the_core_does_not_wind_up_past_the_row_end():
  cal = eps_cal.CRV_TLA_A040
  core = eps_ff.HondaEpsLateralCore(KP_BP, KP_V, KP_BP, KI_V, DT_CTRL, ff=eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, cal))
  for _ in range(3000):
    out = core.update(5.0, 0.0, 0.0, 15.0, 0.0, False, False)  # a wheel stuck 5 deg short: the integrator runs
  assert abs(out) == pytest.approx(cal.output_ceiling(), rel=1e-3)  # the output LPF still closing the last bit
  assert core.pid.p + core.pid.i + core.pid.f <= cal.output_ceiling() + 1e-6  # it stopped at the ceiling, not at 1.0
  for _ in range(10):
    out = core.update(0.0, 0.0, 0.0, 15.0, 0.0, False, False)
  assert abs(out) < cal.output_ceiling() - 0.1  # so it comes off the ceiling at once when the error goes


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
  lac, VM, _ = _controller(monkeypatch)
  CS = car.CarState.new_message(vEgo=8.0)
  params = log.VehicleParameters.new_message(steerRatio=16.0, stiffnessFactor=1.0)
  lac.update(True, CS, VM, params, False, 0.01, False, 0.33, None, None, SimpleNamespace())
  st = lac.starpilot_lateral_state
  assert st.epsCalibration == "clarity_trw_a020"
  assert st.epsCommandDelay == pytest.approx(0.12) and st.epsModelDelay == pytest.approx(0.33)


def test_controller_reads_the_override_fade_time(monkeypatch):
  lac, _, _ = _controller(monkeypatch, {"HondaOverrideFadeUpSecs": "0.8"})
  assert lac.core.override_fade_up_s == 0.8
  lac, _, _ = _controller(monkeypatch)
  assert lac.core.override_fade_up_s == eps_ff.OVERRIDE_FADE_UP_S_DEFAULT == 0.5


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


def test_the_tgg_steers_on_its_own_measured_column_and_rack():
  tgg = eps_cal.CIVIC_TGG_A120
  assert tgg.load == eps_cal.CIVIC_TGG_A120_LOAD and tgg.rack is rack.CIVIC_TGG_A120_RACK
  assert eps_cal.provenance(tgg)["load"].startswith("measured") and eps_cal.provenance(tgg)["rack"].startswith("measured")
  # its column holds about 2x the C020's at a crawl and alike on the highway
  hold = lambda load, v: load.k0 + load.k1 * v * v  # noqa: E731
  assert 1.7 < hold(tgg.load, 5.0) / hold(eps_cal.CIVIC_TBA_C020_LOAD, 5.0) < 2.2
  assert 0.85 < hold(tgg.load, 30.0) / hold(eps_cal.CIVIC_TBA_C020_LOAD, 30.0) < 1.05


def test_a_calibration_can_carry_its_own_friction_knee():
  rdx = eps_cal.ACURA_RDX_TJB_A220
  assert eps_ff.friction_width(8.0, rdx) == 20.0 and eps_ff.friction_width(30.0, rdx) == 15.0
  assert eps_ff.friction_width(30.0, CLA) == eps_ff.friction_width(30.0) == 5.0   # everyone else: the default
  # a slow 2 deg/s correction at speed gets a third of the default knee's friction
  loads = []
  for cal in (rdx, dataclasses.replace(rdx, friction_width_v=None)):
    ff = eps_ff.HondaEpsFirmwareFeedforward(DT_CTRL, cal)
    for k in range(100):
      ff.update(2.0 * k * DT_CTRL, 30.0, 0.0)
    loads.append(ff.load - eps_ff.column_load(ff.prev_angle + eps_ff.LEAD_S * ff.rate, ff.rate, 30.0, 0.0, cal.load, 1e9))
  assert loads[0] / loads[1] == pytest.approx(math.tanh(2.0 / 15.0) / math.tanh(2.0 / 5.0), rel=0.05)


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
  CP = CarInterface.get_params(candidate, {0: {}, 1: {}, 2: {}}, car_fw, False, False, False)  # 7.0: no toggles argument
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
  return honda_eps.get_rack_map(CP, honda_eps.eps_firmware_calibration(CP))


def _controller(monkeypatch, values=None):
  monkeypatch.setattr(honda_eps, "Params", lambda: _Params(values))
  CP = _params(CLARITY_MODIFIED_FW)
  return honda_eps.LatControlHondaEps(CP, None, DT_CTRL), VehicleModel(CP), CP


def test_only_calibrated_modified_eps_images_get_this_controller():
  assert honda_eps.use_honda_eps_controller(_params(CLARITY_MODIFIED_FW))
  assert not honda_eps.use_honda_eps_controller(_params(CLARITY_STOCK_FW))
  assert honda_eps.use_honda_eps_controller(_params(b'39990-TXM,A040\x00\x00', CAR.HONDA_INSIGHT))
  assert not honda_eps.use_honda_eps_controller(_params(b'39990-TXM-A040\x00\x00', CAR.HONDA_INSIGHT))
  assert honda_eps.use_honda_eps_controller(_params(b'39990-TBA,C020\x00\x00', CAR.HONDA_CIVIC_BOSCH))
  assert not honda_eps.use_honda_eps_controller(_params(b'39990-TBA,A030\x00\x00', CAR.HONDA_CIVIC_BOSCH))


@pytest.mark.parametrize("v, delay", [(0.0, 0.15), (3.5, 0.15), (7.0, 0.08), (12.0, 0.10), (20.0, 0.20), (30.0, 0.30), (40.0, 0.30)])
def test_lateral_delay_follows_the_measured_execution_delay(v, delay):
  assert _clarity_lat_delay(v) == pytest.approx(delay)


def test_every_vehicle_tells_the_model_the_measured_schedule():
  # the Clarity's measured schedule is every car's until a measurement on that car says otherwise: the TEG and the
  # C020 have their own, and the same cars take theirs (the A030 the TEG's; the C120 and the TGG the C020's)
  own = {"civic_teg_a010": eps_cal.CIVIC_TEG_A010_LAT_DELAY_SCHEDULE, "civic_tba_a030": eps_cal.CIVIC_TEG_A010_LAT_DELAY_SCHEDULE,
         "civic_tba_c020": eps_cal.CIVIC_TBA_C020_LAT_DELAY_SCHEDULE, "civic_tba_c120": eps_cal.CIVIC_TBA_C020_LAT_DELAY_SCHEDULE,
         "civic_tgg_a120": eps_cal.CIVIC_TBA_C020_LAT_DELAY_SCHEDULE, "rdx_tjb_a220": eps_cal.RDX_TJB_A220_LAT_DELAY_SCHEDULE}
  for _, cal in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values():
    assert cal.lat_delay_schedule == own.get(cal.name, eps_ff.CLARITY_TRW_A020_LAT_DELAY_SCHEDULE), cal.name
  CP = _params(b'39990-TBA,C020\x00\x00', CAR.HONDA_CIVIC_BOSCH)
  assert honda_eps.lateral_delay_schedule(CP) == eps_cal.CIVIC_TBA_C020_LAT_DELAY_SCHEDULE
  # not on this controller: liveDelay
  assert honda_eps.lateral_delay_schedule(_params(b'39990-TGG,A020\x00\x00', CAR.HONDA_CIVIC_BOSCH)) is None


@pytest.mark.parametrize("schedule, lag", [
  (eps_cal.CIVIC_TEG_A010_LAT_DELAY_SCHEDULE, (0.26, 0.31)),  # TEG routes 12e-13d, every speed band
  (eps_cal.CIVIC_TBA_C020_LAT_DELAY_SCHEDULE, (0.33, 0.41)),  # route 380, this controller's output filter
])
def test_a_civic_is_told_its_measured_lag_from_the_frame(schedule, lag):
  # modeld reads a plan model at told + 0.075 s (frame + half a step), so that is where the car's own lag must land
  for v in (3.5, 7.0, 12.0, 20.0, 30.0):
    assert lag[0] - 0.03 <= honda_eps.scheduled_lateral_delay(schedule, v) + 0.075 <= lag[1] + 0.03, v


def test_the_rdx_is_told_its_measured_highway_lag_from_the_frame():
  # routes 412ed2539bfc2c42/00000003 and 00000004 at 28-32 m/s: 0.21-0.27 s from the frame to the yaw curvature
  for v in (20.0, 30.0, 35.0):
    assert 0.21 - 0.03 <= honda_eps.scheduled_lateral_delay(eps_cal.RDX_TJB_A220_LAT_DELAY_SCHEDULE, v) + 0.075 <= 0.27 + 0.03, v


def test_the_rdx_is_told_its_measured_town_lag_from_the_frame():
  # route 412ed2539bfc2c42/0000000b segments 6-9 at 12-20 m/s on turning samples: ~0.19 s schedule (~0.26 s frame)
  for v in (12.0, 15.0, 18.0):
    assert 0.24 - 0.03 <= honda_eps.scheduled_lateral_delay(eps_cal.RDX_TJB_A220_LAT_DELAY_SCHEDULE, v) + 0.075 <= 0.30 + 0.03, v


def test_lateral_delay_dips_in_town_and_rises_from_there():
  # measured: the crawl is slower than town (small targets), and from town up the delay rises with speed
  assert _clarity_lat_delay(3.5) > _clarity_lat_delay(7.0)
  delays = [_clarity_lat_delay(v) for v in np.linspace(7.0, 40.0, 67)]
  assert all(b >= a for a, b in zip(delays, delays[1:], strict=False))


def test_the_output_lpf_is_on_when_nothing_is_set(monkeypatch):
  # vfn's manager seeded HondaTorqueOutputLowPassFilter on; 7.0 has no seeding, so an unset key must read as on
  lac, _, _ = _controller(monkeypatch, {})
  assert lac.core.output_lpf_enabled
  lac, _, _ = _controller(monkeypatch, {"HondaTorqueOutputLowPassFilter": "0"})
  assert not lac.core.output_lpf_enabled


def test_controller_settings_are_read(monkeypatch):
  lac, _, _ = _controller(monkeypatch, {
    "HondaEpsAngleRateLimit": "219", "HondaTorqueOutputLowPassFilter": "1",
    "HondaTorqueOutputLpfTauLowSpeed": "0.07", "HondaTorqueOutputLpfTauStandard": "0.05", "HondaTorqueOutputLpfTauHighway": "0.01",
  })
  assert lac.angle_rate_limit_deg_s == 219.0
  assert lac.core.output_lpf_enabled
  assert lac.core.output_lpf_tau == (0.07, 0.05, 0.01)


def _drive(lac, VM, frames=400, v=9.0):
  CS = car.CarState.new_message()
  CS.vEgo = v
  params = log.VehicleParameters.new_message()
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
  lac, VM, _ = _controller(monkeypatch)
  outs = _drive(lac, VM)
  assert all(out == 0.0 and not pid_log.active for active, out, _, pid_log in outs if not active)
  assert max(abs(out) for _, out, _, _ in outs) > 0.05
  assert all(abs(out) <= 1.0 and math.isfinite(out) for _, out, _, _ in outs)
  state = lac.starpilot_lateral_state
  assert state.epsFfActive and state.epsFfWeight == 1.0 and state.epsFfR5 != 0.0
  msg = log.Event.new_message(starpilotLateralState=state)   # what controlsd publishes
  assert msg.starpilotLateralState.epsFfWeight == 1.0
  # past the ride-through a disengagement resets it
  for _ in range(lac.ride_through_frames + 1):
    lac.reset()   # controlsd, every inactive frame
    out, _, pid_log = lac.update(False, car.CarState.new_message(), VM, log.VehicleParameters.new_message(), False, 0.0,
                                 False, 0.2, None, None, SimpleNamespace())
    assert out == 0.0 and not pid_log.active
  assert lac.core.ff_weight == 0.0 and lac.core.output == 0.0 and lac.core.pid.i == 0.0


def _engaged_in_a_turn(lac, VM, frames=300, v=13.0):
  CS = car.CarState.new_message()
  CS.vEgo = v
  params = log.VehicleParameters.new_message()
  params.steerRatio, params.stiffnessFactor = 16.0, 1.0
  for k in range(frames):
    CS.steeringAngleDeg = 18.0 + 0.5 * math.sin(k * 0.05)
    lac.update(True, CS, VM, params, False, -0.004, False, 0.2, None, None, SimpleNamespace())
  return CS, params


def test_a_one_frame_fault_does_not_throw_the_turn_away(monkeypatch):
  # a single inactive frame (a one-sample STEER_STATUS fault) sends nothing but keeps the feedforward and integrator
  lac, VM, _ = _controller(monkeypatch)
  CS, params = _engaged_in_a_turn(lac, VM)
  ff, i = lac.core.ff.output, lac.core.pid.i
  assert lac.core.ff_weight == 1.0 and abs(ff) > 0.05
  lac.reset()
  out, _, pid_log = lac.update(False, CS, VM, params, False, -0.004, False, 0.2, None, None, SimpleNamespace())
  assert out == 0.0 and not pid_log.active
  assert lac.core.ff_weight == 1.0 and lac.core.ff.output == pytest.approx(ff, rel=0.05) and lac.core.pid.i == i
  out, _, pid_log = lac.update(True, CS, VM, params, False, -0.004, False, 0.2, None, None, SimpleNamespace())
  assert pid_log.active and lac.core.ff_weight == 1.0 and abs(out) > 0.05


def test_a_long_dropout_still_resets(monkeypatch):
  lac, VM, _ = _controller(monkeypatch)
  CS, params = _engaged_in_a_turn(lac, VM)
  for k in range(lac.ride_through_frames + 1):
    assert lac.core.ff_weight == 1.0, k
    lac.reset()
    lac.update(False, CS, VM, params, False, -0.004, False, 0.2, None, None, SimpleNamespace())
  assert lac.core.ff_weight == 0.0 and lac.core.pid.i == 0.0


def test_target_honours_the_angle_rate_limit(monkeypatch):
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsAngleRateLimit": "100"})
  outs = _drive(lac, VM, frames=120)
  steps = [abs(b[2] - a[2]) for a, b in zip(outs[20:], outs[21:], strict=False)]
  assert max(steps) <= 100.0 * DT_CTRL + 1e-6


# --- per-image profiles ----------------------------------------------------------------------------

# (candidate, modified EPS fwVersion, calibration) for every PTM image
CALIBRATION_CARS = [
  (CAR.HONDA_CLARITY, CLARITY_MODIFIED_FW, eps_cal.CLARITY_TRW_A020),
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C020\x00\x00', eps_cal.CIVIC_TBA_C020),
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C120\x00\x00', eps_cal.CIVIC_TBA_C120),
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TGG,A120\x00\x00', eps_cal.CIVIC_TGG_A120),
  (CAR.HONDA_CIVIC, b'39990-TBA,A030\x00\x00', eps_cal.CIVIC_TBA_A030),
  (CAR.HONDA_CIVIC, b'39990-TEG,A010\x00\x00', eps_cal.CIVIC_TEG_A010),
  (CAR.HONDA_INSIGHT, b'39990-TXM,A040\x00\x00', eps_cal.INSIGHT_TXM_A040),
  (CAR.HONDA_CRV_5G, b'39990-TLA,A040\x00\x00', eps_cal.CRV_TLA_A040),
  (CAR.HONDA_CRV_5G, b'39990-TLA,A220\x00\x00', eps_cal.CRV_TLA_A220),
]
ALL_PROFILES = [p for _, _, p in CALIBRATION_CARS]


@pytest.mark.parametrize("candidate,fw,cal", CALIBRATION_CARS, ids=[p.name for _, _, p in CALIBRATION_CARS])
def test_calibration_matches_the_cars_torque_map_and_is_selected_by_default(candidate, fw, cal):
  CP = _params(fw, candidate)
  # 7.0 keeps the command map in CarControllerParams, not CP.lateralParams
  ccp = CarControllerParams(CP)
  assert list(ccp.STEER_LOOKUP) == [-cal.e4_per_output, 0, cal.e4_per_output] == list(ccp.STEER_LOOKUP_V)
  assert honda_eps.eps_firmware_calibration(CP) is cal


def test_clarity_always_steers_with_the_pminus5_build():
  # P-minus-5 is the Clarity standard; there is no build setting any more
  CP = _params(CLARITY_MODIFIED_FW)
  assert honda_eps.eps_firmware_calibration(CP) is eps_cal.CLARITY_TRW_A020
  assert not hasattr(eps_ff, "CLARITY_P123")


@pytest.mark.parametrize("candidate,fw", [
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA-C020\x00\x00'),   # stock EPS
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TGG,A020\x00\x00'),   # modified, but no PTM build exists
  (CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,A030\x00\x00'),   # a known image on the wrong car
])
def test_cars_without_a_matching_profile_keep_the_pid(candidate, fw):
  assert honda_eps.eps_firmware_calibration(_params(fw, candidate)) is None


def test_a_torque_map_the_profile_does_not_expect_keeps_the_pid(monkeypatch):
  CP = _params(b'39990-TBA,C020\x00\x00', CAR.HONDA_CIVIC_BOSCH)
  assert honda_eps.eps_firmware_calibration(CP) is not None

  class _OtherMap(CarControllerParams):
    def __init__(self, CP):
      super().__init__(CP)
      self.STEER_LOOKUP_V = [-4096, 0, 4096]  # the calibration expects [0, 3840]
  monkeypatch.setattr(honda_eps, "CarControllerParams", _OtherMap)
  assert honda_eps.eps_firmware_calibration(CP) is None


def test_clarity_trw_a020_profile_is_the_validated_build():
  # the constants routes 352/353 and the closed-loop replay were validated with; R6 is the angle-scaled centre value
  # re-measured on routes 363/365/366/369, the scale word on routes 35e/360/361
  cal = eps_cal.CLARITY_TRW_A020
  assert cal.kp_v == (117, 148, 184, 220, 245, 257, 263, 265, 265) and cal.r5_per_key == 18.04
  assert cal.r6_per_deg_s == eps_cal.CLARITY_TRW_A020_R6_CENTRE == -122.0 and cal.scale_q8 == 256.0
  assert cal.r6_angle_bp is not None and cal.r6_angle_gain[0] == 1.0 and cal.r6_angle_gain[-1] > 1.15
  assert cal.load == eps_cal.CLARITY_TRW_A020_LOAD and cal.e4_per_output == 3840.0
  assert (cal.p_scale, cal.i_scale) == ((1.25, 1.00, 1.25), (0.70, 0.95, 0.35))


def test_nidec_civics_carry_the_teg_measurements():
  # both Nidec images take the column load, R6 (centre and angle shape) and command delay measured on the TEG-A010
  # telemetry routes; on rev b the A030's rows 0-5 are the TEG's row 3, and it is the same Nidec Civic with the same A
  # table, so it is the TEG's calibration, rack map included
  for cal in (eps_cal.CIVIC_TBA_A030, eps_cal.CIVIC_TEG_A010):
    assert cal.load == eps_cal.CIVIC_TEG_A010_LOAD and cal.e4_per_output == 3840.0
  teg = eps_cal.CIVIC_TEG_A010
  assert teg.r6_angle_bp == eps_cal.CIVIC_TEG_A010_R6_BP and teg.r6_angle_gain == eps_cal.CIVIC_TEG_A010_R6_GAIN
  # R6 is the C120 A table's, computed; the telemetry agrees once railed frames are left out (see below)
  assert (teg.r6_per_deg_s, teg.r6_angle_gain) == (eps_cal.CIVIC_TBA_C120_R6_CENTRE, eps_cal.CIVIC_TBA_C120_R6_GAIN)
  a030 = eps_cal.CIVIC_TBA_A030
  assert dataclasses.replace(a030, name=teg.name) == teg and a030.rack is rack.CIVIC_TEG_A010_RACK
  # the TEG owner's car runs row 3 (TEGA2), measured on its telemetry; the corrected (rev b) image's row 3 carries the
  # Clarity's R5 per key on that row's axis and the Clarity's P knots
  teg = eps_cal.CIVIC_TEG_A010
  assert teg.r5_key_bp == (0, 222, 333, 495, 656, 887, 1108, 1552, 1774) and teg.kp_key_bp == eps_cal.CLARITY_TRW_A020.kp_key_bp
  assert teg.r5_v == (0, 4000, 6000, 8937, 11838, 16000, 20000, 28000, 32000) and teg.kp_v == eps_cal.CLARITY_TRW_A020.kp_v
  assert teg.r6_per_deg_s == eps_cal.CIVIC_TEG_A010_R6_CENTRE and teg.rack is rack.CIVIC_TEG_A010_RACK
  # the Nidec column is stiffer than the C020's at low speed (1.29x at 3 m/s, 1.07x at 8) and alike by 15 m/s
  teg, c020 = eps_cal.CIVIC_TEG_A010_LOAD, eps_cal.CIVIC_TBA_C020_LOAD
  for v, lo, hi in ((3.0, 1.2, 1.4), (8.0, 1.0, 1.15), (15.0, 0.9, 1.1)):
    for load in (teg, c020):
      assert load.k0 + load.k1 * v ** 2 < 0.0
    assert lo < (teg.k0 + teg.k1 * v ** 2) / (c020.k0 + c020.k1 * v ** 2) < hi


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


def test_c020_full_output_lands_on_the_key_clamp():
  # route 00000284 (sent 4096, the 08-05 build) put the rail at row 1's key clamp 1663 (R5 28497 there on TargetMap-D).
  # On rev b row 1 that key is 28127; at 3840 full output decodes to key 1662, one key (17 counts) below it, and 4096
  # still clamps there.
  assert abs(eps_ff.r5_from_output(1.0, 20.0, eps_cal.CIVIC_TBA_C020)) == pytest.approx(28110, abs=1)
  assert abs(eps_ff.r5_from_output(4096 / 3840, 20.0, eps_cal.CIVIC_TBA_C020)) == pytest.approx(28127, abs=1)
  # and its envelope takes the ceiling to key 1108 from 160 km/h
  assert eps_cal.CIVIC_TBA_C020.key_ceiling(170 / 3.6) == 1108


@pytest.mark.parametrize("candidate,fw,cal", CALIBRATION_CARS, ids=[p.name for _, _, p in CALIBRATION_CARS])
def test_every_ptm_car_steers_with_its_own_calibration(monkeypatch, candidate, fw, cal):
  monkeypatch.setattr(honda_eps, "Params", lambda: _Params())
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
  assert eps_cal.CRV_TLA_A040.r6_per_deg_s == eps_cal.CRV_TLA_A040_R6_CENTRE and eps_cal.CRV_TLA_A040.r6_angle_gain == eps_cal.CRV_TLA_A040_R6_GAIN
  # the owner's single V5 fit (-138.4 against 0x14A) sits inside the curve the A table gives
  assert eps_ff.firmware_r6(1.0, 0.0, eps_cal.CRV_TLA_A040) > -138.4 > eps_ff.firmware_r6(1.0, 180.0, eps_cal.CRV_TLA_A040)
  assert eps_cal.CRV_TLA_A040.load is eps_cal.CRV_TLA_A040_LOAD
  assert -0.25 < eps_cal.CRV_TLA_A040_LOAD.k1 < -0.10 and eps_cal.CRV_TLA_A040_LOAD.kroll < 0.0


def test_crv_a220_reads_its_own_command_axis_and_predicts_r6_from_the_a040():
  a220, a040 = eps_cal.CRV_TLA_A220, eps_cal.CRV_TLA_A040
  # selected by the fw string in either spelling, and not on another car
  assert eps_cal.select_eps_firmware_calibration("HONDA_CRV_5G", "39990-TLA-A220") is a220
  assert eps_cal.select_eps_firmware_calibration("HONDA_CIVIC", "39990-TLA-A220") is None
  # command axis read from the A220 image (row 0, 0x11AE0), much more compressed than the A040's
  assert a220.r5_key_bp == (0, 161, 222, 322, 409, 534, 696, 998, 1663) and a220.key_clamp == 1774
  # the corrected build's values are the Clarity's curve on that axis: the Clarity's R5 at key x 3840/4096
  clarity = eps_cal.CLARITY_TRW_A020
  for key, r5 in zip(a220.r5_key_bp, a220.r5_v, strict=True):
    assert r5 == round(float(np.interp(key * 3840 / 4096, clarity.r5_key_bp, clarity.r5_v)))
  # P: the Clarity's own knots moved to the A220's key domain (x 4096/3840), with the Clarity's values
  assert a220.kp_key_bp == tuple(round(k * 4096 / 3840) for k in clarity.kp_key_bp) and a220.kp_v == clarity.kp_v
  # the envelope is the A220's own (1330 from 150 km/h, not flat)
  assert a220.key_ceiling(120 / 3.6) == 1774 and a220.key_ceiling(160 / 3.6) == 1330
  assert a040.key_ceiling(160 / 3.6) == 1774
  # R6 is predicted from the A040 (shared 3121 / A-centre 16783 / NORM 1650), not measured; load is the CR-V's
  assert a220.r6_per_deg_s == a040.r6_per_deg_s == eps_cal.CRV_TLA_A040_R6_CENTRE and a220.r6_angle_gain == a040.r6_angle_gain
  assert a220.load is eps_cal.CRV_TLA_A040_LOAD and a220.e4_per_output == 4096.0
  assert (a220.p_scale, a220.i_scale) == (a040.p_scale, a040.i_scale) == (eps_cal.CRV_TLA_A040_P_SCALE, eps_cal.CRV_TLA_A040_I_SCALE) == ((1.0,) * 3,) * 2



def test_crv_a220_firmware_output_matches_the_clarity():
  # the point of the corrected build: same firmware output per unit output as the Clarity, everywhere. The 10-06 build
  # (TargetMap-D pasted onto this axis) ran 0.71x below output ~0.09 and up to 1.98x above it.
  a220, clarity = eps_cal.CRV_TLA_A220, eps_cal.CLARITY_TRW_A020
  def out(cal, u):
    return abs(eps_ff.firmware_output(eps_ff.r5_from_output(u, 10.0, cal), 0.0, cal))
  for u in (0.03, 0.05, 0.1, 0.15, 0.2, 0.3, 0.45, 0.6, 0.8):
    assert out(a220, u) / out(clarity, u) == pytest.approx(1.0, abs=0.03), u
  pasted = dataclasses.replace(a220, r5_v=eps_cal.TARGET_MAP_D_R5, kp_v=eps_cal.P_ROW_PMINUS5)
  assert out(pasted, 0.05) / out(clarity, 0.05) < 0.8 and out(pasted, 0.3) / out(clarity, 0.3) > 1.7


def test_command_delay_hands_over_the_value_issued_that_long_ago():
  d = honda_eps.CommandDelay(DT_CTRL, 0.2)
  outs = [d.update(float(k), 0.12) for k in range(40)]
  assert outs[30] == pytest.approx(18.0)
  assert outs[0] == 0.0 and outs[5] == 0.0              # not enough history yet: the oldest value
  half = honda_eps.CommandDelay(DT_CTRL, 0.2)
  assert [half.update(float(k), 0.125) for k in range(40)][30] == pytest.approx(17.5)


def test_command_delay_moves_from_its_town_to_its_highway_value():
  cal = eps_cal.CLARITY_TRW_A020
  assert eps_ff.command_delay(cal, 0.0) == eps_ff.command_delay(cal, 10.0) == pytest.approx(0.12)
  assert eps_ff.command_delay(cal, 12.5) == pytest.approx(0.11)
  assert eps_ff.command_delay(cal, 15.0) == eps_ff.command_delay(cal, 30.0) == pytest.approx(0.10)
  assert eps_ff.command_delay(eps_cal.INSIGHT_TXM_A040, 30.0) == 0.0
  assert honda_eps.CommandDelay(DT_CTRL, 0.2).update(3.0, 0.0) == 3.0


def test_the_civics_hold_their_command_delay_on_the_highway():
  # they ran as early above 15 m/s as in town (TEG routes 12e-13d, C020 route 380); the Clarity 0.10-0.14 s (routes
  # 3f1 / 3f5), so it takes 0.10; the Insight needed less than the default there, so it fades to none
  highway = {"clarity_trw_a020": 0.10}
  for _, cal in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values():
    civic = cal.name.startswith("civic_")
    assert cal.cmd_delay_highway_s == (cal.cmd_delay_s if civic else highway.get(cal.name, 0.0)), cal.name
    if civic:
      assert [eps_ff.command_delay(cal, v) for v in (0.0, 12.5, 15.0, 30.0)] == pytest.approx([0.15] * 4), cal.name


def test_every_vehicle_has_its_own_command_delay():
  delays = {cal.name: cal.cmd_delay_s for _, cal in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values()}
  measured = {"clarity_trw_a020": 0.12, "civic_tba_c020": 0.15, "civic_teg_a010": 0.15}
  same_chassis_as_c020 = {"civic_tba_c120": 0.15, "civic_tgg_a120": 0.15}
  inferred = {"insight_txm_a040": 0.15, "civic_tba_a030": 0.15}  # the A030: the TEG's (same Nidec image family)
  for name, delay in delays.items():
    assert delay == {**measured, **same_chassis_as_c020, **inferred}.get(name, eps_ff.CMD_DELAY_DEFAULT_S), name
  # the default is the smaller measured value, so an unmeasured car cannot be pushed late
  assert eps_ff.CMD_DELAY_DEFAULT_S == min(measured.values())


@pytest.mark.parametrize("v, late_frames", [(8.0, 12), (20.0, 10)])  # 0.12 s in town, 0.10 s on the highway
def test_target_follows_the_curvature_one_command_delay_late(monkeypatch, v, late_frames):
  lac, VM, _ = _controller(monkeypatch)
  CS = car.CarState.new_message()
  CS.vEgo = v
  params = log.VehicleParameters.new_message()
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
  return CP, honda_eps.eps_firmware_calibration(CP)


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


@pytest.mark.parametrize("candidate,fw", [(CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C120\x00\x00'),
                                          (CAR.HONDA_CRV_5G, b'39990-TLA,A040\x00\x00')])
def test_cars_without_a_yaw_fit_steer_on_a_spec_rack_map(candidate, fw):
  # see test_honda_eps_spec_plant.py for how well the spec map predicts the measured ones
  CP, cal = _ptm_cp(candidate, fw)
  assert eps_cal.provenance(cal)["rack"].startswith("spec") and honda_eps.get_rack_map(CP, cal) is not None


@pytest.mark.parametrize("firmware_vgr", ["0", "1"])
def test_a_rack_map_is_the_geometry_whatever_the_firmware_vgr_setting(monkeypatch, firmware_vgr):
  lac, VM, _ = _controller(monkeypatch, {"HondaEpsFirmwareVgr": firmware_vgr})
  for k in (-0.05, -0.01, 0.002, 0.03):
    assert lac._desired_angle_no_offset(VM, 8.0, 0.0, k) == pytest.approx(lac.rack_map.angle_from_curvature(k, 8.0, 0.0))


@pytest.mark.parametrize("v", [0.0, 7.0, 15.0, 30.0])
@pytest.mark.parametrize("roll", [0.0, 0.03, -0.03])
def test_rack_map_round_trips(v, roll):
  rack_map = _rack_map()
  for angle in (-430.0, -154.0, -40.0, -3.0, 0.0, 2.0, 25.0, 90.0, 300.0):
    curvature = rack_map.curvature_from_angle(angle, v, roll)
    assert rack_map.angle_from_curvature(curvature, v, roll) == pytest.approx(angle, abs=1e-3)


@pytest.mark.parametrize("v", [3.0, 15.0])
def test_rack_map_reaches_lock_past_table_a(v):
  # the Insight's Table A ends at 430.5 deg, its lock is 457 deg: past the last knot the firmware holds its last
  # divisor, so the map keeps going (it used to clamp at 430.5, so no curvature could ask for more)
  inv = get_honda_vgr_inverse(HondaFlags.VGR_INSIGHT_TXM_A040)
  rack_map = rack.HondaEpsRackMap(2.7, inv, eps_cal.INSIGHT_TXM_A040.rack)
  end = inv[1][-1]
  for angle in (440.0, 457.0, -457.0):
    assert rack_map.angle_from_curvature(rack_map.curvature_from_angle(angle, v, 0.0), v, 0.0) == pytest.approx(angle, abs=1e-6)
  k_end, k_lock = (abs(rack_map.curvature_from_angle(a, v, 0.0)) for a in (end, 457.0))
  assert k_lock == pytest.approx(k_end * 457.0 / end)  # the path grows with the angle at the last divisor and ratio
  assert abs(rack_map.curvature_from_angle(end - 1e-6, v, 0.0)) == pytest.approx(k_end, rel=1e-6)  # continuous at the knot


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
  lac, VM, _ = _controller(monkeypatch)
  VM.update_params(1.0, 17.3)   # a paramsd ratio must no longer change the target
  for curvature, v, roll in ((0.06, 7.0, 0.0), (-0.002, 30.0, 0.02), (0.0, 12.0, 0.0)):
    assert lac._desired_angle_no_offset(VM, v, roll, curvature) == pytest.approx(
      lac.rack_map.angle_from_curvature(curvature, v, roll))


def test_rack_map_asks_less_wheel_than_the_paramsd_ratio_in_tight_turns(monkeypatch):
  # the city over-steer: paramsd's single ratio over VGR asks 3.5-6% too much wheel at 100-250 deg
  lac, VM, _ = _controller(monkeypatch)
  VM.update_params(1.0, 17.3)
  for curvature in (0.04, 0.06, 0.1):
    old = vgr_linear_to_physical(math.degrees(VM.get_steer_from_curvature(-curvature, 7.0, 0.0)),
                                 get_honda_vgr_inverse(HondaFlags.VGR_CLARITY_TRW_A020))
    new = lac.rack_map.angle_from_curvature(curvature, 7.0, 0.0)
    assert 0.93 < new / old < 0.97


def test_insight_carries_its_own_measured_load_on_row_0():
  cal = eps_cal.INSIGHT_TXM_A040
  assert cal.load is eps_cal.INSIGHT_TXM_A040_LOAD and cal.load != eps_cal.CIVIC_TBA_C020_LOAD
  assert cal.r5_key_bp == (0, 111, 222, 333, 443, 665, 887, 1108, 1663)  # row 0, every Insight build and variant
  # the corrected PTM: the Clarity's own map and P table, so the firmware law is the Clarity's
  assert cal.r5_v == eps_cal.CLARITY_TRW_A020_R5 and cal.key_clamp == 1663
  clarity = eps_cal.CLARITY_TRW_A020
  assert (cal.kp_key_bp, cal.kp_v) == (clarity.kp_key_bp, clarity.kp_v)
  def out(c, u):
    return abs(eps_ff.firmware_output(eps_ff.r5_from_output(u, 10.0, c), 0.0, c))
  for u in (0.03, 0.05, 0.1, 0.15, 0.2, 0.3, 0.45, 0.6, 0.8, 1.0):
    assert out(cal, u) / out(clarity, u) == pytest.approx(1.0, abs=0.01), u
  assert cal.e4_per_output == 3840.0 and cal.r6_per_deg_s == eps_cal.INSIGHT_TXM_A040_R6_CENTRE and cal.r6_angle_gain == eps_cal.INSIGHT_TXM_A040_R6_GAIN
  # the fitted column is lighter than the C020's at speed, which the carried-over load over-asked
  insight = eps_ff.column_load(10., 0., 25., 0., load=eps_cal.INSIGHT_TXM_A040_LOAD)
  assert abs(insight) < abs(eps_ff.column_load(10., 0., 25., 0., load=eps_cal.CIVIC_TBA_C020_LOAD))


@pytest.mark.parametrize("cal", [c for c in ALL_PROFILES if not c.name.startswith("clarity")], ids=lambda c: c.name)
def test_every_image_has_angle_dependent_r6(cal):
  # R6 is the pre-table column rate; per published deg/s it grows with the A table's slope on every image
  assert cal.r6_angle_bp is not None and cal.r6_angle_gain[0] == 1.0
  assert eps_ff.firmware_r6(1.0, 180.0, cal) < eps_ff.firmware_r6(1.0, 0.0, cal) < 0.0
  assert eps_ff.firmware_r6(1.0, -180.0, cal) == eps_ff.firmware_r6(1.0, 180.0, cal)


# Telemetry R6 per published deg/s on unrailed frames (10-150 deg/s, |R6| < 30000), by |angle| band (median angle
# ~7/28/65/115/190/310 deg), against a 0.06 s derivative of carState's angle, 2026-10-18: Clarity 363/365/369 (R6 =
# 0x6A3 w3), C020 287/289/294 (0x6A2 w0, bus 1), TEG-A010 133/134/137/13d (0x6A1 w1).
R6_TELEMETRY_ANGLES = (7.0, 28.0, 65.0, 115.0, 190.0, 310.0)
R6_TELEMETRY = {
  "clarity_trw_a020": (-123.3, (1.0, 1.005, 1.072, 1.177, 1.185, 1.197), 0.015),
  "civic_tba_c020": (-158.4, (1.0, 1.003, 1.062, 1.168, 1.181, 1.187), 0.035),
  "civic_teg_a010": (-160.9, (1.0, 0.978, 1.064, 1.117, 1.202, 1.162), 0.03),
}


@pytest.mark.parametrize("name", R6_TELEMETRY)
def test_computed_r6_matches_unrailed_telemetry(name):
  cal = next(c for _, c in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values() if c.name == name)
  centre, shape, tol = R6_TELEMETRY[name]
  for angle, gain in zip(R6_TELEMETRY_ANGLES, shape, strict=True):
    assert eps_ff.firmware_r6(1.0, angle, cal) == pytest.approx(centre * gain, rel=tol)


@pytest.mark.parametrize("name, profile", [
  ("clarity_trw_a020", HONDA_VGR_CLARITY_TRW_A020), ("civic_tba_c020", HONDA_VGR_CIVIC_TBA_C020),
  ("civic_tgg_a120", HONDA_VGR_CIVIC_TBA_C020), ("civic_tba_c120", HONDA_VGR_CIVIC_TBA_C120),
  ("civic_tba_a030", HONDA_VGR_CIVIC_TBA_C120), ("civic_teg_a010", HONDA_VGR_CIVIC_TBA_C120),
  ("insight_txm_a040", HONDA_VGR_INSIGHT_TXM_A040), ("crv_tla_a040", HONDA_VGR_CRV_TLA_A040),
  ("crv_tla_a220", HONDA_VGR_CRV_TLA_A040),
])
def test_every_calibration_takes_its_a_tables_computed_r6(name, profile):
  cal = next(c for _, c in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values() if c.name == name)
  centre, bp, gain = eps_ff.computed_r6(profile)
  assert (cal.r6_per_deg_s, tuple(cal.r6_angle_bp), tuple(cal.r6_angle_gain)) == (centre, bp, gain)
  assert centre == pytest.approx(-122.0 * HONDA_VGR_CENTRE_DIVISOR_BY_PROFILE[profile] / 16384, abs=0.01)


@pytest.mark.parametrize("cal", [c for _, c in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values()], ids=lambda c: c.name)
def test_r6_rails_at_the_firmware_clamp(cal):
  # 0x1380C clamps R6 at +/-32765 in every image: from ~185 deg/s on the Civics, ~260 on the Clarity
  for angle in (0.0, 90.0, 300.0):
    assert eps_ff.firmware_r6(1000.0, angle, cal) == -eps_ff.R6_CLAMP
    assert eps_ff.firmware_r6(-1000.0, angle, cal) == eps_ff.R6_CLAMP
    rail = eps_ff.R6_CLAMP / abs(eps_ff.firmware_r6(1.0, angle, cal))
    assert abs(eps_ff.firmware_r6(0.99 * rail, angle, cal)) < eps_ff.R6_CLAMP
    # past the rail the law no longer depends on the rate
    assert eps_ff.firmware_output(9000.0, 1.5 * rail, cal, angle) == eps_ff.firmware_output(9000.0, 3.0 * rail, cal, angle)
    assert eps_ff.r5_for_motion(500.0, 1.5 * rail, cal, angle_deg=angle) == pytest.approx(
      eps_ff.r5_for_motion(500.0, 3.0 * rail, cal, angle_deg=angle))


def test_a_table_r6_model_matches_the_clarity_and_the_c020_centre():
  # the A-table model, centre scaled by the divisor ratio, against telemetry: Clarity -121.5 at 0-15 deg,
  # C020 -153.2 at 0-15 deg (20647 / 16384 x -122 = -153.7)
  assert eps_cal.CLARITY_TRW_A020_R6_CENTRE * 20647 / 16384 == pytest.approx(eps_cal.CIVIC_TBA_C020_R6_CENTRE, abs=0.01)
  assert eps_cal.CIVIC_TBA_C120_R6_CENTRE == pytest.approx(-122.0 * 20972 / 16384, abs=0.01)
  assert eps_cal.INSIGHT_TXM_A040_R6_CENTRE == pytest.approx(-122.0 * 17613 / 16384, abs=0.01)
  assert eps_cal.CRV_TLA_A040_R6_CENTRE == pytest.approx(-122.0 * 16783 / 16384, abs=0.01)


@pytest.mark.parametrize("name", [cal.name for _, cal in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values()])
def test_every_calibration_says_where_every_value_came_from(name):
  cal = next(c for _, c in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values() if c.name == name)
  prov = eps_cal.provenance(cal)
  assert set(prov) == set(eps_cal.PROVENANCE_FIELDS)
  for key, value in prov.items():
    assert value.split(':')[0].split(' ')[0] in eps_cal.PROVENANCE_KINDS, (name, key, value)
  # consistency with the calibration itself
  assert (prov["rack"] == "none") == (cal.rack is None)
  if cal.cmd_delay_s == eps_ff.CMD_DELAY_DEFAULT_S and not prov["cmd_delay"].startswith("measured"):
    assert prov["cmd_delay"].startswith(("default", "inferred")), name
  assert eps_cal.provenance_summary(cal)


@pytest.mark.parametrize("u", np.linspace(.02, 1.0, 50))
def test_teg_rev_b_asks_the_clarity_r5_and_kp(u):
  # the PTM rule at the TEG's 3840 E4 per unit: the same output gives the Clarity's R5 and Kp, rows 2 and 3 alike
  teg, clarity = eps_cal.CIVIC_TEG_A010, eps_cal.CLARITY_TRW_A020
  key = min(abs(eps_ff.command_key(-u * 3840.0)), 1663)
  r5_teg, r5_cla = float(np.interp(key, teg.r5_key_bp, teg.r5_v)), float(np.interp(key, clarity.r5_key_bp, clarity.r5_v))
  assert r5_teg == pytest.approx(r5_cla, rel=.005, abs=2.)
  row2 = float(np.interp(key, (0, 111, 222, 333, 499, 665, 887, 1108, 1774), (0, 2000, 4000, 6000, 9009, 12000, 16000, 20000, 32000)))
  assert row2 == pytest.approx(r5_teg, rel=.005, abs=2.)
  assert eps_ff.firmware_kp(r5_teg, teg) == pytest.approx(eps_ff.firmware_kp(r5_cla, clarity), rel=.005)


REV_B = {  # each calibration's modelled row in the corrected PTM build (KB PTM_FIX_FAMILY_20261016/out/<car>/plan.json)
  "civic_tba_a030": ((0, 222, 333, 495, 656, 887, 1108, 1552, 1774), (0, 4000, 6000, 8937, 11838, 16000, 20000, 28000, 32000)),
  "civic_tba_c120": ((0, 103, 263, 459, 660, 861, 1111, 1549, 1774), (0, 1856, 4739, 8288, 11910, 15532, 20054, 27946, 32000)),
  "civic_tgg_a120": ((0, 103, 263, 459, 660, 862, 1111, 1549, 1774), (0, 1740, 4443, 7769, 11167, 14579, 18798, 26202, 30002)),
  "crv_tla_a040": ((0, 219, 443, 662, 887, 1108, 1330, 1552, 1663), (0, 3699, 7497, 11200, 15001, 18747, 22502, 26252, 28127)),
}


BUILT_FOR_E4 = {"civic_tgg_a120": 4096.0, "crv_tla_a040": 4096.0}


@pytest.mark.parametrize("name", sorted(REV_B))
def test_held_cars_model_their_corrected_ptm_row_and_ask_the_clarity_command(name):
  cal = next(c for _, c in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values() if c.name == name)
  assert (cal.r5_key_bp, cal.r5_v) == REV_B[name]
  built = BUILT_FOR_E4.get(name, 3840.0)  # the E4 per unit the corrected image's rows and P knots were set for
  assert cal.kp_key_bp == tuple(round(k * built / 3840.0) for k in eps_cal.CLARITY_TRW_A020_P_KEYS) and cal.kp_v == eps_cal.P_ROW_PMINUS5
  clarity = eps_cal.CLARITY_TRW_A020
  # PTM rule: the E4 the image was built for asks for the Clarity's R5 and Kp within 0.6% (key truncation and the 4096
  # images' knots). An image sent less than it was built for (the TGG-A120: built 4096, sent 3840) asks it at a
  # proportionally larger output.
  for u in np.linspace(.05, .9, 35):
    mine = eps_ff.r5_from_output(u * built / cal.e4_per_output, 20.0, cal)
    ref = eps_ff.r5_from_output(u, 20.0, clarity)
    assert mine == pytest.approx(ref, rel=.006, abs=40.)
    assert eps_ff.firmware_kp(mine, cal) == pytest.approx(eps_ff.firmware_kp(ref, clarity), rel=.006)


def test_every_ptm_calibration_names_its_required_corrected_build():
  names = {c.name for _, c in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values()}
  # the Clarity is the reference
  assert set(eps_cal.REQUIRED_PTM_RWD) == names - {"clarity_trw_a020"}
  assert all(len(sha) == 8 and int(sha, 16) >= 0 for sha in eps_cal.REQUIRED_PTM_RWD.values())


def test_every_calibration_has_a_rack_map_and_the_controller_requires_one(monkeypatch):
  assert all(cal.rack is not None for _, cal in eps_cal.EPS_FIRMWARE_CALIBRATIONS.values())
  CP = _params(CLARITY_MODIFIED_FW)
  assert honda_eps.eps_firmware_calibration(CP) is eps_cal.CLARITY_TRW_A020
  CP.flags = int(CP.flags) & ~int(HondaFlags.VGR_CLARITY_TRW_A020)   # no firmware A table: no geometry, so the modified PID
  assert honda_eps.eps_firmware_calibration(CP) is None


def test_honda_eps_cars_keep_vfns_model_smoothing():
  assert honda_eps.lateral_smooth_seconds(_params(CLARITY_MODIFIED_FW), 0.0) == 0.1
  assert honda_eps.lateral_smooth_seconds(_params(CLARITY_STOCK_FW), 0.0) == 0.0


def test_model_action_ramps_across_the_frame():
  from openpilot.common.realtime import DT_CTRL, DT_MDL
  ramp = honda_eps.ModelActionRamp()
  assert ramp.update(0.01, True, True) == 0.0         # a new frame starts from where the output is
  outputs = [ramp.update(0.01, False, True) for _ in range(round(DT_MDL / DT_CTRL) + 2)]
  assert outputs[0] == pytest.approx(0.01 * DT_CTRL / DT_MDL)
  assert all(b >= a for a, b in zip(outputs, outputs[1:])) and outputs[-1] == pytest.approx(0.01)
  ramp.update(0.005, False, True)                     # between frames the held target doesn't move
  assert ramp.output == pytest.approx(0.01)
  for _ in range(2):
    ramp.update(-0.01, True, True) if _ == 0 else ramp.update(-0.01, False, True)
  assert ramp.output == pytest.approx(0.01 - 0.02 * DT_CTRL / DT_MDL)   # mid-ramp, not a step
  assert ramp.update(0.003, False, False) == 0.003    # inactive follows the input exactly
  assert ramp.update(0.004, True, True) == 0.003
