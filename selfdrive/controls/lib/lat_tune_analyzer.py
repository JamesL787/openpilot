"""Offline adaptive P trim for modified-EPS Honda lateral PID (item 116 rules, FLM-style trials).

Pure module: no Params, no Flask. Callers are the Galaxy workspace, the CLI and tests.
Frames come from rlogs (frames_from_log). One trial = one step per speed band, bounded 0.85..1.15.
The bands are StarPilot's PID bands (LatControlPID._lat_pid_scale_banded): hard steps at 25 and 50 mph,
each with its own LatPScale*/LatIScale*/LatFScale* percent. The rules propose only P (item 116); I/F are carried.
The closed-loop sim step (tools/lateral/lat_tune_sim.py) may replace a band's proposal with a P/I pair.
"""
import json
import math
import zlib
from collections import deque

MPH_TO_MS = 0.44704
# (name, low mph, high mph); v < 25 mph -> LowSpeed, v < 50 mph -> Standard, else Highway.
BANDS = (("LowSpeed", 0.0, 25.0), ("Standard", 25.0, 50.0), ("Highway", 50.0, None))
BAND_NAMES = tuple(b[0] for b in BANDS)
_BAND_EDGES = tuple(b[2] * MPH_TO_MS for b in BANDS[:-1])
PCT_STEP = 5          # Galaxy step for Lat*Scale*
PCT_MIN, PCT_MAX = 0, 500

STEP = 0.05          # factor grid; the smallest step
MAX_STEP = 0.15      # largest step per trial (owner, 2026-09-24: "up to 15 % per trial")
FACTOR_MIN = 0.85
FACTOR_MAX = 1.15
MAX_NEIGHBOUR_GAP = 0.15
MIN_MINUTES = 3.0
MIN_SPEED = 4.0
STRAIGHT_DEG = 3.0
CURVE_DEG = 5.0
MIN_CURVE_S = 30.0
# Curve frames split by how fast |desired| moves (over CURVE_RATE_FRAMES): >= +CURVE_RATE_DEG_S is entry
# (winding up), <= -CURVE_RATE_DEG_S is exit, the rest is steady. The angle trails the desired by
# 0.15-0.25 s on every route 262-271, so entry reads 0.72-0.86 and exit 1.00-1.21 while steady sits near
# the whole-curve ratio at 25-50 mph; below 25 mph the steady ratio is the lower one (0.68-0.90). Reported,
# not used by the rules: a low entry ratio with a good steady ratio is lag, which more P only partly fixes.
CURVE_RATE_DEG_S = 5.0
CURVE_RATE_FRAMES = 10
MIN_TRANSIENT_S = 5.0

# A straight-frame error sign change only counts once the error has crossed from >= +SIGN_HYST_DEG to
# <= -SIGN_HYST_DEG (or back). Counting every zero crossing measured the angle sensor's 0.1 deg steps, not
# weave: on 262-271 (8 routes) the 25-50 mph rate was 0.76-0.92 /s with no deadband and 0.24-0.30 /s at
# 0.15 deg; on the highway 0.64-1.58 -> 0.10-0.29. The limits below are in deadband units: 0.6 /s is twice
# the worst 25-50 mph route, 0.45 /s is 1.5x. Replay-set on those 8 routes, not on closed-loop outcomes.
SIGN_HYST_DEG = 0.15
SIGN_RATE_MAX = 0.6        # /s, straight error sign changes
SIGN_RATE_UP_MAX = 0.45    # /s, no step up above this
SIGN_SLACK = 0.05          # /s, a revert also needs this absolute rise (3 min at 0.3 /s is only ~50 changes)
CURVE_RATIO_LOW = 0.95
CURVE_RATIO_HIGH = 1.03
PRESS_RATE_UP_MAX = 1.5    # override onsets per engaged minute; no step up above this
# A driver fighting the wheel near NrdrDriverOverrideThreshold flickers steeringPressed: each press cuts the
# torque, the driver's reading drops under the threshold, the fade brings it back, and it trips again.
# Route 0000026b 32:43.7-45.2 shows seven 0.02-0.04 s presses inside one real fight; across 262-26b, 723 of
# 724 press onsets had >= 0.2 s of |torque| > 1000 within +-1 s, so short presses are not sensor noise.
# Counting every onset tripled the rate (Standard 179 onsets -> 63 fights), so onsets closer than this to
# the previous pressed frame belong to the same override.
PRESS_MERGE_FRAMES = 150   # 1.5 s at 100 Hz
OSC_GROWTH = 1.15
PRESS_GROWTH = 1.25
PRESS_SLACK = 0.2

