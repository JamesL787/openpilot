#!/usr/bin/env python3
"""Bosch-A object tracks as a table, one row per track per sweep, for offline shadow tests of the radar's
own fields (stopped-object detection, NORMALIZED_CLOSING, FW_LID mutual information, non-object traffic).

  bosch_a_tracks.py extract <route_dir> [--segs 3-7,11] [--out FILE.npz]
  bosch_a_tracks.py tracks  <table.npz> [--t0 S --t1 S] [--min-sweeps 10]
  bosch_a_tracks.py plot    <table.npz> --track N [--t0 S --t1 S] [--out FILE.svg] [--csv FILE.csv]

Every field of honda_bosch_a_radar.dbc is decoded with the DBC's own signal definitions (opendbc
get_raw_value), plus the raw 8 bytes of each frame. Time `t` is route seconds from segment 0's initData:
every segment's initData carries the same logMonoTime (checked on 0000025e segments 0 and 5), so a route
with no segment 0 on disk (0000025b) still gets route time.

Table (npz, columnar, numpy only):
  trk_*   one row per slot per sweep whose TRACK_ID is 1..63.
          sweep, mono (logMonoTime of the can message carrying F0), t, slot, tid, life, frame_idx, idx_ok,
          valid (the parser's STATUS / range / azimuth / life / id validity), brk, inc, age_s,
          d_rel, az_rad, y_rel (parser geometry: tan projection, left positive), vrel_u11 (the parser's
          _bosch_a_direct_vrel, no uncertainty qualification), vrel_ratio (_bosch_a_range_ratio_vrel over
          the time since this incarnation's last row), u10 (aux REL_VELOCITY_UNCERTAINTY_RAW, the name the
          radar_interface.py comments use), u11_railed (U11 raw on a rail, 0 or 1728), aux_lag_ms (AUX receive
          time minus F0's) and spread_ms (last minus first frame receive time of the slot: the jitter floor of
          a receive-time latency), then f0_* f1_* f2_* f3_* aux_* for every DBC signal. d_rel is the parser's
          (RANGE_RAW scale plus BOSCH_A_RANGE_OFFSET_M); f0_RANGE is the DBC value without that offset
          and raw (n, 5, 8) uint8 for F0..F3, AUX with have (n, 5).
          FW_LID_* names differ per slot but sit on the same bits, so they are stored by position,
          <frame>_lid_b<lsb>w<size>; lid_names maps each back to its per-slot DBC name. A LID on the same
          bits as a named signal (FW_LID_28 = RANGE_SIGMA_RAW on slot 0) is listed there, not stored twice.
          brk: -1 not valid (identity not judged), 0 same incarnation, 1 first seen, 2 lifecycle break
          (counter reset / reuse, D-049), 3 saturated hold (0xFFE -> 0xFFE, cannot testify), 4 back after
          more than BOSCH_A_STALE_S away. inc counts incarnations of a track id through the route.
          Joined from the latest message before the sweep: v_ego a_ego brake brake_pressed gas_pressed
          yaw (-livePose.angularVelocityDevice.z, left positive) yaw_cs (carState.yawRate, 0 on some
          cars) cruise_on stock_acc (cruise on, not openpilot long) op_long_active (carControl.longActive)
          lead1_tid lead2_tid lead1_d lead1_v lead1_radar, is_lead (1 lead one, 2 lead two, 0 neither),
          m_prob m_x m_y m_v (modelV2.leadsV3[0], x moved to the radar origin, y to radar sign) and
          path_y (model path y at this track's x, radar sign).
  nx_<addr>_<src>_*   non-object frames on the same clock: _mono, _t, _raw (n, 8), and decoded signals
          where the car's pt DBC defines the address (0x1DF ACC_CONTROL, 0x1FA, 0x30C, 0x33D, 0x39F, 0x240..).
          0x400/410/420/669 have no DBC and stay raw. Only src < 128 (the 128+ copies are echoes).
  meta    json: route, segments read, radar src, fingerprint, op_long, t0 mono.

Not a gate and not a parser: nothing here feeds radard. The parser-derived columns are replay values from
the checked-in helpers, and the identity rule is the lifecycle report's tested mirror of the parser's.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from array import array
from pathlib import Path

import numpy as np

import opendbc.car.honda.radar_interface as RI
from openpilot.tools.bosch_a_lifecycle_report import is_same_incarnation
from openpilot.tools.longitudinal.stock_acc_reference import DASH_ADDR, segment_files

RADAR_SRCS = (2, 128)  # the object bank arrives on 2 and again on 128; one is used, preferring 2
NX_IDS = tuple(range(0x240, 0x24B)) + (0x669, 0x400, 0x410, 0x420, 0x1DF, 0x1FA, 0x30C, 0x33D, 0x39F, DASH_ADDR)
RADAR_TO_CAMERA = 1.52  # radard.py: model x is from the camera, radar dRel from the radar
KINDS = ("f0", "f1", "f2", "f3", "aux")
LSQ_WINDOWS_S = (0.25, 0.5)  # stopshadow plan: the D-043 minimum and a 0.5 s window
LSQ_MIN_PTS = 4  # D-043 minimum samples per fit
LSQ_MIN_SPAN_FRAC = 0.75  # the fit's points must cover this share of the window (4 sweeps at ~70 ms span 0.21 s)
# vision association (modelV2 lead 0 on this track): tool defaults, not calibrated. Position and prob only: vision
# understates closing on fast or far approaches, so a speed gate would drop the stopped-car matches; vis_dv logs it
VIS_DX_M, VIS_DX_FRAC, VIS_DY_M = 3.0, 0.10, 2.0

CTX = ("v_ego", "a_ego", "brake", "brake_pressed", "gas_pressed", "yaw", "yaw_cs", "cruise_on", "stock_acc",
       "op_long_active", "lead1_tid", "lead2_tid", "lead1_d", "lead1_v", "lead1_radar", "m_prob", "m_x", "m_y", "m_v")
BASE = ("sweep", "mono", "t", "slot", "tid", "life", "frame_idx", "idx_ok", "valid", "brk", "inc", "age_s",
        "d_rel", "az_rad", "y_rel", "vrel_u11", "vrel_ratio", "u10", "u11_railed", "aux_lag_ms", "spread_ms", "is_lead", "path_y")


def parse_segs(spec: str | None) -> set[int] | None:
  if not spec:
    return None
  out: set[int] = set()
  for part in spec.split(","):
    a, _, b = part.partition("-")
    out.update(range(int(a), int(b or a) + 1))
  return out


def decode(sig, dat: bytes) -> float:
  # the same arithmetic as opendbc MessageState.parse, without its checksum / counter gating
  from opendbc.can.parser import get_raw_value
  raw = get_raw_value(dat, sig)
  if sig.is_signed:
    raw -= ((raw >> (sig.size - 1)) & 0x1) * (1 << sig.size)
  return raw * sig.factor + sig.offset


def radar_layout():
  """addr -> (slot, kind index, [(column, Signal)]) and the per-slot LID name map."""
  from opendbc.can.dbc import DBC
  dbc = DBC(RI.BOSCH_A_DBC_NAME)
  layout, lid_names = {}, []
  for slot in range(RI.BOSCH_A_NUM_SLOTS):
    for k, addr in enumerate(RI.BOSCH_A_MAIN_IDS[slot] + [RI.BOSCH_A_AUX_IDS[slot]]):
      msg = dbc.addr_to_msg[addr]
      named = {(s.lsb, s.size): n for n, s in msg.sigs.items() if not n.startswith("FW_LID_")}
      cols = []
      for n, s in msg.sigs.items():
        if n.startswith("FW_LID_"):
          alias = named.get((s.lsb, s.size))
          col = f"{KINDS[k]}_{alias}" if alias else f"{KINDS[k]}_lid_b{s.lsb}w{s.size}"
          lid_names.append(f"{slot},{col},{n}")
          if alias:
            continue
        else:
          col = f"{KINDS[k]}_{n}"
        cols.append((col, s))
      layout[addr] = (slot, k, cols)
  return layout, lid_names


def nx_layout(fingerprint: str | None):
  if not fingerprint:
    return {}
  from opendbc.can.dbc import DBC
  from openpilot.tools.longitudinal.stock_acc_reference import _dbc
  try:
    pt = DBC(_dbc(fingerprint))
  except Exception:
    return {}
  return {a: [(n, s) for n, s in pt.addr_to_msg[a].sigs.items()] for a in NX_IDS if a in pt.addr_to_msg}


class Columns:
  def __init__(self):
    self.c: dict[str, array] = {}
    self.n = 0

  def add(self, row: dict) -> None:
    for k, v in row.items():
      col = self.c.get(k)
      if col is None:
        col = self.c[k] = array("d", [math.nan]) * self.n
      col.append(v)
    self.n += 1
    for col in self.c.values():
      if len(col) < self.n:
        col.append(math.nan)

  def arrays(self, prefix: str) -> dict:
    return {prefix + k: np.frombuffer(v, dtype=float).copy() for k, v in self.c.items()}


class Extractor:
  def __init__(self):
    self.layout, self.lid_names = radar_layout()
    self.rows = Columns()
    self.raw: list[bytes] = []
    self.have: list[int] = []
    self.cur: dict[int, dict] = {}  # slot -> {kind: (dat, mono)}
    self.sweep = 0
    self.prev: dict[int, dict] = {}  # tid -> last valid row facts
    self.inc: dict[int, int] = {}
    self.ctx = dict.fromkeys(CTX, math.nan)
    self.path = None
    self.t0 = None
    self.src = None
    self.op_long, self.fingerprint = None, None
    self.nx: dict[tuple[int, int], dict] = {}
    self.nx_sigs: dict = {}

  # ---- context
  def on_msg(self, m) -> None:
    w, c = m.which(), self.ctx
    if w == "carState":
      cs = m.carState
      c.update(v_ego=cs.vEgo, a_ego=cs.aEgo, brake=cs.brake, brake_pressed=float(cs.brakePressed),
               gas_pressed=float(cs.gasPressed), yaw_cs=cs.yawRate, cruise_on=float(cs.cruiseState.enabled))
      c["stock_acc"] = float(bool(cs.cruiseState.enabled) and self.op_long is False)
    elif w == "livePose":
      c["yaw"] = -float(m.livePose.angularVelocityDevice.z)
    elif w == "carControl":
      c["op_long_active"] = float(m.carControl.longActive)
    elif w == "radarState":
      l1, l2 = m.radarState.leadOne, m.radarState.leadTwo
      c.update(lead1_tid=l1.radarTrackId if l1.status else math.nan, lead2_tid=l2.radarTrackId if l2.status else math.nan,
               lead1_d=l1.dRel if l1.status else math.nan, lead1_v=l1.vRel if l1.status else math.nan,
               lead1_radar=float(l1.radar) if l1.status else math.nan)
    elif w == "modelV2":
      md = m.modelV2
      ld = md.leadsV3[0] if len(md.leadsV3) else None
      if ld is not None and len(ld.x):
        c.update(m_prob=ld.prob, m_x=ld.x[0] - RADAR_TO_CAMERA, m_y=-ld.y[0], m_v=ld.v[0])
      else:
        c.update(m_prob=math.nan, m_x=math.nan, m_y=math.nan, m_v=math.nan)
      p = md.position
      self.path = (np.asarray(p.x) - RADAR_TO_CAMERA, -np.asarray(p.y)) if len(p.x) else None

  # ---- can
  def on_can(self, mono: int, frames) -> None:
    if self.src is None:
      srcs = {f.src for f in frames if f.address in self.layout}
      self.src = next((s for s in RADAR_SRCS if s in srcs), None)
    for f in frames:
      a = f.address
      if a in self.layout and f.src == self.src:
        slot, k, _ = self.layout[a]
        if k in self.cur.get(slot, {}):
          self.close_sweep()  # a repeat before 0x297: the sweep end was lost
        self.cur.setdefault(slot, {})[k] = (bytes(f.dat), mono)
        if a == RI.BOSCH_A_SWEEP_END_MSG:
          self.close_sweep()
      elif a in NX_IDS and f.src < 128:
        self.on_nx(mono, a, f.src, bytes(f.dat))

  def on_nx(self, mono: int, addr: int, src: int, dat: bytes) -> None:
    d = self.nx.get((addr, src))
    if d is None:
      d = self.nx[(addr, src)] = {"mono": array("q"), "raw": bytearray(), "sig": {n: array("d") for n, _ in self.nx_sigs.get(addr, [])}}
    d["mono"].append(mono)
    d["raw"] += dat[:8].ljust(8, b"\0")
    for n, s in self.nx_sigs.get(addr, []):
      d["sig"][n].append(decode(s, dat) if len(dat) * 8 > max(s.msb, s.lsb) else math.nan)

  def close_sweep(self) -> None:
    cur, self.cur = self.cur, {}
    if not cur:
      return
    for slot in sorted(cur):
      fr = cur[slot]
      if 3 not in fr:
        continue
      addrs = RI.BOSCH_A_MAIN_IDS[slot] + [RI.BOSCH_A_AUX_IDS[slot]]
      tid_sig = dict(self.layout[addrs[3]][2])["f3_TRACK_ID"]
      tid = int(decode(tid_sig, fr[3][0]))
      if not RI.BOSCH_A_TRACK_ID_MIN <= tid <= RI.BOSCH_A_TRACK_ID_MAX:
        continue
      self.add_row(slot, tid, fr, addrs)
    self.sweep += 1

  def add_row(self, slot: int, tid: int, fr: dict, addrs: list[int]) -> None:
    row: dict = {}
    raw = bytearray(40)
    have = 0
    for k in range(5):
      if k not in fr:
        continue
      dat = fr[k][0]
      raw[8 * k:8 * k + len(dat[:8])] = dat[:8]
      have |= 1 << k
      for col, s in self.layout[addrs[k]][2]:
        row[col] = decode(s, dat)
    mono = fr[0][1] if 0 in fr else fr[3][1]
    monos = [m for _, m in fr.values()]
    aux_lag = (fr[4][1] - fr[0][1]) / 1e6 if 0 in fr and 4 in fr else math.nan  # receive jitter floor for latency (E)
    spread = (max(monos) - min(monos)) / 1e6
    t = (mono - self.t0) / 1e9
    st, rr, ar = row.get("f0_STATUS", math.nan), row.get("f0_RANGE_RAW", math.nan), row.get("f0_AZIMUTH_RAW", math.nan)
    life = row.get("f2_LIFECYCLE_RAW", math.nan)
    idx = [row.get(f"{k}_FRAME_IDX") for k in KINDS[:4]]
    idx_ok = None not in idx and len(set(idx)) == 1
    valid = (all(k in fr for k in range(4)) and st != RI.BOSCH_A_STATUS_INVALID and rr != RI.BOSCH_A_RANGE_RAW_INVALID
             and ar != RI.BOSCH_A_ANGLE_RAW_INVALID and life != RI.BOSCH_A_LIFE_INVALID and idx_ok)
    d_rel = az = y_rel = vu = vr = math.nan
    if valid:
      d_rel = RI.BOSCH_A_RANGE_SCALE_M * rr + RI.BOSCH_A_RANGE_OFFSET_M
      az = RI.BOSCH_A_AZIMUTH_SCALE_RAD * (ar - RI.BOSCH_A_AZIMUTH_CENTER)
      y_rel = d_rel * (math.tan(az) if RI.BOSCH_A_USE_TAN_LATERAL_PROJECTION else math.sin(az))
    u10 = row.get("aux_REL_VELOCITY_UNCERTAINTY_RAW", math.nan)  # "u10" in radar_interface.py comments
    railed = math.nan
    if "aux_REL_VELOCITY_RAW" in row:
      v = RI._bosch_a_direct_vrel(row["aux_REL_VELOCITY_RAW"])
      vu = math.nan if v is None else v
      railed = float(row["aux_REL_VELOCITY_RAW"] in RI.BOSCH_A_DIRECT_VREL_RAILS_RAW)

    brk, inc = -1, self.inc.get(tid, 0)
    p = self.prev.get(tid)
    if valid:
      fidx, life = int(idx[0]), int(life)
      if p is None:
        brk = 1
      elif t - p["t"] > RI.BOSCH_A_STALE_S:
        brk = 4
      elif is_same_incarnation(p["idx"], p["life"], fidx, life):
        brk = 3 if life == RI.BOSCH_A_LIFE_SATURATED and p["life"] == RI.BOSCH_A_LIFE_SATURATED else 0
      else:
        brk = 2
      if brk in (1, 2, 4):
        inc += 1
        self.inc[tid] = inc
        born = t
      else:
        born = p["born"]
        if "aux_RANGE_RATIO_RAW" in row:
          v = RI._bosch_a_range_ratio_vrel(row["aux_RANGE_RATIO_RAW"], d_rel, t - p["t"])
          vr = math.nan if v is None else v
      self.prev[tid] = {"t": t, "idx": fidx, "life": life, "born": born}
    age = t - self.prev[tid]["born"] if valid else math.nan

    c = self.ctx
    is_lead = 1.0 if tid == c["lead1_tid"] else 2.0 if tid == c["lead2_tid"] else 0.0
    path_y = math.nan
    if self.path is not None and math.isfinite(d_rel) and self.path[0][0] <= d_rel <= self.path[0][-1]:
      path_y = float(np.interp(d_rel, self.path[0], self.path[1]))
    base = dict(sweep=self.sweep, mono=mono, t=t, slot=slot, tid=tid, life=life, frame_idx=idx[0] if idx[0] is not None else math.nan,
                idx_ok=float(idx_ok), valid=float(valid), brk=brk, inc=inc, age_s=age, d_rel=d_rel, az_rad=az, y_rel=y_rel,
                vrel_u11=vu, vrel_ratio=vr, u10=u10, u11_railed=railed, aux_lag_ms=aux_lag, spread_ms=spread, is_lead=is_lead, path_y=path_y)
    self.rows.add({**base, **{k: float(c[k]) for k in CTX}, **row})
    self.raw.append(bytes(raw))
    self.have.append(have)

  def run(self, files: list[Path]) -> None:
    from openpilot.tools.lib.logreader import LogReader
    self.op_long, self.fingerprint = None, None
    for path in files:  # carParams first, so every row knows stock vs openpilot long and nx knows its DBC
      for m in LogReader(str(path)):
        if m.which() == "carParams":
          self.op_long = bool(m.carParams.openpilotLongitudinalControl)
          self.fingerprint = str(m.carParams.carFingerprint)
          break
      if self.fingerprint is not None:
        break
    self.nx_sigs = nx_layout(self.fingerprint)
    for path in files:
      for m in LogReader(str(path), sort_by_time=True):
        w = m.which()
        if w == "initData" and self.t0 is None:
          self.t0 = m.logMonoTime  # the same value in every segment: segment 0's
        if self.t0 is None:
          continue
        if w == "can":
          self.on_can(m.logMonoTime, m.can)
        else:
          self.on_msg(m)
    self.close_sweep()

  def table(self, meta: dict) -> dict:
    out = self.rows.arrays("trk_")
    for k in ("trk_mono",):
      out[k] = out[k].astype(np.int64) if k in out else np.zeros(0, np.int64)
    n = self.rows.n
    out["trk_raw"] = np.frombuffer(b"".join(self.raw), dtype=np.uint8).reshape(n, 5, 8) if n else np.zeros((0, 5, 8), np.uint8)
    out["trk_have"] = np.array([[(h >> k) & 1 for k in range(5)] for h in self.have], dtype=bool).reshape(n, 5)
    out["lid_names"] = np.array(self.lid_names)
    for (addr, src), d in sorted(self.nx.items()):
      p = f"nx_{addr:03x}_{src}_"
      mono = np.frombuffer(d["mono"], dtype=np.int64).copy()
      out[p + "mono"] = mono
      out[p + "t"] = (mono - self.t0) / 1e9
      out[p + "raw"] = np.frombuffer(bytes(d["raw"]), dtype=np.uint8).reshape(-1, 8)
      for s, col in d["sig"].items():
        out[p + s] = np.frombuffer(col, dtype=float).copy()
    meta = {**meta, "radar_src": self.src, "fingerprint": self.fingerprint, "op_long": self.op_long, "t0_mono": self.t0,
            "sweeps": self.sweep, "rows": n}
    out["meta"] = np.array(json.dumps(meta))
    return out


def cmd_extract(args) -> int:
  route = Path(args.route)
  want = parse_segs(args.segs)
  files = [p for p in segment_files(route) if want is None or int(p.parent.name) in want]
  if not files:
    print(f"no rlogs under {route} for segments {args.segs or 'all'}", file=sys.stderr)
    return 1
  ex = Extractor()
  ex.run(files)
  if ex.t0 is None:
    print("no initData in these segments", file=sys.stderr)
    return 1
  name = route.name if route.name != "." else "route"
  out = Path(args.out or f"/tmp/bosch_a_tracks_{name}{'_' + args.segs.replace(',', '_') if args.segs else ''}.npz")
  tab = ex.table({"route": name, "segments": sorted(int(p.parent.name) for p in files)})
  np.savez_compressed(out, **tab)
  meta = json.loads(str(tab["meta"]))
  nx = sorted({k.split("_")[1] + "/" + k.split("_")[2] for k in tab if k.startswith("nx_")})
  print(f"{out}: {meta['rows']} track rows over {meta['sweeps']} sweeps, radar src {meta['radar_src']}, "
        + f"segments {meta['segments'][0]}..{meta['segments'][-1]} ({len(files)}), non-object ids {' '.join(nx)}")
  return 0


def load(path: str) -> dict:
  z = np.load(path, allow_pickle=False)
  D = {k: z[k] for k in z.files}
  D["meta"] = json.loads(str(D["meta"]))
  return D


def trk(D: dict, tid: int | None = None, t0: float = -math.inf, t1: float = math.inf) -> dict:
  sel = (D["trk_t"] >= t0) & (D["trk_t"] <= t1)
  if tid is not None:
    sel &= D["trk_tid"] == tid
  return {k[4:]: v[sel] for k, v in D.items() if k.startswith("trk_")}


def lsq_slope(t: np.ndarray, d: np.ndarray, key: np.ndarray, win_s: float = LSQ_WINDOWS_S[0]) -> np.ndarray:
  """Trailing least-squares slope of d over the rows of the same key within win_s (rows ordered by time within a key).

  NaN until the window holds LSQ_MIN_PTS finite points covering LSQ_MIN_SPAN_FRAC of win_s."""
  out = np.full(len(t), np.nan)
  for i in range(len(t)):
    j = i
    while j > 0 and key[j - 1] == key[i] and t[i] - t[j - 1] <= win_s + 1e-6:
      j -= 1
    tt, dd = t[j:i + 1], d[j:i + 1]
    ok = np.isfinite(dd)
    if ok.sum() >= LSQ_MIN_PTS and tt[ok][-1] - tt[ok][0] >= LSQ_MIN_SPAN_FRAC * win_s:
      out[i] = np.polyfit(tt[ok] - tt[ok][-1], dd[ok], 1)[0]
  return out


def strict_key(tid: np.ndarray, inc: np.ndarray, brk: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
  """Fit key for ground truth: a saturated hold (brk 3) cannot testify, so it ends the window and its rows drop out."""
  sat = brk == 3
  runs = np.cumsum(np.r_[False, sat[1:] != sat[:-1]])
  return tid * 1e9 + inc * 1e5 + runs, sat


def derived(T: dict, win_s: float = LSQ_WINDOWS_S[0]) -> dict:
  key = T["tid"] * 1e9 + T["inc"] * 1e5
  slope = lsq_slope(T["t"], T["d_rel"], key, win_s)
  skey, sat = strict_key(T["tid"], T["inc"], T["brk"])
  slope_strict = lsq_slope(T["t"], np.where(sat, np.nan, T["d_rel"]), skey, win_s)
  yaw = np.where(np.isfinite(T["yaw"]), T["yaw"], T["yaw_cs"])
  # range rate of a stationary point: -v + w*y, w and y both left positive. Replay check (0000025e, 00000297,
  # 82 range-confirmed stopped rows on 37 tracks): dy/dt follows -w*x (median |r| 0.5-1.1 m/s) not +w*x (2.8-3.5).
  stat = -T["v_ego"] + yaw * T["y_rel"]
  v_abs = T["v_ego"] + slope - yaw * T["y_rel"]
  vis = ((np.abs(T["m_x"] - T["d_rel"]) < np.maximum(VIS_DX_M, VIS_DX_FRAC * T["d_rel"])) & (np.abs(T["m_y"] - T["y_rel"]) < VIS_DY_M)
         & (T["m_prob"] > 0.5))
  return {"slope": slope, "slope_strict": slope_strict, "stat_ref": stat, "nc_d": T["f2_NORMALIZED_CLOSING"] * T["d_rel"],
          "v_abs": v_abs, "v_abs_strict": T["v_ego"] + slope_strict - yaw * T["y_rel"],
          "v_abs_u11": T["v_ego"] + T["vrel_u11"] - yaw * T["y_rel"], "vis_assoc": vis.astype(float),
          "vis_dv": np.where(vis, T["m_v"] - v_abs, np.nan)}


def cmd_tracks(args) -> int:
  D = load(args.table)
  T = trk(D, None, args.t0, args.t1)
  T = {k: v[T["valid"] > 0] for k, v in T.items()}
  print(f"{D['meta']['route']}  {args.t0:.1f}..{args.t1:.1f} s")
  print("  tid inc   first    last  sweeps  d first  d min  d last   |y| med  lead%  u11 med  brk>1")
  keys = sorted({(int(a), int(b)) for a, b in zip(T["tid"], T["inc"], strict=True)}, key=lambda k: (T["t"][(T["tid"] == k[0]) & (T["inc"] == k[1])][0]))
  for tid, inc in keys:
    s = (T["tid"] == tid) & (T["inc"] == inc)
    if s.sum() < args.min_sweeps:
      continue
    d, y, u = T["d_rel"][s], T["y_rel"][s], T["vrel_u11"][s]
    u_med = np.nanmedian(u) if np.isfinite(u).any() else math.nan
    print(f"  {tid:3d} {inc:3d} {T['t'][s][0]:7.1f} {T['t'][s][-1]:7.1f} {s.sum():7d} {d[0]:8.1f} {d.min():6.1f} {d[-1]:7.1f} "
          + f"{np.median(np.abs(y)):9.2f} {100 * np.mean(T['is_lead'][s] == 1):6.0f} {u_med:8.2f} "
          + f"{int(np.sum(T['brk'][s] == 2)):6d}")
  return 0


# ---- SVG, no plotting library needed
COLORS = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#17becf")


def _svg_panels(title: str, t0: float, t1: float, panels: list[dict], marks: list[tuple[float, str, str]]) -> str:
  W, left, right, ph, gap, top = 1400, 70, 230, 150, 26, 40
  H = top + len(panels) * (ph + gap) + 30
  sx = lambda t: left + (t - t0) / max(t1 - t0, 1e-9) * (W - left - right)  # noqa: E731
  out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif" font-size="11">',
         '<rect width="100%" height="100%" fill="white"/>', f'<text x="{left}" y="20" font-size="14">{title}</text>']
  for i, p in enumerate(panels):
    y0 = top + i * (ph + gap)
    vals = np.concatenate([np.asarray(s[2], float)[np.isfinite(np.asarray(s[2], float))] for s in p["series"]] or [np.zeros(0)])
    lo, hi = (float(vals.min()), float(vals.max())) if len(vals) else (0.0, 1.0)
    if p.get("ylim"):
      lo, hi = p["ylim"]
    if hi - lo < 1e-6:
      lo, hi = lo - 1, hi + 1
    pad = 0.05 * (hi - lo)
    lo, hi = lo - pad, hi + pad
    sy = lambda v, y0=y0, lo=lo, hi=hi: y0 + ph - (v - lo) / (hi - lo) * ph  # noqa: E731
    out.append(f'<rect x="{left}" y="{y0}" width="{W - left - right}" height="{ph}" fill="none" stroke="#999"/>')
    out.append(f'<text x="{left + 4}" y="{y0 + 12}" font-weight="bold">{p["label"]}</text>')
    for v in np.linspace(lo + pad, hi - pad, 4):
      out.append(f'<text x="{left - 4}" y="{sy(v) + 4:.1f}" text-anchor="end">{v:.1f}</text>')
      out.append(f'<line x1="{left}" x2="{W - right}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="#eee"/>')
    if lo < 0 < hi:
      out.append(f'<line x1="{left}" x2="{W - right}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" stroke="#bbb"/>')
    for t, color, _ in marks:
      out.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{y0}" y2="{y0 + ph}" stroke="{color}" stroke-dasharray="3,3"/>')
    for j, (name, t, v, *style) in enumerate(p["series"]):
      color = style[0] if style else COLORS[j % len(COLORS)]
      dots = len(style) > 1 and style[1] == "dots"
      t, v = np.asarray(t, float), np.asarray(v, float)
      if dots:
        out += [f'<circle cx="{sx(a):.1f}" cy="{sy(b):.1f}" r="1.8" fill="{color}"/>' for a, b in zip(t, v, strict=True) if math.isfinite(b)]
      else:
        seg: list[str] = []
        for a, b in zip(list(t) + [math.nan], list(v) + [math.nan], strict=True):
          if math.isfinite(a) and math.isfinite(b):
            seg.append(f"{sx(a):.1f},{sy(b):.1f}")
          elif seg:
            out.append(f'<polyline points="{" ".join(seg)}" fill="none" stroke="{color}" stroke-width="1.3"/>')
            seg = []
      out.append(f'<text x="{W - right + 6}" y="{y0 + 14 + 13 * j}" fill="{color}">{name}</text>')
  y = H - 12
  for v in np.linspace(t0, t1, 9):
    out.append(f'<text x="{sx(v):.1f}" y="{y}" text-anchor="middle">{v:.1f}</text>')
  out.append(f'<text x="{W - right + 30}" y="{y}">route s</text>')
  for k, (color, label) in enumerate(dict.fromkeys((c, lbl) for _, c, lbl in marks)):
    out.append(f'<text x="{W - right + 6}" y="{14 + 12 * k}" fill="{color}">- - {label}</text>')  # above the first panel's legend
  out.append("</svg>")
  return "\n".join(out)


def cmd_plot(args) -> int:
  D = load(args.table)
  T = trk(D, args.track, args.t0, args.t1)
  T = {k: v[T["valid"] > 0] for k, v in T.items()}
  if not len(T["t"]):
    print(f"track {args.track} has no valid rows in {args.t0}..{args.t1}", file=sys.stderr)
    return 1
  t0 = args.t0 if math.isfinite(args.t0) else float(T["t"][0])
  t1 = args.t1 if math.isfinite(args.t1) else float(T["t"][-1])
  X = derived(T, args.win)
  t = T["t"]
  lead1 = T["is_lead"] == 1
  marks = [(float(a), "#d62728", "lifecycle break / return") for a in t[np.isin(T["brk"], (2, 4))]]
  meta = D["meta"]
  k = f"nx_{DASH_ADDR:03x}_"
  for key in [x for x in D if x.startswith(k) and x.endswith("_raw")]:
    tt = D[key[:-3] + "t"]
    on = (D[key][:, 4] == 185) & (tt >= t0) & (tt <= t1)
    edges = np.flatnonzero(np.diff(np.concatenate([[False], on]).astype(int)) == 1)
    marks += [(float(tt[i]), "#ff7f0e", "dash BRAKE (0x374 = 185)") for i in edges]
  acc_key = next((x for x in D if x.startswith(f"nx_{0x1DF:03x}_") and x.endswith("ACCEL_COMMAND")), None)
  panels = [
    {"label": "dRel (m)", "series": [("dRel", t, T["d_rel"], "#1f77b4", "dots"),
                                      ("lead one dRel", t, np.where(np.isfinite(T["lead1_d"]), T["lead1_d"], np.nan), "#999"),
                                      ("model lead x", t, np.where(T["m_prob"] > 0.5, T["m_x"], np.nan), "#2ca02c")]},
    {"label": f"LSQ dRel slope ({args.win:g} s, >= {LSQ_MIN_PTS} pts) vs stationary -vEgo+wy (m/s)",
     "series": [("slope", t, X["slope"], "#1f77b4"), ("slope, sat hold ends fit", t, X["slope_strict"], "#ff7f0e", "dots"),
                ("-vEgo + w*y", t, X["stat_ref"], "#999")]},
    {"label": "U11 vRel and range-ratio vRel (m/s)",
     "series": [("U11 vRel", t, T["vrel_u11"], "#1f77b4", "dots"), ("ratio vRel", t, T["vrel_ratio"], "#9467bd", "dots"),
                ("slope", t, X["slope"], "#bbb")]},
    {"label": "NORMALIZED_CLOSING x dRel", "series": [("NC*dRel", t, X["nc_d"], "#1f77b4", "dots"), ("slope", t, X["slope"], "#bbb"),
                                                      ("-vEgo + w*y", t, X["stat_ref"], "#999")]},
    {"label": "vAbs = vEgo + slope - w*y (m/s)", "series": [("vAbs (slope)", t, X["v_abs"], "#1f77b4"),
                                                           ("vAbs (U11)", t, X["v_abs_u11"], "#9467bd", "dots"),
                                                           ("vEgo", t, T["v_ego"], "#999")]},
    {"label": "yRel and model path at this x (m, left +)", "series": [("yRel", t, T["y_rel"], "#1f77b4", "dots"),
                                                                     ("path y", t, T["path_y"], "#2ca02c")]},
    {"label": "lead / ACC", "series": [("is lead one", t, lead1.astype(float) * 3, "#d62728"),
                                       ("is lead two", t, (T["is_lead"] == 2).astype(float) * 2.5, "#ff7f0e"),
                                       ("stock ACC", t, T["stock_acc"] * 2, "#2ca02c"), ("OP long", t, T["op_long_active"] * 1.5, "#1f77b4"),
                                       ("brake pedal", t, T["brake_pressed"], "#8c564b"), ("aEgo/4", t, T["a_ego"] / 4, "#999"),
                                       ("vision on track", t, X["vis_assoc"] * 1.2, "#9467bd"),
                                       ("U11 railed", t, T.get("u11_railed", t * np.nan) * 0.6, "#e377c2")]},
  ]
  if acc_key:
    at = D[acc_key[:acc_key.rindex("_ACCEL_COMMAND")] + "_t"]
    s = (at >= t0) & (at <= t1)
    panels[-1]["series"].append(("stock cmd/4", at[s], D[acc_key][s] / 4, "#17becf"))
  hud_key = next((x for x in D if x.startswith(f"nx_{0x30C:03x}_") and x.endswith("_HUD_LEAD")), None)
  if hud_key:  # dash lead icon: 0 no car, 1 dashed, 2 solid, 3 acc off
    ht = D[hud_key[:hud_key.rindex("_HUD_LEAD")] + "_t"]
    s = (ht >= t0) & (ht <= t1)
    panels[-1]["series"].append(("dash lead icon/2", ht[s], D[hud_key][s] / 2, "#bcbd22"))
  title = f"{meta['route']} track {args.track}  {t0:.1f}..{t1:.1f} s  ({len(t)} sweeps, incarnations {sorted({int(x) for x in T['inc']})})"
  out = Path(args.out or f"/tmp/bosch_a_track_{meta['route']}_{args.track}_{t0:.0f}.svg")
  out.write_text(_svg_panels(title, t0, t1, panels, marks))
  print(out)
  if args.csv:
    cols = ["t", "inc", "brk", "d_rel", "y_rel", "path_y", "vrel_u11", "vrel_ratio", "f2_NORMALIZED_CLOSING", "f2_NORMALIZED_CLOSING_SIGMA_RAW",
            "f1_OBJECT_EXISTENCE_PROBABILITY_RAW", "f0_RANGE_SIGMA_RAW", "f0_RANGE", "u10", "u11_railed", "aux_lag_ms", "spread_ms",
            "v_ego", "yaw", "is_lead", "stock_acc", "op_long_active", "m_x", "m_y", "m_v", "m_prob"]
    cols = [c for c in cols if c in T]  # tables extracted before a column existed
    with open(args.csv, "w") as f:
      f.write(",".join(cols + list(X)) + "\n")
      for i in range(len(t)):
        f.write(",".join(f"{float(T[c][i]):.4g}" for c in cols) + "," + ",".join(f"{float(X[c][i]):.4g}" for c in X) + "\n")
    print(args.csv)
  return 0


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = ap.add_subparsers(dest="mode", required=True)
  e = sub.add_parser("extract")
  e.add_argument("route")
  e.add_argument("--segs", help="segment list, e.g. 3-7,11 (default: every segment on disk)")
  e.add_argument("--out")
  for name in ("tracks", "plot"):
    p = sub.add_parser(name)
    p.add_argument("table")
    p.add_argument("--t0", type=float, default=-math.inf)
    p.add_argument("--t1", type=float, default=math.inf)
    if name == "tracks":
      p.add_argument("--min-sweeps", type=int, default=10)
    else:
      p.add_argument("--track", type=int, required=True)
      p.add_argument("--out")
      p.add_argument("--csv")
      p.add_argument("--win", type=float, default=LSQ_WINDOWS_S[0], help="LSQ slope window, s (plan: 0.25 or 0.5)")
  args = ap.parse_args(argv)
  return {"extract": cmd_extract, "tracks": cmd_tracks, "plot": cmd_plot}[args.mode](args)


if __name__ == "__main__":
  sys.exit(main())
