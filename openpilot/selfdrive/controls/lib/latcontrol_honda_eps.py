"""Lateral controller for the modified-EPS Hondas that run a PTM (Proper Torque Mod) EPS image. controlsd selects it
instead of LatControlPID.

The control law is eps_firmware_ff.HondaEpsLateralCore: vfn's angle PID on the residual plus a feedforward
that inverts the EPS firmware's own P + D + KFF law, so the command is the one the firmware needs to move the
wheel along the desired path rather than one it has to be dragged into by error. The firmware tables come from
the car's own image (eps_firmware_ff.EpsFirmwareCalibration), picked by the EPS part number in carFw.

Which cars get it: every PTM image with a calibration (Clarity TRW-A020, Civic A030/TEG/C020/C120/TGG-A120, Insight
TXM-A040, CR-V A040/A220, RDX 3G TJB-A220), with no setting to turn it off; some of those calibrations carry parts over
from a related car until a drive measures them. A car with no calibration (TGG-A020, Accord TVA-A150), whose torque map
is not the linear [0, E4 cap] the calibration expects, or with no firmware A table for its rack map, keeps the
modified-EPS PID (LatControlHondaModifiedPID).
Per vehicle, from its calibration: the command delay (cmd_delay_s) and the model-delay schedule (lat_delay_schedule),
every car (measured ones, else a default), and the rack map (rack): yaw-fitted on the car, else predicted from its
published specs (honda_eps_spec_plant).

This shell does what LatControlPID does around its PID for a modified-EPS Honda, reusing the same helpers so
each setting behaves identically, except the geometry: curvature -> wheel angle through the calibration's rack map
(the firmware VGR table, a rack ratio by angle and a slip factor, honda_eps_rack_map.HondaEpsRackMap; every calibration
has one, so HondaEpsFirmwareVgr and the road-measured ratio curves are LatControlPID's only), the angle-rate ceiling
(HondaEpsAngleRateLimit), the shared
driver-override detector, and the speed-banded output low-pass (HondaTorqueOutputLowPassFilter /
HondaTorqueOutputLpfTau*). Settings read elsewhere (carcontroller, carstate, controlsd) apply unchanged.

Not read here, on purpose: LatPScale*, LatIScale*, HondaLateralPidKp/KiScale (the PID is fixed per car to the
tune the feedforward was validated with) and LatFScale* (they scaled the kf * angle * v^2 feedforward this
replaces).
"""
import math
from collections import deque

import numpy as np

from openpilot.cereal import custom, log
from opendbc.car.honda.carcontroller import get_eps_modified_steering_pressed
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, normalize_honda_eps_fw
from opendbc.car.honda.values import CarControllerParams, HondaFlags
from openpilot.common.params import Params
from openpilot.common.realtime import DT_CTRL, DT_MDL
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import (
  REQUIRED_PTM_RWD,
  provenance_summary,
  select_eps_firmware_calibration,
)
from openpilot.selfdrive.controls.lib.honda_eps_firmware_ff import (
  HondaEpsFirmwareFeedforward,
  HondaEpsLateralCore,
  EpsFirmwareCalibration,
  OVERRIDE_FADE_UP_S_DEFAULT,
  command_delay,
)
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import HondaEpsRackMap
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.honda_lateral_common import (
  HONDA_ANGLE_RATE_LIMIT_DEG_S,
  HONDA_TORQUE_OUTPUT_LPF_TAU,
  _get_param_bool,
  _get_param_float,
  rate_limit_desired_angle,
)

SETTINGS_REFRESH_FRAMES = 300

# The command delay makes up for the part of the told delay the model does not follow, so it depends on where the
# steering comes from (starpilotModelV2.lateralSource). A plan model is read at the told delay exactly (this fork has no
# MIN_STABLE_DELAY floor), so telling it the measured lag already lands the car on time: no command delay. An action
# head (Cinque v3) moves its aim only ~0.53 of a change in the told delay, which is what the calibration's command
# delay was measured against; a curvature head and an unknown source (older logs, no message yet) take it too.
CMD_DELAY_SCALE_BY_SOURCE = {"plan": 0.0}
CMD_DELAY_RAMP_S = 1.0  # s, from one source's command delay to the other's when the model changes

