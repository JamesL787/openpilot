"""Galaxy Plots: a 20 Hz tracking recorder for lateral and longitudinal control.

What it compares, and why those signals:
  lateral       desiredCurvature * v^2  vs  curvature * v^2   (controlsState, m/s^2)
  longitudinal  longitudinalPlan.aTarget vs carState.aEgo     (m/s^2; aEgo is what longcontrol closes on)
  wheel angle   pidState.steeringAngleDesiredDeg vs carState.steeringAngleDeg (deg; curve response and tight turns,
                free of the steer-ratio model that "measured" lateral accel goes through)
  car ahead     radarState.leadOne distance / speed / radar-or-camera, for the moments-to-check list
Only samples where openpilot is actually in control are scored: carControl.latActive with no steering
touch, and carControl.longActive with no gas press in the pid/starting states. The old sampler read
controlsState.active / controlsState.aTarget, which do not exist in this schema, and polled at 1.3 Hz.

Sampling is paced by longitudinalPlan (20 Hz) with every other service conflated to its latest message,
so a full drive costs six small deserialisations per 50 ms. 20 Hz resolves up to 10 Hz, which covers
steering ping-pong (1-3 Hz) and lets the response lag be measured to 50 ms.

The analysis is a heuristic summary of one drive, not a verdict on a tune. Everything it says is bound
to the recorded samples and the tune snapshot stored beside them.
"""
import csv
import gzip
import json
import os
import shutil
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from openpilot.starpilot.system.the_galaxy import drive_plots_agents as agents

COLUMNS = [
  "t", "v", "a_ego", "enabled", "lat_active", "long_active", "steer_pressed", "gas_pressed", "brake_pressed",
  "lat_des", "lat_act", "long_des", "long_act", "long_state",
  "lat_p", "lat_i", "lat_d", "lat_f", "long_up", "long_ui", "long_uf", "lat_sat",
  # Wheel angles (deg, + = left) as the lateral controller saw them; ang_ok is 0 where the controller does not
  # publish a desired angle (torque cars) and in recordings made before these columns existed.
  "ang_des", "ang_act", "ang_ok",
  # radarState.leadOne: distance (m), speed (m/s) and source (0 no lead, 1 radar, 2 camera only).
  "lead_d", "lead_v", "lead_src",
  # ---- added 2026-09-28 for the lateral / longitudinal agents (drive_plots_agents.py says who asked for what) ----
  # Driver and actuator: carState.steeringTorque / steeringTorqueEps / steeringRateDeg, either blinker,
  # carControl.actuators.torque (requested) and carOutput.actuatorsOutput.torque (delivered; the gap is the override
  # cut and fade).
  "steer_tq", "steer_tq_eps", "steer_rate", "blinker", "tq_req", "tq_out",
  # Controller: pidState.output / angleError / active; starpilotLateralState eps FF (active, weight, feedforward at
  # full weight). pidState.p is the P before LatControlHondaEps's per-band scale.
  "lat_out", "ang_err", "pid_active", "ff_active", "ff_w", "ff",
  # Lane from modelV2.laneLines[1]/[2].y[0]: car offset from the lane centre (m, + = car left of centre), lane width,
  # the lower of the two laneLineProbs and each one (left, right: which side drops out); modelV2.meta.laneChangeState
  # (0 off; a lane change is not wobble).
  "lane_off", "lane_w", "lane_prob", "lane_prob_l", "lane_prob_r", "lane_change",
  # How old controlsState was when this row was taken (ms); a stall shows as a large value.
  "cs_age_ms",
  # Longitudinal: carControl.actuators.accel (sent), plan shouldStop / fcw / hasLead, selfdriveState.experimentalMode
  # (experimental active right now, switched by Conditional Experimental; the driver's setting is in the meta),
  # starpilotPlan tFollow / trackingLead, carState.standstill.
  "a_cmd", "should_stop", "fcw", "has_lead", "exp_mode", "t_follow", "tracking_lead", "standstill",
  # radarState.leadOne extras, leadTwo, and the camera's own lead (modelV2.leadsV3[0]).
  "lead_id", "lead_y", "lead_vrel", "lead_a", "lead_prob", "lead_meas", "lead_vrr",
  "lead2_on", "lead2_d", "lead2_v", "lead2_id",
  "mlead_p", "mlead_x", "mlead_y", "mlead_v", "mlead_a",
  # ---- added 2026-09-29 from the agents' metric requests (Kevin, James, Bob, John) ----
  # Steering faults (carState.steerFaultTemporary / Permanent): a flicker during a takeover is what Kevin counts.
  "fault_t", "fault_p",
  # controlsState.desiredCurvature / curvature in 1/km (+ = right, as lat_des): lat_des is curvature * v^2 and so
  # loses the sign and size of the request at low speed. James.
  "des_curv", "curv",
  # starpilotLateralState firmware feedforward internals: R5 counts it asks for, the column-load counts, and the
  # filtered desired wheel rate (deg/s). James.
  "ff_r5", "ff_load", "ff_rate",
  # liveParameters.angleOffsetDeg / roll (rad) and liveDelay.lateralDelay (s). James, John.
  "ang_off", "roll", "lat_delay",
  # longitudinalPlan: source (0 cruise, 1-3 lead0-2, 4 e2e), allowThrottle / allowBrake, the close-lead brake cap
  # (0 when it did not engage) and the accel the lead geometry requires. Bob.
  "plan_src", "allow_thr", "allow_brk", "cl_cap", "geo_acc",
  # radarState.leadOne dPath (m) and aLeadTau (s); carControl.orientationNED[1] pitch (rad); carState.vCruise (km/h).
  "lead_dpath", "lead_tau", "pitch", "v_cruise",
  # starpilotPlan: red light, forcing a stop, road curvature ahead (1/m), approach-stop pre-commit distance (m).
  "red_light", "forcing_stop", "road_curv", "stop_len",
  # starpilotCarState Honda gas learner: applied gas factor, wind factor, error (m/s^2), learning this tick, and the
  # raw gas factor before its clip (Bob's gf_clip moment).
  "gl_gf", "gl_wf", "gl_err", "gl_learn", "gl_gf_raw",
  # starpilotRadarState: a moving lead in the left / right lane, a vehicle stopped in an adjacent lane.
  "adj_l", "adj_r", "adj_stop",
]
# Columns read as NaN ("not recorded") when an older recording lacks them, so no metric is built from zeros.
_AGENT_COLS = COLUMNS[COLUMNS.index("steer_tq"):]
NAN_COLUMNS = set(_AGENT_COLS)
COL = {name: i for i, name in enumerate(COLUMNS)}
BOOL_COLUMNS = {"enabled", "lat_active", "long_active", "steer_pressed", "gas_pressed", "brake_pressed", "lat_sat", "ang_ok",
                "blinker", "pid_active", "ff_active", "should_stop", "fcw", "has_lead", "exp_mode", "tracking_lead",
                "standstill", "lead_meas", "lead2_on", "fault_t", "fault_p", "allow_thr", "allow_brk", "red_light",
                "forcing_stop", "gl_learn", "adj_l", "adj_r", "adj_stop"}
LEAD_SOURCES = {0: None, 1: "radar", 2: "camera"}

# Lateral controllers the advice can name (see the_galaxy._lateral_controller_info).
CONTROLLER_CLARITY_EPS = "clarity_eps"   # James's controller (LatControlHondaEps): fixed P/I, no Lat*Scale sliders
CONTROLLER_NRDR_PID = "nrdr_pid"         # LatControlPID on a modified-EPS Honda: LatP/I/FScale LowSpeed/Standard/Highway

LONG_STATES = {"off": 0, "pid": 1, "stopping": 2, "starting": 3}

LIVE_BUFFER_S = 60.0
LIVE_WINDOW_S = 30.0
NOMINAL_DT = 0.05
CLIENT_IDLE_TIMEOUT_S = 6.0
OFFROAD_AUTOSTOP_S = 30.0
FINALIZE_ONROAD_POLL_S = 5.0
MAX_RECORDING_S = 8 * 3600.0   # ~90 MB of CSV; stops a forgotten recording from filling /data
FLUSH_EVERY_ROWS = 20

# ---- automatic recording and the copy that goes into the drive's rlog ----
AUTO_CHECK_S = 2.0               # how often the watcher looks at IsOnroad
AUTO_KEEP_SESSIONS = 20          # automatic sessions kept (manual ones are never pruned)
AUTO_KEEP_BYTES = 1_000_000_000  # and at most this much disk for them
DEFAULT_SETTINGS = {"auto_record": True, "publish_to_log": True}
# The rlog carrier: cereal's customReservedRawData0 (a logged :Data slot nothing else uses), so the device needs no
# rebuild. Each message is one JSON object {"schema": RLOG_SCHEMA, "type": "start"|"moment"|"takeover"|"summary"|"end"}.
# Times in it are monotonic (mono_s / mono_ns, the same clock as logMonoTime), never route-relative.
RLOG_SERVICE = "customReservedRawData0"
RLOG_SCHEMA = "drivePlots/1"
PUBLISH_SCAN_S = 20.0            # moments are looked for this often, over the last LIVE_BUFFER_S of samples
PUBLISH_MARGIN_S = 8.0           # a moment is published once it is this old, so its whole shape is in the window
PUBLISH_EDGE_S = 1.0             # moments this close to the window's start may be cut off; the previous scan had them
TAKEOVER_TAIL_S = 7.0            # a takeover waits for release + this, so the +6 s drift is measured
PUBLISH_DEDUPE_S = 3.0
SUMMARY_EVERY_S = 300.0

# ---- analysis thresholds (heuristics; each finding that uses one says so) ----
SEGMENT_GAP_S = 0.2          # a gap longer than this splits the series; lagged pairs never cross it
MAX_LAG_S = 1.5
LAT_MIN_SPEED = 5.0          # m/s; below this lateral accel is too small to say anything
LAT_CURVE_DEMAND = 0.5       # m/s^2; "in a curve" for the gain estimate
LAT_STRAIGHT_DEMAND = 0.15   # m/s^2; "straight" for the drift estimate
LONG_REGIME_DEMAND = 0.25    # m/s^2; accel / braking regimes for the bias estimate
LONG_GAIN_DEMAND = 0.3
HARD_BRAKE = -2.5            # m/s^2
GAIN_LOW, GAIN_HIGH = 0.85, 1.15
WOBBLE_RATIO_HIGH = 1.5
WOBBLE_FLOOR = 0.02          # m/s^2; keeps the ratio finite on a dead-straight road
LAT_BIAS_NOTABLE = 0.05
LONG_BIAS_NOTABLE = 0.15
JERK_HIGH = 2.5              # m/s^3, p95 of engaged actual jerk
LAT_RMSE_GOOD, LAT_RMSE_FAIR = 0.20, 0.40
LONG_RMSE_GOOD, LONG_RMSE_FAIR = 0.25, 0.45
SATURATION_NOTABLE = 0.05    # fraction of curve samples at the steering limit
BAND_MIN_S = 10.0            # a speed band needs this much engaged time to be reported
BAND_GAIN_SPREAD = 0.15      # gain difference between bands worth a sentence
MPH = 2.23694
# Speed bands for the per-band breakdown, in m/s. They are the lateral controllers' own bands and the owner's
# tuning sliders (LowSpeed < 25 mph, Standard 25-50, Highway 50+; nrdr_eps_firmware_ff.BAND_LOW_MAX/BAND_STD_MAX),
# so a band finding points at one slider.
SPEED_BANDS = [(0.0, 25.0 / MPH, "Low speed"), (25.0 / MPH, 50.0 / MPH, "Standard"), (50.0 / MPH, float("inf"), "Highway")]

