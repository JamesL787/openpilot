"""Real Ford factory/Card/SelfdriveD/Controls/native combined-owner lifecycle."""
import pytest
from opendbc.car.ford.values import CAR
from openpilot.starpilot.tests.ford_lifecycle_helpers import ford_joined as ford_joined, run_actual_producer

@pytest.fixture(autouse=True)
def combined_angle(monkeypatch, topology):
  monkeypatch.ford_angle = True
  monkeypatch.ford_topology = topology

@pytest.mark.parametrize('identity', [(CAR.FORD_MUSTANG_MACH_E_MK1,18), (CAR.FORD_ESCAPE_MK4,32), (CAR.FORD_F_150_MK14,66)])
@pytest.mark.parametrize('alpha', [False,True])
@pytest.mark.parametrize('hands_free', [False,True])
@pytest.mark.parametrize('topology', ['automatic','manual-multi'])
def test_angle_aol_brake_reverse_fault_and_hands_free(ford_joined,monkeypatch):
  assert ford_joined.host.CI.CC.bp_lat is not None
  run_actual_producer(ford_joined,monkeypatch,scenario='configuration-parity')


@pytest.mark.parametrize('identity', [(CAR.FORD_MUSTANG_MACH_E_MK1,18)])
@pytest.mark.parametrize('alpha', [False,True])
@pytest.mark.parametrize('hands_free', [True])
@pytest.mark.parametrize('topology', ['automatic'])
def test_mache_nonzero_angle_after_brake_with_hands_free(ford_joined,monkeypatch):
  monkeypatch.ford_nonzero = True
  run_actual_producer(ford_joined,monkeypatch,scenario='configuration-parity')


@pytest.mark.parametrize('identity', [(CAR.FORD_MUSTANG_MACH_E_MK1, 18)])
@pytest.mark.parametrize('alpha', [False, True])
@pytest.mark.parametrize('hands_free', [True])
@pytest.mark.parametrize('topology', ['automatic', 'manual-multi'])
def test_tight_turn_speed_window_stays_inside_native_caps(ford_joined, monkeypatch):
  # Route19's first blocked frames exceed Panda's cap by using the latest
  # speed instead of its six-sample minimum. Exercise real parser/native windows.
  monkeypatch.ford_nonzero = True
  monkeypatch.ford_speed_window = True
  monkeypatch.ford_test_curvature = .03
  run_actual_producer(ford_joined, monkeypatch, scenario='configuration-parity')


@pytest.mark.parametrize('identity', [(CAR.FORD_MUSTANG_MACH_E_MK1, 18)])
@pytest.mark.parametrize('alpha', [False, True])
@pytest.mark.parametrize('hands_free', [True])
@pytest.mark.parametrize('topology', ['automatic'])
def test_real_rejected_packet_resynchronizes_without_permission_bypass(ford_joined, monkeypatch):
  from types import SimpleNamespace
  from opendbc.car import structs
  from opendbc.safety.tests.libsafety import libsafety_py

  joined = ford_joined
  native, safety = joined.native, joined.safety
  native.arm()
  adapter = joined.host.CI.CC.bp_lat
  inputs = adapter.host.inputs
  blocked = 0
  monkeypatch.setattr(inputs, 'update', lambda: None)
  monkeypatch.setattr(inputs, 'lateral_snapshot', lambda speed, *, angle=False: None)
  # Isolate the adapter recovery while preserving actual physical native authority.
  # The full caller matrix above retains real wire/inventory/freshness qualification.
  monkeypatch.setattr(inputs, 'native_permission', lambda cp, max_age_ns: bool(safety.aol_get_permission_mask() & 1))
  CC = structs.CarControl(enabled=True, latActive=True)
  CC.actuators.curvature = .0001
  state = structs.CarState(canValid=True, vEgoRaw=15., gearShifter=structs.CarState.GearShifter.drive)
  state.cruiseState.available = True
  CS = SimpleNamespace(out=state, lat_ctl_lim_stat=0)
  rejected = recovered = False
  neutral_after_rejection = False
  for frame in range(180):
    native.pump(1, mask=1, speed=15.)
    now = (1_000_000 + native.tick * 10_000) * 1000
    from openpilot.cereal import messaging
    panda = messaging.new_message('pandaStates', 1, valid=True, logMonoTime=now)
    panda.pandaStates[0].safetyTxBlocked = blocked
    inputs.sm.update_msgs(now / 1e9, [panda.as_reader()])
    packets = []
    if frame % 5 == 0:
      packets += adapter.step_lateral(CC, CS, native.packer, joined.host.CI.CC.CAN, frame, now)
    if frame % 3 == 0:
      packets += adapter.step_lka(native.packer, joined.host.CI.CC.CAN, now)
    for address, original, bus in packets:
      data = bytearray(original)
      active = address == 0x3D6 and (data[0] >> 4) & 7 == 1
      if active and frame >= 80 and not rejected:
        data[1] ^= 1  # One actual bad checksum; native must reject it.
        assert not safety.safety_tx_hook(libsafety_py.make_CANPacket(address, bus, data))
        blocked += 1
        rejected = True
        continue
      accepted = safety.safety_tx_hook(libsafety_py.make_CANPacket(address, bus, data))
      assert accepted, (frame, hex(address), data.hex())
      if rejected and address == 0x3D6:
        neutral_after_rejection |= not active
        recovered |= active and neutral_after_rejection
  assert rejected and neutral_after_rejection and recovered
  # Host recovery never replaces native authorization.
  safety.aol_set_host_request(0)
  native.pump(5, mask=0, speed=15.)
  now = (1_000_000 + native.tick * 10_000) * 1000
  neutral = adapter.step_lateral(CC, CS, native.packer, joined.host.CI.CC.CAN, 180, now)[0]
  assert (neutral[1][0] >> 4) & 7 == 0


