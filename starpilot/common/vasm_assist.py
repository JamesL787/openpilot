"""D-118 V-ASM radar assist: look sooner where it matters, and keep a just-passed car in the blind spot.

Both parts only ever add "occupied"; neither can clear a side the camera reports occupied.
Sides here are car-frame ("left" = driver's left) unless a name says image.
"""
from __future__ import annotations

from dataclasses import dataclass

# Look sooner: the camera alternates sides once a second (2 s per side). With a reason to look,
# check every FOCUS_INTERVAL and give the focused side the turns, but never starve the other side
# for longer than OTHER_SIDE_MAX_GAP.
FOCUS_INTERVAL = 0.3
FOCUS_LEAD_DIST = 15.0      # m: a radar car in the next lane this close to the front bumper
OTHER_SIDE_MAX_GAP = 1.0    # s

# Pass hold: when radar loses a car we were overtaking close beside us, it is still in the blind spot
# until it has slid back past our rear. Its rear is d_rel ahead of our radar; it must then cover its own
# length, ours, and a margin (~4.8 + 4.6 + 2.6 m) at the closing speed.
PASS_CLEAR_M = 12.0
PASS_HOLD_MIN_S = 1.0
PASS_HOLD_MAX_S = 6.0
PASS_MIN_CLOSING = 0.5      # m/s faster than it, else it is not being passed
PASS_HANDOFF_DIST = 15.0    # m: the last sighting must be this close to mean "about to be beside us"
PASS_SIGHTING_MAX_AGE = 0.5  # s: a sighting older than this when radar loses the car proves nothing
SAME_TRACK_JUMP_M = 5.0     # without track ids, a jump this large is a different car

# D-121 semi hold. After the hand-off above, follow the vehicle with the camera and dead-reckon where its rear is
# (it keeps the speed radar last measured; ours comes from carState). Route 324 segs 101/104/108 (three semis on the
# right, replay): the camera stopped seeing the truck when its rear was 29.7-30.4 m behind our radar, and dropped
# out for 0.3-0.4 s on plain trailer sides after the pass hold had already ended. Cars showed 3-10 m of camera travel.
PASS_BRIDGE_S = 0.6         # s: a camera drop-out this short during a handed-off pass is the same vehicle
LONG_VEHICLE_SEEN_M = 12.0  # m of relative travel with the camera on: longer than any car, so a truck or trailer
LONG_VEHICLE_CLEAR_M = 38.0  # m: hold a long vehicle until its rear is this far behind our radar (front ~10 m behind us)
LONG_VEHICLE_MAX_S = 20.0   # s after radar lost it: cap, in case the speeds stop closing the gap

CAR_TO_IMAGE = {"left": "right", "right": "left"}  # the driver camera is mirrored (see VASMDaemon._publish)


@dataclass(frozen=True)
class AdjacentLead:
  status: bool
  d_rel: float
  v_rel: float
  track_id: int = -1


def lead_from_capnp(lead) -> AdjacentLead:
  return AdjacentLead(bool(lead.status), float(lead.dRel), float(lead.vRel), int(lead.radarTrackId))


def pass_hold_seconds(d_rel: float, closing: float) -> float:
  seconds = (max(d_rel, 0.0) + PASS_CLEAR_M) / max(closing, 1e-3)
  return min(max(seconds, PASS_HOLD_MIN_S), PASS_HOLD_MAX_S)


def _same_car(a: AdjacentLead, b: AdjacentLead) -> bool:
  if a.track_id >= 0 or b.track_id >= 0:
    return a.track_id == b.track_id
  return abs(a.d_rel - b.d_rel) < SAME_TRACK_JUMP_M