# Tight turns, on wheel angle (the definitions tools/lateral/lat_score.py uses for turn_err / turn_past / turn_trail,
# so the numbers compare with the lateral scorecard; lat_score runs at 100 Hz, this at 20 Hz).
TURN_MIN_DEG = 45.0          # |desired wheel angle| for a frame to count as "in a tight turn"
TURN_MIN_SPEED = 4.0         # m/s
TURN_BINS = [(4.0, 5.36, "under 12 mph"), (5.36, 11.2, "12-25 mph")]
TURN_MIN_S = 0.5             # a bin needs this much tight-turn time to be reported
TURN_EPISODE_DEG = 20.0      # a turn episode runs while |desired| > this (so it includes the unwind)
TURN_PAST_NOTABLE = 3.0      # deg; mean past-the-request in a bin worth a takeaway (STATUS 173/190 ranges 0.6-10.6)
TURN_EVENT_DEG = 10.0        # deg; one turn's peak past-the-request worth listing as a moment to check
# Wheel wobble on near-straight road: rms of the 0.4-3 Hz band of the wheel angle (lat_score's wobble: MA 0.15 s
# minus MA 1.25 s) where |desired| and |angle| stay under 12 deg for a whole centred 1.5 s window.
WOBBLE_STRAIGHT_DEG = 12.0
WOBBLE_BINS = [(5.0, 8.0), (8.0, 12.0), (12.0, 20.0)]
WOBBLE_MIN_S = 3.0

# Moments to check (events).
EVENTS_PER_KIND = 15


# =====================================================================================================
# Analysis (pure; unit-tested on synthetic signals)
# =====================================================================================================

def _as_arrays(rows):
  """rows: list of sequences in COLUMNS order, or an (N, len(COLUMNS)) array."""
  data = np.asarray(rows, dtype=float).reshape(-1, len(COLUMNS))
  return {name: data[:, i] for i, name in enumerate(COLUMNS)}


def _segments(t):
  if len(t) == 0:
    return np.zeros(0, dtype=int)
  return np.concatenate([[0], np.cumsum(np.diff(t) > SEGMENT_GAP_S)])


def _dt(t):
  if len(t) < 2:
    return NOMINAL_DT
  d = np.diff(t)
  d = d[(d > 0) & (d <= SEGMENT_GAP_S)]
  return float(np.median(d)) if len(d) else NOMINAL_DT


def _rising_edges(x):
  x = x.astype(bool)
  if len(x) < 2:
    return 0
  return int(np.count_nonzero(x[1:] & ~x[:-1]))


def _runs(mask, seg, min_len):
  """Contiguous index runs where mask is true inside one segment."""
  runs = []
  start = None
  for i in range(len(mask)):
    ok = bool(mask[i]) and (start is None or seg[i] == seg[start])
    if ok and start is None:
      start = i
    elif not ok and start is not None:
      if i - start >= min_len:
        runs.append((start, i))
      start = i if mask[i] else None
  if start is not None and len(mask) - start >= min_len:
    runs.append((start, len(mask)))
  return runs


def _moving_average(x, n):
  if n <= 1 or len(x) < n:
    return x.copy()
  return np.convolve(x, np.ones(n) / n, mode="same")


def _best_lag(des, act, mask, seg, dt):
  """Shift actual back by k samples (actual trails target) and keep the k with the lowest RMSE.
  Pairs are only formed when both ends are scored samples in the same segment."""
  n = len(des)
  best = None
  rmse0 = None
  for k in range(0, int(round(MAX_LAG_S / dt)) + 1):
    if k >= n:
      break
    i = np.arange(n - k)
    ok = mask[i] & mask[i + k] & (seg[i] == seg[i + k])
    if np.count_nonzero(ok) < 20:
      continue
    d = des[i][ok]
    a = act[i + k][ok]
    rmse = float(np.sqrt(np.mean((a - d) ** 2)))
    if k == 0:
      rmse0 = rmse
    if best is None or rmse < best[1] - 1e-9:
      best = (k, rmse, d, a, i[ok])
  if best is None:
    return None
  k, rmse, d, a, idx = best
  return {"lag_s": k * dt, "rmse": rmse, "rmse_no_lag": rmse0 if rmse0 is not None else rmse, "des": d, "act": a, "idx": idx}


def _gain(d, a, demand):
  sel = np.abs(d) > demand
  if np.count_nonzero(sel) < 40:
    return None
  return float(np.sum(d[sel] * a[sel]) / np.sum(d[sel] ** 2))


def _mean_where(x, sel, min_count=40):
  if np.count_nonzero(sel) < min_count:
    return None
  return float(np.mean(x[sel]))


def _r(x, digits=3):
  return None if x is None else round(float(x), digits)


def _gain_sel(d, a, sel, min_count=40):
  if np.count_nonzero(sel) < min_count:
    return None
  den = float(np.sum(d[sel] ** 2))
  return float(np.sum(d[sel] * a[sel]) / den) if den > 0 else None


def _speed_bands(v, d, a, dt, gain_demand, gain_fit=None):
  """Tracking error and gain per speed band, on lag-aligned pairs. Bands with little data are left out.
  gain_fit (v, d, a, sel) replaces the gain with one from other lag-aligned pairs (the wheel angle)."""
  out = []
  err = a - d
  for lo, hi, name in SPEED_BANDS:
    sel = (v >= lo) & (v < hi)
    n = int(np.count_nonzero(sel))
    if n * dt < BAND_MIN_S:
      continue
    if gain_fit is not None:
      gv, gd, ga, gsel = gain_fit
      gain = _gain_sel(gd, ga, gsel & (gv >= lo) & (gv < hi))
    else:
      gain = _gain(d[sel], a[sel], gain_demand)
    out.append({
      "name": name, "lo_ms": _r(lo, 2), "hi_ms": None if hi == float("inf") else _r(hi, 2),
      "engaged_s": round(n * dt, 1),
      "rmse": _r(np.sqrt(np.mean(err[sel] ** 2))),
      "gain": _r(gain),
      "bias": _r(np.mean(err[sel])),
    })
  return out


def _band_label(b):
  lo, hi = b["lo_ms"] * MPH, None if b["hi_ms"] is None else b["hi_ms"] * MPH
  rng = f"{lo:.0f}+ mph" if hi is None else f"under {hi:.0f} mph" if lo == 0 else f"{lo:.0f}-{hi:.0f} mph"
  return f"{b['name']} ({rng})" if b.get("name") else rng


def _has_angles(c):
  return bool(np.any(c["ang_ok"] > 0.5))


def _analyze_turns(c, seg, dt):
  """Tight low-speed turns and near-straight wheel wobble, on wheel angle. None without angle data."""
  if not _has_angles(c):
    return None
  t, v, des, act = c["t"], c["v"], c["ang_des"], c["ang_act"]
  # A driver grab and the first second after it are not the controller's turn (James): left out.
  base = (c["ang_ok"] > 0.5) & (c["lat_active"] > 0.5) & ~agents.after_release(c) & (v > TURN_MIN_SPEED)
  side = np.sign(des)
  past = np.maximum(0.0, side * (act - des))
  trail = np.maximum(0.0, side * (des - act))
  # tools/lateral/lat_score.py's turn_err mask (the agents' scorecard): pidState.active, hands off, v > 4 m/s. It keeps
  # the second after a grab, where the wheel is still catching up, so it reads higher than Plots' own figure.
  active = c["pid_active"] if agents.has(c, "pid_active") else c["lat_active"]
  score = (c["ang_ok"] > 0.5) & (np.nan_to_num(active) > 0.5) & (c["steer_pressed"] < 0.5) & (v > TURN_MIN_SPEED)
  bins = []
  for lo, hi, label in TURN_BINS:
    tight = (np.abs(des) > TURN_MIN_DEG) & (v >= lo) & (v < hi)
    sel, sc = base & tight, score & tight
    n, nsc = int(np.count_nonzero(sel)), int(np.count_nonzero(sc))
    if n * dt < TURN_MIN_S and nsc * dt < TURN_MIN_S:
      continue
    ok = n * dt >= TURN_MIN_S
    b = {"label": label, "lo_ms": lo, "hi_ms": hi, "time_s": round(n * dt, 1),
         "err": _r(np.mean(np.abs(des[sel] - act[sel])), 1) if ok else None, "past": _r(np.mean(past[sel]), 1) if ok else None,
         "trail": _r(np.mean(trail[sel]), 1) if ok else None, "at_limit": _r(np.mean(c["lat_sat"][sel] > 0.5), 2) if ok else None}
    if nsc * dt >= TURN_MIN_S:
      b["scorecard"] = {"time_s": round(nsc * dt, 1), "err": _r(np.mean(np.abs(des[sc] - act[sc])), 1),
                        "past": _r(np.mean(past[sc]), 1), "trail": _r(np.mean(trail[sc]), 1)}
    bins.append(b)
  turns = []
  for s, e in _runs(base & (np.abs(des) > TURN_EPISODE_DEG), seg, 2):
    k = s + int(np.argmax(np.abs(des[s:e])))
    if abs(des[k]) < TURN_MIN_DEG or v[k] >= TURN_BINS[-1][1]:
      continue
    sd = np.sign(des[k])
    same = np.sign(des[s:e]) == sd
    over = np.where(same, sd * (act[s:e] - des[s:e]), 0.0)
    j = s + int(np.argmax(over))
    turns.append({"i": j, "t": round(float(t[j] - t[0]), 1), "mono_s": round(float(t[j]), 3), "v": _r(v[j], 1), "peak_des": _r(abs(des[k]), 0),
                  "overshoot": _r(max(0.0, float(over[j - s])), 1), "side": "left" if sd > 0 else "right"})
  wobble = []
  h = int(round(0.75 / dt))
  fast, slow = max(1, int(round(0.15 / dt))), max(3, int(round(1.25 / dt)))
  straight = base & (np.abs(des) < WOBBLE_STRAIGHT_DEG) & (np.abs(act) < WOBBLE_STRAIGHT_DEG)
  if agents.has(c, "lane_change"):
    # As lat_score's straight_mask: a lane change is the plan moving the wheel, not wobble.
    straight &= ~(np.nan_to_num(c["lane_change"]) > 0.5)
  band, keep = [], []
  for s, e in _runs(straight, seg, 2 * h + 1):
    x = act[s:e]
    bp = _moving_average(x, fast) - _moving_average(x, slow)
    band.append(bp[h: len(x) - h])
    keep.append(np.arange(s + h, e - h))
  if band:
    band, keep = np.concatenate(band), np.concatenate(keep)
    for lo, hi in WOBBLE_BINS:
      sel = (v[keep] >= lo) & (v[keep] < hi)
      n = int(np.count_nonzero(sel))
      if n * dt >= WOBBLE_MIN_S:
        wobble.append({"lo_ms": lo, "hi_ms": hi, "time_s": round(n * dt, 1), "rms_deg": _r(np.sqrt(np.mean(band[sel] ** 2)), 2)})
  return {"bins": bins, "turns": turns, "wobble": wobble}


