from unittest.mock import patch

import pytest

from opendbc.car import car_helpers, gen_empty_fingerprint, structs
from opendbc.car.car_helpers import interfaces
from opendbc.car.supported_brands import SUPPORTED_BRANDS, brand_supported, limit_to_supported_brands
from opendbc.car.values import PLATFORMS


def _get_car(candidate, pre_create_hook=None):
  detected = (candidate, gen_empty_fingerprint(), "0" * 17, [], structs.CarParams.FingerprintSource.can, True)
  with patch.object(car_helpers, "fingerprint", return_value=detected):
    return car_helpers.get_car(lambda wait_for_one=False: [], lambda _: None, lambda _: None, False, False,
                               pre_create_hook=pre_create_hook)


def test_only_honda_is_supported():
  assert SUPPORTED_BRANDS == frozenset({"honda"})
  assert brand_supported("honda") and not brand_supported("toyota") and not brand_supported("mock")


@pytest.mark.parametrize("candidate", sorted(PLATFORMS))
def test_every_platform_outside_supported_brands_is_dashcam(candidate):
  before = interfaces[candidate].get_non_essential_params(candidate)
  already_dashcam = before.dashcamOnly
  after = limit_to_supported_brands(before)
  if after.brand == "honda":
    assert after.dashcamOnly == already_dashcam
  else:
    assert after.dashcamOnly


@pytest.mark.parametrize("candidate", ["HONDA_CIVIC", "HONDA_CRV_5G", "ACURA_RDX_3G"])
def test_fingerprinted_honda_and_acura_keep_control(candidate):
  assert not _get_car(candidate).CP.dashcamOnly


@pytest.mark.parametrize("candidate", ["TOYOTA_COROLLA_TSS2", "HYUNDAI_SONATA", "CHEVROLET_BOLT_EUV", "FORD_BRONCO_SPORT_MK1",
                                       "SUBARU_OUTBACK", "TESLA_MODEL_Y", "VOLKSWAGEN_GOLF_MK7"])
def test_fingerprinted_other_brand_is_dashcam(candidate):
  assert _get_car(candidate).CP.dashcamOnly


def test_startup_hook_sees_dashcam_and_cannot_lift_it():
  seen = []

  def hook(cp, candidate, fingerprints, car_fw):
    seen.append(cp.dashcamOnly)
    cp.dashcamOnly = False
    return cp
  assert _get_car("TOYOTA_COROLLA_TSS2", pre_create_hook=hook).CP.dashcamOnly
  assert seen == [True]


def test_replay_harness_can_read_other_brands_unchanged():
  detected = ("TOYOTA_COROLLA_TSS2", gen_empty_fingerprint(), "0" * 17, [], structs.CarParams.FingerprintSource.can, True)
  with patch.object(car_helpers, "fingerprint", return_value=detected):
    ci = car_helpers.get_car(lambda wait_for_one=False: [], lambda _: None, lambda _: None, False, False,
                             supported_brands_only=False)
  assert not ci.CP.dashcamOnly
