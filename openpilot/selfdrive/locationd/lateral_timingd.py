#!/usr/bin/env python3
"""lateral_timingd: the live lateral timing estimator (lateral_timing.py), SHADOW MODE.

It learns the car's slow timing terms and each model's aim from normal driving and logs what it would set, but it
changes nothing: no params, no message the controller or modeld reads. Results go to the rlog as logMessage events
("lateralTiming.turn" per turning window, "lateralTiming.state" on every change and once a minute), and the learned
state persists across drives in STATE_PATH. It runs only on cars steered by the Honda EPS controller.

Disable it by creating DISABLE_PATH. Delete STATE_PATH to start learning over.
"""
import dataclasses
import hashlib
import json
import math
import os
import time
import uuid
from collections import deque

import numpy as np

from openpilot.selfdrive.locationd.lateral_timing import (Streams, TimingLearner, band_name, find_turns, load_state, save_state,
                                                           slow_composite, size_correction, AIM_SLOPE, MAX_LAG)

STATE_DIR = "/data/lateral_timing"
STATE_PATH = os.path.join(STATE_DIR, "state.json")
DISABLE_PATH = os.path.join(STATE_DIR, "disabled")

BUFFER_S = 180.0        # raw streams kept, enough for the longest turning window plus its padding
STEP_S = 2.0            # how often the buffer is searched for finished windows
CLOSE_MARGIN_S = 2.0    # a window is final once this much later data exists (steeringPressed look-ahead, model latency)
STATE_LOG_S = 60.0
# card publishes carState this long after the CAN packet it decodes (Clarity 7.x rlogs: median 4.3-4.6 ms, p10-p90
# 4.0-5.3 ms): the yaw sample is that much older than carState's own time
CARSTATE_LATENCY_S = 0.0045

# controller settings target -> wheel depends on: a change re-learns S
SETTINGS_KEYS = ("HondaTorqueOutputLowPassFilter", "HondaTorqueOutputLpfTauLowSpeed", "HondaTorqueOutputLpfTauStandard",
                 "HondaTorqueOutputLpfTauHighway", "LatPScaleLowSpeed", "LatPScaleStandard", "LatIScaleLowSpeed",
                 "LatIScaleStandard", "LatFScaleLowSpeed", "LatFScaleStandard", "HondaSteerDeltaUp", "HondaSteerDeltaDown",
                 "HondaSteerDeltaLimiter", "HondaEpsAngleRateLimit")


def _hash(*parts) -> str:
  return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:12]


def calibration_hash(calibration) -> str:
  """The calibration as far as target -> wheel goes: its delays are what the estimator sets, so they are left out."""
  return _hash(repr(dataclasses.replace(calibration, cmd_delay_s=0.0, cmd_delay_highway_s=0.0, lat_delay_schedule=())))


def settings_hash(params) -> str:
  vals = []
  for k in SETTINGS_KEYS:
    try:
      vals.append(f"{k}={params.get(k)!r}")
    except Exception:
      vals.append(f"{k}=?")
  return _hash(*vals)


def code_hash(paths) -> str:
  """The controller's own code (latcontrol_honda_eps.py, honda_eps_firmware_ff.py): a change re-learns S."""
  h = hashlib.sha1()
  for path in paths:
    try:
      with open(path, "rb") as f:
        h.update(f.read())
    except OSError:
      h.update(str(path).encode())
  return h.hexdigest()[:12]


def rack_converter(rack):
  """HondaEpsRackMap.curvature_from_angle over arrays (the same arithmetic, vectorized)."""
  G = 9.81
  ag, pg, wb, sf = rack.angle_grid, rack.path_grid, rack.wheelbase, rack.slip_factor

  def conv(angle, v, roll):
    a = np.abs(np.asarray(angle, float))
    path = np.where(a > ag[-1], pg[-1] * a / ag[-1], np.interp(a, ag, pg)) * np.sign(angle)
    return -(path / wb + G * sf * np.asarray(roll, float)) / (1.0 - sf * np.asarray(v, float) ** 2)
  return conv


def model_key(raw: str) -> str | None:
  """modelIdentity's logMessage (a modeld.loaded record) -> 'modelId:sha12'."""
  try:
    msg = json.loads(raw).get("msg", {})
  except (ValueError, AttributeError):
    return None
  if not isinstance(msg, dict) or msg.get("event") != "modeld.loaded":
    return None
  return f"{msg.get('modelId')}:{str(msg.get('artifactSha256') or '')[:12]}"


