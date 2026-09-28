from types import SimpleNamespace

from cereal import messaging
from openpilot.selfdrive.car.card import set_gas_learner_fields

STATE = {"gasFactor": 1.25, "gasFactorRaw": 1.5, "windFactor": 0.9, "windFactorRaw": 0.875, "error": -0.125,
         "learning": True}


def _fpcs():
  return messaging.new_message('starpilotCarState').starpilotCarState


def test_fields_copied():
  fpcs = _fpcs()
  set_gas_learner_fields(fpcs, SimpleNamespace(gas_learner_state=lambda: STATE))
  assert fpcs.gasLearnerAvailable
  assert fpcs.gasLearnerGasFactor == 1.25
  assert fpcs.gasLearnerGasFactorRaw == 1.5
  assert abs(fpcs.gasLearnerWindFactor - 0.9) < 1e-6
  assert fpcs.gasLearnerWindFactorRaw == 0.875
  assert fpcs.gasLearnerError == -0.125
  assert fpcs.gasLearnerLearning


def test_car_without_learner_leaves_defaults():
  for cc in (None, SimpleNamespace(), SimpleNamespace(gas_learner_state=lambda: None)):
    fpcs = _fpcs()
    set_gas_learner_fields(fpcs, cc)
    assert not fpcs.gasLearnerAvailable
    assert fpcs.gasLearnerGasFactor == 0.0


def test_failure_does_not_raise():
  def boom():
    raise RuntimeError("x")
  fpcs = _fpcs()
  set_gas_learner_fields(fpcs, SimpleNamespace(gas_learner_state=boom))
  assert not fpcs.gasLearnerAvailable