@pytest.mark.parametrize('identity', [(CAR.FORD_MUSTANG_MACH_E_MK1, 18), (CAR.FORD_ESCAPE_MK4, 32), (CAR.FORD_F_150_MK14, 66)])
@pytest.mark.parametrize('alpha', [True])
@pytest.mark.parametrize('hands_free', [True])
@pytest.mark.parametrize('topology', ['automatic', 'manual-multi'])
def test_native_first_pedal_preserves_only_granted_lateral(ford_joined, monkeypatch):
  monkeypatch.ford_nonzero = True
  monkeypatch.ford_native_first_pedal = True
  run_actual_producer(ford_joined, monkeypatch, scenario='configuration-parity')


@pytest.mark.parametrize('identity', [(CAR.FORD_MUSTANG_MACH_E_MK1, 18)])
@pytest.mark.parametrize('alpha', [True])
@pytest.mark.parametrize('hands_free', [True])
@pytest.mark.parametrize('topology', ['automatic', 'manual-multi'])
def test_early_pedal_admission_requires_exact_marked_angle_long_profile(ford_joined):
  from opendbc.car import structs
  from openpilot.starpilot.car.ford.aol import early_native_long_withdrawal_supported
  cp = ford_joined.host.CP
  assert early_native_long_withdrawal_supported(cp)
  for field, value in (('alternativeExperience', 0), ('openpilotLongitudinalControl', False),
                       ('passive', True), ('dashcamOnly', True), ('brand', 'hyundai')):
    changed = structs.CarParams(**cp.to_dict())
    setattr(changed, field, value)
    assert not early_native_long_withdrawal_supported(changed)
  for mask in (128, 1, 16):
    changed = structs.CarParams(**cp.to_dict())
    changed.safetyConfigs[-1].safetyParam ^= mask
    assert not early_native_long_withdrawal_supported(changed)


@pytest.mark.parametrize('identity', [(CAR.FORD_MUSTANG_MACH_E_MK1, 18), (CAR.FORD_ESCAPE_MK4, 32), (CAR.FORD_F_150_MK14, 66)])
@pytest.mark.parametrize('alpha', [False, True])
@pytest.mark.parametrize('hands_free', [False, True])
@pytest.mark.parametrize('topology', ['automatic', 'manual-multi'])
def test_temporary_eps_recovery_with_gas_preserves_only_lateral_intent(ford_joined, monkeypatch):
  # Route3b: cruise is off, gas remains pressed through a 150 ms EPS pulse.
  # The actual native hook must still reject active output during that pulse.
  monkeypatch.ford_nonzero = True
  monkeypatch.ford_eps_gas = True
  run_actual_producer(ford_joined, monkeypatch, scenario='configuration-parity')
