"""StarPilot's CP adapter; model transport and saved Params stay in the host.

Only exact final CP words derived from the existing five classic/six CANFD
extended profiles can select angle. Combined AOL retains its original Ford profile identity.
"""
from opendbc.car import structs
from opendbc.car.ford.values import CAR, FordFlags
from opendbc.bluepilot_lateral.core.angle import AngleController, Inputs
from opendbc.bluepilot_lateral.core.trim import LaneGeometry
from opendbc.bluepilot_lateral.params import limits as bounds

ANGLE_FLAG = 128
CLASSIC = frozenset({CAR.FORD_BRONCO_SPORT_MK1, CAR.FORD_ESCAPE_MK4, CAR.FORD_FOCUS_MK4,
                     CAR.FORD_MAVERICK_MK1, CAR.FORD_EXPLORER_MK6})
CANFD = frozenset({CAR.FORD_ESCAPE_MK4_5, CAR.FORD_EXPEDITION_MK4, CAR.FORD_F_150_MK14,
                   CAR.FORD_F_150_LIGHTNING_MK1, CAR.FORD_RANGER_MK2, CAR.FORD_MUSTANG_MACH_E_MK1})
TRUCKS = CANFD - {CAR.FORD_ESCAPE_MK4_5, CAR.FORD_MUSTANG_MACH_E_MK1}


def mode_word(cp, *, selected):
  if (cp.brand != "ford" or cp.passive or cp.dashcamOnly or cp.notCar or cp.alternativeExperience not in (0, 32) or
      cp.steerControlType != structs.CarParams.SteerControlType.angle or
      not cp.pcmCruise or len(cp.safetyConfigs) not in (1, 2)):
    return None
  if len(cp.safetyConfigs) == 2 and (cp.safetyConfigs[0].safetyModel != structs.CarParams.SafetyModel.noOutput or
                                   cp.safetyConfigs[0].safetyParam != 0):
    return None
  fd = cp.carFingerprint in CANFD
  if ((fd and (not cp.flags & FordFlags.CANFD or cp.flags & ~int(FordFlags.CANFD | FordFlags.HAS_BSM))) or
      (not fd and (cp.carFingerprint not in CLASSIC or cp.flags & ~int(FordFlags.HAS_BSM)))):
    return None
  safety = cp.safetyConfigs[-1]
  long = int(cp.openpilotLongitudinalControl)
  original = (18 if cp.carFingerprint == CAR.FORD_MUSTANG_MACH_E_MK1 else 66) + long if fd else 32 + long
  manual = cp.transmissionType == structs.CarParams.TransmissionType.manual
  if cp.transmissionType not in (structs.CarParams.TransmissionType.automatic, structs.CarParams.TransmissionType.manual):
    return None
  if cp.alternativeExperience == 32:
    expected = original | (256 if manual else 0) | (ANGLE_FLAG if selected else 0)
  else:
    expected = ANGLE_FLAG + (2 if fd else 0) + long if selected else original
  return expected if safety.safetyModel == structs.CarParams.SafetyModel.ford and safety.safetyParam == expected else None


def supported(cp):
  return mode_word(cp, selected=False) is not None or mode_word(cp, selected=True) is not None


def qualified(cp):
  return mode_word(cp, selected=True) is not None


def select(cp, raw):
  # Absence/invalid bytes stay at current curvature. Never rewrite saved bytes.
  chosen = (type(raw) is int and raw == 1) or (type(raw) in (bytes, str) and raw in (b"1", "1"))
  if not chosen or mode_word(cp, selected=False) is None:
    return False
  if cp.alternativeExperience == 32:
    cp.safetyConfigs[-1].safetyParam |= ANGLE_FLAG
  else:
    cp.safetyConfigs[-1].safetyParam = ANGLE_FLAG + (2 if cp.flags & FordFlags.CANFD else 0) + int(cp.openpilotLongitudinalControl)
  cp.steerActuatorDelay = 0.22
  return True


