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

Sign conventions: wheel angle, steeringTorque and lat_des are + = left. lane_off is the car's offset from the lane
centre, + = car left of centre (modelV2 laneLines y is + = right, so the centre's y at x=0 is the car's offset to the
left). "Toward the push" is + in the direction the driver pushed the wheel.

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
    if i_ok:
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
    "median_release_overshoot_deg": med("release_overshoot_deg"),
    "median_back_on_plan_s": med("back_on_plan_s"),
    "median_drift_3s_m": med("drift_3s_m", lambda e: e["lanes_ok"] and not e["blinker"]),
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
                   "under different controllers are not comparable."),
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
  out.sort(key=lambda e: e["t"])
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
      cv = _stats((np.sign(demand) * off)[lb & curve])
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