class LateralTimingRunner:
  """Feeds messages into the streams, searches finished windows, learns, and logs. The same object runs on the device
  (lateral_timingd.main) and in replay (tools/lateral/replay_lateral_timing.py)."""
  def __init__(self, conv, lss: float, keys: dict, state: dict | None, log, save=None, drive: str | None = None):
    self.conv, self.lss, self.log, self.save = conv, lss, log, save
    self.learner = TimingLearner(keys, state)
    self.drive = drive or uuid.uuid4().hex[:8]
    self.drive_counted = False
    self.s = Streams()
    self.frame_keys: deque = deque()       # (tp, model key) for each modelV2 row
    self.model: str | None = None
    self.source = "unknown"
    self.t1 = deque(maxlen=1200)
    self.told = {}                          # band -> recent told delays
    self.open_after = -math.inf
    self.aim_after = -math.inf
    self.last_step = -math.inf
    self.last_state_log = -math.inf
    self.turns: list = []                   # every accepted turn record of this run (replay reads it)
    if self.learner.reset_reason:
      self.log("lateralTiming.reset", reason=self.learner.reset_reason)

  # -- input ------------------------------------------------------------------------------------------------------
  def handle(self, which: str, t: float, msg) -> None:
    if which == "carState":
      self.s.cs.append((t, msg.vEgo, msg.steeringAngleDeg, float(msg.steeringPressed), msg.yawRate, t - CARSTATE_LATENCY_S))
    elif which == "carControl":
      self.s.cc.append((t, float(msg.latActive)))
    elif which == "controlsState":
      lcs = msg.lateralControlState
      des = lcs.pidState.steeringAngleDesiredDeg if lcs.which() == "pidState" else float("nan")
      self.s.ctl.append((t, msg.desiredCurvature, des))
    elif which == "vehicleParameters":
      self.s.lp.append((t, msg.angleOffsetDeg, msg.roll))
    elif which == "starpilotLateralState":
      if msg.epsCalibration:
        self.s.md.append((t, msg.epsModelDelay, msg.epsCommandDelay))
    elif which == "modelV2":
      if len(msg.orientation.z) == 33 and len(msg.velocity.x) == 33:
        tf = msg.timestampEof * 1e-9
        self.s.model.append(np.r_[t, tf, msg.action.desiredCurvature, np.asarray(msg.orientation.z),
                                  np.asarray(msg.orientationRate.z), np.asarray(msg.velocity.x)])
        self.frame_keys.append((t, self.model))
        self.t1.append(t - tf)
    elif which == "modelIdentity":   # msg is the event's logMessage text (the service carries Event.logMessage)
      key = model_key(msg)
      if key is not None and key != self.model:
        self.model = key
        self.log("lateralTiming.model", model=key)

  def set_source(self, source: str) -> None:
    self.source = source or "unknown"

  # -- processing -------------------------------------------------------------------------------------------------
  def step(self, now: float, force: bool = False) -> None:
    if not force and now - self.last_step < STEP_S:
      return
    self.last_step = now
    closed_before = now - CLOSE_MARGIN_S
    turns, frames = find_turns(self.s, self.conv, self.lss, closed_before, self.open_after + 0.5,
                               aim_from=min(self.open_after, self.aim_after) - 1.0)
    changed = False
    for rec in turns:
      self.open_after = max(self.open_after, rec["win_start"])
      if rec["rejected"]:
        continue
      changed |= self._turn(rec)
    if frames is not None:
      changed |= self._aims(frames, closed_before - MAX_LAG)
    if changed or now - self.last_state_log >= STATE_LOG_S:
      self._log_state(now)
    self.s.trim(now - BUFFER_S)
    while self.frame_keys and self.frame_keys[0][0] < now - BUFFER_S:
      self.frame_keys.popleft()

  def _turn(self, rec: dict) -> bool:
    S = slow_composite(rec)
    band = band_name(rec["v"])
    rec.update(S=S, band=band, size_corr=size_correction(rec["tgt_rate"]) if np.isfinite(rec["tgt_rate"]) else None,
               model=self.model, source=self.source, drive=self.drive)
    if S is not None and band is not None and not self.drive_counted:
      self.learner.drives += 1
      self.drive_counted = True
    event = self.learner.add_turn(rec, self.drive)
    rec["outcome"] = event   # not "event": that is cloudlog.event's own first argument
    if band is not None and rec.get("told") is not None:
      self.told.setdefault(band, deque(maxlen=50)).append(rec["told"])
    self.turns.append(rec)
    self.log("lateralTiming.turn", **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in rec.items()})
    if event is not None:
      self.log("lateralTiming." + event, band=band, **self.learner.bands[band].estimate())
    if S is not None and band is not None and self.save is not None:
      self.save(self.learner.to_dict())
    return S is not None and band is not None

  def _aims(self, frames: dict, upto: float) -> bool:
    tp, aim, told = frames["tp"], frames["aim"], frames["told"]
    sel = (tp > self.aim_after) & (tp <= upto)
    if not sel.any():
      return False
    self.aim_after = float(tp[sel].max())
    keys = dict(self.frame_keys)
    by_model: dict = {}
    for i in np.flatnonzero(sel & np.isfinite(aim) & np.isfinite(told)):
      k = keys.get(tp[i])
      if k is not None:
        by_model.setdefault(k, []).append(aim[i] - AIM_SLOPE * told[i])
    froze = False
    for k, offs in by_model.items():
      if self.learner.add_aims(k, offs):
        froze = True
        self.log("lateralTiming.aimFrozen", model=k, **self.learner.aims[k].estimate())
    return froze

  def estimate(self) -> dict:
    t1 = float(np.median(self.t1)) if self.t1 else float("nan")
    told_now = {b: float(np.median(v)) for b, v in self.told.items() if v}
    return self.learner.estimate(self.model, self.source, t1, self.lss, told_now)

  def _log_state(self, now: float) -> None:
    self.last_state_log = now
    self.log("lateralTiming.state", drives=self.learner.drives, **self.estimate())
    if self.save is not None:
      self.save(self.learner.to_dict())


