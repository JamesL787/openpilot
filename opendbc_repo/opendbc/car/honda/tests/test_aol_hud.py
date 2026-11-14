"""Root-run real factory/controller/codec lane HUD regression; controlled CarState."""
import pytest

from opendbc.can import CANParser
from opendbc.car import Bus, gen_empty_fingerprint, structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR, DBC, HondaFlags


@pytest.mark.parametrize("identity", (CAR.HONDA_CIVIC, CAR.HONDA_ACCORD, CAR.HONDA_CIVIC_2022, CAR.ACURA_RDX_3G_MMR))
@pytest.mark.parametrize("active", (False, True))
@pytest.mark.parametrize("visible", (False, True))
@pytest.mark.parametrize("available", (False, True))
def test_actual_controller_preserves_intentional_lane_hud(identity, active, visible, available):
  cp = CarInterface.get_params(identity, gen_empty_fingerprint(), [], True, False, False)
  assert cp.openpilotLongitudinalControl
  ci = CarInterface(cp)
  ci.update([])
  state = structs.CarState(vEgo=30.0)
  state.cruiseState.available = available
  ci.CS.out = state
  cc = structs.CarControl(enabled=active, latActive=active)
  cc.hudControl.lanesVisible = visible
  _, frames = ci.apply(cc.as_reader(), 10_000_000_000)
  decoder = CANParser(DBC[identity][Bus.pt], [("LKAS_HUD", 10)], ci.CC.CAN.lkas)
  assert decoder.update([(10_000_000_000, frames)])
  encoded = decoder.vl["LKAS_HUD"]
  if cp.flags & HondaFlags.BOSCH_ALT_RADAR:
    assert bool(encoded["SOLID_LANES"]) == active
    assert bool(encoded["DASHED_LANES"]) == available
  elif cp.flags & HondaFlags.BOSCH and not cp.flags & HondaFlags.BOSCH_RADARLESS:
    assert bool(encoded["SOLID_LANES"]) == (active and available)
    assert bool(encoded["DASHED_LANES"]) == (active and available)
  else:
    assert bool(encoded["SOLID_LANES"]) == (visible or active)
    if cp.flags & HondaFlags.BOSCH_RADARLESS:
      assert bool(encoded["DASHED_LANES"]) == (visible or active)


@pytest.mark.parametrize("identity", (CAR.ACURA_RDX_3G_MMR, CAR.HONDA_ODYSSEY_5G_MMR,
                                     CAR.ACURA_TLX_2G, CAR.ACURA_MDX_4G))
@pytest.mark.parametrize("available", (False, True))
def test_alt_radar_enabled_longitudinal_with_lateral_inactive_keeps_upstream_hud(identity, available):
  cp = CarInterface.get_params(identity, gen_empty_fingerprint(), [], True, False, False)
  assert cp.openpilotLongitudinalControl
  assert cp.flags & HondaFlags.BOSCH_ALT_RADAR
  ci = CarInterface(cp)
  ci.update([])
  state = structs.CarState(vEgo=30.0)
  state.cruiseState.available = available
  ci.CS.out = state
  cc = structs.CarControl(enabled=True, longActive=True, latActive=False)
  cc.hudControl.lanesVisible = True  # Actual Controls.publish uses enabled.
  _, frames = ci.apply(cc.as_reader(), 10_000_000_000)
  decoder = CANParser(DBC[identity][Bus.pt], [("LKAS_HUD", 10)], ci.CC.CAN.lkas)
  assert decoder.update([(10_000_000_000, frames)])
  encoded = decoder.vl["LKAS_HUD"]
  assert not encoded["SOLID_LANES"], "ALT_RADAR_LAT_INACTIVE_MUST_NOT_SHOW_SOLID_LANES"
  assert bool(encoded["DASHED_LANES"]) == available


@pytest.mark.parametrize("pressed_frames, released_frames, solid", (
  (10, 0, True),      # a nudge mid-lane keeps the lanes filled
  (60, 0, False),     # turning the wheel shows outline lanes like stock
  (60, 50, False),    # still outlined just after letting go
  (60, 120, True),    # filled again once openpilot has steered for a second
))
def test_civic_bosch_outlines_lanes_while_driver_turns(pressed_frames, released_frames, solid):
  cp = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), [], True, False, False)
  ci = CarInterface(cp)
  ci.update([])
  cc = structs.CarControl(enabled=True, latActive=True)
  cc.hudControl.lanesVisible = True
  frames, now = [], 10_000_000_000
  for pressed in [True] * pressed_frames + [False] * released_frames:
    state = structs.CarState(vEgo=30.0, steeringPressed=pressed)
    state.cruiseState.available = True
    ci.CS.out = state
    now += 10_000_000
    _, frames = ci.apply(cc.as_reader(), now)
  # land on a 10 Hz HUD frame with the last state
  while not any(address == 0x33d for address, _, _ in frames):
    now += 10_000_000
    _, frames = ci.apply(cc.as_reader(), now)
  decoder = CANParser(DBC[cp.carFingerprint][Bus.pt], [("LKAS_HUD", 10)], ci.CC.CAN.lkas)
  assert decoder.update([(now, frames)])
  assert bool(decoder.vl["LKAS_HUD"]["SOLID_LANES"]) == solid
  assert decoder.vl["LKAS_HUD"]["DASHED_LANES"]


@pytest.mark.parametrize("v_ego, enabled, lat_active, solid, dashed", (
  (30.0, False, False, False, False),  # main on, openpilot off: no lanes
  (30.0, True, True, True, True),      # steering: filled
  (30.0, True, False, False, True),    # engaged, not steering: outline
  (30.0, False, True, True, True),     # AOL steering with longitudinal off: filled
  (0.0, True, True, False, True),      # stopped and engaged: outline
  (0.0, True, False, False, True),     # stopped, engaged, lateral idle: outline
  (0.0, False, False, False, False),   # stopped, openpilot off: no lanes
))
def test_civic_bosch_outline_only_while_engaged(v_ego, enabled, lat_active, solid, dashed):
  cp = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, gen_empty_fingerprint(), [], True, False, False)
  ci = CarInterface(cp)
  ci.update([])
  state = structs.CarState(vEgo=v_ego)
  state.cruiseState.available = True
  ci.CS.out = state
  cc = structs.CarControl(enabled=enabled, latActive=lat_active)
  cc.hudControl.lanesVisible = True
  _, frames = ci.apply(cc.as_reader(), 10_000_000_000)
  decoder = CANParser(DBC[cp.carFingerprint][Bus.pt], [("LKAS_HUD", 10)], ci.CC.CAN.lkas)
  assert decoder.update([(10_000_000_000, frames)])
  assert bool(decoder.vl["LKAS_HUD"]["SOLID_LANES"]) == solid
  assert bool(decoder.vl["LKAS_HUD"]["DASHED_LANES"]) == dashed
