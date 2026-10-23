"""Ford auto-MAIN synthetic pulse must stay within its original input window."""

import pytest
from opendbc.car import structs
from dataclasses import replace
from openpilot.starpilot.aol.intent import AolSettings
from openpilot.starpilot.car.ford.aol import FordCardIntent


def state(*, available, **kwargs):
  return structs.CarState(
    canValid=True, cruiseState=structs.CarState.CruiseState(available=available), gearShifter=structs.CarState.GearShifter.drive, **kwargs
  ).as_reader()


@pytest.mark.parametrize('guard', ('late', 'backwards', 'cancel', 'main-off', 'can', 'permanent', 'acc', 'disabled', 'fault'))
def test_pending_main_cannot_replay_after_stale_or_disarming_input(guard):
  intent = FordCardIntent(
    None, AolSettings(enabled=True, pause_brake_mps=0.0, lkas_action=0, main_action=0, distance_actions=(0, 0, 0), cancel_actions=(0, 0, 0))
  )
  intent.update(state(available=False), now_ns=1_000_000_000, fault_active=False)
  intent.update(state(available=True), now_ns=1_010_000_000, fault_active=False)
  assert not intent.allowed_latch
  kwargs = {}
  available = True
  now = 1_020_000_000
  if guard == 'late':
    now = 1_040_000_001
  elif guard == 'backwards':
    now = 1_009_000_000
  elif guard == 'cancel':
    kwargs['buttonEvents'] = [structs.CarState.ButtonEvent(type=structs.CarState.ButtonEvent.Type.cancel, pressed=True)]
  elif guard == 'main-off':
    available = False
  elif guard == 'can':
    kwargs['canTimeout'] = True
  elif guard == 'permanent':
    kwargs['steerFaultPermanent'] = True
  elif guard == 'acc':
    kwargs['accFaulted'] = True
  elif guard == 'disabled':
    intent.settings = replace(intent.settings, enabled=False)
  intent.update(state(available=available, **kwargs), now_ns=now, fault_active=guard == 'fault')
  assert not intent.allowed_latch
  intent.update(state(available=True), now_ns=max(now, 1_020_000_000) + 10_000_000, fault_active=False)
  # A new actual MAIN rise is separate; stale pending delivery has been consumed.
  if guard != 'main-off':
    assert not intent.allowed_latch


def test_main_pulse_arms_once_after_prior_main_off_feedback_clears():
  intent = FordCardIntent(None, AolSettings(True, 0.0, 0, 0, (0, 0, 0), (0, 0, 0)))
  intent.update(state(available=False), now_ns=1_000_000_000, fault_active=False)
  intent.update(state(available=True), now_ns=1_010_000_000, fault_active=False)
  assert not intent.allowed_latch
  intent.update(state(available=True), now_ns=1_020_000_000, fault_active=False)
  assert intent.allowed_latch
  intent.update(state(available=True), now_ns=1_030_000_000, fault_active=False)
  assert intent.allowed_latch and not intent.main_pulse


@pytest.mark.parametrize('edge_fault', ('host', 'permanent', 'acc', 'disabled'))
def test_fault_at_original_main_edge_cannot_arm_after_fault_clears(edge_fault):
  intent = FordCardIntent(None, AolSettings(True, 0.0, 0, 0, (0, 0, 0), (0, 0, 0)))
  intent.update(state(available=False), now_ns=1_000_000_000, fault_active=False)
  if edge_fault == 'disabled':
    intent.settings = replace(intent.settings, enabled=False)
  cs = state(available=True, steerFaultPermanent=edge_fault == 'permanent', accFaulted=edge_fault == 'acc')
  intent.update(cs, now_ns=1_010_000_000, fault_active=edge_fault == 'host')
  intent.settings = replace(intent.settings, enabled=True)
  intent.update(state(available=True), now_ns=1_020_000_000, fault_active=False)
  assert not intent.allowed_latch
  intent.update(state(available=True), now_ns=1_030_000_000, fault_active=False)
  assert not intent.allowed_latch
