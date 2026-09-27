#!/usr/bin/env python3
"""Offline lateral PID tuning simulator for modified-EPS Honda PID lateral.

Three stages, each checked against the log before the next one is trusted:

  1. extract   rlogs -> per-frame arrays at controlsState rate (cached as .npz next to the route,
               never in the repo).
  2. replay    open loop: the real LatControlPID is fed the logged inputs (carState, liveParameters,
               controlsState.desiredCurvature, active flag) with the logged tuning params, and its
               output is compared with the logged pidState.output. This proves the harness reproduces
               the on-car controller before anything is changed.
  3. sim       closed loop: the same controller drives an identified steering plant (torque command ->
               steering angle), with the desired curvature held to the logged trajectory. Tuning
               overrides (LatIScaleStandard=75, HondaLateralPidKpScale=0.65, ...) are applied to the
               controller only.

The plant is fitted from logs (see fit_plant). It is a speed-scheduled second-order rack model with
a command delay (fitted or --delay) and 0.1 deg angle quantisation. Its validity is judged by `validate`:
a free-run of the plant on the logged command,
and a closed-loop run at the logged settings whose tracking metrics must match the logged ones.

Limits (read before trusting a number):
  - Desired curvature is exogenous. On the car, a worse tracker changes the car's heading, and the
    model and lane centering then ask for a different curvature. The sim does not close that loop, so
    it scores how well the rack follows a fixed request, not lane position.
  - The plant is linear-in-parameters and fitted on ordinary driving. It will not predict behaviour
    outside what the fit saw (limit cycles at unusual gains, torque saturation, low grip).
  - Evidence from this tool is replay/sim evidence only.

Usage:
  python tools/lateral/lat_pid_sim.py replay ROUTE_DIR
  python tools/lateral/lat_pid_sim.py fit ROUTE_DIR [ROUTE_DIR ...] --out plant.json
  python tools/lateral/lat_pid_sim.py validate --plant plant.json ROUTE_DIR [...]
  python tools/lateral/lat_pid_sim.py sim --plant plant.json ROUTE_DIR [...] --set LatIScaleStandard=75 [--set K=V ...]
  python tools/lateral/lat_pid_sim.py sweep --plant plant.json ROUTE_DIR [...] --param LatIScaleStandard --values 25,50,75,100

EPS firmware (tools/lateral/eps_fw.py): fit through the torque table of the image the drives ran on, then swap in
another image's table. Only the table is modelled; the EPS's tracker / Norm / P / D stay as fitted (warned):
  python tools/lateral/lat_pid_sim.py fit ROUTE_DIR [...] --delay 5 --eps-rwd eps_tools/rwd/<image>.rwd --out plant.json
  python tools/lateral/lat_pid_sim.py compare --plant plant.json ROUTE_DIR --variant pid=pid --eps-rwd A.rwd --eps-rwd B.rwd
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from types import SimpleNamespace

import numpy as np

DT = 0.01
MPH = 0.44704
BANDS = (("low <25mph", 0.0, 25 * MPH), ("standard 25-50", 25 * MPH, 50 * MPH), ("highway >50", 50 * MPH, 99.0))

# Params the controller reads through Params() every 300 frames, plus the Kp/Ki toggles.
TUNING_KEYS = (
  "LatPScaleLowSpeed", "LatPScaleStandard", "LatPScaleHighway",
  "LatIScaleLowSpeed", "LatIScaleStandard", "LatIScaleHighway",
  "LatFScaleLowSpeed", "LatFScaleStandard", "LatFScaleHighway", "LatGainSchedule",
  "HondaCenterScale", "HondaCenterBoostThreshold", "HondaCenterBoostMinSpeed",
  "NrdrLatAngleRateLimit", "HondaTorqueLowPassFilter",
  "HondaLpfTauLowSpeed", "HondaLpfTauStandard", "HondaLpfTauHighway", "NrdrLatUseFirmwareVgr", "NrdrLatRateFF",
  "NrdrLatPidFirmwareFF",
  "HondaLateralPidKpScale", "HondaLateralPidKiScale",
  "NrdrLearnSteerRatio", "NrdrLearnStiffness", "NrdrLearnAngleOffset",
  # carcontroller steering path (opendbc_repo/opendbc/car/honda/carcontroller.py _update_steering_torque)
  "NrdrMinSteerSpeed", "HondaOverrideTorqueScale", "HondaOverrideFadeUpSecs", "HondaOverrideFadeDownSecs",
  "HondaSteerDeltaLimiter", "HondaSteerDeltaUp", "HondaSteerDeltaDown",
)

FIELDS = ("t", "v", "a_ego", "angle", "rate", "pressed", "eps_torque", "lblink", "rblink",
          "sr", "stiff", "offset", "roll", "des_curv", "active", "out", "des_angle",
          "cc_torque", "co_torque", "lane_change", "log_p", "log_i", "log_f")


# ----------------------------------------------------------------------------------------------
# 1. extract

def _segments(route_dir):
  segs = glob.glob(os.path.join(route_dir, "*", "rlog.zst")) + glob.glob(os.path.join(route_dir, "*", "rlog.bz2"))
  return sorted(segs, key=lambda p: int(os.path.basename(os.path.dirname(p))))


def extract(route_dir, cache=True):
  cache_path = os.path.join(route_dir, "lat_pid_sim.npz")
  return extract_logs(_segments(route_dir), os.path.basename(os.path.normpath(route_dir)), cache_path if cache else None)


def extract_logs(log_paths, route, cache_path=None, should_continue=None):
  """extract() from an explicit list of segment logs in order (the device keeps segments as <route>--<n>/ dirs,
  not under one route dir). cache_path: an .npz read if present, written otherwise. should_continue() -> False
  stops the read and raises InterruptedError."""
  if cache_path and os.path.exists(cache_path):
    z = np.load(cache_path, allow_pickle=False)
    data = {k: z[k] for k in FIELDS}
    data["cp_bytes"] = z["cp_bytes"].tobytes()
    data["params"] = json.loads(str(z["params"]))
    data["route"] = route
    return data

  from openpilot.tools.lib.logreader import LogReader
  rows = []
  cp_bytes = None
  params = {}
  cs = lp = cc = co = None
  lcs = 0
  t0 = None
  n_msg = 0
  for seg in log_paths:
    try:
      lr = LogReader(seg)
      for m in lr:
        n_msg += 1
        if should_continue is not None and n_msg % 20000 == 0 and not should_continue():
          raise InterruptedError("stopped")
        w = m.which()
        if t0 is None:
          t0 = m.logMonoTime
        if w == "initData" and not params:
          for e in m.initData.params.entries:
            if e.key in TUNING_KEYS:
              try:
                params[e.key] = e.value.decode()
              except Exception:
                pass
        elif w == "carParams" and cp_bytes is None:
          cp_bytes = m.carParams.as_builder().to_bytes()
        elif w == "carState":
          cs = m.carState
        elif w == "liveParameters":
          lp = m.liveParameters
        elif w == "carControl":
          cc = m.carControl
        elif w == "carOutput":
          co = m.carOutput
        elif w == "modelV2":
          lcs = int(m.modelV2.meta.laneChangeState.raw)
        elif w == "controlsState" and cs is not None and lp is not None:
          c = m.controlsState
          lcs_ = c.lateralControlState
          if lcs_.which() != "pidState":
            continue
          p = lcs_.pidState
          rows.append((
            (m.logMonoTime - t0) * 1e-9, cs.vEgo, cs.aEgo, cs.steeringAngleDeg, cs.steeringRateDeg,
            float(cs.steeringPressed), cs.steeringTorque, float(cs.leftBlinker), float(cs.rightBlinker),
            lp.steerRatio, lp.stiffnessFactor, lp.angleOffsetDeg, lp.roll, c.desiredCurvature,
            float(p.active), p.output, p.steeringAngleDesiredDeg,
            cc.actuators.torque if cc is not None else 0.0,
            co.actuatorsOutput.torque if co is not None else 0.0, float(lcs), p.p, p.i, p.f,
          ))
    except InterruptedError:
      raise
    except Exception as e:  # a truncated final segment is common; keep what was read
      print(f"warning: {seg}: {e}", file=sys.stderr)
  if cp_bytes is None:
    raise RuntimeError(f"{route}: no carParams in log")
  arr = np.array(rows, dtype=np.float64)
  data = {k: arr[:, i] for i, k in enumerate(FIELDS)}
  data["cp_bytes"] = cp_bytes
  data["params"] = params
  data["route"] = route
  if cache_path:
    np.savez_compressed(cache_path, **{k: data[k] for k in FIELDS},
                        cp_bytes=np.frombuffer(cp_bytes, dtype=np.uint8), params=json.dumps(params))
  return data


# ----------------------------------------------------------------------------------------------
# controller harness

class _DictParams:
  """Stands in for Params() inside LatControlPID; values are strings as on the device."""
  def __init__(self, values):
    self.values = values

  def get(self, key, *args, **kwargs):
    v = self.values.get(key)
    return None if v is None else str(v)

  def get_bool(self, key, *args, **kwargs):
    v = self.values.get(key)
    if v is None:
      return bool(kwargs.get("default", False))
    return str(v).strip().lower() in ("1", "true")


def _truthy(v, default=True):
  if v is None:
    return default
  return str(v).strip().lower() in ("1", "true")


KINDS = ("pid", "torque_upstream", "torque_starpilot", "clarity_eps")
# Torque-controller defaults from the lat-accel study (STATUS 140): LAF ~11-12 m/s^2 per unit command and
# friction ~0.02-0.03 (command units) above 25 mph, several times that below. SR 15.27 is the pooled fit
# after the firmware VGR map (model M1), used in place of paramsd's scalar when the map is on.
TORQUE_DEFAULTS = {"laf": 11.5, "friction": 0.025, "friction_low": None, "vgr": False, "lat_delay": 0.2}
VGR_SR = 15.27
# PID-kind gain overrides, for running another fork's gains through this repo's PID. kp/ki/kf replace CarParams'
# gains flat across speed (kf also bypasses the banded modified-EPS kf); rate_damp subtracts
# rate_damp * 0.010 * steeringRateDeg, faded out linearly to 30 mph (nrdr-nightly's NrdrLatControlPID, without its
# unwind-phase weighting). nrdr-nightly's Civic Bosch modified-EPS defaults: kp 0.03, ki 0.01, kf 1.2e-5, rate_damp 0.3.
PID_GAIN_KEYS = ("kp", "ki", "kf", "rate_damp")


class _VgrVM:
  """VehicleModel whose angle -> curvature first maps the published (physical) angle to the centre-equivalent
  one through the firmware VGR map. Lets a controller without a hook (StarPilot's torque) use the map."""
  def __init__(self, VM, inverse):
    self.VM = VM
    self.inverse = inverse

  def calc_curvature(self, sa, u, roll):
    from opendbc.car.honda.steer_ratio import vgr_physical_to_linear
    return self.VM.calc_curvature(np.radians(vgr_physical_to_linear(float(np.degrees(sa)), self.inverse)), u, roll)

  def __getattr__(self, name):
    return getattr(self.VM, name)


class Controller:
  """The real lateral controller plus the VehicleModel update controlsd does before calling it.
  kind "pid" is the car's LatControlPID; "torque_upstream" is comma's LatControlTorque (vendored in
  latcontrol_torque_upstream.py); "torque_starpilot" is StarPilot's LatControlTorque with NNFF off (NNFF is a
  different class that controlsd swaps in; it is never built here). The torque kinds are built on the logged
  CarParams with the lateral tuning switched to torque and the TORQUE_DEFAULTS values (overridable).
  "clarity_eps" is LatControlClarityEps, what controlsd builds on a modified-EPS Clarity / Civic Bosch when
  NrdrLatEpsFirmwareFF is on (STATUS 166), on the logged CarParams' pid gains; LatP/I/F and the Honda Kp/Ki scales
  do not reach it, as on the car."""
  def __init__(self, cp_bytes, params, testing_ground=False, kind="pid", torque=None):
    from cereal import car, custom
    from opendbc.car.car_helpers import interfaces
    from opendbc.car.vehicle_model import VehicleModel
    from openpilot.selfdrive.controls.lib import latcontrol_pid
    from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID

    assert kind in KINDS, kind
    self.kind = kind
    self.tq = {**TORQUE_DEFAULTS, **(torque or {})}
    with car.CarParams.from_bytes(cp_bytes) as r:
      cpb = r.as_builder()
    self.gains = {k: v for k, v in (torque or {}).items() if k in PID_GAIN_KEYS}
    if self.gains and kind != "pid":
      raise ValueError(f"{sorted(self.gains)} apply to the pid kind only")
    for k in ("kp", "ki"):
      if k in self.gains:
        setattr(cpb.lateralTuning.pid, k + "BP", [0.0])
        setattr(cpb.lateralTuning.pid, k + "V", [float(self.gains[k])])
    if "kf" in self.gains:
      cpb.lateralTuning.pid.kf = float(self.gains["kf"])
    if kind not in ("pid", "clarity_eps"):
      cpb.lateralTuning.init("torque")
      t = cpb.lateralTuning.torque
      t.latAccelFactor = float(self.tq["laf"])
      t.friction = float(self.tq["friction"])
      t.latAccelOffset = 0.0
      t.steeringAngleDeadzoneDeg = 0.0
    self.CP = cpb.as_reader()
    fpcp = custom.StarPilotCarParams.new_message().as_reader()
    self.CI = interfaces[self.CP.carFingerprint](self.CP, fpcp)
    self.VM = VehicleModel(self.CP)
    self.params = dict(params)
    self.vgr = None
    self.target = 0.0
    self._friction = None
    self._restore = []
    if kind == "pid":
      # The Civic Bosch "testing ground" slot is chosen by a file on the device that the log does not
      # record. The replay stage shows whether forcing it off reproduces the logged output.
      self._patch(latcontrol_pid, "civic_bosch_modified_lateral_testing_ground_active", lambda *a, **kw: testing_ground)
      saved_params = latcontrol_pid.Params
      latcontrol_pid.Params = lambda: _DictParams(self.params)
      try:
        self.lac = LatControlPID(self.CP, self.CI, DT)
      finally:
        latcontrol_pid.Params = saved_params
      self.lac.params = _DictParams(self.params)
      if "kf" in self.gains:
        self.lac.is_modified_eps_kf_car = False
    elif kind == "clarity_eps":
      from openpilot.selfdrive.controls.lib import latcontrol_clarity_eps
      if not latcontrol_clarity_eps.use_clarity_eps_controller(self.CP, _DictParams({"NrdrLatEpsFirmwareFF": "1"})):
        raise ValueError(f"clarity_eps needs a modified-EPS Clarity or Civic Bosch on pid tuning, not {self.CP.carFingerprint}")
      self._patch(latcontrol_clarity_eps, "Params", lambda: _DictParams(self.params))
      self.lac = latcontrol_clarity_eps.LatControlClarityEps(self.CP, self.CI, DT)
    else:
      from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, vgr_physical_to_linear
      if self.tq["vgr"]:
        self.vgr = get_honda_vgr_inverse(self.CP.flags)
        if self.vgr is None:
          raise ValueError("vgr requested but the logged CarParams carry no firmware VGR flag")
      if kind == "torque_upstream":
        from openpilot.selfdrive.controls.lib.latcontrol_torque_upstream import LatControlTorque
        a2l = None if self.vgr is None else (lambda a, inv=self.vgr: vgr_physical_to_linear(a, inv))
        self.lac = LatControlTorque(self.CP, self.CI, DT, angle_to_linear=a2l)
      else:
        from openpilot.selfdrive.controls.lib import latcontrol_torque
        # Both Civic testing-ground slots are device files the log does not record; the base (B) branch is used.
        self._patch(latcontrol_torque, "civic_bosch_modified_lateral_testing_ground_active", lambda *a, **kw: False)
        self._patch(latcontrol_torque, "civic_bosch_modified_a_lateral_testing_ground_active", lambda *a, **kw: False)
        # Its Civic-modified branch multiplies LAF by CIVIC_BOSCH_MODIFIED_B_LAT_ACCEL_FACTOR_MULT; divide it out
        # so both torque kinds see the same car model and differ only in control law.
        self.laf_mult = latcontrol_torque.CIVIC_BOSCH_MODIFIED_B_LAT_ACCEL_FACTOR_MULT
        self.lac = latcontrol_torque.LatControlTorque(self.CP, self.CI, DT)
        self.lac.update_live_torque_params(self.tq["laf"] / self.laf_mult, 0.0, self.tq["friction"])
    self.toggles = SimpleNamespace(
      honda_lateral_pid_kp_scale=float(self.params.get("HondaLateralPidKpScale", 1.0)),
      honda_lateral_pid_ki_scale=float(self.params.get("HondaLateralPidKiScale", 1.0)),
    )
    self.learn_sr = _truthy(self.params.get("NrdrLearnSteerRatio"))
    self.learn_x = _truthy(self.params.get("NrdrLearnStiffness"))
    self.learn_offset = _truthy(self.params.get("NrdrLearnAngleOffset"))

  def _patch(self, mod, name, fn):
    self._restore.append((mod, name, getattr(mod, name)))
    setattr(mod, name, fn)

  def close(self):
    for mod, name, fn in reversed(self._restore):
      setattr(mod, name, fn)
    self._restore = []

  def raw_target(self):
    """The unshaped target angle (deg, physical): the PID's before the slew clip and smoothing, or for the torque
    kinds the angle the controller's own kinematics (VGR map or not, its sR) give for the desired curvature."""
    return self.lac.raw_angle_steers_des if self.kind == "pid" else self.target  # clarity_eps: before its rate limit

  def _set_friction(self, v):
    fr = self.tq["friction"]
    if self.tq["friction_low"] is not None:
      fr = float(np.interp(v, [20 * MPH, 25 * MPH], [self.tq["friction_low"], self.tq["friction"]]))
    if fr != self._friction:
      self._friction = fr
      if self.kind == "torque_upstream":
        self.lac.update_torque_parameters(self.tq["laf"], 0.0, fr)
      else:
        self.lac.update_live_torque_params(self.tq["laf"] / self.laf_mult, 0.0, fr)

  def step(self, d, k, angle, rate, steer_limited):
    x = max(d["stiff"][k] if self.learn_x else 1.0, 0.1)
    if self.vgr is not None:
      sr = VGR_SR
    else:
      sr = max(d["sr"][k] if self.learn_sr else self.CP.steerRatio, 0.1)
    self.VM.update_params(x, sr)
    lp = SimpleNamespace(angleOffsetDeg=float(d["offset"][k]) if self.learn_offset else 0.0, roll=float(d["roll"][k]))
    CS = SimpleNamespace(
      vEgo=float(d["v"][k]), aEgo=float(d["a_ego"][k]), steeringAngleDeg=float(angle), steeringRateDeg=float(rate),
      steeringPressed=bool(d["pressed"][k]), steeringTorque=float(d["eps_torque"][k]),
      leftBlinker=bool(d["lblink"][k]), rightBlinker=bool(d["rblink"][k]), standstill=d["v"][k] < 0.1,
    )
    active, curv = bool(d["active"][k]), float(d["des_curv"][k])
    if self.kind == "pid":
      out, des, self.last_log = self.lac.update(active, CS, self.VM, lp, bool(steer_limited), curv,
                                                False, 0.0, None, None, self.toggles)
      if self.gains.get("rate_damp") and active:
        fade = float(np.clip((30 * MPH - CS.vEgo) / (30 * MPH), 0.0, 1.0))
        out = float(np.clip(out - self.gains["rate_damp"] * 0.010 * CS.steeringRateDeg * fade, -1.0, 1.0))
      return float(out), float(des)
    if self.kind == "clarity_eps":
      # the shell's own map (firmware VGR or sr curve) before its rate limit; it recomputes the same value in update
      self.target = self.lac._desired_angle_no_offset(self.VM, CS.vEgo, lp.roll, curv) + lp.angleOffsetDeg
      out, des, self.last_log = self.lac.update(active, CS, self.VM, lp, bool(steer_limited), curv,
                                                False, 0.0, None, None, self.toggles)
      return float(out), float(des)
    from opendbc.car.honda.steer_ratio import vgr_linear_to_physical
    lin = float(np.degrees(self.VM.get_steer_from_curvature(-curv, CS.vEgo, lp.roll)))
    self.target = vgr_linear_to_physical(lin, self.vgr) + lp.angleOffsetDeg
    self._set_friction(CS.vEgo)
    if self.kind == "torque_upstream":
      out, _, self.last_log = self.lac.update(active, CS, self.VM, lp, bool(steer_limited), curv, False, self.tq["lat_delay"])
    else:
      VM = self.VM if self.vgr is None else _VgrVM(self.VM, self.vgr)
      out, _, self.last_log = self.lac.update(active, CS, VM, lp, bool(steer_limited), curv, False, self.tq["lat_delay"],
                                              None, None, SimpleNamespace())
    return float(out), self.target


# ----------------------------------------------------------------------------------------------
# 2. replay (open loop)

def replay(d, overrides=None, testing_ground=False):
  params = dict(d["params"])
  params.update(overrides or {})
  ctl = Controller(d["cp_bytes"], params, testing_ground)
  n = len(d["t"])
  out = np.zeros(n)
  des = np.zeros(n)
  try:
    for k in range(n):
      steer_limited = abs(d["cc_torque"][k] - d["co_torque"][k]) > 1e-2
      out[k], des[k] = ctl.step(d, k, d["angle"][k], d["rate"][k], steer_limited)
  finally:
    ctl.close()
  return out, des


# ----------------------------------------------------------------------------------------------
# replay with the logged integrator freeze
#
# The integrator freezes on steer_limited_by_safety, which controlsd derives from carControl vs the
# latest carOutput. The log interleaves those messages too coarsely to recover which frame each
# comparison used, so the check below takes the freeze pattern from the log itself (logged I
# unchanged from the previous frame). Everything else is recomputed.

def replay_logged_freeze(d, overrides=None, testing_ground=False):
  params = dict(d["params"])
  params.update(overrides or {})
  ctl = Controller(d["cp_bytes"], params, testing_ground)
  li = d["log_i"]
  frozen = np.r_[False, li[1:] == li[:-1]]
  out = np.zeros(len(li))
  try:
    for k in range(len(li)):
      out[k], _ = ctl.step(d, k, d["angle"][k], d["rate"][k], frozen[k])
  finally:
    ctl.close()
  return out


def replay_report(d, overrides=None):
  act = d["active"] > 0.5
  print(f"== {d['route']}  replay (open loop)  {act.sum() / 100 / 60:.1f} min active  overrides {overrides or {}}")
  for label, out in (("logged tuning params, freeze recomputed", replay(d, overrides)[0]),
                     ("logged tuning params, logged freeze", replay_logged_freeze(d, overrides))):
    e = out[act] - d["out"][act]
    print(f"  {label:42s} torque |sim-log| median {np.median(abs(e)):.1e}  p99 {np.percentile(abs(e), 99):.1e}" +
          f"  (logged |out| median {np.median(abs(d['out'][act])):.3f})")


# ----------------------------------------------------------------------------------------------
# 3. plant: delivered torque command -> steering angle
#
#   rate' = (c0 + c1 v) rate + (c2 + c3 v^2/100) theta + (c4 + c5 v + c6 v^2/100) u + c7 + c8 tanh(rate / 2)
#   theta' = rate
#
# theta is the steering angle minus paramsd's learned offset, rate the logged steering rate (it
# tracks a 50 ms angle derivative at r = 0.96; the angle itself is 0.1 deg quantised), u the
# delivered command (carOutput.actuatorsOutput.torque). Delay 0: a delay grid 0-250 ms fitted worst
# at every nonzero delay on held-out data. Fitted by Levenberg-Marquardt on free-run angle error over
# 1 s windows of engaged, hands-off driving above 4 m/s. The driver torque sensor is deliberately
# not an input: it carries the logged trajectory and would bias any comparison towards the tuning
# that was actually driven.

PLANT_WIN = 100
PLANT_STRIDE = 50


# The command reaches the rack DELAY frames late. Without it the fitted plant answered the command in the
# same frame, the closed loop had more phase margin than the car, and the sim under-predicted weave
# (sign changes 0.5-0.6 /s against 0.8 logged, item 113). fit_plant picks the delay from FIT_DELAYS by
# free-run residual. The angle sensor reports 0.1 deg steps (STEER_ANGLE factor), so the controller and
# the metrics see the quantised angle, as on the car. STATUS 132: most of that gap was the quantisation
# (raw zero crossings count sensor steps); with the analyzer's deadband the undelayed plant already matched
# the logs, and 5 frames of delay matches both counts best.
FIT_DELAYS = (0, 2, 4, 6, 8, 10, 12, 15, 20)
# Optional tenth coefficient: a centring pull that is about the same at any angle past a few degrees (c9 tanh(th /
# CENTRING_DEG)). Below 25 mph the logged hold command is ~0.14 of table torque plus ~0.003 per degree (routes
# after 6 Aug, quasi-steady, hands off), which the linear spring alone cannot give; without it the sim holds
# low-speed curves at 0.94-0.95 of the desired angle against 0.87 logged (STATUS 147). Fit with centring=True.
CENTRING_DEG = 2.0
ANGLE_QUANT_DEG = 0.1
SIGN_HYST_DEG = 0.15   # lat_tune_analyzer.SIGN_HYST_DEG


class Plant:
  """eps: an eps_fw.EpsTable. With one, u in accel() is the table torque (EpsTable.drive of the delivered command)
  rather than the command itself, and the table can be swapped for another image's (with_eps) at sim time."""
  def __init__(self, coef, delay=0, quant=0.0, eps=None):
    self.c = np.asarray(coef, dtype=float)
    self.delay = int(delay)
    self.quant = float(quant)
    self.eps = eps

  @staticmethod
  def from_json(j):
    if j.get("bands"):
      return BandedPlant.from_json(j)
    # Plants fitted before the delay existed carry neither key and keep their old, undelayed behaviour.
    eps = None
    if j.get("eps"):
      from openpilot.tools.lateral.eps_fw import EpsTable
      eps = EpsTable.from_json(j["eps"])
    return Plant(j["coef"], j.get("delay_frames", 0), j.get("angle_quant_deg", 0.0), eps)

  def drive(self, u):
    """Plant input for a delivered command."""
    return u if self.eps is None else self.eps.drive(u)

  def with_eps(self, eps):
    """This plant with another image's torque table. Only a plant fitted through a table has the units for it."""
    if self.eps is None:
      raise ValueError("plant was fitted on the raw command; refit it with --eps-rwd before swapping the table")
    return Plant(self.c, self.delay, self.quant, eps)

  def measure(self, theta):
    return float(np.round(theta / self.quant) * self.quant) if self.quant > 0 else theta

  def accel(self, theta, rate, u, v):
    c = self.c
    return ((c[0] + c[1] * v) * rate + (c[2] + c[3] * v * v / 100) * theta
            + (c[4] + c[5] * v + c[6] * v * v / 100) * u + c[7] + c[8] * np.tanh(rate / 2.0)
            + (c[9] * np.tanh(theta / CENTRING_DEG) if len(c) > 9 else 0.0))

  def to_json(self):
    return {"coef": self.c.tolist(), "delay_frames": self.delay, "angle_quant_deg": self.quant,
            "eps": self.eps.to_json() if self.eps is not None else None,
            "model": "rate' = (c0+c1 v) r + (c2+c3 v^2/100) th + (c4+c5 v+c6 v^2/100) u(t - delay) + c7 + c8 tanh(r/2)" +
                     (" + c9 tanh(th/%g)" % CENTRING_DEG if len(self.c) > 9 else "")}


class BandedPlant(Plant):
  """Two plants fitted on separate speed ranges, blended linearly between blend_mph[0] and blend_mph[1]: `low`
  below, `high` above. STATUS 147: one plant fitted on every speed held low-speed curves at 0.94 of the desired
  angle against 0.87 logged; a plant fitted below 25 mph only (with the centring term) reads 0.91. Both must share
  the delay, quantisation and torque table, which the delivered command passes through once, outside accel()."""
  def __init__(self, low, high, blend_mph=(22.0, 28.0)):
    if (low.delay, low.quant) != (high.delay, high.quant) or (low.eps is None) != (high.eps is None) or \
       (low.eps is not None and low.eps.sha1 != high.eps.sha1):
      raise ValueError("banded plant halves differ in delay, quantisation or torque table")
    super().__init__(high.c, high.delay, high.quant, high.eps)
    self.low, self.high = low, high
    self.blend_mph = (float(blend_mph[0]), float(blend_mph[1]))

  @staticmethod
  def from_json(j):
    low, high = (Plant.from_json(b) for b in j["bands"])
    return BandedPlant(low, high, j.get("blend_mph", (22.0, 28.0)))

  def with_eps(self, eps):
    return BandedPlant(self.low.with_eps(eps), self.high.with_eps(eps), self.blend_mph)

  def accel(self, theta, rate, u, v):
    lo, hi = self.blend_mph[0] * MPH, self.blend_mph[1] * MPH
    w = min(max((v - lo) / (hi - lo), 0.0), 1.0)
    if w <= 0.0:
      return self.low.accel(theta, rate, u, v)
    if w >= 1.0:
      return self.high.accel(theta, rate, u, v)
    return (1.0 - w) * self.low.accel(theta, rate, u, v) + w * self.high.accel(theta, rate, u, v)

  def to_json(self):
    return {"bands": [self.low.to_json(), self.high.to_json()], "blend_mph": list(self.blend_mph)}


def load_plant(path):
  """A plant JSON (single or banded) with its metadata keys ("car", "eps_fw", ...) ignored."""
  with open(path) as f:
    return Plant.from_json(json.load(f))


def _hands_off(d):
  return (d["active"] > 0.5) & (d["pressed"] < 0.5) & (d["v"] > 4.0)


def _windows(d, win, stride):
  m = _hands_off(d)
  cs = np.r_[0, np.cumsum(~m)]
  st = np.arange(1, len(m) - win - 1, stride)
  return st[(cs[st + win + 1] - cs[st]) == 0]


def _pack(ds, win, stride):
  """Windows of `win` frames; "u" also holds the max(FIT_DELAYS) delivered commands before each window."""
  pre = max(FIT_DELAYS)
  parts = []
  for d in ds:
    st = _windows(d, win, stride)
    st = st[st >= pre]
    if len(st) == 0:
      continue
    idx = st[:, None] + np.arange(win + 1)[None, :]
    uidx = st[:, None] + np.arange(-pre, win + 1)[None, :]
    parts.append({"v": d["v"][idx], "u": d["co_torque"][uidx], "th": d["angle"][idx] - d["offset"][idx], "r": d["rate"][idx]})
  return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def _plant_freerun(p, plant):
  """p["u"] is the plant input: already through plant.drive."""
  th = p["th"][:, 0].copy()
  r = p["r"][:, 0].copy()
  out = np.zeros_like(p["th"])
  out[:, 0] = th
  u0 = max(FIT_DELAYS) - plant.delay
  for j in range(p["th"].shape[1] - 1):
    r = r + plant.accel(th, r, p["u"][:, u0 + j], p["v"][:, j]) * DT
    th = th + r * DT
    out[:, j + 1] = th
  return out


def fit_plant(ds, iters=60, verbose=True, delays=FIT_DELAYS, eps=None, centring=False):
  """Fits the coefficients at each candidate delay and keeps the delay with the lowest free-run residual.
  With eps (an EpsTable) the command goes through that firmware table first; use the image the drives ran on."""
  p = _pack(ds, PLANT_WIN, PLANT_STRIDE)
  if eps is not None:
    p["u"] = eps.drive(p["u"])
  best = None
  for delay in delays:
    plant, cost = _fit_coef(p, delay, iters, verbose, centring)
    if verbose:
      print(f"  delay {delay:2d} frames: window rms {np.sqrt(cost):.3f} deg")
    if best is None or cost < best[1]:
      best = (plant, cost)
  best[0].quant = ANGLE_QUANT_DEG
  best[0].eps = eps
  return best[0], p["v"].shape[0]


def _fit_coef(p, delay, iters, verbose, centring=False):
  def resid(c):
    return (_plant_freerun(p, Plant(c, delay)) - p["th"])[:, 10::10].ravel()

  c = np.array([-8.0, 0.0, -2.0, 0.0, 300.0, 0.0, 0.0, 0.0, 0.0] + ([0.0] if centring else []))
  lam = 1e-2
  r0 = resid(c)
  for it in range(iters):
    J = np.zeros((len(r0), len(c)))
    for i in range(len(c)):
      h = 1e-4 * max(1.0, abs(c[i]))
      cc = c.copy()
      cc[i] += h
      J[:, i] = (resid(cc) - r0) / h
    A = J.T @ J
    g = J.T @ r0
    improved = False
    while lam < 1e8:
      cn = c + np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), -g)
      rn = resid(cn)
      if np.isfinite(rn).all() and rn @ rn < r0 @ r0:
        rel = 1 - (rn @ rn) / (r0 @ r0)
        c, r0, lam, improved = cn, rn, max(lam / 3, 1e-6), True
        break
      lam *= 5
    if verbose > 1:
      print(f"  fit it {it:2d}  window rms {np.sqrt(np.mean(r0 ** 2)):.3f} deg")
    if not improved or rel < 1e-6:
      break
  return Plant(c, delay), float(np.mean(r0 ** 2))