# A one-frame STEER_STATUS fault (the RDX's NO_TORQUE_ALERT_1 trips on a single raw torque sample over 768 internal
# counts, with no debounce) drops latActive for one frame, and controlsd resets the lateral controller on every
# inactive frame. A reset mid-turn throws the feedforward away, and it may only rejoin once the error is under
# FF_JOIN_ERROR_DEG: on route 412ed2539bfc2c42/000000cc at 719.65 s the fault cut a -0.28 feedforward holding a 20 deg
# turn at 13 m/s, P alone pushed the other way, and the wheel unwound at 190 deg/s while the error grew past 10 deg.
# So a dropout this short sends nothing but keeps the controller's state, tracking with the integrator held, and only
# a longer one resets it. In the closed-loop replay of that turn: feedforward off 250 -> 0 ms, worst error 11 -> 8 deg.
RIDE_THROUGH_S = 0.1




class CommandDelay:
  """The value issued delay seconds ago, linearly interpolated between frames. Fed every frame, engaged or not,
  so the history is already there at engagement; before it has enough history it returns the oldest value."""

  def __init__(self, dt: float, max_delay: float):
    self.dt = dt
    self.buf: deque[float] = deque(maxlen=int(math.ceil(max_delay / dt)) + 2)

  def update(self, value: float, delay: float) -> float:
    self.buf.append(float(value))
    if delay <= 0.0:
      return float(value)
    steps = delay / self.dt
    i = int(steps)
    frac = steps - i
    n = len(self.buf)
    newer = self.buf[max(n - 1 - i, 0)]
    older = self.buf[max(n - 2 - i, 0)]
    return newer + frac * (older - newer)


def eps_firmware_calibration(CP) -> EpsFirmwareCalibration | None:
  """The EPS image calibration this car steers with, or None to keep the modified-EPS PID."""
  if not (bool(CP.flags & HondaFlags.EPS_MODIFIED) and CP.lateralTuning.which() == "pid"):
    return None
  eps_fw = next((normalize_honda_eps_fw(fw.fwVersion) for fw in CP.carFw if fw.ecu == "eps"), None)
  if eps_fw is None:
    return None
  calibration = select_eps_firmware_calibration(str(CP.carFingerprint), eps_fw)
  if calibration is None:
    return None
  # The inversion assumes 0xE4 = -output * e4_per_output, i.e. the car's linear modified-EPS torque map. StarPilot 7.0
  # keeps that map in CarControllerParams (STEER_LOOKUP) rather than CP.lateralParams.
  cap = float(calibration.e4_per_output)
  ccp = CarControllerParams(CP)
  if [float(x) for x in ccp.STEER_LOOKUP] != [-cap, 0.0, cap] or [float(x) for x in ccp.STEER_LOOKUP_V] != [-cap, 0.0, cap]:
    return None
  if calibration.rack is None or get_honda_vgr_inverse(CP.flags) is None:  # its geometry: see get_rack_map
    return None
  return calibration


def use_honda_eps_controller(CP) -> bool:
  return eps_firmware_calibration(CP) is not None


# vfn's lateral smoothing, which this controller's delay schedules were measured with: modeld low-passes the model's
# curvature over 0.1 s and adds the 0.1 s to the delay it tells the model and this controller. 7.0 runs upstream's 0.0
# (for action-head models that smooth internally) and holds the 20 Hz action across each model frame, so in low-speed
# turns the controller saw 3.3x the >3 Hz target content of vfn (route aa72d9572459015c/00000013 vs 00000389).
LAT_SMOOTH_SECONDS = 0.1


def lateral_smooth_seconds(CP, default: float) -> float:
  """controlsd, modeld: the model-curvature smoothing (and the matching delay) for this car."""
  return LAT_SMOOTH_SECONDS if use_honda_eps_controller(CP) else default


class ModelActionRamp:
  """vfn's NrdrLatModelActionInterp: ramp modeld's 20 Hz action across the model frame instead of holding it, so the
  100 Hz target has no 20 Hz staircase. A new model frame starts a ramp from wherever the output is now."""
  def __init__(self):
    self.reset(0.0)

  def reset(self, curvature: float) -> None:
    self.output = self.start = self.target = float(curvature)
    self.elapsed = 0.0

  def update(self, curvature: float, new_frame: bool, active: bool) -> float:
    if not active:
      self.reset(curvature)
      return self.output
    if new_frame:
      self.start, self.target, self.elapsed = self.output, float(curvature), 0.0
    else:
      self.elapsed += DT_CTRL
    self.output = self.start + min(self.elapsed / DT_MDL, 1.0) * (self.target - self.start)
    return self.output


