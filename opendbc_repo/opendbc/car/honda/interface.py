#!/usr/bin/env python3
import numpy as np
from openpilot.common.params import Params, UnknownKeyName
from opendbc.car import get_safety_config, structs, uds
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.disable_ecu import disable_ecu
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.values import CarControllerParams, HondaFlags, CAR, HONDA_BOSCH, HONDA_BOSCH_A, HONDA_BOSCH_CANFD, \
                                                 HONDA_NIDEC_ALT_SCM_MESSAGES, HONDA_BOSCH_RADARLESS, HondaSafetyFlags
from opendbc.car.honda.steer_ratio import get_honda_vgr_profile, HONDA_VGR_PROFILE_FLAGS, normalize_honda_eps_fw
from opendbc.car.honda.carcontroller import CarController
from opendbc.car.honda.carstate import CarState
from opendbc.car.honda.radar_interface import RadarInterface
from opendbc.car.interfaces import CarInterfaceBase

TransmissionType = structs.CarParams.TransmissionType

class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  @staticmethod
  def get_pid_accel_limits(CP, current_speed, cruise_speed):
    if CP.carFingerprint in HONDA_BOSCH:
      return CarControllerParams.BOSCH_ACCEL_MIN, CarControllerParams.BOSCH_ACCEL_MAX
    elif CP.enableGasInterceptorDEPRECATED:
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

    if candidate in HONDA_BOSCH:
      cfgs = [get_safety_config(structs.CarParams.SafetyModel.hondaBosch)]
      if candidate in HONDA_BOSCH_CANFD and CAN.pt >= 4:
        cfgs.insert(0, get_safety_config(structs.CarParams.SafetyModel.noOutput))
      ret.safetyConfigs = cfgs

      # HONDA_BOSCH_A platforms (plain bosch_a harness: not CANFD, not radarless, not alt-radar) have
      # a firmware-correct RadarInterface (16-slot Bosch-A object bank, RX-only) and use it by
      # default via BoschARadar: every other Bosch platform still has no parsed radar DBC and
      # keeps radarUnavailable=True regardless.
      # Independent of alpha long: that decides who commands the gas/brake (openpilot vs. stock
      # ACC), not where the lead comes from. A real radar-confirmed lead only helps radarState
      # regardless of which controller is acting on it, so the two are not exclusive.
      try:
        bosch_a_radar_tryout = Params().get_bool("BoschARadar")
      except UnknownKeyName:
        bosch_a_radar_tryout = False
      ret.radarUnavailable = not (candidate in HONDA_BOSCH_A and bosch_a_radar_tryout)
      # Disable the radar and let openpilot control longitudinal
      # WARNING: THIS DISABLES AEB!
      # If Bosch radarless, this blocks ACC messages from the camera
      ret.alphaLongitudinalAvailable = True
      ret.openpilotLongitudinalControl = alpha_long
      ret.pcmCruise = not ret.openpilotLongitudinalControl
    else:
      ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.hondaNidec)]
      ret.openpilotLongitudinalControl = True

      ret.pcmCruise = True
      ret.enableGasInterceptorDEPRECATED = 0x201 in fingerprint[CAN.pt]
      if ret.enableGasInterceptorDEPRECATED:
        ret.pcmCruise = False

    if candidate == CAR.HONDA_CRV_5G:
      ret.enableBsm = 0x12f8bfa7 in fingerprint[CAN.radar]

    # Detect Bosch cars with new HUD msgs
    if any(0x33DA in f for f in fingerprint.values()):
      ret.flags |= HondaFlags.BOSCH_EXT_HUD.value

    if 0x184 in fingerprint[CAN.pt]:
      ret.flags |= HondaFlags.HYBRID.value

    if ret.flags & HondaFlags.ALLOW_MANUAL_TRANS and all(msg not in fingerprint[CAN.pt] for msg in (0x191, 0x1A3)):
      # Manual transmission support for allowlisted cars only, to prevent silent fall-through on auto-detection failures
      ret.transmissionType = TransmissionType.manual
    elif 0x191 in fingerprint[CAN.pt] and candidate != CAR.ACURA_RDX:
      # Traditional CVTs, gearshift position in GEARBOX_CVT
      ret.transmissionType = TransmissionType.cvt
    else:
      # Traditional autos, direct-drive EVs and eCVTs, gearshift position in GEARBOX_AUTO
      ret.transmissionType = TransmissionType.automatic

    ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0], [0]]
    ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kpBP = [[0.], [0.]]
    ret.lateralTuning.pid.kf = 0.00006  # conservative feed-forward
    ret.steerActuatorDelay = 0.1
    ret.stoppingDecelRate = 0.3

    if candidate in HONDA_BOSCH:
      ret.longitudinalActuatorDelay = 0.5 # s
      if candidate in HONDA_BOSCH_RADARLESS:
        ret.stopAccel = CarControllerParams.BOSCH_ACCEL_MIN  # stock uses -4.0 m/s^2 once stopped but limited by safety model
    else:
      # default longitudinal tuning for all hondas
      ret.longitudinalTuning.kiBP = [0., 5., 35.]
      ret.longitudinalTuning.kiV = [1.2, 0.8, 0.5]

    eps_modified = False
    is_c120_modified_eps = False
    for fw in car_fw:
      if fw.ecu == "eps" and b"," in fw.fwVersion:
        eps_modified = True
        if normalize_honda_eps_fw(fw.fwVersion) == "39990-TBA-C120":
          is_c120_modified_eps = True

    if eps_modified:
      ret.flags |= HondaFlags.EPS_MODIFIED.value

    # VGR is selected by the exact EPS image, not by vehicle family and not by
    # the generic comma-based modified-EPS detector. Unknown firmware gets no
    # VGR override and therefore retains the normal fixed steer ratio.
    vgr_profile = get_honda_vgr_profile(car_fw)
    if vgr_profile is not None:
      ret.flags |= int(HONDA_VGR_PROFILE_FLAGS[vgr_profile])

    if candidate == CAR.HONDA_CITY_7G:
      ret.vEgoStopping = 2.0
      ret.stoppingDecelRate = 0.3
    else:
      ret.vEgoStopping = 0.5
      ret.stoppingDecelRate = 0.1
    ret.vEgoStarting = ret.vEgoStopping

    if candidate == CAR.HONDA_CIVIC:
      if eps_modified:
        # stock request input values:     0x0000, 0x00DE, 0x014D, 0x01EF, 0x0290, 0x0377, 0x0454, 0x0610, 0x06EE
        # stock request output values:    0x0000, 0x0917, 0x0DC5, 0x1017, 0x119F, 0x140B, 0x1680, 0x1680, 0x1680
        # modified request output values: 0x0000, 0x0917, 0x0DC5, 0x1017, 0x119F, 0x140B, 0x1680, 0x2880, 0x3180
        # stock filter output values:     0x009F, 0x0108, 0x0108, 0x0108, 0x0108, 0x0108, 0x0108, 0x0108, 0x0108
        # modified filter output values:  0x009F, 0x0108, 0x0108, 0x0108, 0x0108, 0x0108, 0x0108, 0x0400, 0x0480
        # note: max request allowed is 4096, but request is capped at 3840 in firmware, so modifications result in 2x max
        # NRDR 39990-TBA,A030 linear-max: the modded table ramps linearly to the 3840 firmware cap,
        # so the piecewise breakpoints collapse to a single ramp.
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 3840], [0, 3840]]
        # Shares the modified-EPS Bosch tune: four-point handoff at 25 mph.
        ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.018, 0.024, 0.048, 0.060]]
        ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.006, 0.008, 0.016, 0.020]]
        ret.lateralTuning.pid.kf = 3.6e-6
        ret.steerAtStandstill, ret.autoResumeSng = True, True
        ret.minEnableSpeed, ret.minSteerSpeed = -1.0, -1.0
      else:
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560], [0, 2560]]
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[1.1], [0.33]]

    elif candidate in (CAR.HONDA_CIVIC_BOSCH, CAR.HONDA_CIVIC_BOSCH_DIESEL):
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
      if eps_modified:
        # NRDR modified-EPS Bosch tune: four-point handoff at 25 mph, with C020's native
        # command range and rack model retained.
        ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.018, 0.024, 0.048, 0.060]]
        ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.006, 0.008, 0.016, 0.020]]
        ret.lateralTuning.pid.kf = 3.6e-6
        ret.steerAtStandstill, ret.autoResumeSng = True, True
        ret.minEnableSpeed, ret.minSteerSpeed = -1.0, -1.0
        if is_c120_modified_eps:
          # NRDR 39990-TBA-C120 linear-max: the modded table ramps linearly to the 3840
          # firmware cap, so the piecewise breakpoints collapse to a single ramp. C020 is
          # left on the 4096 range above -- its native command range and rack model are
          # retained -- this only applies to the C120 image specifically.
          ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 3840], [0, 3840]]
      else:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]
      if candidate == CAR.HONDA_CIVIC_BOSCH:
          CarControllerParams.BOSCH_GAS_LOOKUP_V = [0, 750]

    elif candidate == CAR.HONDA_CIVIC_2022:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
      if eps_modified:
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2564, 8000], [0, 2564, 3840]]
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.3], [0.09]]  # 2.5x Modded EPS
      else:
        ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0, 10], [0.05, 0.5]]
        ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0, 10], [0.0125, 0.125]]

    elif candidate == CAR.HONDA_ACCORD:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
      if eps_modified:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.3], [0.09]]
      else:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.6], [0.18]]
      if ret.transmissionType == TransmissionType.manual:
        CarControllerParams.BOSCH_GAS_LOOKUP_BP = [-0.2, 2.0]

    elif candidate == CAR.HONDA_ACCORD_11G:
      ret.steerActuatorDelay = 0.22
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560, 5200], [0, 2560, 12747]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    elif candidate == CAR.ACURA_ILX:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 3840], [0, 3840]]  # TODO: determine if there is a dead zone at the top end
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]

    elif candidate in (CAR.HONDA_CRV, CAR.HONDA_CRV_EU):
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 1000], [0, 1000]]  # TODO: determine if there is a dead zone at the top end
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]
      ret.wheelSpeedFactor = 1.025

    elif candidate == CAR.HONDA_CRV_5G:
      if eps_modified:
        # stock request input values:     0x0000, 0x00DB, 0x01BB, 0x0296, 0x0377, 0x0454, 0x0532, 0x0610, 0x067F
        # stock request output values:    0x0000, 0x0500, 0x0A15, 0x0E6D, 0x1100, 0x1200, 0x129A, 0x134D, 0x1400
        # modified request output values: 0x0000, 0x0500, 0x0A15, 0x0E6D, 0x1100, 0x1200, 0x1ACD, 0x239A, 0x2800
        # NRDR 39990-TLA-A040 linear-max: linear ramp to the 4096 cap, so the piecewise breakpoints
        # collapse to a single segment. Matches nrdr's own CR-V 5G range.
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]
        # NRDR modified-EPS tune, shared with the Clarity/Civics/Insight. The speed banding lives
        # HERE rather than in the runtime LatPScale/LatIScale params, which are neutralized to
        # 100% and act as fine-trim on top. Do not re-band in both places.
        ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.018, 0.024, 0.048, 0.060]]
        ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.006, 0.008, 0.016, 0.020]]
        # kf is banded too, in latcontrol_pid.py's NRDR_MODIFIED_EPS_KF_CARS path; this scalar
        # is the fallback for anything not on that path.
        ret.lateralTuning.pid.kf = 3.6e-6
        ret.steerAtStandstill, ret.autoResumeSng = True, True
        ret.minEnableSpeed, ret.minSteerSpeed = -1.0, -1.0
      else:
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 3840], [0, 3840]]
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.64], [0.192]]
      ret.wheelSpeedFactor = 1.025

    elif candidate == CAR.HONDA_CRV_HYBRID:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.6], [0.18]]
      ret.wheelSpeedFactor = 1.025

    elif candidate == CAR.HONDA_CRV_6G:
      ret.steerActuatorDelay = 0.15
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 5100], [0, 5100]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
      if ret.flags & HondaFlags.HYBRID:
        CarControllerParams.BOSCH_GAS_LOOKUP_BP = [-0.3, 2.0]

    elif candidate == CAR.HONDA_FIT:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.2], [0.05]]

    elif candidate == CAR.HONDA_FREED:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.2], [0.05]]

    elif candidate in (CAR.HONDA_HRV, CAR.HONDA_HRV_3G):
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]
      if candidate == CAR.HONDA_HRV:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.16], [0.025]]
        ret.wheelSpeedFactor = 1.025
      else:
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]  # TODO: can probably use some tuning
        # The 3G HR-V settles more cleanly in lead follow when planner delay
        # better matches its stronger immediate longitudinal response.
        ret.longitudinalActuatorDelay = 0.4

    elif candidate == CAR.HONDA_CLARITY:
      if eps_modified:
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 3840], [0, 3840]]
        # NRDR modified-EPS tune, shared with the Civics and Insight. The speed banding lives
        # HERE rather than in the runtime LatPScale/LatIScale params, which are neutralized to
        # 100% and act as fine-trim on top. Do not re-band in both places.
        #
        # nrdr 2026-07-29 (36e97ec6c2) bakes in their road-tested 50% low-speed trim: below
        # 25 mph kp/ki/kf are half the standard-speed tune. That half previously lived only as
        # a written param value on their device, so it was invisible in the repo when this tune
        # was first ported on 07-27. The near-duplicate breakpoint just below 25 mph reproduces
        # their hard handoff to the unchanged standard-speed tune.
        ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.018, 0.024, 0.048, 0.060]]
        ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.006, 0.008, 0.016, 0.020]]
        # kf is banded too, but this schema has no kfBP/kfV (nightly added them as capnp
        # fields @5/@6). The modified-EPS KF curve lives in latcontrol_pid.py; this scalar is
        # the fallback for anything not on that path.
        ret.lateralTuning.pid.kf = 3.6e-6
        ret.steerAtStandstill, ret.autoResumeSng = True, True
        ret.minEnableSpeed, ret.minSteerSpeed = -1.0, -1.0
      else:
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560], [0, 2560]]
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]
      ret.stopAccel = 0.0

    elif candidate == CAR.ACURA_RDX:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 1000], [0, 1000]]  # TODO: determine if there is a dead zone at the top end
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]

    elif candidate == CAR.ACURA_RDX_3G:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4095], [0, 4095]]
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.2], [0.06]]
      CarControllerParams.BOSCH_GAS_LOOKUP_V = [0, 2200]

    elif candidate == CAR.ACURA_RDX_3G_MMR:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 3840], [0, 3840]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
      CarControllerParams.BOSCH_GAS_LOOKUP_V = [0, 2000]
      if not ret.openpilotLongitudinalControl:
        ret.minSteerSpeed = 70. * CV.KPH_TO_MS

    elif candidate == CAR.HONDA_ODYSSEY:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.28], [0.08]]
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end

    elif candidate == CAR.HONDA_ODYSSEY_TWN:
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.28], [0.08]]
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 32767], [0, 32767]]

    elif candidate in (CAR.HONDA_PILOT, CAR.HONDA_PILOT_4G):
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0, 10], [0.05, 0.5]]
      ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0, 10], [0.0125, 0.125]]

    elif candidate == CAR.ACURA_MDX_4G:
      ret.steerActuatorDelay = 0.15
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560, 4209], [0, 2560, 9150]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    elif candidate == CAR.ACURA_MDX_4G_MMR:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560, 4920], [0, 2560, 12000]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    elif candidate == CAR.HONDA_RIDGELINE:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.38], [0.11]]

    elif candidate == CAR.HONDA_INSIGHT:
      if eps_modified:
        # NRDR 39990-TXM-A040 linear-max: linear ramp to the 3840 cap.
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 3840], [0, 3840]]
        # Shares the modified-EPS Clarity tune: four-point handoff at 25 mph.
        ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.018, 0.024, 0.048, 0.060]]
        ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0., 25. * CV.MPH_TO_MS - 1e-3, 25. * CV.MPH_TO_MS, 50. * CV.MPH_TO_MS], [0.006, 0.008, 0.016, 0.020]]
        ret.lateralTuning.pid.kf = 3.6e-6
        ret.steerAtStandstill, ret.autoResumeSng = True, True
        ret.minEnableSpeed, ret.minSteerSpeed = -1.0, -1.0
      else:
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.6], [0.18]]

    elif candidate == CAR.HONDA_NBOX_2G:
      # JDM kei car, unrelated to the modified-EPS fleet. Left on the pre-split tune it
      # shared with the Insight rather than moved onto the Clarity numbers untested.
      if eps_modified:
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 3840], [0, 3840]]
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.06], [0.02]]
        ret.lateralTuning.pid.kf = 0.000024
        ret.steerAtStandstill, ret.autoResumeSng = True, True
        ret.minEnableSpeed, ret.minSteerSpeed = -1.0, -1.0
      else:
        ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
        ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.6], [0.18]]

    elif candidate in (CAR.HONDA_E, CAR.HONDA_E_ADVANCE):
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]  # TODO: determine if there is a dead zone at the top end
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.6], [0.18]] # TODO: can probably use some tuning

    elif candidate == CAR.HONDA_ODYSSEY_5G_MMR:
      # Stock camera sends up to 2560 during LKA operation and up to 3840 during RDM operation
      # Steer motor torque does rise a little above 2560, but not linearly, RDM also applies one-sided brake drag
      #ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560, 3072], [0, 2560, 3840]]
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560], [0, 2560]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
      ret.steerActuatorDelay = 0.15
      CarControllerParams.BOSCH_GAS_LOOKUP_V = [0, 2000]
      if not ret.openpilotLongitudinalControl:
        # When using stock ACC, the radar intercepts and filters steering commands the EPS would otherwise accept
        ret.minSteerSpeed = 70. * CV.KPH_TO_MS

    elif candidate == CAR.ACURA_TLX_2G_MMR:
      ret.steerActuatorDelay = 0.15
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0, 10], [0.05, 0.5]]
      ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0, 10], [0.0125, 0.125]]

    elif candidate in (CAR.HONDA_FIT_4G,):
      ret.steerActuatorDelay = 0.15
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    elif candidate == CAR.ACURA_INTEGRA:
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 4096], [0, 4096]]
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.8], [0.24]]

    elif candidate == CAR.ACURA_ADX:
      ret.steerActuatorDelay = 0.15
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 5000], [0, 5000]]
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kpV = [[0, 10], [0.05, 0.5]]
      ret.lateralTuning.pid.kiBP, ret.lateralTuning.pid.kiV = [[0, 10], [0.0125, 0.125]]

    elif candidate == CAR.HONDA_PASSPORT_4G:
      ret.steerActuatorDelay = 0.15
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560, 5120], [0, 2560, 12789]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    else:
      ret.steerActuatorDelay = 0.15
      ret.lateralParams.torqueBP, ret.lateralParams.torqueV = [[0, 2560], [0, 2560]]
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    # These cars use alternate user brake msg (0x1BE)
    if 0x1BE in fingerprint[CAN.pt] and candidate in (CAR.HONDA_ACCORD, CAR.HONDA_HRV_3G, CAR.ACURA_RDX_3G, CAR.ACURA_MDX_4G,
                                                      CAR.ACURA_ADX, *HONDA_BOSCH_CANFD):
      ret.flags |= HondaFlags.BOSCH_ALT_BRAKE.value

    if ret.flags & HondaFlags.BOSCH_ALT_BRAKE:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.ALT_BRAKE.value
    if candidate in HONDA_NIDEC_ALT_SCM_MESSAGES:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.NIDEC_ALT.value
    if ret.enableGasInterceptorDEPRECATED:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.GAS_INTERCEPTOR.value
    if (ret.flags & HondaFlags.NIDEC) and (ret.flags & HondaFlags.HYBRID):
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.NIDEC_HYBRID.value
      # some Nidec hybrids report brake hold via BRAKE_HOLD_HYBRID_ALT instead of VSA_STATUS
      if 0x223 in fingerprint[CAN.pt]:
        ret.flags |= HondaFlags.HYBRID_ALT_BRAKEHOLD.value
    if ret.openpilotLongitudinalControl and candidate in HONDA_BOSCH:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.BOSCH_LONG.value
    if candidate in HONDA_BOSCH_RADARLESS:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.RADARLESS.value
    if candidate in HONDA_BOSCH_CANFD:
      ret.safetyConfigs[-1].safetyParam |= HondaSafetyFlags.BOSCH_CANFD.value

    # min speed to enable ACC. if car can do stop and go, then set enabling speed
    # to a negative value, so it won't matter. Otherwise, add 0.5 mph margin to not
    # conflict with PCM acc
    if candidate == CAR.HONDA_FIT_4G and not ret.openpilotLongitudinalControl:
      ret.autoResumeSng = False
    elif ret.transmissionType == TransmissionType.manual and not ret.openpilotLongitudinalControl:
      ret.autoResumeSng = False
    else:
      ret.autoResumeSng = candidate in (HONDA_BOSCH | {CAR.HONDA_CIVIC, CAR.HONDA_CLARITY}) or ret.enableGasInterceptorDEPRECATED

    if ret.autoResumeSng:
      ret.minEnableSpeed = -1.
    elif candidate == CAR.HONDA_ODYSSEY_TWN:
      ret.minEnableSpeed = 19. * CV.MPH_TO_MS
    elif candidate == CAR.HONDA_FIT_4G:
      ret.minEnableSpeed = 30. * CV.KPH_TO_MS
    else:
      ret.minEnableSpeed = 25.51 * CV.MPH_TO_MS

    if candidate == CAR.HONDA_PILOT_4G:
      CarControllerParams.BOSCH_GAS_LOOKUP_V = [0, 2200]

    ret.steerLimitTimer = 0.8
    ret.radarDelay = 0.1

    return ret

  @staticmethod
  def init(CP, can_recv, can_send, communication_control=None):
    if CP.carFingerprint in (HONDA_BOSCH - HONDA_BOSCH_RADARLESS) and CP.openpilotLongitudinalControl:
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