def plant_holdout(ds, plant, win=300, stride=100):
  """Free-run error at the end of `win`-frame windows, and the error of just holding the start angle."""
  p = _pack(ds, win, stride)
  p["u"] = plant.drive(p["u"])
  s = _plant_freerun(p, plant)
  return (float(np.sqrt(np.mean((s[:, -1] - p["th"][:, -1]) ** 2))),
          float(np.sqrt(np.mean((p["th"][:, 0] - p["th"][:, -1]) ** 2))), p["v"].shape[0])


# ----------------------------------------------------------------------------------------------
# 4. closed loop

class CarControllerSteer:
  """The steering-torque stages of the Honda carcontroller that can make the delivered command differ
  from CC.actuators.torque: minimum steer speed, the driver-override ramp and the optional delta limiter.
  Mirrors CarController._update_steering_torque with NrdrIncreaseOverrideTolerance off (raw steeringPressed)."""
  def __init__(self, params):
    def g(k, dflt):
      return float(params.get(k, dflt))
    self.min_speed = min(max(g("NrdrMinSteerSpeed", 1), 0), 45) * MPH
    self.override_scale = min(max(g("HondaOverrideTorqueScale", 0), 0), 100) / 100.0
    self.fade_up = g("HondaOverrideFadeUpSecs", 1.0)
    self.fade_down = g("HondaOverrideFadeDownSecs", 0.0)
    self.delta = _truthy(params.get("HondaSteerDeltaLimiter"), default=False)
    self.up = g("HondaSteerDeltaUp", 3.0)
    self.down = g("HondaSteerDeltaDown", 3.0)
    self.ramp = 0.0
    self.last = 0.0
    self.active_prev = False

  def step(self, cmd, active, v, pressed):
    cmd = cmd if active else 0.0
    if v < self.min_speed:
      cmd = 0.0
    if active:
      if not self.active_prev:
        self.ramp = 0.0
      if pressed:
        self.ramp = self.override_scale if self.fade_down <= 0 else max(self.override_scale, self.ramp - DT / self.fade_down)
      else:
        self.ramp = 1.0 if self.fade_up <= 0 else min(1.0, self.ramp + DT / self.fade_up)
      cmd *= self.ramp
    else:
      self.ramp = 0.0
    if self.delta:
      cmd = min(max(cmd, self.last - self.down * DT), self.last + self.up * DT)
    self.last = cmd
    self.active_prev = active
    return cmd


