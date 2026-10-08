"""Drive-latched firmware control, with exact EPS-family admission.

Firmware version strings identify the family, not the contents of a modified image.
The owner must still confirm the flashed build. Every image has its own calibration, and
a car with no entry gets no firmware controller: there is no generic Honda fallback.
Entries marked provisional carry values over from another car instead of measuring them.
"""
from dataclasses import dataclass

from opendbc.sunnypilot.car.honda.values_ext import HondaFlagsSP

from openpilot.nrdr.features.lateral.honda_vgr import get_honda_vgr_profile, normalize_honda_eps_firmware


@dataclass(frozen=True)
class FirmwareControllerProfile:
  name: str
  calibration: str
  prediction_schedule: bool = False
  provisional: bool = False


CLARITY_PROFILE = FirmwareControllerProfile("Clarity TRW-A020", "clarity_trw_a020", prediction_schedule=True)
CIVIC_PROFILE = FirmwareControllerProfile("Civic Bosch C020", "civic_bosch_c020")
# Column load measured from the owner's telemetry rlogs of the TEG-A010; R6 from its A table. The live command row is
# set by the car's variant code: TEGA1 selects row 2, TEGA2 row 3 (TEGA0 and TBCA3 disable the LKAS controller, so a
# car that steers is one of those two). Which one is still to be read from a telemetry drive; the calibration carries
# row 1 until then.
TEG_PROFILE = FirmwareControllerProfile("Civic TEG-A010", "civic_teg_a010")
# Column load measured from the owner's telemetry rlogs of this image; R6 from its A table (the angle average of
# which is the owner's telemetry fit).
CRV_PROFILE = FirmwareControllerProfile("CR-V TLA-A040", "crv_tla_a040")
# Tables read from the image; column load carried over from the C020. R6 is the C120's own A table, and the C020's
# measured curve on the TGG-A120 (same A table).
CIVIC_C120_PROFILE = FirmwareControllerProfile("Civic Bosch C120", "civic_bosch_c120", provisional=True)
CIVIC_TGG_PROFILE = FirmwareControllerProfile("Civic hatch TGG-A120", "civic_tgg_a120", provisional=True)
# Column load measured from the owner's rlogs; R6 from its own A table (no telemetry build to measure it).
INSIGHT_PROFILE = FirmwareControllerProfile("Insight TXM-A040", "insight_txm_a040")
_PROFILES = {
  ("HONDA_CLARITY", "39990-TRW-A020"): CLARITY_PROFILE,
  ("HONDA_CIVIC_BOSCH", "39990-TBA-C020"): CIVIC_PROFILE,
  ("HONDA_CIVIC_BOSCH", "39990-TBA-C120"): CIVIC_C120_PROFILE,
  ("HONDA_CIVIC_BOSCH", "39990-TGG-A120"): CIVIC_TGG_PROFILE,
  ("HONDA_CIVIC", "39990-TEG-A010"): TEG_PROFILE,
  ("HONDA_CRV_5G", "39990-TLA-A040"): CRV_PROFILE,
  ("HONDA_INSIGHT", "39990-TXM-A040"): INSIGHT_PROFILE,
}


def _firmware_family(CP) -> FirmwareControllerProfile | None:
  if CP is None or str(getattr(CP, "brand", "")) != "honda":
    return None
  for firmware in getattr(CP, "carFw", ()):
    if firmware.ecu == "eps":
      profile = _PROFILES.get((str(CP.carFingerprint), normalize_honda_eps_firmware(firmware.fwVersion)))
      if profile is not None:
        return profile
  return None


def firmware_controller_profile(CP, CP_SP) -> FirmwareControllerProfile | None:
  profile = _firmware_family(CP)
  if profile is not None and getattr(CP_SP, "flags", 0) & HondaFlagsSP.EPS_MODIFIED.value and \
     get_honda_vgr_profile(CP) is not None and CP.lateralTuning.which() == "pid":
    return profile
  return None


def yaw_controller_available(CP, CP_SP) -> bool:
  # Keep the legacy wire/call-site name; this controller is not a live yaw loop.
  return firmware_controller_profile(CP, CP_SP) is not None


def firmware_controller_selected(params, CP, CP_SP) -> bool:
  """Use the admitted selection, not a stale selector left over from another car."""
  return str(params.get("NrdrLateralController")) in ("1", "b'1'") and yaw_controller_available(CP, CP_SP)


def firmware_controller_profile_for_model(params, CP) -> FirmwareControllerProfile | None:
  """Resolve once per drive, without waiting on Honda-only data for other cars."""
  if _firmware_family(CP) is None or \
     str(params.get("NrdrLateralController")) not in ("1", "b'1'"):
    return None
  from openpilot.cereal import custom, messaging
  CP_SP = messaging.log_from_bytes(params.get("CarParamsSP", block=True), custom.CarParamsSP)
  return firmware_controller_profile(CP, CP_SP)


def firmware_controller_for_model(params, CP) -> bool:
  return firmware_controller_profile_for_model(params, CP) is not None
