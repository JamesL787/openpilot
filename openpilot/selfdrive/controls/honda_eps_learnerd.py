#!/usr/bin/env python3
"""Shadow daemon for the HondaEps car learner (controls/lib/honda_eps_car_learner.py).

Runs only on a car LatControlHondaEps steers, and only with HondaEpsLearner on (the default). It turns the drive into 60 s chunks,
feeds the learner, keeps its state in a file under /data and publishes what it found as the HondaEpsLearnerResult
param, which every route's initData then carries (tools/lateral/learner_result.py reads it back from a qlog).
Nothing reads the result back into the controller.
"""
import os
import struct
import time

import numpy as np

import openpilot.cereal.messaging as messaging
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, normalize_honda_eps_fw
from opendbc.car.honda.yaw_rate import DBC_SCALE, DBC_ZERO, LEARN_FRAMES, SETTLE_FRAMES, YAW_RATE_CALIBRATION, YawRateCalibration
from opendbc.car.structs import car
from openpilot.common.hardware import PC
from openpilot.common.hardware.hw import Paths
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib import honda_eps_car_learner as L
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import REQUIRED_PTM_RWD
from openpilot.selfdrive.controls.lib.honda_eps_firmware_ff import OVERRIDE_FADE_UP_S_DEFAULT
from openpilot.selfdrive.controls.lib.honda_lateral_common import _get_param_bool, _get_param_float

QUEUED = ('carState', 'carControl', 'sendcan', 'modelV2', 'gpsLocation', 'gpsLocationExternal')
LATEST = ('vehicleParameters', 'starpilotLateralState')
CHUNK_FRAMES = int(L.CHUNK_S / L.DT)
MIN_CHUNK_FRAMES = 1000
MAX_GAP_S = 0.5
SAVE_EVERY = 5  # chunks
STATE_DIR = os.getenv('HONDA_EPS_LEARNER_DIR', os.path.join(Paths.comma_home() if PC else '/data', 'honda_eps_learner'))
STATE_FILE = 'state.npz'


class FrameBuilder:
  """Per carState frame, the latest value of every other stream, cut into chunks that never span a gap. The replay
  tool feeds it log events, so both build the same chunks. On the car the yaw counts come back out of carState.yawRate
  through opendbc's calibration; a replay decodes the logged 0x94 instead (raw_yaw), because an old log's yawRate was
  made with whatever calibration its build had. Either way there is no yaw until carstate has learned this drive's zero
  at a standstill: its seed is one unit's (the CR-V's 509.5 is the A040 car's; the A220 car sits at 512.0)."""
  def __init__(self, yaw_calibration, raw_yaw=False):
    self.yaw_calibration = yaw_calibration
    self.yaw_decoder = YawRateCalibration(*yaw_calibration) if raw_yaw and yaw_calibration is not None else None
    self.yaw_bus, self.yaw_seen, self.raw = None, {}, None
    self.stopped_frames, self.zeroed = 0, False
    self.st = {'lat': 0.0, 'e4': 0.0, 'off': 0.0, 'roll': 0.0, 'act': np.nan, 'cmd_delay': np.nan}
    self._clear()

  def _clear(self):
    self.rows, self.models, self.gps = [], [], []

  def _chunk(self):
    rows, models, gps = self.rows, self.models, self.gps
    self._clear()
    if len(rows) < MIN_CHUNK_FRAMES:
      return None
    c = dict(zip(L.CHUNK_FIELDS, np.array(rows, float).T, strict=True))
    c['model'] = np.array(models, float) if models else None
    c['gps'] = np.array(gps, float) if gps else None
    return c

  def flush(self):
    return self._chunk()

  def handle(self, which, m, t):
    """A finished chunk, or None."""
    st = self.st
    if which == 'carState':
      out = self._chunk() if self.rows and (t - self.rows[-1][0] > MAX_GAP_S or len(self.rows) >= CHUNK_FRAMES) else None
      self.stopped_frames = self.stopped_frames + 1 if m.standstill else 0
      self.zeroed |= self.stopped_frames >= SETTLE_FRAMES + LEARN_FRAMES
      yawc = np.nan
      if self.yaw_decoder is not None:
        if self.raw is not None:
          self.yaw_decoder.update((self.raw - DBC_ZERO) * DBC_SCALE, m.standstill)
          if self.zeroed:
            yawc = self.raw - self.yaw_decoder.zero
      elif self.yaw_calibration is not None and self.zeroed:
        yawc = float(L.yaw_counts(m.yawRate, self.yaw_calibration[0], self.yaw_calibration[2]))
      self.rows.append((t, m.vEgo, m.aEgo, m.steeringAngleDeg, m.steeringRateDeg, m.steeringTorque, float(m.steeringPressed),
                        float(m.leftBlinker or m.rightBlinker), st['lat'], st['e4'], st['off'], st['roll'],
                        float(not (m.steerFaultTemporary or m.steerFaultPermanent)), yawc, st['act'], st['cmd_delay']))
      return out
    if which == 'sendcan':
      for msg in m:
        if msg.address == 0xE4:
          st['e4'] = struct.unpack('>h', msg.dat[0:2])[0]
    elif which == 'carControl':
      st['lat'] = float(m.latActive)
    elif which in ('vehicleParameters', 'liveParameters'):
      st['off'], st['roll'] = m.angleOffsetDeg, m.roll
    elif which == 'starpilotLateralState':
      st['cmd_delay'] = m.epsCommandDelay
    elif which == 'modelV2':
      st['act'] = m.action.desiredCurvature
      rate = np.array(m.orientationRate.z)
      if len(rate) == len(L.PLAN_T):
        self.models.append(np.r_[t, m.timestampEof * 1e-9, st['act'], rate / np.maximum(np.array(m.velocity.x), 1.0)])
    elif which in ('gpsLocation', 'gpsLocationExternal'):
      if m.hasFix or (m.flags & 1):  # logs before hasFix mark a fix in flags
        self.gps.append((t, m.bearingDeg, m.speed, m.bearingAccuracyDeg))
    elif which == 'can' and self.yaw_decoder is not None:
      for msg in m:
        if msg.address == 0x94 and msg.src < 3:
          if self.yaw_bus is None:
            self.yaw_seen[msg.src] = self.yaw_seen.get(msg.src, 0) + 1
            if self.yaw_seen[msg.src] > 50:
              self.yaw_bus = msg.src
          if msg.src == self.yaw_bus:
            self.raw = (msg.dat[0] << 2) | (msg.dat[1] >> 6)
    return None


