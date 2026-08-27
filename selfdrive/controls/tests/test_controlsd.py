from types import SimpleNamespace

import cereal.messaging as messaging
from cereal import car, log

from openpilot.selfdrive.controls.controlsd import Controls

STEER_ANGLE_SATURATION_THRESHOLD = 2.5  # matches latcontrol_angle.py


class FakeSubMaster:
  """Minimal SubMaster stand-in covering only the topics Controls.publish() reads."""

  def __init__(self):
    self._structs = {}
    self.valid = {}
    self.logMonoTime = {}

  def add(self, topic, valid=True, log_mono_time=0):
    msg = messaging.new_message(topic)
    struct = getattr(msg, topic)
    self._structs[topic] = struct
    self.valid[topic] = valid
    self.logMonoTime[topic] = log_mono_time
    return struct

  def __getitem__(self, topic):
    return self._structs[topic]


class FakePubMaster:
  def send(self, *args, **kwargs):
    pass


def _build_controls():
  """A Controls instance wired up just enough for publish() to run end to end,
  matching the __new__-then-set-attributes pattern test_nissan_leaf_fallback.py
  already uses for this same heavy class."""
  controls = Controls.__new__(Controls)

  controls.CP = car.CarParams.new_message(steerControlType=car.CarParams.SteerControlType.angle)
  controls.pm = FakePubMaster()
  controls.LoC = SimpleNamespace(long_control_state=car.CarControl.Actuators.LongControlState.off,
                                 pid=SimpleNamespace(p=0.0, i=0.0, f=0.0))
  controls.LaC = SimpleNamespace()  # no starpilot_lateral_state -> skips that debug send
  controls.starpilot_toggles = SimpleNamespace()
  controls.curvature = 0.0
  controls.desired_curvature = 0.0
  controls.calibrated_pose = None
  controls.steer_limited_by_safety = False

  sm = FakeSubMaster()
  sm.add('carState')
  sm.add('longitudinalPlan')
  sm.add('starpilotCarState')
  sm.add('selfdriveState')
  sm.add('driverAssistance', valid=False)
  sm.add('carOutput')
  sm.add('driverMonitoringState')
  sm.logMonoTime['modelV2'] = 0
  controls.sm = sm

  cc = car.CarControl.new_message()
  lac_log = log.ControlsState.LateralAngleState.new_message()
  return controls, cc, lac_log


def _set_steering(cc, sm, *, requested_deg, applied_deg):
  cc.actuators.steeringAngleDeg = requested_deg
  sm['carOutput'].actuatorsOutput.steeringAngleDeg = applied_deg


def test_aol_refreshes_steer_limited_by_safety():
  """
  Regression for AOL stale steer_limited_by_safety state.

  1. Begin with normal OP active and a requested/output mismatch, causing
     steer_limited_by_safety=True.
  2. Drop selfdriveState.active=False while keeping CC.latActive=True via AOL.
  3. Make requested and applied torque match.
  4. Verify steer_limited_by_safety clears instead of retaining the old True.
  """
  controls, cc, lac_log = _build_controls()

  cc.enabled = True
  cc.longActive = True
  cc.latActive = True
  controls.sm['selfdriveState'].active = True
  _set_steering(cc, controls.sm, requested_deg=10.0, applied_deg=0.0)
  controls.publish(cc, lac_log)
  assert controls.steer_limited_by_safety

  # AOL keeps latActive true while full self-drive is disengaged.
  controls.sm['selfdriveState'].active = False
  cc.enabled = False
  cc.longActive = False
  cc.latActive = True
  _set_steering(cc, controls.sm, requested_deg=10.0, applied_deg=10.0)
  controls.publish(cc, lac_log)
  assert not controls.steer_limited_by_safety


def test_lateral_inactive_clears_steer_limited_by_safety():
  """A previous limiting condition must not survive a latActive=False transition."""
  controls, cc, lac_log = _build_controls()

  cc.enabled = True
  cc.longActive = True
  cc.latActive = True
  controls.sm['selfdriveState'].active = True
  _set_steering(cc, controls.sm, requested_deg=10.0, applied_deg=0.0)
  controls.publish(cc, lac_log)
  assert controls.steer_limited_by_safety

  cc.enabled = False
  cc.longActive = False
  cc.latActive = False
  controls.publish(cc, lac_log)
  assert not controls.steer_limited_by_safety
