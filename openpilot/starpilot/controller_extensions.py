import math
import time

import numpy as np

import openpilot.cereal.messaging as messaging
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.common.swaglog import cloudlog

from openpilot.starpilot.controllers.toyota_cruise import ToyotaCruisePreference, capability as toyota_cruise_capability

from opendbc.car.ford.values import CAR, FordFlags


class ManualTurnInputs:
  def __init__(self, params, *, track_assist_permission: bool = False):
    self.params = params
    self.track_assist_permission = track_assist_permission
    self.sm = messaging.SubMaster(["modelV2", "lateralDelay"] + (["pandaStates", "aolSafetyWire"] if track_assist_permission else []))
    self.enabled = bool(self.params.get("FordHumanTurnDetection", return_default=True))
    self.frames = 0
    self.blend_settings = self._read_blend_settings()
    self._applied_blends = {}

  def _read_blend_settings(self):
    settings = []
    for key, default, low, high in (("FordCurvatureBlendLow", 0.4, 0.0, 1.0),
                                    ("FordCurvatureBlendHigh", 0.4, 0.0, 1.0),
                                    ("FordCurvatureLaneChangeFactor", 0.85, 0.5, 1.25)):
      try:
        value = float(self.params.get(key, return_default=True))
        if not math.isfinite(value):
          value = default
      except (TypeError, ValueError, OverflowError, RuntimeError):
        value = default
      settings.append(float(np.clip(value, low, high)))
    return tuple(settings)

  def apply_blend_settings(self, controller):
    for name in ("mache_lateral", "classic_lateral", "new_port_curvature"):
      owner = getattr(controller, name, None)
      if owner is not None and self._applied_blends.get(owner) != self.blend_settings:
        owner.set_blend_settings(*self.blend_settings)
        self._applied_blends[owner] = self.blend_settings

  def update(self):
    self.sm.update(0)
    if self.frames % 100 == 0:
      self.enabled = bool(self.params.get("FordHumanTurnDetection", return_default=True))
      self.blend_settings = self._read_blend_settings()
    self.frames += 1
    state = self.sm["modelV2"].meta.laneChangeState
    model_ready = self.sm.alive["modelV2"] and self.sm.valid["modelV2"]
    return self.enabled, int(getattr(state, "raw", state)) in (1, 2, 3), model_ready


  def preview_curvature(self, speed: float) -> float | None:
    try:
      now = time.monotonic_ns()
      stamp = self.sm.logMonoTime["modelV2"]
      if (not self.sm.alive["modelV2"] or not self.sm.valid["modelV2"] or
          not 0 < stamp <= now <= stamp + 100_000_000 or not math.isfinite(speed) or speed < 0.1):
        return None
      yaw = tuple(self.sm["modelV2"].orientationRate.z)
      if len(yaw) != len(ModelConstants.T_IDXS) or not all(math.isfinite(value) for value in yaw):
        return None
      delay = 0.2
      delay_stamp = self.sm.logMonoTime["lateralDelay"]
      if (self.sm.alive["lateralDelay"] and self.sm.valid["lateralDelay"] and
          0 < delay_stamp <= now <= delay_stamp + 1_000_000_000):
        measured_delay = float(self.sm["lateralDelay"].lateralDelay)
        if math.isfinite(measured_delay):
          delay = float(np.clip(measured_delay, 0.2, 0.4))
      return float(np.interp(delay, ModelConstants.T_IDXS, yaw)) / speed
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
      return None

  def lateral_snapshot(self, speed: float, *, angle: bool = False):
    if self.preview_curvature(speed) is None:
      return None
    delay = 0.15 if angle else 0.2
    now = time.monotonic_ns()
    stamp = self.sm.logMonoTime["lateralDelay"]
    if (self.sm.alive["lateralDelay"] and self.sm.valid["lateralDelay"] and
        0 < stamp <= now <= stamp + 1_000_000_000):
      value = float(self.sm["lateralDelay"].lateralDelay)
      if math.isfinite(value):
        delay = float(np.clip(value, 0.1, 0.15)) if angle else float(np.clip(value, 0.2, 0.4))
    return self.sm["modelV2"], ModelConstants.T_IDXS, delay, self.enabled

  def native_permission(self, cp, *, max_age_ns):
    """Exact current public Panda acknowledgment for the optional angle owner."""
    if not self.track_assist_permission:
      return False
    try:
      # Drain happens in update(); capture one SM snapshot before sampling clocks.
      pandas = self.sm["pandaStates"]
      stamp = int(self.sm.logMonoTime["pandaStates"])
      receipt = int(self.sm.recv_time["pandaStates"] * 1e9)
      now, boot = time.monotonic_ns(), time.clock_gettime_ns(time.CLOCK_BOOTTIME)
      if (not self.sm.seen["pandaStates"] or not self.sm.all_checks(["pandaStates"]) or
          not 0 < stamp <= boot <= stamp + max_age_ns or
          not 0 < receipt <= now <= receipt + max_age_ns):
        return False
      if len(pandas) != len(cp.safetyConfigs):
        return False
      aol = cp.brand == "ford" and cp.alternativeExperience == 32
      if aol:
        from openpilot.starpilot.aol.runtime import current_native
        native = current_native(self.sm, cp, now_ns=boot)
        if (native is None or not native.pandaInventory or not native.requestedLateral or not native.lateralAllowed or
            native.sourcePandaStatesMonoTime != stamp or boot - native.observedMonoTime > max_age_ns):
          return False
      for i, (panda, config) in enumerate(zip(pandas, cp.safetyConfigs, strict=True)):
        if (panda.safetyModel != config.safetyModel or panda.safetyParam != config.safetyParam or
            panda.alternativeExperience != cp.alternativeExperience or panda.safetyRxChecksInvalid or
            panda.heartbeatLost or len(panda.faults) or str(panda.faultStatus) != "none"):
          return False
        if (not aol and bool(panda.controlsAllowed) != (i == len(pandas) - 1) or
            aol and i != len(pandas) - 1 and panda.controlsAllowed):
          return False
      return True
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
      return False

  def native_tx_blocked(self):
    """Read only after native_permission qualified this same Panda snapshot."""
    try:
      value = self.sm["pandaStates"][-1].safetyTxBlocked
      return int(value) if 0 <= value <= 0xFFFFFFFF else None
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OverflowError):
      return None

  def assist_permission(self):
    if not self.track_assist_permission:
      return (), False
    return self.sm["pandaStates"], self.sm.all_checks(["pandaStates"])


