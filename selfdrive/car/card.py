#!/usr/bin/env python3
import math
import os
import time
import threading

import cereal.messaging as messaging

from cereal import car, custom, log

from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process, Priority, Ratekeeper
from openpilot.common.swaglog import cloudlog, ForwardingHandler
from openpilot.system.hardware.hw import Paths

from opendbc.car import DT_CTRL, ButtonType, structs
from opendbc.car.can_definitions import CanData, CanRecvCallable, CanSendCallable
from opendbc.car.carlog import carlog
from opendbc.car.fw_versions import ObdCallback
from opendbc.car.car_helpers import get_car, interfaces
from opendbc.car.interfaces import CarInterfaceBase, RadarInterfaceBase
from opendbc.safety import ALTERNATIVE_EXPERIENCE
from openpilot.selfdrive.pandad import can_capnp_to_list, can_list_to_can_capnp
from openpilot.common.constants import CV
from openpilot.selfdrive.car.gps_accel import G as GRAVITY, GpsAccelEstimator
from openpilot.selfdrive.car.cruise import (
  VCruiseHelper, IMPERIAL_INCREMENT, V_CRUISE_MAX, V_CRUISE_MIN,
  is_speed_limit_confirmation_pending,
)
from openpilot.selfdrive.car.redneck_cruise import (IncreaseBlock, RedneckCruise, close_lead_cap_ms, closing_target_in_path,
                                                    gas_release_floor_expired, get_model_only_far_lead_target_ms,
                                                    is_far_lead_corroborated, is_speed_button_press,
                                                    select_redneck_target_speed, update_gas_release_floor,
                                                    update_launch_state, want_gas_snap)
from openpilot.selfdrive.car.car_specific import MockCarState

from openpilot.starpilot.common.favorite_slots import (
  FAVORITE_ACTION_ACCEL_COUNTER,
  FAVORITE_ACTION_DECEL_COUNTER,
)
from openpilot.starpilot.common.starpilot_variables import always_on_lateral_available, get_starpilot_toggles, update_starpilot_toggles
from openpilot.starpilot.common.lateral_only_experimental import experimental_mode_available
from openpilot.starpilot.controls.starpilot_card import StarPilotCard

REPLAY = "REPLAY" in os.environ
OPENPILOT_LEAD_MIN_DISTANCE = 0.1
REDNECK_DECREASE_LOOKAHEAD_POINTS = 10
SLC_SOURCE_NONE = "None"
EventName = log.OnroadEvent.EventName

# forward
carlog.addHandler(ForwardingHandler(cloudlog))


def set_gas_learner_fields(fpcs, car_controller) -> None:
  """Copy the Honda Bosch LongGasLearner factors into starpilotCarState for the drive log.
  Log-only: any failure leaves the fields at their defaults instead of stopping card."""
  getter = getattr(car_controller, 'gas_learner_state', None)
  if getter is None:
    return
  try:
    state = getter()
    if state is None:
      return
    fpcs.gasLearnerGasFactor = state["gasFactor"]
    fpcs.gasLearnerGasFactorRaw = state["gasFactorRaw"]
    fpcs.gasLearnerWindFactor = state["windFactor"]
    fpcs.gasLearnerWindFactorRaw = state["windFactorRaw"]
    fpcs.gasLearnerError = state["error"]
    fpcs.gasLearnerLearning = state["learning"]
    fpcs.gasLearnerAvailable = True
  except Exception:
    if not getattr(set_gas_learner_fields, "failed", False):
      set_gas_learner_fields.failed = True  # type: ignore[attr-defined]
      cloudlog.exception("card: gas learner logging failed")


def set_vsa_accel_fields(fpcs, car_state, pitch: float = float('nan')) -> None:
  """Copy the Honda VSA accelerometer (carstate.vsa_long_accel) into starpilotCarState, plus the same value with
  g*sin(pitch) removed (pitch: carControl.orientationNED[1], the locationd pose). Log-only."""
  fpcs.aEgoVsaPitchCorrected = float('nan')
  a = getattr(car_state, 'vsa_long_accel', None)
  if a is None:
    return
  try:
    valid = bool(getattr(car_state, 'vsa_long_accel_valid', False)) and math.isfinite(a)
    fpcs.aEgoVsa = float(a) if math.isfinite(a) else 0.0
    fpcs.aEgoVsaValid = valid
    if valid and math.isfinite(pitch):
      fpcs.aEgoVsaPitchCorrected = float(a) - GRAVITY * math.sin(pitch)
  except Exception:
    if not getattr(set_vsa_accel_fields, "failed", False):
      set_vsa_accel_fields.failed = True  # type: ignore[attr-defined]
      cloudlog.exception("card: VSA accel logging failed")


def set_gps_accel_fields(fpcs, est: GpsAccelEstimator, age: float) -> None:
  """Copy the 10 Hz u-blox grade / acceleration estimate (selfdrive/car/gps_accel.py) into starpilotCarState."""
  valid = est.valid(age)
  fpcs.gpsAccelValid = valid
  fpcs.aEgoGps = est.accel if valid else 0.0
  fpcs.gpsGrade = est.grade if valid else 0.0


