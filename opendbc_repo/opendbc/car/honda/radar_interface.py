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

# Trigger on the highest-numbered main frame (slot 15's f3, 0x2FF): an assumed ascending transmit order
# within a sweep, matching the "trigger on the last ID" pattern used elsewhere in this codebase (Toyota,
# Hyundai, GM). Not a firmware-proven fact -- confirm against a live capture before relying on exact
# emit timing; the accumulate-until-trigger design below tolerates the order being wrong (it just widens
# the emit window across more update() batches), it just won't be pace-optimal.
BOSCH_A_TRIGGER_MSG = BOSCH_A_MAIN_IDS[BOSCH_A_NUM_SLOTS - 1][3]

# Range: f0 raw_range (12-bit, B2:B3 high nibble) -> meters. Firmware q16 = 8*raw_range; physical
# calibration keeps slope/offset as named, replay-refinable constants (do not add a second radar/camera
# longitudinal offset on top of this).
BOSCH_A_RANGE_SCALE_M = 0.05712
BOSCH_A_RANGE_OFFSET_M = -3.0

# Azimuth: f0 raw_angle (11-bit, B4:B5 high 3 bits) -> degrees, offset-binary about 1024.
BOSCH_A_AZIMUTH_SCALE_DEG = 0.032
BOSCH_A_AZIMUTH_CENTER = 1024

# Invalid sentinels (section 3/4/5/6 of the spec).
BOSCH_A_STATUS_INVALID = 0xF
BOSCH_A_RANGE_RAW_INVALID = 0xFFF
BOSCH_A_ANGLE_RAW_INVALID = 0x7FF
BOSCH_A_LIFE_INVALID = 0xFFF
BOSCH_A_AUX_RAW_INVALID = 0x3FF  # rawCA invalid sentinel (section 12); also used to gate rawC9 debug state

# vRel OLS history window -- a TUNING constant (max samples retained per live incarnation), NOT a
# recovered firmware value. Start simple; replay/unit tests decide if a KF or alpha-beta layer is needed.
BOSCH_A_VREL_MAX_SAMPLES = 8

# Staleness gate -- TUNING constant, reused plumbing pattern (not a firmware fact): if the whole bus goes
# quiet (no trigger frame) this long, drop every live point rather than freezing a phantom lead. Also
# used per-slot: a slot with no coherent observation for this long is dropped even while the bus overall
# stays live (e.g. the firmware genuinely stopped transmitting that slot's IDs without ever sending an
# explicit invalid/sentinel observation).
BOSCH_A_STALE_S = 0.15  # ~3 missed 20 Hz sweeps


@dataclass
class _BoschASlotState:
  track_id: int | None = None
  prev_valid: bool = False
  prev_frame_idx: int | None = None
  prev_life: int | None = None
  last_seen_nanos: int | None = None
  samples: deque = field(default_factory=lambda: deque(maxlen=BOSCH_A_VREL_MAX_SAMPLES))
  # Auxiliary enrichment (section 12) -- debug/telemetry only, never a RadarPoint validity gate.
  aux_raw_c9: float = float('nan')
  aux_raw_ca: float = float('nan')

  def reset(self):
    self.prev_valid = False
    self.prev_frame_idx = None
    self.prev_life = None
    self.samples.clear()
    self.aux_raw_c9 = float('nan')
    self.aux_raw_ca = float('nan')


def _bosch_a_ols_vrel(samples: deque) -> float:
  """Lifecycle-clean temporal range-rate estimate (section 10). samples: deque[(t_seconds, dRel_m)]."""
  n = len(samples)
  if n < 2:
    # A single sample (first sighting of an incarnation) has no derivative yet.
    return 0.0
  if n == 2:
    (t1, d1), (t2, d2) = samples
    dt = t2 - t1
    return (d2 - d1) / dt if dt > 0 else 0.0

  t_newest = samples[-1][0]
  N = n
  St = Sd = Stt = Std = 0.0
  for t, d in samples:
    tau = t - t_newest
    St += tau
    Sd += d
    Stt += tau * tau
    Std += tau * d
  denom = N * Stt - St * St
  if denom == 0.0:
    return 0.0
  return (N * Std - St * Sd) / denom


