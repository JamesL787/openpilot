import math

import numpy as np
import pytest

from opendbc.car.car_helpers import interfaces
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, vgr_linear_to_physical
from opendbc.car.honda.values import CAR as HONDA, HondaFlags
from openpilot.tools.lateral import lat_pid_sim as sim

# plant_d5 (fitted on 260-263) without its offset and friction terms: stable, and a positive command turns the wheel
# to a positive angle.
PLANT = sim.Plant([-8.544, 0.0716, -1.635, -4.022, 1785.5, -19.756, -60.5, 0.0, 0.0], delay=5)


def _cp_bytes(vgr=True):
  CP = interfaces[HONDA.HONDA_CIVIC_BOSCH].get_non_essential_params(HONDA.HONDA_CIVIC_BOSCH)
  CP.flags |= int(HondaFlags.EPS_MODIFIED) | (int(HondaFlags.VGR_CIVIC_TBA_C020) if vgr else 0)
  CP.dashcamOnly = True
  return CP.to_bytes()


def _route(curv, v=20.0, n=1500, vgr=True):
  """Engaged, hands off, constant speed; the desired curvature steps to curv at 3 s."""
  d = {k: np.zeros(n) for k in sim.FIELDS}
  d["t"] = np.arange(n) * sim.DT
  d["v"][:] = v
  d["active"][:] = 1.0
  d["sr"][:] = 16.0
  d["stiff"][:] = 1.0
  d["des_curv"][300:] = curv
  d["cp_bytes"] = _cp_bytes(vgr)
  d["params"] = {"HondaLateralPidKpScale": "1.0", "HondaLateralPidKiScale": "1.0"}
  d["route"] = "synthetic"
  return d


@pytest.mark.parametrize("kind", ["torque_upstream", "torque_starpilot"])
@pytest.mark.parametrize("vgr", [False, True])
def test_torque_kinds_close_the_loop_onto_their_own_target(kind, vgr):
  d = _route(0.004)   # right turn in this fork's convention: a negative wheel angle
  ang, des, out, deliv, raw = sim.simulate(d, PLANT, with_raw=True, kind=kind, torque={"vgr": vgr})
  assert raw[-1] < -5.0
  assert np.all(np.isfinite(ang)) and np.max(np.abs(deliv)) <= 1.0 + 1e-9
  assert ang[-1] == pytest.approx(raw[-1], abs=0.1 * abs(raw[-1]))
  assert out[-1] < 0.0


def test_vgr_target_is_the_map_applied_to_the_linear_angle():
  d = _route(0.02, v=8.0)
  _, _, _, _, raw_off = sim.simulate(d, PLANT, with_raw=True, kind="torque_upstream", torque={"vgr": False})
  _, _, _, _, raw_on = sim.simulate(d, PLANT, with_raw=True, kind="torque_upstream", torque={"vgr": True})
  ctl = sim.Controller(d["cp_bytes"], d["params"], kind="torque_upstream", torque={"vgr": True})
  ctl.VM.update_params(1.0, sim.VGR_SR)
  lin = math.degrees(ctl.VM.get_steer_from_curvature(-0.02, 8.0, 0.0))
  ctl.close()
  assert raw_on[-1] == pytest.approx(vgr_linear_to_physical(lin, get_honda_vgr_inverse(ctl.CP.flags)), abs=1e-6)
  assert abs(raw_on[-1]) != pytest.approx(abs(raw_off[-1]), abs=0.5)   # the map and sR change the target at 8 m/s


def test_vgr_without_the_firmware_flag_is_refused():
  d = _route(0.004, vgr=False)
  with pytest.raises(ValueError):
    sim.Controller(d["cp_bytes"], d["params"], kind="torque_upstream", torque={"vgr": True})


def test_starpilot_kind_restores_the_testing_ground_hooks():
  from openpilot.selfdrive.controls.lib import latcontrol_torque
  before = (latcontrol_torque.civic_bosch_modified_lateral_testing_ground_active,
            latcontrol_torque.civic_bosch_modified_a_lateral_testing_ground_active)
  sim.simulate(_route(0.002, n=400), PLANT, kind="torque_starpilot")
  assert (latcontrol_torque.civic_bosch_modified_lateral_testing_ground_active,
          latcontrol_torque.civic_bosch_modified_a_lateral_testing_ground_active) == before


def test_parse_variant_splits_torque_keys_from_param_overrides():
  assert sim.parse_variant("x=torque_starpilot,vgr=1,friction_low=0.08,NrdrLatRateFF=0.5") == \
    ("x", "torque_starpilot", {"vgr": True, "friction_low": 0.08}, {"NrdrLatRateFF": "0.5"})
  with pytest.raises(ValueError):
    sim.parse_variant("x=nnff")


PID_PARAMS = {"HondaLateralPidKpScale": "1.0", "HondaLateralPidKiScale": "1.0"}
SPEEDS = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0)