STATE_VERSION = 2
APPLY_MODE = 2

# Manual lateral gains the factor is relative to. A change to any of them resets the learned state.
TUNING_KEYS = (
  "LatPScaleLowSpeed", "LatPScaleStandard", "LatPScaleHighway",
  "LatIScaleLowSpeed", "LatIScaleStandard", "LatIScaleHighway",
  "LatFScaleLowSpeed", "LatFScaleStandard", "LatFScaleHighway", "LatGainSchedule",
  "HondaLateralPidKpScale", "HondaLateralPidKiScale",
  "HondaCenterScale", "HondaCenterBoostThreshold", "HondaCenterBoostMinSpeed",
  "HondaTorqueLowPassFilter", "HondaLpfTauLowSpeed", "HondaLpfTauStandard", "HondaLpfTauHighway", "NrdrLatRateFF",
  "HondaOverrideTorqueScale", "HondaOverrideFadeUpSecs", "HondaOverrideFadeDownSecs",
  # Selects the rack map that turns curvature into the target wheel angle (firmware VGR table vs
  # the road-measured curve). Switching moves the centre gain ~10 % and the taper, so every angle
  # the factor was learned against changes. The paramsd-learned ratio is deliberately not here:
  # it drifts continuously, and resetting on it would mean never learning.
  "NrdrLatUseFirmwareVgr",
  # Swaps the feedforward the learned factors were fitted against.
  "NrdrLatEpsFirmwareFF",
)

_FIELDS = ("n", "n_act", "n_st", "e2_st", "sc", "n_cur", "ang_cur", "des_cur", "press",
           "n_ss", "ang_ss", "des_ss", "n_en", "ang_en", "des_en", "n_ex", "ang_ex", "des_ex")
_CURVE_PARTS = ("ss", "en", "ex")


def band_index(v_ego):
  """Band of v_ego, with the same strict < edges as _lat_pid_scale_banded."""
  for i, edge in enumerate(_BAND_EDGES):
    if v_ego < edge:
      return i
  return len(BANDS) - 1


def band_weights(v_ego):
  return ((band_index(v_ego), 1.0),)


def band_label(i):
  name, lo, hi = BANDS[i]
  return f"{name} {lo:g}-{hi:g} mph" if hi is not None else f"{name} {lo:g}+ mph"


def _fingerprint_value(v):
  """One canonical text per value, whichever side it came from. initData carries the raw stored bytes
  ("0", "0.5") but Params.get() on the device returns typed values (False, 0.5), so an un-normalised
  hash made every trial mismatch once a BOOL key such as HondaTorqueLowPassFilter was set, and force
  became the routine path. Bools and numbers become repr(float); anything else (LatGainSchedule JSON)
  stays as the stripped text."""
  if isinstance(v, bytes):
    v = v.decode("utf-8", "replace")
  if v is None:
    return ""
  if isinstance(v, bool):
    return repr(float(v))
  s = str(v).strip()
  if s.lower() in ("true", "false"):
    return repr(float(s.lower() == "true"))
  try:
    f = float(s)
  except ValueError:
    return s
  return repr(f) if math.isfinite(f) else s


# Keys added to TUNING_KEYS after routes were already hashed, with the value at which they leave the controller
# unchanged. Unset or at that value they stay out of the hash, so adding one does not re-hash every earlier route
# (which would split the pool and reset the learned state on update).
FINGERPRINT_ADDED_OFF = {"NrdrLatRateFF": repr(0.0), "NrdrLatEpsFirmwareFF": repr(0.0)}


def tuning_fingerprint(values):
  """Short hash of the manual tuning. `values` maps key -> param value (raw str/bytes, typed, or None)."""
  norm = {k: _fingerprint_value(values.get(k)) for k in TUNING_KEYS}
  parts = [f"{k}={v}" for k, v in norm.items() if not (k in FINGERPRINT_ADDED_OFF and v in ("", FINGERPRINT_ADDED_OFF[k]))]
  return f"{zlib.crc32(';'.join(parts).encode()):08x}"


