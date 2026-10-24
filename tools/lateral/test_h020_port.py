"""Behavioral checks of the H020 rev-b port against res's real CarParams/PID-log schemas, interface and setup code."""
import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest
from cereal import car, custom, log
from collections import defaultdict
from opendbc.car import Bus, structs
from opendbc.car.honda import hondacan
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR, CarControllerParams
from opendbc.sunnypilot.car.honda import h020_ptm as gate
from opendbc.sunnypilot.car.honda.fingerprints_ext import FW_VERSIONS_EXT
from openpilot.selfdrive.controls.lib import honda_eps_firmware_ff as ff
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import H020, R6_CENTRE, EPS_FIRMWARE_CALIBRATIONS
from openpilot.selfdrive.controls.lib.honda_eps_h020_geometry import H020_VGR_INVERSE, A_X, A_Y
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import HondaEpsRackMap
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import LatControlHondaEps, use_honda_eps_controller, warn_if_h020_tune_replaced

ROOT = Path(__file__).resolve().parents[2]
PTM_ID = b"39990-TEA,H020\0\0"
FPS = {i: {} for i in range(4)}


def fw_list(version):
  return [car.CarParams.CarFw.new_message(ecu="eps", address=0x18da30f1, fwVersion=version)]


def real_cp(version=PTM_ID, candidate=CAR.HONDA_CIVIC_BOSCH):
  """CarParams exactly as res builds them (get_params, get_params_sp, then card's carFw/carFingerprint)."""
  fw = fw_list(version)
  c = CarInterface.get_params(candidate, FPS, fw, False, False, False)
  CarInterface.get_params_sp(c, candidate, FPS, fw, False, False, False)
  c.carFw = fw
  return c


def cp_dict(c):
  d = c.to_dict()
  d.pop("carFw", None)
  return d


def sensors(**kw):
  base = dict(steeringAngleDeg=0., steeringRateDeg=0., steeringTorque=0., vEgo=15., steeringPressed=False)
  return NS(**{**base, **kw})


def only_h020_eps_id():
  assert gate.EPS_ID == b"39990-TEA,H020"


def test_fingerprint_lists_only_rev_b():
  eps = FW_VERSIONS_EXT[CAR.HONDA_CIVIC_BOSCH][(car.CarParams.Ecu.eps, 0x18da30f1, None)]
  assert b"39990-TEA,H020\x00\x00" in eps
  assert b"39990-TEA-H020\x00\x00" not in eps  # the stock string is not added


def test_real_interface_applies_h020_only_to_rev_b_on_civic_bosch():
  c = real_cp()
  assert (list(c.lateralParams.torqueBP), list(c.lateralParams.torqueV)) == ([0, 3840], [0, 3840])
  assert c.lateralTuning.which() == "pid" and c.lateralTuning.pid.kf == 0.0
  assert list(c.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
  assert list(c.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])
  assert use_honda_eps_controller(c)


@pytest.mark.parametrize("version", [b"39990-TEA-H020\0\0", b"39990-TEA,H02B\0\0", b"39990-TEA-H02B\0\0", b"39990-TEA,H020-x\0",
                                     b"39990-TGG,A120\0\0", b"39990-TBA,C020\0\0"])
def test_other_firmware_keeps_res_tune(version):
  # same punctuation (comma = modified EPS) on an unrelated part number gives res's own tune for that case
  twin = version.replace(b"H020", b"H021").replace(b"H02B", b"H021")
  other = real_cp(version)
  if b"TEA" in version:
    assert cp_dict(other) == cp_dict(real_cp(twin))
  assert not use_honda_eps_controller(other)


def test_other_platform_with_rev_b_unchanged():
  assert cp_dict(real_cp(PTM_ID, CAR.HONDA_CIVIC)) == cp_dict(real_cp(b"39990-TEA,H021\0\0", CAR.HONDA_CIVIC))


def test_conflicting_or_missing_eps_not_matched():
  c = real_cp()
  assert not gate.is_h020([])
  c.carFw = fw_list(PTM_ID) + fw_list(b"39990-TBA,C020\0\0")
  assert not gate.is_h020(c.carFw) and not use_honda_eps_controller(c)


