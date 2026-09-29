"""Per-drive numbers the lateral and longitudinal agents asked for (2026-09-28), computed from Plots recordings and,
through tools/drive_plots/rlog_report.py, from any route's rlogs:

- driver takeovers, per episode and route-wide: Driver override (Kevin) and Metadrive Sim (John), whose gate uses the
  same definitions (hold swing, release overshoot, back on plan, release step, drift toward the push);
- radar / longitudinal moments: Radar Work (Bob);
- lane centring, angle tracking, feedforward, integrator and tight-turn lag per speed band: VFN Shadow controller
  (James), for LatControlClarityEps.

Pure functions over the recorder's column dict ``c`` (name -> float array). NaN means "not recorded" (a recording made
before the column existed, or a message that never arrived); every metric that needs a missing column is None, never a
number built from zeros. Times: ``t`` in the output is seconds from the start of the arrays and ``mono_s`` is the
frame's logMonoTime in seconds, so a caller can convert exactly (the rlog report turns it into seconds from the
route's first logMonoTime).

Sign conventions: wheel angle and steeringTorque are + = left; lat_des and des_curv are + = right. lane_off is the
car's offset from the lane centre, + = car left of centre (modelV2 laneLines y is + = right, so the centre's y at x=0
is the car's offset to the left). "Toward the push" is + in the direction the driver pushed the wheel.

Not recorded, so never reconstructed here (James): the controller output before its low-pass filter, ff_ramp on its
own, the modified EPS's own pressed signal, and design C's driver-led offset/flag. carState.steeringPressed is the raw
pressed bit, so takeovers are labelled "raw pressed". BLoTv3 and Bosch-A gate internals are not published on any
cereal message (Bob); leadOne.radar and radarTrackId are the published proxies.
"""
import numpy as np

MPH = 2.23694
BANDS = [(0.0, 25.0 / MPH, "Low speed"), (25.0 / MPH, 50.0 / MPH, "Standard"), (50.0 / MPH, float("inf"), "Highway")]

# ---- driver takeovers (Kevin / John) ----
TAKEOVER_TQ_START = 600.0     # |carState.steeringTorque| that starts a takeover without steeringPressed (Honda units)
TAKEOVER_TQ_RELEASE = 300.0   # release: |steeringTorque| below this ...
TAKEOVER_RELEASE_HOLD_S = 0.3  # ... for this long (Kevin)
TAKEOVER_SHORT_S = 1.0        # shorter holds are tagged "short grab"
SWING_SKIP_S = 0.5            # hold swing is measured from press + this to release (John)
OVERSHOOT_WINDOW_S = 3.0      # release overshoot window
SETTLE_DEG = (1.0, 2.0)       # back on plan: |wheel - plan| under this ...
SETTLE_HOLD_S = 0.5           # ... for this long
SETTLE_MAX_S = 10.0
RELEASE_STEP_S = 0.5          # largest per-frame change in delivered torque over [release, +this)
DRIFT_AT_S = (1.0, 3.0, 6.0)  # lane drift toward the push, measured from the position at release
VLAT_HALF_S = 0.25            # lateral speed at release: slope of lane_off over +-this
LANES_OK_PROB = 0.5           # both lane lines at least this likely: lane numbers usable
# James (route 293): a window's lane numbers count when both lines are above LANES_OK_PROB for LANES_OK_FRAC of its
# frames and neither stays under LANES_LOST_PROB longer than LANES_LOST_S in a row. Lines flicker to 0 for a frame
# at merges and gores; requiring every frame kept 1 of 80 takeovers on that route.
LANES_OK_FRAC = 0.9
LANES_LOST_PROB = 0.3
LANES_LOST_S = 0.5
TORQUE_CUT_FRAC = 0.5         # delivered torque below this fraction of the requested ...
TORQUE_CUT_MIN = 0.05         # ... while the request is at least this (normalized torque): cut or faded
STALL_MS = 100.0              # controlsState older than this inside an episode: stalled (John drops these)
RELEASE_CLASS_V = 15.0        # James's "driver release": a grab above this speed (m/s) ...
RELEASE_CLASS_MAX_S = 3.0     # ... held under this long
# Kevin's turn-fight numbers (2026-09-29): slow turns where the plan is tighter than the wheel, the EPS faulting while
# pressed, and drivers holding just under the cut.
TURN_ANG_DES = 30.0           # |ang_des| at release above this (deg): a turn, else a straight
SLOPE_HALF_S = 0.05           # takeback rate: least-squares slope of lat_out over +-this (a 0.1 s window); a frame
                              # difference at 20 Hz measured timestamp jitter (3-4 /s fake against ~2 /s real)
TAKEBACK_WINDOW_S = 1.0       # peak takeback rate over [release, +this)
T90_SETTLE_S = (2.5, 3.0)     # lat_out's settled value: its median over [release + a, release + b]
T90_MIN_CHANGE = 0.05         # a takeback smaller than this (normalized output) has no t90
REPRESS_S = (0.3, 0.8)        # a re-press this long after the release: the snapback Kevin flags
REPRESS_LATE_S = (0.8, 1.3)   # report-only count
NEAR_CUT_TQ = (1500.0, 1800.0)  # |steeringTorque| held in this band without steeringPressed: holding just under the cut
# Kevin's live flags on each takeover (published as it finishes): FLICKER = steerFaultTemporary during the press;
# SNAPBACK = repress; GAP = |release_gap_deg| over GAP_FLAG_DEG under GAP_FLAG_V; NEAR-CUT = near-cut band held in one
# run longer than NEAR_CUT_HOLD_S.
GAP_FLAG_DEG = 20.0
GAP_FLAG_V = 4.47             # m/s: 10 mph
NEAR_CUT_HOLD_S = 1.0

# ---- radar / longitudinal moments (Bob) ----
BRAKE_LIST = -1.5             # aTarget below this is a braking moment (Bob's replay episodes use -1.5)
BRAKE_HARD = -2.5             # ... and "hard" below this
MERGE_S = 3.0
LEAD_APPEAR_D = 30.0          # a lead that appears closer than this (m)
LEAD_JUMP_D = 8.0             # or whose distance drops by more than this in one frame
LEAD_VANISH_D = 40.0          # a lead lost while closer than this, ego moving
LEAD_VANISH_V = 2.0
TRACK_SWAP_D = 3.0            # radarTrackId changed while the distance moved less than this: same car, new ID
LEAD_IN_LANE_Y = 2.0          # |lead y| (m) for appear / vanish: next-lane camera leads flicker (Bob, route 28f: 21 of 29)
LEAD_HOLD_S = 0.5             # the new lead state must hold this long before an appear / vanish counts
LEAD_FLICKER_S = 1.0          # an appear and a vanish this close together are one "lead_flicker"
NO_LEAD_BRAKE = -1.0
CAMERA_BRAKE = -1.5
GAS_BRAKE_PLAN = -0.5         # gas press after the plan braked below this ...
GAS_BRAKE_HOLD_S = 0.3        # ... for at least this long
DRIVER_BRAKE_PLAN = -0.5      # brake press while openpilot's plan was gentler than this
# James's 2026-09-29 lateral moments.
SNAP_WINDOW_S = 1.0           # release_snap: peak |d tq_out/dt| over [release, +this) ...
SNAP_REPRESS_S = 1.5          # ... and whether steeringPressed rises again within this
HWY_V = 20.0                  # m/s: highway moments
INSIDE_CUT_DEMAND = 0.5       # |lat_des| m/s^2 ...
INSIDE_CUT_M = 0.25           # ... car toward the inside of the curve by more than this (m) ...
INSIDE_CUT_S = 2.0            # ... for at least this long
CURVE_SIDE_MIN_DEG = 0.5      # |wheel angle - angle offset| under this: curve side unknown (James)
WIGGLE_DEMAND = 0.3           # |lat_des| m/s^2 under this: a straight
WIGGLE_TQ = 0.05              # |tq_out| (normalized) a swing must pass on each side to count
WIGGLE_CROSSINGS = 4          # this many sign changes ...
WIGGLE_S = 3.0                # ... within this long
# Bob's 2026-09-29 moments.
EXP_FLIP_S = 1.0              # experimental mode switched again this soon after its previous switch: exp_flipflop
RED_LIGHT_STOP_V = 2.0        # a red light the car did not slow below this (m/s) ...
RED_LIGHT_WINDOW_S = 10.0     # ... within this long after it came on: false_red_light
ATARGET_STEP = 0.5            # |aTarget change| between consecutive plan frames (m/s^2)
COAST_NEAR_D = 40.0           # radar lead closer than this (m) ...
COAST_NEAR_S = 0.5            # ... coasting (measuredRadar false) longer than this
VREL_DISAGREE = 3.0           # |vRel - vRelRangeDerived| (m/s) ...
VREL_DISAGREE_S = 1.0         # ... for longer than this, moving (Bob: 1.5 / 0.5 s gave 263 in 0.96 h of route 297)
MODEL_DISAGREE_D = (5.0, 0.15)  # |radar d - model d| > max(5 m, 0.15 d) ...
MODEL_DISAGREE_S = 1.0        # ... for longer than this, model lead prob above MODEL_PROB_MIN
MODEL_PROB_MIN = 0.5
OVERSPEED_MS = 0.45           # vEgo above the set speed by this (m/s) with no lead ...
OVERSPEED_S = 3.0             # ... for longer than this
V_CRUISE_UNSET = 250.0        # carState.vCruise (km/h) at or above this is "not set" (255)
GF_CLIP = 1.59                # gasLearnerGasFactorRaw at the clip
GF_REARM_S = 5.0