def default_state(tuning=None):
  return {"version": STATE_VERSION, "bands": list(BAND_NAMES), "factor": [1.0] * len(BANDS),
          "prev": [None] * len(BANDS), "carry": [None] * len(BANDS), "drives": 0, "last": [], "tuning": tuning}


def parse_state(raw):
  try:
    if isinstance(raw, bytes):
      raw = raw.decode("utf-8")
    s = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(s, dict) or s.get("version") != STATE_VERSION or list(s.get("bands", ())) != list(BAND_NAMES):
      return default_state()
    f = [float(x) for x in s["factor"]]
    if len(f) != len(BANDS) or not all(math.isfinite(x) and FACTOR_MIN - 1e-9 <= x <= FACTOR_MAX + 1e-9 for x in f):
      return default_state()
    prev = s.get("prev") or [None] * len(BANDS)
    if len(prev) != len(BANDS):
      prev = [None] * len(BANDS)
    carry = s.get("carry") or [None] * len(BANDS)
    if len(carry) != len(BANDS):
      carry = [None] * len(BANDS)
    carry = [_clean_acc(c) for c in carry]
    tuning = s.get("tuning")
    return {"version": STATE_VERSION, "bands": list(BAND_NAMES), "factor": f, "prev": prev, "carry": carry,
            "drives": int(s.get("drives", 0)), "last": list(s.get("last", [])),
            "tuning": tuning if isinstance(tuning, str) else None}
  except (TypeError, ValueError, KeyError, AttributeError, UnicodeDecodeError):
    return default_state()


def _clean_acc(c):
  if not isinstance(c, dict):
    return None
  try:
    out = {k: float(c.get(k, 0.0)) for k in _FIELDS}
  except (TypeError, ValueError):
    return None
  return out if all(math.isfinite(v) and v >= 0 for v in out.values()) else None


class DriveStats:
  """Per-band accumulators for one drive. Plain floats so observe() stays cheap at 100 Hz."""
  def __init__(self, carry=None, tuning=None):
    self.tuning = tuning
    self.acc = [dict.fromkeys(_FIELDS, 0.0) for _ in BANDS]
    for a, c in zip(self.acc, carry or [None] * len(BANDS), strict=True):
      if c is not None:
        a.update(c)
    self.prev_sign = 0.0
    self.prev_pressed = False
    self.since_press = PRESS_MERGE_FRAMES
    self.des_hist = deque(maxlen=CURVE_RATE_FRAMES + 1)

  def observe(self, v_ego, desired_deg, angle_deg, pressed, lane_change, steer_limited):
    """Call once per engaged frame."""
    onset = pressed and not self.prev_pressed and self.since_press >= PRESS_MERGE_FRAMES
    self.prev_pressed = pressed
    self.since_press = 0 if pressed else self.since_press + 1
    if v_ego < MIN_SPEED:
      self.prev_sign = 0.0
      self.des_hist.clear()
      return
    self.des_hist.append(desired_deg)
    ws = band_weights(v_ego)
    for i, w in ws:
      a = self.acc[i]
      a["n_act"] += w
      if onset:
        a["press"] += w
    if pressed or lane_change or steer_limited:
      self.prev_sign = 0.0
      return
    err = desired_deg - angle_deg
    straight = abs(desired_deg) < STRAIGHT_DEG
    curve = abs(desired_deg) > CURVE_DEG
    # Inside the deadband the last sign is kept, so a crossing needs the full 2 x SIGN_HYST_DEG swing.
    sign = (1.0 if err >= SIGN_HYST_DEG else -1.0 if err <= -SIGN_HYST_DEG else 0.0) if straight else 0.0
    changed = straight and self.prev_sign != 0.0 and sign != 0.0 and sign != self.prev_sign
    part = "ss"
    if curve and len(self.des_hist) > CURVE_RATE_FRAMES:
      rate = (abs(desired_deg) - abs(self.des_hist[0])) / (CURVE_RATE_FRAMES * 0.01)
      part = "en" if rate >= CURVE_RATE_DEG_S else "ex" if rate <= -CURVE_RATE_DEG_S else "ss"
    for i, w in ws:
      a = self.acc[i]
      a["n"] += w
      if straight:
        a["n_st"] += w
        a["e2_st"] += w * err * err
        if changed:
          a["sc"] += w
      elif curve:
        a["n_cur"] += w
        s = 1.0 if desired_deg > 0.0 else -1.0
        a["ang_cur"] += w * angle_deg * s
        a["des_cur"] += w * abs(desired_deg)
        a["n_" + part] += w
        a["ang_" + part] += w * angle_deg * s
        a["des_" + part] += w * abs(desired_deg)
    if sign != 0.0:
      self.prev_sign = sign
    elif not straight:
      self.prev_sign = 0.0

  def has_data(self):
    return any(a["n"] > 0 for a in self.acc)

  def to_json(self):
    return json.dumps({"version": STATE_VERSION, "bands": list(BAND_NAMES), "tuning": self.tuning,
                       "acc": [{k: round(v, 4) for k, v in a.items()} for a in self.acc]}, separators=(",", ":"))

  @staticmethod
  def from_json(raw):
    try:
      if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
      d = json.loads(raw) if isinstance(raw, str) else raw
      if not isinstance(d, dict) or d.get("version") != STATE_VERSION or list(d.get("bands", ())) != list(BAND_NAMES):
        return None
      tuning = d.get("tuning")
      st = DriveStats(tuning=tuning if isinstance(tuning, str) else None)
      for a, src in zip(st.acc, d["acc"], strict=True):
        for k in _FIELDS:
          v = float(src.get(k, 0.0))
          if not math.isfinite(v) or v < 0:
            return None
          a[k] = v
      return st
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeDecodeError):
      return None


