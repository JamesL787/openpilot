#!/usr/bin/env python3
import math
from collections import deque
from dataclasses import dataclass, field

from opendbc.can import CANParser
from opendbc.car import Bus, structs
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.values import DBC
from opendbc.car.interfaces import RadarInterfaceBase


def _create_nidec_can_parser(car_fingerprint):
  radar_messages = [0x400] + list(range(0x430, 0x43A)) + list(range(0x440, 0x446))
  messages = [(m, 20) for m in radar_messages]
  return CANParser(DBC[car_fingerprint][Bus.radar], messages, 1)


# ============================================================================
# Honda Bosch-A 16-slot object bank
# ============================================================================
# 16 CAN-visible object slots. Each slot has 4 main frames (f0..f3, one CAN ID each -- NOT sub-frames
# muxed onto a shared ID) plus one synchronized auxiliary 5th frame. This supersedes any prior model of
# 0x280/0x284/0x288/0x28C as pieces of one object, or of 0x2C8/0x2C9 as a separate "coarse" list: it is
# ONE 16-slot bank with one auxiliary frame per slot. See honda_bosch_a_radar.dbc for the bit geometry.
BOSCH_A_DBC_NAME = 'honda_bosch_a_radar'
BOSCH_A_NUM_SLOTS = 16


def _bosch_a_main_base(slot: int) -> int:
  return 0x280 + 4 * slot if slot < 4 else 0x2D0 + 4 * (slot - 4)


def _bosch_a_aux_id(slot: int) -> int:
  return 0x2C8 + slot if slot < 8 else 0x290 + (slot - 8)


BOSCH_A_MAIN_IDS = [[_bosch_a_main_base(s) + i for i in range(4)] for s in range(BOSCH_A_NUM_SLOTS)]
BOSCH_A_AUX_IDS = [_bosch_a_aux_id(s) for s in range(BOSCH_A_NUM_SLOTS)]
BOSCH_A_ALL_IDS = [addr for ids in BOSCH_A_MAIN_IDS for addr in ids] + BOSCH_A_AUX_IDS

# Publish RadarPoints when the last MAIN object frame arrives. Passive captures prove that slot 15's
# companion frame, 0x297, follows 0x2FF and is the final observed object-family frame in a full sweep:
#
#   ... 0x2FC, 0x2FD, 0x2FE, 0x2FF, 0x297
#
# Keep 0x2FF as the RadarPoint trigger while the companion data remains optional/debug-only. Making
# 0x297 the sole trigger would allow one dropped auxiliary frame to suppress an otherwise-valid point
# update, contrary to the parser's "aux never gates validity" contract.
BOSCH_A_TRIGGER_MSG = BOSCH_A_MAIN_IDS[BOSCH_A_NUM_SLOTS - 1][3]
BOSCH_A_SWEEP_END_MSG = BOSCH_A_AUX_IDS[BOSCH_A_NUM_SLOTS - 1]  # 0x297

# Observed coherent Bosch-A sweep cadence is ~14.5-16 Hz in the available captures.
BOSCH_A_FREQ_HZ = 15

# Range: f0 raw_range (12-bit, B2:B3 high nibble) -> meters. Firmware q16 = 8*raw_range; physical
# calibration keeps slope/offset as named, replay-refinable constants (do not add a second radar/camera
# longitudinal offset on top of this).
BOSCH_A_RANGE_SCALE_M = 0.05712
BOSCH_A_RANGE_OFFSET_M = -3.0

# Azimuth: f0 raw_angle (11-bit, B4:B5 high 3 bits), offset-binary about 1024.
#
# The f3 angular-edge pair independently closes the exact center-angle scale:
#   azimuth_rad = (raw_angle - 1024) / 2048
#
# This supersedes the older empirical 0.032 deg/count fit.
BOSCH_A_AZIMUTH_SCALE_RAD = 1.0 / 2048.0
BOSCH_A_AZIMUTH_CENTER = 1024

