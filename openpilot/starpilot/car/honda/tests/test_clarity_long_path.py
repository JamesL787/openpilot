"""The Nidec interceptor Clarity's longitudinal path is untouched by the Bosch-A / Civic Bosch work (Trung's Honda set).

The shared piece is BoschLearningParams, which also loads the interceptor learner's factors. Its new one-time reset
keys off `learner_version`, which only the Civic Bosch learner sets. These tests pin the Clarity's behaviour to the
pre-merge code (8226ca24c6), reproduced below as `reference_factors`.
"""

import math
import os
import tempfile

import pytest

from opendbc.car import gen_empty_fingerprint
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.nidec_interceptor import CLARITY_GAS_MULT_V, NidecInterceptor
from opendbc.car.honda.values import CAR
from openpilot.common.params import Params
from openpilot.starpilot.car.honda.longitudinal import BoschLearningParams
from openpilot.starpilot.longitudinal.bosch_a_smooth import BoschASmooth
from openpilot.starpilot.longitudinal.bosch_a_toggles import HUMAN_FOLLOWING_KEY, STOCK_BRAKE_FEEL_KEY, vehicle_supported
from openpilot.starpilot.longitudinal import human_following
from openpilot.starpilot.longitudinal.honda_bosch_a_long import HondaBoschALongEnhancement, active_for
from openpilot.starpilot.ui.feature_settings_owner import FeatureSettingsOwner


def clarity_cp():
  fp = gen_empty_fingerprint()
  fp[0][0x201] = 6  # the interceptor's pedal sensor
  return CarInterface.get_params(CAR.HONDA_CLARITY, fp, [], False, False, False)


class FakeParams:
  def __init__(self, gas, wind):
    self.values = {"HondaGasFactorParams": gas, "HondaWindFactorParams": wind}
    self.puts = []

  def get(self, key, return_default=False):
    return self.values[key]

  def put(self, key, value):
    self.puts.append((key, value))
    self.values[key] = value


def reference_factors(params):
  # BoschLearningParams.__init__ at 8226ca24c6, which had no learner_version check
  factors = []
  for key in ("HondaGasFactorParams", "HondaWindFactorParams"):
    try:
      value = float(params.get(key, return_default=True))
      if not math.isfinite(value):
        value = 1.0
    except (TypeError, ValueError, OverflowError, RuntimeError):
      value = 1.0
    factors.append(value)
  return factors


def test_the_clarity_builds_the_interceptor_with_no_learner_and_no_bosch_path():
  ci = CarInterface(clarity_cp())
  interceptor = ci.CC.nidec_interceptor
  assert isinstance(interceptor, NidecInterceptor)
  assert not interceptor.learn and not hasattr(interceptor, "learner_version")
  assert interceptor.gas_mult_v == CLARITY_GAS_MULT_V == [1.0, 1.0]
  assert (interceptor.bosch_gas_factor, interceptor.bosch_wind_factor) == (1.0, 1.0)
  assert ci.CC.bosch_longitudinal is None and ci.CC.interceptor_learning_params is None


@pytest.mark.parametrize("learn", (False, True))
@pytest.mark.parametrize("gas, wind", ((1.0, 1.0), (1.37, 2.4), (0.05, 6.0), (float("nan"), 1.2), ("bad", None)))
def test_interceptor_factors_match_the_pre_merge_loader_and_never_reset(learn, gas, wind):
  with tempfile.TemporaryDirectory() as root:
    meta = os.path.join(root, "learner.json")
    params, reference_params = FakeParams(gas, wind), FakeParams(gas, wind)
    owner, reference = NidecInterceptor(clarity_cp(), learn=learn), NidecInterceptor(clarity_cp(), learn=learn)
    loaded = BoschLearningParams(params, owner, meta_path=meta)
    reference.set_factors(*reference_factors(reference_params))
    assert (owner.bosch_gas_factor, owner.bosch_wind_factor) == (reference.bosch_gas_factor, reference.bosch_wind_factor)
    assert loaded.saved == (reference.bosch_gas_factor, reference.bosch_wind_factor)
    assert params.puts == [] and params.values == reference_params.values  # the saved factors are not rewritten
    assert not os.path.exists(meta) and not os.path.exists(meta + ".tmp")  # the one-time reset never ran


def test_interceptor_persist_writes_the_same_as_before():
  params = FakeParams(1.2, 1.5)
  owner = NidecInterceptor(clarity_cp(), learn=True)
  with tempfile.TemporaryDirectory() as root:
    loaded = BoschLearningParams(params, owner, meta_path=os.path.join(root, "learner.json"))
  owner.bosch_gas_factor, owner.bosch_wind_factor = 1.3, 1.6
  loaded.persist(5999)
  assert params.puts == []
  loaded.persist(6000)
  assert params.puts == [("HondaGasFactorParams", 1.3), ("HondaWindFactorParams", 1.6)]


def test_no_bosch_a_piece_runs_on_the_clarity():
  cp = clarity_cp()
  assert not vehicle_supported(cp) and not active_for(cp)
  assert not human_following.enabled_for(cp, True)
  assert not BoschASmooth(cp, 0.05).enabled
  assert not HondaBoschALongEnhancement(cp, 0.05, stock_brake_feel=True).enabled


def bosch_a_rows(cp, saved=None):
  with tempfile.TemporaryDirectory() as root:
    params = Params(root)
    for key, value in (saved or {}).items():
      params.put_bool(key, value, block=True)
    owner = FeatureSettingsOwner(params, lambda group: group == "preferences", vehicle_fingerprint=lambda: str(cp.carFingerprint),
                                 vehicle_params=lambda: cp)
    state = owner.snapshot("profiles", parked=True, system_long=True, lateral_context=False, metric=False)
    return {row.key: row for row in state.rows if row.key in (STOCK_BRAKE_FEEL_KEY, HUMAN_FOLLOWING_KEY)}


def test_the_bosch_a_toggles_are_hidden_on_the_clarity():
  assert bosch_a_rows(clarity_cp()) == {}


def test_a_bosch_a_toggle_left_on_still_shows_so_it_can_be_turned_off():
  rows = bosch_a_rows(clarity_cp(), {STOCK_BRAKE_FEEL_KEY: True})
  assert set(rows) == {STOCK_BRAKE_FEEL_KEY} and rows[STOCK_BRAKE_FEEL_KEY].available


def test_the_bosch_a_toggles_show_on_a_verified_bosch_a_civic():
  cp = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), [], True, False, False)
  if not vehicle_supported(cp):
    pytest.skip("this Civic Bosch build has no openpilot longitudinal")
  assert set(bosch_a_rows(cp)) == {STOCK_BRAKE_FEEL_KEY, HUMAN_FOLLOWING_KEY}
