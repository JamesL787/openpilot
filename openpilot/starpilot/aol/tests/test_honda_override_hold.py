"""honda_override_hold: a temporary EPS fault that clears and rises again within one Honda override keeps the intent,
and nothing else does."""
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from openpilot.starpilot.aol.honda_override import OVERRIDE_HOLD_NS, honda_override_hold, honda_override_withdrawal

T0 = 10_000_000_000


def cs(**kw):
  base = {'steeringPressed': True, 'steerFaultTemporary': True, 'steerFaultPermanent': False, 'canValid': True, 'canTimeout': False}
  return NS(**(base | kw))


def axis(t=T0, session="s1", reason="none"):
  return NS(sessionId=session, sourceCarStateMonoTime=t, faultReason=reason)


def tp(**kw):
  return NS(**({'lateral_baseline_ns': 0, 'failed': False, 'paused': False, 'session': "s1"} | kw))


@pytest.fixture(autouse=True)
def qualified():
  with patch("opendbc.car.honda.stock_aol.qualified", return_value=True) as q:
    yield q


HONDA = NS(brand="honda")


def accepted(p, t=T0):
  p.lateral_baseline_ns = 1
  assert honda_override_withdrawal(HONDA, cs(), p, axis(t))
  p.lateral_baseline_ns = 0   # the healthy frames before the regrant drop it


def test_refault_within_one_override_keeps_intent():
  p = tp()
  accepted(p)
  assert honda_override_hold(p, HONDA, cs(), axis(T0 + 60_000_000), latched=True)
  assert honda_override_hold(p, HONDA, cs(), axis(T0 + 1_900_000_000), latched=True)   # each accepted frame renews


def test_no_hold_without_an_accepted_first_rise():
  assert not honda_override_hold(tp(), HONDA, cs(), axis(), latched=True)


@pytest.mark.parametrize("change", [
  {'cs': cs(steeringPressed=False)},
  {'axis': axis(session="s2")},
  {'axis': axis(T0 + OVERRIDE_HOLD_NS + 1)},
])
def test_override_end_releases_the_hold(change):
  p = tp()
  accepted(p)
  assert not honda_override_hold(p, HONDA, change.get("cs", cs()), change.get("axis", axis(T0 + 50_000_000)), latched=True)
  assert p.honda_override_held is None
  assert not honda_override_hold(p, HONDA, cs(), axis(T0 + 100_000_000), latched=True)


@pytest.mark.parametrize("kw", [
  {'latched': False}, {'tp': {'failed': True}}, {'tp': {'paused': True}}, {'tp': {'lateral_baseline_ns': 5}},
  {'cs': {'steerFaultTemporary': False}}, {'cs': {'steerFaultPermanent': True}}, {'cs': {'canValid': False}},
  {'cs': {'canTimeout': True}}, {'axis': {'reason': "canError"}},
])
def test_integrity_checks_still_apply(kw):
  p = tp()
  accepted(p)
  for k, v in kw.get("tp", {}).items():
    setattr(p, k, v)
  a = axis(T0 + 50_000_000, **kw.get("axis", {}))
  assert not honda_override_hold(p, HONDA, cs(**kw.get("cs", {})), a, latched=kw.get("latched", True))


def test_other_brands_and_unqualified_hondas_never_hold(qualified):
  p = tp()
  assert not honda_override_withdrawal(NS(brand="toyota"), cs(), p, axis())
  qualified.return_value = False
  assert not honda_override_withdrawal(HONDA, cs(), p, axis())
  assert getattr(p, "honda_override_held", None) is None