@dataclass
class _Pass:
  """D-121: one handed-off vehicle, followed after radar lost it."""
  lost_at: float
  hold_until: float     # the plain pass hold above
  v_ego: float | None   # our speed at the last sighting; with v_rel it fixes the vehicle's speed
  v_rel: float
  d_rel: float          # dead-reckoned position of its rear relative to our radar (negative: behind)
  updated_at: float
  seen: bool = False    # the camera has picked it up since radar lost it
  seen_m: float = 0.0   # relative travel while the camera saw it
  camera_off_at: float | None = None  # last camera-on -> off edge; None while on or never seen

  @property
  def long_vehicle(self) -> bool:
    return self.seen_m >= LONG_VEHICLE_SEEN_M

  def advance(self, now: float, v_ego: float | None, camera: bool) -> bool:
    """Move it on to now; True while it still holds the side."""
    dt = max(now - self.updated_at, 0.0)
    self.updated_at = now
    closing = 0.0
    if v_ego is not None and self.v_ego is not None:
      closing = v_ego - (self.v_ego + self.v_rel)
      self.d_rel -= closing * dt
    if camera:
      if self.seen:
        self.seen_m += max(closing, 0.0) * dt
      self.seen = True
      self.camera_off_at = None
    elif self.seen and self.camera_off_at is None:
      self.camera_off_at = now

    if self.long_vehicle:
      return self.d_rel > -LONG_VEHICLE_CLEAR_M and now - self.lost_at < LONG_VEHICLE_MAX_S
    if camera:
      return now - self.lost_at < LONG_VEHICLE_MAX_S
    if self.camera_off_at is not None:
      return now - self.camera_off_at <= PASS_BRIDGE_S
    return now < self.hold_until  # the camera has not picked it up yet


class PassHold:
  """Per side: remember the last close sighting of a car we were passing; hold the side when radar loses it.

  With v_ego and the camera state (D-121) it also follows the vehicle after the hand-off: short camera drop-outs are
  bridged, and a vehicle the camera saw for more than LONG_VEHICLE_SEEN_M is held until it is LONG_VEHICLE_CLEAR_M
  behind. Without them it is the D-118 hold alone.
  """

  def __init__(self):
    self._sighting: dict[str, tuple[AdjacentLead, float, float | None]] = {}
    self._until = {"left": 0.0, "right": 0.0}
    self._pass: dict[str, _Pass] = {}

  def reset(self):
    self._sighting.clear()
    self._until = {"left": 0.0, "right": 0.0}
    self._pass.clear()

  def update(self, side: str, lead: AdjacentLead | None, now: float, v_ego: float | None = None,
             camera: bool = False) -> bool:
    present = lead is not None and lead.status
    sighting = self._sighting.get(side)

    if sighting is not None:
      seen, seen_at, seen_v_ego = sighting
      if not present or not _same_car(seen, lead):
        if now - seen_at <= PASS_SIGHTING_MAX_AGE:
          hold_until = seen_at + pass_hold_seconds(seen.d_rel, -seen.v_rel)
          self._until[side] = max(self._until[side], hold_until)
          if v_ego is not None:
            self._pass[side] = _Pass(seen_at, hold_until, seen_v_ego, seen.v_rel, seen.d_rel, seen_at)
        del self._sighting[side]

    if present and -lead.v_rel >= PASS_MIN_CLOSING and 0.0 <= lead.d_rel <= PASS_HANDOFF_DIST:
      self._sighting[side] = (lead, now, v_ego)
    elif present and side in self._sighting:
      del self._sighting[side]  # same car, but it pulled away or matched our speed: not being passed

    followed = False
    tracked = self._pass.get(side)
    if tracked is not None:
      followed = tracked.advance(now, v_ego, camera)
      if not followed:
        del self._pass[side]

    return now < self._until[side] or followed


def focus_sides(left_blinker: bool, right_blinker: bool, leads: dict[str, AdjacentLead | None],
                prompt_side: str = "") -> set[str]:
  """Car-frame sides worth looking at every FOCUS_INTERVAL."""
  sides = set()
  if left_blinker:
    sides.add("left")
  if right_blinker:
    sides.add("right")
  if prompt_side in ("left", "right"):
    sides.add(prompt_side)
  for side, lead in leads.items():
    if lead is not None and lead.status and lead.d_rel <= FOCUS_LEAD_DIST:
      sides.add(side)
  return sides


def pick_image_side(focus_image: set[str], configured: list[str], current: str,
                    last_at_side: dict[str, float], now: float) -> str:
  """Image side to infer next: the single focused side, except when the other has waited too long."""
  focused = [s for s in configured if s in focus_image]
  if len(focused) != 1:
    return current
  side = focused[0]
  for other in configured:
    if other != side and now - last_at_side.get(other, 0.0) >= OTHER_SIDE_MAX_GAP:
      return other
  return side