def band_metrics(a, dt=0.01):
  minutes = a["n"] * dt / 60.0
  act_min = a["n_act"] * dt / 60.0
  return {
    "min": minutes,
    "straight_rms": math.sqrt(a["e2_st"] / a["n_st"]) if a["n_st"] > 0 else None,
    "sign_rate": a["sc"] / (a["n_st"] * dt) if a["n_st"] * dt >= 10.0 else None,
    "curve_ratio": a["ang_cur"] / a["des_cur"] if a["n_cur"] * dt >= MIN_CURVE_S and a["des_cur"] > 0 else None,
    "press_rate": a["press"] / act_min if act_min > 0 else None,
    **{f"curve_ratio_{k}": _ratio(a, k, MIN_CURVE_S if k == "ss" else MIN_TRANSIENT_S, dt) for k in _CURVE_PARTS},
  }


def _ratio(a, part, min_s, dt):
  n, des = a.get("n_" + part, 0.0), a.get("des_" + part, 0.0)
  return a["ang_" + part] / des if n * dt >= min_s and des > 0 else None


def curve_step(curve_ratio):
  """Step that would bring the curve ratio to 1.0 if angle tracked P linearly, on the STEP grid, 1..3 steps."""
  need = abs(1.0 / curve_ratio - 1.0)
  return min(max(round(need / STEP) * STEP, STEP), MAX_STEP)