def test_map_must_stay_linear():
  c = real_cp()
  c.lateralParams.torqueV = [0, 3000]
  assert not use_honda_eps_controller(c)


def test_torque_tune_replacement_is_selected_away_and_logged():
  # setup_interfaces (sunnypilot/selfdrive/car/interfaces.py:_initialize_torque_lateral_control) runs after get_params_sp
  # and, with EnforceTorqueControl or NNLC on, does exactly this call. (The module needs the native Params binding.)
  c = real_cp()
  CarInterface.configure_torque_tune(c.carFingerprint, c.lateralTuning)
  assert c.lateralTuning.which() == "torque"
  assert not use_honda_eps_controller(c)
  logged = []
  warn_if_h020_tune_replaced(c, NS(error=logged.append))
  assert logged and "not selected" in logged[0]


def test_warning_silent_for_unrelated_and_selected():
  logged = []
  warn_if_h020_tune_replaced(real_cp(), NS(error=logged.append))
  warn_if_h020_tune_replaced(real_cp(b"39990-TEA,H021\0\0"), NS(error=logged.append))
  assert not logged


def _controlsd_branch(cpm):
  """Execute controlsd's real lateral-controller selection branch with a stub self."""
  tree = ast.parse((ROOT / "selfdrive/controls/controlsd.py").read_text())
  init = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "Controls"
              for n in c.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
  branch = next(n for n in init.body if isinstance(n, ast.If) and "steerControlType" in ast.dump(n.test))
  mod = ast.fix_missing_locations(ast.Module([branch], []))
  made = []
  ns = {"car": car, "LatControlAngle": lambda *a: made.append("angle"), "LatControlHondaEps": lambda *a: made.append("honda_eps"),
        "LatControlPID": lambda *a: made.append("pid"), "LatControlTorque": lambda *a: made.append("torque"),
        "use_honda_eps_controller": use_honda_eps_controller, "warn_if_h020_tune_replaced": warn_if_h020_tune_replaced,
        "cloudlog": NS(error=lambda m: made.append("log"))}
  exec(compile(mod, "controlsd", "exec"), ns, {"self": NS(CP=cpm, CP_SP=None, CI=None)})
  return made


def test_controlsd_selects_honda_eps_only_for_h020_rev_b():
  assert _controlsd_branch(real_cp()) == ["honda_eps"]
  assert _controlsd_branch(real_cp(b"39990-TEA,H021\0\0")) == ["pid"]
  assert _controlsd_branch(real_cp(b"39990-TEA-H020\0\0")) == ["pid"]


def test_controlsd_logs_when_h020_tune_replaced():
  c = real_cp()
  CarInterface.configure_torque_tune(c.carFingerprint, c.lateralTuning)
  assert _controlsd_branch(c) == ["log", "torque"]


def test_controlsd_logs_when_h020_map_replaced_on_pid_tune():
  c = real_cp()
  c.lateralParams.torqueV = [0, 3000]
  assert _controlsd_branch(c) == ["log", "pid"]


def test_e4_scaling_matches_the_calibration():
  c = real_cp()
  p = CarControllerParams(c)
  assert p.STEER_MAX == 3840 == H020.e4_per_output
  for u in (-1.0, -0.4, 0.0, 0.25, 1.0):
    e4 = int(np.interp(-u * p.STEER_MAX, p.STEER_LOOKUP_BP, p.STEER_LOOKUP_V))
    assert e4 == int(-u * 3840)
    r5 = ff.r5_from_output(u, 15.0, H020)
    assert (r5 == 0) if e4 == 0 else (np.sign(r5) == np.sign(e4))
  assert ff.command_key(-3840) == -1662 and abs(ff.command_key(3840)) <= H020.key_clamp  # full output is inside the 1663 clamp


def test_calibration_matches_firmware_evidence_json():
  e = json.loads((ROOT / "tools/lateral/h020_firmware_evidence.json").read_text())
  assert H020.r5_key_bp == tuple(e["r5_key_bp"]) and H020.r5_v == tuple(e["r5_v"])
  assert H020.kp_key_bp == tuple(e["kp_key_bp"]) and H020.kp_v == tuple(e["kp_v"])
  assert H020.envelope_bp == tuple(e["envelope_bp"]) and H020.envelope_v == tuple(e["envelope_v"])
  assert H020.key_clamp == e["key_clamp"] == 1663 and e["norm"] == 1650
  assert set(EPS_FIRMWARE_CALIBRATIONS) == {"39990-TEA-H020"}  # one calibration, keyed by the normalized ID