def model_geometry(model, *, fresh=False):
  """Project a caller-qualified snapshot to immutable core arrays; no model imports."""
  if model is None or fresh is not True:
    return None
  try:
    position_x, position_y = tuple(model.position.x), tuple(model.position.y)
  except (AttributeError, TypeError, ValueError):
    return None
  try:
    return LaneGeometry(position_x=position_x, position_y=position_y, fresh=True, left_x=tuple(model.laneLines[1].x), left_y=tuple(model.laneLines[1].y),
                        right_x=tuple(model.laneLines[2].x), right_y=tuple(model.laneLines[2].y),
                        probabilities=(model.laneLineProbs[1], model.laneLineProbs[2]),
                        standard_deviations=(model.laneLineStds[1], model.laneLineStds[2]))
  except (AttributeError, IndexError, TypeError, ValueError):
    return LaneGeometry(position_x=position_x, position_y=position_y, fresh=True)


class Host:
  def __init__(self, cp):
    if not qualified(cp):
      raise ValueError("BluePilot angle requires an exact admitted Ford safety word")
    low, high = (0.95, 0.95) if cp.carFingerprint in TRUCKS else ((1.0, 1.05) if cp.carFingerprint in CANFD else (1.0, 1.15))
    self.cp = cp
    self.controller = AngleController(low_gain=low, high_gain=high)
    self.inputs = None
    self.tx_blocked = None

  def update(self, CC, CS):
    if self.inputs is not None:
      self.inputs.update()
    snapshot = self.inputs.lateral_snapshot(CS.out.vEgoRaw, angle=True) if self.inputs is not None else None
    model, times, delay, _ = snapshot if snapshot is not None else (None, (), 0.15, True)
    aol = self.cp.alternativeExperience == 32
    ordinary = CC.enabled and CS.out.cruiseState.enabled and not CS.out.gasPressed and not CS.out.brakePressed
    ready = (self.inputs is not None and self.inputs.native_permission(self.cp, max_age_ns=bounds.PANDA_AGE_NS) and
             (aol and CS.out.cruiseState.available or ordinary) and CC.latActive and CS.out.canValid and
             not CS.out.canTimeout and
             (not aol or CS.out.gearShifter in (structs.CarState.GearShifter.drive,
                                              structs.CarState.GearShifter.sport, structs.CarState.GearShifter.low)) and
             not CS.out.steerFaultTemporary and not CS.out.steerFaultPermanent and not CS.out.vehicleSensorsInvalid)
    # Rejected frames do not advance Panda's accepted counter/path history.
    # One real blocked-TX increment requires an accepted neutral resynchronization,
    # rather than sending an indefinitely rejected chain of active counters.
    counter_reader = getattr(self.inputs, "native_tx_blocked", None)
    blocked = counter_reader() if ready and callable(counter_reader) else None
    if not ready:
      self.tx_blocked = None
    elif type(blocked) is int and 0 <= blocked <= 0xFFFFFFFF:
      changed = self.tx_blocked is not None and blocked != self.tx_blocked
      self.tx_blocked = blocked
      ready = not changed
    speed_min = speed_max = None
    speed_window = getattr(CS, "bluepilot_speed_window", None)
    if speed_window is not None:
      low, high, step = speed_window
      # Allow source progress across the existing 100 ms CAN freshness window.
      margin = max(0.05, 5 * step)
      speed_min = max(0.1, min(low, CS.out.vEgoRaw) - margin)
      speed_max = max(high, CS.out.vEgoRaw, 0.1) + margin
    meta = model.meta if model is not None else None
    return self.controller.step(Inputs(
      active=ready, speed=CS.out.vEgoRaw, measured_curvature=-CS.out.yawRate / max(CS.out.vEgoRaw, 0.1),
      desired_curvature=CC.actuators.curvature, steering_pressed=CS.out.steeringPressed,
      steering_angle=CS.out.steeringAngleDeg, yaw_predictions=tuple(model.orientationRate.z) if model is not None else (),
      time_indices=tuple(times), lateral_delay=delay,
      lane_change=int(getattr(meta.laneChangeState, "raw", meta.laneChangeState)) in (1, 2, 3) if meta else False,
      lane_direction=int(getattr(meta.laneChangeDirection, "raw", meta.laneChangeDirection)) if meta else 0,
      limit_status=getattr(CS, "lat_ctl_lim_stat", 0),
      geometry=model_geometry(model, fresh=snapshot is not None), speed_min=speed_min, speed_max=speed_max))
