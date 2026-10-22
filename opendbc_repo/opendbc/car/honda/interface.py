#!/usr/bin/env python3
from opendbc.car.pedal import supported_pedal_detected
import numpy as np
from opendbc.can.dbc import DBC as CANDBC
from opendbc.car import Bus, get_safety_config, structs, uds
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.disable_ecu import disable_ecu
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.values import CarControllerParams, HondaFlags, CAR, HondaSafetyFlags, MANUAL_TRANS_CARS, MODIFIED_EPS_FW, DBC
from opendbc.car.honda.steer_ratio import get_honda_vgr_profile, HONDA_VGR_PROFILE_FLAGS
from opendbc.car.honda.carcontroller import CarController
from opendbc.car.honda.carstate import CarState
from opendbc.car.honda.radar_interface import RadarInterface
from opendbc.car.interfaces import CarInterfaceBase

TransmissionType = structs.CarParams.TransmissionType
RADARLESS_PORTS = frozenset((CAR.HONDA_FIT_4G, CAR.ACURA_INTEGRA, CAR.ACURA_ADX))


def _modified_eps_tune(ret: structs.CarParams) -> None:
  # Modified-EPS tune, shared by the Clarity, Civics, Insight, CR-V 5G and PTM RDX 3G: a four-point handoff at
  # 25 mph (half gains below). The speed banding lives here, not in the runtime LatPScale/LatIScale params, which stay
  # at 100% as fine trim; do not band in both places. kf is banded in latcontrol_pid; this scalar is its fallback.
  bp = [0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS]
  ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [bp, [0.018, 0.024, 0.048, 0.060]]
  ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [bp, [0.006, 0.008, 0.016, 0.020]]
  ret.lateralTuning.pid.kf = 3.6e-6
  # autoResumeSng and minEnableSpeed are recomputed at the end of _get_params, as on vfn
  ret.steerAtStandstill, ret.autoResumeSng = True, True
  ret.minEnableSpeed, ret.minSteerSpeed = -1.0, -1.0


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  DRIVABLE_GEARS = (structs.CarState.GearShifter.sport,)

  @staticmethod
  def get_pid_accel_limits(CP, current_speed, cruise_speed):
    if CP.flags & HondaFlags.BOSCH:
      return CarControllerParams.BOSCH_ACCEL_MIN, CarControllerParams.BOSCH_ACCEL_MAX
    elif CP.flags & HondaFlags.GAS_INTERCEPTOR:
      return CarControllerParams.NIDEC_ACCEL_MIN, CarControllerParams.NIDEC_ACCEL_MAX
    else:
      # NIDECs don't allow acceleration near cruise_speed,
      # so limit limits of pid to prevent windup
      ACCEL_MAX_VALS = [CarControllerParams.NIDEC_ACCEL_MAX, 0.2]
      ACCEL_MAX_BP = [cruise_speed - 2., cruise_speed - .2]
      return CarControllerParams.NIDEC_ACCEL_MIN, np.interp(current_speed, ACCEL_MAX_BP, ACCEL_MAX_VALS)

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "honda"

    CAN = CanBus(ret, fingerprint)

    if ret.flags & HondaFlags.BOSCH:
      cfgs = [get_safety_config(structs.CarParams.SafetyModel.hondaBosch)]
      if ret.flags & HondaFlags.BOSCH_CANFD and CAN.pt >= 4:
        cfgs.insert(0, get_safety_config(structs.CarParams.SafetyModel.noOutput))
      ret.safetyConfigs = cfgs

      from opendbc.car.honda.bosch_a_radar import bosch_a_radar_platform
      ret.radarUnavailable = docs or not bosch_a_radar_platform(candidate)
      # Disable the radar and let openpilot control longitudinal
      # WARNING: THIS DISABLES AEB!
      # If Bosch radarless, this blocks ACC messages from the camera
      # TODO: get radar disable working on Bosch CANFD
      ret.alphaLongitudinalAvailable = not (ret.flags & HondaFlags.BOSCH_CANFD) and not (candidate in RADARLESS_PORTS and is_release)
      ret.openpilotLongitudinalControl = alpha_long and ret.alphaLongitudinalAvailable
      ret.pcmCruise = not ret.openpilotLongitudinalControl
    else:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.hondaNidec)]
      ret.openpilotLongitudinalControl = True

      ret.pcmCruise = True
      if supported_pedal_detected(fingerprint, CAN.pt, supported=CAN.pt == 0):
        ret.flags |= HondaFlags.GAS_INTERCEPTOR.value
        ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.GAS_INTERCEPTOR.value
        ret.pcmCruise = False

    if candidate == CAR.HONDA_CRV_5G and 0x12f8bfa7 in fingerprint[CAN.radar]:
      ret.flags |= HondaFlags.HAS_BSM.value

    # Detect Bosch cars with new HUD msgs
    if any(0x33DA in f for f in fingerprint.values()):
      ret.flags |= HondaFlags.BOSCH_EXT_HUD.value

    if 0x184 in fingerprint[CAN.pt]:
      ret.flags |= HondaFlags.HYBRID.value
    # some Nidec hybrids (Clarity) report brake hold via BRAKE_HOLD_HYBRID_ALT (0x223) instead of VSA_STATUS
    if (ret.flags & HondaFlags.NIDEC) and (ret.flags & HondaFlags.HYBRID) and 0x223 in fingerprint[CAN.pt]:
      ret.flags |= HondaFlags.HYBRID_ALT_BRAKEHOLD.value

    if candidate in MANUAL_TRANS_CARS and all(msg not in fingerprint[CAN.pt] for msg in (0x191, 0x1A3)):
      ret.transmissionType = TransmissionType.manual
    elif 0x191 in fingerprint[CAN.pt] and "GEARBOX_CVT" in CANDBC(DBC[candidate][Bus.pt]).name_to_msg:
      # Traditional CVTs, gearshift position in GEARBOX_CVT
      ret.transmissionType = TransmissionType.cvt
    else:
      # Traditional autos, direct-drive EVs and eCVTs, gearshift position in GEARBOX_AUTO
      ret.transmissionType = TransmissionType.automatic

    ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kpBP = [[0.], [0.]]
    ret.lateralTuning.pid.kf = 0.00006  # conservative feed-forward
    ret.steerActuatorDelay = 0.1

    if ret.flags & HondaFlags.BOSCH:
      ret.longitudinalActuatorDelay = 0.5 # s
      if ret.flags & HondaFlags.BOSCH_RADARLESS:
        ret.stopAccel = CarControllerParams.BOSCH_ACCEL_MIN  # stock uses -4.0 m/s^2 once stopped but limited by safety model
    else:
      # default longitudinal tuning for all hondas
      ret.longitudinalTuning.kiBP = [0., 5., 35.]
      ret.longitudinalTuning.kiV = [1.2, 0.8, 0.5]

    # logging-only queries (e.g. the EPS serial number) are not firmware images; counting them made every
    # allow-listed modified EPS look unknown and forced dashcam (seen on 39990-TBA,C020, 2026-10-21)
    eps_observations = [fw for fw in car_fw if fw.ecu == "eps" and not fw.logging]
    modified_eps = any(b"," in fw.fwVersion for fw in eps_observations)
    eps_modified = bool(modified_eps) and all(
      fw.address == 0x18DA30F1 and fw.subAddress == 0 and
      fw.fwVersion in MODIFIED_EPS_FW.get(candidate, ()) for fw in eps_observations)
    if eps_modified:
      ret.flags |= HondaFlags.EPS_MODIFIED.value
    elif modified_eps:
      ret.dashcamOnly = True

    # VGR is selected by the exact EPS image, not by vehicle family. Unknown firmware gets no VGR override and
    # keeps the normal fixed steer ratio.
    vgr_profile = get_honda_vgr_profile(car_fw)
    if vgr_profile is not None:
      ret.flags |= int(HONDA_VGR_PROFILE_FLAGS[vgr_profile])

    if candidate == CAR.HONDA_CIVIC:
      if eps_modified:
        _modified_eps_tune(ret)
      else:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[1.1], [0.33]]

    elif candidate in (CAR.HONDA_CIVIC_BOSCH, CAR.HONDA_CIVIC_BOSCH_DIESEL):
      if eps_modified:
        _modified_eps_tune(ret)
      else:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]

    elif candidate == CAR.HONDA_CIVIC_2022 and eps_modified:
      # 2.5x modded EPS (no CIVIC_2022 image is on MODIFIED_EPS_FW yet, so this stays off until one is added)
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.3], [0.09]]

    elif candidate in (CAR.HONDA_CIVIC_2022, CAR.HONDA_PRELUDE_6G):
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0, 10], [0.05, 0.5]]
      ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0, 10], [0.0125, 0.125]]

    elif candidate == CAR.HONDA_ACCORD:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = ([[0.3], [0.09]] if eps_modified else [[0.6], [0.18]])

    elif candidate == CAR.HONDA_ACCORD_11G:
      ret.longitudinalActuatorDelay = 0.05
      ret.steerActuatorDelay = 0.3
      ret.lateralTuning.init("pid")
      ret.lateralTuning.pid.kf = 0.000035
      ret.lateralTuning.pid.kpBP = [0.0]
      ret.lateralTuning.pid.kiBP = [0.0]
      ret.lateralTuning.pid.kpV = [0.115]
      ret.lateralTuning.pid.kiV = [0.052]

    elif candidate == CAR.ACURA_ILX:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]

    elif candidate in (CAR.HONDA_CRV, CAR.HONDA_CRV_EU, CAR.HONDA_CRV_SA):
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]
      ret.wheelSpeedFactor = 1.025

    elif candidate == CAR.HONDA_CRV_5G:
      if eps_modified:
        _modified_eps_tune(ret)
      else:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.64], [0.192]]
      ret.wheelSpeedFactor = 1.025

    elif candidate == CAR.HONDA_CRV_HYBRID:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.6], [0.18]]
      ret.wheelSpeedFactor = 1.025

    elif candidate == CAR.HONDA_FIT:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.2], [0.05]]

    elif candidate == CAR.HONDA_FREED:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.2], [0.05]]

    elif candidate in (CAR.HONDA_HRV, CAR.HONDA_HRV_3G):
      if candidate == CAR.HONDA_HRV:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.16], [0.025]]
        ret.wheelSpeedFactor = 1.025
      else:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]  # TODO: can probably use some tuning

    elif candidate == CAR.HONDA_FIT_4G:
      ret.steerActuatorDelay = 0.15
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    elif candidate == CAR.ACURA_INTEGRA:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]

    elif candidate == CAR.ACURA_ADX:
      ret.steerActuatorDelay = 0.15
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0, 10], [0.05, 0.5]]
      ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0, 10], [0.0125, 0.125]]

    elif candidate == CAR.HONDA_CLARITY:
      if eps_modified:
        _modified_eps_tune(ret)
      else:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]
      ret.stopAccel = 0.0

    elif candidate == CAR.ACURA_RDX:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]

    elif candidate in (CAR.ACURA_RDX_3G, CAR.ACURA_RDX_3G_MMR) and eps_modified:
      # 39990-TJB,A220 PTM, the same image on the same rack for 2019-21 and 2022+ (MMR). Its target map X axis runs
      # E4 0..4096 and Route A puts the 30000 top there, level with the Clarity's 29982 at its 3840 cap, so the
      # Clarity's gains carry over 1:1. LatControlHondaEps steers it (honda_eps_calibrations ACURA_RDX_TJB_A220).
      ret.lateralTuning.init("pid")
      _modified_eps_tune(ret)

    elif candidate == CAR.ACURA_RDX_3G:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.2], [0.06]]

    elif candidate == CAR.HONDA_ODYSSEY:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.28], [0.08]]

    elif candidate == CAR.HONDA_ODYSSEY_TWN:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.28], [0.08]]

    elif candidate == CAR.HONDA_PILOT:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.38], [0.11]]

    elif candidate == CAR.HONDA_RIDGELINE:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.38], [0.11]]

    elif candidate == CAR.HONDA_INSIGHT and eps_modified:
      _modified_eps_tune(ret)

    elif candidate in (CAR.HONDA_INSIGHT, CAR.HONDA_NBOX_2G):
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.6], [0.18]]

    elif candidate in (CAR.HONDA_E, CAR.HONDA_E_ADVANCE):
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.6], [0.18]] # TODO: can probably use some tuning

    elif candidate == CAR.HONDA_ODYSSEY_5G_MMR:
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
      ret.steerActuatorDelay = 0.15
      if not ret.openpilotLongitudinalControl:
        # When using stock ACC, the radar intercepts and filters steering commands the EPS would otherwise accept
        ret.minSteerSpeed = 70. * CV.KPH_TO_MS

    else:
      ret.steerActuatorDelay = 0.15
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    from opendbc.car.honda.parameter_profiles import apply_factory_profile
    apply_factory_profile(ret, candidate)

    if candidate == CAR.ACURA_RDX_3G_MMR:
      # TODO: release from dashcam when there's enough driving data for torqued/paramsd to converge
      # only ever add dashcam here; a plain assignment cleared the unrecognized-modified-EPS dashcam set above
      ret.dashcamOnly = ret.dashcamOnly or is_release

    # These cars use alternate user brake msg (0x1BE)
    if 0x1BE in fingerprint[CAN.pt] and (candidate in (CAR.HONDA_ACCORD, CAR.HONDA_HRV_3G, CAR.ACURA_RDX_3G, CAR.ACURA_MDX_4G, CAR.ACURA_ADX) or
                                          ret.flags & HondaFlags.BOSCH_CANFD):
      ret.flags |= HondaFlags.BOSCH_ALT_BRAKE.value

    if ret.flags & HondaFlags.BOSCH_ALT_BRAKE:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.ALT_BRAKE.value
    if ret.flags & HondaFlags.NIDEC_ALT_SCM_MESSAGES:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.NIDEC_ALT.value
    if ret.openpilotLongitudinalControl and ret.flags & HondaFlags.BOSCH:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.BOSCH_LONG.value
      if candidate == CAR.ACURA_RDX_3G:
        ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.RDX_HIGH_GAS.value
    if ret.flags & HondaFlags.BOSCH_RADARLESS:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.RADARLESS.value
    if ret.flags & HondaFlags.BOSCH_CANFD:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.BOSCH_CANFD.value
      if candidate == CAR.HONDA_ACCORD_11G:
        ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.BOSCH_CANFD_MVL.value

    # min speed to enable ACC. if car can do stop and go, then set enabling speed
    # to a negative value, so it won't matter. Otherwise, add 0.5 mph margin to not
    # conflict with PCM acc
    ret.autoResumeSng = (bool(ret.flags & HondaFlags.BOSCH) and not (candidate == CAR.HONDA_FIT_4G and not ret.openpilotLongitudinalControl)) or \
      candidate in (CAR.HONDA_CIVIC, CAR.HONDA_CLARITY) or bool(ret.flags & HondaFlags.GAS_INTERCEPTOR)
    if ret.transmissionType == TransmissionType.manual and not ret.openpilotLongitudinalControl:
      ret.autoResumeSng = False
    if ret.autoResumeSng:
      ret.minEnableSpeed = -1.
    elif candidate == CAR.HONDA_ODYSSEY_TWN:
      ret.minEnableSpeed = 19. * CV.MPH_TO_MS
    elif candidate == CAR.HONDA_FIT_4G:
      ret.minEnableSpeed = 30. * CV.KPH_TO_MS
    else:
      ret.minEnableSpeed = 25.51 * CV.MPH_TO_MS

    ret.steerLimitTimer = 0.8
    ret.radarDelay = 0.1

    return ret

  @staticmethod
  def init(CP, can_recv, can_send, communication_control=None):
    if CP.flags & HondaFlags.BOSCH and not (CP.flags & HondaFlags.BOSCH_RADARLESS) and CP.openpilotLongitudinalControl:
      # 0x80 silences response
      if communication_control is None:
        communication_control = bytes([uds.SERVICE_TYPE.COMMUNICATION_CONTROL, 0x80 | uds.CONTROL_TYPE.DISABLE_RX_DISABLE_TX,
                                       uds.MESSAGE_TYPE.NORMAL_AND_NETWORK_MANAGEMENT])
      disable_ecu(can_recv, can_send, bus=CanBus(CP).pt, addr=0x18DAB0F1, com_cont_req=communication_control)

  @staticmethod
  def deinit(CP, can_recv, can_send):
    communication_control = bytes([uds.SERVICE_TYPE.COMMUNICATION_CONTROL, 0x80 | uds.CONTROL_TYPE.ENABLE_RX_ENABLE_TX,
                                   uds.MESSAGE_TYPE.NORMAL_AND_NETWORK_MANAGEMENT])
    CarInterface.init(CP, can_recv, can_send, communication_control)