# ---- lateral detail (James) ----
LANE_PROB_MIN = 0.4
CURVE_DEMAND = 0.5            # |lat_des| m/s^2: a curve
STRAIGHT_DEMAND = 0.15        # |lat_des| m/s^2: a straight
LANE_OFF_NOTABLE = 0.3        # m
LANE_DEADBAND = 0.08          # m; lane centring's own deadband, never a controller bias on its own
AFTER_RELEASE_S = 1.0         # frames this soon after a raw press are left out of controller metrics
TIGHT_DEG = 30.0              # tight turn for turn-in lag
LAT_MIN_V = 5.0


def has(c, name):
  x = c.get(name)
  return x is not None and len(x) > 0 and not np.all(np.isnan(x))


def _r(x, n=2):
  if x is None:
    return None
  try:
    x = float(x)
  except (TypeError, ValueError):
    return None
  return round(x, n) if np.isfinite(x) else None


def _pct(x, q):
  x = x[np.isfinite(x)]
  return float(np.percentile(x, q)) if len(x) else None


def _dt(t):
  d = np.diff(t)
  d = d[(d > 0) & (d < 0.2)]
  return float(np.median(d)) if len(d) else 0.05


def _b(c, name):
  x = c.get(name)
  if x is None:
    return np.zeros(len(c["t"]), dtype=bool)
  return np.nan_to_num(x) > 0.5


def _starts(mask, t, merge_s=MERGE_S):
  """Rising edges of mask, merging edges closer than merge_s to the previous kept one."""
  m = np.asarray(mask, dtype=bool)
  if len(m) == 0:
    return []
  idx = np.flatnonzero(m & ~np.concatenate([[False], m[:-1]]))
  out = []
  for i in idx:
    if not out or t[i] - t[out[-1]] >= merge_s:
      out.append(int(i))
  return out


def _runs_of(mask):
  """(start, end) index pairs of the True runs in mask, end exclusive."""
  m = np.concatenate([[False], np.asarray(mask, dtype=bool), [False]])
  d = np.flatnonzero(np.diff(m.astype(np.int8)))
  return list(zip(d[::2], d[1::2], strict=True))


def _held_runs(mask, t, hold_s):
  """(start, end, seconds) of the True runs of mask lasting longer than hold_s; end exclusive."""
  out = []
  for a, b in _runs_of(mask):
    dur = float(t[min(b, len(t) - 1)] - t[a])   # until the first False frame (or the last frame)
    if dur > hold_s:
      out.append((int(a), int(b), dur))
  return out


def _at(t, t0):
  return int(min(len(t) - 1, max(0, np.searchsorted(t, t0))))


def band_of(v):
  for lo, hi, name in BANDS:
    if lo <= v < hi:
      return name
  return BANDS[-1][2]


def held(c):
  """True while the driver holds the wheel: raw steeringPressed or inside a takeover episode (steeringPressed flickers
  off during a light hold the torque still shows)."""
  out = _b(c, "steer_pressed").copy()
  for a, r in _episodes(c):
    out[a:r + 1] = True
  return out


def after_release(c, s=AFTER_RELEASE_S):
  """True while the driver holds the wheel and for s seconds after. A hold is raw steeringPressed or a takeover
  episode: steeringPressed flickers off during a light hold the torque still shows (James, route 293: tight turns
  and a 15 s hold leaked through on steeringPressed alone)."""
  t = c["t"]
  h = held(c)
  out = h.copy()
  last_end = -1e9
  for i in range(len(t)):
    if i > 0 and h[i - 1] and not h[i]:
      last_end = t[i]
    if t[i] - last_end < s:
      out[i] = True
  return out


def unwrap_lane(off, width):
  """Lane offset made continuous across lane changes: a one-frame jump of more than half a lane width is a new lane,
  so the lane width is added back (the car did not teleport)."""
  off = np.asarray(off, dtype=float).copy()
  if len(off) < 2:
    return off
  w = np.where(np.isfinite(width) & (width > 2.0), width, 3.6)
  shift = 0.0
  prev = off[0]
  for i in range(1, len(off)):
    if not np.isfinite(off[i]):
      continue
    if np.isfinite(prev):
      jump = off[i] - prev
      if abs(jump) > 0.5 * w[i]:
        shift -= np.sign(jump) * w[i]
    prev = off[i]
    off[i] += shift
  return off


# =====================================================================================================
# Driver takeovers
# =====================================================================================================

def _episodes(c):
  """(start, release) index pairs. Start: steeringPressed rises or |steeringTorque| > TAKEOVER_TQ_START.
  Release: |steeringTorque| < TAKEOVER_TQ_RELEASE for TAKEOVER_RELEASE_HOLD_S (steeringPressed falling when the
  torque was not recorded)."""
  t = c["t"]
  n = len(t)
  pressed = _b(c, "steer_pressed")
  tq_ok = has(c, "steer_tq")
  tq = np.abs(np.nan_to_num(c["steer_tq"])) if tq_ok else np.zeros(n)
  start = pressed | (tq > TAKEOVER_TQ_START)
  eps = []
  i = 0
  while i < n:
    if not start[i]:
      i += 1
      continue
    s = i
    j = i + 1
    quiet_since = None
    while j < n:
      if t[j] - t[j - 1] > 0.5:   # a gap in the data ends the episode where the data ended
        break
      quiet = (tq[j] < TAKEOVER_TQ_RELEASE) if tq_ok else not pressed[j]
      if quiet:
        if quiet_since is None:
          quiet_since = j
        if t[j] - t[quiet_since] >= (TAKEOVER_RELEASE_HOLD_S if tq_ok else 0.0):
          break
      else:
        quiet_since = None
      j += 1
    r = quiet_since if quiet_since is not None else min(j, n - 1)
    eps.append((s, max(s, r)))
    i = max(j, r + 1)
  return eps


def _settle(t, err, r, thr):
  end = t[r] + SETTLE_MAX_S
  since = None
  for k in range(r, len(t)):
    if t[k] > end:
      return None
    if abs(err[k]) < thr:
      if since is None:
        since = k
      if t[k] - t[since] >= SETTLE_HOLD_S:
        return round(float(t[since] - t[r]), 2)
    else:
      since = None
  return None


def _ls_slope(t, y, k, half):
  """Least-squares slope of y against t over the frames within +-half s of frame k (None under 3 frames)."""
  a, b = int(np.searchsorted(t, t[k] - half - 1e-6)), int(np.searchsorted(t, t[k] + half + 1e-6))
  tt, yy = t[a:b], y[a:b]
  ok = np.isfinite(yy)
  tt, yy = tt[ok], yy[ok]
  if len(tt) < 3:
    return None
  tt = tt - tt.mean()
  den = float(np.sum(tt * tt))
  return float(np.sum(tt * (yy - yy.mean())) / den) if den > 0 else None