def _create_bosch_a_can_parser(CP):
  messages = [(addr, 20) for addr in BOSCH_A_ALL_IDS]
  return CANParser(DBC[CP.carFingerprint][Bus.radar], messages, CanBus(CP).radar)


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
      self._next_track_id = 0
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
      if self.bosch_a_radar and self.pts and self._last_trigger_nanos >= 0:
        now = self.rcp._last_update_nanos
        if (now - self._last_trigger_nanos) * 1e-9 > BOSCH_A_STALE_S:
          return self._bosch_a_stale_radardata()
      return None

    rr = self._update(self.updated_messages)
    self.updated_messages.clear()
    return rr

  def _bosch_a_stale_radardata(self):
    # Whole-bus silence: clear every live point/history and emit an EMPTY RadarData (not None) so
    # radard drops any lead within a cycle instead of freezing a phantom. trackIds are not reused even
    # across a staleness clear -- a slot that revives later gets a fresh incarnation and trackId.
    self.pts.clear()
    for slot_state in self._slots:
      slot_state.reset()
    self._last_trigger_nanos = -1
    stale = structs.RadarData()
    if not self.rcp.can_valid:
      stale.errors.canError = True
    stale.errors.radarUnavailableTemporary = True
    return stale

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
    now_s = now * 1e-9

    for slot in range(BOSCH_A_NUM_SLOTS):
      f0, f1, f2, f3 = BOSCH_A_MAIN_IDS[slot]
      aux = BOSCH_A_AUX_IDS[slot]
      st = self._slots[slot]

      if not (f0 in updated_messages and f1 in updated_messages and
              f2 in updated_messages and f3 in updated_messages):
        # Incomplete main-frame set this cycle: a missing CAN frame must NOT be treated as a lifecycle
        # mismatch or a death/replacement decision (section 8). Leave the existing point/history alone,
        # except for the per-slot staleness gate (a slot that has been silent -- not merely
        # partially-assembled this one cycle -- for BOSCH_A_STALE_S is dropped).
        if st.prev_valid and st.last_seen_nanos is not None and (now - st.last_seen_nanos) * 1e-9 > BOSCH_A_STALE_S:
          self.pts.pop(slot, None)
          st.reset()
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
      life = int(v2['LIFECYCLE_RAW'])

      # Auxiliary enrichment: attach only when its own cycle index matches this observation's. A
      # missing/stale/off-cycle aux frame must never suppress an otherwise-good RadarPoint (section 2).
      if aux in updated_messages:
        av = self.rcp.vl[aux]
        if int(av['FRAME_IDX']) == idx0:
          raw_c9 = av['RAWC9_RAW']
          raw_ca = av['RAWCA_RAW']
          st.aux_raw_c9 = raw_c9
          st.aux_raw_ca = raw_ca if raw_ca != BOSCH_A_AUX_RAW_INVALID else float('nan')

      object_valid = (status != BOSCH_A_STATUS_INVALID and range_raw != BOSCH_A_RANGE_RAW_INVALID and
                      angle_raw != BOSCH_A_ANGLE_RAW_INVALID and life != BOSCH_A_LIFE_INVALID)

      if not object_valid:
        # DEATH: a coherent completed observation that fails validity retires the point/history.
        if st.prev_valid:
          self.pts.pop(slot, None)
        st.reset()
        continue

      same_incarnation = False
      if st.prev_valid:
        frame_delta = (idx0 - st.prev_frame_idx) & 0xF
        life_delta = (life - st.prev_life) & 0xFFF
        same_incarnation = (life_delta == 2 * frame_delta)

      if not st.prev_valid or not same_incarnation:
        # BIRTH (no prior valid observation) or IN-PLACE REPLACEMENT (lifecycle identity broken):
        # allocate a fresh, never-reused trackId and clear all dRel/vRel history.
        st.track_id = self._next_track_id
        self._next_track_id += 1
        st.samples.clear()
        self.pts.pop(slot, None)
      # else: CONTINUE -- same trackId, history retained.

      dRel = BOSCH_A_RANGE_SCALE_M * range_raw + BOSCH_A_RANGE_OFFSET_M
      azimuth_deg = BOSCH_A_AZIMUTH_SCALE_DEG * (angle_raw - BOSCH_A_AZIMUTH_CENTER)
      azimuth_rad = math.radians(azimuth_deg)
      yRel = -dRel * math.sin(azimuth_rad)

      st.samples.append((now_s, dRel))
      vRel = _bosch_a_ols_vrel(st.samples)

      if slot not in self.pts:
        self.pts[slot] = structs.RadarData.RadarPoint()
        self.pts[slot].trackId = st.track_id
        self.pts[slot].aRel = float('nan')
        self.pts[slot].yvRel = float('nan')

      self.pts[slot].dRel = dRel
      self.pts[slot].yRel = yRel
      self.pts[slot].vRel = vRel
      self.pts[slot].measured = True

      st.prev_valid = True
      st.prev_frame_idx = idx0
      st.prev_life = life
      st.last_seen_nanos = now

    ret.points = list(self.pts.values())
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
