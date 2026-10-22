"""Behavioral checks against res's actual CarParams/PID-log schemas and the port's numerical code."""
import dataclasses
import json
import math
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest
from cereal import car, log
from opendbc.sunnypilot.car.honda import h020_ptm as gate
from openpilot.selfdrive.controls.lib import honda_eps_firmware_ff as ff
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import H020, R6_CENTRE
from openpilot.selfdrive.controls.lib.honda_eps_h020_geometry import H020_VGR_INVERSE, A_X, A_Y
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import HondaEpsRackMap
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import LatControlHondaEps, use_honda_eps_controller

ROOT = Path(__file__).resolve().parents[2]
CFG = {"enabled": True, "ptm_build": "20261011-trk4250", "calibration_stage": "provisional"}


def cp(version=b"39990-TEA,H020\0\0", fp="HONDA_CIVIC_BOSCH"):
  c = car.CarParams.new_message()
  c.carFingerprint = fp
  c.wheelbase = 2.7
  c.steerLimitTimer = 0.8
  c.lateralTuning.init("pid")
  c.lateralParams.torqueBP = [0, 2564, 8000]
  c.lateralParams.torqueV = [0, 2564, 3840]
  c.carFw = [{"ecu": "eps", "address": 0x18da30f1, "fwVersion": version}]
  return c


@pytest.mark.parametrize("bad", [{}, {"enabled": True}, {**CFG, "enabled": "true"},
                                 {**CFG, "ptm_build": "stock"}, {**CFG, "calibration_stage": "measured"}])
def test_config_rejects_incomplete_or_unknown_build(tmp_path, bad):
  p = tmp_path / "config.json";p.write_text(json.dumps(bad))
  assert gate.read_config(p) == {"enabled": False}


def test_config_failures_fall_back(tmp_path):
  assert gate.read_config(tmp_path / "missing") == {"enabled": False}
  p = tmp_path / "config.json";p.write_text("not-json")
  assert gate.read_config(p) == {"enabled": False}
  p.write_text("[]");assert gate.read_config(p) == {"enabled": False}


@pytest.mark.parametrize("variant", ["20261011-trk4250", "20261011-trk3200"])
def test_explicit_build_config(tmp_path, variant):
  p = tmp_path / "config.json";p.write_text(json.dumps({**CFG, "ptm_build": variant}))
  assert gate.read_config(p)["enabled"] is True


@pytest.mark.parametrize("version,fp", [(b"39990-TEA-H020", "HONDA_CIVIC_BOSCH"),
                                         (b"39990-TEA,H020-extra", "HONDA_CIVIC_BOSCH"),
                                         (b"39990-TBA,C020", "HONDA_CIVIC_BOSCH"),
                                         (b"39990-TEA,H020", "HONDA_CIVIC")])
def test_other_firmware_and_platforms_unchanged(version, fp):
  c = cp(version, fp);before = c.to_dict()
  assert not gate.configure_h020(c, fp, c.carFw, CFG)
  assert c.to_dict() == before
  assert not use_honda_eps_controller(c, CFG)


def test_disabled_does_not_change_existing_tune():
  c = cp();before = c.to_dict()
  assert not gate.configure_h020(c, c.carFingerprint, c.carFw, {"enabled": False})
  assert c.to_dict() == before


def test_h020_linear_map_and_selection():
  c = cp();assert gate.configure_h020(c, c.carFingerprint, c.carFw, CFG)
  assert list(c.lateralParams.torqueBP) == [0, 3840]
  assert list(c.lateralParams.torqueV) == [0, 3840]
  assert list(c.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
  assert list(c.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])
  assert c.lateralTuning.pid.kf == 0.0
  assert use_honda_eps_controller(c, CFG)
  c.lateralParams.torqueV = [0, 3000]
  assert not use_honda_eps_controller(c, CFG)


def test_no_eps_or_ambiguous_eps():
  c = cp();c.carFw = []
  assert not gate.is_h020_ptm(c.carFw)
  c.carFw = [{"ecu": "eps", "fwVersion": b"39990-TEA,H020"}, {"ecu": "eps", "fwVersion": b"39990-TBA,C020"}]
  assert not gate.is_h020_ptm(c.carFw)


def test_h020_own_firmware_tables():
  assert H020.r5_key_bp == (0, 226, 311, 495, 656, 887, 1108, 1552, 1774)
  assert H020.kp_key_bp == (3, 173, 441, 665, 887, 1104, 1317, 1610, 1774)
  assert H020.envelope_bp == (0, 50, 100, 150, 200, 240, 300, 321, 400)
  assert H020.envelope_v == (1774, 1774, 1774, 1774, 1774, 1552, 1219, 1108, 1108)
  assert R6_CENTRE == pytest.approx(-153.74)
  assert H020.key_ceiling(0) == 1663
  assert H020.key_ceiling(200 / 3.6) == 1108


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


