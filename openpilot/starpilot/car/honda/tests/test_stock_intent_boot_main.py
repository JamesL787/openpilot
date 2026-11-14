"""Boot-time main-already-on arming, shaped on route 000000ac--138f4b8bb4 segment 0:
cruiseState.available went True a frame before canValid did, so the stock off->on
edge that normally pulses the auto-main button never happened and AOL stayed
unarmed until a full cruise engage."""
from types import SimpleNamespace

from opendbc.car.structs import car
from openpilot.starpilot.aol.intent import AolSettings, AOL_TOGGLE
from openpilot.starpilot.car.honda.stock_intent import HondaStockCardIntent

CP = SimpleNamespace(carFingerprint='', flags=0, safetyConfigs=[SimpleNamespace(safetyParam=0)])
AUTO_MAIN_SETTINGS = AolSettings(True, 0., 0, 0, (0, 0, 0), (0, 0, 0))
LKAS_TOGGLE_SETTINGS = AolSettings(True, 0., AOL_TOGGLE, 0, (0, 0, 0), (0, 0, 0))


def frame(*, can_valid, available):
  cs = car.CarState(canValid=can_valid, gearShifter='drive')
  cs.cruiseState.available = available
  return cs


def test_main_on_before_can_valid_arms_within_three_healthy_frames():
  intent = HondaStockCardIntent(CP, AUTO_MAIN_SETTINGS)
  # 6.23s: avail=False, canValid=False
  intent.update(frame(can_valid=False, available=False).as_reader(), now_ns=1)
  assert not intent.allowed_latch
  # 6.25s: avail=True, canValid=False (unhealthy -- main_neutral stays reset)
  intent.update(frame(can_valid=False, available=True).as_reader(), now_ns=2)
  assert not intent.allowed_latch
  # 6.26s onward: avail=True, canValid=True, main still on the whole time.
  armed_within = None
  for tick in range(1, 4):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=2 + tick)
    if intent.allowed_latch:
      armed_within = tick
      break
  assert armed_within is not None and armed_within <= 3


def test_lkas_mapped_to_toggle_disables_auto_main_and_never_arms():
  intent = HondaStockCardIntent(CP, LKAS_TOGGLE_SETTINGS)
  intent.update(frame(can_valid=False, available=True).as_reader(), now_ns=1)
  for tick in range(1, 11):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=1 + tick)
    assert not intent.allowed_latch


def test_mid_drive_can_blip_with_main_still_on_does_not_rearm():
  intent = HondaStockCardIntent(CP, AUTO_MAIN_SETTINGS)
  intent.update(frame(can_valid=False, available=False).as_reader(), now_ns=1)
  now = 2
  for _ in range(4):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=now)
    now += 1
    if intent.allowed_latch:
      break
  assert intent.allowed_latch  # armed via the boot path first
  # A brief CAN blip mid-drive clears the latch (cruiseState briefly reads unavailable too).
  intent.update(frame(can_valid=False, available=False).as_reader(), now_ns=now)
  now += 1
  assert not intent.allowed_latch
  # Healthy again with main still on: main_seen is already True, so this is not
  # treated as a fresh boot and the pulse does not refire by itself.
  for _ in range(5):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=now)
    now += 1
    assert not intent.allowed_latch


def test_boot_with_main_off_then_on_still_arms():
  intent = HondaStockCardIntent(CP, AUTO_MAIN_SETTINGS)
  intent.update(frame(can_valid=True, available=False).as_reader(), now_ns=1)
  assert not intent.allowed_latch
  armed = False
  for tick in range(1, 5):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=1 + tick)
    if intent.allowed_latch:
      armed = True
      break
  assert armed


def test_disabled_setting_never_arms():
  settings = AolSettings(False, 0., 0, 0, (0, 0, 0), (0, 0, 0))
  intent = HondaStockCardIntent(CP, settings)
  intent.update(frame(can_valid=False, available=True).as_reader(), now_ns=1)
  for tick in range(1, 11):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=1 + tick)
    assert not intent.allowed_latch


# Main mapped to AOL (James's follow-up on PR #74): auto_main is False, so the boot pulse never fires. The first
# healthy frame with main already on arms the latch directly, under the same guards as the pulse.
MAIN_TOGGLE_SETTINGS = AolSettings(True, 0., 0, AOL_TOGGLE, (0, 0, 0), (0, 0, 0))
BOTH_TOGGLE_SETTINGS = AolSettings(True, 0., AOL_TOGGLE, AOL_TOGGLE, (0, 0, 0), (0, 0, 0))


def test_main_mapped_boot_with_main_on_arms_on_first_healthy_frame():
  intent = HondaStockCardIntent(CP, MAIN_TOGGLE_SETTINGS)
  assert not intent.auto_main
  intent.update(frame(can_valid=False, available=True).as_reader(), now_ns=1)
  assert not intent.allowed_latch
  intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=2)
  assert intent.allowed_latch and not intent.pause_lateral and intent.physical_arm_ns == 2
  for tick in range(3, 8):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=tick)
    assert intent.allowed_latch


def test_main_mapped_boot_with_main_off_does_not_arm():
  intent = HondaStockCardIntent(CP, MAIN_TOGGLE_SETTINGS)
  for tick in range(1, 6):
    intent.update(frame(can_valid=True, available=False).as_reader(), now_ns=tick)
    assert not intent.allowed_latch


def test_main_mapped_boot_does_not_arm_while_standard_cruise_enabled():
  intent = HondaStockCardIntent(CP, MAIN_TOGGLE_SETTINGS)
  intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=1, standard_enabled=True)
  assert not intent.allowed_latch
  # Not a fresh boot any more: the arm does not fire later either.
  intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=2)
  assert not intent.allowed_latch


def test_main_mapped_boot_does_not_arm_with_acc_fault_or_disabled():
  cs = frame(can_valid=True, available=True)
  cs.accFaulted = True
  intent = HondaStockCardIntent(CP, MAIN_TOGGLE_SETTINGS)
  intent.update(cs.as_reader(), now_ns=1)
  assert not intent.allowed_latch
  disabled = HondaStockCardIntent(CP, AolSettings(False, 0., 0, AOL_TOGGLE, (0, 0, 0), (0, 0, 0)))
  disabled.update(frame(can_valid=True, available=True).as_reader(), now_ns=1)
  assert not disabled.allowed_latch


def test_main_mapped_boot_does_not_arm_with_fault_inhibit():
  intent = HondaStockCardIntent(CP, MAIN_TOGGLE_SETTINGS)
  intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=1, fault_active=True)
  assert not intent.allowed_latch


def test_lkas_also_mapped_keeps_boot_unarmed():
  intent = HondaStockCardIntent(CP, BOTH_TOGGLE_SETTINGS)
  for tick in range(1, 6):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=tick)
    assert not intent.allowed_latch


def test_main_mapped_mid_drive_can_blip_does_not_rearm():
  intent = HondaStockCardIntent(CP, MAIN_TOGGLE_SETTINGS)
  intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=1)
  assert intent.allowed_latch
  intent.update(frame(can_valid=False, available=True).as_reader(), now_ns=2)
  assert not intent.allowed_latch
  for tick in range(3, 8):
    intent.update(frame(can_valid=True, available=True).as_reader(), now_ns=tick)
    assert not intent.allowed_latch