# Invalid sentinels (section 3/4/5/6 of the spec).
BOSCH_A_STATUS_INVALID = 0xF
BOSCH_A_RANGE_RAW_INVALID = 0xFFF
BOSCH_A_ANGLE_RAW_INVALID = 0x7FF
BOSCH_A_LIFE_INVALID = 0xFFF
BOSCH_A_TRACK_ID_MIN = 1
BOSCH_A_TRACK_ID_MAX = 0x3F
# AUX logical 0x00CA has an explicit 0x3FF invalid sentinel. Firmware proves the normalization below;
# captures strongly support interpreting the active value as previous/current range ratio.
BOSCH_A_RANGE_RATIO_INVALID = 0x3FF
BOSCH_A_LOGICAL_00CA_INVALID = BOSCH_A_RANGE_RATIO_INVALID  # compatibility/debug alias
BOSCH_A_RANGE_RATIO_SCALE = 0.001
BOSCH_A_RANGE_RATIO_OFFSET = 0.5

# The synchronized AUX frame contains an 11-bit offset-binary velocity-like field and a 10-bit
# companion quality/uncertainty field.  The byte locations are now decoded in the DBC.  The exact
# Bosch descriptor name is still being verified, so keep the conversion constants isolated here.
# Capture validation shows active values in [0, 1728], with 0x7FE used as the inactive sentinel.
BOSCH_A_DIRECT_VREL_INVALID = 0x7FE
BOSCH_A_DIRECT_VREL_MIN_RAW = 0
BOSCH_A_DIRECT_VREL_MAX_RAW = 1728
BOSCH_A_DIRECT_VREL_CENTER_RAW = 864
BOSCH_A_DIRECT_VREL_SCALE_MPS = 1.0 / 64.0
# Empirical raw-quality policy: active captures with u10 <= 255 are the only band where the
# velocity-like candidate is consistently useful.  This is deliberately not presented as a Bosch
# physical unit or descriptor constant; it keeps saturated/high-uncertainty AUX values from becoming
# authoritative velocity measurements.
BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW = 255

# Measurement-authority policy. These are replay-derived safety/tuning gates, not recovered Bosch
# constants. Range innovation is measured from the previous accepted observation so a reset cannot
# become the baseline for following sweeps.
BOSCH_A_RANGE_SIGMA_DEGRADED_RAW = 4
BOSCH_A_RANGE_INNOVATION_MAX_M = 2.0
BOSCH_A_RANGE_INNOVATION_HARD_MAX_M = 5.0
BOSCH_A_FALLBACK_RANGE_RATE_MAX_MPS = 50.0
BOSCH_A_USE_TAN_LATERAL_PROJECTION = True

# Accepted-range history is retained for continuity and the adjacent two-point fallback. Rejected
# range resets never enter it, and it is not used for a multi-sample OLS velocity fit.
BOSCH_A_VREL_MAX_SAMPLES = 8

# Staleness gate -- TUNING constant, reused plumbing pattern (not a firmware fact). At the observed
# ~15 Hz cadence, 0.20 s is approximately three missed sweeps.
BOSCH_A_STALE_S = 0.20


@dataclass
class _BoschASlotState:
  last_seen_nanos: int | None = None

  # Firmware logical-ID companion data -- telemetry/debug only for now, never a RadarPoint validity
  # gate. 0x00C9 has a firmware transform but no proven physical meaning; 0x00CA has an explicit
  # invalid sentinel and its physical meaning remains unresolved.
  logical_00c9_raw: float = float('nan')
  logical_00ca_raw: float = float('nan')
  direct_vrel_raw: int | None = None
  direct_vrel_uncertainty_raw: int | None = None

  def reset(self):
    self.last_seen_nanos = None
    self.logical_00c9_raw = float('nan')
    self.logical_00ca_raw = float('nan')
    self.direct_vrel_raw = None
    self.direct_vrel_uncertainty_raw = None