def simulate(d, plant, overrides=None, testing_ground=False, with_raw=False, kind="pid", torque=None):
  """Closed loop. While engaged, hands off and above 4 m/s the plant integrates the delivered command;
  everywhere else the state is re-synced to the log (the driver, or nobody, is steering). with_raw adds
  the target before the slew clip and smoothing, which the logged desired angle already includes."""
  params = dict(d["params"])
  params.update(overrides or {})
  ctl = Controller(d["cp_bytes"], params, testing_ground, kind=kind, torque=torque)
  ccs = CarControllerSteer(params)
  n = len(d["t"])
  ang = np.zeros(n)
  des = np.zeros(n)
  out = np.zeros(n)
  deliv = np.zeros(n)
  raw = np.zeros(n)
  sim_on = _hands_off(d)
  th = d["angle"][0]
  r = d["rate"][0]
  steer_limited = False
  try:
    for k in range(n):
      if not sim_on[k]:
        th, r = d["angle"][k], d["rate"][k]
      ang[k] = plant.measure(th) if sim_on[k] else th
      out[k], des[k] = ctl.step(d, k, ang[k], r, steer_limited)
      raw[k] = ctl.raw_target()
      deliv[k] = ccs.step(out[k], d["active"][k] > 0.5, d["v"][k], d["pressed"][k] > 0.5)
      steer_limited = (d["active"][k] > 0.5) and abs(out[k] - deliv[k]) > 1e-2
      if sim_on[k]:
        th_rel = th - d["offset"][k]
        r = r + plant.accel(th_rel, r, plant.drive(deliv[max(k - plant.delay, 0)]), d["v"][k]) * DT
        th = th + r * DT
  finally:
    ctl.close()
  return (ang, des, out, deliv, raw) if with_raw else (ang, des, out, deliv)