def _frames_s(t, mask):
  """Seconds covered by the True frames of mask, each frame lasting until the next (gaps over 0.2 s cut to 0.2)."""
  if len(t) < 2 or not np.any(mask):
    return 0.0
  d = np.clip(np.diff(t, append=t[-1]), 0.0, 0.2)
  return float(np.sum(d[mask]))


def _turn_fight(c, t, s, r, dt, angles, err):
  """Kevin's per-episode numbers (see TURN_ANG_DES and below). NaN-only columns give None."""
  v = c["v"]
  e = {"v_release": _r(v[r], 1)}
  ang_des = c["ang_des"] if angles else None
  e["turn"] = bool(abs(ang_des[r]) > TURN_ANG_DES) if ang_des is not None and np.isfinite(ang_des[r]) else None
  e["release_gap_deg"] = _r(-err[r], 1) if err is not None and np.isfinite(err[r]) else None
  out = c["lat_out"] if has(c, "lat_out") else None
  e["lat_out_release"] = _r(abs(out[r]), 3) if out is not None and np.isfinite(out[r]) else None
  e["takeback_rate_peak"] = e["t90_s"] = None
  if out is not None:
    hi = _at(t, t[r] + TAKEBACK_WINDOW_S)
    rates = [_ls_slope(t, out, k, SLOPE_HALF_S) for k in range(r, hi)]
    rates = [abs(x) for x in rates if x is not None]
    e["takeback_rate_peak"] = _r(max(rates), 2) if rates else None
    if t[-1] >= t[r] + T90_SETTLE_S[1] and np.isfinite(out[r]):
      a, b = _at(t, t[r] + T90_SETTLE_S[0]), _at(t, t[r] + T90_SETTLE_S[1])
      pressed_again = bool(np.any(_b(c, "steer_pressed")[r + 1:b + 1]))
      tail = out[a:b + 1]
      if not pressed_again and np.any(np.isfinite(tail)):
        change = float(np.nanmedian(tail)) - float(out[r])
        if abs(change) >= T90_MIN_CHANGE:
          frac = (out[r:b + 1] - out[r]) / change
          hit = np.flatnonzero(np.nan_to_num(frac, nan=-1.0) >= 0.9)
          e["t90_s"] = _r(t[r + hit[0]] - t[r], 2) if len(hit) else None
  w = slice(s, r + 1)
  fault = _b(c, "fault_t")[w] if has(c, "fault_t") else None
  lat_on = _b(c, "lat_active")[w] if has(c, "lat_active") else None
  if fault is not None or lat_on is not None:
    flick = np.zeros(r + 1 - s, dtype=bool)
    if fault is not None:
      flick |= fault
    if lat_on is not None and len(lat_on) and lat_on[0]:
      flick |= ~lat_on
    e["fault_flicker_n"] = len(_runs_of(flick))
    e["fault_flicker_ms"] = _r(_frames_s(t[w], flick) * 1000.0, 0)
  else:
    e["fault_flicker_n"] = e["fault_flicker_ms"] = None
  if ang_des is not None and r > s:
    d = np.abs(np.diff(ang_des[w])) / np.maximum(np.diff(t[w]), 0.01)
    e["ang_des_step_max_dps"] = _r(np.nanmax(d), 0) if np.any(np.isfinite(d)) else None
  else:
    e["ang_des_step_max_dps"] = None
  if has(c, "steer_tq"):
    tq = np.abs(c["steer_tq"][w])
    pressed = _b(c, "steer_pressed")[w]
    lat_now = _b(c, "lat_active")[w]
    e["override_cut_s"] = _r(_frames_s(t[w], lat_now & pressed), 2)
    near = (tq >= NEAR_CUT_TQ[0]) & (tq <= NEAR_CUT_TQ[1]) & ~pressed
    e["near_cut_s"] = _r(_frames_s(t[w], near), 2)
    e["near_cut_held_s"] = _r(max([x[2] for x in _held_runs(near, t[w], 0.0)], default=0.0), 2)
  else:
    e["override_cut_s"] = e["near_cut_s"] = e["near_cut_held_s"] = None
  e["fault_in_press"] = bool(np.any(fault)) if fault is not None else None
  return e