@dataclass
class _BoschATrackState:
  """Persistent state for one Bosch CAN object identity, independent of wire slot."""
  track_id: int
  prev_frame_idx: int | None = None
  prev_life: int | None = None
  last_seen_nanos: int | None = None
  wire_slot: int | None = None
  samples: deque = field(default_factory=lambda: deque(maxlen=BOSCH_A_VREL_MAX_SAMPLES))


def _bosch_a_direct_vrel(raw_value: int | float | None,
                         uncertainty_raw: int | float | None = None) -> float | None:
  """Decode the capture-validated AUX relative-velocity candidate.

  None means that AUX was absent/invalid and the caller should use the OLS fallback.  The [0, 1728]
  active domain is deliberately enforced here because values above the observed +13.5 m/s rail have
  not appeared on active objects; 0x7FE is the observed inactive sentinel.
  """
  if raw_value is None:
    return None
  raw = int(raw_value)
  if raw == BOSCH_A_DIRECT_VREL_INVALID:
    return None
  if not BOSCH_A_DIRECT_VREL_MIN_RAW <= raw <= BOSCH_A_DIRECT_VREL_MAX_RAW:
    return None
  # u10 is retained as a raw quality indicator because its physical units remain unresolved.  The
  # conservative threshold is evidence-backed tuning, not a recovered firmware validity rule.
  if uncertainty_raw is not None and int(uncertainty_raw) > BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW:
    return None
  return (raw - BOSCH_A_DIRECT_VREL_CENTER_RAW) * BOSCH_A_DIRECT_VREL_SCALE_MPS


def _bosch_a_range_ratio(raw_value: int | float | None) -> float | None:
  if raw_value is None:
    return None
  raw = int(raw_value)
  if raw == BOSCH_A_RANGE_RATIO_INVALID or not 0 <= raw < BOSCH_A_RANGE_RATIO_INVALID:
    return None
  return BOSCH_A_RANGE_RATIO_OFFSET + BOSCH_A_RANGE_RATIO_SCALE * raw


def _bosch_a_range_ratio_vrel(raw_value: int | float | None, d_rel: float, dt: float) -> float | None:
  """Return the range rate implied by the empirical previous/current range ratio."""
  ratio = _bosch_a_range_ratio(raw_value)
  if ratio is None or dt <= 0.0 or not math.isfinite(d_rel):
    return None
  return d_rel * (1.0 - ratio) / dt


def _bosch_a_measurement_degraded(range_sigma_raw: int, existence_raw: int,
                                  direct_vrel_uncertainty_raw: int | None) -> bool:
  range_quality_bad = range_sigma_raw >= BOSCH_A_RANGE_SIGMA_DEGRADED_RAW or existence_raw in (0, 0x7F)
  velocity_quality_bad = (direct_vrel_uncertainty_raw is not None and
                          direct_vrel_uncertainty_raw > BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW)
  return range_quality_bad or velocity_quality_bad