def metrics(d, ang, des, mask=None, raw=None, cmd=None):
  """Same definitions as the owner-facing lateral report: per speed band, engaged and hands off. With raw
  (the unshaped target) also the error, lag and curve-entry ratio against it, so target smoothing shows.
  With cmd (the delivered torque command) also its frame-to-frame rms change, x100 (command units per s)."""
  m0 = _hands_off(d) if mask is None else mask
  v = d["v"]
  res = {}
  for name, lo, hi in BANDS:
    m = m0 & (v >= max(lo, 4.0)) & (v < hi)
    if m.sum() < 3000:
      res[name] = None
      continue
    e = des[m] - ang[m]
    cur = m & (np.abs(des) > 5)
    st = m & (np.abs(des) < 3)
    es = des[st] - ang[st]
    res[name] = {
      "min": m.sum() / 100 / 60,
      "err_rms": float(np.sqrt(np.mean(e ** 2))),
      "bias": float(e.mean()),
      "curve_ratio": float(np.median(ang[cur] / des[cur])) if cur.sum() > 300 else None,
      "curve_s": cur.sum() / 100,
      "straight_rms": float(np.sqrt(np.mean(es ** 2))) if st.sum() else None,
      "zero_cross": float(np.sum(np.diff(np.sign(es)) != 0) / (st.sum() / 100)) if st.sum() else None,
      "sign_hyst": sign_changes(des - ang, st) / (st.sum() / 100) if st.sum() else None,
      "lag_s": tracking_lag(des, ang, cur),
    }
    if raw is not None:
      rcur = m & (np.abs(raw) > 5)
      en = rcur & curve_entry(raw)
      res[name].update({
        "err_rms_raw": float(np.sqrt(np.mean((raw[m] - ang[m]) ** 2))),
        "lag_raw_s": tracking_lag(raw, ang, rcur),
        "entry_ratio_raw": float(np.median(ang[en] / raw[en])) if en.sum() > 300 else None,
      })
    if cmd is not None:
      dm = m[1:] & m[:-1]
      res[name]["cmd_jitter"] = float(np.sqrt(np.mean((np.diff(cmd)[dm] / DT) ** 2)))
  return res


