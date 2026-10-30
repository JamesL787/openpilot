"""honda_override_shield: up from the first temporary EPS fault of a latched Honda override until the driver lets go,
and dropped by every real fault."""
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from openpilot.starpilot.aol.honda_override import honda_override_shield

HONDA = NS(brand="honda")


def cs(**kw):
  base = {'steeringPressed': True, 'steerFaultTemporary': True, 'steerFaultPermanent': False, 'canValid': True,
          'canTimeout': False, 'accFaulted': False}
  return NS(**(base | kw))


@pytest.fixture(autouse=True)
def qualified():
  with patch("opendbc.car.honda.stock_aol.qualified", return_value=True) as q:
    yield q


def test_rises_with_the_fault_and_holds_until_the_driver_lets_go():
  owner = NS()
  assert not honda_override_shield(owner, HONDA, cs(steerFaultTemporary=False), latched=True)   # a press alone
  assert honda_override_shield(owner, HONDA, cs(), latched=True)
  assert honda_override_shield(owner, HONDA, cs(steerFaultTemporary=False), latched=True)   # the fault blips clear
  assert honda_override_shield(owner, HONDA, cs(), latched=True)                            # and rises again
  assert not honda_override_shield(owner, HONDA, cs(steeringPressed=False, steerFaultTemporary=False), latched=True)
  assert not honda_override_shield(owner, HONDA, cs(steerFaultTemporary=False), latched=True)   # a new press: off


def test_needs_the_latch_when_the_fault_rises():
  assert not honda_override_shield(NS(), HONDA, cs(), latched=False)


@pytest.mark.parametrize("bad", [{'steerFaultPermanent': True}, {'canValid': False}, {'canTimeout': True}, {'accFaulted': True}])
def test_drops_on_real_faults(bad):
  owner = NS()
  assert honda_override_shield(owner, HONDA, cs(), latched=True)
  assert not honda_override_shield(owner, HONDA, cs(**bad), latched=True)


def test_honda_and_qualified_only(qualified):
  assert not honda_override_shield(NS(), NS(brand="toyota"), cs(), latched=True)
  qualified.return_value = False
  assert not honda_override_shield(NS(), HONDA, cs(), latched=True)