def _create_bosch_a_can_parser(CP):
  messages = [(addr, BOSCH_A_FREQ_HZ) for addr in BOSCH_A_ALL_IDS]
  # Bus.radar selects the Bosch-A DBC; the object/fusion feed itself is
  # physically on the camera-side ACC-CAN.
  return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, CanBus(CP).camera)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.radar_off_can = CP.radarUnavailable
    self.bosch_a_radar = (not self.radar_off_can and Bus.radar in DBC[CP.carFingerprint] and
                           DBC[CP.carFingerprint][Bus.radar] == BOSCH_A_DBC_NAME)

    if self.radar_off_can:
      self.rcp = None
      self.trigger_msg = 0x445
    elif self.bosch_a_radar:
      self.rcp = _create_bosch_a_can_parser(CP)
      self.trigger_msg = BOSCH_A_TRIGGER_MSG
      self._slots = [_BoschASlotState() for _ in range(BOSCH_A_NUM_SLOTS)]
      self._tracks: dict[int, _BoschATrackState] = {}
      self._slot_track_ids: list[int | None] = [None] * BOSCH_A_NUM_SLOTS
      self._last_trigger_nanos = -1
    else:
      # Nidec
      self.rcp = _create_nidec_can_parser(CP.carFingerprint)
      self.trigger_msg = 0x445
      self.track_id = 0
      self.radar_fault = False
      self.radar_wrong_config = False

    self.updated_messages = set()

  def update(self, can_strings):
    if self.radar_off_can or self.rcp is None:
      return super().update(None)

    vls = self.rcp.update(can_strings)
    self.updated_messages.update(vls)

    if self.trigger_msg not in self.updated_messages:
      if self.bosch_a_radar and self._last_trigger_nanos >= 0:
        now = self.rcp._last_update_nanos
        if (now - self._last_trigger_nanos) * 1e-9 > BOSCH_A_STALE_S:
          return self._bosch_a_stale_radardata()
      return None

    rr = self._update(self.updated_messages)
    self.updated_messages.clear()
    return rr

  def _bosch_a_stale_radardata(self):
    # Whole-bus silence: clear every live point/history and emit an EMPTY RadarData (not None) so
    # radard drops any lead within a cycle instead of freezing a phantom. The next observation starts
    # a fresh incarnation for its CAN identity.
    self.pts.clear()
    self._tracks.clear()
    self._slot_track_ids = [None] * BOSCH_A_NUM_SLOTS
    for slot_state in self._slots:
      slot_state.reset()
    self._last_trigger_nanos = -1
    stale = structs.RadarData()
    if not self.rcp.can_valid:
      stale.errors.canError = True
    stale.errors.radarUnavailableTemporary = True
    return stale

  def _bosch_a_retire_track(self, track_id: int):
    self._tracks.pop(track_id, None)
    self.pts.pop(track_id, None)
    for slot, slot_track_id in enumerate(self._slot_track_ids):
      if slot_track_id == track_id:
        self._slot_track_ids[slot] = None

  def _bosch_a_retire_stale_tracks(self, now: int):
    for track_id, track in list(self._tracks.items()):
      if track.last_seen_nanos is not None and (now - track.last_seen_nanos) * 1e-9 > BOSCH_A_STALE_S:
        self._bosch_a_retire_track(track_id)

  def _update(self, updated_messages):
    if self.bosch_a_radar:
      return self._update_bosch_a(updated_messages)
    return self._update_nidec(updated_messages)

  def _update_bosch_a(self, updated_messages):
    ret = structs.RadarData()
    if not self.rcp.can_valid:
      ret.errors.canError = True

    now = self.rcp._last_update_nanos
    self._last_trigger_nanos = now
    self._bosch_a_retire_stale_tracks(now)

    observations = []

    for slot in range(BOSCH_A_NUM_SLOTS):
      f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[slot]
      aux = BOSCH_A_AUX_IDS[slot]
      st = self._slots[slot]

      if not (f0 in updated_messages and f1 in updated_messages and
              f2 in updated_messages and f3 in updated_messages):
        # Incomplete main-frame set: a missing CAN frame must not be treated as a lifecycle mismatch or
        # death/replacement. Logical tracks are retired independently by their global staleness gate.
        continue

      v0 = self.rcp.vl[f0]
      v1 = self.rcp.vl[f1]
      v2 = self.rcp.vl[f2]
      v3 = self.rcp.vl[f3]

      idx0 = int(v0['FRAME_IDX'])
      if not (idx0 == int(v1['FRAME_IDX']) == int(v2['FRAME_IDX']) == int(v3['FRAME_IDX'])):
        # The four main frames don't share a common cycle index -- not a coherent observation this
        # window. Only combine main-frame data from a coherent common frame index (section 2).
        continue

      status = int(v0['STATUS'])
      range_raw = int(v0['RANGE_RAW'])
      angle_raw = int(v0['AZIMUTH_RAW'])
      range_sigma_raw = int(v0['RANGE_SIGMA_RAW'])
      existence_raw = int(v1['OBJECT_EXISTENCE_PROBABILITY_RAW'])
      life = int(v2['LIFECYCLE_RAW'])
      track_id = int(v3['TRACK_ID'])
      track_id_valid = BOSCH_A_TRACK_ID_MIN <= track_id <= BOSCH_A_TRACK_ID_MAX
      st.last_seen_nanos = now
      direct_vrel_raw = None
      direct_vrel_uncertainty_raw = None
      range_ratio_raw = None

      # Attach synchronized companion data only when its cycle matches. Missing AUX never invalidates
      # an otherwise coherent F0-F3 object; it only removes independent motion/quality evidence.
      if aux in updated_messages:
        av = self.rcp.vl[aux]
        if int(av['FRAME_IDX']) == idx0:
          direct_vrel_raw = int(av['REL_VELOCITY_RAW'])
          direct_vrel_uncertainty_raw = int(av['REL_VELOCITY_UNCERTAINTY_RAW'])
          range_ratio_raw = int(av['RANGE_RATIO_RAW'])
          logical_00c9_raw = av['FW_LID_00C9_RAW']
          logical_00ca_raw = av['FW_LID_00CA_RAW']
          st.logical_00c9_raw = logical_00c9_raw
          st.logical_00ca_raw = (
            logical_00ca_raw if logical_00ca_raw != BOSCH_A_LOGICAL_00CA_INVALID else float('nan')
          )
          st.direct_vrel_raw = direct_vrel_raw
          st.direct_vrel_uncertainty_raw = direct_vrel_uncertainty_raw

      object_valid = (status != BOSCH_A_STATUS_INVALID and range_raw != BOSCH_A_RANGE_RAW_INVALID and
                      angle_raw != BOSCH_A_ANGLE_RAW_INVALID and life != BOSCH_A_LIFE_INVALID)

      observations.append({
        'slot': slot,
        'frame_idx': idx0,
        'life': life,
        'track_id': track_id,
        'track_id_valid': track_id_valid,
        'object_valid': object_valid,
        'range_sigma_raw': range_sigma_raw,
        'existence_raw': existence_raw,
        'direct_vrel_raw': direct_vrel_raw,
        'direct_vrel_uncertainty_raw': direct_vrel_uncertainty_raw,
        'range_ratio_raw': range_ratio_raw,
      })

    # First collapse duplicate wire observations of one CAN identity. The dictionary is also the
    # output uniqueness boundary: one valid Bosch identity can never create two RadarPoints.
    valid_by_id = {}
    for observation in observations:
      if not (observation['object_valid'] and observation['track_id_valid']):
        # An invalid observation ends publication for the object currently occupying this wire slot,
        # but it does not immediately destroy the persistent state. The object may be multiplexed to
        # another slot or may return before the per-identity stale deadline; a later lifecycle break
        # or staleness expiry will clear its derivative history.
        ids_to_hide = {self._slot_track_ids[observation['slot']]}
        if observation['track_id_valid']:
          ids_to_hide.add(observation['track_id'])
        for invalid_id in ids_to_hide - {None}:
          self.pts.pop(invalid_id, None)
        continue
      track_id = observation['track_id']
      current = valid_by_id.get(track_id)
      if current is None:
        valid_by_id[track_id] = observation
        continue

      # Prefer the wire slot currently associated with the persistent state. If neither candidate is
      # preferred, retain the lower slot for deterministic handling of a malformed duplicate frame.
      track = self._tracks.get(track_id)
      current_score = (0 if track is not None and track.wire_slot == current['slot'] else 1, current['slot'])
      candidate_score = (0 if track is not None and track.wire_slot == observation['slot'] else 1,
                         observation['slot'])
      if candidate_score < current_score:
        valid_by_id[track_id] = observation

    valid_ids = set(valid_by_id)
    for track_id, observation in sorted(valid_by_id.items(), key=lambda item: item[1]['slot']):
      slot = observation['slot']
      idx0 = observation['frame_idx']
      life = observation['life']

      # A wire-slot replacement ends publication for the old occupant, but not its persistent
      # identity/history. If the old ID is still valid in another slot this sweep, keep its point;
      # otherwise hide it until that ID returns or reaches its own stale deadline.
      old_id = self._slot_track_ids[slot]
      if old_id is not None and old_id != track_id and old_id not in valid_ids:
        self.pts.pop(old_id, None)

      track = self._tracks.get(track_id)
      if track is None:
        track = _BoschATrackState(track_id=track_id)
        self._tracks[track_id] = track

      same_incarnation = False
      if track.prev_frame_idx is not None and track.prev_life is not None:
        frame_delta = (idx0 - track.prev_frame_idx) & 0xF
        life_delta = (life - track.prev_life) & 0xFFF
        same_incarnation = life_delta == 2 * frame_delta

      if not same_incarnation:
        # The CAN identity remains the externally-visible key, but a lifecycle discontinuity starts a
        # new incarnation and must not inherit the previous object's range-rate history.
        track.samples.clear()
        self.pts.pop(track_id, None)

      v0 = self.rcp.vl[BOSCH_A_MAIN_IDS[slot][0]]
      range_raw = int(v0['RANGE_RAW'])
      angle_raw = int(v0['AZIMUTH_RAW'])
      dRel = BOSCH_A_RANGE_SCALE_M * range_raw + BOSCH_A_RANGE_OFFSET_M
      azimuth_rad = BOSCH_A_AZIMUTH_SCALE_RAD * (angle_raw - BOSCH_A_AZIMUTH_CENTER)
      # The firmware's internal geometry path uses tan(angle) for a forward-axis distance.  The
      # Bosch object range is consumed as that forward-axis quantity here, so use the same projection
      # rather than treating it as radial/slant range.  Keep the switch explicit while the final
      # output bridge remains under static review.
      lateral_projection = math.tan if BOSCH_A_USE_TAN_LATERAL_PROJECTION else math.sin
      yRel = -dRel * lateral_projection(azimuth_rad)

      now_s = now * 1e-9
      direct_vrel_raw = observation['direct_vrel_raw']
      direct_vrel_uncertainty_raw = observation['direct_vrel_uncertainty_raw']
      direct_vrel = _bosch_a_direct_vrel(direct_vrel_raw, direct_vrel_uncertainty_raw)
      range_ratio_raw = observation['range_ratio_raw']

      # Validate against the previous accepted range. Qualified U11 and the range-ratio field are
      # independent corroboration paths; high-U10 U11 is deliberately excluded from this decision.
      previous_sample = track.samples[-1] if track.samples else None
      fallback_vrel = 0.0
      ratio_vrel = None
      range_rejected = False
      degraded = _bosch_a_measurement_degraded(
        observation['range_sigma_raw'], observation['existence_raw'], direct_vrel_uncertainty_raw,
      )
      if previous_sample is not None:
        previous_time, previous_range = previous_sample
        dt = now_s - previous_time
        if dt <= 0.0:
          range_rejected = True
        else:
          fallback_vrel = (dRel - previous_range) / dt
          ratio = _bosch_a_range_ratio(range_ratio_raw)
          ratio_vrel = _bosch_a_range_ratio_vrel(range_ratio_raw, dRel, dt)

          residuals_m = []
          if direct_vrel is not None:
            residuals_m.append(abs(dRel - (previous_range + direct_vrel * dt)))
          if ratio is not None:
            residuals_m.append(abs(previous_range - dRel * ratio))

          if residuals_m:
            innovation_m = min(residuals_m)
            range_rejected = (
              innovation_m > BOSCH_A_RANGE_INNOVATION_HARD_MAX_M or
              (degraded and innovation_m > BOSCH_A_RANGE_INNOVATION_MAX_M)
            )
          else:
            range_rejected = abs(fallback_vrel) > BOSCH_A_FALLBACK_RANGE_RATE_MAX_MPS

      if range_rejected:
        # Keep the last accepted point briefly as an unmeasured coast. The rejected geometry is not
        # published and never becomes the baseline for a later derivative.
        accepted_fresh = previous_sample is not None and now_s - previous_sample[0] <= BOSCH_A_STALE_S
        point = self.pts.get(track_id)
        if accepted_fresh and point is not None:
          point.measured = False
        else:
          self.pts.pop(track_id, None)
        track.prev_frame_idx = idx0
        track.prev_life = life
        track.last_seen_nanos = now
        track.wire_slot = slot
        for old_slot, old_id in enumerate(self._slot_track_ids):
          if old_slot != slot and old_id == track_id:
            self._slot_track_ids[old_slot] = None
        self._slot_track_ids[slot] = track_id
        continue

      track.samples.append((now_s, dRel))
      sample_count = len(track.samples)

      # Prefer qualified native U11. A healthy range ratio is the second source; otherwise use only
      # the adjacent derivative between accepted ranges. Do not extend U11 saturation rails with the
      # ratio yet: capture validation improves the negative rail but regresses the positive rail.
      if direct_vrel is not None:
        vRel = direct_vrel
      elif ratio_vrel is not None and not degraded:
        vRel = ratio_vrel
      else:
        vRel = fallback_vrel

      # A birth observation has no range-rate yet. Keep it as history, but do not publish a RadarPoint
      # until a second coherent observation of the same CAN identity supplies a finite derivative.
      matured = sample_count >= 2 and math.isfinite(vRel)
      if matured and track_id not in self.pts:
        self.pts[track_id] = structs.RadarData.RadarPoint()
        self.pts[track_id].trackId = track_id
        self.pts[track_id].aRel = float('nan')
        self.pts[track_id].yvRel = float('nan')

      if matured:
        self.pts[track_id].dRel = dRel
        self.pts[track_id].yRel = yRel
        self.pts[track_id].vRel = vRel
        self.pts[track_id].measured = True
      else:
        self.pts.pop(track_id, None)

      track.prev_frame_idx = idx0
      track.prev_life = life
      track.last_seen_nanos = now
      track.wire_slot = slot
      for old_slot, old_id in enumerate(self._slot_track_ids):
        if old_slot != slot and old_id == track_id:
          self._slot_track_ids[old_slot] = None
      self._slot_track_ids[slot] = track_id

    ret.points = [self.pts[track_id] for track_id in sorted(self.pts)]
    return ret

  def _update_nidec(self, updated_messages):
    ret = structs.RadarData()

    for ii in sorted(updated_messages):
      cpt = self.rcp.vl[ii]
      if ii == 0x400:
        # check for radar faults
        self.radar_fault = cpt['RADAR_STATE'] != 0x79
        self.radar_wrong_config = cpt['RADAR_STATE'] == 0x69
      elif cpt['LONG_DIST'] < 255:
        if ii not in self.pts or cpt['NEW_TRACK']:
          self.pts[ii] = structs.RadarData.RadarPoint()
          self.pts[ii].trackId = self.track_id
          self.track_id += 1
        self.pts[ii].dRel = cpt['LONG_DIST']  # from front of car
        self.pts[ii].yRel = -cpt['LAT_DIST']  # in car frame's y axis, left is positive
        self.pts[ii].vRel = cpt['REL_SPEED']
        self.pts[ii].aRel = float('nan')
        self.pts[ii].yvRel = float('nan')
        self.pts[ii].measured = True
      else:
        if ii in self.pts:
          del self.pts[ii]

    if not self.rcp.can_valid:
      ret.errors.canError = True
    if self.radar_fault:
      ret.errors.radarFault = True
    if self.radar_wrong_config:
      ret.errors.wrongConfig = True

    ret.points = list(self.pts.values())

    return ret