def curve_entry(des, frames=10, rate=5.0):
  """Frames where |des| grows faster than rate deg/s over the last frames (lat_tune_analyzer's entry part)."""
  a = np.abs(des)
  grow = np.zeros(len(a))
  grow[frames:] = (a[frames:] - a[:-frames]) / (frames * DT)
  return grow > rate


def sign_changes(err, straight):
  """Straight-frame error sign changes with the analyzer's deadband: a change needs a swing from >= +h to <= -h
  (or back), and the count restarts at every frame that is not straight, as DriveStats.observe does."""
  prev = 0
  n = 0
  for e, s in zip(err, straight, strict=True):
    if not s:
      prev = 0
      continue
    sign = 1 if e >= SIGN_HYST_DEG else -1 if e <= -SIGN_HYST_DEG else 0
    if sign and prev and sign != prev:
      n += 1
    if sign:
      prev = sign
  return n


def tracking_lag(des, ang, mask, max_frames=60):
  """Shift (s) of the angle behind the desired that minimises the curve-frame error, or None."""
  idx = np.where(mask)[0]
  idx = idx[idx + max_frames < len(ang)]
  if len(idx) < 300:
    return None
  costs = [np.mean((des[idx] - ang[idx + k]) ** 2) for k in range(max_frames + 1)]
  return int(np.argmin(costs)) * DT


