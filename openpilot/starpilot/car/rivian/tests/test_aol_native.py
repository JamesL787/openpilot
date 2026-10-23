"""Native permission tests: physical DBC RX grants, never controls_allowed setters."""

import pytest
from opendbc.car import structs
from opendbc.car.rivian.tests.test_base_driving import ControllerRig
from opendbc.safety.tests.libsafety import libsafety_py


class NativeRig:
  def __init__(self, *, alpha=False, alternative=32):
    self.car = ControllerRig(alpha=alpha)
    self.native = libsafety_py.libsafety
    self.native.init_tests()
    self.native.set_alternative_experience(alternative)
    assert self.native.set_safety_hooks(structs.CarParams.SafetyModel.rivian, int(alpha)) == 0
    self.native.set_aol_test_heartbeat(True)
    self.tick = 0
    for _ in range(3):
      self.feed(feature=0)

  def feed(self, *, request=1, **kwargs):
    self.tick += 1
    self.native.set_timer(1_000_000 + self.tick * 10_000)
    self.car.feed(**kwargs)
    for address, data, bus in self.car.last_frames:
      assert self.native.safety_rx_hook(libsafety_py.make_CANPacket(address, bus, data))
    self.native.safety_tick()
    self.native.aol_set_host_request(request)
    return self.native.aol_get_permission_mask()

  def engage(self):
    assert self.feed(feature=1) == 0  # grant and request same instant cannot join
    assert self.feed(feature=1) == 1
    assert self.native.get_controls_allowed()


@pytest.mark.parametrize('alpha', [False, True])
def test_native_real_engagement_brake_reverse_and_recovery(alpha):
  rig = NativeRig(alpha=alpha)
  assert rig.native.safety_config_valid()
  assert rig.native.aol_get_permission_mask() == 0  # Standby is not a grant.
  rig.engage()
  assert rig.feed(feature=1, request=3) == (3 if alpha else 1)
  assert rig.feed(brake=True, feature=0) == 1
  assert not rig.native.get_controls_allowed()
  assert rig.feed(gear=2, feature=0) == 0
  assert rig.feed(gear=4, feature=0) == 1
  assert rig.feed(fault=True, feature=0) == 0
  assert rig.feed(feature=0) == 1
  assert rig.feed(unavailable=True, feature=0) == 0
  assert rig.feed(feature=0) == 1
  assert rig.feed(feature=0, request=0) == 0
  assert rig.feed(feature=0, request=1) == 1
  rig.native.set_aol_test_heartbeat(False)
  assert rig.native.aol_get_permission_mask() == 0
  rig.native.set_aol_test_heartbeat(True)
  assert rig.feed(feature=0, request=1) == 0
  rig.engage()


@pytest.mark.parametrize('cause', ['request_lease', 'heartbeat', 'corrupt', 'park', 'faulted_acm'])
def test_native_source_or_session_loss_needs_new_engagement(cause):
  rig = NativeRig()
  rig.engage()
  if cause == 'request_lease':
    rig.native.set_timer(1_000_000 + rig.tick * 10_000 + 200_001)
    assert rig.native.aol_get_permission_mask() == 0
    rig.tick += 21  # next source remains later than the expired observation
  elif cause == 'heartbeat':
    rig.native.set_aol_test_heartbeat(False)
    assert rig.native.aol_get_permission_mask() == 0
    rig.native.set_aol_test_heartbeat(True)
  elif cause == 'corrupt':
    address, data, bus = next(m for m in rig.car.last_frames if m[0] == 0x380)
    data = bytes([data[0] ^ 0x80]) + data[1:]
    assert not rig.native.safety_rx_hook(libsafety_py.make_CANPacket(address, bus, data))
    assert rig.native.aol_get_permission_mask() == 0
  elif cause == 'park':
    assert rig.feed(gear=1, feature=0) == 0
  else:
    assert rig.feed(feature=4) == 0
  assert rig.feed(feature=0) == 0
  rig.engage()


def test_native_zero_alternative_does_not_retain_lateral_after_brake():
  rig = NativeRig(alternative=0)
  rig.feed(feature=1)
  assert rig.native.get_controls_allowed()
  rig.feed(feature=0, brake=True)
  assert not rig.native.get_controls_allowed()
  assert not rig.native.lateral_controls_allowed()


def test_native_long_axis_not_inherited_from_lateral_token():
  rig = NativeRig(alpha=True)
  rig.engage()
  rig.feed(feature=0, brake=True)
  assert rig.feed(request=3, feature=0) == 1
  address, data, bus = rig.car.packer.make_can_msg('ACM_longitudinalRequest', 0, {'ACM_AccelerationRequest': 0.1})
  assert not rig.native.safety_tx_hook(libsafety_py.make_CANPacket(address, bus, data))