def test_command_map_is_the_tgg_rev_b_law():
  # TGG-A120 rev-b image row 0 (its own native knots), read from the corrected TGG image
  tx, ty = (0, 103, 263, 459, 660, 862, 1111, 1549, 1774), (0, 1740, 4443, 7769, 11167, 14579, 18798, 26202, 30002)
  k = np.arange(0, 1664)
  assert np.abs(np.interp(k, H020.r5_key_bp, H020.r5_v) - np.interp(k, tx, ty)).max() <= 2.0
  assert H020.kp_v == (117, 148, 184, 220, 245, 257, 263, 265, 265)
  assert H020.kp_key_bp == tuple(round(x * 4096 / 3840) for x in (0, 222, 443, 665, 887, 1108, 1330, 1552, 1774))
  slopes = np.diff(H020.r5_v) / np.diff(H020.r5_key_bp)
  assert slopes.max() / slopes.min() < 1.1  # no 2x gain segment (the October 11 H020 map had 8.5..35.4 R5/key)


def test_h020_derived_tables():
  assert R6_CENTRE == pytest.approx(-153.74)
  assert H020.key_ceiling(0) == 1663
  assert H020.key_ceiling(100 / 3.6) == 1663
  assert H020.key_ceiling(130 / 3.6) == 1330  # Clarity limits; TGG rev-b is flat


def test_position_map_matches_firmware_equation():
  linear, angle = H020_VGR_INVERSE
  raw = np.asarray(linear) * A_Y[0] * 10 / 16384
  expected = raw * 16384 / np.interp(raw, A_X, A_Y) / 10
  assert np.max(np.abs(expected - angle)) < 1e-10
  assert np.all(np.diff(angle) > 0)


@pytest.mark.parametrize("v", [0, 3, 12, 30])
def test_geometry_roundtrip(v):
  rack = HondaEpsRackMap(2.7, H020_VGR_INVERSE, H020.rack)
  for angle in [-480, -120, -5, 0, 5, 120, 480]:
    k = rack.curvature_from_angle(angle, v, 0.02)
    assert rack.angle_from_curvature(k, v, 0.02) == pytest.approx(angle, abs=1e-6)


def test_firmware_inverse_residual_and_r6_rail():
  for angle in [-120, 0, 120]:
    for rate in [-40, 0, 40]:
      for target in [-800, 0, 800]:
        r = ff.r5_for_motion(target, rate, H020, angle_deg=angle)
        assert ff.firmware_output(r, rate, H020, angle) == pytest.approx(target, abs=1e-7)
  assert ff.firmware_r6(1000, 0, H020) == -32765
  assert ff.firmware_r6(-1000, 0, H020) == 32765


def test_core_stays_bounded_and_freezes_on_driver_press():
  core = ff.HondaEpsLateralCore([0], [0.03], [0], [0.01], 0.01, ff.HondaEpsFirmwareFeedforward(0.01, H020))
  for i in range(1000):
    out = core.update(20 * math.sin(i / 50), 0, 10 * math.sin(i / 50), 12, 0, False, False)
    assert math.isfinite(out) and abs(out) <= 1
  before = core.pid.i
  core.update(10, 0, 0, 12, 0, True, True)
  assert core.pid.i == before and core.ff_weight == 0
  core.reset();assert core.output == 0 and core.pid.i == 0



def test_adapter_and_log_schema():
  c = real_cp()
  ctrl = LatControlHondaEps(c, None, None)
  cs, lp = sensors(vEgo=12.), NS(roll=0.0, angleOffsetDeg=1.0)
  out, angle, state = ctrl.update(True, cs, None, lp, False, -0.005, None, False)
  assert math.isfinite(out) and abs(out) <= 1
  assert abs(angle - 1.) <= 3.0 + 1e-9
  assert state.active
  controls = log.ControlsState.new_message()
  controls.lateralControlState.pidState = state
  assert controls.lateralControlState.which() == "pidState"