def obd_callback(params: Params) -> ObdCallback:
  def set_obd_multiplexing(obd_multiplexing: bool):
    if params.get_bool("ObdMultiplexingEnabled") != obd_multiplexing:
      cloudlog.warning(f"Setting OBD multiplexing to {obd_multiplexing}")
      params.remove("ObdMultiplexingChanged")
      params.put_bool("ObdMultiplexingEnabled", obd_multiplexing)
      params.get_bool("ObdMultiplexingChanged", block=True)
      cloudlog.warning("OBD multiplexing set successfully")
  return set_obd_multiplexing


def can_comm_callbacks(logcan: messaging.SubSocket, sendcan: messaging.PubSocket) -> tuple[CanRecvCallable, CanSendCallable]:
  def can_recv(wait_for_one: bool = False) -> list[list[CanData]]:
    """
    wait_for_one: wait the normal logcan socket timeout for a CAN packet, may return empty list if nothing comes

    Returns: CAN packets comprised of CanData objects for easy access
    """
    ret = []
    for can in messaging.drain_sock(logcan, wait_for_one=wait_for_one):
      ret.append([CanData(msg.address, msg.dat, msg.src) for msg in can.can])
    return ret

  def can_send(msgs: list[CanData]) -> None:
    sendcan.send(can_list_to_can_capnp(msgs, msgtype='sendcan'))

  return can_recv, can_send