def _analyze_lateral(c, seg, dt, min_engaged_s):
  mask = (c["lat_active"] > 0.5) & (c["steer_pressed"] < 0.5) & (c["v"] > LAT_MIN_SPEED)
  engaged_s = float(np.count_nonzero(mask) * dt)
  out = {
    "engaged_s": round(engaged_s, 1),
    "steer_overrides": _rising_edges((c["steer_pressed"] > 0.5) & (c["lat_active"] > 0.5)),
  }
  turns = _analyze_turns(c, seg, dt)
  if turns is not None:
    out["turns"] = {k: turns[k] for k in ("bins", "wobble")}
    out["turns"]["count"] = len(turns["turns"])
    out["turns"]["overshoots"] = [{k: x[k] for k in ("t", "mono_s", "v", "peak_des", "overshoot", "side")}
                                  for x in turns["turns"] if x["overshoot"] >= TURN_EVENT_DEG]
  if engaged_s < min_engaged_s:
    out["status"] = "insufficient"
    return out
  fit = _best_lag(c["lat_des"], c["lat_act"], mask, seg, dt)
  if fit is None:
    out["status"] = "insufficient"
    return out
  d, a = fit["des"], fit["act"]
  err = a - d
  # Curve response on wheel angle when it was recorded: "measured" lateral accel goes through paramsd's linear
  # steer ratio, while both Honda controllers aim through the firmware ratio table, so in tight turns the two
  # disagree by up to ~10 % (route 292: angle gain 1.06 vs curvature gain 0.94 above 90 deg). "In a curve" is
  # still chosen by the requested lateral accel.
  gain_fit = None
  if turns is not None:
    afit = _best_lag(c["ang_des"], c["ang_act"], mask & (c["ang_ok"] > 0.5), seg, dt)
    if afit is not None:
      gain_fit = (c["v"][afit["idx"]], afit["des"], afit["act"], np.abs(c["lat_des"][afit["idx"]]) > LAT_CURVE_DEMAND)
  hp_act, hp_des = [], []
  win = max(3, int(round(1.0 / dt)) | 1)
  for s, e in _runs(mask, seg, win * 2):
    for src, dst in ((c["lat_act"], hp_act), (c["lat_des"], hp_des)):
      x = src[s:e]
      hp = (x - _moving_average(x, win))[win // 2: len(x) - win // 2]
      dst.append(hp)
  wobble = None
  if hp_act:
    ra = float(np.sqrt(np.mean(np.concatenate(hp_act) ** 2)))
    rd = float(np.sqrt(np.mean(np.concatenate(hp_des) ** 2)))
    wobble = ra / max(rd, WOBBLE_FLOOR)
  in_curve = np.abs(d) > LAT_CURVE_DEMAND
  sat = c["lat_sat"][fit["idx"]] > 0.5
  saturated_curve = float(np.mean(sat[in_curve])) if np.count_nonzero(in_curve) >= 40 else None
  out.update({
    "status": "ok",
    "lag_s": _r(fit["lag_s"], 2),
    "rmse": _r(fit["rmse"]),
    "rmse_no_lag": _r(fit["rmse_no_lag"]),
    "p95_abs_error": _r(np.percentile(np.abs(err), 95)),
    "curve_gain": _r(_gain_sel(gain_fit[1], gain_fit[2], gain_fit[3]) if gain_fit else _gain(d, a, LAT_CURVE_DEMAND)),
    "curve_gain_source": "wheel angle" if gain_fit else "lateral acceleration",
    "straight_bias": _r(_mean_where(err, np.abs(d) < LAT_STRAIGHT_DEMAND, 100)),
    "wobble_ratio": _r(wobble, 2),
    "peak_demand": _r(np.max(np.abs(d))),
    "saturated_curve_frac": _r(saturated_curve),
    "speed_bands": _speed_bands(c["v"][fit["idx"]], d, a, dt, LAT_CURVE_DEMAND, gain_fit),
  })
  return out


def _events(c, dt, lateral, cap=EVENTS_PER_KIND, takeover_data=None):
  """Moments worth a look, with the time into the recording, the speed and the car ahead: braking moments and
  lead changes (drive_plots_agents.long_moments, Radar Work's list), James's lateral moments (lat_moments), driver takeovers while openpilot steered (raw
  steeringPressed, with release numbers) and tight turns that went past the request. cap: per kind (None = all)."""
  t = c["t"]
  if len(t) < 2:
    return []
  out = agents.long_moments(c, cap=cap) + agents.lat_moments(c, cap=cap)
  eps = (takeover_data or agents.takeovers(c))["episodes"]
  kept = [e for e in eps if e["lat_active"]]
  for e in (kept[:cap] if cap else kept):
    x = {"kind": "steer_takeover", **{k: e[k] for k in ("t", "mono_s", "v", "hold_s", "tag", "push", "blinker",
                                                            "release_overshoot_deg", "back_on_plan_s", "lanes_ok", "flags")
                                      if k in e}}
    x["drift_3s_m"] = e.get("drift_3s_m")
    out.append(x)
  overs = (lateral.get("turns") or {}).get("overshoots") or []
  for x in (overs[:cap] if cap else overs):
    out.append({"kind": "turn_overshoot", **x})
  out.sort(key=lambda e: e["t"])
  return out


def _analyze_longitudinal(c, seg, dt, min_engaged_s):
  state = np.rint(c["long_state"]).astype(int)
  mask = ((c["long_active"] > 0.5) & (c["gas_pressed"] < 0.5) &
          np.isin(state, [LONG_STATES["pid"], LONG_STATES["starting"]]) &
          ~((c["v"] < 0.3) & (c["long_des"] <= 0.0)))
  engaged_s = float(np.count_nonzero(mask) * dt)
  out = {
    "engaged_s": round(engaged_s, 1),
    "gas_overrides": _rising_edges((c["gas_pressed"] > 0.5) & (c["enabled"] > 0.5)),
    # Planned braking (aTarget), not aEgo: hills and driver braking make aEgo alone misleading (Radar Work).
    "hard_brakes": _rising_edges((c["long_des"] < HARD_BRAKE) & (c["long_active"] > 0.5)),
  }
  if engaged_s < min_engaged_s:
    out["status"] = "insufficient"
    return out
  fit = _best_lag(c["long_des"], c["long_act"], mask, seg, dt)
  if fit is None:
    out["status"] = "insufficient"
    return out
  d, a = fit["des"], fit["act"]
  err = a - d
  jerks = []
  smooth = max(1, int(round(0.25 / dt)))
  for s, e in _runs(mask, seg, smooth * 4):
    x = _moving_average(c["long_act"][s:e], smooth)[smooth: -smooth or None]
    if len(x) > 2:
      jerks.append(np.abs(np.diff(x)) / dt)
  out.update({
    "status": "ok",
    "lag_s": _r(fit["lag_s"], 2),
    "rmse": _r(fit["rmse"]),
    "rmse_no_lag": _r(fit["rmse_no_lag"]),
    "p95_abs_error": _r(np.percentile(np.abs(err), 95)),
    "gain": _r(_gain(d, a, LONG_GAIN_DEMAND)),
    "accel_bias": _r(_mean_where(err, d > LONG_REGIME_DEMAND)),
    "brake_bias": _r(_mean_where(err, d < -LONG_REGIME_DEMAND)),
    "jerk_p95": _r(np.percentile(np.concatenate(jerks), 95), 2) if jerks else None,
    "speed_bands": _speed_bands(c["v"][fit["idx"]], d, a, dt, LONG_GAIN_DEMAND),
  })
  return out


def _fmt_time(seconds):
  seconds = int(round(seconds or 0))
  if seconds < 60:
    return f"{seconds} s"
  m, sec = divmod(seconds, 60)
  if m < 60:
    return f"{m} min {sec:02d} s"
  h, m = divmod(m, 60)
  return f"{h} h {m:02d} min"


def _feel(rmse, good, fair):
  if rmse <= good:
    return "small enough that you would hardly feel it"
  if rmse <= fair:
    return "enough that you would notice it in places"
  return "large enough to feel most of the time"


_FIXED_GAINS = ("James's controller drove this drive. It ignores the LatP / LatI / LatF sliders, so there is no slider "
                "for this; note it and compare a few drives.")


def _band_notes(bands, what, takeaways, controller=None, steering=False):
  known = [b for b in (bands or []) if b.get("gain") is not None]
  if len(known) < 2:
    return []
  parts = ", ".join(f"{_band_label(b)} {round(b['gain'] * 100)}%" for b in known)
  gains = [b["gain"] for b in known]
  if max(gains) - min(gains) > BAND_GAIN_SPREAD:
    if steering and controller == CONTROLLER_NRDR_PID:
      where = "the Low speed / Standard / Highway sliders let you change one speed without the others."
    elif steering and controller == CONTROLLER_CLARITY_EPS:
      where = "James's controller has no per-speed sliders, so note it and compare a few drives."
    else:
      where = "the speed breakpoints are the place to look."
    takeaways.append(f"{what} changes with speed ({parts}). The tune is right at one speed and off at another; {where}")
    return [f"By speed: {parts}. The response is not the same at every speed, which points at one speed band "
            "rather than a single gain."]
  return [f"By speed: {parts}. The response was consistent across speeds."]


def _turn_notes(turns, takeaways, controller=None):
  """Tight low-speed turns and wheel wobble, in degrees of steering-wheel angle."""
  if not turns:
    return []
  notes = []
  bins = turns.get("bins") or []
  if bins:
    parts = "; ".join(f"{b['label']}: off by {b['err']}° on average ({b['past']}° past the request, {b['trail']}° behind it)"
                      for b in bins if b["err"] is not None) or "too little time after leaving out your grabs"
    notes.append(f"Tight turns (wheel past {TURN_MIN_DEG:.0f}°, {turns.get('count', 0)} turn(s)): {parts}. "
                 "'Behind' is mostly the wheel catching up; 'past' is overshoot or a late unwind.")
    sc = [b for b in bins if b.get("scorecard")]
    if sc:
      notes.append("Counting the second after you let go of the wheel, as the agents' scorecard (lat_score) does: " +
                   "; ".join(f"{b['label']} off by {b['scorecard']['err']}° ({b['scorecard']['past']}° past)" for b in sc) +
                   ". A big gap between the two numbers means the wheel is still catching up right after your grabs.")
    worst = max(bins, key=lambda b: b["past"] or 0)
    if (worst["past"] or 0) > TURN_PAST_NOTABLE:
      takeaways.append(f"In tight turns {worst['label']} the wheel went {worst['past']}° past the request on average (overshoot "
                       "or late unwind). The turns are listed under Moments to check.")
    sat = max(b["at_limit"] or 0 for b in bins)
    if sat > SATURATION_NOTABLE:
      notes.append(f"Steering was at its limit for {round(sat * 100)}% of tight-turn time, so some of the lag there is the car's "
                   "limit, not the tune.")
  elif turns.get("count") is not None:
    notes.append(f"No tight low-speed turns (wheel past {TURN_MIN_DEG:.0f}° under 25 mph) this drive.")
  over = turns.get("overshoots") or []
  if over:
    notes.append(f"{len(over)} turn(s) went {TURN_EVENT_DEG:.0f}° or more past the request at some point; see Moments to check.")
  wob = turns.get("wobble") or []
  if wob:
    parts = ", ".join(f"{b['lo_ms'] * MPH:.0f}-{b['hi_ms'] * MPH:.0f} mph {b['rms_deg']}°" for b in wob)
    notes.append(f"Wheel wobble on near-straight road (quick back-and-forth of the wheel itself): {parts}. "
                 "Lower is steadier; compare drives rather than reading one number.")
  return notes


def _band(rmse, good, fair):
  if rmse <= good:
    return "closely"
  if rmse <= fair:
    return "with some visible error"
  return "loosely"


def _lateral_findings(m, takeaways, controller=None):
  """Plain-language summary and notes for steering. Numbers stay in the metrics; the words say what it felt like."""
  if m.get("status") != "ok":
    turn_takeaways = []
    notes = _turn_notes(m.get("turns"), turn_takeaways, controller)
    takeaways.extend(turn_takeaways)
    return (f"Not enough engaged steering above {LAT_MIN_SPEED * MPH:.0f} mph ({LAT_MIN_SPEED * 3.6:.0f} km/h) to judge "
            f"({_fmt_time(m.get('engaged_s', 0))} counted)."), notes
  notes = [f"The car starts reacting about {m['lag_s']} s after openpilot asks. After allowing for that, it typically stayed "
           f"within {m['rmse']} m/s² of the planned path, {_feel(m['rmse'], LAT_RMSE_GOOD, LAT_RMSE_FAIR)}."]
  g = m.get("curve_gain")
  on_angle = m.get("curve_gain_source") == "wheel angle"
  if g is not None:
    pct = round(g * 100)
    if controller == CONTROLLER_CLARITY_EPS:
      low_fix = high_fix = _FIXED_GAINS
    elif controller == CONTROLLER_NRDR_PID:
      low_fix = "consider a slightly higher LatF (feedforward) slider for the speed where it happens."
      high_fix = "consider a slightly lower LatF (feedforward) slider for the speed where it happens."
    elif on_angle:
      low_fix, high_fix = "consider a slightly higher feedforward.", "consider a slightly lower feedforward."
    else:
      low_fix = "consider a slightly higher feedforward or check the steer ratio."
      high_fix = "consider a slightly lower feedforward or check the steer ratio."
    cause = "the steering feedforward" if on_angle else "the steering feedforward (or the steer ratio)"
    if g < GAIN_LOW:
      notes.append(f"In curves the wheel turned about {100 - pct}% less than asked, so the car tends to run wide. If this repeats "
                   f"across drives, {cause} is a little low.")
      takeaways.append(f"Under-turning in curves ({pct}% of the request): {low_fix}")
    elif g > GAIN_HIGH:
      notes.append(f"In curves the wheel turned about {pct - 100}% more than asked, so the car tends to cut in. If this repeats "
                   f"across drives, {cause} is a little high.")
      takeaways.append(f"Over-turning in curves ({pct}% of the request): {high_fix}")
    else:
      notes.append(f"In curves the wheel turned almost exactly as much as asked ({pct}%).")
  else:
    notes.append("There were no sustained curves, so curve response could not be measured this drive.")
  notes.extend(_band_notes(m.get("speed_bands"), "Curve response", takeaways, controller, steering=True))
  notes.extend(_turn_notes(m.get("turns"), takeaways, controller))
  sat = m.get("saturated_curve_frac")
  if sat is not None and sat > SATURATION_NOTABLE:
    notes.append(f"Steering was at its limit for {round(sat * 100)}% of the time in curves, meaning the car could not turn as hard "
                 "as openpilot wanted. Expect to take over in the sharpest curves; the steering limit is a car-specific setting.")
    takeaways.append(f"Steering hit its limit {round(sat * 100)}% of curve time: the sharpest curves are beyond what the car will do on its own.")
  w = m.get("wobble_ratio")
  if w is not None:
    if w > WOBBLE_RATIO_HIGH:
      notes.append(f"The wheel made quick back-and-forth corrections about {w}× stronger than the road called for. That is the "
                   "wobble or ping-pong you can feel on straights; it usually means the gain is a little high or the friction/damping a little low.")
      fix = (_FIXED_GAINS if controller == CONTROLLER_CLARITY_EPS else
             "try a slightly lower LatP slider for the speed where it happens." if controller == CONTROLLER_NRDR_PID else
             "try a little less gain or a little more friction/damping.")
      takeaways.append(f"Steering wobble ({w}× the road's demand): {fix}")
    else:
      notes.append(f"Steering was steady, with no unnecessary back-and-forth (ratio {w}, where about 1 is ideal).")
  b = m.get("straight_bias")
  if b is not None and abs(b) > LAT_BIAS_NOTABLE:
    side = "left" if b > 0 else "right"
    notes.append(f"On straight roads the car sat slightly to the {side} of the planned line ({abs(b)} m/s² on average). "
                 "If it feels like a constant pull, a small steering-offset change fixes this, not the gains.")
    takeaways.append(f"Constant {side} lean on straights: adjust the steering offset slightly.")
  if m.get("steer_overrides"):
    notes.append(f"You took the wheel {m['steer_overrides']} time(s) while engaged.")
  quality = f"Steering followed the planned path {_band(m['rmse'], LAT_RMSE_GOOD, LAT_RMSE_FAIR)}"
  if w is not None and w > WOBBLE_RATIO_HIGH:
    quality += ", but with some wobble"
  return f"{quality} over {_fmt_time(m['engaged_s'])} of engaged driving.", notes


def _longitudinal_findings(m, takeaways):
  if m.get("status") != "ok":
    return f"Not enough engaged openpilot speed control to judge ({_fmt_time(m.get('engaged_s', 0))} counted).", []
  notes = [f"The car starts reacting about {m['lag_s']} s after openpilot asks. After allowing for that, it typically stayed "
           f"within {m['rmse']} m/s² of the planned acceleration, {_feel(m['rmse'], LONG_RMSE_GOOD, LONG_RMSE_FAIR)}."]
  g = m.get("gain")
  gain_off = g is not None and not (GAIN_LOW <= g <= GAIN_HIGH)
  if gain_off:
    pct = round(g * 100)
    if g < GAIN_LOW:
      notes.append(f"Overall the car delivered about {pct}% of the acceleration and braking openpilot asked for, so it feels lazier than planned.")
      takeaways.append(f"Speed control under-delivers ({pct}% of the request): the car does less than the planner asks.")
    else:
      notes.append(f"Overall the car delivered about {pct}% of the acceleration and braking openpilot asked for, so it feels sharper than planned.")
      takeaways.append(f"Speed control over-delivers ({pct}% of the request): the car does more than the planner asks.")
  notes.extend(_band_notes(m.get("speed_bands"), "Speed-control response", takeaways))
  bb = m.get("brake_bias")
  if bb is not None:
    if bb > LONG_BIAS_NOTABLE:
      notes.append(f"When braking, the car slowed {bb} m/s² less than planned on average, so it closes on traffic a little more than intended.")
      takeaways.append(f"Braking is lighter than planned by {bb} m/s²: the car arrives a bit hot behind a slowing lead.")
    elif bb < -LONG_BIAS_NOTABLE:
      notes.append(f"When braking, the car slowed {abs(bb)} m/s² more than planned on average, so braking can feel early or strong.")
      takeaways.append(f"Braking is stronger than planned by {abs(bb)} m/s²: stops may feel abrupt.")
    else:
      notes.append("Braking matched the plan.")
  ab = m.get("accel_bias")
  if ab is not None:
    if ab < -LONG_BIAS_NOTABLE:
      notes.append(f"When accelerating, the car pulled away {abs(ab)} m/s² less than planned on average (sluggish).")
      takeaways.append(f"Acceleration is weaker than planned by {abs(ab)} m/s²: pull-away feels sluggish.")
    elif ab > LONG_BIAS_NOTABLE:
      notes.append(f"When accelerating, the car pulled away {ab} m/s² more than planned on average (a surge).")
      takeaways.append(f"Acceleration is stronger than planned by {ab} m/s²: pull-away can surge.")
    else:
      notes.append("Acceleration matched the plan.")
  j = m.get("jerk_p95")
  if j is not None:
    if j > JERK_HIGH:
      notes.append(f"Speed changes were abrupt (peak jerk {j} m/s³, above {JERK_HIGH}). Look at the acceleration profile or the actuator delay.")
      takeaways.append(f"Abrupt speed changes (jerk {j} m/s³): smooth the acceleration profile or check the actuator delay.")
    else:
      notes.append(f"Speed changes were smooth (peak jerk {j} m/s³).")
  if m.get("hard_brakes"):
    notes.append(f"{m['hard_brakes']} hard braking event(s) (harder than {abs(HARD_BRAKE)} m/s²) while engaged; each is listed under "
                 "Moments to check with the car ahead at that time.")
  if m.get("gas_overrides"):
    notes.append(f"You pressed the gas {m['gas_overrides']} time(s) while engaged, usually a sign the car felt slow to you.")
  if m.get("gas_during_brake"):
    notes.append(f"{m['gas_during_brake']} of those presses came while openpilot was braking, which often means the braking "
                 "was not needed. Those are the moments most worth checking.")
    takeaways.append(f"You overrode openpilot's braking {m['gas_during_brake']} time(s). Check those times under Moments to check; "
                     "note whether the car ahead was a real slower car.")
  quality = f"Speed control followed the plan {_band(m['rmse'], LONG_RMSE_GOOD, LONG_RMSE_FAIR)}"
  if gain_off:
    quality += f", but delivered {'less' if g < GAIN_LOW else 'more'} than asked"
  elif j is not None and j > JERK_HIGH:
    quality += ", but felt jerky"
  return f"{quality} over {_fmt_time(m['engaged_s'])} of engaged driving.", notes


def analyze(rows, min_engaged_s=20.0, controller=None, detail=True, cap=EVENTS_PER_KIND, lateral_delay=None,
            git_commit=None):
  """controller: the lateral controller that drove (CONTROLLER_* or None), so advice names settings that apply.
  detail: add the agents' sections (driver takeovers, lateral detail per band); the live 30 s view skips them.
  cap: moments kept per kind (None = all, for the rlog report)."""
  c = _as_arrays(rows)
  t = c["t"]
  seg = _segments(t)
  dt = _dt(t)
  lat = _analyze_lateral(c, seg, dt, min_engaged_s)
  lon = _analyze_longitudinal(c, seg, dt, min_engaged_s)
  lon["radar_vrel_gap"] = agents.vrel_gap_stats(c)
  take = agents.takeovers(c) if detail else None
  if take is not None:
    for e in take["episodes"]:
      e["lateral_controller"], e["git_commit"] = controller, git_commit   # Kevin: episodes compare within one controller
  lat_detail = agents.lateral_detail(c, lateral_delay) if detail else None
  # Plain-language copies for the Steering card (the full blocks stay under driver_takeovers / lateral_detail).
  if take is not None and agents.has(c, "steer_tq"):
    lat["takeovers"] = {k: v for k, v in take["summary"].items() if k != "definition"}
  if lat_detail and lat_detail.get("status") == "ok":
    lat["lane_straight"] = [{"band": b["band"], "median_m": b["lane_straight"]["median"]}
                            for b in lat_detail["bands"] if b.get("lane_straight")]
  events = _events(c, dt, lat, cap=cap, takeover_data=take)
  lon["gas_during_brake"] = sum(1 for e in events if e["kind"] == "gas_during_brake")
  takeaways = []
  lat_summary, lat_notes = _lateral_findings(lat, takeaways, controller)
  lon_summary, lon_notes = _longitudinal_findings(lon, takeaways)
  if not takeaways and (lat.get("status") == "ok" or lon.get("status") == "ok"):
    takeaways.append("Nothing stood out this drive. Small errors are normal; compare a few drives before changing the tune.")
  # Overridden braking is the one finding a single drive can act on (it names times to check), so it goes first.
  takeaways.sort(key=lambda s: not s.startswith("You overrode"))
  duration = float(t[-1] - t[0]) if len(t) > 1 else 0.0
  if lat.get("curve_gain_source") == "wheel angle":
    curve_how = ("Curve response compares the wheel angle openpilot asked for with the one the car reached, so the steer "
                 "ratio does not bias it. ")
  else:
    curve_how = ("Steering 'measured' comes from the steering angle through the vehicle model, so a wrong steer ratio "
                 "shows up as a curve-response error. ")
  return {
    "duration_s": round(duration, 1),
    "samples": int(len(t)),
    "sample_dt_s": round(dt, 3),
    "disengagements": _rising_edges(~(c["enabled"] > 0.5)) if len(t) else 0,
    "controller": controller,
    "takeaways": takeaways[:4],
    "events": events,
    "lateral": {**lat, "summary": lat_summary, "notes": lat_notes},
    "longitudinal": {**lon, "summary": lon_summary, "notes": lon_notes},
    "driver_takeovers": take,
    "lateral_detail": lat_detail,
    "method": ("How this was scored: only moments when openpilot was steering (no hands on the wheel, above "
               f"{LAT_MIN_SPEED * MPH:.0f} mph) or controlling speed (no gas, not stopped) count. The car's response is shifted "
               f"by its measured reaction delay before it is compared with the request. {curve_how}Tight turns (wheel past "
               f"{TURN_MIN_DEG:.0f}° under 25 mph) are scored on wheel angle without that shift, the way the lateral scorecard "
               "scores them. These are heuristics from one drive, not a verdict on the tune."),
  }


def overview(rows, buckets=1200):
  """Bucket-averaged series for a whole-drive chart, plus the per-bucket worst error."""
  c = _as_arrays(rows)
  n = len(c["t"])
  if n == 0:
    return {"t": [], "series": {}}
  edges = np.linspace(0, n, min(buckets, n) + 1).astype(int)
  out = {k: [] for k in ("t", "v", "lat_des", "lat_act", "long_des", "long_act", "lat_active", "long_active",
                         "lat_err_max", "long_err_max")}
  t0 = c["t"][0]
  for s, e in zip(edges[:-1], edges[1:]):
    if e <= s:
      continue
    sl = slice(s, e)
    out["t"].append(round(float(np.mean(c["t"][sl]) - t0), 2))
    for k in ("v", "lat_des", "lat_act", "long_des", "long_act"):
      out[k].append(round(float(np.mean(c[k][sl])), 3))
    out["lat_active"].append(round(float(np.mean(c["lat_active"][sl])), 2))
    out["long_active"].append(round(float(np.mean(c["long_active"][sl])), 2))
    out["lat_err_max"].append(round(float(np.max(np.abs(c["lat_act"][sl] - c["lat_des"][sl]))), 3))
    out["long_err_max"].append(round(float(np.max(np.abs(c["long_act"][sl] - c["long_des"][sl]))), 3))
  return out


def window(rows, start_s, end_s, max_points=3000, t0=None):
  """Full-resolution rows between start_s and end_s (seconds from the drive's first sample, t0 when rows is itself
  only part of the drive)."""
  data = np.asarray(rows, dtype=float).reshape(-1, len(COLUMNS))
  if not len(data):
    return []
  t0 = data[0, 0] if t0 is None else t0
  rel = data[:, 0] - t0
  sel = data[(rel >= start_s) & (rel <= end_s)]
  stride = max(1, int(np.ceil(len(sel) / max_points)))
  sel = sel[::stride].copy()
  sel[:, 0] -= t0
  return [_json_row(r) for r in np.round(sel, 4).tolist()]


def _json_row(row):
  """NaN ("not recorded") becomes null: browsers' JSON.parse rejects NaN."""
  return [None if isinstance(x, float) and x != x else x for x in row]


def _json_safe(x):
  if isinstance(x, dict):
    return {k: _json_safe(v) for k, v in x.items()}
  if isinstance(x, (list, tuple)):
    return [_json_safe(v) for v in x]
  if isinstance(x, (float, np.floating)):
    return None if not np.isfinite(x) else float(x)
  if isinstance(x, (np.integer, np.bool_)):
    return x.item()
  return x


# =====================================================================================================
# Sampling
# =====================================================================================================

def _f(x, default=0.0):
  try:
    v = float(x)
    return v if np.isfinite(v) else default
  except Exception:
    return default


def build_row(sm):
  cs = sm["controlsState"]
  cc = sm["carControl"]
  car_state = sm["carState"]
  plan = sm["longitudinalPlan"]
  v = max(0.0, _f(getattr(car_state, "vEgo", 0.0)))
  have_cc = sm.recv_frame["carControl"] > 0
  lat_p = lat_i = lat_d = lat_f = 0.0
  lat_sat = 0
  ang_des = 0.0
  ang_ok = 0
  try:
    lcs = cs.lateralControlState
    which = lcs.which()
    st = getattr(lcs, which)
    lat_sat = int(bool(getattr(st, "saturated", False)))
    if which in ("pidState", "torqueState"):
      lat_p, lat_i, lat_f = _f(st.p), _f(st.i), _f(st.f)
      lat_d = _f(getattr(st, "d", 0.0)) if which == "torqueState" else 0.0
    if which in ("pidState", "angleState"):
      # Both Honda controllers (LatControlPID, LatControlHondaEps) log pidState with the target wheel angle,
      # offset included, in the same frame as carState.steeringAngleDeg.
      ang_des = _f(st.steeringAngleDesiredDeg)
      ang_ok = 1
  except Exception:
    pass
  lead_d = lead_v = 0.0
  lead_src = 0
  try:
    if sm.recv_frame["radarState"] > 0:
      lead = sm["radarState"].leadOne
      if lead.status:
        lead_d, lead_v = _f(lead.dRel), _f(lead.vLead)
        lead_src = 1 if lead.radar else 2
  except Exception:
    pass
  try:
    long_state = LONG_STATES.get(str(cs.longControlState), 0)
  except Exception:
    long_state = 0
  t = sm.logMonoTime["longitudinalPlan"] / 1e9 if sm.logMonoTime["longitudinalPlan"] else time.monotonic()
  base = [
    round(t, 3), round(v, 3), round(_f(getattr(car_state, "aEgo", 0.0)), 3),
    int(have_cc and bool(cc.enabled)), int(have_cc and bool(cc.latActive)), int(have_cc and bool(cc.longActive)),
    int(bool(getattr(car_state, "steeringPressed", False))), int(bool(getattr(car_state, "gasPressed", False))),
    int(bool(getattr(car_state, "brakePressed", False))),
    round(_f(cs.desiredCurvature) * v * v, 4), round(_f(cs.curvature) * v * v, 4),
    round(_f(getattr(plan, "aTarget", 0.0)), 4), round(_f(getattr(car_state, "aEgo", 0.0)), 4), long_state,
    round(lat_p, 4), round(lat_i, 4), round(lat_d, 4), round(lat_f, 4),
    round(_f(cs.upAccelCmd), 4), round(_f(cs.uiAccelCmd), 4), round(_f(cs.ufAccelCmd), 4), lat_sat,
    round(ang_des, 2), round(_f(getattr(car_state, "steeringAngleDeg", 0.0)), 2), ang_ok,
    round(lead_d, 2), round(lead_v, 2), lead_src,
  ]
  return base + _agent_columns(sm, cs, cc, have_cc, car_state, plan, t)


NAN = float("nan")


def _got(sm, name):
  try:
    return sm.recv_frame[name] > 0
  except (KeyError, AttributeError):
    return False


def _agent_columns(sm, cs, cc, have_cc, car_state, plan, t):
  """The NAN_COLUMNS, in COLUMNS order. A message that never arrived gives NaN (not recorded), not 0."""
  o = {}
  o["steer_tq"] = _f(getattr(car_state, "steeringTorque", NAN), NAN)
  o["steer_tq_eps"] = _f(getattr(car_state, "steeringTorqueEps", NAN), NAN)
  o["steer_rate"] = _f(getattr(car_state, "steeringRateDeg", NAN), NAN)
  o["blinker"] = int(bool(getattr(car_state, "leftBlinker", False)) or bool(getattr(car_state, "rightBlinker", False)))
  o["standstill"] = int(bool(getattr(car_state, "standstill", False)))
  o["tq_req"] = _f(cc.actuators.torque, NAN) if have_cc else NAN
  o["a_cmd"] = _f(cc.actuators.accel, NAN) if have_cc else NAN
  o["tq_out"] = _f(sm["carOutput"].actuatorsOutput.torque, NAN) if _got(sm, "carOutput") else NAN
  o["lat_out"] = o["ang_err"] = o["pid_active"] = NAN
  try:
    lcs = cs.lateralControlState
    if lcs.which() == "pidState":
      ps = lcs.pidState
      o["lat_out"], o["ang_err"], o["pid_active"] = _f(ps.output, NAN), _f(ps.angleError, NAN), int(bool(ps.active))
  except Exception:
    pass
  o["ff_active"] = o["ff_w"] = o["ff"] = NAN
  if _got(sm, "starpilotLateralState"):
    try:
      ls = sm["starpilotLateralState"]
      o["ff_active"], o["ff_w"], o["ff"] = int(bool(ls.epsFfActive)), _f(ls.epsFfWeight, NAN), _f(ls.epsFfFeedforward, NAN)
    except Exception:
      pass
  o["lane_off"] = o["lane_w"] = o["lane_prob"] = o["lane_prob_l"] = o["lane_prob_r"] = o["lane_change"] = NAN
  o["mlead_p"] = o["mlead_x"] = o["mlead_y"] = o["mlead_v"] = o["mlead_a"] = NAN
  if _got(sm, "modelV2"):
    try:
      md = sm["modelV2"]
      ll, probs = md.laneLines, md.laneLineProbs
      if len(ll) >= 3 and len(ll[1].y) and len(ll[2].y) and len(probs) >= 3:
        y1, y2 = float(ll[1].y[0]), float(ll[2].y[0])
        o["lane_off"], o["lane_w"] = (y1 + y2) / 2.0, y2 - y1   # y is + = right, so the centre's y = car left of it
        o["lane_prob_l"], o["lane_prob_r"] = float(probs[1]), float(probs[2])
        o["lane_prob"] = min(o["lane_prob_l"], o["lane_prob_r"])
      o["lane_change"] = int(md.meta.laneChangeState.raw)
      if len(md.leadsV3):
        ld = md.leadsV3[0]
        o["mlead_p"] = _f(ld.prob, NAN)
        o["mlead_x"] = _f(ld.x[0], NAN) if len(ld.x) else NAN
        o["mlead_y"] = _f(ld.y[0], NAN) if len(ld.y) else NAN
        o["mlead_v"] = _f(ld.v[0], NAN) if len(ld.v) else NAN
        o["mlead_a"] = _f(ld.a[0], NAN) if len(ld.a) else NAN
    except Exception:
      pass
  try:
    cs_mono = sm.logMonoTime["controlsState"]
    o["cs_age_ms"] = max(0.0, (t * 1e9 - cs_mono) / 1e6) if cs_mono else NAN
  except Exception:
    o["cs_age_ms"] = NAN
  o["should_stop"] = int(bool(getattr(plan, "shouldStop", False)))
  o["fcw"] = int(bool(getattr(plan, "fcw", False)))
  o["has_lead"] = int(bool(getattr(plan, "hasLead", False)))
  o["exp_mode"] = int(bool(sm["selfdriveState"].experimentalMode)) if _got(sm, "selfdriveState") else NAN
  o["t_follow"] = o["tracking_lead"] = NAN
  if _got(sm, "starpilotPlan"):
    try:
      sp = sm["starpilotPlan"]
      o["t_follow"], o["tracking_lead"] = _f(sp.tFollow, NAN), int(bool(sp.trackingLead))
    except Exception:
      pass
  for k in ("lead_id", "lead_y", "lead_vrel", "lead_a", "lead_prob", "lead_meas", "lead_vrr",
            "lead2_on", "lead2_d", "lead2_v", "lead2_id"):
    o[k] = NAN
  if _got(sm, "radarState"):
    try:
      rs = sm["radarState"]
      l1, l2 = rs.leadOne, rs.leadTwo
      if l1.status:
        o["lead_id"], o["lead_y"], o["lead_vrel"] = _f(l1.radarTrackId, -1), _f(l1.yRel, NAN), _f(l1.vRel, NAN)
        o["lead_a"], o["lead_prob"] = _f(l1.aLeadK, NAN), _f(l1.modelProb, NAN)
        o["lead_meas"], o["lead_vrr"] = int(bool(l1.measuredRadar)), _f(l1.vRelRangeDerived, NAN)
      o["lead2_on"] = int(bool(l2.status))
      if l2.status:
        o["lead2_d"], o["lead2_v"], o["lead2_id"] = _f(l2.dRel, NAN), _f(l2.vLead, NAN), _f(l2.radarTrackId, -1)
    except Exception:
      pass
  _request_columns(sm, o, cs, cc, have_cc, car_state, plan)
  return [round(o[k], 4) if isinstance(o[k], float) and o[k] == o[k] else o[k] for k in _AGENT_COLS]


def _field(msg, name, default=NAN):
  return _f(getattr(msg, name, default), default)


def _request_columns(sm, o, cs, cc, have_cc, car_state, plan):
  """The 2026-09-29 columns. Each message is read in its own try so one missing field cannot blank the others."""
  o["fault_t"] = int(bool(getattr(car_state, "steerFaultTemporary", False)))
  o["fault_p"] = int(bool(getattr(car_state, "steerFaultPermanent", False)))
  o["v_cruise"] = _field(car_state, "vCruise")
  o["des_curv"] = _field(cs, "desiredCurvature") * 1000.0
  o["curv"] = _field(cs, "curvature") * 1000.0
  o["pitch"] = NAN
  if have_cc:
    try:
      ned = cc.orientationNED
      o["pitch"] = _f(ned[1], NAN) if len(ned) >= 2 else NAN
    except Exception:
      pass
  o["ff_r5"] = o["ff_load"] = o["ff_rate"] = NAN
  if _got(sm, "starpilotLateralState"):
    try:
      ls = sm["starpilotLateralState"]
      o["ff_r5"], o["ff_load"], o["ff_rate"] = _field(ls, "epsFfR5"), _field(ls, "epsFfLoad"), _field(ls, "epsFfDesiredRate")
    except Exception:
      pass
  o["ang_off"] = o["roll"] = NAN
  if _got(sm, "liveParameters"):
    try:
      lp = sm["liveParameters"]
      o["ang_off"], o["roll"] = _field(lp, "angleOffsetDeg"), _field(lp, "roll")
    except Exception:
      pass
  o["lat_delay"] = _field(sm["liveDelay"], "lateralDelay") if _got(sm, "liveDelay") else NAN
  o["plan_src"] = o["allow_thr"] = o["allow_brk"] = o["cl_cap"] = o["geo_acc"] = NAN
  try:
    o["plan_src"] = int(plan.longitudinalPlanSource.raw)
    o["allow_thr"], o["allow_brk"] = int(bool(plan.allowThrottle)), int(bool(plan.allowBrake))
    o["cl_cap"], o["geo_acc"] = _field(plan, "closeLeadBrakeCap"), _field(plan, "leadGeometryRequiredAccel")
  except Exception:
    pass
  o["lead_dpath"] = o["lead_tau"] = NAN
  if _got(sm, "radarState"):
    try:
      l1 = sm["radarState"].leadOne
      if l1.status:
        o["lead_dpath"], o["lead_tau"] = _field(l1, "dPath"), _field(l1, "aLeadTau")
    except Exception:
      pass
  o["red_light"] = o["forcing_stop"] = o["road_curv"] = o["stop_len"] = NAN
  if _got(sm, "starpilotPlan"):
    try:
      sp = sm["starpilotPlan"]
      o["red_light"], o["forcing_stop"] = int(bool(sp.redLight)), int(bool(sp.forcingStop))
      o["road_curv"], o["stop_len"] = _field(sp, "roadCurvature"), _field(sp, "approachStopLength")
    except Exception:
      pass
  o["gl_gf"] = o["gl_wf"] = o["gl_err"] = o["gl_learn"] = o["gl_gf_raw"] = NAN
  if _got(sm, "starpilotCarState"):
    try:
      scs = sm["starpilotCarState"]
      if scs.gasLearnerAvailable:
        o["gl_gf"], o["gl_wf"] = _field(scs, "gasLearnerGasFactor"), _field(scs, "gasLearnerWindFactor")
        o["gl_err"], o["gl_learn"] = _field(scs, "gasLearnerError"), int(bool(scs.gasLearnerLearning))
        o["gl_gf_raw"] = _field(scs, "gasLearnerGasFactorRaw")
    except Exception:
      pass
  o["adj_l"] = o["adj_r"] = o["adj_stop"] = NAN
  if _got(sm, "starpilotRadarState"):
    try:
      sr = sm["starpilotRadarState"]
      o["adj_l"], o["adj_r"] = int(bool(sr.leadLeft.status)), int(bool(sr.leadRight.status))
      o["adj_stop"] = int(bool(sr.adjacentStopped.status))
    except Exception:
      pass


def _fmt(x):
  # Numpy scalars repr as "np.float64(...)", which read_rows cannot parse back.
  if isinstance(x, (bool, np.bool_, int, np.integer)):
    return str(int(x))
  return repr(float(x))


class DrivePlots:
  SERVICES = ["controlsState", "carControl", "carState", "longitudinalPlan", "radarState", "carOutput", "modelV2",
              "selfdriveState", "starpilotPlan", "starpilotLateralState", "liveParameters", "liveDelay", "starpilotCarState",
              "starpilotRadarState"]

  def __init__(self, root, is_onroad, submaster_factory=None, clock=time.monotonic, controller_fn=None,
               meta_fn=None, route_fn=None, publisher_factory=None):
    self.root = Path(root)
    self.meta_fn = meta_fn               # -> dict snapshot of car/tune for an automatic recording
    self.route_fn = route_fn             # -> loggerd's CurrentRoute, or None before it is set
    self._publisher_factory = publisher_factory
    self._pm = None
    self._auto_thread = None
    self._skip_this_drive = False        # the driver stopped the automatic recording; wait for the next drive
    self.is_onroad = is_onroad
    self.clock = clock
    self.controller_fn = controller_fn   # -> CONTROLLER_* or None, for the live analysis's advice
    self._submaster_factory = submaster_factory
    self.lock = threading.Lock()
    self.thread = None
    self.last_client = -1e9
    self.buffer = deque(maxlen=int(LIVE_BUFFER_S / NOMINAL_DT))
    self.seq = 0
    self.last_sample_wall = 0.0
    self.last_error = ""
    self.rec = None            # dict while recording
    self._live_cache = (-1, None)
    self._sleep = time.sleep
    self._heavy = threading.Lock()      # one whole-session read at a time: taps on several moments queue, not stack

  # ---------------- lifecycle ----------------
  def _make_submaster(self):
    if self._submaster_factory is not None:
      return self._submaster_factory(self.SERVICES)
    from cereal import messaging
    return messaging.SubMaster(self.SERVICES, poll="longitudinalPlan")

  def touch(self):
    with self.lock:
      self.last_client = self.clock()
      self._ensure_thread_locked()

  def _ensure_thread_locked(self):
    if self.thread is not None and self.thread.is_alive():
      return
    self.thread = threading.Thread(target=self._run, name="galaxy-drive-plots", daemon=True)
    self.thread.start()

  def _should_run(self):
    with self.lock:
      return self.rec is not None or (self.clock() - self.last_client) < CLIENT_IDLE_TIMEOUT_S

  def _run(self):
    try:
      sm = self._make_submaster()
    except Exception as e:
      with self.lock:
        self.last_error = f"subscribe failed: {e}"
        self.thread = None
      return
    last_onroad_check = -1e9
    while self._should_run():
      try:
        self.step(sm)
        now = self.clock()
        if now - last_onroad_check >= 1.0:
          last_onroad_check = now
          self._check_autostop(now)
      except Exception as e:
        with self.lock:
          self.last_error = str(e)
        time.sleep(0.1)
    with self.lock:
      self.thread = None

  def step(self, sm):
    sm.update(100)
    if not sm.updated["longitudinalPlan"]:
      return False
    row = build_row(sm)
    with self.lock:
      self.seq += 1
      self.buffer.append((self.seq, row))
      self.last_sample_wall = time.time()
      self.last_error = ""
      rec = self.rec
      if rec is not None:
        rec["writer"].writerow([_fmt(x) for x in row])
        rec["rows"] += 1
        if rec["first_t"] is None:
          rec["first_t"] = row[0]
          rec["first_wall"] = self.last_sample_wall
        rec["last_t"] = row[0]
        if rec["rows"] % FLUSH_EVERY_ROWS == 0:
          rec["file"].flush()
    return True

  def _check_autostop(self, now):
    with self.lock:
      rec = self.rec
    if rec is None:
      return
    onroad = bool(self.is_onroad())
    reason = None
    with self.lock:
      if onroad:
        rec["seen_onroad"] = True
        rec["offroad_since"] = None
      elif rec["seen_onroad"]:
        if rec["offroad_since"] is None:
          rec["offroad_since"] = now
        elif now - rec["offroad_since"] >= OFFROAD_AUTOSTOP_S:
          reason = "drive ended"
      if reason is None and now - rec["started_mono"] >= MAX_RECORDING_S:
        reason = "time limit"
    if reason:
      self.stop_recording(reason=reason)

  # ---------------- recording ----------------
  def _session_dir(self, session_id):
    session_id = str(session_id)
    if not session_id.isalnum():
      raise ValueError("bad session id")
    return self.root / session_id

  def start_recording(self, meta=None):
    with self.lock:
      if self.rec is not None:
        return self._rec_status_locked()
      self.root.mkdir(parents=True, exist_ok=True)
      session_id = time.strftime("%Y%m%d%H%M%S", time.localtime())
      d = self.root / session_id
      suffix = 0
      while d.exists():
        suffix += 1
        d = self.root / f"{session_id}{suffix}"
      d.mkdir(parents=True)
      m = dict(meta or {})
      m.update({"id": d.name, "started_at": time.time(), "status": "recording", "columns": COLUMNS})
      (d / "meta.json").write_text(json.dumps(m, indent=1))
      f = open(d / "samples.csv", "w", newline="")
      w = csv.writer(f)
      w.writerow(COLUMNS)
      self.rec = {"id": d.name, "dir": d, "file": f, "writer": w, "rows": 0, "first_t": None, "last_t": None,
                  "started_mono": self.clock(), "seen_onroad": bool(self.is_onroad()), "offroad_since": None,
                  "meta": m, "route": m.get("route"), "start_published": False, "last_scan": self.clock(),
                  "last_summary": self.clock(), "published": [], "counts": {}}
      self._ensure_thread_locked()
      return self._rec_status_locked()

  def stop_recording(self, reason="stopped", background=True):
    with self.lock:
      rec = self.rec
      self.rec = None
    if rec is None:
      return None
    if reason == "stopped by user":
      self._skip_this_drive = True
    self._publish_end(rec, reason)
    try:
      rec["file"].flush()
      rec["file"].close()
    except Exception:
      pass
    if rec["rows"] == 0:
      # Nothing arrived (openpilot was not running); an empty session would only clutter the list.
      shutil.rmtree(rec["dir"], ignore_errors=True)
      return {"id": rec["id"], "rows": 0, "reason": reason, "discarded": True}
    # Wall time of the first sample: analysis times count from it, so the UI can show a moment's time of day.
    self._update_meta(rec["dir"], {"status": "analyzing", "stopped_at": time.time(), "stop_reason": reason,
                                   "first_sample_at": rec.get("first_wall")})
    if background:
      threading.Thread(target=self._finalize_and_prune, args=(rec["dir"], True), daemon=True).start()
    else:
      self._finalize_and_prune(rec["dir"])
    return {"id": rec["id"], "rows": rec["rows"], "reason": reason}

  def _wait_until_parked(self):
    """The whole-drive analysis waits until the car is offroad, so it never competes with openpilot for RAM or CPU
    while driving (a stop by hand, or MAX_RECORDING_S, can happen mid-drive)."""
    while True:
      try:
        if not self.is_onroad():
          return
      except Exception:
        return
      self._sleep(FINALIZE_ONROAD_POLL_S)

  def _finalize_and_prune(self, d, wait_until_parked=False):
    if wait_until_parked:
      self._wait_until_parked()
    self.finalize(d)
    self.prune_auto_sessions()

  def _update_meta(self, d, updates):
    p = d / "meta.json"
    try:
      m = json.loads(p.read_text())
    except Exception:
      m = {"id": d.name}
    m.update(updates)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1))
    os.replace(tmp, p)
    return m

  def finalize(self, d):
    with self._heavy:
      try:
        self._finalize(Path(d))
      finally:
        release_freed_memory()

  def _finalize(self, d):
    try:
      rows = read_rows(d)
      try:
        m = json.loads((d / "meta.json").read_text())
      except Exception:
        m = {}
      result = analyze(rows, controller=m.get("lateral_controller"), lateral_delay=m.get("lateral_delay"),
                       git_commit=m.get("git_commit"))
      result["overview"] = overview(rows)
      tmp = d / "analysis.tmp"
      tmp.write_text(json.dumps(_json_safe(result)))
      os.replace(tmp, d / "analysis.json")
      raw = d / "samples.csv"
      if raw.exists():
        with open(raw, "rb") as src, gzip.open(d / "samples.csv.gz.tmp", "wb") as dst:
          shutil.copyfileobj(src, dst)
        os.replace(d / "samples.csv.gz.tmp", d / "samples.csv.gz")
        raw.unlink()
      self._update_meta(d, {"status": "done", "duration_s": result["duration_s"],
                            "lateral_summary": result["lateral"]["summary"],
                            "longitudinal_summary": result["longitudinal"]["summary"]})
    except Exception as e:
      self._update_meta(d, {"status": "error", "error": str(e)})

  def recover_interrupted(self):
    """A session left 'recording'/'analyzing' by a Galaxy restart is finalized with what was written."""
    if not self.root.exists():
      return
    with self.lock:
      active = self.rec["id"] if self.rec else None
    for d in self.root.iterdir():
      if not d.is_dir() or d.name == active:
        continue
      try:
        m = json.loads((d / "meta.json").read_text())
      except Exception:
        continue
      if m.get("status") in ("recording", "analyzing") and not (d / "analysis.json").exists():
        self._update_meta(d, {"status": "analyzing", "stop_reason": "interrupted (Galaxy restarted)"})
        self._wait_until_parked()
        self.finalize(d)

  # ---------------- automatic recording ----------------
  def settings(self):
    out = dict(DEFAULT_SETTINGS)
    try:
      saved = json.loads((self.root / "settings.json").read_text())
      out.update({k: bool(saved[k]) for k in DEFAULT_SETTINGS if k in saved})
    except Exception:
      pass
    return out

  def set_settings(self, updates):
    cur = self.settings()
    cur.update({k: bool(v) for k, v in (updates or {}).items() if k in DEFAULT_SETTINGS})
    self.root.mkdir(parents=True, exist_ok=True)
    tmp = self.root / "settings.tmp"
    tmp.write_text(json.dumps(cur))
    os.replace(tmp, self.root / "settings.json")
    return cur

  def start_auto(self):
    """Start the watcher that records every drive (Galaxy calls this once at startup)."""
    with self.lock:
      if self._auto_thread is not None and self._auto_thread.is_alive():
        return
      self._auto_thread = threading.Thread(target=self._auto_loop, name="galaxy-drive-plots-auto", daemon=True)
      self._auto_thread.start()

  def _auto_loop(self):
    while True:
      try:
        self.auto_tick()
      except Exception as e:
        with self.lock:
          self.last_error = f"auto: {e}"
      time.sleep(AUTO_CHECK_S)

  def auto_tick(self):
    """One watcher step: start a recording when a drive starts, then keep the drive's rlog copy up to date."""
    onroad = bool(self.is_onroad())
    settings = self.settings()
    with self.lock:
      rec = self.rec
    if not onroad:
      self._skip_this_drive = False
    elif rec is None and settings["auto_record"] and not self._skip_this_drive:
      meta = {}
      if self.meta_fn is not None:
        try:
          meta = dict(self.meta_fn() or {})
        except Exception:
          meta = {}
      meta["auto"] = True
      self.start_recording(meta)
      with self.lock:
        rec = self.rec
    if rec is None:
      return
    if not rec.get("route") and self.route_fn is not None:
      try:
        route = self.route_fn()
      except Exception:
        route = None
      if route:
        rec["route"] = route
        rec["meta"]["route"] = route
        self._update_meta(rec["dir"], {"route": route})
    if settings["publish_to_log"] and onroad:
      self._publish_tick(rec)

  def prune_auto_sessions(self):
    """Drop the oldest automatic sessions past AUTO_KEEP_SESSIONS / AUTO_KEEP_BYTES. Manual ones are kept."""
    if not self.root.exists():
      return []
    with self.lock:
      active = self.rec["id"] if self.rec else None
    auto = []
    for d in self.root.iterdir():
      if not d.is_dir() or d.name == active:
        continue
      try:
        m = json.loads((d / "meta.json").read_text())
      except Exception:
        continue
      if m.get("auto") and m.get("status") in ("done", "error"):
        size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
        auto.append((m.get("started_at") or 0, d, size))
    auto.sort(key=lambda x: x[0], reverse=True)
    removed, total = [], 0
    for i, (_, d, size) in enumerate(auto):
      total += size
      if i >= AUTO_KEEP_SESSIONS or total > AUTO_KEEP_BYTES:
        shutil.rmtree(d, ignore_errors=True)
        removed.append(d.name)
    return removed

  # ---------------- the drive's rlog copy ----------------
  def _publish(self, kind, body):
    if self._pm is None:
      if self._publisher_factory is not None:
        self._pm = self._publisher_factory()
      else:
        from cereal import messaging
        self._pm = messaging.PubMaster([RLOG_SERVICE])
    now_ns = int(time.monotonic() * 1e9)
    payload = json.dumps(_json_safe({"schema": RLOG_SCHEMA, "type": kind, "mono_ns": now_ns, **body}),
                         separators=(",", ":")).encode()
    if self._publisher_factory is not None:
      self._pm.send(RLOG_SERVICE, payload)
      return payload
    from cereal import messaging
    msg = messaging.new_message(None, valid=True)
    msg.customReservedRawData0 = payload
    self._pm.send(RLOG_SERVICE, msg)
    return payload

  def _publish_tick(self, rec):
    now = self.clock()
    if not rec["start_published"]:
      rec["start_published"] = True
      m = rec["meta"]
      self._publish("start", {"session": rec["id"], "auto": bool(m.get("auto")), "route": rec.get("route"),
                              "car": m.get("car"), "lateral_controller": m.get("lateral_controller"),
                              "lateral_delay": m.get("lateral_delay"), "git_commit": m.get("git_commit"),
                              "git_branch": m.get("git_branch"), "openpilot_longitudinal": m.get("openpilot_longitudinal"),
                              "tune": m.get("tune", {}), "columns": COLUMNS})
    if now - rec["last_scan"] >= PUBLISH_SCAN_S:
      rec["last_scan"] = now
      self._scan_and_publish(rec)
    if now - rec["last_summary"] >= SUMMARY_EVERY_S:
      rec["last_summary"] = now
      self._publish_summary(rec)

  def _recent_arrays(self, rec):
    with self.lock:
      rows = [r for _, r in self.buffer]
    first = rec.get("first_t")
    if first is not None:
      rows = [r for r in rows if r[0] >= first]
    return _as_arrays(rows) if len(rows) > 1 else None

  def _seen(self, rec, kind, mono_s):
    for k, m in rec["published"]:
      if k == kind and abs(m - mono_s) < PUBLISH_DEDUPE_S:
        return True
    rec["published"].append((kind, mono_s))
    rec["published"] = rec["published"][-400:]
    rec["counts"][kind] = rec["counts"].get(kind, 0) + 1
    return False

  def _scan_and_publish(self, rec):
    """Publish the moments and takeovers that have finished since the last scan. Returns how many."""
    c = self._recent_arrays(rec)
    if c is None:
      return 0
    t = c["t"]
    t0 = rec["first_t"] if rec["first_t"] is not None else t[0]
    lo = t[0] + (PUBLISH_EDGE_S if t[0] > t0 + 0.5 else -1.0)
    hi = t[-1] - PUBLISH_MARGIN_S
    sent = 0
    for e in agents.long_moments(c, t0=t0) + agents.lat_moments(c, t0=t0):
      if lo <= e["mono_s"] <= hi and not self._seen(rec, e["kind"], e["mono_s"]):
        self._publish("moment", {"session": rec["id"], "route": rec.get("route"), **e})
        sent += 1
    for e in agents.takeovers(c, t0=t0)["episodes"]:
      release_mono = e["mono_s"] + (e["release_t"] - e["t"])
      if lo <= e["mono_s"] and release_mono + TAKEOVER_TAIL_S <= t[-1] and not self._seen(rec, "takeover", e["mono_s"]):
        e = {k: v for k, v in e.items() if not k.startswith("i_") or k in ("i_press", "i_press_min", "i_release", "i_release_1s")}
        self._publish("takeover", {"session": rec["id"], "route": rec.get("route"), **e,
                                   "lateral_controller": rec["meta"].get("lateral_controller"),
                                   "git_commit": rec["meta"].get("git_commit")})
        sent += 1
    return sent

  def _publish_summary(self, rec, kind="summary", reason=None):
    body = {"session": rec["id"], "route": rec.get("route"), "rows": rec["rows"],
            "elapsed_s": round((rec["last_t"] - rec["first_t"]) if rec["first_t"] is not None else 0.0, 1),
            "counts": dict(rec["counts"])}
    if reason:
      body["reason"] = reason
    with self.lock:
      rows = [r for _, r in self.buffer]
    if len(rows) > 1:
      try:
        a = analyze(rows, min_engaged_s=10.0, controller=rec["meta"].get("lateral_controller"), detail=False)
        body["last_window_s"] = LIVE_BUFFER_S
        body["lateral"] = a["lateral"]["summary"]
        body["longitudinal"] = a["longitudinal"]["summary"]
      except Exception as e:
        body["error"] = str(e)
    return self._publish(kind, body)

  def _publish_end(self, rec, reason):
    if not rec.get("start_published") or not self.settings()["publish_to_log"]:
      return
    try:
      self._scan_and_publish(rec)
      self._publish_summary(rec, kind="end", reason=reason)
    except Exception:
      pass

  # ---------------- queries ----------------
  def _rec_status_locked(self):
    if self.rec is None:
      return None
    r = self.rec
    elapsed = (r["last_t"] - r["first_t"]) if r["first_t"] is not None else 0.0
    return {"id": r["id"], "rows": r["rows"], "elapsed_s": round(elapsed, 1)}

  def live(self, since=0):
    self.touch()
    with self.lock:
      rows = [[s, *_json_row(r)] for s, r in self.buffer if s > since]
      seq = self.seq
      age = time.time() - self.last_sample_wall if self.last_sample_wall else None
      rec = self._rec_status_locked()
      err = self.last_error
      cache_seq, cache = self._live_cache
      window_rows = None
      if cache_seq != seq:
        last_t = self.buffer[-1][1][0] if self.buffer else 0.0
        window_rows = [r for _, r in self.buffer if r[0] >= last_t - LIVE_WINDOW_S]
    if window_rows is not None:
      cache = None
      if len(window_rows) > 1:
        controller = None
        if self.controller_fn is not None:
          try:
            controller = self.controller_fn()
          except Exception:
            controller = None
        a = analyze(window_rows, min_engaged_s=10.0, controller=controller, detail=False)
        cache = {k: a[k] for k in ("lateral", "longitudinal", "controller")}
      with self.lock:
        self._live_cache = (seq, cache)
    return {
      "columns": ["seq", *COLUMNS],
      "rows": rows,
      "seq": seq,
      "sampleAgeSeconds": None if age is None else round(age, 3),
      "stale": age is None or age > 1.5,
      "recording": rec,
      "lastError": err,
      "liveAnalysis": cache,
      "liveWindowSeconds": LIVE_WINDOW_S,
    }

  def list_sessions(self):
    out = []
    if not self.root.exists():
      return out
    for d in sorted(self.root.iterdir(), reverse=True):
      if not d.is_dir():
        continue
      try:
        m = json.loads((d / "meta.json").read_text())
      except Exception:
        continue
      out.append({k: m.get(k) for k in ("id", "started_at", "stopped_at", "status", "stop_reason", "duration_s",
                                        "lateral_summary", "longitudinal_summary", "car", "error", "auto", "route")})
    return out

  def get_session(self, session_id):
    d = self._session_dir(session_id)
    if not d.is_dir():
      return None
    m = json.loads((d / "meta.json").read_text())
    analysis = None
    if (d / "analysis.json").exists():
      analysis = json.loads((d / "analysis.json").read_text())
    return {"meta": m, "analysis": analysis}

  def get_window(self, session_id, start_s, end_s):
    d = self._session_dir(session_id)
    with self._heavy:
      rows, t0 = read_rows(d, start_s, end_s)
      out = window(rows, start_s, end_s, t0=t0)
      del rows
      release_freed_memory()
    return {"columns": COLUMNS, "rows": out}

  def csv_path(self, session_id):
    d = self._session_dir(session_id)
    for name in ("samples.csv.gz", "samples.csv"):
      if (d / name).exists():
        return d / name
    return None

  def delete_session(self, session_id):
    d = self._session_dir(session_id)
    with self.lock:
      if self.rec is not None and self.rec["id"] == d.name:
        return False
    if not d.is_dir():
      return False
    shutil.rmtree(d)
    return True