def run(ctrl, frames, **kw):
  cs, lp = sensors(), NS(roll=0., angleOffsetDeg=0.)
  out = None
  for i in range(frames):
    out, ang, _ = ctrl.update(True, sensors(**kw), None, lp, False, -0.01 * min(i / 100, 1), None, False)
  return out


def hold(frames=300, pressed=None, torque_sign=1):
  ctrl = LatControlHondaEps(real_cp(), None, None)
  lp = NS(roll=0., angleOffsetDeg=0.)
  ang, trace = 0., []
  for i in range(frames):
    pr = pressed(i) if pressed else False
    cs = sensors(steeringAngleDeg=ang, steeringPressed=pr, steeringTorque=torque_sign * 1500 * np.sign(ctrl.core.output or 1) if pr else 0.)
    out, a, _ = ctrl.update(True, cs, None, lp, False, -0.01 * min(i / 100, 1), None, False)
    ang += (a - ang) * 0.1
    trace.append((round(ctrl.core.ff_weight, 3), out))
  return ctrl, trace


def test_short_same_direction_press_keeps_feedforward():
  _, trace = hold(500, pressed=lambda i: 300 <= i < 306)
  assert min(w for w, _ in trace[300:330]) == 1.0


def test_opposing_press_drops_feedforward_immediately():
  _, trace = hold(500, pressed=lambda i: 300 <= i < 304, torque_sign=-1)
  assert trace[301][0] == 0.0


def test_sustained_same_direction_press_is_recognized():
  _, trace = hold(500, pressed=lambda i: 300 <= i < 340)
  assert trace[339][0] == 0.0


def test_one_frame_dropout_rides_through_with_zero_output():
  ctrl, _ = hold(300)
  cs, lp = sensors(), NS(roll=0., angleOffsetDeg=0.)
  ctrl.reset()
  out, _, st = ctrl.update(False, cs, None, lp, False, -0.01, None, False)
  assert out == 0.0 and not st.active and ctrl.core.ff_weight == 1.0
  ctrl.reset()
  out, _, st = ctrl.update(True, cs, None, lp, False, -0.01, None, False)
  assert out != 0.0 and st.active and ctrl.core.ff_weight == 1.0


def test_long_dropout_hard_resets():
  ctrl, _ = hold(300)
  cs, lp = sensors(), NS(roll=0., angleOffsetDeg=0.)
  for _ in range(12):
    ctrl.reset()
    out, _, _ = ctrl.update(False, cs, None, lp, False, -0.01, None, False)
    assert out == 0.0
  assert ctrl.core.pid.i == 0 and ctrl.core.output == 0 and ctrl.core.ff_weight == 0


@pytest.mark.parametrize("bad_field", ["steeringAngleDeg", "steeringRateDeg", "vEgo", "steeringTorque", "roll", "angleOffsetDeg", "curvature"])
def test_invalid_inputs_produce_zero_and_reset(bad_field):
  ctrl = LatControlHondaEps(real_cp(), None, None)
  cs, lp, k = sensors(), NS(roll=0., angleOffsetDeg=0.), -0.005
  if bad_field == "curvature":
    k = float("nan")
  elif hasattr(cs, bad_field):
    setattr(cs, bad_field, float("nan"))
  else:
    setattr(lp, bad_field, float("nan"))
  out, angle, state = ctrl.update(True, cs, None, lp, False, k, None, False)
  assert out == 0 and angle == 0 and not state.active
  assert ctrl.core.output == 0 and ctrl.core.pid.i == 0


def test_engage_mid_turn_slews_from_wheel_angle():
  ctrl = LatControlHondaEps(real_cp(), None, None)
  cs, lp = sensors(steeringAngleDeg=60.), NS(roll=0., angleOffsetDeg=0.)
  _, angle, _ = ctrl.update(True, cs, None, lp, False, -0.02, None, False)
  assert abs(angle - 60.) <= 3.0 + 1e-9


@pytest.mark.parametrize("v,p,i", [(0., 0.018, 0.006), (10., 0.02337, 0.00779),
                                  (11.176, 0.048, 0.016), (22.352, 0.060, 0.020), (35., 0.060, 0.020)])