def _fmt(x, f):
  return "  -  " if x is None else format(x, f)


def print_metrics(label, res):
  print(f"  {label}")
  for name, r in res.items():
    if r is None:
      print(f"    {name:15s} too little data")
      continue
    print(f"    {name:15s} {r['min']:4.1f} min | err rms {r['err_rms']:5.2f} deg  bias {r['bias']:+.2f} | curve actual/des " +
          f"{_fmt(r['curve_ratio'], '.3f')} ({r['curve_s']:.0f} s) | straight rms {_fmt(r['straight_rms'], '.2f')}" +
          f"  sign changes {_fmt(r['zero_cross'], '.1f')}/s ({_fmt(r['sign_hyst'], '.2f')}/s at {SIGN_HYST_DEG} deg)" +
          f" | lag {_fmt(r['lag_s'], '.2f')} s")
    if "err_rms_raw" in r:
      jit = f"  cmd rate rms {r['cmd_jitter']:.2f}/s" if "cmd_jitter" in r else ""
      print(f"    {'':15s} vs unshaped target: err rms {r['err_rms_raw']:5.2f} deg  lag {_fmt(r['lag_raw_s'], '.2f')} s" +
            f"  entry actual/target {_fmt(r['entry_ratio_raw'], '.3f')}{jit}")