def eps_fw_version(CP):
  return next((normalize_honda_eps_fw(fw.fwVersion) for fw in CP.carFw if fw.ecu == "eps"), None)


def learner_setup(CP, cal):
  """(wheelbase, firmware angle table, yaw calibration, identity) for the learner. The identity names the EPS version
  and the PTM image the calibration's law was built for: saved state from another one is dropped."""
  return (float(CP.wheelbase), get_honda_vgr_inverse(CP.flags), YAW_RATE_CALIBRATION.get(str(CP.carFingerprint)),
          f"{eps_fw_version(CP)}|{REQUIRED_PTM_RWD.get(cal.name, '')}")


def should_run(params, CP) -> bool:
  """manager: only on a car LatControlHondaEps steers, and only when asked for."""
  if not _get_param_bool(params, "HondaEpsLearner", True):
    return False
  from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import use_honda_eps_controller
  return use_honda_eps_controller(CP)


class LearnerRunner:
  def __init__(self, params, cal, setup, state_dir=None):
    self.params, self.cal = params, cal
    self.wheelbase, self.vgr_inverse, self.yaw_calibration, self.identity = setup
    self.path = os.path.join(STATE_DIR if state_dir is None else state_dir, STATE_FILE)
    self.fade_up_s = _get_param_float(params, "HondaOverrideFadeUpSecs", OVERRIDE_FADE_UP_S_DEFAULT, 0.0, 10.0)
    self.learner = None
    if not self._reset_requested():
      self.learner = self._load()
    if self.learner is None:
      self.learner = self._new()
      self.publish()

  def _new(self):
    return L.HondaEpsCarLearner(self.cal, self.wheelbase, self.vgr_inverse, self.yaw_calibration, self.fade_up_s, self.identity)

  def _load(self):
    try:
      with open(self.path, 'rb') as f:
        blob = f.read()
    except OSError:
      return None
    learner = L.HondaEpsCarLearner.from_bytes(blob, self.cal, self.wheelbase, self.vgr_inverse, self.yaw_calibration, self.fade_up_s, self.identity)
    cloudlog.info(f"honda_eps_learnerd: {'resumed' if learner is not None else 'dropped'} saved state for {self.identity}")
    return learner

  def _reset_requested(self):
    if not _get_param_bool(self.params, "HondaEpsLearnerReset", False):
      return False
    self.params.put_bool("HondaEpsLearnerReset", False)
    try:
      os.remove(self.path)
    except OSError:
      pass
    cloudlog.info("honda_eps_learnerd: reset")
    return True

  def add(self, chunk):
    if self._reset_requested():
      self.learner = self._new()
    before = {k: v[0] for k, v in self.learner.status().items()}
    self.learner.add_chunk(chunk)
    changed = {k: v for k, v in self.learner.status().items() if v[0] != before[k]}
    if changed:
      cloudlog.info(f"honda_eps_learnerd: {changed}")
    if changed or self.learner.chunks % SAVE_EVERY == 0:
      self.save()

  def publish(self):
    self.params.put("HondaEpsLearnerResult", self.learner.result())

  def save(self):
    self.publish()
    try:
      os.makedirs(os.path.dirname(self.path), exist_ok=True)
      with open(self.path + '.tmp', 'wb') as f:
        f.write(self.learner.to_bytes())
      os.replace(self.path + '.tmp', self.path)
    except OSError:
      cloudlog.exception("honda_eps_learnerd: could not save state")


def main():
  from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import eps_firmware_calibration
  params = Params()
  CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  cal = eps_firmware_calibration(CP)
  if cal is None:  # manager does not start it on such a car
    cloudlog.info("honda_eps_learnerd: this car is not steered by LatControlHondaEps")
    while True:
      time.sleep(60)
  os.nice(10)
  setup = learner_setup(CP, cal)
  runner = LearnerRunner(params, cal, setup)
  builder = FrameBuilder(setup[2])
  poller = messaging.Poller()
  for service in QUEUED + LATEST:
    messaging.sub_sock(service, poller=poller, conflate=service in LATEST)
  try:
    while True:
      events = [e for sock in poller.poll(1000) for e in messaging.drain_sock(sock)]
      for e in sorted(events, key=lambda e: e.logMonoTime):
        which = e.which()
        chunk = builder.handle(which, getattr(e, which), e.logMonoTime * 1e-9)
        if chunk is not None:
          runner.add(chunk)
  except KeyboardInterrupt:
    pass
  finally:
    chunk = builder.flush()
    if chunk is not None:
      runner.learner.add_chunk(chunk)
    runner.save()


if __name__ == "__main__":
  main()