def update_state(state, stats, mode):
  """One drive's step. Returns the new state; `last` lists what each band did and why."""
  state = parse_state(state) if not isinstance(state, dict) else parse_state(json.dumps(state))
  f = list(state["factor"])
  prev = list(state["prev"])
  carry = [None] * len(BANDS)
  last = []
  for i, a in enumerate(stats.acc):
    m = band_metrics(a)
    k = BAND_NAMES[i]
    if m["min"] < MIN_MINUTES or m["sign_rate"] is None:
      # Too little data: nothing moves, and the data carries into the next drive (same factor).
      carry[i] = {kk: round(v, 4) for kk, v in a.items()}
      last.append(f"{k}: hold ({m['min']:.1f} min of data, carried)")
      continue
    p = prev[i]
    step = 0.0
    why = "hold"
    stepped_up = p is not None and p.get("stepped", 0.0) > 0 and mode == APPLY_MODE
    press_now = m["press_rate"] or 0.0
    undo = -p["stepped"] if stepped_up else 0.0
    if stepped_up and p.get("sign_rate") and m["sign_rate"] > max(p["sign_rate"] * OSC_GROWTH, p["sign_rate"] + SIGN_SLACK):
      step, why = undo, f"revert: sign changes {p['sign_rate']:.2f} -> {m['sign_rate']:.2f}/s after the last increase"
    elif stepped_up and p.get("press_rate") is not None and press_now > p["press_rate"] * PRESS_GROWTH + PRESS_SLACK:
      step, why = undo, f"revert: override onsets {p['press_rate']:.2f} -> {press_now:.2f}/min after the last increase"
    elif m["sign_rate"] > SIGN_RATE_MAX:
      step, why = -STEP, f"down: sign changes {m['sign_rate']:.2f}/s > {SIGN_RATE_MAX}"
    elif m["curve_ratio"] is not None and m["curve_ratio"] > CURVE_RATIO_HIGH:
      step = -curve_step(m["curve_ratio"])
      why = f"down {-step:.2f}: curve ratio {m['curve_ratio']:.3f} > {CURVE_RATIO_HIGH}"
    elif (m["curve_ratio"] is not None and m["curve_ratio"] < CURVE_RATIO_LOW and m["sign_rate"] < SIGN_RATE_UP_MAX
          and press_now < PRESS_RATE_UP_MAX):
      step = curve_step(m["curve_ratio"])
      why = f"up {step:.2f}: curve ratio {m['curve_ratio']:.3f} < {CURVE_RATIO_LOW}"
    elif m["curve_ratio"] is not None and m["curve_ratio"] < CURVE_RATIO_LOW:
      why = f"hold: curve ratio {m['curve_ratio']:.3f} low but sign changes {m['sign_rate']:.2f}/s or onsets {press_now:.2f}/min too high"
    new = min(max(f[i] + step, FACTOR_MIN), FACTOR_MAX)
    prev[i] = {"factor": f[i], "stepped": new - f[i], "sign_rate": m["sign_rate"], "curve_ratio": m["curve_ratio"],
               "straight_rms": m["straight_rms"], "press_rate": m["press_rate"], "min": round(m["min"], 2)}
    f[i] = new
    last.append(f"{k}: {why} -> {new:.2f}")
  # neighbour smoothness: pull toward 1.0 whichever of a pair sits further from it
  for _ in range(len(f)):
    for i in range(len(f) - 1):
      if abs(f[i] - f[i + 1]) > MAX_NEIGHBOUR_GAP + 1e-9:
        j = i if abs(f[i] - 1.0) > abs(f[i + 1] - 1.0) else i + 1
        o = i + 1 if j == i else i
        f[j] = f[o] + math.copysign(MAX_NEIGHBOUR_GAP, f[j] - f[o])
  state.update({"factor": [round(x, 4) for x in f], "prev": prev, "carry": carry, "drives": state["drives"] + 1, "last": last})
  return state


# ---------------------------------------------------------------------------
# Trial building (offline). Values are the Lat*Scale* percent params (INT, Galaxy range 0-500, step 5).

SCHEMA_VERSION = 2
P_KEYS = tuple(f"LatPScale{n}" for n in BAND_NAMES)
I_KEYS = tuple(f"LatIScale{n}" for n in BAND_NAMES)
F_KEYS = tuple(f"LatFScale{n}" for n in BAND_NAMES)
BAND_KEYS = P_KEYS
SCHEDULE_KEY = "LatGainSchedule"


def _param_str(v):
  if isinstance(v, bytes):
    v = v.decode("utf-8", "replace")
  return "" if v is None else str(v)


# Per-band defaults when a Lat*Scale* key is unset, in BAND_NAMES order. They must match both
# common/params_keys.h and the fallbacks in LatControlPID's param refresh (latcontrol_pid.py); the
# display used to show 100 for every unset key, which was wrong for LowSpeed I (20) and Highway I (0).
BAND_DEFAULTS = {"p": (100, 100, 100), "i": (20, 100, 0), "f": (100, 100, 100)}


def _pct(raw, default=100):
  try:
    return int(round(float(_param_str(raw).strip() or default)))
  except ValueError:
    return default


