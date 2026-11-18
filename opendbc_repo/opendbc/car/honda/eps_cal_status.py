"""Clarity mode-switch EPS: the 0x6A4 EPS_CAL_STATUS interlock (rwd-xray lab/clarity/CLARITY_MODESW_MM_P2_20261116,
PROTOCOL_SPEC_DRAFT.md §4).

openpilot asks for a calibration mode in 0xE4 byte 3 (bits 3:1). A switch-capable EPS build reports in 0x6A4 the mode it
is actually running. The EPS changes mode only at LKAS idle, so after an EPS reset, a reflash or a mode that is not built
in, the requested and the active mode can differ while openpilot is engaged. LatControlHondaEps is built for one
calibration, so it must not steer unless the EPS runs that one:

  - no 0x6A4 ever seen (stock, CleanPTM, P1): nothing changes, the interlock is inactive
  - 0x6A4 seen, then silent for more than STATUS_TIMEOUT_FRAMES: fault (as for missing EPS frames)
  - unknown build ID, or the requested mode is not built into it: fault
  - active mode != requested mode: fault until the EPS reports the requested mode (it switches at the next LKAS idle,
    which the fault itself brings about by disengaging lateral)

A fault sets carState.steerFaultTemporary. Only checksum- and counter-valid frames count (CANParser drops the others).

Angle mode (clarity_angle_mode.py, HondaFlags.CLARITY_ANGLE_MODE) asks for mode 3 and is stricter, because an angle
target sent to an EPS that is not running the angle loop is read as a torque:
  - no 0x6A4 seen yet: fault ("no_status")
  - the build must have the angle loop (ANGLE_BUILDS), layout v3
  - the EPS's own angle-loop fault (byte 2 bit 0, latched until the request drops): fault ("angle_fault"), which drops
    the request and so clears it
angle_ready is True only when none of these (or the checks above) fault; CarController sends angle payloads only then.
"""
from opendbc.car.carlog import carlog
from opendbc.car.honda.clarity_angle_mode import EPS_MODE_ANGLE, angle_mode
from opendbc.car.honda.modified_eps import modified_eps
from opendbc.car.honda.values import CAR

# build ID (0x6A4 byte 1) -> modes built in (bit k = mode k). The ID also fixes the frame layout. Each build's README
# records ID <-> bin/rwd sha256.
KNOWN_BUILDS = {
  0x04: 0b1111,  # angle mode 20261118 layout v3 (bin d884e27f, rwd bb4ff1b3): MM 0x02's 0-2, 3 = angle loop (CleanPTM tables, A280 flat)
  0x02: 0b111,   # MM 20261116 layout v2 (bin 2382007c, rwd a173fd71; 11-17 fixes: 252 ms switch debounce, IMASK 10 copy, no reload while engaged): 0 stock, 1 CleanPTM, 2 P2 slot (= CleanPTM for now)
}
ANGLE_BUILDS = {0x04}         # builds with the in-EPS angle loop (0x6A4 layout v3)
STATUS_TIMEOUT_FRAMES = 50   # carState updates (100 Hz): 0.5 s, 25 periods of the 50 Hz frame
MSG = "EPS_CAL_STATUS"


def requested_eps_mode(CP) -> int:
  """The calibration mode openpilot asks for in 0xE4 byte 3: 3 in angle mode, 1 (CleanPTM) when it runs the PTM
  controller on the Clarity, else 0."""
  if angle_mode(CP):
    return EPS_MODE_ANGLE
  return 1 if (modified_eps(CP) and CP.carFingerprint == CAR.HONDA_CLARITY) else 0


class EpsCalStatus:
  def __init__(self, CP):
    self.requested = requested_eps_mode(CP)
    self.enabled = self.requested != 0
    self.angle = self.requested == EPS_MODE_ANGLE
    self.announced = False      # a valid 0x6A4 seen since start: this EPS is switch-capable
    self.frames_since = 0
    self.last_ts = 0
    self.active_mode = -1
    self.build_id = -1
    self.fault = ""             # "" = OK, else the reason
    # layout v3 (angle builds): the EPS angle loop's own view, for logging
    self.loop_running = False
    self.angle_fault_why = 0    # 1 jump, 2 stale, 3 angle invalid
    self.angle_ref_deg = 0.0
    self.angle_out = 0

  def update(self, cp) -> str:
    if not self.enabled:
      return ""
    ts = cp.ts_nanos[MSG]["COUNTER"]
    if ts and ts != self.last_ts:
      self.last_ts, self.frames_since, self.announced = ts, 0, True
    else:
      self.frames_since += 1
    if self.announced:
      fault = self._check(cp.vl[MSG])
    else:
      fault = "no_status" if self.angle else ""
    if fault != self.fault:
      carlog.warning(f"EPS_CAL_STATUS: {fault or 'ok'} (active mode {self.active_mode}, requested {self.requested}, build {self.build_id:#04x})")
      self.fault = fault
    return fault

  def _check(self, vl) -> str:
    if self.frames_since > STATUS_TIMEOUT_FRAMES:
      return "lost"
    self.active_mode, self.build_id = int(vl["ACTIVE_MODE"]), int(vl["BUILD_ID"])
    caps = KNOWN_BUILDS.get(self.build_id)
    if caps is None:
      return "unknown_build"
    if not (caps >> self.requested) & 1:
      return "mode_not_built"
    if self.active_mode != self.requested:
      return "inactive_mode"
    if self.angle:
      if self.build_id not in ANGLE_BUILDS:
        return "no_angle_loop"
      self.loop_running = bool(vl["ANGLE_LOOP_RUNNING"])
      self.angle_fault_why = int(vl["ANGLE_FAULT_WHY"])
      self.angle_ref_deg, self.angle_out = float(vl["ANGLE_REF"]), int(vl["ANGLE_OUT"])
      if vl["ANGLE_FAULT"]:
        return "angle_fault"
    return ""

  @property
  def angle_ready(self) -> bool:
    """Angle mode only: the EPS runs the angle loop's mode on an angle build, reports no fault, and is not lost."""
    return self.angle and self.announced and self.fault == ""