# ----------------------------------------------------------------------------------------------

def load(route_dirs):
  return [extract(r) for r in route_dirs]


def _overrides(pairs):
  out = {}
  for p in pairs or []:
    k, _, v = p.partition("=")
    out[k.strip()] = v.strip()
  return out


def stiffness(cp_bytes, params, kind="pid", torque=None, speeds=(5, 10, 15, 20, 25, 30), disps=(2.0, 5.0, 10.0),
              settle=300, hold=100):
  """How hard the controller pushes back on a driver who has not (yet) tripped steeringPressed: engaged on a
  straight (desired curvature 0) with the wheel held at 0, then held at +disp deg (the driver's hand) for hold
  frames. Returns {speed: {disp: (command after 0.1 s, command after hold)}}. The command is what the car would
  deliver before the override ramp; the growth between the two columns is the integrator winding against the hand."""
  res = {}
  for v in speeds:
    res[v] = {}
    for disp in disps:
      n = settle + hold
      d = {k: np.zeros(n) for k in FIELDS}
      d["v"][:] = v
      d["active"][:] = 1.0
      d["sr"][:] = 16.0
      d["stiff"][:] = 1.0
      ctl = Controller(cp_bytes, params, kind=kind, torque=torque)
      try:
        outs = []
        for k in range(n):
          out, _ = ctl.step(d, k, 0.0 if k < settle else disp, 0.0, False)
          outs.append(out)
      finally:
        ctl.close()
      res[v][disp] = (outs[settle + 10], outs[-1])
  return res


def parse_variant(spec):
  """NAME=KIND[,key=value...]. Keys in TORQUE_DEFAULTS tune the torque kinds (vgr=1 turns the firmware map on);
  any other key is a param override (e.g. pid+rff=pid,NrdrLatRateFF=0.5)."""
  name, _, rest = spec.partition("=")
  kind, *kvs = rest.split(",")
  if kind not in KINDS:
    raise ValueError(f"{spec}: kind must be one of {KINDS}")
  torque, over = {}, {}
  for kv in kvs:
    k, _, v = kv.partition("=")
    k, v = k.strip(), v.strip()
    if k in TORQUE_DEFAULTS or k in PID_GAIN_KEYS:
      torque[k] = _truthy(v) if k == "vgr" else float(v)
    else:
      over[k] = v
  return name, kind, torque, over


