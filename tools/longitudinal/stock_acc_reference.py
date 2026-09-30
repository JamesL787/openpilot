#!/usr/bin/env python3
"""What would stock Honda ACC have commanded here? A nearest-neighbour reference built from every stock-ACC drive.

The car's own ACC (Bosch radar, stock long) leaves its decision on CAN: ACC_CONTROL (0x1DF) ACCEL_COMMAND, read
from the bus the radar sends it on (src < 128). This tool pairs that command with the situation openpilot logged
at the same moment (ego speed and accel, radarState leadOne gap and closing speed, lead accel) and keeps the pairs
as a corpus. For any moment of any other drive it finds the k most similar stock moments and reports what stock
commanded then, now and over the next 3 s: median, spread, and how close the nearest precedent is.

  stock_acc_reference.py build   ~/routes/0000025e--919b58ab81 ... --cache-dir /tmp/sar   # corpus (stock rows kept)
  stock_acc_reference.py validate --cache-dir /tmp/sar            # leave-one-route-out: how well it predicts stock
  stock_acc_reference.py gain     --cache-dir /tmp/sar [ALPHA_ROUTE ...]  # command -> aEgo at a firm brake, stock vs ours
  stock_acc_reference.py compare  ~/routes/00000298--... --cache-dir /tmp/sar [--json OUT]
                                  # every alpha-long brake episode: our command vs stock's precedent, onset, peak, twitch
  stock_acc_reference.py compare  ROUTE_DIR --cache-dir /tmp/sar --candidate TRACE.json
                                  # scores a candidate command trace ({"t": [...], "cmd": [...]}, route seconds)
                                  # in place of the logged one, so an open-loop planner variant gets the same verdicts
  stock_acc_reference.py leadbrake --cache-dir /tmp/sar [ALPHA_ROUTE ...]
                                  # does the command move when the lead starts braking, before the gap closes?
  stock_acc_reference.py stops    --cache-dir /tmp/sar [ALPHA_ROUTE ...] [--list] [--json OUT]
                                  # end-of-stop profile behind a lead: command and aEgo on the way down, the lurch
  stock_acc_reference.py law      --cache-dir /tmp/sar [ALPHA_ROUTE ...] [--list] [--json OUT]
                                  # stock's brake law in regimes (following / dash BRAKE threat / set speed): the
                                  # time gap and TTC it starts braking at, how fast it lets go; ours beside it
  stock_acc_reference.py augment  FRAMES.json ROUTE_DIR --cache-dir /tmp/sar --out FRAMES_STOCK.json
                                  # adds a `stock_nn` variant to an alpha_closed_loop_replay frames JSON, so
                                  # long_replay_viewer.py draws it next to the planner variants

The family: alpha_open_loop_replay.py runs our planner on a stock route (the exact same situation, open loop);
this tool goes the other way and puts stock's precedent onto our own drives, where stock never drove. Hand either
one's output to long_replay_viewer.py to look at an event.

What it is NOT (read before quoting a number)
---------------------------------------------
* A lookup, not a model of the radar unit. Stock's own target selection is inside the Bosch radar and in no log;
  the situation here is what *openpilot* saw (radarState leadOne). Where openpilot's lead is wrong and the radar's
  is right, stock's precedent reflects the right one; that is the point of the comparison, and also its limit.
* The lead accel feature is the 1 s causal slope of vEgo + vRel, not aLeadK. A one-frame aLeadK spike is a
  perception artefact, not a situation, so it must not pick the neighbours (Bob, 2026-09-29: the twitch class is
  mostly aLeadK spikes driving the close-lead cap). aLeadK is reported beside each episode instead.
* Stock rows are dropped while the driver presses gas or brake. On most stock brake events openpilot's ICBM is
  also stepping the set speed down (0x296 DECEL_SET; Bob's confound), often below ego speed, so stock is then partly
  holding a set speed that openpilot chose. Dropping those rows would drop most of stock's braking (route 270: 60 %
  of the moving rows with a lead), so set speed minus ego speed is a matching feature instead: a query from an
  alpha drive, where the set speed sits above ego speed, lands on stock moments where it did too. Every episode
  reports the share of its neighbours that were set-speed limited (`setbind_share`) or had an ICBM press in the
  last ICBM_WINDOW_S (`icbm_share`).
* Where the nearest precedent is further than NO_PRECEDENT, the answer is "no stock precedent", never a guess.
* Corpus as of 2026-09-29: 16 stock routes, about 100 stock-engaged minutes with a lead within 120 m, one car (HONDA_CIVIC_BOSCH, dongle
  11c8fa231c0499ed). Hard braking (aEgo < -2.5) is about 60 s of that. Everything it says is replay evidence.

Route data is never committed (AGENTS.md section 7): route directories are arguments, the cache lives outside the
repo. Time is route seconds from the first initData, the clock of alpha_open_loop_replay.py and the viewer.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HZ = 20
ACC_CONTROL_ADDR = 0x1DF
DASH_ADDR = 0x374            # STALK_STATUS: DASHBOARD_ALERT = dat[4]; 185 = the dash BRAKE warning (Bob, route 299)
DASH_BRAKE = 185
SCM_BUTTONS = 0x296          # CRUISE_BUTTONS = (dat[0] >> 5) & 7: 3 = DECEL_SET, 4 = RES_ACCEL
LEAD_MAX_D = 120.0           # m: rows with a farther (or no) lead are not in the corpus and are never queried
MOVING_MIN_V = 1.0           # m/s: stock holds ACCEL_COMMAND at -4.0 at standstill; a hold, not a brake
SETBIND_MS = 0.5             # m/s: set speed within this of vEgo -> stock is at least partly speed-limited
SETERR_CLIP = (-6.0, 3.0)    # m/s: set speed - vEgo, clipped; farther above ego speed is all the same to ACC
ICBM_WINDOW_S = 3.0
LEAD_ACCEL_S = 1.0           # causal slope window for lead accel
HORIZONS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)
K = 15
# Feature scales: one unit of distance is "about as different as": 3 m/s ego speed, 15 % of gap, 1.2 m/s closing
# speed, 0.7 m/s^2 lead accel, 1.5 m/s of set speed minus ego speed. Ego accel is deliberately not a feature: on
# stock rows it is stock's own braking of a moment ago, so matching on it lets the reference copy whatever braking
# is already under way, and on an alpha drive it would make stock look like it agrees with ours.
SCALES = np.array([3.0, 0.15, 1.2, 0.7, 1.5])
NO_PRECEDENT = 1.5           # median neighbour distance past which the answer is "no stock precedent"
BRAKE_ON = -1.0              # episode starts when either side goes below this
REVERSAL_MIN = 0.3           # m/s^2 swing that counts as the command changing its mind
LEADBRAKE_ON = -1.0          # m/s^2 lead accel slope that counts as the lead starting to brake
RADAR_MODEL_GAP = 3.0        # m/s radar closing faster than the model lead on the same car (Bob's gate3 condition)
VREL_RAIL = -13.5 + 1 / 128  # m/s: radar vRel at or below this is on its rail, a bound not a value (Jason)
MIN_SAME_ROWS = 10           # same-car rows (0.5 s) in the 1 s window before the radar/model gap can tag (Jason)
RAIL_SHARE = 0.25           # share of the same-car rows on the rail before the radar/model tag falls back to the max gap
SLOPE_WINDOW_S = 6.0         # s of same-car rows the read-only distance-slope columns are fitted over
LEAD_SWAP_M = 4.0            # m of dRel jump in one row, beyond what vRel explains, that counts as a lead swap
ALERT_WINDOW_S = 1.0         # s either side of a dash BRAKE warning that counts as "stock warned here"
ALERT_SHARE = 0.2            # share of stock neighbours that warned before an episode is tagged "stock would warn"
LINGER_S = 1.0               # s: ours takes this much longer than stock to back off half its peak (Bob, 299 bm1)
FIELDS = ("t", "v", "a", "d", "vrel", "alead", "aleadk", "yrel", "radar", "mprob", "mx", "mv",
          "cmd", "stock", "alpha", "icbm", "setv", "alert")


# ------------------------------------------------------------------------------------------------ read

def segment_files(route_dir: Path) -> list[Path]:
  segs = []
  for d in route_dir.iterdir():
    if d.is_dir() and d.name.isdigit():
      for name in ("rlog.zst", "rlog.bz2", "rlog"):
        if (d / name).exists():
          segs.append((int(d.name), d / name))
          break
  if not segs and (route_dir / route_dir.name).is_dir():  # some downloads nest the route one level deeper
    return segment_files(route_dir / route_dir.name)
  return [p for _, p in sorted(segs)]


def _dbc(fingerprint: str) -> str:
  from opendbc.car.honda.values import DBC
  dbc = DBC[fingerprint]
  return dbc["pt"] if isinstance(dbc, dict) and "pt" in dbc else str(list(dbc.values())[0])


def read_route(route_dir: Path) -> dict:
  """One row per radarState tick (20 Hz). `cmd` is stock's ACCEL_COMMAND on stock rows and openpilot's
  carControl.actuators.accel on alpha-long rows."""
  from opendbc.can.parser import CANParser
  from openpilot.tools.lib.logreader import LogReader

  rows = {k: [] for k in FIELDS}
  meta: dict = {"route": route_dir.name, "op_long": None, "fingerprint": None, "acc_bus": None}
  t0 = None
  cs = cc = md = None
  parser = None
  stock_cmd = math.nan
  dash = 0
  last_icbm = -1e9
  vhist: list[tuple[float, float]] = []
  for path in segment_files(route_dir):
    for m in LogReader(str(path), sort_by_time=True):
      w = m.which()
      if t0 is None:
        if w != "initData":
          continue
        t0 = m.logMonoTime
      t = (m.logMonoTime - t0) / 1e9
      if w == "carParams" and meta["op_long"] is None:
        meta["op_long"] = bool(m.carParams.openpilotLongitudinalControl)
        meta["fingerprint"] = str(m.carParams.carFingerprint)
      elif w == "carState":
        cs = m.carState
      elif w == "carControl":
        cc = m.carControl
      elif w == "modelV2":
        md = m.modelV2
      elif w == "sendcan":
        for f in m.sendcan:
          if f.address == SCM_BUTTONS and (bytes(f.dat)[0] >> 5) & 7 == 3:
            last_icbm = t
      elif w == "can":
        if parser is None and meta["fingerprint"]:
          for f in m.can:
            if f.address == ACC_CONTROL_ADDR and f.src < 128:
              meta["acc_bus"] = int(f.src)
              parser = CANParser(_dbc(meta["fingerprint"]), [("ACC_CONTROL", 50)], int(f.src))
              break
        if parser is not None:
          for f in m.can:
            if f.address == DASH_ADDR and f.src == meta["acc_bus"] and len(f.dat) > 4:
              dash = bytes(f.dat)[4]
          fr = [(f.address, bytes(f.dat), f.src) for f in m.can if f.address == ACC_CONTROL_ADDR and f.src < 128]
          if fr and ACC_CONTROL_ADDR in parser.update([(m.logMonoTime, fr)]):
            stock_cmd = float(parser.vl["ACC_CONTROL"]["ACCEL_COMMAND"])
      elif w == "radarState" and cs is not None and meta["op_long"] is not None:
        ld = m.radarState.leadOne
        v = float(cs.vEgo)
        on = bool(ld.status)
        vl = v + float(ld.vRel) if on else math.nan
        vhist.append((t, vl))
        while vhist and vhist[0][0] < t - LEAD_ACCEL_S:
          vhist.pop(0)
        good = [(tt, x) for tt, x in vhist if math.isfinite(x)]
        alead = math.nan
        if len(good) >= 0.7 * LEAD_ACCEL_S * HZ and good[-1][0] - good[0][0] > 0.5 * LEAD_ACCEL_S:
          tt, x = np.array(good).T
          alead = float(np.polyfit(tt - tt[-1], x, 1)[0])
        ml = md.leadsV3[0] if md is not None and len(md.leadsV3) else None
        engaged = bool(cs.cruiseState.enabled) and not cs.gasPressed and not cs.brakePressed
        alpha = bool(meta["op_long"]) and cc is not None and bool(cc.longActive) and not cs.gasPressed
        rows["t"].append(t)
        rows["v"].append(v)
        rows["a"].append(float(cs.aEgo))
        rows["d"].append(float(ld.dRel) if on else math.nan)
        rows["vrel"].append(float(ld.vRel) if on else math.nan)
        rows["alead"].append(alead)
        rows["aleadk"].append(float(ld.aLeadK) if on else math.nan)
        rows["yrel"].append(float(ld.yRel) if on else math.nan)
        rows["radar"].append(float(bool(ld.radar)) if on else math.nan)
        rows["mprob"].append(float(ml.prob) if ml is not None else math.nan)
        rows["mx"].append(float(ml.x[0]) if ml is not None else math.nan)
        rows["mv"].append(float(ml.v[0]) if ml is not None else math.nan)
        rows["cmd"].append(float(cc.actuators.accel) if alpha else (stock_cmd if not meta["op_long"] else math.nan))
        rows["stock"].append(float(engaged and not meta["op_long"]))
        rows["alpha"].append(float(alpha))
        rows["icbm"].append(float(t - last_icbm < ICBM_WINDOW_S))
        rows["alert"].append(float(dash == DASH_BRAKE))
        # set speed: the cluster's under stock ACC; under alpha long it is openpilot's vCruise (km/h, 255 = unset)
        sc = float(cs.cruiseState.speedCluster)
        vc = float(cs.vCruise) / 3.6 if 0 < cs.vCruise < 250 else math.nan
        rows["setv"].append(sc if sc > 0 and not meta["op_long"] else vc)
  out = {k: np.array(v, dtype=float) for k, v in rows.items()}
  out["meta"] = meta
  return out


def from_cache(z) -> dict:
  # caches written before the alert column: alert unknown (NaN), not "never warned"
  R = {k: z[k] if k in z.files else np.full(len(z["t"]), np.nan) for k in FIELDS}
  R["meta"] = json.loads(str(z["meta"]))
  return R


def load(route_dir: Path, cache_dir: Path | None) -> dict:
  f = cache_dir / f"{route_dir.name}.npz" if cache_dir else None
  if f is not None and f.exists():
    z = np.load(f, allow_pickle=False)
    R = from_cache(z)
    return R
  R = read_route(route_dir)
  if f is not None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(f, meta=json.dumps(R["meta"]), **{k: R[k] for k in FIELDS})
  return R


# ------------------------------------------------------------------------------------------------ corpus

def features(R: dict) -> np.ndarray:
  d = np.maximum(R["d"], 2.0)
  se = np.clip(np.nan_to_num(R["setv"] - R["v"], nan=SETERR_CLIP[1]), *SETERR_CLIP)
  return np.vstack([R["v"], np.log(d), R["vrel"], R["alead"], se]).T / SCALES


def future(R: dict, mask_ok: np.ndarray) -> np.ndarray:
  """cmd at each horizon ahead; NaN where the row that far ahead is not a usable stock row or time jumps."""
  t, cmd = R["t"], R["cmd"]
  out = np.full((len(t), len(HORIZONS)), np.nan)
  for j, h in enumerate(HORIZONS):
    k = np.searchsorted(t, t + h - 0.5 / HZ)
    k = np.minimum(k, len(t) - 1)
    ok = mask_ok[k] & (np.abs(t[k] - t - h) < 1.0 / HZ)
    out[:, j] = np.where(ok, cmd[k], np.nan)
  return out


def usable(R: dict, who: str) -> np.ndarray:
  side = R["stock"] > 0.5 if who == "stock" else R["alpha"] > 0.5
  m = side & np.isfinite(R["cmd"]) & (R["v"] > MOVING_MIN_V) & np.isfinite(R["d"]) & (R["d"] < LEAD_MAX_D)
  m &= np.isfinite(R["vrel"]) & np.isfinite(R["alead"])
  return m


class Corpus:
  def __init__(self, routes: list[dict]):
    X, Y, W, I = [], [], [], []
    self.names = []
    revs, minutes = 0, 0.0
    for R in routes:
      if R["meta"]["op_long"] or R["meta"]["op_long"] is None:
        continue
      m = usable(R, "stock")
      if m.sum() == 0:
        continue
      Y.append(future(R, m)[m])
      X.append(features(R)[m])
      setbind = np.isfinite(R["setv"]) & (R["setv"] < R["v"] + SETBIND_MS)
      W.append(np.vstack([R["icbm"][m], R["t"][m], setbind[m], near_alert(R)[m]]).T)
      I.append(np.full(m.sum(), len(self.names)))
      self.names.append(R["meta"]["route"])
      for s, e in runs(m):
        revs += reversals(R["cmd"][s:e])
        minutes += (e - s) / HZ / 60
    if not X:
      raise SystemExit("no stock-ACC rows: pass stock routes (carParams.openpilotLongitudinalControl false)")
    self.X, self.Y, self.W, self.I = np.vstack(X), np.vstack(Y), np.vstack(W), np.concatenate(I)
    # how often stock itself changes its mind, from its logged commands. The kNN median cannot answer this:
    # it stitches a different set of neighbours every row, so it wobbles more than any real controller.
    self.reversals_per_min = revs / minutes if minutes > 0 else math.nan

  def query(self, Q: np.ndarray, exclude: int | None = None, k: int = K) -> dict:
    """k nearest stock rows for each query row. Returns per-horizon median/p25/p75, the median neighbour
    distance, and the share of neighbours with an ICBM press in the window / a set speed at or below ego speed."""
    X, Y, W = self.X, self.Y, self.W
    if exclude is not None:
      keep = self.I != exclude
      X, Y, W = X[keep], Y[keep], W[keep]
    n = len(Q)
    med = np.full((n, len(HORIZONS)), np.nan)
    p25, p75 = med.copy(), med.copy()
    dist = np.full(n, np.nan)
    icbm = np.full(n, np.nan)
    setbind = np.full(n, np.nan)
    alert = np.full(n, np.nan)
    x2 = np.sum(X * X, axis=1)
    for s in range(0, n, 256):
      q = Q[s:s + 256]
      D2 = x2[None, :] - 2 * q @ X.T + np.sum(q * q, axis=1)[:, None]
      nn = np.argpartition(D2, k, axis=1)[:, :k]
      dist[s:s + 256] = np.sqrt(np.maximum(np.median(np.take_along_axis(D2, nn, 1), axis=1), 0))
      y = Y[nn]  # (q, k, H)
      med[s:s + 256] = np.nanmedian(y, axis=1)
      p25[s:s + 256] = np.nanpercentile(y, 25, axis=1)
      p75[s:s + 256] = np.nanpercentile(y, 75, axis=1)
      icbm[s:s + 256] = W[nn, 0].mean(axis=1)
      setbind[s:s + 256] = W[nn, 2].mean(axis=1)
      a = W[nn, 3]
      known = np.isfinite(a).sum(axis=1)
      alert[s:s + 256] = np.where(known > 0, np.nansum(a, axis=1) / np.maximum(known, 1), np.nan)
    return {"med": med, "p25": p25, "p75": p75, "dist": dist, "icbm": icbm, "setbind": setbind, "alert": alert}


def load_corpus(cache_dir: Path) -> tuple[Corpus, list[dict]]:
  routes = []
  for f in sorted(cache_dir.glob("*.npz")):
    z = np.load(f, allow_pickle=False)
    R = from_cache(z)
    routes.append(R)
  return Corpus(routes), routes


# ------------------------------------------------------------------------------------------------ episodes

def runs(m: np.ndarray) -> list[tuple[int, int]]:
  """[start, end) of each run of True in m."""
  d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
  return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1), strict=True))


def smooth(x: np.ndarray, n: int = int(0.5 * HZ)) -> np.ndarray:
  """Centred n-sample mean that skips NaN; NaN where x is NaN."""
  ok = np.isfinite(x)
  k = np.ones(n)
  num = np.convolve(np.where(ok, x, 0.0), k, "same")
  den = np.convolve(ok.astype(float), k, "same")
  return np.where(ok, num / np.maximum(den, 1), np.nan)


def reversals(x: np.ndarray) -> int:
  """How many times the command changes direction by at least REVERSAL_MIN (hysteresis turning points)."""
  x = x[np.isfinite(x)]
  if len(x) < 3:
    return 0
  n, direction, ext = 0, 0, x[0]
  for v in x[1:]:
    if direction == 0:
      if abs(v - ext) >= REVERSAL_MIN:
        direction, ext = (1 if v > ext else -1), v
    elif direction * (v - ext) > 0:
      ext = v
    elif abs(v - ext) >= REVERSAL_MIN:
      n += 1
      direction, ext = -direction, v
  return n


def episodes(t: np.ndarray, a: np.ndarray, b: np.ndarray, mask: np.ndarray, gap_s: float = 1.5) -> list[tuple[int, int]]:
  hit = mask & ((a < BRAKE_ON) | (b < BRAKE_ON))
  idx = np.flatnonzero(hit)
  out = []
  for i in idx:
    if out and t[i] - t[out[-1][1]] < gap_s:
      out[-1][1] = i
    else:
      out.append([i, i])
  pre, post = int(2 * HZ), int(2 * HZ)
  return [(max(s - pre, 0), min(e + post, len(t) - 1)) for s, e in out]


def onset(t, x, s, e, level=BRAKE_ON):
  k = np.flatnonzero(x[s:e + 1] < level)
  return float(t[s + k[0]]) if len(k) else math.nan


def release(t, x, s, e):
  # seconds from the peak brake until the command is back above half of it; stock is sharp in and sharp out
  k = s + int(np.nanargmin(x[s:e + 1]))
  if not x[k] < BRAKE_ON:
    return math.nan
  r = np.flatnonzero(x[k:e + 1] > 0.5 * x[k])
  return float(t[k + r[0]] - t[k]) if len(r) else float(t[e] - t[k])


def near_alert(R: dict) -> np.ndarray:
  # 1 within ALERT_WINDOW_S of a dash BRAKE warning, 0 elsewhere, NaN for a cache written before the column
  a = R["alert"]
  if not np.isfinite(a).any():
    return np.full(len(a), np.nan)
  w = int(ALERT_WINDOW_S * HZ)
  return (np.convolve(a > 0.5, np.ones(2 * w + 1), "same") > 0).astype(float)


def fmt_t(t: float) -> str:
  return f"{int(t // 60)}:{t % 60:04.1f}" if math.isfinite(t) else "  -  "


# ------------------------------------------------------------------------------------------------ modes

def cmd_build(args) -> int:
  for p in args.routes:
    R = load(p.expanduser(), args.cache_dir)
    m = R["meta"]
    s = usable(R, "stock") if not m["op_long"] else usable(R, "alpha")
    print(f"{m['route']}: {'alpha long' if m['op_long'] else 'STOCK ACC'} bus {m['acc_bus']} rows {len(R['t'])} " +
          f"usable-with-lead {s.sum() / HZ / 60:.1f} min", flush=True)
  return 0


def cmd_validate(args) -> int:
  C, routes = load_corpus(args.cache_dir)
  print(f"corpus: {len(C.names)} stock routes, {len(C.X)} rows ({len(C.X) / HZ / 60:.0f} min with a lead < {LEAD_MAX_D:.0f} m)")
  print("leave-one-route-out: each stock route is predicted from the others only\n")
  print(f"{'route':22s} {'rows':>6s} {'mae0':>5s} {'mae1s':>5s} {'brk':>4s} {'mae0@brk':>8s} {'noPrec':>6s}  " +
        "episode onset dt (pred - stock) / peak (pred, stock)")
  all_e0, all_eb, all_on, all_pk = [], [], [], []
  for ri, name in enumerate(C.names):
    sel = C.I == ri
    r = C.query(C.X[sel], exclude=ri)
    y = C.Y[sel]
    e0 = np.abs(r["med"][:, 0] - y[:, 0])
    e1 = np.abs(r["med"][:, 2] - y[:, 2])
    brk = y[:, 0] < -1.5
    nop = r["dist"] > NO_PRECEDENT
    all_e0.append(e0[np.isfinite(e0)])
    all_eb.append(e0[brk & np.isfinite(e0)])
    # episodes on the route's own clock
    t = C.W[sel, 1]
    ep = []
    for s, e in episodes(t, y[:, 0], r["med"][:, 0], np.ones(len(t), bool)):
      if t[e] - t[s] > 30 or np.any(np.diff(t[s:e + 1]) > 0.5):
        continue
      on_p, on_s = onset(t, r["med"][:, 0], s, e), onset(t, y[:, 0], s, e)
      pk_p, pk_s = np.nanmin(r["med"][s:e + 1, 0]), np.nanmin(y[s:e + 1, 0])
      if pk_s < -1.5:
        all_on.append(on_p - on_s)
        all_pk.append(pk_p - pk_s)
      ep.append(f"{fmt_t(t[s] + 2)} {on_p - on_s:+.1f}s {pk_p:+.1f}/{pk_s:+.1f}")
    print(f"{name:22s} {sel.sum():6d} {np.nanmean(e0):5.2f} {np.nanmean(e1):5.2f} {brk.sum():4d} " +
          f"{np.nanmean(e0[brk]) if brk.any() else math.nan:8.2f} {nop.mean():6.1%}  " + "; ".join(ep[:6]))
  e0, eb = np.concatenate(all_e0), np.concatenate(all_eb)
  on, pk = np.array(all_on), np.array(all_pk)
  print(f"\nall: command mae now {e0.mean():.2f} m/s^2 (p90 {np.percentile(e0, 90):.2f}); while stock < -1.5: " +
        f"{eb.mean():.2f} (p90 {np.percentile(eb, 90):.2f}, n {len(eb)})")
  if len(on):
    on_f = on[np.isfinite(on)]
    print(f"stock brake episodes (peak < -1.5): {len(pk)}; predicted onset - stock onset median {np.median(on_f):+.2f} s " +
          f"(|dt| p75 {np.percentile(np.abs(on_f), 75):.2f}, missed {np.sum(~np.isfinite(on))}); " +
          f"peak error median {np.median(pk):+.2f} (|err| p75 {np.percentile(np.abs(pk), 75):.2f})")
  return 0


def cmd_gain(args) -> int:
  """Delivered aEgo against the commanded accel at a firm brake: stock (corpus) vs ours (alpha routes)."""
  _, routes = load_corpus(args.cache_dir)
  groups = {"stock": [R for R in routes if not R["meta"]["op_long"]]}
  alpha_routes = [load(p.expanduser(), args.cache_dir) for p in args.routes]
  groups["alpha"] = [R for R in alpha_routes if R["meta"]["op_long"]] + [R for R in routes if R["meta"]["op_long"]]
  print("aEgo(t + lag) against cmd(t), moving, cmd < -1.5 held for 0.5 s; lag picked by least error\n")
  for who, rs in groups.items():
    if not rs:
      print(f"{who}: no routes")
      continue
    best = None
    for lag in np.arange(0.0, 1.05, 0.1):
      c, a = [], []
      for R in rs:
        side = R["stock"] if who == "stock" else R["alpha"]
        cmd = R["cmd"]
        n = int(round(lag * HZ))
        if len(cmd) <= n:
          continue
        held = np.convolve((cmd < -1.5).astype(float), np.ones(int(0.5 * HZ)), "full")[:len(cmd)] >= 0.5 * HZ
        m = held & (side > 0.5) & (R["v"] > 3.0) & np.isfinite(cmd)
        m[len(m) - n:] = False
        k = np.flatnonzero(m)
        c.append(cmd[k])
        a.append(R["a"][k + n])
      c, a = np.concatenate(c), np.concatenate(a)
      if len(c) < 20:
        continue
      g = float(np.sum(a * c) / np.sum(c * c))
      rms = float(np.sqrt(np.mean((a - g * c) ** 2)))
      if best is None or rms < best[2]:
        best = (lag, g, rms, len(c), c, a)
    if best is None:
      print(f"{who}: too few firm-brake rows")
      continue
    lag, g, rms, n, c, a = best
    bands = []
    for lo, hi in ((-2.0, -1.5), (-2.5, -2.0), (-3.0, -2.5), (-4.5, -3.0)):
      b = (c >= lo) & (c < hi)
      if b.sum() >= 10:
        bands.append(f"cmd {lo:+.1f}..{hi:+.1f}: aEgo/cmd {np.median(a[b] / c[b]):.2f} (n {b.sum()})")
    print(f"{who}: lag {lag:.1f} s  gain {g:.2f}  rms {rms:.2f}  n {n} ({n / HZ:.0f} s)\n  " + "\n  ".join(bands))
  return 0


def compare_route(R: dict, C: Corpus) -> dict:
  m = usable(R, "alpha")
  if R["meta"]["op_long"]:
    who = "alpha"
  else:
    m = usable(R, "stock")
    who = "stock"
  Q = features(R)
  pred = {k: np.full((len(R["t"]),) + (() if k in ("dist", "icbm", "setbind", "alert") else (len(HORIZONS),)), np.nan)
          for k in ("med", "p25", "p75", "dist", "icbm", "setbind", "alert")}
  exclude = C.names.index(R["meta"]["route"]) if R["meta"]["route"] in C.names else None
  if m.any():
    r = C.query(Q[m], exclude=exclude)
    for k in pred:
      pred[k][m] = r[k]
  # the stock reference is smoothed over 0.5 s: row-to-row neighbour changes are not stock changing its mind
  t, ours, stock = R["t"], np.where(m, R["cmd"], np.nan), smooth(pred["med"][:, 0])
  eps = []
  for s, e in episodes(t, ours, stock, m):
    if np.any(np.diff(t[s:e + 1]) > 0.5):
      continue
    seg = slice(s, e + 1)
    dist = float(np.nanmedian(pred["dist"][seg]))
    ours_pk, st_pk = float(np.nanmin(ours[seg])), float(np.nanmin(stock[seg]))
    on_o, on_s = onset(t, ours, s, e), onset(t, stock, s, e)
    rel_o, rel_s = release(t, ours, s, e), release(t, stock, s, e)
    k = s + int(np.nanargmin(ours[seg]))
    # radar vs model on the same car, over the second leading up to our peak: model lead speed minus radar lead
    # speed, positive when radar says the lead is closing faster. Only where the lead is radar-backed and the model's
    # lead sits at the radar's range (else the two are different cars and the difference means nothing).
    w = slice(max(s, k - HZ), k + 1)
    vr_lead = R["v"][w] + R["vrel"][w]
    same = (R["radar"][w] > 0.5) & (np.abs(R["mx"][w] - R["d"][w]) < np.maximum(5.0, 0.2 * R["d"][w]))
    gap = np.where(same, R["mv"][w] - vr_lead, np.nan)
    gap_max = float(np.nanmax(gap)) if np.isfinite(gap).any() else math.nan
    # the tag fires on the median gap: 5 of 17 tags on 297/298/29c/29d were a one-row spike (Bob, Jason). With radar
    # vRel on its rail the gap is only a lower bound and the median under-reports, so there the max still decides.
    gap_med = float(np.nanmedian(gap)) if np.isfinite(gap).any() else math.nan
    # one rail row among many is a touch, not a bound on the whole second (Jason): the max decides only past RAIL_SHARE
    rail_rows, same_rows = int(np.sum(same & (R["vrel"][w] <= VREL_RAIL))), int(same.sum())
    on_rail = same_rows > 0 and rail_rows >= RAIL_SHARE * same_rows
    # too few same-car rows to call the second either way: no tag, only a "low n" note when the max would have fired
    low_n = same_rows < MIN_SAME_ROWS
    gap_trig = math.nan if low_n else gap_max if on_rail else gap_med
    # read-only, in no verdict yet: does the model's own distance close like the radar's? On 29d 4:40 the model lead
    # speed said no closing while its distance closed at -4.1 m/s against radar dRel -4.0. 2 s fits are too noisy.
    ws = slice(max(0, k - int(SLOPE_WINDOW_S * HZ)), k + 1)
    sm = (R["radar"][ws] > 0.5) & (np.abs(R["mx"][ws] - R["d"][ws]) < np.maximum(5.0, 0.2 * R["d"][ws]))
    fit = int(sm.sum()) >= HZ
    ts = t[ws][sm]
    slopes = {c: round(float(np.polyfit(ts - ts[0], R[c][ws][sm], 1)[0]), 1) if fit else None for c in ("mx", "d")}
    # the cache keeps no track id, so a lead swap shows as the lead dropping out or dRel jumping by more than its own
    # vRel explains. A slope across one mixes two cars (297 48:05, 298 7:27: the lead left and revealed another).
    dw, vw, tw = R["d"][ws], R["vrel"][ws], t[ws]
    jump = np.abs(np.diff(dw) - vw[1:] * np.diff(tw)) > np.maximum(LEAD_SWAP_M, 0.1 * dw[1:])
    brk = np.flatnonzero((np.isfinite(dw[1:]) != np.isfinite(dw[:-1])) | np.where(np.isfinite(jump), jump, False)) + 1
    lead_swap = bool(brk.size)
    # dRel6 column: fit only the last same-car segment, from the latest swap (or the window start) to our peak. With a
    # 6 s fit every rail episode on 297/298/29c spanned a swap, so the slope said nothing where it was needed (Jason).
    s0 = int(brk[-1]) if brk.size else 0
    # no range sigma in the cache: a segment that starts where the lead appears may be a new track's range still
    # converging (297 48:12: 95 -> 72 m in 0.9 s while rsig fell 59 -> 11), which reads as fake closing (Jason)
    seg_new = bool(s0 > 0 and not np.isfinite(dw[s0 - 1]))
    ssm = sm[s0:]
    seg_fit = int(ssm.sum()) >= HZ
    tss = tw[s0:][ssm]
    seg_slope = round(float(np.polyfit(tss - tss[0], dw[s0:][ssm], 1)[0]), 1) if seg_fit else None
    eps.append({
      "t0": round(float(t[s]) + 2.0, 1), "t1": round(float(t[e]) - 2.0, 1),
      "ours_peak": round(ours_pk, 2), "stock_peak": round(st_pk, 2),
      "stock_peak_p25": round(float(np.nanmin(pred["p25"][seg, 0])), 2),
      "ours_onset": round(on_o, 2) if math.isfinite(on_o) else None,
      "stock_onset": round(on_s, 2) if math.isfinite(on_s) else None,
      "ours_release": round(rel_o, 2) if math.isfinite(rel_o) else None,
      "stock_release": round(rel_s, 2) if math.isfinite(rel_s) else None,
      "ours_reversals": reversals(ours[seg]),
      "stock_reversals": round(C.reversals_per_min * (e - s + 1) / HZ / 60, 1),
      "ours_s_below_2p5": round(float(np.sum(ours[seg] < -2.5) / HZ), 2),
      "stock_s_below_2p5": round(float(np.sum(stock[seg] < -2.5) / HZ), 2),
      "at_ours_peak": {"v": round(float(R["v"][k]), 1), "d": round(float(R["d"][k]), 1), "vrel": round(float(R["vrel"][k]), 1),
                       "alead": round(float(R["alead"][k]), 2), "aleadk": round(float(R["aleadk"][k]), 2),
                       "radar": bool(R["radar"][k] > 0.5), "model_v_minus_radar": round(float(R["mv"][k] - (R["v"][k] + R["vrel"][k])), 1)},
      "radar_minus_model_closing": round(gap_trig, 1) if math.isfinite(gap_trig) else None,
      "radar_minus_model_closing_max": round(gap_max, 1) if math.isfinite(gap_max) else None,
      "radar_minus_model_closing_median": round(gap_med, 1) if math.isfinite(gap_med) else None,
      "radar_vrel_on_rail": on_rail, "rail_rows": f"{rail_rows}/{same_rows}", "radar_model_low_n": low_n,
      "slope_fit_rows": int(sm.sum()), "model_dist_slope": slopes["mx"], "radar_dist_slope": slopes["d"],
      "slope_spans_lead_swap": lead_swap, "radar_dist_slope_seg": seg_slope,
      "slope_seg_s": round(float(tw[-1] - tw[s0]), 1), "slope_seg_new_lead": seg_new,
      "radar_vrel_median": round(float(np.nanmedian(R["vrel"][ws][sm])), 1) if fit else None,
      "min_a_ego": round(float(np.nanmin(R["a"][seg])), 2),
      "precedent_dist": round(dist, 2), "no_precedent": bool(dist > NO_PRECEDENT),
      "icbm_share": round(float(np.nanmean(pred["icbm"][seg])), 2),
      "setbind_share": round(float(np.nanmean(pred["setbind"][seg])), 2),
      # share of stock neighbours at a dash BRAKE warning, at the row where the most of them were
      "stock_alert_share": round(float(np.nanmax(pred["alert"][seg])), 2) if np.isfinite(pred["alert"][seg]).any() else None,
      # n/a (None) under openpilot long: the radar is silenced (disable_ecu), so the car's own FCW/AEB is off
      "dash_alert": None if R["meta"]["op_long"] or not np.isfinite(R["alert"][seg]).any() else bool(np.nanmax(R["alert"][seg]) > 0.5),
    })
  rate_min = m.sum() / HZ / 60
  return {"route": R["meta"]["route"], "who": who, "minutes_with_lead": round(rate_min, 1),
          "ours_reversals_per_min": round(reversals(ours[m]) / rate_min, 2) if rate_min > 0 else None,
          "stock_reversals_per_min": round(C.reversals_per_min, 2),
          "episodes": eps, "_pred": pred, "_mask": m}


def slope_cell(e):
  # dRel6 column, display only: radar dRel slope since the last lead swap, and how long that segment is. "-" when it
  # has under 1 s of same-car rows; never a fit across a swap, which mixes two cars (Jason, Bob)
  s = e.get("radar_dist_slope_seg")
  return "-" if s is None else f"{s:+.1f} ({e['slope_seg_s']:.1f}s{' new' if e.get('slope_seg_new_lead') else ''})"


def verdict(e: dict) -> str:
  tags = []
  if e["no_precedent"]:
    tags.append("no stock precedent")
  else:
    if e["ours_peak"] < e["stock_peak_p25"] - 0.5 and e["ours_peak"] < -1.5:
      tags.append("ours harder")
    if e["stock_peak"] < -1.5 and e["ours_peak"] > e["stock_peak"] + 1.0:
      tags.append("ours softer")
    if e["ours_onset"] is not None and e["stock_onset"] is not None:
      if e["ours_onset"] - e["stock_onset"] > 0.5:
        tags.append("ours later")
      elif e["stock_onset"] - e["ours_onset"] > 0.5:
        tags.append("ours earlier")
    elif e["ours_onset"] is not None and e["stock_peak"] > -0.7:
      tags.append("stock would not brake")
    if e.get("ours_release") is not None and e.get("stock_release") is not None and \
       e["ours_release"] - e["stock_release"] > LINGER_S:
      tags.append("ours lingers")
    if e["ours_reversals"] >= e["stock_reversals"] + 2:
      tags.append("ours twitchier")
  if (e.get("stock_alert_share") or 0.0) >= ALERT_SHARE:
    tags.append("stock would warn")
  if e.get("dash_alert"):
    tags.append("dash BRAKE shown")
  if (e.get("radar_minus_model_closing") or 0.0) >= RADAR_MODEL_GAP:
    tags.append("radar closing > model (rail)" if e.get("radar_vrel_on_rail") else "radar closing > model")
  elif e.get("radar_model_low_n") and (e.get("radar_minus_model_closing_max") or 0.0) >= RADAR_MODEL_GAP:
    tags.append("radar/model low n")
  if e["at_ours_peak"]["aleadk"] is not None and e["at_ours_peak"]["aleadk"] < -4 and e["at_ours_peak"]["alead"] > -1.5:
    tags.append("aLeadK spike")
  return ", ".join(tags) or "similar"


def with_candidate(R: dict, path: Path) -> dict:
  """R with its command replaced by a candidate trace ({"t": [...], "cmd": [...]} in route seconds, e.g. an
  open-loop planner variant). Rows the trace does not cover within 0.1 s get NaN and drop out of the scoring."""
  doc = json.loads(Path(path).read_text())
  ct, cc = np.asarray(doc["t"], float), np.asarray(doc["cmd"], float)
  o = np.argsort(ct)
  ct, cc = ct[o], cc[o]
  k = np.clip(np.searchsorted(ct, R["t"]), 1, len(ct) - 1)
  k = np.where(np.abs(ct[k - 1] - R["t"]) < np.abs(ct[k] - R["t"]), k - 1, k)
  R = dict(R)
  R["cmd"] = np.where(np.abs(ct[k] - R["t"]) < 0.1, cc[k], np.nan)
  R["meta"] = dict(R["meta"], candidate=str(path))
  return R


def lead_brake_events(R: dict, side: np.ndarray) -> list[dict]:
  """Moments the lead starts braking while the gap is not yet closing: lead accel slope first below
  LEADBRAKE_ON after a calm second, vRel > -1 m/s, lead within 100 m, engaged from 0.5 s before to 2 s after. Measures the
  command's change from its value at the start, and when the gap starts closing (vRel < -1)."""
  t, al, vr, cmd = R["t"], R["alead"], R["vrel"], R["cmd"]
  out = []
  last = -1e9
  for i in range(HZ, len(t) - 2 * HZ):
    if not (al[i] < LEADBRAKE_ON and al[i - 1] >= LEADBRAKE_ON) or t[i] - last < 5.0:
      continue
    w = slice(i - HZ // 2, i + 2 * HZ + 1)
    if (np.any(np.diff(t[w]) > 0.2) or not np.all(side[w] > 0.5) or not np.all(np.isfinite(cmd[w])) or
        not (vr[i] > -1.0 and R["d"][i] < 100 and R["v"][i] > 5.0) or not np.nanmedian(al[i - HZ:i]) > -0.5):
      continue
    last = t[i]
    closing = np.flatnonzero(vr[i:i + 2 * HZ] < -1.0)
    tc = float(closing[0] / HZ) if len(closing) else math.inf
    c0 = cmd[i]
    before = cmd[i:i + (closing[0] if len(closing) else 2 * HZ) + 1]
    out.append({"t": round(float(t[i]), 1), "v": round(float(R["v"][i]), 1), "d": round(float(R["d"][i]), 1),
                "lead_accel_1s": round(float(np.nanmin(al[i:i + HZ])), 2), "t_gap_closing": tc,
                "drop_before_closing": round(float(c0 - np.min(before)), 2),
                "drop_1s": round(float(c0 - np.min(cmd[i:i + HZ + 1])), 2),
                "drop_2s": round(float(c0 - np.min(cmd[i:i + 2 * HZ + 1])), 2)})
  return out


def cmd_leadbrake(args) -> int:
  """Q3 (Bob): does the command move when the lead starts braking, before the gap starts closing? Stock from the
  corpus, ours from the alpha routes given. The control is every calm-lead moment with the same gate (vRel > -1,
  lead within 100 m, lead accel above -0.5): how often the command drops that much anyway."""
  _, routes = load_corpus(args.cache_dir)
  groups = {"stock": [R for R in routes if not R["meta"]["op_long"]]}
  groups["ours"] = [R for R in (load(p.expanduser(), args.cache_dir) for p in args.routes) if R["meta"]["op_long"]]
  for who, rs in groups.items():
    ev, base1 = [], []
    for R in rs:
      side = R["stock"] if who == "stock" else R["alpha"]
      if len(R["t"]) < 5 * HZ:
        continue
      ev += lead_brake_events(R, side)
      cmd = R["cmd"]
      calm = ((side > 0.5) & (R["vrel"] > -1.0) & (R["d"] < 100) & (R["v"] > 5.0) & (R["alead"] > -0.5) &
              np.isfinite(cmd))
      for i in np.flatnonzero(calm[:-HZ])[::HZ]:
        seg = cmd[i:i + HZ + 1]
        if np.all(np.isfinite(seg)) and R["t"][i + HZ] - R["t"][i] < 1.2:
          base1.append(cmd[i] - np.min(seg))
    if not ev:
      print(f"{who}: no lead-brake onsets")
      continue
    d1 = np.array([e["drop_1s"] for e in ev])
    db = np.array([e["drop_before_closing"] for e in ev])
    tc = np.array([e["t_gap_closing"] for e in ev])
    base1 = np.array(base1)
    print(f"{who}: {len(ev)} lead-brake onsets (lead accel < {LEADBRAKE_ON} after a calm second, vRel > -1, d < 100)")
    print(f"  command drop in the first 1 s: median {np.median(d1):.2f}, >= 0.3 in {np.mean(d1 >= 0.3):.0%}" +
          f"   (calm-lead control, n {len(base1)}: median {np.median(base1):.2f}, >= 0.3 in {np.mean(base1 >= 0.3):.0%})")
    print(f"  drop before the gap starts closing (vRel < -1): median {np.nanmedian(db):.2f}, >= 0.3 in {np.mean(db >= 0.3):.0%};" +
          f" when it closes within 2 s it starts after median {np.median(tc[np.isfinite(tc)]):.1f} s ({np.mean(np.isinf(tc)):.0%} not within 2 s)")
    la, d2 = np.array([e["lead_accel_1s"] for e in ev]), np.array([e["drop_2s"] for e in ev])
    for lo, hi, name in [(-99, -3.0, "hard (< -3)"), (-3.0, -1.5, "medium"), (-1.5, 0.0, "light (> -1.5)")]:
      for gap, gname in [(np.isfinite(tc), "gap closes within 2 s"), (np.isinf(tc), "gap still open at 2 s")]:
        m = (la >= lo) & (la < hi) & gap
        if m.any():
          print(f"    lead brake {name:<14} {gname}: n {m.sum():>3}  drop 1 s median {np.median(d1[m]):.2f}" +
                f" (>= 0.3 {np.mean(d1[m] >= 0.3):>4.0%})  drop 2 s median {np.median(d2[m]):.2f} (>= 0.3 {np.mean(d2[m] >= 0.3):>4.0%})")
    if args.list:
      for e in ev:
        print("   ", e)
  return 0


STOP_V = 0.2                 # m/s: stopped
STOP_BINS = (4.0, 2.0, 1.0, 0.5)  # m/s: speeds the approach is sampled at


def stop_events(R: dict, side: np.ndarray) -> list[dict]:
  """Stops behind a lead: speed falls from >= 4 m/s to below STOP_V and stays there 1 s, engaged throughout and a
  lead within 30 m at the stop. Samples command and aEgo at STOP_BINS on the way down, and reports how the stop
  ends: the command over the last second, the aEgo step at standstill (the lurch), the final gap."""
  t, v, a, cmd = R["t"], R["v"], R["a"], R["cmd"]
  out = []
  last = -1e9
  stopped = v < STOP_V
  for i in np.flatnonzero(stopped[1:] & ~stopped[:-1]) + 1:
    j = i + HZ
    if j >= len(t) or t[i] - last < 10.0 or not np.all(stopped[i:j]) or t[j] - t[i] > 1.2:
      continue
    above = np.flatnonzero(v[:i] >= STOP_BINS[0])
    if not len(above) or t[i] - t[above[-1]] > 20.0:
      continue
    s0 = above[-1]
    if np.any(stopped[s0:i]):  # a creep after an earlier stop, not a fresh approach
      continue
    w = slice(s0, j)
    if (np.any(np.diff(t[w]) > 0.2) or not np.all(side[w] > 0.5) or not np.all(np.isfinite(cmd[w])) or
        not (np.isfinite(R["d"][i]) and R["d"][i] < 30.0)):
      continue
    last = t[i]
    e = {"t": round(float(t[i]), 1), "approach_s": round(float(t[i] - t[s0]), 1), "gap_at_stop": round(float(R["d"][i]), 1)}
    for vb in STOP_BINS:
      k = s0 + int(np.flatnonzero(v[s0:i + 1] <= vb)[0])
      e[f"cmd_at_{vb:g}"] = round(float(cmd[k]), 2)
      e[f"aego_at_{vb:g}"] = round(float(a[k]), 2)
    e["s_below_1"] = round(float(t[i] - t[s0 + int(np.flatnonzero(v[s0:i + 1] <= 1.0)[0])]), 1)
    e["min_cmd"] = round(float(np.min(cmd[s0:i + 1])), 2)
    e["min_aego"] = round(float(np.min(a[s0:i + 1])), 2)
    last1 = slice(max(s0, i - HZ), i + 1)
    e["cmd_last_1s_min"] = round(float(np.min(cmd[last1])), 2)
    e["cmd_last_1s_rise"] = round(float(cmd[i] - np.min(cmd[last1])), 2)
    e["aego_before_stop"] = round(float(np.min(a[last1])), 2)
    e["lurch"] = round(float(np.max(a[i:j]) - np.min(a[last1])), 2)  # aEgo step from the last braking to standstill
    e["reversals"] = reversals(cmd[s0:i + 1])
    out.append(e)
  return out


def cmd_stops(args) -> int:
  """End-of-stop profile, stock (corpus) against ours (alpha routes given)."""
  _, routes = load_corpus(args.cache_dir)
  groups = {"stock": [R for R in routes if not R["meta"]["op_long"]]}
  groups["ours"] = [R for R in (load(p.expanduser(), args.cache_dir) for p in args.routes) if R["meta"]["op_long"]]
  keys = [f"{k}_at_{vb:g}" for vb in STOP_BINS for k in ("cmd", "aego")] + \
         ["approach_s", "s_below_1", "min_cmd", "min_aego", "cmd_last_1s_min", "cmd_last_1s_rise", "aego_before_stop",
          "lurch", "gap_at_stop", "reversals"]
  res = {}
  for who, rs in groups.items():
    ev = []
    for R in rs:
      for e in stop_events(R, R["stock"] if who == "stock" else R["alpha"]):
        ev.append({"route": R["meta"]["route"], **e})
    res[who] = ev
  print(f"stops behind a lead (>= {STOP_BINS[0]:g} m/s to < {STOP_V} m/s, engaged, lead < 30 m): " +
        ", ".join(f"{w} n {len(ev)}" for w, ev in res.items()))
  print(f"  {'median (p25..p75)':<18}" + "".join(f"{w:>22}" for w in res))
  for k in keys:
    cells = []
    for ev in res.values():
      x = np.array([e[k] for e in ev], dtype=float)
      cells.append(f"{np.median(x):>+8.2f} ({np.percentile(x, 25):+.2f}..{np.percentile(x, 75):+.2f})" if len(x) else "-")
    print(f"  {k:<18}" + "".join(f"{c:>22}" for c in cells))
  if args.list:
    for w, ev in res.items():
      for e in ev:
        print(f"  {w:<5} {e['route']:<22} {fmt_t(e['t'])}", {k: e[k] for k in keys})
  if args.json:
    Path(args.json).write_text(json.dumps(res, indent=1))
  return 0


TTC_CAP = 20.0               # s: TTCs past this (or opening) print as the cap; no brake law looks that far ahead
GAP_BINS = (0.0, 0.8, 1.2, 1.8, 3.0, math.inf)   # s time gap d / vEgo
TTC_BINS = (0.0, 2.0, 3.0, 4.0, 6.0, 10.0, math.inf)  # s extrapolated TTC; 4.0..4.75 is where the doc puts prefill/HUD
LAW_MIN_ROWS = 5 * HZ        # a cell needs 5 s of driving before its braking share is printed


def ttc(d, v, vrel, alead):
  """Seconds until ego at constant speed reaches a lead that keeps its accel (and stops at 0, never reverses);
  TTC_CAP where it never does. alead = 0 gives the plain d / closing speed."""
  d, v, vrel, alead = (np.asarray(x, dtype=float) for x in np.broadcast_arrays(d, v, vrel, alead))
  vl = np.maximum(v + vrel, 0.0)
  al = np.minimum(np.nan_to_num(alead), 0.0)  # a lead speeding up is taken as steady: a bound on the threat
  out = np.full(d.shape, TTC_CAP)
  with np.errstate(divide="ignore", invalid="ignore"):
    # while the lead still moves: d + vrel t + al t^2 / 2 = 0, first positive root
    disc = vrel * vrel - 2.0 * al * d
    t_q = np.where(al < -1e-3, (-vrel - np.sqrt(np.maximum(disc, 0.0))) / al, d / -vrel)
    t_q = np.where((al < -1e-3) & (disc < 0), np.inf, t_q)
    t_q = np.where((al >= -1e-3) & (vrel >= 0), np.inf, t_q)
    t_stop = np.where(al < -1e-3, vl / -al, np.inf)
    # after the lead has stopped: ego covers the gap plus the lead's stopping distance
    t_after = (d + vl * vl / np.where(al < -1e-3, -2.0 * al, np.inf)) / v
    hit = np.where((t_q > 0) & (t_q <= t_stop), t_q, np.where(np.isfinite(t_stop) & (v > 0), t_after, np.inf))
  ok = np.isfinite(hit) & (hit >= 0) & np.isfinite(d)
  out[ok] = np.minimum(hit[ok], TTC_CAP)
  return out


def law_events(R: dict, who: str) -> list[dict]:
  """Every brake (command below BRAKE_ON) with a lead, the situation at its onset, and how it lets go.
  regime: 'threat' = a dash BRAKE warning within ALERT_WINDOW_S of the brake (stock only; the radar is silenced
  under openpilot long), 'set speed' = set speed at or below ego speed at the onset (ICBM or a set-speed cut, not
  the lead), 'following' = the rest. The following law is what our planner should be shaped against."""
  t, v, a, cmd, d, vrel = R["t"], R["v"], R["a"], R["cmd"], R["d"], R["vrel"]
  m = usable(R, who)
  alert = near_alert(R) if who == "stock" else np.full(len(t), np.nan)
  out = []
  for s, e in episodes(t, cmd, cmd, m):
    if np.any(np.diff(t[s:e + 1]) > 0.2):  # a cut-in has no lead before the onset, so only the onset row must be usable
      continue
    k = np.flatnonzero(cmd[s:e + 1] < BRAKE_ON)
    if not len(k):
      continue
    i = s + int(k[0])
    if not m[i]:
      continue
    if who == "stock" and np.isfinite(alert[s:e + 1]).any() and np.nanmax(alert[s:e + 1]) > 0.5:
      regime = "threat"
    elif np.isfinite(R["setv"][i]) and R["setv"][i] < v[i] + SETBIND_MS:
      regime = "set speed"
    else:
      regime = "following"
    p = s + int(np.nanargmin(cmd[s:e + 1]))
    rel = release(t, cmd, s, e)
    vr = smooth(vrel[s:e + 1])
    z = np.flatnonzero((vr >= 0) & (np.arange(s, e + 1) >= i))
    out.append({
      "t": round(float(t[i]), 1), "regime": regime, "v": round(float(v[i]), 1), "d": round(float(d[i]), 1),
      "gap_s": round(float(d[i] / max(v[i], MOVING_MIN_V)), 2), "vrel": round(float(vrel[i]), 2),
      "alead": round(float(R["alead"][i]), 2), "aleadk": round(float(R["aleadk"][i]), 2),
      "aego": round(float(a[i]), 2),
      "ttc_plain": round(float(ttc(d[i], v[i], vrel[i], 0.0)), 2),
      "ttc_alead": round(float(ttc(d[i], v[i], vrel[i], R["alead"][i])), 2),
      "ttc_aleadk": round(float(ttc(d[i], v[i], vrel[i], R["aleadk"][i])), 2),
      "peak_cmd": round(float(cmd[p]), 2), "to_peak_s": round(float(t[p] - t[i]), 2),
      "release_s": round(rel, 2) if math.isfinite(rel) else None,
      # half-release time minus the moment the gap stopped closing: positive = still braking after it opened
      "release_after_open_s": (round(float(t[p] + rel - t[s + z[0]]), 2) if len(z) and math.isfinite(rel) else None),
      "reversals": reversals(cmd[i:e + 1]),
    })
  return out


def law_grid(R: dict, who: str) -> np.ndarray:
  """Per (time gap bin, TTC bin) cell: [rows, braking rows] over non-threat, non-set-speed rows."""
  m = usable(R, who) & ~(np.isfinite(R["setv"]) & (R["setv"] < R["v"] + SETBIND_MS))
  if who == "stock":
    m &= ~(near_alert(R) > 0.5)
  g = np.digitize(R["d"][m] / R["v"][m], GAP_BINS[1:-1])
  c = np.digitize(ttc(R["d"][m], R["v"][m], R["vrel"][m], R["alead"][m]), TTC_BINS[1:-1])
  out = np.zeros((len(GAP_BINS) - 1, len(TTC_BINS) - 1, 2))
  np.add.at(out[..., 0], (g, c), 1)
  np.add.at(out[..., 1], (g, c), (R["cmd"][m] < BRAKE_ON).astype(float))
  return out


def cmd_law(args) -> int:
  """Stock's brake law split into its regimes, and ours beside it: when it starts braking, how it lets go."""
  _, routes = load_corpus(args.cache_dir)
  ours = [load(p.expanduser(), args.cache_dir) for p in args.routes] if args.routes else routes
  groups = {"stock": [R for R in routes if not R["meta"]["op_long"]], "ours": [R for R in ours if R["meta"]["op_long"]]}
  keys = ["v", "gap_s", "vrel", "alead", "aleadk", "ttc_plain", "ttc_alead", "ttc_aleadk", "peak_cmd", "to_peak_s",
          "release_s", "release_after_open_s", "reversals"]
  res, grids = {}, {}
  for who, rs in groups.items():
    ev = []
    grids[who] = sum((law_grid(R, who) for R in rs), np.zeros((len(GAP_BINS) - 1, len(TTC_BINS) - 1, 2)))
    for R in rs:
      ev += [{"route": R["meta"]["route"], **e} for e in law_events(R, who)]
    res[who] = ev
  cols = [(w, g) for w in res for g in ("following", "threat", "set speed") if not (w == "ours" and g == "threat")]
  cols = [(w, g, [e for e in res[w] if e["regime"] == g]) for w, g in cols]
  print(f"brake onsets (command < {BRAKE_ON:g}) with a lead; TTC = ego at constant speed vs the lead keeping its accel, " +
        f"capped at {TTC_CAP:g} s")
  print(f"  {'median (p25..p75)':<21}" + "".join(f"{w + ' ' + g + f' n {len(ev)}':>24}" for w, g, ev in cols))
  for k in keys:
    cells = []
    for _, _, ev in cols:
      x = np.array([e[k] for e in ev if e[k] is not None], dtype=float)
      cells.append(f"{np.median(x):+.2f} ({np.percentile(x, 25):+.1f}..{np.percentile(x, 75):+.1f})" if len(x) else "-")
    print(f"  {k:<21}" + "".join(f"{c:>24}" for c in cells))
  print(f"\nfollowing regime: share of rows braking (command < {BRAKE_ON:g}) by time gap and TTC(alead), stock / ours " +
        f"('.' = under {LAW_MIN_ROWS // HZ} s of driving)")
  lab = [f"{lo:g}-{hi:g}" if math.isfinite(hi) else f">{lo:g}" for lo, hi in zip(TTC_BINS[:-1], TTC_BINS[1:], strict=True)]
  print(f"  {'gap | TTC':<10}" + "".join(f"{x:>14}" for x in lab))
  for gi, (lo, hi) in enumerate(zip(GAP_BINS[:-1], GAP_BINS[1:], strict=True)):
    row = []
    for ci in range(len(TTC_BINS) - 1):
      c = []
      for w in ("stock", "ours"):
        n, b = grids[w][gi, ci]
        c.append(f"{100 * b / n:3.0f}" if n >= LAW_MIN_ROWS else "  .")
      row.append(" / ".join(c))
    print(f"  {(f'{lo:g}-{hi:g}' if math.isfinite(hi) else f'>{lo:g}'):<10}" + "".join(f"{x:>14}" for x in row))
  if args.list:
    for w, ev in res.items():
      for e in ev:
        print(f"  {w:<5} {e['route']:<22} {fmt_t(e['t'])} {e['regime']:<9}", {k: e[k] for k in keys})
  if args.json:
    Path(args.json).write_text(json.dumps({"events": res, "grid": {w: g.tolist() for w, g in grids.items()},
                                           "gap_bins": GAP_BINS[1:-1], "ttc_bins": TTC_BINS[1:-1]}, indent=1))
  return 0


def cmd_compare(args) -> int:
  C, _ = load_corpus(args.cache_dir)
  out = []
  if args.candidate and len(args.routes) != 1:
    raise SystemExit("--candidate scores one route at a time")
  for p in args.routes:
    R = load(p.expanduser(), args.cache_dir)
    if args.candidate:
      R = with_candidate(R, args.candidate)
    res = compare_route(R, C)
    print(f"\n{res['route']} ({res['who']} long, {res['minutes_with_lead']} min engaged with a lead): command reversals " +
          f"per minute ours {res['ours_reversals_per_min']} vs stock precedent {res['stock_reversals_per_min']}")
    print(f"  {'time':>7s} {'ours pk':>7s} {'stock pk':>8s} {'onset o/s':>11s} {'rel o/s':>9s} {'rev o/s':>7s} {'<-2.5s o/s':>10s} " +
          f"{'aEgo':>5s} {'v':>4s} {'d':>5s} {'vrel':>5s} {'aLd':>5s} {'aLdK':>5s} {'prec':>4s} {'dRel6':>16s}  verdict")
    for e in res["episodes"]:
      if e["ours_peak"] > args.min_peak and e["stock_peak"] > args.min_peak:
        continue
      k = e["at_ours_peak"]
      on = (f"{e['ours_onset'] - e['stock_onset']:+.1f}s" if e["ours_onset"] is not None and e["stock_onset"] is not None
            else f"{'o' if e['ours_onset'] is not None else '-'}/{'s' if e['stock_onset'] is not None else '-'}")
      rel = "/".join(f"{x:.1f}" if x is not None else "-" for x in (e["ours_release"], e["stock_release"]))
      print(f"  {fmt_t(e['t0']):>7s} {e['ours_peak']:+7.2f} {e['stock_peak']:+8.2f} {on:>11s} {rel:>9s} " +
            f"{e['ours_reversals']:>3d}/{e['stock_reversals']:<4.1f} {e['ours_s_below_2p5']:4.1f}/{e['stock_s_below_2p5']:<4.1f} " +
            f"{e['min_a_ego']:+5.1f} {k['v']:4.0f} {k['d']:5.0f} {k['vrel']:+5.1f} {k['alead']:+5.1f} {k['aleadk']:+5.1f} " +
            f"{e['precedent_dist']:4.1f} {slope_cell(e):>16s}  {verdict(e)}")
    print(f"  dRel6: radar distance slope (m/s) from the last lead swap (at most {SLOPE_WINDOW_S:.0f} s back) to our peak, " +
          "(segment length; 'new' = starts where the lead appears, may be a new track's range converging); " +
          "'-' = under 1 s of same-car rows. Display only")
    out.append({k: v for k, v in res.items() if not k.startswith("_")} | {"verdicts": [verdict(e) for e in res["episodes"]]})
  if args.json:
    Path(args.json).write_text(json.dumps(out, indent=1))
  return 0


def cmd_augment(args) -> int:
  C, _ = load_corpus(args.cache_dir)
  R = load(args.route.expanduser(), args.cache_dir)
  res = compare_route(R, C)
  doc = json.loads(Path(args.frames).read_text())
  frames = doc["frames"]
  t = R["t"]
  med, dist = res["_pred"]["med"][:, 0], res["_pred"]["dist"]
  ok = np.isfinite(med)
  for f in frames:
    k = int(np.clip(np.searchsorted(t, f["t"]), 1, len(t) - 1))
    k = k - 1 if abs(t[k - 1] - f["t"]) < abs(t[k] - f["t"]) else k
    good = abs(t[k] - f["t"]) < 0.1 and ok[k] and dist[k] <= NO_PRECEDENT
    f["out"]["stock_nn"] = float(med[k]) if good else None
    f.setdefault("src", {})["stock_nn"] = f"k{K} d{dist[k]:.2f}" if abs(t[k] - f["t"]) < 0.1 and math.isfinite(dist[k]) else "no lead"
  v = doc.setdefault("meta", {}).setdefault("variants", [])
  if "stock_nn" not in v:
    v.append("stock_nn")
  doc["meta"]["stock_nn"] = {"corpus_routes": C.names, "k": K, "no_precedent": NO_PRECEDENT,
                             "note": "stock ACC precedent (median of k nearest stock moments), replay evidence"}
  Path(args.out).write_text(json.dumps(doc))
  print(f"wrote {args.out}: stock_nn on {sum(f['out']['stock_nn'] is not None for f in frames)} of {len(frames)} frames")
  return 0


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = ap.add_subparsers(dest="mode", required=True)
  for name in ("build", "validate", "gain", "compare", "leadbrake", "stops", "law", "augment"):
    s = sub.add_parser(name)
    s.add_argument("--cache-dir", type=Path, required=True, help="per-route npz cache and corpus (outside the repo)")
    if name in ("build", "gain", "compare", "leadbrake", "stops", "law"):
      s.add_argument("routes", nargs="*" if name in ("gain", "leadbrake", "stops", "law") else "+", type=Path)
    if name in ("leadbrake", "stops", "law"):
      s.add_argument("--list", action="store_true", help="print every event")
    if name in ("stops", "law"):
      s.add_argument("--json")
    if name == "compare":
      s.add_argument("--json")
      s.add_argument("--min-peak", type=float, default=-1.5, help="list episodes where either side goes below this")
      s.add_argument("--candidate", type=Path, help='score this command trace instead: JSON {"t": [...], "cmd": [...]}')
    if name == "augment":
      s.add_argument("frames", type=Path)
      s.add_argument("route", type=Path)
      s.add_argument("--out", required=True)
  args = ap.parse_args()
  return {"build": cmd_build, "validate": cmd_validate, "gain": cmd_gain, "compare": cmd_compare,
          "leadbrake": cmd_leadbrake, "stops": cmd_stops, "law": cmd_law, "augment": cmd_augment}[args.mode](args)


if __name__ == "__main__":
  sys.exit(main())