class Car:
  CI: CarInterfaceBase
  RI: RadarInterfaceBase
  CP: car.CarParams

  FPCP: custom.StarPilotCarParams

  def __init__(self, CI=None, RI=None) -> None:
    self.can_sock = messaging.sub_sock('can', timeout=20)
    self.sm = messaging.SubMaster(['pandaStates', 'carControl', 'onroadEvents', 'radarState', 'longitudinalPlan'])
    self.pm = messaging.PubMaster(['sendcan', 'carState', 'carParams', 'carOutput', 'liveTracks'])
    self.gps_pm = None

    self.can_rcv_cum_timeout_counter = 0
    self._last_car_gps_timestamp_nanos = 0
    self._last_car_gps_received_monotonic = 0.0
    self._last_car_gps_publish_monotonic = 0.0

    self.CC_prev = car.CarControl.new_message()
    self.CS_prev = car.CarState.new_message()
    self.initialized_prev = False

    self.last_actuators_output = structs.CarControl.Actuators()

    self.params = Params()
    self.params_memory = Params(memory=True)
    self._favorite_virtual_accel_counter = self.params_memory.get_int(FAVORITE_ACTION_ACCEL_COUNTER)
    self._favorite_virtual_decel_counter = self.params_memory.get_int(FAVORITE_ACTION_DECEL_COUNTER)
    self._favorite_virtual_releases = []

    self.can_callbacks = can_comm_callbacks(self.can_sock, self.pm.sock['sendcan'])

    is_release = False

    if CI is None:
      # wait for one pandaState and one CAN packet
      print("Waiting for CAN messages...")
      while True:
        can = messaging.recv_one_retry(self.can_sock)
        if len(can.can) > 0:
          break

      alpha_long_allowed = self.params.get_bool("AlphaLongitudinalEnabled")
      num_pandas = len(messaging.recv_one_retry(self.sm.sock['pandaStates']).pandaStates)

      cached_params = None
      cached_params_raw = self.params.get("CarParamsCache")
      if cached_params_raw is not None:
        with car.CarParams.from_bytes(cached_params_raw) as _cached_params:
          cached_params = _cached_params

      self.CI = get_car(*self.can_callbacks, obd_callback(self.params), alpha_long_allowed, is_release, self.params, num_pandas, cached_params,
                        get_starpilot_toggles(read_persisted_force_params=True))
      self.RI = interfaces[self.CI.CP.carFingerprint].RadarInterface(self.CI.CP)
      self.CP = self.CI.CP

      # continue onto next fingerprinting step in pandad
      self.params.put_bool("FirmwareQueryDone", True)

      self.FPCP = self.CI.FPCP
    else:
      self.CI, self.CP, self.FPCP = CI, CI.CP, CI.FPCP
      self.RI = RI

    car_gps_supported = bool(getattr(self.CI.CS, 'car_gps_supported', False))
    self.params.put_bool("CarGpsAvailable", car_gps_supported)
    if car_gps_supported:
      self.gps_pm = messaging.PubMaster(['gpsLocationExternal'])

    aol_available = always_on_lateral_available(self.CP)
    interface_alternative_experience = self.CP.alternativeExperience
    if not aol_available:
      interface_alternative_experience &= ~ALTERNATIVE_EXPERIENCE.ALWAYS_ON_LATERAL
    self.CP.alternativeExperience = interface_alternative_experience
    openpilot_enabled_toggle = self.params.get_bool("OpenpilotEnabledToggle")
    controller_available = self.CI.CC is not None and openpilot_enabled_toggle
    self.CP.passive = not controller_available
    if self.CP.passive:
      safety_config = structs.CarParams.SafetyConfig()
      safety_config.safetyModel = structs.CarParams.SafetyModel.noOutput
      self.CP.safetyConfigs = [safety_config]

    if self.CP.secOcRequired and not is_release:
      # Copy user key if available
      try:
        user_key = Params(Paths.params_cache_root()).get("SecOCKey")
        if user_key is not None:
          user_key = user_key.strip()
          if len(user_key) == 32:
            self.params.put("SecOCKey", user_key)
      except Exception:
        pass

      secoc_key = self.params.get("SecOCKey")
      if secoc_key is not None:
        try:
          saved_secoc_key = bytes.fromhex(secoc_key.strip())
        except (TypeError, ValueError):
          saved_secoc_key = b""

        if len(saved_secoc_key) == 16:
          self.CP.secOcKeyAvailable = True
          self.CI.CS.secoc_key = saved_secoc_key
          if controller_available:
            self.CI.CC.secoc_key = saved_secoc_key
        else:
          cloudlog.warning("Saved SecOC key is invalid")

    if self.CP.secOcRequired and not self.CP.secOcKeyAvailable:
      self.CP.passive = True
      safety_config = structs.CarParams.SafetyConfig()
      safety_config.safetyModel = structs.CarParams.SafetyModel.noOutput
      self.CP.safetyConfigs = [safety_config]

    # Write previous route's CarParams
    prev_cp = self.params.get("CarParamsPersistent")
    if prev_cp is not None:
      self.params.put("CarParamsPrevRoute", prev_cp)

    # Write CarParams for controls and radard
    cp_bytes = self.CP.to_bytes()
    self.params.put("CarParams", cp_bytes)
    self.params.put_nonblocking("CarParamsCache", cp_bytes)
    self.params.put_nonblocking("CarParamsPersistent", cp_bytes)

    self.mock_carstate = MockCarState()
    self.v_cruise_helper = VCruiseHelper(self.CP, self.FPCP)
    self.redneck_cruise = RedneckCruise(self.CP, self.FPCP) if self.CP.brand in ("hyundai", "honda", "subaru") and \
      self.FPCP.redneckCruiseAvailable and not self.FPCP.pcmCruiseSpeed else None

    self.is_metric = self.params.get_bool("IsMetric")
    self.safe_mode = self.params.get_bool("SafeMode")
    self.experimental_mode = (
      self.params.get_bool("ExperimentalMode") and
      experimental_mode_available(self.CP) and
      not self.safe_mode
    )

    # card is driven by can recv, expected at 100Hz
    self.rk = Ratekeeper(100, print_delay_threshold=None)

    self.resume_prev_button = False
    self.starpilot_toggles = get_starpilot_toggles(read_persisted_force_params=True)

    self.FPCP.alternativeExperience |= interface_alternative_experience
    if not aol_available:
      self.FPCP.alternativeExperience &= ~ALTERNATIVE_EXPERIENCE.ALWAYS_ON_LATERAL

    if self.starpilot_toggles.always_on_lateral and aol_available:
      self.CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ALWAYS_ON_LATERAL
      self.FPCP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.ALWAYS_ON_LATERAL
    if getattr(self.starpilot_toggles, "remap_cancel_to_distance", False):
      self.CP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.GM_REMAP_CANCEL_TO_DISTANCE
      self.FPCP.alternativeExperience |= ALTERNATIVE_EXPERIENCE.GM_REMAP_CANCEL_TO_DISTANCE

    fpcp_bytes = self.FPCP.to_bytes()
    self.params.put("StarPilotCarParams", fpcp_bytes)
    self.params.put_nonblocking("StarPilotCarParamsPersistent", fpcp_bytes)

    update_starpilot_toggles()

    self.starpilot_card = StarPilotCard(self.CP, self.FPCP)

    starpilot_services = ['starpilotOnroadEvents', 'starpilotPlan', 'starpilotSelfdriveState', 'liveCalibration', 'selfdriveState']
    if self.CP.brand == "rivian":
      starpilot_services.append('liveParameters')
    if self.CP.brand == "honda" and self.redneck_cruise is not None:
      # ICBM increase block: the model's lead below radard's publish threshold (route 276 14:36.7).
      starpilot_services.append('modelV2')
    # Honda: 10 Hz u-blox fix for the log-only grade / GPS acceleration next to aEgoVsa (gps_accel.py)
    self.gps_accel = GpsAccelEstimator() if self.CP.brand == "honda" else None
    if self.gps_accel is not None:
      starpilot_services.append('gpsLocationExternal')
    self.sm = self.sm.extend(starpilot_services)
    self.pm = self.pm.extend(['starpilotCarState'])

  def _inject_favorite_virtual_cruise_events(self, CS: car.CarState) -> None:
    virtual_events = [
      structs.CarState.ButtonEvent(pressed=False, type=button_type)
      for button_type in self._favorite_virtual_releases
    ]
    self._favorite_virtual_releases = []

    for counter_key, counter_attr, button_type in (
      (FAVORITE_ACTION_ACCEL_COUNTER, "_favorite_virtual_accel_counter", ButtonType.accelCruise),
      (FAVORITE_ACTION_DECEL_COUNTER, "_favorite_virtual_decel_counter", ButtonType.decelCruise),
    ):
      counter = self.params_memory.get_int(counter_key)
      if counter == getattr(self, counter_attr):
        continue
      setattr(self, counter_attr, counter)
      virtual_events.append(structs.CarState.ButtonEvent(pressed=True, type=button_type))
      self._favorite_virtual_releases.append(button_type)

    if virtual_events:
      if hasattr(CS, "to_dict"):
        CS.buttonEvents = [*(be.to_dict() if hasattr(be, "to_dict") else be for be in CS.buttonEvents),
                           *(be.to_dict() if hasattr(be, "to_dict") else be for be in virtual_events)]
      else:
        CS.buttonEvents = list(CS.buttonEvents) + list(virtual_events)

  def state_update(self) -> tuple[car.CarState, structs.RadarDataT | None]:
    """carState update loop, driven by can"""

    can_strs = messaging.drain_sock_raw(self.can_sock, wait_for_one=True)
    can_list = can_capnp_to_list(can_strs)

    # Update carState from CAN
    CS, FPCS = self.CI.update(can_list, self.starpilot_toggles)
    if self.CP.brand == 'mock':
      CS, FPCS = self.mock_carstate.update(CS, FPCS)
    self._inject_favorite_virtual_cruise_events(CS)

    # Update radar tracks from CAN. Honda Bosch-A bounds a coast that implies a reversing lead by ego speed.
    if hasattr(self.RI, 'v_ego'):
      self.RI.v_ego = CS.vEgo
    RD: structs.RadarDataT | None = self.RI.update(can_list)

    self.sm.update(0)

    can_rcv_valid = len(can_strs) > 0

    # Check for CAN timeout
    if not can_rcv_valid:
      self.can_rcv_cum_timeout_counter += 1

    if can_rcv_valid and REPLAY:
      self.can_log_mono_time = messaging.log_from_bytes(can_strs[0]).logMonoTime

    preap_software_cruise = (
      self.CP.brand == "tesla" and self.CP.carFingerprint == "TESLA_MODEL_S_PREAP" and
      self.CP.openpilotLongitudinalControl and not self.CP.pcmCruise
    )
    if not preap_software_cruise:
      starpilot_plan = self.sm['starpilotPlan']
      speed_limit_confirmation_pending = is_speed_limit_confirmation_pending(starpilot_plan)
      slc_target_with_offset = 0.0
      if self.starpilot_toggles.speed_limit_controller and starpilot_plan.slcSpeedLimitSource != SLC_SOURCE_NONE:
        slc_target_with_offset = starpilot_plan.slcSpeedLimit + starpilot_plan.slcSpeedLimitOffset
      self.v_cruise_helper.update_v_cruise(
        CS,
        self.sm['carControl'].enabled,
        self.is_metric,
        speed_limit_confirmation_pending,
        self.starpilot_toggles,
        starpilot_car_state=FPCS,
        slc_target_with_offset=slc_target_with_offset,
      )
    else:
      preap_v_cruise_kph = float(CS.cruiseState.speed * CV.MS_TO_KPH)
      self.v_cruise_helper.v_cruise_kph_last = self.v_cruise_helper.v_cruise_kph
      self.v_cruise_helper.v_cruise_kph = preap_v_cruise_kph
      self.v_cruise_helper.v_cruise_cluster_kph = preap_v_cruise_kph
    slc_force_speed = self.params_memory.get_float("SLCForceCruiseSpeed")
    if slc_force_speed > 0:
      if self.is_metric:
        new_cruise_kph = round(slc_force_speed * CV.MS_TO_KPH)
      else:
        new_cruise_kph = round(slc_force_speed * CV.MS_TO_MPH) * IMPERIAL_INCREMENT
      self.v_cruise_helper.v_cruise_kph = max(min(new_cruise_kph, V_CRUISE_MAX), V_CRUISE_MIN)
      self.v_cruise_helper.v_cruise_cluster_kph = self.v_cruise_helper.v_cruise_kph
      self.params_memory.remove("SLCForceCruiseSpeed")

    if self.sm['carControl'].enabled and not self.CC_prev.enabled and not preap_software_cruise:
      # Use CarState w/ buttons from the step selfdrived enables on
      desired_speed_limit = self.sm['starpilotPlan'].slcSpeedLimit + self.sm['starpilotPlan'].slcSpeedLimitOffset
      self.v_cruise_helper.initialize_v_cruise(
        self.CS_prev,
        self.experimental_mode,
        self.resume_prev_button,
        self.starpilot_toggles,
        desired_speed_limit=desired_speed_limit,
      )

    # TODO: mirror the carState.cruiseState struct?
    CS.vCruise = float(self.v_cruise_helper.v_cruise_kph)
    CS.vCruiseCluster = float(self.v_cruise_helper.v_cruise_cluster_kph)

    if any(be.type in (ButtonType.accelCruise, ButtonType.resumeCruise) for be in CS.buttonEvents):
      self.resume_prev_button = True
    elif any(be.type in (ButtonType.decelCruise, ButtonType.setCruise) for be in CS.buttonEvents):
      self.resume_prev_button = False

    FPCS = self.starpilot_card.update(CS, FPCS, self.sm, self.starpilot_toggles)
    return CS, RD, FPCS

  def state_publish(self, CS: car.CarState, RD: structs.RadarDataT | None, FPCS: custom.StarPilotCarState):
    """carState and carParams publish loop"""

    get_car_gps = getattr(self.CI.CS, 'get_car_gps', None)
    car_gps = get_car_gps() if get_car_gps is not None else None
    now = time.monotonic()
    if car_gps is not None and car_gps['timestamp_nanos'] > self._last_car_gps_timestamp_nanos:
      self._last_car_gps_timestamp_nanos = car_gps['timestamp_nanos']
      self._last_car_gps_received_monotonic = now

    if car_gps is not None and self._last_car_gps_received_monotonic > 0.0 and \
        now - self._last_car_gps_received_monotonic <= 2.5 and \
        now - self._last_car_gps_publish_monotonic >= 0.2:
      gps_send = messaging.new_message('gpsLocationExternal', valid=True)
      gps = gps_send.gpsLocationExternal
      gps.flags = 0
      gps.latitude = car_gps['latitude']
      gps.longitude = car_gps['longitude']
      gps.altitude = car_gps['altitude']
      gps.speed = car_gps['speed']
      gps.bearingDeg = car_gps['bearingDeg']
      gps.horizontalAccuracy = car_gps['horizontalAccuracy']
      gps.unixTimestampMillis = car_gps['unixTimestampMillis']
      gps.source = log.GpsLocationData.SensorSource.car
      gps.vNED = car_gps['vNED']
      gps.verticalAccuracy = car_gps['verticalAccuracy']
      gps.bearingAccuracyDeg = car_gps['bearingAccuracyDeg']
      gps.speedAccuracy = car_gps['speedAccuracy']
      gps.hasFix = car_gps['hasFix']
      gps.satelliteCount = car_gps['satelliteCount']
      assert self.gps_pm is not None
      self.gps_pm.send('gpsLocationExternal', gps_send)
      self._last_car_gps_publish_monotonic = now

    # carParams - logged every 50 seconds (> 1 per segment)
    if self.sm.frame % int(50. / DT_CTRL) == 0:
      cp_send = messaging.new_message('carParams')
      cp_send.valid = True
      cp_send.carParams = self.CP
      self.pm.send('carParams', cp_send)

    # publish new carOutput
    co_send = messaging.new_message('carOutput')
    co_send.valid = self.sm.all_checks(['carControl'])
    co_send.carOutput.actuatorsOutput = self.last_actuators_output
    self.pm.send('carOutput', co_send)

    # kick off controlsd step while we actuate the latest carControl packet
    cs_send = messaging.new_message('carState')
    cs_send.valid = CS.canValid
    cs_send.carState = CS
    cs_send.carState.canErrorCounter = self.can_rcv_cum_timeout_counter
    cs_send.carState.cumLagMs = -self.rk.remaining * 1000.
    self.pm.send('carState', cs_send)

    if RD is not None:
      tracks_msg = messaging.new_message('liveTracks')
      tracks_msg.valid = not any(RD.errors.to_dict().values())
      tracks_msg.liveTracks = RD
      self.pm.send('liveTracks', tracks_msg)

    fpcs_send = messaging.new_message('starpilotCarState')
    fpcs_send.valid = CS.canValid
    fpcs_send.starpilotCarState = FPCS
    set_gas_learner_fields(fpcs_send.starpilotCarState, getattr(self.CI, 'CC', None))
    self.update_accel_log_fields(fpcs_send.starpilotCarState)
    self.pm.send('starpilotCarState', fpcs_send)

  def update_accel_log_fields(self, fpcs) -> None:
    """Log-only acceleration references (STATUS 215/216): VSA accelerometer, pose-pitch corrected, and the 10 Hz
    u-blox grade / acceleration. Never raises; a GPS failure disables only the GPS fields."""
    pitch = float('nan')
    if self.gps_accel is not None:
      try:
        if self.sm.updated['gpsLocationExternal']:
          self.gps_accel.update(self.sm.logMonoTime['gpsLocationExternal'] * 1e-9, self.sm['gpsLocationExternal'])
        age = (self.sm.frame - self.sm.recv_frame['gpsLocationExternal']) * DT_CTRL if self.sm.seen['gpsLocationExternal'] else -1.0
        set_gps_accel_fields(fpcs, self.gps_accel, age)
        orientation = list(self.sm['carControl'].orientationNED)
        if len(orientation) == 3 and self.sm.valid['carControl']:
          pitch = orientation[1]
      except Exception:
        cloudlog.exception("card: GPS accel logging failed, disabled")
        self.gps_accel = None
    set_vsa_accel_fields(fpcs, getattr(self.CI, 'CS', None), pitch)

  def controls_update(self, CS: car.CarState, CC: car.CarControl):
    """control update loop, driven by carControl"""

    if not self.initialized_prev:
      # Initialize CarInterface, once controls are ready
      # TODO: this can make us miss at least a few cycles when doing an ECU knockout
      was_openpilot_long = self.CP.openpilotLongitudinalControl
      self.CI.init(self.CP, *self.can_callbacks)
      # If ECU disable was skipped/failed, strip LONG safety flag from BOTH CarParams
      nissan_leaf_alpha_long = self.CP.brand == "nissan" and self.CP.carFingerprint == "NISSAN_LEAF"
      if was_openpilot_long and (self.CP.brand == "hyundai" or nissan_leaf_alpha_long) and self.params.get_bool("EcuDisableFailed"):
        # ECU disable failed/rejected - switch to lateral-only mode with stock ACC
        # Keep this local to avoid importing every brand's values into card.py.
        LONG_FLAG = 4 if self.CP.brand == "hyundai" else 2 if self.CP.brand == "nissan" else 0
        for cfg in self.CP.safetyConfigs:
          cfg.safetyParam &= ~LONG_FLAG
        for cfg in self.FPCP.safetyConfigs:
          cfg.safetyParam &= ~LONG_FLAG
        self.CP.pcmCruise = True
        self.CP.openpilotLongitudinalControl = False
        self.params.put("CarParams", self.CP.to_bytes())
        self.params.put("StarPilotCarParams", self.FPCP.to_bytes())
      # signal pandad to switch to car safety mode
      self.params.put_bool_nonblocking("ControlsReady", True)

    if self.sm.all_alive(['carControl']):
      # send car controls over can
      now_nanos = self.can_log_mono_time if REPLAY else int(time.monotonic() * 1e9)
      self._update_redneck_cruise(CS, CC)
      self._update_openpilot_lead_state(CC)
      if self.CP.brand == "rivian" and self.sm.all_checks(['liveParameters']) and hasattr(self.CI.CC, 'update_live_params'):
        live_params = self.sm['liveParameters']
        self.CI.CC.update_live_params(live_params.roll, live_params.angleOffsetDeg,
                                      live_params.stiffnessFactor, live_params.steerRatio)
      self.last_actuators_output, can_sends = self.CI.apply(CC, now_nanos, self.starpilot_toggles)
      self.pm.send('sendcan', can_list_to_can_capnp(can_sends, msgtype='sendcan', valid=CS.canValid))

      self.CC_prev = CC

  def _update_openpilot_lead_state(self, CC: car.CarControl) -> None:
    lead_visible = bool(CC.hudControl.leadVisible)
    lead_distance = 0.0
    lead_rel_speed = 0.0

    if self.sm.seen['radarState'] and self.sm.valid['radarState']:
      lead = self.sm['radarState'].leadOne
      if lead.status:
        lead_visible = True
        lead_distance = max(float(lead.dRel), 0.0)
        lead_rel_speed = float(lead.vRel)

    if lead_distance <= OPENPILOT_LEAD_MIN_DISTANCE:
      lead_distance = 0.0
      lead_rel_speed = 0.0

    self.CI.CS.openpilot_lead_visible = lead_visible
    self.CI.CS.openpilot_lead_distance = lead_distance
    self.CI.CS.openpilot_lead_rel_speed = lead_rel_speed

  def _update_redneck_cruise(self, CS: car.CarState, CC: car.CarControl) -> None:
    if self.redneck_cruise is None:
      return

    v_target_ms, lead_present = self._get_redneck_target_speed(CS, CC)
    counter_sync = bool(getattr(self.starpilot_toggles, "icbm_counter_sync", False))
    send_button, v_target = self.redneck_cruise.run(CS, CC, v_target_ms, self.is_metric, lead_present=lead_present,
                                                    gas_snap=getattr(self, "redneck_gas_snap", False),
                                                    counter_sync=counter_sync)
    self.CI.CS.redneck_send_button = send_button
    self.CI.CS.redneck_counter_sync = counter_sync
    self.CI.CS.redneck_v_target = v_target

  def _get_redneck_target_speed(self, CS: car.CarState, CC: car.CarControl) -> tuple[float, bool]:
    starpilot_target_speed = 0.0
    slc_target_speed = 0.0
    csc_target_speed = 0.0
    if self.sm.seen['starpilotPlan'] and self.sm.valid['starpilotPlan']:
      starpilot_plan = self.sm['starpilotPlan']
      starpilot_target_speed = float(starpilot_plan.vCruise)
      if getattr(starpilot_plan, "cscControllingSpeed", False):
        csc_target_speed = float(starpilot_plan.cscSpeed)
      if self.starpilot_toggles.speed_limit_controller:
        overridden_speed = float(starpilot_plan.slcOverriddenSpeed)
        slc_limit = float(starpilot_plan.slcSpeedLimit) + float(starpilot_plan.slcSpeedLimitOffset)
        allow_lower_override = getattr(self.starpilot_toggles, "redneck_cruise", False)
        slc_target_speed = overridden_speed if allow_lower_override and overridden_speed > 0 else max(overridden_speed, slc_limit)

    # Use acceleration projection only when SLC has no resolved target.
    if self.CP.openpilotLongitudinalControl and slc_target_speed <= 0.0:
      return CS.vEgo * 1.01 + 3 * CC.actuators.accel, bool(CC.hudControl.leadVisible)

    allow_plan_decrease = False
    lead_present = False
    lead_distance_m = 0.0
    lead_rel_speed_ms = 0.0
    lead_speed_ms = None  # far lead: leadOne.vLead (always on for Honda ICBM, STATUS 128)
    lead_corroborated = False  # radar-backed or modelProb >= 0.7: the far-lead target uses the lower decel
    lookahead_points = REDNECK_DECREASE_LOOKAHEAD_POINTS

    plan_speeds = []
    if self.sm.seen['longitudinalPlan'] and self.sm.valid['longitudinalPlan']:
      longitudinal_plan = self.sm['longitudinalPlan']
      plan_speeds = [float(speed) for speed in longitudinal_plan.speeds if math.isfinite(float(speed))]
      lead_present = bool(longitudinal_plan.hasLead)
      allow_plan_decrease = bool(lead_present or longitudinal_plan.shouldStop or
                                 str(longitudinal_plan.longitudinalPlanSource) != "cruise")
      if lead_present and len(plan_speeds) > 0:
        lookahead_points = len(plan_speeds)
        if self.sm.seen['radarState'] and self.sm.valid['radarState']:
          lead = self.sm['radarState'].leadOne
          if lead.status:
            lead_distance_m = max(float(lead.dRel), 0.0)
            lead_rel_speed_ms = float(lead.vRel)
            if getattr(self.starpilot_toggles, "icbm_far_lead", False):
              lead_speed_ms = float(lead.vLead)
              lead_corroborated = is_far_lead_corroborated(getattr(lead, "radar", False), getattr(lead, "modelProb", 0.0))

    # Launch: the cruise target (SLC and CSC limits still apply) with no plan or lead hold.
    launch_target_speed = select_redneck_target_speed(
      float(getattr(CS, "vCruise", 0.0)),
      float(CS.cruiseState.speedCluster),
      starpilot_target_speed,
      plan_speeds,
      lookahead_points,
      allow_plan_decrease=False,
      slc_target_speed_ms=slc_target_speed,
      csc_target_speed_ms=csc_target_speed,
    )
    normal_target_speed = select_redneck_target_speed(
      float(getattr(CS, "vCruise", 0.0)),
      float(CS.cruiseState.speedCluster),
      starpilot_target_speed,
      plan_speeds,
      lookahead_points,
      allow_plan_decrease=allow_plan_decrease,
      lead_present=lead_present,
      lead_distance_m=lead_distance_m,
      lead_rel_speed_ms=lead_rel_speed_ms,
      lead_speed_ms=lead_speed_ms,
      slc_target_speed_ms=slc_target_speed,
      csc_target_speed_ms=csc_target_speed,
      lead_corroborated=lead_corroborated,
    )
    # Honda ICBM (STATUS 128 far lead): a confident vision-only lead the planner ignores lowers the far-lead
    # target, and increases are held after a lead change and while a path-relative target is closing
    # (route 276 8:27.9, 14:36.7, 17:22.5; redneck_cruise FAR_LEAD_MODEL_ONLY_* and INCREASE_BLOCK_*).
    increase_blocked = False
    close_lead_cap = float("inf")  # launch-target cap behind a close lead (route 277 16:34.1)
    if getattr(self.starpilot_toggles, "icbm_far_lead", False):
      radar_state = self.sm['radarState'] if self.sm.seen['radarState'] and self.sm.valid['radarState'] else None
      lead_one = radar_state.leadOne if radar_state is not None else None
      lead_two = getattr(radar_state, "leadTwo", None)
      normal_target_speed = min(normal_target_speed, get_model_only_far_lead_target_ms(lead_one))
      model_leads, model_v_ego = None, None
      if self.sm.seen.get('modelV2', False) and self.sm.valid.get('modelV2', False):
        model = self.sm['modelV2']
        model_leads = model.leadsV3
        model_v_ego = float(model.velocity.x[0]) if len(model.velocity.x) else None
      closing = closing_target_in_path((lead_one, lead_two), model_leads, float(getattr(CS, "vEgo", 0.0)), model_v_ego)
      if not hasattr(self, "redneck_increase_block"):
        self.redneck_increase_block = IncreaseBlock()
      increase_blocked = self.redneck_increase_block.update(lead_one, lead_present, closing,
                                                                 float(getattr(CS, "vEgo", 0.0)))
      close_lead_cap = close_lead_cap_ms(lead_one, float(getattr(CS, "vEgo", 0.0)), normal_target_speed)
    self.redneck_increase_blocked = increase_blocked

    driver_button = is_speed_button_press(getattr(CS, "buttonEvents", []))
    enabled = bool(getattr(CC, "enabled", True))
    v_ego = float(getattr(CS, "vEgo", 0.0))
    standstill = bool(getattr(CS, "standstill", False))
    gas_pressed = bool(getattr(CS, "gasPressed", False))
    set_speed = float(CS.cruiseState.speedCluster)
    self.redneck_launch_active, self.redneck_was_stopped = update_launch_state(
      getattr(self, "redneck_launch_active", False),
      getattr(self, "redneck_was_stopped", False),
      enabled,
      v_ego,
      standstill,
      gas_pressed,
      driver_button,
      launch_target_speed,
      set_speed_ms=set_speed,
      hold_target_ms=normal_target_speed,
      lead_cap_ms=close_lead_cap,
    )

    gas_release_floor = 0.0
    self.redneck_gas_snap = False
    if getattr(self.starpilot_toggles, "set_speed_on_gas_release", False):
      brake_pressed = bool(getattr(CS, "brakePressed", False))
      self.redneck_gas_snap = want_gas_snap(enabled, gas_pressed, driver_button, brake_pressed, v_ego, set_speed,
                                            launch_target_speed)
      gas_snapped = getattr(self, "redneck_gas_snapped", False) and gas_pressed or self.redneck_gas_snap
      gas_release_floor = update_gas_release_floor(
        getattr(self, "redneck_gas_release_floor", 0.0),
        getattr(self, "redneck_gas_pressed_prev", False),
        gas_pressed,
        enabled,
        v_ego,
        standstill,
        brake_pressed,
        driver_button,
        set_speed,
        bool(getattr(self, "is_metric", False)),
        snapped=getattr(self, "redneck_gas_snapped", False),
      )
      self.redneck_gas_snapped = gas_snapped
      # A new release (re)starts the floor's clock; a far closing lead that wants the set lower, or
      # GAS_RELEASE_FLOOR_MAX_S, drops the floor until the next release (route 271 BM2/BM4, STATUS 126).
      if gas_release_floor > 0.0:
        new_release = getattr(self, "redneck_gas_pressed_prev", False) and not gas_pressed
        age_s = 0.0 if new_release else getattr(self, "redneck_gas_release_floor_age", 0.0) + DT_CTRL
        self.redneck_gas_release_floor_age = age_s
        if gas_release_floor_expired(age_s, lead_present, lead_rel_speed_ms, normal_target_speed,
                                     min(gas_release_floor, launch_target_speed), lead_distance_m, v_ego):
          gas_release_floor = 0.0
    self.redneck_gas_release_floor = gas_release_floor
    self.redneck_gas_pressed_prev = gas_pressed

    # The launch bypasses the lead-driven target, so a close lead caps it (close_lead_cap_ms, route 277 16:34.1).
    # The gas-release floor is not capped: the driver set it, and at 277 38:26.4 the cap cut it 46.0 -> 41.6 mph
    # while the driver was passing the lead (replay).
    if self.redneck_launch_active:
      target_speed = min(launch_target_speed, close_lead_cap)
    elif gas_release_floor > 0.0:
      # The floor never raises the target above the cruise target (vCruise, SLC and CSC still cap it).
      target_speed = max(normal_target_speed, min(gas_release_floor, launch_target_speed))
    else:
      target_speed = normal_target_speed
    return IncreaseBlock.apply(target_speed, set_speed, increase_blocked), lead_present

  def step(self):
    CS, RD, FPCS = self.state_update()

    self.state_publish(CS, RD, FPCS)

    initialized = (not any(e.name == EventName.selfdriveInitializing for e in self.sm['onroadEvents']) and
                   self.sm.seen['onroadEvents'])
    if not self.CP.passive and initialized:
      self.controls_update(CS, self.sm['carControl'])

    self.initialized_prev = initialized
    self.CS_prev = CS

    self.CI.CS.CC = self.sm['carControl']

    self.starpilot_toggles = get_starpilot_toggles(self.sm)

  def params_thread(self, evt):
    while not evt.is_set():
      self.safe_mode = self.params.get_bool("SafeMode")
      self.is_metric = self.params.get_bool("IsMetric")
      self.experimental_mode = (
        self.params.get_bool("ExperimentalMode") and
        experimental_mode_available(self.CP) and
        not self.safe_mode
      )
      time.sleep(0.1)

  def card_thread(self):
    e = threading.Event()
    t = threading.Thread(target=self.params_thread, args=(e, ))
    try:
      t.start()
      while True:
        self.step()
        self.rk.monitor_time()
    finally:
      e.set()
      t.join()


def main():
  config_realtime_process(4, Priority.CTRL_HIGH)
  car = Car()
  car.card_thread()


if __name__ == "__main__":
  main()
