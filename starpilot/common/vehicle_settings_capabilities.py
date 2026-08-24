"""Capabilities used to decide whether a vehicle-specific setting is meaningful.

The settings frontends deliberately keep a user's stored values intact.  This module
only answers whether a setting applies to the detected vehicle and active controller,
so the native UI, Galaxy, and Favorites can all hide the same irrelevant controls.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opendbc.car.chrysler.values import JEEPS as CHRYSLER_JEEPS
from opendbc.car.gm.values import CAR as GM_CAR
from opendbc.car.honda.values import CAR as HONDA_CAR, HONDA_BOSCH_A, HondaFlags
from opendbc.car.hyundai.values import CAR as HYUNDAI_CAR, HyundaiFlags
from opendbc.car.subaru.values import SubaruFlags
from opendbc.car.tesla.values import CAR as TESLA_CAR
from opendbc.car.toyota.values import RADAR_ACC_CAR, SECOC_CAR, TSS2_CAR


def _text(value: Any) -> str:
  return str(value or "")


def _bool_attr(cp: Any, name: str) -> bool:
  return bool(getattr(cp, name, False)) if cp is not None else False


def _int_attr(cp: Any, name: str) -> int:
  try:
    return int(getattr(cp, name, 0)) if cp is not None else 0
  except (TypeError, ValueError):
    return 0


def _lateral_tuning_kind(cp: Any) -> str:
  try:
    return str(cp.lateralTuning.which())
  except (AttributeError, TypeError):
    return ""


def _is_in(fingerprint: str, cars: Any) -> bool:
  return fingerprint in {_text(candidate) for candidate in cars}


LEGACY_VOLT_STOCK_ACC_CARS = {
  GM_CAR.CHEVROLET_VOLT,
  GM_CAR.CHEVROLET_VOLT_2019,
  GM_CAR.CHEVROLET_VOLT_ASCM,
  GM_CAR.CHEVROLET_VOLT_CAMERA,
}


# Each listed key is hidden unless its matching capability is true.  Keep this
# catalogue next to the predicates rather than maintaining separate make lists in
# every UI.  Generic settings are intentionally absent.
SETTING_CAPABILITY_REQUIREMENTS: dict[str, str] = {
  # Generic controller choices whose implementation is controller-specific.
  "ForceAutoTune": "HasTorqueLateral",
  "ForceAutoTuneOff": "HasTorqueLateral",
  "ForceTorqueController": "HasForceTorqueController",
  "NNFF": "HasNonAngleLateral",
  "NNFFLite": "HasNonAngleLateral",
  "SteerFriction": "HasTorqueLateral",
  "SteerKP": "HasTorqueLateral",
  "SteerLatAccel": "HasTorqueLateral",
  "StopAccel": "HasGenericStopTuning",
  "StoppingDecelRate": "HasGenericStopTuning",
  "VEgoStarting": "HasGenericStopTuning",
  "VEgoStopping": "HasGenericStopTuning",

  # Honda modified-EPS lateral tuning.
  "HondaCenterScale": "HasHondaModifiedEpsLateral",
  "HondaCenterBoostThreshold": "HasHondaModifiedEpsLateral",
  "HondaCenterBoostMinSpeed": "HasHondaModifiedEpsLateral",
  "HondaUnwindFreeze": "HasHondaModifiedEpsLateral",
  "HondaUnwindBoostSeconds": "HasHondaModifiedEpsLateral",
  "HondaUnwindFfMultiplier": "HasHondaModifiedEpsLateral",
  "LatPScaleLowSpeed": "HasHondaModifiedEpsLateral",
  "LatIScaleLowSpeed": "HasHondaModifiedEpsLateral",
  "LatFScaleLowSpeed": "HasHondaModifiedEpsLateral",
  "LatPScaleStandard": "HasHondaModifiedEpsLateral",
  "LatIScaleStandard": "HasHondaModifiedEpsLateral",
  "LatFScaleStandard": "HasHondaModifiedEpsLateral",
  "LatPScaleHighway": "HasHondaModifiedEpsLateral",
  "LatIScaleHighway": "HasHondaModifiedEpsLateral",
  "LatFScaleHighway": "HasHondaModifiedEpsLateral",
  "NrdrLearnSteerRatio": "HasHondaModifiedEpsLateral",
  "NrdrLearnStiffness": "HasHondaModifiedEpsLateral",
  "NrdrLearnAngleOffset": "HasHondaModifiedEpsLateral",
  "NrdrTuneLearner": "HasHondaModifiedEpsLateral",
  "NrdrTuneLearnerStrength": "HasHondaModifiedEpsLateral",
  "NrdrTuneLearnerRate": "HasHondaModifiedEpsLateral",
  "NrdrTuneLearnerReset": "HasHondaModifiedEpsLateral",
  "NrdrLatStiction": "HasHondaModifiedEpsLateral",
  "HondaLateralPidKpScale": "HasHondaPidLateral",
  "HondaLateralPidKiScale": "HasHondaPidLateral",

  # Honda CarController controls and the two Bosch-only experiments.
  "NrdrIncreaseOverrideTolerance": "HasHonda",
  "NrdrDriverOverrideThreshold": "HasHonda",
  "NrdrOverrideThresholdCenterBoost": "HasHonda",
  "HondaDriverAssistDuringOverride": "HasHonda",
  "HondaOverrideFadeDownSecs": "HasHonda",
  "HondaOverrideFadeUpSecs": "HasHonda",
  "HondaOverrideTorqueScale": "HasHonda",
  "HondaTorqueLowPassFilter": "HasHonda",
  "HondaLpfTauLowSpeed": "HasHonda",
  "HondaLpfTauStandard": "HasHonda",
  "HondaLpfTauHighway": "HasHonda",
  "HondaSteerDeltaLimiter": "HasHonda",
  "HondaSteerDeltaUp": "HasHonda",
  "HondaSteerDeltaDown": "HasHonda",
  "NrdrMinSteerSpeed": "HasHonda",
  "NrdrHondaEcuMatchedLong": "HasHondaNidecLongitudinal",
  "NrdrHondaFullBrakeAuthority": "HasHondaNidecLongitudinal",
  "NrdrRoenAccelerationLimits": "HasHondaNidecLongitudinal",
  "HondaStoppingDecelRate": "HasHondaNidecLongitudinal",
  "HondaLiveLearningGas": "HasHondaLongitudinal",
  "NrdrHondaDashVariantB": "HasHonda",
  "LongPidTuneScale": "HasHondaLongitudinal",
  "LongPidTuneScaleAggressive": "HasHondaLongitudinal",
  "LongPidTuneScaleStandard": "HasHondaLongitudinal",
  "LongPidTuneScaleRelaxed": "HasHondaLongitudinal",
  "LongPidTuneScaleEcon": "HasHondaLongitudinal",
  "StaticFeedforwardLong": "HasHondaLongitudinal",
  "HondaStopAccel": "HasHondaLongitudinal",
  "HondaStoppingDecelRateLong": "HasHondaLongitudinal",
  "HondaVEgoStarting": "HasHondaLongitudinal",
  "HondaVEgoStopping": "HasHondaLongitudinal",
  "NrdrBoschARadar": "HasHondaBoschARadar",
  "BoschLong": "HasHondaBoschLong",
  "NrdrBlotV2": "HasCivicBoschLong",

  # Vehicle settings and physical controller hardware.
  "RivianAngleControl": "HasRivianAngleHarness",
  "TeslaCoopSteering": "HasTeslaModel3",
  "NAPRadarEnabled": "HasTeslaPreAP",
  "NAPRadarBehindNosecone": "HasTeslaPreAP",
  "NAPRadarOffset": "HasTeslaPreAP",
  "NAPPedalEnabled": "HasTeslaPreAP",
  "NAPPedalCanBus": "HasTeslaPreAP",
  "NAPAdaptiveAccel": "HasTeslaPreAP",
  "NAPPedalCalibDone": "HasTeslaPreAP",
  "NAPPedalCalibFactor": "HasTeslaPreAP",
  "NAPPedalCalibZero": "HasTeslaPreAP",
  "GMPedalLongitudinal": "HasGMPedal",
  "GMDashSpoofOffsets": "HasGMPedal",
  "IgnoreIgnitionLine": "HasGM",
  "LongPitch": "HasGMLongitudinal",
  "RemoteStartBootsComma": "HasGM",
  "VoltSNG": "HasLegacyVoltStockAcc",
  "GMAutoHold": "HasLegacyVoltStockAcc",
  "VoltOnePedalMode": "HasLegacyVoltStockAcc",
  "JeepBrakeHold": "HasJeepBrakeHold",
  "SubaruSNG": "HasSubaruSNG",
  "SubaruSNGManualParkingBrake": "HasSubaruSNG",
  "ClusterOffset": "HasToyota",
  "SNGHack": "HasToyotaSNGHack",
  "ToyotaAutoHold": "HasToyotaAutoHold",
  "RemapCancelToDistance": "HasBoltPedal",
  "HKGRemoteStartBootsComma": "HasHKGRemoteClimate",
  "NostalgiaMode": "HasNostalgiaMode",
  "CancelButtonControl": "HasBoltPedal",
  "LongCancelButtonControl": "HasBoltPedal",
  "VeryLongCancelButtonControl": "HasBoltPedal",
  "LKASButtonControl": "HasLKASButton",
  "ModeButtonControl": "HasHKGCanFdMediaButtons",
  "LongModeButtonControl": "HasHKGCanFdMediaButtons",
  "VeryLongModeButtonControl": "HasHKGCanFdMediaButtons",
  "StarButtonControl": "HasHKGCanFdMediaButtons",
  "LongStarButtonControl": "HasHKGCanFdMediaButtons",
  "VeryLongStarButtonControl": "HasHKGCanFdMediaButtons",

  # Radar-dependent long features are controller-independent, but still cannot
  # operate on a radarless fingerprint.
  "HumanLaneChanges": "HasRadar",
  "RadarTakeoffs": "HasRadar",
}


def get_vehicle_setting_capabilities(cp: Any | None, *, disable_openpilot_longitudinal: bool = False,
                                     has_rivian_angle_harness: bool = False) -> dict[str, bool]:
  """Return the complete UI capability set for an active ``CarParams`` object."""
  brand = _text(getattr(cp, "brand", "")).lower()
  fingerprint = _text(getattr(cp, "carFingerprint", ""))
  flags = _int_attr(cp, "flags")
  has_pedal = _bool_attr(cp, "enableGasInterceptorDEPRECATED")
  has_openpilot_longitudinal = (
    _bool_attr(cp, "openpilotLongitudinalControl") and not disable_openpilot_longitudinal
  )
  has_alpha_longitudinal = _bool_attr(cp, "alphaLongitudinalAvailable")
  has_radar = not _bool_attr(cp, "radarUnavailable")
  lateral_kind = _lateral_tuning_kind(cp)
  is_angle_lateral = lateral_kind == "angle"
  is_torque_lateral = lateral_kind == "torque"
  is_honda = brand == "honda"
  is_honda_pid = is_honda and lateral_kind == "pid" and not is_angle_lateral
  is_honda_bosch = is_honda and bool(flags & HondaFlags.BOSCH.value)
  is_honda_bosch_a = is_honda and _is_in(fingerprint, HONDA_BOSCH_A)
  is_honda_modified_eps = is_honda_pid and bool(flags & HondaFlags.EPS_MODIFIED.value)
  is_hyundai_canfd = brand == "hyundai" and bool(flags & HyundaiFlags.CANFD.value)
  is_toyota = brand == "toyota"
  has_subaru_sng = brand == "subaru" and not bool(
    flags & (SubaruFlags.GLOBAL_GEN2.value | SubaruFlags.HYBRID.value | SubaruFlags.LKAS_ANGLE.value)
  )
  has_legacy_volt_stock_acc = _is_in(fingerprint, LEGACY_VOLT_STOCK_ACC_CARS)
  has_toyota_auto_hold = fingerprint in {
    _text(candidate) for candidate in (TSS2_CAR - RADAR_ACC_CAR - SECOC_CAR)
  }

  return {
    "HasRadar": has_radar,
    "HasAlphaLongitudinal": has_alpha_longitudinal,
    "HasOpenpilotLongitudinal": has_openpilot_longitudinal,
    "HasGenericStopTuning": not (is_honda and has_openpilot_longitudinal),
    "HasNonAngleLateral": not is_angle_lateral,
    "HasTorqueLateral": is_torque_lateral and not is_angle_lateral,
    "HasForceTorqueController": not is_torque_lateral and not is_angle_lateral,
    "HasHonda": is_honda,
    "HasHondaPidLateral": is_honda_pid,
    "HasHondaModifiedEpsLateral": is_honda_modified_eps,
    "HasHondaLongitudinal": is_honda and has_openpilot_longitudinal,
    "HasHondaNidecLongitudinal": is_honda and has_openpilot_longitudinal and not is_honda_bosch and not has_pedal,
    "HasHondaBoschLong": is_honda_bosch and has_openpilot_longitudinal,
    "HasHondaBoschARadar": is_honda_bosch_a,
    "HasCivicBosch": is_honda and fingerprint == _text(HONDA_CAR.HONDA_CIVIC_BOSCH),
    "HasCivicBoschLong": is_honda and fingerprint == _text(HONDA_CAR.HONDA_CIVIC_BOSCH) and has_openpilot_longitudinal,
    "HasGM": brand == "gm",
    "HasGMPedal": brand == "gm" and has_pedal,
    "HasGMLongitudinal": brand == "gm" and has_openpilot_longitudinal,
    "HasLegacyVoltStockAcc": has_legacy_volt_stock_acc,
    "HasBoltPedal": brand == "gm" and fingerprint.startswith("CHEVROLET_BOLT") and has_pedal,
    "HasJeepBrakeHold": brand == "chrysler" and _is_in(fingerprint, CHRYSLER_JEEPS),
    "HasSubaruSNG": has_subaru_sng,
    "HasToyota": is_toyota,
    "HasToyotaSNGHack": is_toyota and has_openpilot_longitudinal and not has_pedal and not _bool_attr(cp, "autoResumeSng"),
    "HasToyotaAutoHold": is_toyota and has_toyota_auto_hold,
    "HasTeslaModel3": fingerprint == _text(TESLA_CAR.TESLA_MODEL_3),
    "HasTeslaPreAP": fingerprint == _text(TESLA_CAR.TESLA_MODEL_S_PREAP),
    "HasRivianAngleHarness": brand == "rivian" and has_rivian_angle_harness,
    "HasHKGCanFdMediaButtons": is_hyundai_canfd,
    "HasHKGRemoteClimate": is_hyundai_canfd and has_openpilot_longitudinal,
    "HasNostalgiaMode": fingerprint == _text(HYUNDAI_CAR.HYUNDAI_IONIQ_6) and has_openpilot_longitudinal,
    "HasLKASButton": brand != "subaru",
  }


def get_setting_capabilities(cp: Any | None, *, disable_openpilot_longitudinal: bool = False,
                             has_rivian_angle_harness: bool = False) -> dict[str, bool]:
  """Return a setting-key map suitable for rendering a settings catalogue."""
  capabilities = get_vehicle_setting_capabilities(
    cp,
    disable_openpilot_longitudinal=disable_openpilot_longitudinal,
    has_rivian_angle_harness=has_rivian_angle_harness,
  )
  return {
    key: capabilities.get(required_capability, False)
    for key, required_capability in SETTING_CAPABILITY_REQUIREMENTS.items()
  }


def is_setting_supported(key: str, capabilities: Mapping[str, bool]) -> bool:
  """Return whether ``key`` has no gate or its declared gate is currently true."""
  requirement = SETTING_CAPABILITY_REQUIREMENTS.get(key)
  return requirement is None or bool(capabilities.get(requirement, False))