def takeovers(c, t0=None):
  """Every driver takeover with the per-episode numbers, plus route-wide counts."""
  t = c["t"]
  if len(t) < 2:
    return {"episodes": [], "summary": {"count": 0}}
  t0 = t[0] if t0 is None else t0
  dt = _dt(t)
  v = np.nan_to_num(c["v"])
  angles = has(c, "ang_des") and np.any(_b(c, "ang_ok"))
  err = (c["ang_act"] - c["ang_des"]) if angles else None
  # James's "back within 2 deg" uses the controller's own pidState.angleError (only its magnitude is used).
  ctrl_err = c["ang_err"] if angles and has(c, "ang_err") else err
  tq = c["steer_tq"] if has(c, "steer_tq") else None
  lane = has(c, "lane_off")
  off = unwrap_lane(c["lane_off"], c["lane_w"] if has(c, "lane_w") else np.full(len(t), np.nan)) if lane else None
  prob = c["lane_prob"] if has(c, "lane_prob") else None
  out_ok, req_ok = has(c, "tq_out"), has(c, "tq_req")
  i_ok = has(c, "lat_i")
  eps = []
  for s, r in _episodes(c):
    hold = float(t[r] - t[s])
    seg_tq = np.nan_to_num(tq[s:r + 1]) if tq is not None else None
    push = 0
    if seg_tq is not None and len(seg_tq) and np.any(seg_tq):
      push = int(np.sign(np.sum(seg_tq)))
    elif angles:
      push = int(np.sign(np.nansum(err[s:r + 1])))
    e = {
      "t": round(float(t[s] - t0), 2), "mono_s": round(float(t[s]), 3), "release_t": round(float(t[r] - t0), 2),
      "hold_s": round(hold, 2), "tag": "short grab" if hold < TAKEOVER_SHORT_S else "long hold",
      "v": _r(v[s], 1), "band": band_of(v[s]), "push": {1: "left", -1: "right"}.get(push),
      "blinker": bool(np.any(_b(c, "blinker")[s:r + 1])),
      "lat_active": bool(np.any(_b(c, "lat_active")[max(0, s - 2):s + 1])),
      "tq_peak": _r(np.max(np.abs(seg_tq)), 0) if seg_tq is not None and len(seg_tq) else None,
      "tq_mean": _r(np.mean(np.abs(seg_tq)), 0) if seg_tq is not None and len(seg_tq) else None,
      "release_class": bool(v[s] > RELEASE_CLASS_V and hold < RELEASE_CLASS_MAX_S),
      # openpilot steering again within 0.5 s of the release; otherwise there is no plan being returned to.
      "lat_active_after": bool(np.any(_b(c, "lat_active")[r:_at(t, t[r] + 0.5) + 1])),
    }
    # Torque cut / fade: delivered clearly below requested.
    if out_ok and req_ok:
      w = slice(s, min(len(t), r + int(round(1.0 / dt)) + 1))
      req, got = np.nan_to_num(c["tq_req"][w]), np.nan_to_num(c["tq_out"][w])
      cut = (np.abs(req) >= TORQUE_CUT_MIN) & (np.abs(got) < TORQUE_CUT_FRAC * np.abs(req))
      e["cut_s"] = round(float(np.count_nonzero(cut) * dt), 2)
      e["cut_start"] = round(float(t[w][np.argmax(cut)] - t[s]), 2) if np.any(cut) else None
      k = slice(r, min(len(t), r + max(2, int(round(RELEASE_STEP_S / dt)) + 1)))
      d = np.abs(np.diff(np.nan_to_num(c["tq_out"][k])))
      e["release_step_max"] = _r(np.max(d), 4) if len(d) else None
    else:
      e["cut_s"] = e["cut_start"] = e["release_step_max"] = None
    e.update(_turn_fight(c, t, s, r, dt, angles, err))
    # Kevin: at the car's 20 Hz a 0.1 s slope window holds 2-3 samples, so takeback_rate_peak is noisier than his
    # 100 Hz road table; label it (rlog_report --rate carstate rebuilds at 100 Hz).
    e["sample_hz"] = int(round(1.0 / dt)) if dt > 0 else None
    if i_ok:
      e["i_press_min"] = _r(np.nanmin(c["lat_i"][s:r + 1]), 4) if np.any(np.isfinite(c["lat_i"][s:r + 1])) else None
      e["i_press"] = _r(c["lat_i"][s], 4)
      e["i_release"] = _r(c["lat_i"][r], 4)
      e["i_release_1s"] = _r(c["lat_i"][_at(t, t[r] + 1.0)], 4) if t[-1] >= t[r] + 1.0 else None
    if angles and err is not None and not e["lat_active_after"]:
      e["hold_swing_deg"] = e["release_overshoot_deg"] = e["back_on_plan_s"] = e["back_within_2deg_s"] = None
    elif angles and err is not None:
      k0 = _at(t, t[s] + SWING_SKIP_S)
      sw = err[k0:r + 1]
      e["hold_swing_deg"] = _r(np.nanmax(sw) - np.nanmin(sw), 1) if hold > SWING_SKIP_S and len(sw) else None
      k1 = _at(t, t[r] + OVERSHOOT_WINDOW_S)
      post = err[r:k1 + 1]
      if push and len(post):
        e["release_overshoot_deg"] = _r(max(0.0, float(np.nanmax(-push * post))), 1)
      else:
        e["release_overshoot_deg"] = None
      e["back_on_plan_s"] = _settle(t, err, r, SETTLE_DEG[0])
      e["back_within_2deg_s"] = _settle(t, ctrl_err, r, SETTLE_DEG[1])
    # Lane numbers count only when the lines were seen from the press to the end of the window: a faint line jumps
    # and reads as drift (James, route 293: 1.06 m "drift" with the right line at 0.02-0.18). lane_prob is already
    # the lower of the two lines; a missing frame counts as not seen.
    def lanes_through(k):
      if prob is None or k is None:
        return False
      p = np.nan_to_num(prob[s:k + 1], nan=0.0)
      if not len(p) or np.mean(p > LANES_OK_PROB) < LANES_OK_FRAC:
        return False
      lost = [r_ - a_ for a_, r_ in _runs_of(p < LANES_LOST_PROB)]
      return bool(not lost or max(lost) * dt <= LANES_LOST_S)

    if lane and push:
      base = off[r]
      for s_ in DRIFT_AT_S:
        k = _at(t, t[r] + s_)
        e[f"drift_{s_:g}s_m"] = (_r(push * (off[k] - base), 2)
                                 if t[-1] >= t[r] + s_ and np.isfinite(base) and lanes_through(k) else None)
      a, b = _at(t, t[r] - VLAT_HALF_S), _at(t, t[r] + VLAT_HALF_S)
      e["vlat_rel"] = (_r(push * (off[b] - off[a]) / (t[b] - t[a]), 2)
                       if t[b] > t[a] and np.isfinite(off[a]) and np.isfinite(off[b]) else None)
    else:
      for s_ in DRIFT_AT_S:
        e[f"drift_{s_:g}s_m"] = None
      e["vlat_rel"] = None
    # James: lateral position from the centre of the lane the car was in at the press (+ = left), carried across a lane
    # change by the unwrap, at press, release and press + 3 s: the real-grab twin of the design-C sim's "residual at
    # +3 s from press". Limited road evidence only; a real grab has no no-push twin, so it is never scored pass/fail.
    for key, k in (("lane_press_m", s), ("lane_release_m", r), ("lane_press_3s_m", _at(t, t[s] + 3.0) if t[-1] >= t[s] + 3.0 else None)):
      e[key] = (_r(c["lane_off"][s] + (off[k] - off[s]), 2)
                if lane and k is not None and np.isfinite(c["lane_off"][s]) and np.isfinite(off[k]) and lanes_through(k)
                else None)
    if prob is not None:
      e["lane_prob_release"] = _r(prob[r], 2)
      p = prob[s:_at(t, t[r] + DRIFT_AT_S[-1]) + 1]
      e["lane_prob_min"] = _r(np.nanmin(p), 2) if np.any(np.isfinite(p)) else None
      e["lane_ok_frac"] = _r(np.mean(np.nan_to_num(p, nan=0.0) > LANES_OK_PROB), 2) if len(p) else None
      e["lanes_ok"] = lanes_through(r)
    else:
      e["lane_prob_release"], e["lane_prob_min"], e["lane_ok_frac"], e["lanes_ok"] = None, None, None, False
    if has(c, "cs_age_ms"):
      w = slice(s, _at(t, t[r] + DRIFT_AT_S[-1]) + 1)
      e["cs_age_max_ms"] = _r(np.nanmax(c["cs_age_ms"][w]), 0)
      e["stalled"] = bool(e["cs_age_max_ms"] is not None and e["cs_age_max_ms"] > STALL_MS)
    else:
      e["cs_age_max_ms"], e["stalled"] = None, None
    eps.append(e)

  # Re-press: the next takeover's press this long after this one's release.
  for k, e in enumerate(eps):
    e2 = eps[k + 1] if k + 1 < len(eps) else None
    gap = (e2["mono_s"] - (e["mono_s"] + e["hold_s"])) if e2 is not None else None
    e["repress_after_s"] = _r(gap, 2) if gap is not None and gap <= REPRESS_LATE_S[1] else None
    e["repress"] = bool(gap is not None and REPRESS_S[0] <= gap < REPRESS_S[1])
    e["repress_late"] = bool(gap is not None and REPRESS_LATE_S[0] <= gap < REPRESS_LATE_S[1])
    gd = e.get("release_gap_deg")
    e["flags"] = [f for f, on in (
      ("FLICKER", bool(e.get("fault_in_press"))),
      ("SNAPBACK", e["repress"]),
      ("GAP", gd is not None and abs(gd) > GAP_FLAG_DEG and e["v_release"] is not None and e["v_release"] < GAP_FLAG_V),
      ("NEAR-CUT", (e.get("near_cut_held_s") or 0.0) > NEAR_CUT_HOLD_S)) if on]

  def med(key, sel=lambda e: True):
    x = [e[key] for e in eps if sel(e) and e.get(key) is not None]
    return _r(np.median(x), 2) if x else None

  rel = [e for e in eps if e["release_class"]]
  summary = {
    "count": len(eps),
    "short": sum(e["tag"] == "short grab" for e in eps), "long": sum(e["tag"] == "long hold" for e in eps),
    "blinker": sum(e["blinker"] for e in eps), "no_blinker": sum(not e["blinker"] for e in eps),
    "lanes_usable": sum(e["lanes_ok"] for e in eps),
    "releases": len(rel),
    "repress": sum(e["repress"] for e in eps), "repress_late": sum(e["repress_late"] for e in eps),
    "fault_flicker": sum(bool(e.get("fault_flicker_n")) for e in eps),
    "near_cut": sum((e.get("near_cut_s") or 0) > 0 for e in eps),
    "flags": {f: sum(f in e["flags"] for e in eps) for f in ("FLICKER", "SNAPBACK", "GAP", "NEAR-CUT")},
    "median_release_overshoot_deg": med("release_overshoot_deg"),
    "median_back_on_plan_s": med("back_on_plan_s"),
    # Each drift median beside how many takeovers it stands on (James: 3 must never read like 80). Takeovers with a
    # blinker are lane changes, left out of both counts.
    **{f"median_drift_{s_:g}s_m": med(f"drift_{s_:g}s_m", lambda e: not e["blinker"]) for s_ in DRIFT_AT_S},
    **{f"drift_{s_:g}s_measurable": f"{sum(e[f'drift_{s_:g}s_m'] is not None for e in eps if not e['blinker'])} / "
                                    f"{sum(not e['blinker'] for e in eps)}" for s_ in DRIFT_AT_S},
    "definition": (f"Start: raw carState.steeringPressed rises or |steeringTorque| > {TAKEOVER_TQ_START:g}. Release: "
                   f"|steeringTorque| < {TAKEOVER_TQ_RELEASE:g} for {TAKEOVER_RELEASE_HOLD_S:g} s. Wheel error is "
                   "carState.steeringAngleDeg - pidState.steeringAngleDesiredDeg (the plan is the reference; the "
                   f"driver's own target is unknown). Drift is lane offset toward the push, unwrapped across lane "
                   f"changes, and None unless, from the press to the end of that window, both lane lines are above "
                   f"{LANES_OK_PROB:g} for {LANES_OK_FRAC:.0%} of frames and neither stays under {LANES_LOST_PROB:g} longer "
                   f"than {LANES_LOST_S:g} s in a row; lanes_ok is the same test from press to release. lane_prob_min "
                   "and lane_ok_frac (share of frames with both lines above "
                   f"{LANES_OK_PROB:g}) cover press to release + "
                   f"{DRIFT_AT_S[-1]:g} s. lane_press_m / lane_release_m / lane_press_3s_m are gated the same way. releases = grabs above "
                   f"{RELEASE_CLASS_V:g} m/s held under {RELEASE_CLASS_MAX_S:g} s. Swing, overshoot and settle are "
                   "None when openpilot was not steering within 0.5 s of the release (lat_active_after). lane_press_m / "
                   "lane_release_m / lane_press_3s_m: position from the centre of the lane at the press (+ = left), "
                   "limited road evidence, never pass/fail. lateral_controller / git_commit: what drove; takeovers "
                   "under different controllers are not comparable. Kevin's turn-fight numbers: v_release; turn = |ang_des| > "
                   f"{TURN_ANG_DES:g} deg at release; release_gap_deg = ang_des - ang_act at release (signed); "
                   "lat_out_release = |pidState.output|; takeback_rate_peak = the largest |least-squares slope| of lat_out "
                   f"over {2 * SLOPE_HALF_S:g} s windows in the {TAKEBACK_WINDOW_S:g} s after release (per s); t90_s = release "
                   f"to 90% of lat_out's settled value (median over release + {T90_SETTLE_S[0]:g}-{T90_SETTLE_S[1]:g} s; None "
                   f"when it moves less than {T90_MIN_CHANGE:g} or the driver presses again first); repress = the next press "
                   f"{REPRESS_S[0]:g}-{REPRESS_S[1]:g} s after release (repress_late {REPRESS_LATE_S[0]:g}-{REPRESS_LATE_S[1]:g} s, "
                   "report only); fault_flicker_n / _ms = steerFaultTemporary on, or latActive dropping, between press and "
                   "release; ang_des_step_max_dps = the largest frame-to-frame ang_des step during the press, per s "
                   "(the target re-seed); i_press_min = lat_i's lowest during the press, beside i_press; override_cut_s = "
                   "latActive with raw steeringPressed (Honda sets it from |steeringTorque| against the effective "
                   f"override threshold); near_cut_s = {NEAR_CUT_TQ[0]:g} <= |steeringTorque| <= {NEAR_CUT_TQ[1]:g} "
                   "without steeringPressed; near_cut_held_s = its longest single run. flags (Kevin's live flags): "
                   "FLICKER = steerFaultTemporary between press and release; SNAPBACK = repress; GAP = |release_gap_deg| > "
                   f"{GAP_FLAG_DEG:g} under {GAP_FLAG_V:g} m/s (10 mph); NEAR-CUT = near_cut_held_s > {NEAR_CUT_HOLD_S:g} s."),
  }
  return {"episodes": eps, "summary": summary}