def band_gains(raw_params):
  """[{"p", "i", "f"}] per band: the Lat*Scale* percent params as stored (missing -> BAND_DEFAULTS)."""
  return [{"p": _pct(raw_params.get(pk), BAND_DEFAULTS["p"][n]), "i": _pct(raw_params.get(ik), BAND_DEFAULTS["i"][n]),
           "f": _pct(raw_params.get(fk), BAND_DEFAULTS["f"][n])}
          for n, (pk, ik, fk) in enumerate(zip(P_KEYS, I_KEYS, F_KEYS, strict=True))]


def schedule_terms(raw):
  """Terms a LatGainSchedule value overrides ("p"/"i"/"f"), as LatControlPID parses it."""
  from openpilot.selfdrive.controls.lib.latcontrol_pid import parse_lat_gain_schedule
  try:
    sched = parse_lat_gain_schedule(_param_str(raw) or None)
  except Exception:
    sched = None
  return sorted(t for t in ("p", "i", "f") if sched and t in sched)


def strip_schedule_p(raw):
  """LatGainSchedule without its "p" term, so the LatPScale* bands drive P again. "" when nothing is left.

  Only a schedule the controller currently accepts is touched. LatControlPID rejects a malformed schedule
  whole, so its i/f terms are not in effect; stripping a bad "p" (e.g. a knot over the 300 limit) could make
  the rest valid and switch those i/f terms on, which this tool must never do. A rejected schedule already
  leaves P on the bands, so it is returned unchanged."""
  text = _param_str(raw).strip()
  if not text:
    return ""
  if "p" not in schedule_terms(text):
    return text
  try:
    d = json.loads(text)
  except ValueError:
    return text
  if not isinstance(d, dict) or "p" not in d:
    return text
  d = {k: v for k, v in d.items() if k != "p"}
  return json.dumps(d, separators=(",", ":")) if any(t in d for t in ("i", "f")) else ""


def propose_p(current, factor):
  """current % x factor on the Galaxy 5 % grid; a step never rounds away to nothing."""
  if abs(factor - 1.0) < 1e-9:
    return current
  target = int(round(current * factor / PCT_STEP)) * PCT_STEP
  if factor > 1.0 and target <= current:
    target = current + PCT_STEP
  elif factor < 1.0 and target >= current:
    target = current - PCT_STEP
  return min(max(target, PCT_MIN), PCT_MAX)


def build_trial(stats, baseline, route_names, per_route, warnings):
  """One trial from one DriveStats over the selected routes. baseline = {"fingerprint", "gains", "raw"}."""
  state = update_state(default_state(baseline.get("fingerprint")), stats, APPLY_MODE)
  gains = baseline.get("gains") or band_gains({})
  bands = []
  for i, (name, lo, hi) in enumerate(BANDS):
    m = band_metrics(stats.acc[i]) if stats.acc[i]["n"] > 0 else {
      "min": 0.0, "straight_rms": None, "sign_rate": None, "curve_ratio": None, "press_rate": None,
      "curve_ratio_ss": None, "curve_ratio_en": None, "curve_ratio_ex": None}
    reason = state["last"][i] if i < len(state["last"]) else ""
    decision = reason.split(":", 2)[1].strip().split(" ")[0] if reason.count(":") >= 1 else "hold"
    cur = {k: int(gains[i][k]) for k in ("p", "i", "f")}
    bands.append({"name": name, "lowMph": lo, "highMph": hi, "pKey": P_KEYS[i],
                  "minutes": round(m["min"], 2), "ready": m["min"] >= MIN_MINUTES,
                  "signRate": m["sign_rate"], "curveRatio": m["curve_ratio"], "straightRms": m["straight_rms"],
                  "curveRatioSteady": m["curve_ratio_ss"], "curveRatioEntry": m["curve_ratio_en"],
                  "curveRatioExit": m["curve_ratio_ex"], "pressRate": m["press_rate"], "factor": state["factor"][i], "decision": decision, "reason": reason,
                  "current": cur, "proposed": {"p": propose_p(cur["p"], state["factor"][i]), "i": cur["i"], "f": cur["f"]}})
  raw = {k: _param_str(v) for k, v in baseline.get("raw", {}).items()}
  return {"schemaVersion": SCHEMA_VERSION, "bandNames": list(BAND_NAMES), "routeNames": list(route_names),
          "warnings": list(warnings), "baseline": {"fingerprint": baseline.get("fingerprint"), "gains": gains, "raw": raw,
                                                   "scheduleTerms": schedule_terms(raw.get(SCHEDULE_KEY))},
          "bands": bands, "factors": list(state["factor"]), "perRoute": list(per_route), "applied": None}


