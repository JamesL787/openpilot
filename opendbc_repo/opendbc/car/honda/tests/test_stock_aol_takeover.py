"""A hard steering takeover keeps the Honda AOL latch: the driver holding the wheel is a temporary restriction."""
from types import SimpleNamespace

from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.stock_aol import native_observation, temporary_restriction
from opendbc.car.honda.values import CAR


def _cp():
  fingerprint = gen_empty_fingerprint()
  fingerprint[1][0x1A3] = 8
  cp = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, fingerprint, [], False, False, False)
  cp.alternativeExperience = 32
  return cp


def _state(*, pressed=False, temporary=False, gear="drive", permanent=False):
  return structs.CarState(canValid=True, gearShifter=gear, steeringPressed=pressed, steerFaultTemporary=temporary,
                          steerFaultPermanent=permanent).as_reader()


def _native(requested, allowed):
  return SimpleNamespace(requestedLateral=requested, lateralAllowed=allowed)


def test_driver_steering_is_a_temporary_restriction():
  cp = _cp()
  assert temporary_restriction(cp, _state(pressed=True))
  assert temporary_restriction(cp, _state(temporary=True))
  assert not temporary_restriction(cp, _state())
  assert not temporary_restriction(cp, _state(pressed=True, permanent=True))


def test_hard_takeover_sequence_keeps_the_latch():
  # 00000039--a3fe07ccbe 488.6 s: EPS fault while overriding, the fault flickers clear while the driver still steers
  # and openpilot is not re-requesting lateral, then the driver lets go and lateral is requested again
  cp, pending, ms = _cp(), 0, 1_000_000
  for t, state, native in ((10, _state(pressed=True, temporary=True), _native(True, False)),
                           (100, _state(pressed=True, temporary=True), _native(False, False)),
                           (370, _state(pressed=True), _native(False, False)),       # fault clear, still steering
                           (700, _state(pressed=True), _native(False, False))):      # > 200 ms later
    pending, lost, reset = native_observation(native, latched=True, panda_ready=True,
                                              restricted=temporary_restriction(cp, state), now_ns=t * ms,
                                              pending_since_ns=pending, previously_acknowledged=True)
    assert not lost and not reset, t
  # released: the host asks again and the panda grants
  pending, lost, reset = native_observation(_native(True, True), latched=True, panda_ready=True,
                                            restricted=temporary_restriction(cp, _state()), now_ns=750 * ms,
                                            pending_since_ns=pending, previously_acknowledged=True)
  assert not lost and not reset


def test_a_real_grant_loss_after_release_still_resets():
  cp, ms = _cp(), 1_000_000
  pending, _, reset = native_observation(_native(True, False), latched=True, panda_ready=True,
                                         restricted=temporary_restriction(cp, _state()), now_ns=10 * ms, pending_since_ns=0)
  assert not reset
  _, _, reset = native_observation(_native(True, False), latched=True, panda_ready=True,
                                   restricted=temporary_restriction(cp, _state()), now_ns=260 * ms, pending_since_ns=pending)
  assert reset
