from types import SimpleNamespace

from opendbc.car.honda.values import CAR as HONDA_CAR, HondaFlags
from opendbc.car.hyundai.values import CAR as HYUNDAI_CAR, HyundaiFlags
from opendbc.car.tesla.values import CAR as TESLA_CAR

from openpilot.starpilot.common.vehicle_settings_capabilities import (
  SETTING_CAPABILITY_REQUIREMENTS,
  get_setting_capabilities,
  get_vehicle_setting_capabilities,
)


class _LateralTuning:
  def __init__(self, kind):
    self._kind = kind

  def which(self):
    return self._kind


def _cp(*, brand="", fingerprint="", flags=0, longitudinal=False, alpha=False,
        pedal=False, radar_unavailable=False, auto_resume_sng=False, lateral="pid"):
  return SimpleNamespace(
    brand=brand,
    carFingerprint=fingerprint,
    flags=flags,
    openpilotLongitudinalControl=longitudinal,
    alphaLongitudinalAvailable=alpha,
    enableGasInterceptorDEPRECATED=pedal,
    radarUnavailable=radar_unavailable,
    autoResumeSng=auto_resume_sng,
    lateralTuning=_LateralTuning(lateral),
  )


def test_honda_bosch_uses_honda_stop_controls_not_generic_duplicates():
  crv = _cp(
    brand="honda",
    fingerprint="HONDA_CRV_5G",
    flags=HondaFlags.BOSCH.value | HondaFlags.EPS_MODIFIED.value,
    longitudinal=True,
    alpha=True,
  )

  capabilities = get_vehicle_setting_capabilities(crv)
  settings = get_setting_capabilities(crv)

  assert capabilities["HasHondaLongitudinal"]
  assert capabilities["HasHondaModifiedEpsLateral"]
  assert not capabilities["HasHondaNidecLongitudinal"]
  assert not capabilities["HasGenericStopTuning"]
  assert not settings["StopAccel"]
  assert not settings["NrdrHondaEcuMatchedLong"]
  assert not settings["NrdrHondaFullBrakeAuthority"]
  assert not settings["NrdrRoenAccelerationLimits"]
  assert settings["HondaLiveLearningGas"]
  assert settings["LongPidTuneScaleAggressive"]
  assert settings["HondaStopAccel"]
  assert settings["NrdrBoschARadar"]
  assert settings["BoschLong"]


def test_honda_nidec_and_pedal_controller_paths_are_distinct():
  nidec = _cp(brand="honda", fingerprint="HONDA_CIVIC", longitudinal=True)
  pedal = _cp(brand="honda", fingerprint="HONDA_CIVIC", longitudinal=True, pedal=True)

  assert get_vehicle_setting_capabilities(nidec)["HasHondaNidecLongitudinal"]
  assert not get_vehicle_setting_capabilities(pedal)["HasHondaNidecLongitudinal"]


def test_vehicle_controls_require_the_exact_vehicle_or_hardware():
  generic_gm = _cp(brand="gm", fingerprint="CHEVROLET_EQUINOX", longitudinal=True)
  gm_pedal = _cp(brand="gm", fingerprint="CHEVROLET_BOLT_ACC_2022_2023", pedal=True)
  model_3 = _cp(brand="tesla", fingerprint=str(TESLA_CAR.TESLA_MODEL_3))
  preap = _cp(brand="tesla", fingerprint=str(TESLA_CAR.TESLA_MODEL_S_PREAP))

  generic_settings = get_setting_capabilities(generic_gm)
  pedal_settings = get_setting_capabilities(gm_pedal)
  model_3_caps = get_vehicle_setting_capabilities(model_3)
  preap_caps = get_vehicle_setting_capabilities(preap)

  assert generic_settings["IgnoreIgnitionLine"]
  assert generic_settings["LongPitch"]
  assert not generic_settings["GMPedalLongitudinal"]
  assert pedal_settings["GMPedalLongitudinal"]
  assert pedal_settings["RemapCancelToDistance"]
  assert model_3_caps["HasTeslaModel3"]
  assert not model_3_caps["HasTeslaPreAP"]
  assert preap_caps["HasTeslaPreAP"]
  assert not preap_caps["HasTeslaModel3"]


def test_hyundai_canfd_and_longitudinal_gates_are_combined():
  ioniq = _cp(
    brand="hyundai",
    fingerprint=str(HYUNDAI_CAR.HYUNDAI_IONIQ_6),
    flags=HyundaiFlags.CANFD.value,
    longitudinal=True,
  )
  stock_long = _cp(
    brand="hyundai",
    fingerprint=str(HYUNDAI_CAR.HYUNDAI_IONIQ_6),
    flags=HyundaiFlags.CANFD.value,
  )

  active_settings = get_setting_capabilities(ioniq)
  stock_settings = get_setting_capabilities(stock_long)

  assert active_settings["HKGRemoteStartBootsComma"]
  assert active_settings["NostalgiaMode"]
  assert active_settings["ModeButtonControl"]
  assert not stock_settings["HKGRemoteStartBootsComma"]
  assert not stock_settings["NostalgiaMode"]
  assert stock_settings["ModeButtonControl"]


def test_catalogue_has_explicit_gates_for_all_platform_specific_controls():
  expected = {
    "HondaCenterScale", "NrdrHondaEcuMatchedLong", "NrdrHondaFullBrakeAuthority",
    "HondaLiveLearningGas", "LongPidTuneScaleAggressive", "HondaStopAccel", "BoschLong", "NrdrBlotV2",
    "TeslaCoopSteering", "NAPRadarEnabled", "GMPedalLongitudinal", "LongPitch",
    "VoltSNG", "JeepBrakeHold", "SubaruSNG", "ToyotaAutoHold",
    "RivianAngleControl", "NostalgiaMode", "ModeButtonControl",
  }

  assert expected <= SETTING_CAPABILITY_REQUIREMENTS.keys()