def build_band_params(trial, device_gains=None):
  """{"LatPScaleStandard": int, "LatIScaleStandard": int, ...}: the band params a trial writes. F is never written.

  Only bands whose factor moved are written for P; a held band keeps whatever the device has. The step is
  applied to the device's current P (device_gains, as band_gains returns), not the P logged on the routes:
  the two differ only on a forced apply, and there writing the logged value x factor would silently undo a
  manual change made since the drive. Without device_gains the logged value is used.
  I is written only for a band the closed-loop sim step moved (tools/lateral/lat_tune_sim.py sets "iDelta");
  the rules never propose I. It is likewise a step from the device's current I, in points, clamped to 0..500."""
  out = {}
  for n, b in enumerate(trial["bands"]):
    factor = float(b.get("factor", 1.0))
    if abs(factor - 1.0) >= 1e-9:
      base = device_gains[n]["p"] if device_gains is not None else b["current"]["p"]
      out[b["pKey"]] = int(propose_p(int(base), factor))
    i_delta = int(b.get("iDelta") or 0)
    if i_delta:
      base_i = device_gains[n]["i"] if device_gains is not None else b["current"]["i"]
      out[I_KEYS[n]] = int(min(max(int(base_i) + i_delta, PCT_MIN), PCT_MAX))
  return out


# ---------------------------------------------------------------------------
# rlog -> frames. Only what DriveStats.observe needs; everything else is skipped.

from dataclasses import dataclass


@dataclass(slots=True)
class RouteLog:
  route: str
  segment: str
  log_path: str
  log_reader: object = None   # callable(path, **kw) -> iterable of messages; None = LogReader


def _default_log_reader(path, **kw):
  from openpilot.tools.lib.logreader import LogReader
  return LogReader(path, **kw)


def _steer_of(actuators):
  for name in ("torque", "steer"):
    if hasattr(actuators, name):
      return float(getattr(actuators, name))
  return None


class FrameSource:
  """Iterates one segment log and yields DriveStats.observe() arguments at each pidState controlsState."""

  def __init__(self, log_path, log_reader=None, should_continue=None):
    self.log_path = log_path
    self.log_reader = log_reader or _default_log_reader
    self.should_continue = should_continue
    self.tuning = {}      # TUNING_KEYS values from initData, str
    self.n = 0

  def frames(self):
    wanted = set(TUNING_KEYS)
    v_ego = angle = 0.0
    pressed = lane_change = False
    cc_steer = co_steer = None
    for msg in self.log_reader(self.log_path):
      if self.should_continue is not None and not self.should_continue():
        return
      which = msg.which()
      if which == "initData":
        params = getattr(msg.initData, "params", None)
        entries = getattr(params, "entries", None)
        if entries is not None:
          for e in entries:
            if e.key in wanted:
              self.tuning[e.key] = _param_str(e.value)
        elif isinstance(params, dict):
          self.tuning.update({k: _param_str(v) for k, v in params.items() if k in wanted})
      elif which == "carState":
        cs = msg.carState
        v_ego, angle, pressed = float(cs.vEgo), float(cs.steeringAngleDeg), bool(cs.steeringPressed)
      elif which == "modelV2":
        lane_change = str(getattr(getattr(msg.modelV2, "meta", None), "laneChangeState", "off")) != "off"
      elif which == "carControl":
        cc_steer = _steer_of(msg.carControl.actuators)
      elif which == "carOutput":
        co_steer = _steer_of(msg.carOutput.actuatorsOutput)
      elif which == "controlsState":
        lcs = msg.controlsState.lateralControlState
        if lcs.which() != "pidState" or not lcs.pidState.active:
          continue
        steer_limited = cc_steer is not None and co_steer is not None and abs(cc_steer - co_steer) > 0.01
        self.n += 1
        yield v_ego, float(lcs.pidState.steeringAngleDesiredDeg), angle, pressed, lane_change, steer_limited


