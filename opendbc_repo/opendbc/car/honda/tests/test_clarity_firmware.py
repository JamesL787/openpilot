import itertools

import pytest

from opendbc.car import structs
from opendbc.car.fw_versions import match_fw_to_car
from opendbc.car.honda.firmware_validation import validate_fw_match
from opendbc.car.honda.fingerprints import FW_VERSIONS
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.tests.test_modified_eps import params
from opendbc.car.honda.values import CAR, CarControllerParams, HondaFlags

Ecu = structs.CarParams.Ecu
SOURCE = {
  (Ecu.shiftByWire, 0x18DA0BF1): (b"54008-TRW-A910\x00\x00",),
  (Ecu.vsa, 0x18DA28F1): (b"57114-TRW-A010\x00\x00", b"57114-TRW-A020\x00\x00"),
  (Ecu.eps, 0x18DA30F1): (b"39990-TRW-A020\x00\x00", b"39990-TRW,A020\x00\x00"),
  (Ecu.srs, 0x18DA53F1): (b"77959-TRW-A210\x00\x00", b"77959-TRW-A220\x00\x00"),
  (Ecu.gateway, 0x18DAEFF1): (b"38897-TRW-A010\x00\x00",),
  (Ecu.fwdRadar, 0x18DAB0F1): (b"36161-TRW-A110\x00\x00",),
}


def cohort(values=None):
  selected = values if values is not None else [versions[0] for versions in SOURCE.values()]
  return [structs.CarParams.CarFw(ecu=ecu, address=address, subAddress=0, fwVersion=version, brand="honda")
          for (ecu, address), version in zip(SOURCE, selected, strict=True)]


@pytest.mark.parametrize("versions", tuple(itertools.product(*SOURCE.values())))
def test_complete_original_cohort_exact_and_fuzzy_keep_correct_controller(versions):
  fw = cohort(versions)
  for allow_exact in (True, False):
    assert match_fw_to_car(fw, "", allow_exact=allow_exact, log=False)[1] == {CAR.HONDA_CLARITY}
  cp = params(CAR.HONDA_CLARITY, fw)
  assert not cp.dashcamOnly
  modified = any(b"," in version for version in versions)
  assert bool(cp.flags & HondaFlags.EPS_MODIFIED) == modified
  if modified:
    # the modified Clarity runs the four-point modified-EPS tune on its linear 3840 map
    assert list(cp.lateralTuning.pid.kpV) == pytest.approx([0.018, 0.024, 0.048, 0.060])
    assert list(cp.lateralTuning.pid.kiV) == pytest.approx([0.006, 0.008, 0.016, 0.020])
    assert CarControllerParams(cp).STEER_LOOKUP == [-3840, 0, 3840]
  else:
    assert list(cp.lateralTuning.pid.kpV) == pytest.approx([0.8])
    assert list(cp.lateralTuning.pid.kiV) == pytest.approx([0.24])
    assert CarControllerParams(cp).STEER_LOOKUP == [-2560, 0, 2560]
  ci = CarInterface(cp)
  assert (ci.CC.modified_eps_steering is not None) == modified   # the modified-EPS steering stage


def test_cohort_without_radar_response_fingerprints():
  # what the modified Clarity actually answers: EPS, VSA and SRS, no fwdRadar/gateway/shift-by-wire
  answered = {Ecu.eps: b"39990-TRW,A020\x00\x00", Ecu.vsa: b"57114-TRW-A010\x00\x00", Ecu.srs: b"77959-TRW-A210\x00\x00"}
  fw = [structs.CarParams.CarFw(ecu=ecu, address=address, subAddress=0, fwVersion=answered[ecu], brand="honda")
        for ecu, address in SOURCE if ecu in answered]
  assert match_fw_to_car(fw, "", log=False)[1] == {CAR.HONDA_CLARITY}


@pytest.mark.parametrize("ecu,corruption", [(ecu, corruption) for ecu in (Ecu.eps, Ecu.vsa, Ecu.fwdRadar)
                                            for corruption in ("missing", "unknown", "mixed")
                                            if not (ecu == Ecu.fwdRadar and corruption == "missing")])
def test_mandatory_evidence_cannot_fall_through_to_fuzzy(ecu, corruption):
  fw = cohort()
  original = next(observation for observation in fw if observation.ecu == ecu)
  if corruption == "missing":
    fw = [observation for observation in fw if observation.ecu != ecu]
  else:
    bad = structs.CarParams.CarFw(ecu=ecu, address=original.address, subAddress=0,
                                 fwVersion=b"39990-TBA-A030\x00\x00" if ecu == Ecu.eps else b"UNKNOWN", brand="honda")
    fw = fw + [bad] if corruption == "mixed" else [bad if observation.ecu == ecu else observation for observation in fw]
  for allow_exact in (True, False):
    assert CAR.HONDA_CLARITY not in match_fw_to_car(fw, "", allow_exact=allow_exact, log=False)[1]


@pytest.mark.parametrize("ecu", (Ecu.srs, Ecu.gateway, Ecu.shiftByWire))
def test_unknown_present_optional_firmware_is_not_ignored(ecu):
  fw = cohort()
  next(observation for observation in fw if observation.ecu == ecu).fwVersion = b"UNKNOWN"
  assert CAR.HONDA_CLARITY not in match_fw_to_car(fw, "", log=False)[1]


def test_other_honda_candidates_are_not_restricted():
  for candidate in CAR:
    if candidate != CAR.HONDA_CLARITY:
      assert validate_fw_match(candidate, {}, FW_VERSIONS)