def lateral_delay_schedule(CP) -> tuple | None:
  """controlsd, modeld: the delay to tell the model in place of liveDelay, whenever this controller steers the car."""
  calibration = eps_firmware_calibration(CP)
  return calibration.lat_delay_schedule if calibration is not None else None


def scheduled_lateral_delay(schedule: tuple, v_ego: float) -> float:
  return float(np.interp(v_ego, *schedule))


def get_rack_map(CP, calibration: EpsFirmwareCalibration | None) -> HondaEpsRackMap | None:
  """The calibration's rack map (yaw-fitted or spec-predicted), on the firmware VGR table it was made for; None when
  either is missing, and then eps_firmware_calibration keeps the car on the modified-EPS PID."""
  vgr_inverse = get_honda_vgr_inverse(CP.flags)
  if calibration is None or calibration.rack is None or vgr_inverse is None:
    return None
  return HondaEpsRackMap(CP.wheelbase, vgr_inverse, calibration.rack)


EPS_STATE_FIELDS = ("epsFfActive", "epsFfFeedforward", "epsFfR5", "epsFfLoad", "epsFfDesiredRate", "epsFfWeight",
                    "epsCalibration", "epsCommandDelay", "epsModelDelay")


def write_eps_state(dst, src) -> None:
  """StarPilot 7.0's controlsd builds starpilotLateralState itself; copy this controller's eps* telemetry into it."""
  for name in EPS_STATE_FIELDS:
    setattr(dst, name, getattr(src, name))