_M_ARENA_MAX = -8


def _libc():
  try:
    import ctypes
    return ctypes.CDLL("libc.so.6")
  except (OSError, ImportError):
    return None


def limit_malloc_arenas(n=2):
  """Cap glibc at n malloc arenas. Each Flask request thread otherwise gets its own, and freed memory in them is
  not returned: the_galaxy held seven ~33 MB arenas after one Plots visit (device, 2026-09-28). Call before the
  server starts its threads. A no-op off glibc."""
  libc = _libc()
  if libc is None:
    return False
  try:
    return bool(libc.mallopt(_M_ARENA_MAX, int(n)))
  except AttributeError:
    return False


def release_freed_memory():
  """Hand memory freed by a large read back to the system (glibc malloc_trim). A no-op off glibc."""
  libc = _libc()
  try:
    if libc is not None:
      libc.malloc_trim(0)
  except AttributeError:
    pass


_READ_BLOCK = 2048


def read_rows(d, start_s=None, end_s=None):
  """Read a session's samples, tolerating a torn last line from an interrupted write.

  Streams the file into one float array: reading the whole text and a list of Python floats first cost ~110 MB for a
  20-minute drive, several zooms at once took the_galaxy to 667 MB on the device (route 294), and glibc kept most of
  it. With start_s/end_s (seconds from the drive's first sample) only that window's rows are kept, and the return is
  (rows, t0) so the caller can place them in the drive."""
  d = Path(d)
  windowed = start_s is not None
  empty = np.zeros((0, len(COLUMNS)))
  if (d / "samples.csv.gz").exists():
    f = gzip.open(d / "samples.csv.gz", "rt", newline="")
  elif (d / "samples.csv").exists():
    f = open(d / "samples.csv", newline="")
  else:
    return (empty, None) if windowed else empty
  # Fixed blocks, joined one at a time at the end: growing one array by doubling held ~3 copies at once
  # (a 2-hour drive peaked at +250 MB).
  blocks, block, k, n, t0 = [], np.empty((_READ_BLOCK, len(COLUMNS))), 0, 0, None
  with f:
    reader = csv.reader(f)
    header = next(reader, None)
    if not header or header[0] != "t":
      return (empty, None) if windowed else empty
    # Older sessions may lack columns added later; they are read by header name and missing ones are zero.
    order = [header.index(name) if name in header else None for name in COLUMNS]
    fill = [np.nan if name in NAN_COLUMNS else 0.0 for name in COLUMNS]
    try:
      for rec in reader:
        if len(rec) != len(header):
          continue
        try:
          if windowed:
            t = float(rec[0])
            if t0 is None:
              t0 = t
            if t - t0 > end_s:
              break
            if t - t0 < start_s:
              continue
          row = [fill[k] if i is None else float(rec[i]) for k, i in enumerate(order)]
        except ValueError:
          continue
        if k == _READ_BLOCK:
          blocks.append(block)
          block, k = np.empty((_READ_BLOCK, len(COLUMNS))), 0
        block[k] = row
        k += 1
        n += 1
    except (EOFError, OSError):   # a gzip cut short: keep what was read
      pass
  blocks.append(block[:k])
  del block
  rows = np.empty((n, len(COLUMNS)))
  i = 0
  while blocks:
    b = blocks.pop(0)
    rows[i:i + len(b)] = b
    i += len(b)
  return (rows, t0) if windowed else rows