def _merge_stats(dst, src):
  for a, b in zip(dst.acc, src.acc, strict=True):
    for k in _FIELDS:
      a[k] += b[k]


def analyze_sources(sources, should_continue=None, on_progress=None, baseline_overrides=None, mixed_tuning=False):
  """sources: RouteLog list in analysis order (oldest first). Returns a trial dict (build_trial).

  The newest route's logged lateral tuning is the baseline, and only routes driven on that same tuning
  (tuning_fingerprint) are pooled into the metrics. The others are listed in the warnings and in perRoute
  with used=False: their metrics describe gains the proposal is not relative to (123b: the 4 newest routes
  ran on 4 tunings, and pooling them mixed Standard I 25 and 75). mixed_tuning=True pools every route anyway.

  baseline_overrides: {param: value} replacing the logged Lat*Scale* values the proposal starts from (what-if).
  The metrics still come from the logs, i.e. from the gains the routes were actually driven with."""
  warnings = []
  tuning_by_route = {}
  stats_by_route = {}
  minutes_by_route = {}
  for idx, src in enumerate(sources):
    if on_progress is not None:
      on_progress(idx, len(sources), src)
    fs = FrameSource(src.log_path, log_reader=src.log_reader, should_continue=should_continue)
    seg_stats = DriveStats()
    # One DriveStats per route keeps the sign-change and press-merge state continuous across its segments.
    route_stats = stats_by_route.setdefault(src.route, DriveStats())
    for frame in fs.frames():
      route_stats.observe(*frame)
      seg_stats.observe(*frame)
    if fs.n == 0:
      warnings.append(f"{src.route}--{src.segment}: no engaged pidState frames (not modified-EPS PID, or never engaged)")
    if fs.tuning:
      tuning_by_route[src.route] = fs.tuning
    mins = minutes_by_route.setdefault(src.route, [0.0] * len(BANDS))
    for i in range(len(BANDS)):
      mins[i] = round(mins[i] + band_metrics(seg_stats.acc[i])["min"], 2)
  route_names = list(dict.fromkeys(s.route for s in sources))
  latest = next((tuning_by_route[r] for r in reversed(route_names) if r in tuning_by_route), {})
  base_fp = tuning_fingerprint(latest) if latest else None
  fps = {r: tuning_fingerprint(t) for r, t in tuning_by_route.items()}
  if base_fp is None or mixed_tuning:
    used = set(route_names)
  else:
    used = {r for r in route_names if fps.get(r) == base_fp}
  if mixed_tuning and len(set(fps.values())) > 1:
    warnings.append("routes were driven with different lateral tuning (fingerprint mismatch) and were pooled anyway "
                    "(mixed tuning); the newest route's tuning is the baseline")
  for r in route_names:
    if r in used:
      continue
    diff = sorted(k for k in TUNING_KEYS
                  if _fingerprint_value(tuning_by_route.get(r, {}).get(k)) != _fingerprint_value(latest.get(k)))
    why = f"differs in {', '.join(diff)}" if r in tuning_by_route else "no logged tuning (initData)"
    warnings.append(f"{r}: left out, driven on different lateral tuning than the newest route ({why})")
  stats = DriveStats()
  for r in route_names:
    if r in used and r in stats_by_route:
      _merge_stats(stats, stats_by_route[r])
  if baseline_overrides:
    logged = dict(latest)
    latest = {**latest, **{k: _param_str(v) for k, v in baseline_overrides.items()}}
    for k, v in baseline_overrides.items():
      warnings.append(f"baseline override: {k} = {v} (routes were driven with {logged.get(k) or 'default'}; "
                      "the metrics describe that gain, not this one)")
  if "p" in schedule_terms(latest.get(SCHEDULE_KEY)):
    warnings.append("LatGainSchedule overrides P on these routes; the proposal is relative to the LatPScale* bands, "
                    "and applying removes the schedule's p term")
  baseline = {"fingerprint": tuning_fingerprint(latest) if latest else None, "gains": band_gains(latest), "raw": latest}
  per_route = [{"route": r, "minutes": minutes_by_route[r], "tuning": fps.get(r), "used": r in used} for r in route_names]
  return build_trial(stats, baseline, route_names, per_route, warnings)