class LatControlHondaEps(LatControl):
  def __init__(self, CP, CI, dt, calibration: EpsFirmwareCalibration | None = None):
    super().__init__(CP, CI, dt)
    self.params = Params()
    self.calibration = calibration if calibration is not None else eps_firmware_calibration(CP)
    assert self.calibration is not None, f"no EPS firmware calibration for {CP.carFingerprint}"
    required = REQUIRED_PTM_RWD.get(self.calibration.name)
    cloudlog.info(f"LatControlHondaEps: {CP.carFingerprint} steering with EPS calibration {self.calibration.name} " +
                  f"({provenance_summary(self.calibration)})" +
                  (f"; requires the corrected PTM build, RWD sha256 {required}..." if required else ""))
    pid = CP.lateralTuning.pid
    self.core = HondaEpsLateralCore([float(x) for x in pid.kpBP], [float(x) for x in pid.kpV],
                                       [float(x) for x in pid.kiBP], [float(x) for x in pid.kiV], dt,
                                       ff=HondaEpsFirmwareFeedforward(dt, cal=self.calibration))
    self.rack_map = get_rack_map(CP, self.calibration)
    assert self.rack_map is not None, f"no rack map for {self.calibration.name}"
    self.cmd_delay = CommandDelay(dt, self.calibration.cmd_delay_s)
    self.lateral_source = "unknown"
    self.cmd_delay_scale = 1.0
    self.frame = -1
    self.prev_rate_limited_angle = 0.0
    self.steering_pressed_filter_s = 0.0
    self.steering_pressed_prev = False
    self.inactive_frames = math.inf  # frames since latActive was last true; see RIDE_THROUGH_S
    self.ride_through_frames = int(round(RIDE_THROUGH_S / dt))
    self.starpilot_lateral_state = custom.StarPilotLateralState.new_message()
    self._read_settings()

  def _read_settings(self):
    self.angle_rate_limit_deg_s = _get_param_float(self.params, "HondaEpsAngleRateLimit", HONDA_ANGLE_RATE_LIMIT_DEG_S, 0.0, 2000.0)
    self.core.output_lpf_enabled = _get_param_bool(self.params, "HondaTorqueOutputLowPassFilter", True)
    self.core.output_lpf_tau = tuple(
      _get_param_float(self.params, key, default, 0.0, 5.0)
      for key, default in zip(("HondaTorqueOutputLpfTauLowSpeed", "HondaTorqueOutputLpfTauStandard", "HondaTorqueOutputLpfTauHighway"),
                              HONDA_TORQUE_OUTPUT_LPF_TAU, strict=True)
    )
    self.core.override_fade_up_s = _get_param_float(self.params, "HondaOverrideFadeUpSecs", OVERRIDE_FADE_UP_S_DEFAULT, 0.0, 10.0)

  def update_lateral_source(self, source: str) -> None:
    """controlsd: where the model's steering comes from (modeld's ModelLateralSource param)."""
    self.lateral_source = str(source)

  def _command_delay(self, v_ego: float) -> float:
    target = CMD_DELAY_SCALE_BY_SOURCE.get(self.lateral_source, 1.0)
    step = self.dt / CMD_DELAY_RAMP_S
    self.cmd_delay_scale += max(min(target - self.cmd_delay_scale, step), -step)
    return self.cmd_delay_scale * command_delay(self.calibration, v_ego)

  def reset(self):
    # controlsd calls this on every inactive frame; update() decides whether the dropout is long enough to reset
    if self.inactive_frames > self.ride_through_frames:
      self._hard_reset()

  def _hard_reset(self):
    super().reset()
    self.core.reset()
    self.steering_pressed_filter_s = 0.0
    self.steering_pressed_prev = False

  def _desired_angle_no_offset(self, VM, v_ego, roll, desired_curvature):
    # The calibration's rack map is the geometry: fitted against the car's own yaw sensor, or predicted from its
    # specs, on the exact firmware table. paramsd's steer ratio (VM) is not used.
    return self.rack_map.angle_from_curvature(desired_curvature, v_ego, roll)

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, curvature_limited,
             lat_delay, calibrated_pose=None, model_data=None, starpilot_toggles=None):
    # StarPilot 7.0's controlsd passes only the first eight; the last three are unused here.
    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)

    cmd_delay = self._command_delay(CS.vEgo)
    desired_curvature = self.cmd_delay.update(desired_curvature, cmd_delay)
    angle_des_no_offset = self._desired_angle_no_offset(VM, CS.vEgo, params.roll, desired_curvature)
    if active:
      angle_des_no_offset = rate_limit_desired_angle(angle_des_no_offset, self.prev_rate_limited_angle,
                                                     self.angle_rate_limit_deg_s, self.dt)
    self.prev_rate_limited_angle = angle_des_no_offset

    angle_des = angle_des_no_offset + params.angleOffsetDeg
    pid_log.steeringAngleDesiredDeg = angle_des
    pid_log.angleError = angle_des - CS.steeringAngleDeg

    if not active:
      self.inactive_frames += 1
      if self.inactive_frames > self.ride_through_frames:
        self._hard_reset()
      else:
        # a brief dropout: keep tracking with the integrator held, send nothing
        self.core.update(angle_des_no_offset, params.angleOffsetDeg, CS.steeringAngleDeg, CS.vEgo, params.roll, False, True)
      output = 0.0
      pid_log.active = False
    else:
      self.inactive_frames = 0
      self.frame += 1
      if self.frame % SETTINGS_REFRESH_FRAMES == 0:
        self._read_settings()
      self.steering_pressed_filter_s, steering_pressed = get_eps_modified_steering_pressed(
        bool(CS.steeringPressed), float(getattr(CS, "steeringTorque", 0.0)), float(self.core.output),
        self.steering_pressed_filter_s, self.steering_pressed_prev,
      )
      self.steering_pressed_prev = steering_pressed
      output = self.core.update(angle_des_no_offset, params.angleOffsetDeg, CS.steeringAngleDeg, CS.vEgo, params.roll,
                                steering_pressed, steer_limited_by_safety)
      output = float(max(min(output, self.steer_max), -self.steer_max))

      pid_log.active = True
      pid_log.p = float(self.core.pid.p)
      pid_log.i = float(self.core.pid.i)
      pid_log.f = float(self.core.pid.f)
      pid_log.output = output
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output) < 1e-3, CS, steer_limited_by_safety,
                                                      curvature_limited))

    ff = self.core.ff
    state = self.starpilot_lateral_state
    state.epsFfActive = bool(active)
    state.epsFfWeight = float(self.core.ff_weight)
    state.epsFfFeedforward = float(ff.output)
    state.epsFfR5 = float(ff.r5)
    state.epsFfLoad = float(ff.load)
    state.epsFfDesiredRate = float(ff.rate)
    state.epsCalibration = self.calibration.name
    state.epsCommandDelay = float(cmd_delay)
    state.epsModelDelay = float(lat_delay)
    return output, angle_des, pid_log