def test_transferred_tgg_pid_schedule(v, p, i):
  c = real_cp()
  core = ff.HondaEpsLateralCore(list(c.lateralTuning.pid.kpBP), list(c.lateralTuning.pid.kpV),
                              list(c.lateralTuning.pid.kiBP), list(c.lateralTuning.pid.kiV),
                              0.01, ff.HondaEpsFirmwareFeedforward(0.01, H020))
  core.pid.speed = v
  assert core.pid.k_p == pytest.approx(p, abs=2e-5)
  assert core.pid.k_i == pytest.approx(i, abs=2e-5)


def test_tgg_vehicle_donor_with_h020_firmware_inverse():
  from openpilot.selfdrive.controls.lib.honda_eps_rack_map import CIVIC_TGG_A120_RACK
  assert H020.rack == CIVIC_TGG_A120_RACK and H020.rack.ratio_v[0] == 15.09
  load = ff.column_load(10., 0., 5., 0., H020.load)
  assert load == pytest.approx(-120.18)
  r5 = ff.r5_for_motion(load, 0., H020, angle_deg=10.)
  assert ff.firmware_output(r5, 0., H020, 10.) == pytest.approx(load, abs=1e-8)


# --- driver-override settings (plain files in the params directory), carstate threshold and the carcontroller ramp ---

def write(params_dir, name, value):
  (params_dir / name).write_text(str(value))


@pytest.mark.parametrize("name,text,expected", [
  ("HondaDriverOverrideThreshold", "2100", 2100.0), ("HondaDriverOverrideThreshold", " 1200\n", 1200.0),
  ("HondaDriverOverrideThreshold", "100", 500.0), ("HondaDriverOverrideThreshold", "999999", 5000.0),
  ("HondaDriverOverrideThreshold", "nan", 1800.0), ("HondaDriverOverrideThreshold", "abc", 1800.0), ("HondaDriverOverrideThreshold", "", 1800.0),
  ("HondaOverrideFadeDownSecs", "0.3", 0.3), ("HondaOverrideFadeDownSecs", "-2", 0.0), ("HondaOverrideFadeDownSecs", "inf", 0.0),
  ("HondaOverrideFadeUpSecs", "1.5", 1.5), ("HondaOverrideFadeUpSecs", "99", 10.0), ("HondaOverrideFadeUpSecs", "x", 0.5)])
def test_setting_files_are_clipped_and_bad_values_fall_back(tmp_path, name, text, expected):
  write(tmp_path, name, text)
  assert gate.read_setting(name, tmp_path) == expected


def test_missing_setting_files_give_the_h020_defaults(tmp_path):
  s = gate.H020Settings(tmp_path)
  assert (s.override_threshold, s.fade_down_s, s.fade_up_s) == (1800.0, 0.0, 0.5)


def test_settings_are_reread_about_once_a_second(tmp_path):
  s = gate.H020Settings(tmp_path)
  write(tmp_path, "HondaDriverOverrideThreshold", 1200)
  for _ in range(99):
    s.tick()
  assert s.override_threshold == 1800.0
  s.tick()
  assert s.override_threshold == 1200.0


def make_ci(monkeypatch, tmp_path, version=PTM_ID):
  monkeypatch.setattr(gate, "PARAMS_DIR", tmp_path)
  fw = fw_list(version)
  cp = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, FPS, fw, False, False, False)
  sp = CarInterface.get_params_sp(cp, CAR.HONDA_CIVIC_BOSCH, FPS, fw, False, False, False)
  cp.carFw = fw
  return CarInterface(cp, sp)


class FakeParser:
  def __init__(self, torque):
    self.vl = defaultdict(lambda: defaultdict(float))
    self.vl["STEER_STATUS"]["STEER_TORQUE_SENSOR"] = torque
    self.vl_all = defaultdict(lambda: defaultdict(list))
    self.ts = defaultdict(lambda: defaultdict(list))
    self.can_valid, self.counter_fail, self.updated = True, 0, defaultdict(list)


def pressed_at(ci, torque):
  ret, _ = ci.CS.update({Bus.pt: FakeParser(torque), Bus.cam: FakeParser(0), Bus.body: FakeParser(0)})
  return ret.steeringPressed