def main():
  from opendbc.car.structs import car
  import openpilot.cereal.messaging as messaging
  from openpilot.common.hardware import HARDWARE
  from openpilot.common.params import Params
  from openpilot.common.swaglog import cloudlog
  from openpilot.selfdrive.controls.lib import latcontrol_honda_eps, honda_eps_firmware_ff
  from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import eps_firmware_calibration, get_rack_map, lateral_smooth_seconds
  from opendbc.car.honda.steer_ratio import normalize_honda_eps_fw

  params = Params()
  CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  calibration = eps_firmware_calibration(CP)
  rack = get_rack_map(CP, calibration)
  if calibration is None or rack is None or os.path.exists(DISABLE_PATH):
    cloudlog.event("lateralTiming.idle", calibration=calibration.name if calibration else None, disabled=os.path.exists(DISABLE_PATH))
    while True:
      time.sleep(60)

  conv = rack_converter(rack)
  eps_fw = next((normalize_honda_eps_fw(fw.fwVersion) for fw in CP.carFw if fw.ecu == "eps"), None)
  keys = dict(fingerprint=str(CP.carFingerprint), eps_fw=eps_fw, calibration=calibration.name,
              calibration_hash=calibration_hash(calibration), settings=settings_hash(params),
              code=code_hash((latcontrol_honda_eps.__file__, honda_eps_firmware_ff.__file__)),
              device=HARDWARE.get_device_type())
  runner = LateralTimingRunner(conv, lateral_smooth_seconds(CP, 0.0), keys, load_state(STATE_PATH),
                               log=cloudlog.event, save=lambda d: save_state(STATE_PATH, d))
  cloudlog.event("lateralTiming.start", keys=keys, drive=runner.drive, drives=runner.learner.drives)

  services = ["carState", "carControl", "controlsState", "modelV2", "starpilotLateralState", "vehicleParameters"]
  sm = messaging.SubMaster(services, poll="carState", ignore_alive=services, ignore_valid=services)
  # modelIdentity carries Event.logMessage, which SubMaster would file under the wrong name: read it directly
  identity = messaging.sub_sock("modelIdentity", conflate=True)
  last_source = -math.inf
  while True:
    sm.update()
    for which in sorted((w for w in services if sm.updated[w]), key=lambda w: sm.logMonoTime[w]):
      runner.handle(which, sm.logMonoTime[which] * 1e-9, sm[which])
    if (ident := messaging.recv_one_or_none(identity)) is not None and ident.which() == "logMessage":
      runner.handle("modelIdentity", ident.logMonoTime * 1e-9, ident.logMessage)
    now = sm.logMonoTime["carState"] * 1e-9
    if now - last_source > 10.0:
      last_source = now
      src = params.get("ModelLateralSource")
      runner.set_source(src.decode() if isinstance(src, bytes) else (src or "unknown"))
    try:
      runner.step(now)
    except Exception:
      # shadow mode: a bug here must not crash-loop the process; log it and drop the buffered window
      cloudlog.exception("lateralTiming.error")
      runner.s.trim(now)


if __name__ == "__main__":
  main()
