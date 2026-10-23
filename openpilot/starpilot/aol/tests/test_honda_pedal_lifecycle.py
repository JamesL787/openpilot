"""Nidec pedal actual acquisition/parser/Card/Controls/native recovery."""
import pytest
from opendbc.car.honda.values import CAR
from openpilot.starpilot.aol.tests.test_honda_recovery_lifecycle import TestHondaCurrentCaller as CurrentCaller
from openpilot.starpilot.aol.tests.honda_native_fixture import honda_native_pair as honda_native_pair

@pytest.mark.usefixtures('honda_native_pair')
class TestHondaPedal(CurrentCaller):
  def test_pedal_0_eps_reverse_recovery(self):
    self.run_current_caller(candidate=CAR.HONDA_CIVIC, word=544, pedal=True)

  def test_pedal_1_eps_reverse_recovery(self):
    self.run_current_caller(candidate=CAR.ACURA_ILX, word=548, pedal=True)

  def test_pedal_2_eps_reverse_recovery(self):
    self.run_current_caller(candidate=CAR.HONDA_ODYSSEY_TWN, word=804, pedal=True)