# =====================================================================================================
# Radar / longitudinal moments
# =====================================================================================================

def lead_snapshot(c, i):
  src = int(round(np.nan_to_num(c["lead_src"][i]))) if "lead_src" in c else 0
  if src <= 0:
    return None
  snap = {"d": _r(c["lead_d"][i], 1), "v": _r(c["lead_v"][i], 1), "src": "radar" if src == 1 else "camera"}
  for key, name, n in (("lead_id", "track_id", 0), ("lead_vrel", "vrel", 2), ("lead_a", "a", 2), ("lead_prob", "prob", 2),
                       ("lead_y", "y", 2), ("lead_vrr", "vrel_range", 2)):
    if has(c, key):
      val = _r(c[key][i], n)
      snap[name] = int(val) if (n == 0 and val is not None) else val
  return snap


def long_moments(c, t0=None, cap=None):
  """Bob's moment list. Braking moments trigger on the plan (aTarget), never on aEgo alone; both are reported."""
  t = c["t"]
  n = len(t)
  if n < 2:
    return []
  t0 = t[0] if t0 is None else t0
  dt = _dt(t)
  v = np.nan_to_num(c["v"])
  plan = np.nan_to_num(c["long_des"])
  a_ego = np.nan_to_num(c["long_act"])
  on = _b(c, "long_active")
  src = np.nan_to_num(c["lead_src"]) if "lead_src" in c else np.zeros(n)
  lead_on = src > 0.5
  d = np.nan_to_num(c["lead_d"]) if "lead_d" in c else np.zeros(n)
  exp = c.get("exp_mode")
  win = max(1, int(round(MERGE_S / dt)))
  out = []

  def base(kind, i, **kw):
    e = {"kind": kind, "t": round(float(t[i] - t0), 1), "mono_s": round(float(t[i]), 3), "v": _r(v[i], 1),
         "lead": lead_snapshot(c, i)}
    # selfdriveState.experimentalMode: experimental active right now. Under Conditional Experimental / Chill the planner
    # switches it by itself, so it is not the driver's setting (that is in the tune snapshot: ExperimentalMode,
    # ConditionalExperimental, ConditionalChill).
    if exp is not None and np.isfinite(exp[i]):
      e["experimental_active"] = bool(exp[i] > 0.5)
    e.update(kw)
    return e

  def add(kind, idx, fn):
    kept = [fn(i) for i in idx]
    kept = [e for e in kept if e is not None]
    out.extend(kept[:cap] if cap else kept)

  def brake(i):
    j = slice(i, min(n, i + win))
    k = i + int(np.argmin(plan[j]))
    return base("hard_brake" if plan[k] < BRAKE_HARD else "firm_brake", i, plan_min=_r(plan[k], 2),
                a_min=_r(np.min(a_ego[j]), 2), peak_t=round(float(t[k] - t0), 1), lead_at_peak=lead_snapshot(c, k),
                gas_after=bool(np.any(_b(c, "gas_pressed")[j])))
  add("brake", _starts(on & (plan < BRAKE_LIST), t), brake)

  gas = _b(c, "gas_pressed") & _b(c, "enabled")
  hold = max(1, int(round(GAS_BRAKE_HOLD_S / dt)))

  def gas_brake(i):
    k = slice(max(0, i - hold), i)
    if i - hold < 0 or not (np.all(on[k]) and np.all(plan[k] < GAS_BRAKE_PLAN)):
      return None
    return base("gas_during_brake", i, plan_min=_r(np.min(plan[max(0, i - 2 * hold):i]), 2), lead=lead_snapshot(c, i - 1))
  add("gas", _starts(gas, t), gas_brake)

  prev_on = np.concatenate([[False], lead_on[:-1]])
  prev_d = np.concatenate([[0.0], d[:-1]])
  moving = v > LEAD_VANISH_V   # stopped in traffic, the camera lead flickers on and off at a few metres
  if has(c, "lead_y"):
    y = np.abs(c["lead_y"])
    in_lane = ~(y >= LEAD_IN_LANE_Y)                    # NaN y (not recorded) is not gated
    prev_in_lane = np.concatenate([[True], in_lane[:-1]])
  else:
    in_lane = prev_in_lane = np.ones(n, dtype=bool)
  hold_n = max(1, int(round(LEAD_HOLD_S / dt)))

  def holds(i, state):
    w = lead_on[i:i + hold_n]
    return len(w) == hold_n and bool(np.all(w == state))

  # Bob: every appear / vanish needs the car close and in (or next to) our lane; a far distance drop is a lead_jump.
  appear = lead_on & (~prev_on | (prev_d - d > LEAD_JUMP_D)) & (d < LEAD_APPEAR_D) & in_lane & moving
  jump = lead_on & prev_on & (prev_d - d > LEAD_JUMP_D) & (d >= LEAD_APPEAR_D) & in_lane & moving
  vanish = ~lead_on & prev_on & (prev_d < LEAD_VANISH_D) & prev_in_lane & moving
  appear[0] = jump[0] = vanish[0] = False
  ups = [(i, "appear") for i in _starts(appear, t, 0.0)]
  downs = [(i, "vanish") for i in _starts(vanish, t, 0.0)]
  ev = sorted(ups + downs)
  flick, used = [], set()
  for k, (i, kind) in enumerate(ev):
    if k in used:
      continue
    if k + 1 < len(ev) and ev[k + 1][1] != kind and t[ev[k + 1][0]] - t[i] < LEAD_FLICKER_S:
      used.update((k, k + 1))
      flick.append(i)
  ev = [(i, kind) for k, (i, kind) in enumerate(ev) if k not in used and holds(i, kind == "appear")]
  add("appear", _starts(np.isin(np.arange(n), [i for i, kd in ev if kd == "appear"]), t, 1.0),
      lambda i: base("lead_appeared_close", i, d_before=_r(prev_d[i], 1) if prev_on[i] else None))
  add("vanish", _starts(np.isin(np.arange(n), [i for i, kd in ev if kd == "vanish"]), t, 1.0),
      lambda i: base("lead_vanished_close", i, lead=lead_snapshot(c, i - 1)))
  add("flicker", _starts(np.isin(np.arange(n), flick), t, 1.0),
      lambda i: base("lead_flicker", i, lead=lead_snapshot(c, i if lead_on[i] else i - 1)))
  add("jump", _starts(jump, t, 1.0), lambda i: base("lead_jump", i, d_before=_r(prev_d[i], 1)))
  if has(c, "lead_id"):
    # radarTrackId, -1 on a camera-only lead. A swap is radar to radar (both >= 0, different, lead kept, distance
    # within TRACK_SWAP_D); a handoff to or from the camera is radar_acquired / radar_lost (Bob).
    ids = np.where(np.isfinite(c["lead_id"]), c["lead_id"], -1.0)
    prev_id = np.concatenate([[ids[0]], ids[:-1]])
    kept = lead_on & prev_on & (np.abs(d - prev_d) < TRACK_SWAP_D) & (ids != prev_id)
    swap = kept & (ids >= 0) & (prev_id >= 0)
    add("swap", _starts(swap, t, 1.0), lambda i: base("track_id_swap", i, id_before=int(prev_id[i]), id_after=int(ids[i])))
    add("acquired", _starts(kept & (ids >= 0) & (prev_id < 0), t, 1.0),
        lambda i: base("radar_acquired", i, id_after=int(ids[i])))
    add("lost", _starts(kept & (ids < 0) & (prev_id >= 0), t, 1.0),
        lambda i: base("radar_lost", i, id_before=int(prev_id[i]), lead=lead_snapshot(c, i - 1)))
  add("nolead", _starts(on & (plan < NO_LEAD_BRAKE) & ~lead_on, t),
      lambda i: base("brake_no_lead", i, plan_min=_r(np.min(plan[i:i + win]), 2)))
  add("camera", _starts(on & (plan < CAMERA_BRAKE) & (np.round(src) == 2), t),
      lambda i: base("camera_only_brake", i, plan_min=_r(np.min(plan[i:i + win]), 2)))

  half = max(1, int(round(0.5 / dt)))

  def driver_brake(i):
    k = slice(max(0, i - half), i)
    if i == 0 or not np.any(on[k]) or np.min(plan[k]) <= DRIVER_BRAKE_PLAN:
      return None
    return base("driver_brake_override", i, plan_min=_r(np.min(plan[k]), 2), lead=lead_snapshot(c, i - 1))
  add("driver", _starts(_b(c, "brake_pressed"), t), driver_brake)
  out.extend(_bob_moments(c, t, t0, v, plan, on, lead_on, d, base, cap))
  out.sort(key=lambda e: e["t"])
  return out