def _modified_cp_bytes():
  """The CarParams a modified-EPS (39990-TBA-C020, VGR) Civic Bosch fingerprints to, PID tune included."""
  from types import SimpleNamespace
  from opendbc.car import gen_empty_fingerprint
  from opendbc.car.structs import CarParams
  fw = [CarParams.CarFw(ecu=CarParams.Ecu.eps, fwVersion=b'39990-TBA,C020\x00\x00', address=0x18DA30F1, subAddress=0)]
  toggles = SimpleNamespace(force_torque_controller=False, nnff=False, nnff_lite=False)
  CP = interfaces[HONDA.HONDA_CIVIC_BOSCH].get_params(HONDA.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), fw, False, False, False, toggles)
  assert CP.flags & HondaFlags.EPS_MODIFIED and CP.flags & HondaFlags.VGR_CIVIC_TBA_C020
  return CP.to_bytes()


def _push_back(kind, torque=None):
  """|command| 0.1 s after the wheel is held 5 deg off a straight, per speed."""
  res = sim.stiffness(_modified_cp_bytes(), PID_PARAMS, kind=kind, torque=torque, speeds=SPEEDS, disps=(5.0,))
  return np.array([abs(res[v][5.0][0]) for v in SPEEDS])


def test_torque_tune_pushes_back_no_harder_than_the_pid():
  # The owner's override complaint: on the stock-EPS table the torque controller fought the driver. With the measured
  # tune (opendbc sets LAF 11.5; StarPilot's Civic branch then multiplies it by 1.2) it must not out-push the PID.
  pid = _push_back("pid")
  for kind, laf in (("torque_upstream", 11.5), ("torque_starpilot", 11.5 * 1.2)):
    tq = _push_back(kind, {"vgr": True, "laf": laf, "friction": 0.025})
    assert np.all(tq <= pid), (kind, tq, pid)
  # The backstop's worst case (LAF floor 8.0 x 1.2, friction cap 0.05) stays close to the PID.
  floor = _push_back("torque_starpilot", {"vgr": True, "laf": 8.0 * 1.2, "friction": 0.05})
  assert np.all(floor <= 1.25 * pid), (floor, pid)
  # The stock-EPS table is what this guards against: 1.9-2.8x the PID from 34 mph up, 3.8-5x below.
  stock = _push_back("torque_upstream", {"vgr": True, "laf": 1.6917, "friction": 0.2546})
  assert np.all(stock >= 1.5 * pid), (stock, pid)


def test_civic_modified_torque_params_are_bounded_on_every_path():
  from openpilot.selfdrive.controls.lib.latcontrol_vehicle_tunes import (CIVIC_BOSCH_MODIFIED_B_LAT_ACCEL_FACTOR_MULT as MULT,
                                                                        CIVIC_BOSCH_MODIFIED_MAX_FRICTION, CIVIC_BOSCH_MODIFIED_MIN_LAT_ACCEL_FACTOR)
  d = _route(0.0, n=10)
  # offline CP (the stock-EPS table) through __init__
  ctl = sim.Controller(d["cp_bytes"], d["params"], kind="torque_starpilot", torque={"laf": 1.6917, "friction": 0.2546})
  try:
    tp = ctl.lac.torque_params
    assert tp.latAccelFactor == pytest.approx(CIVIC_BOSCH_MODIFIED_MIN_LAT_ACCEL_FACTOR * MULT)
    assert tp.friction == pytest.approx(CIVIC_BOSCH_MODIFIED_MAX_FRICTION)
    # learned (torqued) or custom-toggle values through update_live_torque_params
    ctl.lac.update_live_torque_params(2.0, 0.0, 0.3)
    assert (tp.latAccelFactor, tp.friction) == pytest.approx((CIVIC_BOSCH_MODIFIED_MIN_LAT_ACCEL_FACTOR * MULT, CIVIC_BOSCH_MODIFIED_MAX_FRICTION))
    # values inside the bounds pass through unchanged
    ctl.lac.update_live_torque_params(11.5, 0.0, 0.025)
    assert (tp.latAccelFactor, tp.friction) == pytest.approx((11.5 * MULT, 0.025))
  finally:
    ctl.close()