def test_carstate_h020_threshold_default_and_file(monkeypatch, tmp_path):
  ci = make_ci(monkeypatch, tmp_path)
  assert not pressed_at(ci, 1500) and pressed_at(ci, 1900)  # 1800 by default
  write(tmp_path, "HondaDriverOverrideThreshold", 1200)
  for _ in range(100):
    ci.CS.h020_settings.tick()
  assert pressed_at(ci, 1500)


def test_carstate_other_modified_eps_keeps_the_res_threshold(monkeypatch, tmp_path):
  write(tmp_path, "HondaDriverOverrideThreshold", 3000)
  ci = make_ci(monkeypatch, tmp_path, b"39990-TEA,H021\0\0")
  assert ci.CS.h020_settings is None and ci.CC.h020_settings is None
  assert pressed_at(ci, 1300) and not pressed_at(ci, 1100)  # res's 1200


def drive(ci, monkeypatch, frames, torque, pressed, driver_torque=0.0):
  """Run real CarController.update; return (apply_torque, lkas_active) of the last frame."""
  sent = []
  monkeypatch.setattr(hondacan, "create_steering_control", lambda packer, CAN, apply, active: sent.append((apply, active)) or (0, b"", 0))
  monkeypatch.setattr(hondacan, "create_lkas_hud", lambda *a, **k: (0, b"", 0))
  msg = car.CarControl.new_message()  # card hands the controller a reader
  msg.latActive = True
  msg.actuators.torque = torque
  CC = msg.as_reader()
  CS = ci.CS
  CS.out = car.CarState.new_message()
  CS.out.vEgo = 15.0
  CS.out.steeringPressed = pressed
  CS.out.steeringTorque = driver_torque
  CS.lkas_hud, CS.acc_hud = {}, {}
  for _ in range(frames):
    ci.CC.update(CC, custom.CarControlSP.new_message().as_reader(), CS, 0)
  return sent[-1]


def test_carcontroller_fades_in_over_half_a_second_after_engage(monkeypatch, tmp_path):
  ci = make_ci(monkeypatch, tmp_path)
  assert drive(ci, monkeypatch, 1, 0.4, False)[0] == pytest.approx(-0.4 * 0.02 * 3840, abs=2)   # ramp 0.02 after one frame
  assert drive(ci, monkeypatch, 24, 0.4, False)[0] == pytest.approx(-0.4 * 0.5 * 3840, abs=3)    # half way at 25 frames
  assert drive(ci, monkeypatch, 30, 0.4, False)[0] == pytest.approx(-0.4 * 3840, abs=2)           # full by 0.5 s


def test_carcontroller_override_cuts_torque_at_once_and_drops_lkas(monkeypatch, tmp_path):
  ci = make_ci(monkeypatch, tmp_path)
  drive(ci, monkeypatch, 80, 0.4, False)
  apply, active = drive(ci, monkeypatch, 1, 0.4, True, driver_torque=-2500)  # opposing the command: latched immediately
  assert apply == 0 and not active and ci.CC.last_torque == 0.0
  apply, active = drive(ci, monkeypatch, 1, 0.4, False)  # released: authority returns over fade-up, LKAS requested again
  assert active and 0 < abs(apply) < 0.4 * 3840 * 0.05
  assert drive(ci, monkeypatch, 60, 0.4, False)[0] == pytest.approx(-0.4 * 3840, abs=2)


def test_carcontroller_fade_down_file_and_same_direction_press_delay(monkeypatch, tmp_path):
  write(tmp_path, "HondaOverrideFadeDownSecs", 0.2)
  ci = make_ci(monkeypatch, tmp_path)
  drive(ci, monkeypatch, 80, 0.4, False)
  apply, active = drive(ci, monkeypatch, 1, 0.4, True, driver_torque=-2500)
  assert active is False and abs(apply) == pytest.approx(0.4 * 0.95 * 3840, abs=40)


def test_carcontroller_unrelated_car_is_unchanged(monkeypatch, tmp_path):
  ci = make_ci(monkeypatch, tmp_path, b"39990-TEA,H021\0\0")
  apply, active = drive(ci, monkeypatch, 60, 0.4, True, driver_torque=-2500)
  prm = CarControllerParams(ci.CP)
  assert active and apply == int(np.interp(-0.4 * prm.STEER_MAX, prm.STEER_LOOKUP_BP, prm.STEER_LOOKUP_V))  # res's own map, no override handling