def lat_moments(c, t0=None, cap=None):
  """James's lateral moments: fault_flicker, release_snap, hwy_inside_cut and hwy_wiggle."""
  t = c["t"]
  n = len(t)
  if n < 2:
    return []
  t0 = t[0] if t0 is None else t0
  v = np.nan_to_num(c["v"])
  lat = _b(c, "lat_active")
  out = []

  def base(kind, i, **kw):
    e = {"kind": kind, "t": round(float(t[i] - t0), 1), "mono_s": round(float(t[i]), 3), "v": _r(v[i], 1)}
    e.update(kw)
    return e

  def add(idx, fn):
    kept = [e for e in (fn(*x) if isinstance(x, tuple) else fn(x) for x in idx) if e is not None]
    out.extend(kept[:cap] if cap else kept)

  def val(name, i, k=2):
    return _r(_col(c, name, n)[i], k)

  pressed = _b(c, "steer_pressed")
  tq = _col(c, "steer_tq", n)
  if has(c, "fault_t"):
    f = _b(c, "fault_t")
    was = np.concatenate([[False], lat[:-1]])
    for a, b in _runs_of(f):
      if a == 0 or not (lat[a] or was[a]):
        continue
      if cap and sum(e["kind"] == "fault_flicker" for e in out) >= cap:
        break
      out.append(base("fault_flicker", a, fault_s=_r(t[min(b, n - 1)] - t[a], 2), steer_pressed=bool(pressed[a]),
                      steer_tq_abs=_r(abs(tq[a]), 0), ang=val("ang_act", a, 1), fault_permanent=bool(_b(c, "fault_p")[a])))

  if has(c, "tq_out") and has(c, "steer_pressed"):
    y = _col(c, "tq_out", n)
    fall = np.zeros(n, dtype=bool)
    fall[1:] = pressed[:-1] & ~pressed[1:] & lat[1:]
    rise = np.flatnonzero(pressed[1:] & ~pressed[:-1]) + 1

    def snap(r):
      k = int(np.searchsorted(t, t[r] + SNAP_WINDOW_S))
      slopes = [(abs(sl), j) for j in range(r, k) if (sl := _ls_slope(t, y, j, SLOPE_HALF_S)) is not None]
      if not slopes:
        return None
      peak, j = max(slopes)
      nxt = rise[rise > r]
      again = len(nxt) > 0 and t[nxt[0]] - t[r] < SNAP_REPRESS_S
      return base("release_snap", r, tq_out_rate_peak=_r(peak, 2), peak_after_s=_r(t[j] - t[r], 2),
                  repress=bool(again), repress_after_s=_r(t[nxt[0]] - t[r], 2) if again else None,
                  ang=val("ang_act", r, 1), ang_des=val("ang_des", r, 1))
    add(_starts(fall, t, 1.0), snap)

  hwy = lat & (v >= HWY_V) & ~after_release(c) & ~_b(c, "blinker") & ~(np.nan_to_num(_col(c, "lane_change", n)) > 0.5)
  dem = _col(c, "lat_des", n)
  if has(c, "lane_off") and has(c, "ang_act") and has(c, "lat_des"):
    # Curve side from the wheel angle less liveParameters' offset (+ = left, James): at 25 m/s a 0.5 m/s^2 curve is
    # ~1.9 deg of wheel and the offset sat at -0.7 to -1.3 deg on 294/296/297, so the raw angle can name the wrong side.
    # Under CURVE_SIDE_MIN_DEG the side is unknown and the frame is skipped. lane_off is + for the car left of centre,
    # so + here is inside.
    side_ang = np.nan_to_num(c["ang_act"]) - np.nan_to_num(_col(c, "ang_off", n))
    side = np.where(np.abs(side_ang) >= CURVE_SIDE_MIN_DEG, np.sign(side_ang), 0.0)
    inside = side * c["lane_off"]
    lane_ok = np.nan_to_num(_col(c, "lane_prob", n), nan=1.0) > LANE_PROB_MIN
    cut = hwy & lane_ok & (np.abs(np.nan_to_num(dem)) >= INSIDE_CUT_DEMAND) & (np.nan_to_num(inside) > INSIDE_CUT_M)
    add([x for x in _runs_of(cut) if t[min(x[1], n - 1)] - t[x[0]] >= INSIDE_CUT_S],
        lambda a, b: base("hwy_inside_cut", a, inside_max_m=_r(np.nanmax(inside[a:b]), 2), for_s=_r(t[min(b, n - 1)] - t[a], 1),
                          lat_des=val("lat_des", a), ang=val("ang_act", a, 1), lane_w=val("lane_w", a),
                          ang_off=val("ang_off", a), turn="left" if side[a] > 0 else "right"))

  if has(c, "tq_out") and has(c, "lat_des"):
    y = np.nan_to_num(_col(c, "tq_out", n))
    ok = hwy & (np.abs(np.nan_to_num(dem, nan=np.inf)) < WIGGLE_DEMAND)
    starts = []
    for a, b in _runs_of(ok):
      big = [j for j in range(a, b) if abs(y[j]) > WIGGLE_TQ]    # a swing counts once it passes the floor
      cross = [j for p, j in zip(big[:-1], big[1:], strict=True) if np.sign(y[j]) != np.sign(y[p])]
      k = WIGGLE_CROSSINGS - 1
      starts += [cross[m] for m in range(len(cross) - k) if t[cross[m + k]] - t[cross[m]] <= WIGGLE_S]

    def wiggle(i):
      k = int(np.searchsorted(t, t[i] + WIGGLE_S))
      return base("hwy_wiggle", i, tq_out_pp=_r(np.max(y[i:k]) - np.min(y[i:k]), 3), lat_des=val("lat_des", i),
                  ff=val("ff", i, 3), ff_w=val("ff_w", i), lat_p=val("lat_p", i, 3), lat_f=val("lat_f", i, 3),
                  lane_off=val("lane_off", i))
    add(_starts(np.isin(np.arange(n), starts), t), wiggle)
  out.sort(key=lambda e: e["t"])
  return out