def main(argv=None):
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = ap.add_subparsers(dest="cmd", required=True)
  p = sub.add_parser("replay", help="open-loop check of the controller harness against the log")
  p.add_argument("routes", nargs="+")
  p.add_argument("--set", action="append", help="param override KEY=VALUE, e.g. HondaLateralPidKpScale=1.0")
  p = sub.add_parser("fit", help="fit the steering plant")
  p.add_argument("routes", nargs="+")
  p.add_argument("--out", required=True)
  p.add_argument("--delay", type=int, help="fit at this command delay (frames) instead of picking from FIT_DELAYS; " +
                 "on 263/268/271 the free-run picks 0 but 5 matches the closed-loop sign changes best (STATUS 132)")
  p.add_argument("--eps-rwd", help="fit through this C020 image's torque table (the image the drives ran on)")
  p.add_argument("--eps-row", type=int, default=0, help="table row (default 0, STATUS 146)")
  p = sub.add_parser("validate", help="plant free-run and closed-loop-at-logged-settings vs the log")
  p.add_argument("routes", nargs="+")
  p.add_argument("--plant", required=True)
  p.add_argument("--set", action="append", help="param override applied to every route (e.g. an ineffective Kp scale)")
  p = sub.add_parser("sim", help="closed loop with tuning overrides")
  p.add_argument("routes", nargs="+")
  p.add_argument("--plant", required=True)
  p.add_argument("--base", action="append", help="override applied to both runs (e.g. the effective Kp scale)")
  p.add_argument("--set", action="append", required=True)
  p = sub.add_parser("sweep", help="closed loop over values of one param")
  p.add_argument("routes", nargs="+")
  p.add_argument("--plant", required=True)
  p.add_argument("--base", action="append")
  p.add_argument("--param", required=True)
  p.add_argument("--values", required=True)
  p = sub.add_parser("compare", help="closed loop, several controllers on the same routes")
  p.add_argument("routes", nargs="+")
  p.add_argument("--plant", required=True)
  p.add_argument("--base", action="append", help="param override applied to every variant")
  p.add_argument("--variant", action="append", required=True,
                 help="NAME=KIND[,key=value...], KIND in " + "|".join(KINDS) +
                 f"; torque keys {sorted(TORQUE_DEFAULTS)} (defaults {TORQUE_DEFAULTS}), others are param overrides")
  for name in ("validate", "sim", "sweep", "compare"):
    sp = sub.choices[name]
    sp.add_argument("--eps-rwd", action="append", help="run through this C020 image's torque table instead of the one the " +
                    "plant was fitted with (repeat to compare images); needs a plant fitted with --eps-rwd")
    sp.add_argument("--eps-row", type=int, default=0)
  p = sub.add_parser("stiffness", help="push-back on a held wheel before an override is detected (no plant)")
  p.add_argument("routes", nargs="+", help="CarParams and logged params are taken from the first route")
  p.add_argument("--base", action="append")
  p.add_argument("--variant", action="append", required=True, help="as for compare")
  args = ap.parse_args(argv)

  if args.cmd == "replay":
    for d in load(args.routes):
      replay_report(d, _overrides(args.set))
    return

  if args.cmd == "fit":
    ds = load(args.routes)
    eps = None
    if args.eps_rwd:
      from openpilot.tools.lateral.eps_fw import EpsTable
      eps = EpsTable.from_rwd(args.eps_rwd, args.eps_row)
    plant, nwin = fit_plant(ds, delays=FIT_DELAYS if args.delay is None else (args.delay,), eps=eps)
    j = plant.to_json()
    j.update({"routes": [d["route"] for d in ds], "windows": int(nwin), "window_s": PLANT_WIN * DT})
    with open(args.out, "w") as f:
      json.dump(j, f, indent=1)
    print(f"plant written to {args.out}: delay {plant.delay} frames, {np.round(plant.c, 3).tolist()}")
    return

  if args.cmd == "stiffness":
    d = load(args.routes[:1])[0]
    base = _overrides(args.base)
    print(f"{d['route']} CarParams; command (1.0 = full) against a wheel held off-centre on a straight, " +
          "at 0.1 s / after 1 s; no plant, no override ramp")
    for spec in args.variant:
      name, kind, torque, over = parse_variant(spec)
      print(f"  {name} [{kind} {torque or ''} {over or ''}]")
      for v, row in stiffness(d["cp_bytes"], {**d["params"], **base, **over}, kind, torque).items():
        cells = "  ".join(f"{disp:4.0f} deg {a:+.3f}/{b:+.3f}" for disp, (a, b) in row.items())
        print(f"    {v:4.0f} m/s ({v / MPH:3.0f} mph)  {cells}")
    return

  with open(args.plant) as f:
    pj = json.load(f)
  fitted = Plant.from_json(pj)
  ds = load(args.routes)
  for plant, label in eps_plants(fitted, args.eps_rwd, args.eps_row):
    if label:
      print(f"#### EPS table: {label}")
    _run(args, pj, plant, ds)


def eps_plants(plant, rwds, row=0):
  """[(plant, label)]: the fitted plant as is, or once per image with that image's torque table swapped in."""
  if not rwds:
    return [(plant, plant.eps.source + " (fitted)" if plant.eps is not None else "")]
  from openpilot.tools.lateral.eps_fw import EpsTable
  out = []
  for path in rwds:
    eps = EpsTable.from_rwd(path, row)
    label = f"{eps.source} row {eps.row}"
    diff = plant.eps.controller_diff(eps) if plant.eps is not None else {}
    if diff:
      label += ("\n  WARNING: controller words differ from the fitted image and are NOT modelled (only the table is): " +
                ", ".join(f"{k} {a} -> {b}" for k, (a, b) in diff.items()))
    out.append((plant.with_eps(eps), label))
  return out


def _run(args, pj, plant, ds):
  if args.cmd == "validate":
    ov = _overrides(args.set)
    print(f"plant fitted on {pj.get('routes')}, delay {plant.delay} frames, angle step {plant.quant} deg")
    for d in ds:
      e, hold, n = plant_holdout([d], plant)
      held = "" if d["route"] in pj.get("routes", []) else "  (held out)"
      print(f"== {d['route']}{held}  plant free-run 3 s end error {e:.2f} deg (hold-angle baseline {hold:.2f}, {n} windows)")
      print_metrics("logged", metrics(d, d["angle"], d["des_angle"]))
      ang, des, _, _ = simulate(d, plant, ov)
      print_metrics(f"sim at logged settings {ov or ''}", metrics(d, ang, des))
    return

  base = _overrides(args.base)
  if args.cmd == "compare":
    vs = [parse_variant(v) for v in args.variant]
    for d in ds:
      print(f"== {d['route']}  (plant-simulated; desired curvature held to the log; each scored against its own target)")
      for name, kind, torque, over in vs:
        ang, des, _, deliv, raw = simulate(d, plant, {**base, **over}, with_raw=True, kind=kind, torque=torque)
        print_metrics(f"{name} [{kind} {torque or ''} {over or ''}]", metrics(d, ang, des, raw=raw, cmd=deliv))
    return
  if args.cmd == "sim":
    variants = [("baseline " + str(base or "logged"), base), ("with " + str(_overrides(args.set)), {**base, **_overrides(args.set)})]
  else:
    variants = [(f"{args.param}={v}", {**base, args.param: v}) for v in args.values.split(",")]
  for d in ds:
    print(f"== {d['route']}  (plant-simulated; desired curvature held to the log)")
    for label, ov in variants:
      ang, des, _, _, raw = simulate(d, plant, ov, with_raw=True)
      print_metrics(label, metrics(d, ang, des, raw=raw))


if __name__ == "__main__":
  main()