def test_pid_gain_overrides_replace_the_tune_and_refuse_the_torque_kinds():
  assert sim.parse_variant("nrdr=pid,kp=0.03,ki=0.01,kf=1.2e-5,rate_damp=0.3,HondaCenterScale=0.5") == \
    ("nrdr", "pid", {"kp": 0.03, "ki": 0.01, "kf": 1.2e-5, "rate_damp": 0.3}, {"HondaCenterScale": "0.5"})
  d = _route(0.0, n=10)
  d["cp_bytes"] = _modified_cp_bytes()
  with pytest.raises(ValueError):
    sim.Controller(d["cp_bytes"], d["params"], kind="torque_upstream", torque={"kp": 0.03})
  ctl = sim.Controller(d["cp_bytes"], d["params"], torque={"kp": 0.03, "ki": 0.01, "kf": 1.2e-5})
  try:
    assert list(ctl.CP.lateralTuning.pid.kpV) == [pytest.approx(0.03)] and list(ctl.CP.lateralTuning.pid.kiV) == [pytest.approx(0.01)]
    assert ctl.lac.ff_factor == pytest.approx(1.2e-5) and not ctl.lac.is_modified_eps_kf_car
  finally:
    ctl.close()


def test_rate_damping_opposes_the_wheel_rate_below_30_mph_only():
  d = _route(0.0, n=10)
  d["cp_bytes"] = _modified_cp_bytes()
  outs = {}
  for v in (5.0, 20.0):
    d["v"][:] = v
    for damp in (0.0, 0.3):
      ctl = sim.Controller(d["cp_bytes"], d["params"], torque={"rate_damp": damp} if damp else None)
      try:
        outs[(v, damp)] = [ctl.step(d, k, 0.0, 20.0, False)[0] for k in range(5)][-1]
      finally:
        ctl.close()
  # 5 m/s: fade (13.4 - 5) / 13.4 = 0.63, so 0.3 * 0.010 * 20 deg/s * 0.63 less command
  assert outs[(5.0, 0.3)] == pytest.approx(outs[(5.0, 0.0)] - 0.3 * 0.010 * 20.0 * (30 * sim.MPH - 5.0) / (30 * sim.MPH), abs=1e-6)
  assert outs[(20.0, 0.3)] == pytest.approx(outs[(20.0, 0.0)])


# Wiring only. On a synthetic step both this and the pid kind limit-cycle at +-1 against PLANT and the shipped
# C020 plant, so convergence is scored on logged routes (STATUS 167), not here.
@pytest.mark.parametrize("vgr", [False, True])
def test_clarity_eps_kind_builds_the_car_controller_and_joins_the_feedforward(vgr):
  from openpilot.selfdrive.controls.lib.latcontrol_clarity_eps import LatControlClarityEps
  from openpilot.selfdrive.controls.lib.nrdr_eps_firmware_ff import CIVIC_BOSCH_C020
  d = _route(0.02, vgr=vgr)   # a turn past FF_ANGLE_GATE_DEG, so the gate is fully open
  d["params"]["NrdrLatUseFirmwareVgr"] = "1" if vgr else "0"
  ctl = sim.Controller(d["cp_bytes"], d["params"], kind="clarity_eps")
  assert isinstance(ctl.lac, LatControlClarityEps) and ctl.lac.core.ff.cal is CIVIC_BOSCH_C020
  weights = []
  for k in range(400):   # wheel held on the target: the feedforward joins and fades in over 0.5 s
    ctl.step(d, k, ctl.raw_target() if k else 0.0, 0.0, False)
    weights.append(ctl.lac.core.ff_weight)
  ctl.close()
  assert weights[299] == 0.0 and weights[-1] == 1.0   # straight: held out by the angle gate; in the turn: in
  assert ctl.last_log.active and ctl.lac.core.ff.output < 0.0   # right turn: a negative feedforward
  ang, des, out, deliv, raw = sim.simulate(d, PLANT, with_raw=True, kind="clarity_eps")
  assert raw[-1] < -5.0 and des[-1] == pytest.approx(raw[-1], abs=1e-6)
  assert np.all(np.isfinite(ang)) and np.max(np.abs(deliv)) <= 1.0 + 1e-9


def test_clarity_eps_kind_ignores_the_pid_sliders_as_on_the_car():
  d = _route(0.004)
  base = sim.simulate(d, PLANT, kind="clarity_eps")[2]
  d["params"].update({"LatPScaleStandard": "150", "LatIScaleStandard": "10", "HondaLateralPidKpScale": "0.5"})
  assert np.array_equal(sim.simulate(d, PLANT, kind="clarity_eps")[2], base)
  assert not np.array_equal(sim.simulate(d, PLANT, kind="pid")[2], sim.simulate(_route(0.004), PLANT, kind="pid")[2])


def test_clarity_eps_kind_is_refused_on_a_stock_eps_and_restores_params():
  from openpilot.selfdrive.controls.lib import latcontrol_clarity_eps
  before = latcontrol_clarity_eps.Params
  sim.simulate(_route(0.002, n=400), PLANT, kind="clarity_eps")
  assert latcontrol_clarity_eps.Params is before
  CP = interfaces[HONDA.HONDA_CIVIC_BOSCH].get_non_essential_params(HONDA.HONDA_CIVIC_BOSCH)
  with pytest.raises(ValueError):
    sim.Controller(CP.to_bytes(), {}, kind="clarity_eps")