def vrel_gap_stats(c):
  """|vRel - vRelRangeDerived| over moving radar-lead frames (Bob): the spread behind vrel_disagree's threshold."""
  if not (has(c, "lead_vrel") and has(c, "lead_vrr")):
    return None
  radar = np.round(np.nan_to_num(c["lead_src"])) == 1 if "lead_src" in c else np.zeros(len(c["t"]), dtype=bool)
  g = np.abs(c["lead_vrel"] - c["lead_vrr"])[radar & (np.nan_to_num(c["v"]) > LEAD_VANISH_V)]
  g = g[np.isfinite(g)]
  if not len(g):
    return None
  return {"frames": len(g), "p50": _r(np.percentile(g, 50), 2), "p90": _r(np.percentile(g, 90), 2),
          "over_threshold_pct": _r(100.0 * np.mean(g > VREL_DISAGREE), 1)}


def _col(c, name, n):
  x = c.get(name)
  return np.full(n, np.nan) if x is None or len(x) != n else x


def _bob_moments(c, t, t0, v, plan, on, lead_on, d, base, cap):
  """Bob's 2026-09-29 moments: planner switching, radar lead quality, and the gas learner. Each is None-safe: a
  column that was not recorded gives no moments of that kind."""
  n = len(t)
  out = []

  def add(idx, fn):
    kept = [e for e in (fn(*x) if isinstance(x, tuple) else fn(x) for x in idx) if e is not None]
    out.extend(kept[:cap] if cap else kept)

  def val(name, i, k=2):
    return _r(_col(c, name, n)[i], k)

  standstill = _b(c, "standstill") | (v < 0.3)

  def mode(i):
    return {"red_light": bool(_b(c, "red_light")[i]) if has(c, "red_light") else None, "road_curv": val("road_curv", i, 4)}

  if has(c, "exp_mode"):
    x = _col(c, "exp_mode", n)
    ok = np.isfinite(x)
    flips = [i for i in range(1, n) if ok[i] and ok[i - 1] and (x[i] > 0.5) != (x[i - 1] > 0.5)]
    # One moment per burst: flips each under EXP_FLIP_S after the one before (route 297 had bursts of 0.05 s flips).
    bursts = []
    for p, i in zip(flips[:-1], flips[1:], strict=True):
      if t[i] - t[p] >= EXP_FLIP_S:
        continue
      if bursts and bursts[-1][1] == p:
        bursts[-1][1], bursts[-1][2] = i, bursts[-1][2] + 1
      else:
        bursts.append([p, i, 2])
    # Bob: stopped bursts are a separate CEM issue (standstill), and a burst with long control off the whole time never
    # reached the car (long_active False: kept in the analysis and the CSVs, left out of the drive's list). The cap
    # applies to each group, so the off bursts never crowd the listed ones out.
    ff = [base("exp_flipflop", p, flips=k, burst_s=_r(t[i] - t[p], 2), experimental_after=bool(x[i] > 0.5),
               standstill=int(standstill[p]), long_active=bool(np.any(on[p:i + 1])), **mode(p)) for p, i, k in bursts]
    for grp in ([e for e in ff if e["long_active"]], [e for e in ff if not e["long_active"]]):
      out.extend(grp[:cap] if cap else grp)

  if has(c, "red_light"):
    def red(i):
      k = int(np.searchsorted(t, t[i] + RED_LIGHT_WINDOW_S))
      if k >= n:     # the drive ended inside the window: not judged
        return None
      if np.min(v[i:k + 1]) < RED_LIGHT_STOP_V:
        return None
      return base("false_red_light", i, v_min_10s=_r(np.min(v[i:k + 1]), 1), plan_min_10s=_r(np.min(plan[i:k + 1]), 2),
                  road_curv=val("road_curv", i, 4), stop_len=val("stop_len", i, 1),
                  forcing_stop=bool(_b(c, "forcing_stop")[i]) if has(c, "forcing_stop") else None)
    add(_starts(_b(c, "red_light"), t, RED_LIGHT_WINDOW_S), red)   # the flag flickers: one moment per window

  if has(c, "long_des"):
    ld = _col(c, "long_des", n)
    step = np.zeros(n, dtype=bool)
    step[1:] = on[1:] & on[:-1] & (np.abs(np.diff(ld)) > ATARGET_STEP)   # NaN compares False
    add(_starts(step, t, 1.0), lambda i: base("atarget_step", i, a_before=_r(ld[i - 1], 2), a_after=_r(ld[i], 2),
                                            plan_src=val("plan_src", i, 0), cl_cap=val("cl_cap", i)))

  if has(c, "cl_cap"):
    cap_x = _col(c, "cl_cap", n)
    engaged = np.isfinite(cap_x) & (np.abs(np.nan_to_num(cap_x)) > 1e-3)
    prev_zero = np.concatenate([[False], np.isfinite(cap_x[:-1]) & ~engaged[:-1]])
    add(_starts(engaged & prev_zero, t),
        lambda i: base("close_lead_cap", i, cl_cap=_r(cap_x[i], 2), a_target=_r(plan[i], 2), geo_acc=val("geo_acc", i)))

  radar = lead_on & (np.round(np.nan_to_num(c["lead_src"]) if "lead_src" in c else np.zeros(n)) == 1)
  if has(c, "lead_meas"):
    coast = radar & (d < COAST_NEAR_D) & np.isfinite(c["lead_meas"]) & ~_b(c, "lead_meas")
    add(_held_runs(coast, t, COAST_NEAR_S),
        lambda a, b, dur: base("radar_coast_near", a, coast_s=_r(dur, 2), d_min=_r(np.min(d[a:b]), 1)))
  if has(c, "lead_vrel") and has(c, "lead_vrr"):
    gap = np.abs(c["lead_vrel"] - c["lead_vrr"])
    # Moving only: stopped behind a stopped car the range-derived speed is noise (route 297: 9 m/s gaps at 0 m/s).
    add(_held_runs(radar & (v > LEAD_VANISH_V) & (np.nan_to_num(gap) > VREL_DISAGREE), t, VREL_DISAGREE_S),
        lambda a, b, dur: base("vrel_disagree", a, gap_max=_r(np.max(gap[a:b]), 2), for_s=_r(dur, 2)))
  if has(c, "mlead_x") and has(c, "mlead_p"):
    dm = np.abs(d - np.nan_to_num(c["mlead_x"], nan=np.inf))
    lim = np.maximum(MODEL_DISAGREE_D[0], MODEL_DISAGREE_D[1] * d)
    far = radar & (np.nan_to_num(c["mlead_p"]) > MODEL_PROB_MIN) & np.isfinite(dm) & (dm > lim)
    add(_held_runs(far, t, MODEL_DISAGREE_S),
        lambda a, b, dur: base("radar_vs_model", a, model_d=val("mlead_x", a, 1), d_gap_max=_r(np.max(dm[a:b]), 1),
                               for_s=_r(dur, 2)))

  if has(c, "v_cruise"):
    vc = _col(c, "v_cruise", n)
    set_ok = np.isfinite(vc) & (vc > 0) & (vc < V_CRUISE_UNSET)
    over = on & ~lead_on & set_ok & (v > np.nan_to_num(vc) / 3.6 + OVERSPEED_MS)
    add(_held_runs(over, t, OVERSPEED_S),
        lambda a, b, dur: base("overspeed_no_lead", a, v_cruise_ms=_r(vc[a] / 3.6, 2), over_max=_r(np.max(v[a:b] - vc[a:b] / 3.6), 2),
                               for_s=_r(dur, 1), pitch=val("pitch", a, 3), gl_gf=val("gl_gf", a, 3), gl_wf=val("gl_wf", a, 3),
                               a_target=_r(plan[a], 2)))

  if has(c, "gl_gf_raw"):
    raw = _col(c, "gl_gf_raw", n)
    clip = np.nan_to_num(raw) >= GF_CLIP
    # Rising edge only, after at least GF_REARM_S under the clip: a factor sitting on the clip dithers across it.
    edges = [i for i in _starts(clip, t, 0.0) if not np.any(clip[int(np.searchsorted(t, t[i] - GF_REARM_S)):i])]
    add(edges,
        lambda i: base("gf_clip", i, gl_gf_raw=_r(raw[i], 3), gl_gf=val("gl_gf", i, 3), gl_err=val("gl_err", i, 3),
                       pitch=val("pitch", i, 3)))
  return out