def test_actual_res_adapter_and_log_schema(monkeypatch, tmp_path):
  p = tmp_path / "config.json";p.write_text(json.dumps(CFG));monkeypatch.setattr(gate, "CONFIG_PATH", p)
  c = cp();assert gate.configure_h020(c, c.carFingerprint, c.carFw)
  ctrl = LatControlHondaEps(c, None, None, activation=CFG)
  cs = NS(steeringAngleDeg=0.0, steeringRateDeg=0.0, steeringTorque=0., vEgo=12., steeringPressed=False)
  lp = NS(roll=0.0, angleOffsetDeg=1.0)
  out, angle, state = ctrl.update(True, cs, None, lp, False, -0.005, None, False)
  assert math.isfinite(out) and abs(out) <= 1
  assert abs(angle - 1.) <= 3.0 + 1e-9
  assert state.active
  controls = log.ControlsState.new_message();controls.lateralControlState.pidState = state
  assert controls.lateralControlState.which() == "pidState"
  for _ in range(12):
    ctrl.reset()
    out, angle, state = ctrl.update(False, cs, None, lp, False, -0.005, None, False)
    assert out == 0 and not state.active
  assert ctrl.core.pid.i == 0


@pytest.mark.parametrize("bad_field", ["steeringAngleDeg", "steeringRateDeg", "vEgo", "roll", "angleOffsetDeg", "curvature"])
def test_invalid_inputs_produce_zero_and_reset(monkeypatch, tmp_path, bad_field):
  p = tmp_path / "config.json";p.write_text(json.dumps(CFG));monkeypatch.setattr(gate, "CONFIG_PATH", p)
  c = cp();gate.configure_h020(c, c.carFingerprint, c.carFw)
  ctrl = LatControlHondaEps(c, None, None, activation=CFG)
  cs = NS(steeringAngleDeg=0., steeringRateDeg=0., steeringTorque=0., vEgo=12., steeringPressed=False)
  lp = NS(roll=0., angleOffsetDeg=0.)
  k = -0.005
  if bad_field == "curvature":k = float("nan")
  elif hasattr(cs, bad_field):setattr(cs, bad_field, float("nan"))
  else:setattr(lp, bad_field, float("nan"))
  output, angle, state = ctrl.update(True, cs, None, lp, False, k, None, False)
  assert output == 0 and angle == 0 and not state.active
  assert ctrl.core.output == 0 and ctrl.core.pid.i == 0


@pytest.mark.parametrize("v,p,i", [(0., 0.018, 0.006), (10., 0.02337, 0.00779),
                                  (11.176, 0.048, 0.016), (22.352, 0.060, 0.020), (35., 0.060, 0.020)])
def test_transferred_tgg_pid_schedule(v, p, i):
  c = cp();gate.configure_h020(c, c.carFingerprint, c.carFw, CFG)
  core = ff.HondaEpsLateralCore(list(c.lateralTuning.pid.kpBP), list(c.lateralTuning.pid.kpV),
                              list(c.lateralTuning.pid.kiBP), list(c.lateralTuning.pid.kiV),
                              0.01, ff.HondaEpsFirmwareFeedforward(0.01, H020))
  core.pid.speed = v
  assert core.pid.k_p == pytest.approx(p, abs=2e-5)
  assert core.pid.k_i == pytest.approx(i, abs=2e-5)


def test_tgg_vehicle_donor_with_h020_firmware_inverse():
  from openpilot.selfdrive.controls.lib.honda_eps_rack_map import CIVIC_TGG_A120_RACK
  assert H020.rack == CIVIC_TGG_A120_RACK
  assert H020.rack.ratio_v[0] == 15.09
  load = ff.column_load(10., 0., 5., 0., H020.load)
  assert load == pytest.approx(-120.18)
  r5 = ff.r5_for_motion(load, 0., H020, angle_deg=10.)
  assert ff.firmware_output(r5, 0., H020, 10.) == pytest.approx(load, abs=1e-8)
  # Donor transfer must not replace H020's command/P axes or its speed envelope.
  assert H020.r5_key_bp[1:3] == (226, 311)
  assert H020.kp_key_bp[0] == 3
  assert H020.key_ceiling(200 / 3.6) == 1108