class ResumePlanInputs:
  """Card-owned fresh plan evidence, independent of Controls' saved preference snapshot."""
  def __init__(self, *, boottime=False):
    self.boottime = boottime
    from openpilot.starpilot.longitudinal.inputs import ResumeFreshness
    self.sm = messaging.SubMaster(["deviceState", "carState", "longitudinalPlan"], frequency=25)
    self.freshness = ResumeFreshness()

  def update(self, now_ns):
    self.sm.update(0)
    clock_ns = time.clock_gettime_ns(time.CLOCK_BOOTTIME) if self.boottime else time.monotonic_ns()
    return (type(now_ns) is int and abs(clock_ns - now_ns) <= 150_000_000 and
            self.freshness.current(self.sm) and not self.sm['longitudinalPlan'].shouldStop)


def configure_controller(CI, params):
  cp = CI.CP
  controller = CI.CC
  from openpilot.starpilot.car.ford.cluster_preferences import FordClusterPreference, qualified as cluster_qualified
  if controller is not None and cluster_qualified(cp):
    controller.hands_free_cluster_input = FordClusterPreference(params)
  if controller is not None and cp.brand == 'gm':
    from opendbc.car.gm.values import (is_bolt_euv_longitudinal, is_volt_longitudinal,
                                     camera_acc_pedal_profile, volt_cc_pedal_profile)
    from opendbc.car.gm.suburban import stopping_decel_rate as suburban_stopping_decel_rate
    pedal = camera_acc_pedal_profile(cp) or volt_cc_pedal_profile(cp)
    if (is_bolt_euv_longitudinal(cp) or is_volt_longitudinal(cp) or suburban_stopping_decel_rate(cp) is not None or
        pedal is not None and pedal.longitudinal):
      from openpilot.starpilot.car.gm.tune_preferences import GradeCompensationPreference
      controller.long_pitch_input = GradeCompensationPreference(params)
  from opendbc.car.gm.truck_longitudinal import truck_tuning_supported
  if controller is not None and truck_tuning_supported(cp):
    from openpilot.starpilot.car.gm.tune_preferences import TruckTuningPreference
    controller.truck_tuning_input = TruckTuningPreference(cp, params)
  from opendbc.car.gm.long_tune import tune_options
  if controller is not None and 1 in tune_options(cp):
    from openpilot.starpilot.car.gm.tune_preferences import AccTunePreference
    controller.gm_acc_tune_input = AccTunePreference(cp, params)
  from opendbc.car.toyota import pedal
  if pedal.configured(cp):
    from openpilot.starpilot.car.toyota.pedal_preferences import PedalPreference
    from openpilot.starpilot.car.toyota.prius_preferences import filter_preference_enabled
    if not filter_preference_enabled(params):
      pedal.prepare_stock(cp)
    if controller is not None:
      controller.pedal_input = PedalPreference(cp, params)
  from opendbc.car.toyota.rav4h_filter import enabled as rav4h_filter_enabled, prepare_stock as prepare_rav4h_stock
  if rav4h_filter_enabled(cp):
    from openpilot.starpilot.car.toyota.rav4h_preferences import Rav4hFilterPreference
    from openpilot.starpilot.car.toyota.prius_preferences import filter_preference_enabled
    if not filter_preference_enabled(params):
      prepare_rav4h_stock(cp)
    elif controller is not None:
      controller.rav4h_filter_input = Rav4hFilterPreference(cp, params)
  from opendbc.car.toyota import dsu_bypass
  if dsu_bypass.enabled(cp):
    from openpilot.starpilot.car.toyota.bypass_preferences import BypassPreference
    from openpilot.starpilot.car.toyota.prius_preferences import filter_preference_enabled
    if not filter_preference_enabled(params):
      dsu_bypass.prepare_stock(cp)
    elif controller is not None:
      controller.bypass_input = BypassPreference(cp, params)
  from opendbc.car.toyota import advert_filter
  if advert_filter.enabled(cp):
    from openpilot.starpilot.car.toyota.advert_preferences import AdvertFilterPreference
    from openpilot.starpilot.car.toyota.prius_preferences import filter_preference_enabled
    if not filter_preference_enabled(params):
      advert_filter.prepare_stock(cp)
    elif controller is not None:
      controller.advert_filter_input = AdvertFilterPreference(cp, params)
  from opendbc.car.toyota.prius_longitudinal import enabled as prius_filter_enabled, prepare_stock as prepare_prius_stock
  if prius_filter_enabled(cp):
    from openpilot.starpilot.car.toyota.prius_preferences import PriusFilterPreference, filter_preference_enabled
    if not filter_preference_enabled(params):
      prepare_prius_stock(cp)
      if controller is not None:
        controller.prius_longitudinal = False
    elif controller is not None:
      controller.prius_filter_input = PriusFilterPreference(cp, params)
  from opendbc.car.gm.values import is_gm_auto_hold, is_volt_one_pedal, is_bolt_pedal_profile, camera_acc_pedal_profile, volt_cc_pedal_profile
  cc_pedal = volt_cc_pedal_profile(cp)
  camera_pedal = camera_acc_pedal_profile(cp) or cc_pedal
  if controller is not None and camera_pedal is not None and camera_pedal.longitudinal:
    from openpilot.starpilot.car.gm.camera import CameraPedalPreference
    controller.camera_pedal_input = CameraPedalPreference(cp, params)
    if cc_pedal is not None or camera_pedal.volt:
      controller.longitudinal_maneuver_input = CameraPedalPreference(cp, params, maneuver=True)
  if controller is not None and is_bolt_pedal_profile(cp):
    from openpilot.starpilot.car.gm.paddle import PADDLE_IDS, PaddlePreference
    if cp.carFingerprint in PADDLE_IDS:
      controller.maneuver_paddle_input = PaddlePreference(cp, params)
  if controller is not None and is_gm_auto_hold(cp) and controller.gm_auto_hold:
    from openpilot.starpilot.car.gm.auto_hold import AutoHoldPreference
    controller.gm_auto_hold_input = AutoHoldPreference(cp, params)
  if controller is not None and is_volt_one_pedal(cp) and controller.volt_one_pedal:
    from openpilot.starpilot.car.gm.auto_hold import AutoHoldPreference
    controller.volt_one_pedal_input = AutoHoldPreference(cp, params, "VoltOnePedalMode")
  from opendbc.car.gm.values import is_volt_longitudinal
  if controller is not None and is_volt_longitudinal(cp) and controller.volt_sng:
    try:
      from opendbc.car.gm.values import GMFlags, is_volt_ascm_longitudinal, is_volt_sdgm_profile
      controller.volt_sng_plan_input = ResumePlanInputs(
        boottime=(is_volt_sdgm_profile(cp, longitudinal=True) and cp.safetyConfigs[0].safetyParam == 0x5007 or
                  cp.alternativeExperience == 32 and not cp.flags & GMFlags.PEDAL_LONG and is_volt_ascm_longitudinal(cp)))
    except OSError:
      controller.volt_sng_plan_input = None
      cloudlog.exception('Optional Volt resume input transport unavailable')
  if controller is not None and toyota_cruise_capability(cp) is not None:
    controller.reverse_cruise_input = ToyotaCruisePreference(cp, params)
  if (controller is not None and cp.brand == "ford" and cp.carFingerprint == CAR.FORD_MUSTANG_MACH_E_MK1 and
      not cp.flags & FordFlags.LKA_STEERING and not cp.passive and not cp.dashcamOnly and not cp.notCar and
      getattr(controller, "manual_turn", None) is not None):
    controller.manual_turn_inputs = ManualTurnInputs(params, track_assist_permission=bool(cp.flags & FordFlags.CANFD))

  from opendbc.bluepilot_lateral.hosts.starpilot import qualified as angle_qualified
  if controller is not None and angle_qualified(cp) and getattr(controller, "bp_lat", None) is not None:
    controller.bp_lat.host.inputs = ManualTurnInputs(params, track_assist_permission=True)

  from opendbc.car.ford.classic_lateral import qualified as classic_qualified
  from opendbc.car.ford.generic_canfd_lateral import qualified as generic_canfd_qualified
  if controller is not None and (classic_qualified(cp) or generic_canfd_qualified(cp)) and getattr(controller, "classic_lateral", None) is not None:
    controller.manual_turn_inputs = ManualTurnInputs(params)

  from opendbc.car.ford.new_port_curvature import qualified as new_port_curvature_qualified
  if controller is not None and new_port_curvature_qualified(cp) and getattr(controller, "new_port_curvature", None) is not None:
    controller.manual_turn_inputs = ManualTurnInputs(params)

  if controller is not None and cp.brand == "ford" and getattr(controller, "manual_turn_inputs", None) is not None:
    controller.manual_turn_inputs.apply_blend_settings(controller)

  if controller is not None and cp.brand == "honda" and getattr(controller, "modified_eps_steering", None) is not None:
    # one settings source for the modified-EPS steering stage and the car state's steering-pressed threshold
    from openpilot.starpilot.car.honda.modified_eps import ModifiedEpsPreferences
    preferences = ModifiedEpsPreferences(params)
    controller.modified_eps_settings = preferences
    if getattr(CI, "CS", None) is not None:
      CI.CS.modified_eps_settings = preferences

  if (controller is not None and cp.brand == "honda" and getattr(controller, "nidec_interceptor", None) is not None and
      controller.nidec_interceptor.learn):
    from openpilot.starpilot.car.honda.longitudinal import BoschLearningParams
    controller.interceptor_learning_params = BoschLearningParams(params, controller.nidec_interceptor)

  if controller is not None and cp.brand == "honda" and getattr(controller, "bosch_longitudinal", None) is not None:
    from openpilot.starpilot.car.honda.longitudinal import BoschLearningParams
    controller.bosch_learning_params = BoschLearningParams(params, controller.bosch_longitudinal)

  from opendbc.car.hyundai.g90_lead import eligible as g90_lead_eligible
  if controller is not None and g90_lead_eligible(cp):
    from openpilot.starpilot.longitudinal.g90_lead import G90LeadInputs
    try:
      controller.g90_lead_inputs = G90LeadInputs()
    except OSError:
      controller.g90_lead_inputs = None
      cloudlog.exception('Optional G90 lead input transport unavailable')

  from opendbc.car.hyundai.gv70_camera_lead import eligible as gv70_lead_eligible
  if controller is not None and gv70_lead_eligible(cp):
    from openpilot.starpilot.longitudinal.gv70_lead import GV70LeadInputs
    try:
      controller.gv70_lead_inputs = GV70LeadInputs()
    except OSError:
      controller.gv70_lead_inputs = None
      cloudlog.exception('Optional GV70 lead input transport unavailable')

  from opendbc.car.hyundai.ev9_longitudinal import qualified as ev9_long_qualified
  from opendbc.car.hyundai.ioniq5pe_long_profile import qualified as pe_long_qualified
  if controller is not None and (ev9_long_qualified(cp) or pe_long_qualified(cp)):
    from openpilot.starpilot.longitudinal.canfd_lead import CANFDLeadInputs
    try:
      controller.ev9_lead_inputs = CANFDLeadInputs()
    except OSError:
      controller.ev9_lead_inputs = None
      cloudlog.exception('Optional EV9 lead input transport unavailable')

  if controller is not None and getattr(controller, 'ioniq6_longitudinal', None) is not None:
    from openpilot.starpilot.longitudinal.canfd_lead import CANFDLeadInputs
    try:
      controller.ioniq6_lead_inputs = CANFDLeadInputs()
    except OSError:
      controller.ioniq6_lead_inputs = None
      cloudlog.exception('Optional Ioniq 6 lead input transport unavailable')

  if controller is not None and getattr(controller, 'torque_ev_scc_enabled', False):
    from openpilot.starpilot.longitudinal.canfd_lead import CANFDLeadInputs
    try:
      controller.torque_ev_lead_inputs = CANFDLeadInputs()
    except OSError:
      controller.torque_ev_lead_inputs = None
      cloudlog.exception('Optional torque EV lead input transport unavailable')