# =====================================================================================================
# Lateral detail per band (James)
# =====================================================================================================

def _stats(x):
  x = x[np.isfinite(x)]
  if len(x) < 20:
    return None
  return {"n_s": None, "median": _r(np.median(x), 3), "p10": _r(np.percentile(x, 10), 3),
          "p90": _r(np.percentile(x, 90), 3), "pct_over_0_3m": _r(100.0 * np.mean(np.abs(x) > LANE_OFF_NOTABLE), 1)}


def lateral_detail(c, lateral_delay=None):
  t = c["t"]
  if len(t) < 2:
    return {"status": "no_data"}
  dt = _dt(t)
  v = np.nan_to_num(c["v"])
  eng = _b(c, "lat_active") & ~after_release(c) & (v > LAT_MIN_V)
  demand = np.nan_to_num(c["lat_des"])
  straight = np.abs(demand) < STRAIGHT_DEMAND
  curve = np.abs(demand) > CURVE_DEMAND
  angles = has(c, "ang_des") and np.any(_b(c, "ang_ok"))
  err = np.abs(c["ang_act"] - c["ang_des"]) if angles else None
  out = {"status": "ok", "engaged_s": round(float(np.count_nonzero(eng) * dt), 1), "bands": [],
         "sample_dt_s": round(dt, 3),
         "notes": [("pidState.p is the P before the per-band p_scale (1.25 / 1.00 / 1.25 on LatControlClarityEps), and the "
                    "output is clipped and low-pass filtered, so p + i + f is not the output."),
                   f"Lane offsets under {LANE_DEADBAND * 100:.0f} cm are inside lane centring's deadband.",
                   "Frames with the wheel pressed (raw steeringPressed) and the first second after a release are left out."]}
  lane = has(c, "lane_off") and has(c, "lane_prob")
  if lane:
    lane_ok = eng & (np.nan_to_num(c["lane_prob"]) > LANE_PROB_MIN) & ~_b(c, "blinker")
    out["lane_width_median_m"] = _r(np.nanmedian(c["lane_w"][lane_ok]), 2) if has(c, "lane_w") and np.any(lane_ok) else None
  ff = has(c, "ff_w")
  out_ok = has(c, "lat_out")
  for lo, hi, name in BANDS:
    b = eng & (v >= lo) & (v < hi)
    if np.count_nonzero(b) * dt < 10.0:
      continue
    row = {"band": name, "engaged_s": round(float(np.count_nonzero(b) * dt), 1)}
    if lane:
      lb = b & lane_ok
      off = c["lane_off"]
      st = _stats(off[lb & straight])
      if st:
        st["n_s"] = round(float(np.count_nonzero(lb & straight) * dt), 1)
      # lat_des (desiredLateralAccel) is + for a RIGHT curve, lane_off + for the car LEFT of centre: the inside is
      # -sign(lat_des) (James, 290-294: corr(desiredCurvature, steeringAngleDeg) = -0.99).
      cv = _stats((-np.sign(demand) * off)[lb & curve])
      if cv:
        cv["n_s"] = round(float(np.count_nonzero(lb & curve) * dt), 1)
      row["lane_straight"] = st                 # + = car left of centre
      row["lane_curve_toward_inside"] = cv      # + = car toward the inside of the curve
      row["lane_width_m"] = _r(np.nanmedian(c["lane_w"][lb]), 2) if has(c, "lane_w") and np.any(lb) else None
    if err is not None:
      row["angle_err_straight"] = {"p50": _r(_pct(err[b & straight], 50), 2), "p95": _r(_pct(err[b & straight], 95), 2)}
      row["angle_err_curve"] = {"p50": _r(_pct(err[b & curve], 50), 2), "p95": _r(_pct(err[b & curve], 95), 2)}
    if ff:
      w = np.nan_to_num(c["ff_w"])
      row["ff_active_pct"] = _r(100.0 * np.mean(w[b] > 0), 1)
      if out_ok:
        a = b & (w > 0)
        den = np.mean(np.abs(np.nan_to_num(c["lat_out"][a]))) if np.any(a) else 0.0
        row["ff_share"] = _r(np.mean(np.abs(np.nan_to_num(c["lat_f"][a]))) / den, 2) if den > 1e-6 else None
    row["saturated_pct"] = _r(100.0 * np.mean(_b(c, "lat_sat")[b]), 1)
    row["i_abs_p95"] = _r(_pct(np.abs(c["lat_i"][b]), 95), 4) if has(c, "lat_i") else None
    out["bands"].append(row)
  # Tight turns: turn-in lag (desired crosses TIGHT_DEG until the wheel does, same side) and the peak error.
  if angles:
    des, act = np.nan_to_num(c["ang_des"]), np.nan_to_num(c["ang_act"])
    ok = _b(c, "lat_active") & ~after_release(c)
    hold = held(c)
    turns = []
    for i in _starts(ok & (np.abs(des) > TIGHT_DEG), t, 2.0):
      side = np.sign(des[i])
      j = i
      while j < len(t) and t[j] - t[i] < 3.0 and side * act[j] < TIGHT_DEG and ok[j]:
        j += 1
      k = i
      while k < len(t) and np.abs(des[k]) > TIGHT_DEG * 0.5 and ok[k]:
        k += 1
      lag = float(t[j] - t[i]) if j < len(t) and side * act[j] >= TIGHT_DEG else None
      turns.append({"t": round(float(t[i] - t[0]), 1), "mono_s": round(float(t[i]), 3), "v": _r(v[i], 1),
                    "turn_in_lag_s": _r(lag, 2), "peak_err_deg": _r(np.max(np.abs(act[i:k + 1] - des[i:k + 1])), 1),
                    # James: the share of -10 s .. +5 s around the turn-in the driver was holding the wheel (0 = clean).
                    "held_frac": _r(np.mean(hold[_at(t, t[i] - 10.0):_at(t, t[i] + 5.0) + 1]), 2)})
    lags = [x["turn_in_lag_s"] for x in turns if x["turn_in_lag_s"] is not None]
    out["tight_turns"] = {"count": len(turns), "median_turn_in_lag_s": _r(np.median(lags), 2) if lags else None,
                          "lateral_delay_s": _r(lateral_delay, 3),
                          "median_peak_err_deg": _r(np.median([x["peak_err_deg"] for x in turns]), 1) if turns else None,
                          "turns": turns}
  return out
