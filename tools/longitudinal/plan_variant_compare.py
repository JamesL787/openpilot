#!/usr/bin/env python3
"""Side-by-side planner-variant pages from closed-loop replay frames (alpha_closed_loop_replay.py --frames-json).

Simulation / replay, not driven. Inside --sim-window every variant in a frame's `sim` field drives its own simulated
car (first-order delay model, see SimCar); the lead, camera and radar are the logged ones. gap_shift is how far that car
has fallen behind the logged one, so its gap to the lead is replayed dRel + gap_shift. Past DRIFT_M of drift the logged
world no longer matches what that car would have seen, and the traces are drawn dashed from there.

One page per frames JSON plus index.html:
  plan_variant_compare.py /tmp/rv/plan/nocaps/NC_*.json --out /tmp/pvc [--base b0.075 --cmp x_nocap]

Per window: planner command (output_a_target), sim aEgo, sim vEgo and gap for each variant on one time axis, with the
logged car, the replayed radar lead and the camera lead underneath; first command <= -0.5 / -1.5 and min gap marked per
variant; spans where |base - cmp| > BIND_DIFF shaded. Once the two sim cars differ in speed (DIVERGE_V) they no longer
see the same scene, so a shaded span after that line is not the caps alone. A bird's-eye strip under the plots moves
every sim car against the logged scene.

If the JSON sits next to <stem>.trace.json (lpxwrap `_trace`), the lpx.py lines that changed output_a_target in each
cycle are listed under the cursor.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

import numpy as np

from openpilot.tools.longitudinal.analyze_route_longitudinal import threshold_sign_changes

BRAKE_MARKS = (-0.5, -1.5)   # first command at or below each, per variant (Radar Work (Bob), 2026-09-29)
BRAKE_TIME = -0.5            # time spent with the command below this
BIND_DIFF = 0.3              # |base - cmp| command gap that counts as the caps binding
BIND_MERGE_S = 0.15          # join shaded spans closer than this
DIVERGE_V = 0.05             # m/s between the two sim cars: past this they see different scenes
DRIFT_M = 10.0               # |gap_shift| past which the logged world no longer matches the sim car (long_replay_viewer)
PAD_S = 3.0                  # plotted before and after the sim window
VIS_PROB = 0.5               # camera lead drawn at or above this
SMOOTH_FRAC = 0.10           # jrms ratio beyond which "smoother?" says yes/no instead of same
JRMS_FLAT = 0.05             # m/s³: a base jrms below this is a flat command, and a ratio against it means nothing
SIM_DELAY, SIM_TAU = 0.1, 0.3  # alpha_closed_loop_replay SimCar's actuator model, used to recover the residual it added
RESID_HOLD = 0.3             # residual (m/s²) that, with the logged car stopped, is its brakes holding it
STOP_V = 0.1                 # logged vEgo below this counts as stopped; a sim car above it is moving
CLOSER_M = 1.0               # min-gap loss that counts as closer
LATER_S = 0.3                # first-brake delay that counts as later

LABELS = {"b0.075": "base", "x_nocap": "nocaps", "x_none": "lpx base", "nobound": "nobound", "mvl": "mvl"}
COLORS = {"b0.075": "#1f5fbf", "x_nocap": "#d62728", "mvl": "#2ca02c", "x_none": "#9467bd", "nobound": "#8c564b"}
SPARE = ["#ff7f0e", "#17becf", "#bcbd22", "#e377c2", "#7f7f7f"]


def label(v: str) -> str:
  return LABELS.get(v, v)


def mmss(t: float) -> str:
  return f"{int(t // 60)}:{t % 60:04.1f}"


def fnum(x, nd=2):
  return None if x is None or not math.isfinite(float(x)) else round(float(x), nd)


def load(path: Path) -> dict:
  D = json.loads(path.read_text())
  fr = D["frames"]
  n = len(fr)
  t = np.array([f["t"] for f in fr])
  sim_keys: list[str] = []
  for f in fr:
    for k in f.get("sim") or {}:
      if k not in sim_keys:
        sim_keys.append(k)
  W = {"path": path, "meta": D["meta"], "t": t, "v_ego": np.array([f["v_ego"] for f in fr]),
       "a_ego": np.array([f["a_ego"] for f in fr]), "cmd_log": np.array([f["accel_cmd"] for f in fr]),
       "engaged": np.array([bool(f["engaged"]) for f in fr]), "sim_keys": sim_keys}
  W["out"] = {k: np.array([f["out"].get(k, np.nan) for f in fr]) for k in fr[0]["out"]}
  for i, name in enumerate(("sv", "sa", "gs")):
    W[name] = {k: np.array([(f.get("sim") or {}).get(k, [np.nan] * 3)[i] for f in fr]) for k in sim_keys}
  ld = [f.get("lead") or {} for f in fr]
  W["d"] = np.array([x["d"] if x.get("status") else np.nan for x in ld])
  W["vlead"] = W["v_ego"] + np.array([x["vRel"] if x.get("status") else np.nan for x in ld])
  W["track"] = [x.get("track") if x.get("status") and x.get("radar") else None for x in ld]
  vis = [f.get("vis") or {} for f in fr]
  W["visx"] = np.array([x["x"] if x.get("p", 0) >= VIS_PROB else np.nan for x in vis])
  W["visp"] = np.array([x.get("p", np.nan) for x in vis])
  W["visv"] = np.array([x["v"] if x.get("p", 0) >= VIS_PROB else np.nan for x in vis])
  W["gap"] = {k: W["d"] + W["gs"][k] for k in sim_keys}
  W["resid"] = residual(W, sim_keys[0]) if sim_keys else np.full(n, np.nan)
  tr = path.with_name(path.stem + ".trace.json")
  W["trace"] = None
  if tr.exists():
    T = json.loads(tr.read_text())
    key = next(iter(T))
    if len(T[key]) == n:
      W["trace"] = {"key": key, "rows": [r[1] for r in T[key]]}
  return W


class _FirstOrderDelay:
  """alpha_closed_loop_replay._FirstOrderDelay, 0.05 s ticks."""
  def __init__(self, a0: float):
    self.a, self.buf = a0, []

  def step(self, u: float, dt: float) -> float:
    self.buf.append(u)
    ud = self.buf.pop(0) if len(self.buf) > round(SIM_DELAY / 0.05) else self.buf[0]
    self.a += (ud - self.a) * min(dt / SIM_TAU, 1.0)
    return self.a


def residual(W: dict, k: str) -> np.ndarray:
  """The residual SimCar added to every sim car: its aEgo minus its own actuator model driven by its previous command.
  It is the logged car's aEgo minus the model of the logged command, the same for every variant (to rounding), and is
  what carries road grade and brake hold into the sim. Recovered from the sim car, so FORCE-zeroed frames read 0."""
  r = np.full(len(W["t"]), np.nan)
  idx = np.where(np.isfinite(W["sv"][k]))[0]
  if idx.size < 2:
    return r
  m = _FirstOrderDelay(float(W["sa"][k][idx[0]]))
  r[idx[0]] = 0.0
  for a, b in zip(idx, idx[1:], strict=False):
    dt = min(W["t"][b] - W["t"][a], 0.2) if b == a + 1 else 0.05
    r[b] = W["sa"][k][b] - m.step(float(W["out"][k][a]), dt)
  return r


def dedupe(W: dict, order: list[str]) -> tuple[list[str], dict[str, str]]:
  """Variants whose sim car matches an earlier one everywhere are dropped from the plot and named in the note."""
  keep, same = [], {}
  for k in order:
    m = np.isfinite(W["sv"][k])
    twin = next((q for q in keep if np.allclose(W["out"][q][m], W["out"][k][m], atol=1e-6)
                 and np.allclose(W["sv"][q][m], W["sv"][k][m], atol=1e-4, equal_nan=True)), None)
    if twin is None:
      keep.append(k)
    else:
      same[k] = twin
  return keep, same


def spans(t: np.ndarray, mask: np.ndarray, merge: float) -> list[tuple[float, float]]:
  out: list[list[float]] = []
  for i in np.where(mask)[0]:
    if out and t[i] - out[-1][1] <= merge:
      out[-1][1] = t[i]
    else:
      out.append([t[i], t[i]])
  return [(a, b) for a, b in out]


def metrics(W: dict, k: str, judge_to: float = np.inf) -> dict:
  """Command and gap scores inside the sim window up to judge_to (the first push or drift of the judged pair, so both
  variants are scored over the same span); min_gap, drift and push over the whole window."""
  t, m = W["t"], np.isfinite(W["sv"][k])
  if (m & (t < judge_to)).sum() < 3:
    return {"n": int((m & (t < judge_to)).sum())}
  tt = t[m]
  j = tt < judge_to
  cmd = W["out"][k][m][j]
  dt = np.diff(tt[j])
  jerk = np.diff(cmd) / np.maximum(dt, 1e-3)
  gap = W["gap"][k][m]
  firsts = {}
  for thr in BRAKE_MARKS:
    idx = np.where(cmd <= thr)[0]
    firsts[thr] = float(tt[j][idx[0]]) if idx.size else None
  gi = int(np.nanargmin(gap)) if np.isfinite(gap).any() else None
  drift = np.where(np.abs(W["gs"][k][m]) > DRIFT_M)[0]
  # logged car stopped and held by its brakes: the residual is the hold, and a sim car still moving is pushed by it
  push = np.where((W["v_ego"][m] < STOP_V) & (W["resid"][m] > RESID_HOLD) & (W["sv"][k][m] > STOP_V))[0]
  cut = min([tt[drift[0]] if drift.size else np.inf, tt[push[0]] if push.size else np.inf, judge_to])
  trusted = np.where(tt < cut, gap, np.nan)
  ti = int(np.nanargmin(trusted)) if np.isfinite(trusted).any() else None
  lost = None
  if gi is not None:
    # lead gone while this car was still moving toward where it was: the min gap is only up to the last radar point
    after = np.where(~np.isfinite(gap[gi:]) & (W["sv"][k][m][gi:] > 0.5))[0]
    lost = float(tt[gi + after[0]]) if after.size else None
  return {
    "n": int(j.sum()), "t0": float(tt[0]), "t1": float(tt[j][-1]), "judge_to": None if not np.isfinite(judge_to) else float(judge_to),
    "peak_cmd": float(cmd.min()), "max_cmd": float(cmd.max()),
    "jrms": float(np.sqrt(np.mean(jerk ** 2))) if jerk.size else None,
    "flips": threshold_sign_changes(cmd.tolist()),
    "t_brake": float(np.sum(dt[cmd[:-1] < BRAKE_TIME])),
    "first": firsts,
    "min_gap": float(gap[gi]) if gi is not None else None, "t_min_gap": float(tt[gi]) if gi is not None else None,
    "min_a": float(np.nanmin(W["sa"][k][m][j])), "v_end": float(W["sv"][k][m][-1]),
    "drift_t": float(tt[drift[0]]) if drift.size else None, "lead_lost_t": lost,
    "push_t": float(tt[push[0]]) if push.size else None, "push_s": float(push.size * 0.05),
    "trusted_gap": float(trusted[ti]) if ti is not None else None, "t_trusted_gap": float(tt[ti]) if ti is not None else None,
  }


def compare(W: dict, base: str, cmp: str) -> dict:
  t = W["t"]
  both = np.isfinite(W["sv"][base]) & np.isfinite(W["sv"][cmp])
  diff = np.abs(W["out"][base] - W["out"][cmp])
  bind = spans(t, both & (diff > BIND_DIFF), BIND_MERGE_S)
  dv = np.where(both & (np.abs(W["sv"][base] - W["sv"][cmp]) > DIVERGE_V))[0]
  return {"bind": bind, "bind_s": float(sum(b - a for a, b in bind)), "diverge_t": float(t[dv[0]]) if dv.size else None}


def verdicts(mb: dict, mc: dict) -> tuple[str, str]:
  if not mb.get("jrms") or mc.get("jrms") is None:
    return "-", "-"
  if mb["jrms"] < JRMS_FLAT:
    smooth = ("same" if mc["jrms"] < JRMS_FLAT else "no") + f" (base flat, jrms {mb['jrms']:.2f} -> {mc['jrms']:.2f}"
  else:
    r = mc["jrms"] / mb["jrms"]
    smooth = ("yes" if r < 1 - SMOOTH_FRAC else "no" if r > 1 + SMOOTH_FRAC else "same") + f" (jrms x{r:.2f}"
  smooth += f", flips {mb['flips']}->{mc['flips']})" if mc["flips"] != mb["flips"] else ")"
  parts = []
  gb, gc = mb["trusted_gap"], mc["trusted_gap"]
  if gb is not None and gc is not None and gc < gb - CLOSER_M:
    parts.append(f"closer {gb - gc:.1f} m")
  for thr in BRAKE_MARKS:
    fb, fc = mb["first"][thr], mc["first"][thr]
    if fb is not None and (fc is None or fc - fb > LATER_S):
      parts.append(f"<={thr:g} " + ("never" if fc is None else f"later {fc - fb:.1f} s"))
  return smooth, ", ".join(parts) if parts else "no"


# ---------------------------------------------------------------- SVG
PW, PH, ML, MR, MT, MB = 1100, 190, 60, 20, 14, 22


class Panel:
  def __init__(self, title: str, t0: float, t1: float, ys: list[np.ndarray], pad=0.08, force=()):
    vals = np.concatenate([y[np.isfinite(y)] for y in ys] + [np.array(force, dtype=float)])
    lo, hi = (float(vals.min()), float(vals.max())) if vals.size else (0.0, 1.0)
    if hi - lo < 1e-3:
      lo, hi = lo - 1, hi + 1
    p = (hi - lo) * pad
    self.lo, self.hi, self.t0, self.t1, self.title = lo - p, hi + p, t0, t1, title
    self.el: list[str] = []

  def x(self, t):
    return ML + (t - self.t0) / (self.t1 - self.t0) * (PW - ML - MR)

  def y(self, v):
    return MT + (self.hi - v) / (self.hi - self.lo) * (PH - MT - MB)

  def line(self, t, y, color, width=1.6, dash=None, drift_t=None, opacity=1.0):
    m = np.isfinite(y) & (t >= self.t0) & (t <= self.t1)
    if drift_t is not None:
      self._poly(t, y, m & (t <= drift_t), color, width, dash, opacity)
      self._poly(t, y, m & (t >= drift_t), color, width, "5,4", opacity * 0.8)
    else:
      self._poly(t, y, m, color, width, dash, opacity)

  def _poly(self, t, y, m, color, width, dash, opacity):
    seg: list[str] = []
    prev = -2
    for i in np.where(m)[0]:
      if i != prev + 1 and len(seg) > 1:
        self._emit(seg, color, width, dash, opacity)
        seg = []
      elif i != prev + 1:
        seg = []
      seg.append(f"{self.x(t[i]):.1f},{self.y(y[i]):.1f}")
      prev = i
    if len(seg) > 1:
      self._emit(seg, color, width, dash, opacity)

  def _emit(self, pts, color, width, dash, opacity):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    self.el.append(f'<polyline fill="none" stroke="{color}" stroke-width="{width}" opacity="{opacity}"{d} points="{" ".join(pts)}"/>')

  def dots(self, t, y, color, r=1.6):
    m = np.isfinite(y) & (t >= self.t0) & (t <= self.t1)
    self.el += [f'<circle cx="{self.x(a):.1f}" cy="{self.y(b):.1f}" r="{r}" fill="{color}" opacity="0.55"/>' for a, b in zip(t[m], y[m], strict=True)]

  def hline(self, v, color="#999", dash="3,3"):
    if self.lo <= v <= self.hi:
      self.el.append(f'<line x1="{ML}" x2="{PW - MR}" y1="{self.y(v):.1f}" y2="{self.y(v):.1f}" stroke="{color}" stroke-dasharray="{dash}"/>')

  def vline(self, t, color, dash="4,3", text=None):
    if self.t0 <= t <= self.t1:
      x = self.x(t)
      self.el.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{MT}" y2="{PH - MB}" stroke="{color}" stroke-dasharray="{dash}"/>')
      if text:
        self.el.append(f'<text x="{x + 3:.1f}" y="{PH - MB - 4}" font-size="10" fill="{color}">{html.escape(text)}</text>')

  def shade(self, a, b, color="#ff9900", opacity=0.18):
    a, b = max(a, self.t0), min(b + 0.05, self.t1)
    if b > a:
      self.el.insert(0, f'<rect x="{self.x(a):.1f}" y="{MT}" width="{self.x(b) - self.x(a):.1f}" height="{PH - MT - MB}" fill="{color}" opacity="{opacity}"/>')

  def mark(self, t, v, color, shape, text=None):
    if t is None or not (self.t0 <= t <= self.t1) or not math.isfinite(v):
      return
    x, y = self.x(t), self.y(min(max(v, self.lo), self.hi))
    if shape == "tri_open":
      self.el.append(f'<path d="M{x:.1f},{y - 9:.1f} l-5,-8 l10,0 z" fill="white" stroke="{color}" stroke-width="1.6"/>')
    elif shape == "tri":
      self.el.append(f'<path d="M{x:.1f},{y - 9:.1f} l-5,-8 l10,0 z" fill="{color}"/>')
    else:
      self.el.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="none" stroke="{color}" stroke-width="2"/>')
    if text:
      self.el.append(f'<text x="{x + 6:.1f}" y="{y + 14:.1f}" font-size="10" fill="{color}">{html.escape(text)}</text>')

  def svg(self, legend: list[tuple[str, str, str]]) -> str:
    ax = [f'<rect x="{ML}" y="{MT}" width="{PW - ML - MR}" height="{PH - MT - MB}" fill="none" stroke="#bbb"/>']
    for v in np.linspace(self.lo, self.hi, 5)[1:-1]:
      ax.append(f'<text x="{ML - 4}" y="{self.y(v) + 3:.1f}" font-size="10" text-anchor="end" fill="#555">{v:.1f}</text>')
      ax.append(f'<line x1="{ML}" x2="{PW - MR}" y1="{self.y(v):.1f}" y2="{self.y(v):.1f}" stroke="#eee"/>')
    step = max(1, int(round((self.t1 - self.t0) / 12)))
    for s in range(int(math.ceil(self.t0)), int(self.t1) + 1):
      if s % step == 0:
        ax.append(f'<text x="{self.x(s):.1f}" y="{PH - 6}" font-size="10" text-anchor="middle" fill="#555">{mmss(s)}</text>')
    lg, x = [], ML + 6
    for name, color, dash in legend:
      d = f' stroke-dasharray="{dash}"' if dash else ""
      lg.append(f'<line x1="{x}" x2="{x + 18}" y1="{MT + 8}" y2="{MT + 8}" stroke="{color}" stroke-width="2"{d}/>'
                + f'<text x="{x + 22}" y="{MT + 11}" font-size="10">{html.escape(name)}</text>')
      x += 30 + 6 * len(name)
    return (f'<div class="panel"><div class="ptitle">{html.escape(self.title)}</div>'
            + f'<svg width="{PW}" height="{PH}" data-t0="{self.t0}" data-t1="{self.t1}">{"".join(ax + self.el + lg)}'
            + f'<line class="cur" x1="-10" x2="-10" y1="{MT}" y2="{PH - MB}" stroke="#000" stroke-width="1"/></svg></div>')


def page(W: dict, name: str, base: str, cmp: str) -> tuple[str, dict]:
  order = [k for k in (base, cmp) if k in W["sim_keys"]] + [k for k in W["sim_keys"] if k not in (base, cmp)]
  shown, same = dedupe(W, order)
  col = {k: COLORS.get(k) or SPARE[i % len(SPARE)] for i, k in enumerate(shown)}
  M0 = {k: metrics(W, k) for k in shown}
  stops = [M0[k][q] for k in (base, cmp) if k in M0 for q in ("push_t", "drift_t") if M0[k].get(q) is not None]
  judge_to = min(stops) if stops else np.inf
  M = {k: metrics(W, k, judge_to) for k in shown}
  for k in shown:
    M[k].update({q: M0[k].get(q) for q in ("push_t", "push_s", "drift_t", "lead_lost_t", "min_gap", "t_min_gap")})
  M.update({k: M[v] for k, v in same.items()})
  C = compare(W, base, cmp) if base in W["sim_keys"] and cmp in W["sim_keys"] else {"bind": [], "bind_s": 0.0, "diverge_t": None}
  sw = W["meta"].get("sim_window") or [W["t"][0], W["t"][-1]]
  hold = spans(W["t"], (W["v_ego"] < STOP_V) & (W["resid"] > RESID_HOLD), BIND_MERGE_S)
  t0, t1 = sw[0] - PAD_S, sw[1] + PAD_S
  t = W["t"]
  view = (t >= t0) & (t <= t1)

  def mk(title, ys, force=()):
    return Panel(title, t0, t1, [y[view] for y in ys], force=force)

  panels = []
  p = mk("planner command output_a_target (m/s²)", [W["out"][k] for k in shown] + [W["cmd_log"]], force=(-1.6, 0.2))
  p.hline(0, "#666", None)
  for thr in BRAKE_MARKS:
    p.hline(thr)
  p.line(t, W["cmd_log"], "#aaa", 1.2, "2,2")
  for k in shown:
    p.line(t, W["out"][k], col[k], drift_t=M[k].get("drift_t"))
    for thr, shape in zip(BRAKE_MARKS, ("tri_open", "tri"), strict=True):
      ft = M[k].get("first", {}).get(thr)
      p.mark(ft, thr, col[k], shape)
  panels.append((p, [(label(k), col[k], None) for k in shown] + [("logged accel cmd", "#aaa", "2,2"),
                                                                  ("▽ first ≤-0.5  ▼ first ≤-1.5", "#fff", None)]))

  p = mk("sim aEgo (m/s²)", [W["sa"][k] for k in shown] + [W["a_ego"], W["resid"]])
  p.hline(0, "#666", None)
  p.line(t, W["a_ego"], "#aaa", 1.2, "2,2")
  p.line(t, W["resid"], "#b8860b", 1.2, "1,2")
  for k in shown:
    p.line(t, W["sa"][k], col[k], drift_t=M[k].get("drift_t"))
  panels.append((p, [(label(k), col[k], None) for k in shown] + [("logged aEgo", "#aaa", "2,2"),
                                                                  ("residual added to every sim car", "#b8860b", "1,2")]))

  p = mk("sim vEgo (m/s)", [W["sv"][k] for k in shown] + [W["v_ego"], W["vlead"]], force=(0,))
  p.line(t, W["v_ego"], "#aaa", 1.2, "2,2")
  p.line(t, W["vlead"], "#444", 1.0, "1,3")
  p.dots(t, W["visv"], "#48a")
  for k in shown:
    p.line(t, W["sv"][k], col[k], drift_t=M[k].get("drift_t"))
  panels.append((p, [(label(k), col[k], None) for k in shown] + [("logged vEgo", "#aaa", "2,2"), ("radar vLead", "#444", "1,3"),
                                                                  ("camera v", "#48a", None)]))

  p = mk("gap to lead (m): sim car = replayed dRel + gap_shift", [W["gap"][k] for k in shown] + [W["d"], W["visx"]], force=(0,))
  p.hline(0, "#c00", None)
  p.line(t, W["d"], "#aaa", 1.2, "2,2")
  p.dots(t, W["visx"], "#48a")
  for k in shown:
    p.line(t, W["gap"][k], col[k], drift_t=M[k].get("drift_t"))
    mg, tg = M[k].get("min_gap"), M[k].get("trusted_gap")
    if mg is not None:
      p.mark(M[k]["t_min_gap"], mg, col[k], "circ", f"{label(k)} {mg:.1f}" + ("" if tg == mg else " (untrusted)"))
    if tg is not None and tg != mg:
      p.mark(M[k]["t_trusted_gap"], tg, col[k], "circ", f"{label(k)} {tg:.1f}")
  panels.append((p, [(label(k), col[k], None) for k in shown] + [("logged dRel (car as driven)", "#aaa", "2,2"),
                                                                  (f"camera x (p≥{VIS_PROB})", "#48a", None)]))

  for p, _ in panels:
    p.vline(sw[0], "#555", "6,3", "sim start")
    p.vline(sw[1], "#555", "6,3", "sim end")
    for a, b in C["bind"]:
      p.shade(a, b)
    if C["diverge_t"] is not None:
      p.vline(C["diverge_t"], "#d62728", "2,3", "sim cars diverge")
    for a, b in hold:
      p.shade(a, b, "#666", 0.12)

  smooth, closer = verdicts(M.get(base, {}), M.get(cmp, {})) if base in M and cmp in M else ("-", "-")
  flags = []
  for k in shown:
    m = M[k]
    if m.get("push_t") is not None:
      flags.append(f"{label(k)}: SIM ARTEFACT from {mmss(m['push_t'])} ({m['push_s']:.1f} s): the logged car is stopped and held by its brakes, and"
                   + f" that hold (residual up to +{np.nanmax(W['resid'][np.isfinite(W['sv'][k])]):.2f} m/s²) is added to this sim car, which is still"
                   + " moving, so it is pushed forward against its own command. Gaps after this are not the planner's; trusted min gap"
                   + f" {'-' if m.get('trusted_gap') is None else format(m['trusted_gap'], '.1f')} m")
    if m.get("min_gap") is not None and m["min_gap"] < 0:
      flags.append(f"{label(k)}: gap below 0 ({m['min_gap']:.1f} m at {mmss(m['t_min_gap'])}) — the sim car ran past the logged lead:"
                   + " a missed stop or a sim artefact (the lead does not react to the sim car, and the radar lead can drop at close range)")
    if m.get("lead_lost_t") is not None:
      flags.append(f"{label(k)}: lead lost at {mmss(m['lead_lost_t'])} with the sim car still moving — min gap only covers up to there")
    if m.get("drift_t") is not None:
      flags.append(f"{label(k)}: drifted > {DRIFT_M:g} m from the logged car at {mmss(m['drift_t'])} (dashed after)")
  if "x_none" in W["out"] and "b0.075" in W["out"]:
    sm = np.isfinite(W["sv"].get(base, np.full(len(t), np.nan)))
    dd = np.abs(W["out"]["x_none"] - W["out"]["b0.075"])[sm]
    if dd.size and np.nanmax(dd) > 1e-3:
      flags.append(f"lpx with no switches (x_none) differs from the repo planner (b0.075) on {int((dd > 1e-3).sum())} frames, up to"
                   + f" {np.nanmax(dd):.2f}: part of any x_* vs b0.075 difference here is the lpx copy, not the switch")

  rows = []
  for k in shown + list(same):
    m = M[k]
    if m.get("n", 0) < 3:
      continue
    f5, f15 = m["first"][-0.5], m["first"][-1.5]
    twin = f" (= {label(same[k])})" if k in same else ""
    gap_all = "-" if m["min_gap"] is None else format(m["min_gap"], ".1f")
    gap_ok = "-" if m["trusted_gap"] is None else format(m["trusted_gap"], ".1f")
    rows.append(f'<tr><td><span class="sw" style="background:{col.get(k, col.get(same.get(k), "#999"))}"></span>{html.escape(label(k))}{twin}</td>'
                + f'<td>{m["peak_cmd"]:.2f}</td><td>{gap_ok}</td><td>{gap_all}</td>'
                + f'<td>{m["jrms"]:.2f}</td><td>{m["flips"]}</td><td>{m["t_brake"]:.1f}</td>'
                + f'<td>{"-" if f5 is None else mmss(f5)}</td><td>{"-" if f15 is None else mmss(f15)}</td>'
                + f'<td>{m["min_a"]:.2f}</td><td>{m["v_end"]:.1f}</td></tr>')

  # data for the cursor and the bird's-eye view, sim window +- pad only
  idx = np.where(view)[0]

  def arr(a, nd=2):
    return [None if not math.isfinite(float(x)) else round(float(x), nd) for x in a[idx]]

  js = {"t": arr(t, 3), "d": arr(W["d"]), "visx": arr(W["visx"]), "vlead": arr(W["vlead"]), "v": arr(W["v_ego"]),
        "cmdlog": arr(W["cmd_log"]), "track": [W["track"][i] for i in idx],
        "var": [{"k": k, "name": label(k), "c": col[k], "gs": arr(W["gs"][k]), "sv": arr(W["sv"][k]), "sa": arr(W["sa"][k]),
                 "out": arr(W["out"][k]), "gap": arr(W["gap"][k])} for k in shown],
        "trace": [W["trace"]["rows"][i] for i in idx] if W["trace"] else None, "tracekey": W["trace"]["key"] if W["trace"] else None}

  meta = W["meta"]
  title = f"{name} — {mmss(sw[0])}–{mmss(sw[1])}"
  note_same = "".join(f"<li>{html.escape(label(k))} is identical to {html.escape(label(v))} here and is not drawn</li>" for k, v in same.items())
  bind_txt = (f"{len(C['bind'])} span(s), {C['bind_s']:.1f} s where |{label(base)} − {label(cmp)}| &gt; {BIND_DIFF}"
              + ("" if C["diverge_t"] is None else f"; sim cars diverge at {mmss(C['diverge_t'])}, after which the two see different scenes"
                 + " and a shaded span is no longer the caps alone"))
  scored = ("over the whole sim window" if not np.isfinite(judge_to) else
            f"from sim start to {mmss(judge_to)}, the first standstill-hold push or {DRIFT_M:g} m drift of {html.escape(label(base))}"
            + f" or {html.escape(label(cmp))}, so both are scored over the same span")
  doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>
body{{font:13px system-ui,sans-serif;margin:14px;max-width:1500px}} .warn{{background:#fff4d6;border:1px solid #e0b000;padding:6px 10px;margin:6px 0}}
table{{border-collapse:collapse;margin:6px 0}} td,th{{border:1px solid #ccc;padding:3px 8px;text-align:right}} td:first-child{{text-align:left}}
.sw{{display:inline-block;width:12px;height:12px;margin-right:6px;vertical-align:middle}} .ptitle{{font-weight:600;margin-top:4px}}
#wrap{{display:flex;gap:14px;align-items:flex-start}} #side{{position:sticky;top:8px}} #read td{{font-variant-numeric:tabular-nums}}
</style></head><body>
<h2>{html.escape(title)}</h2>
<div class="warn"><b>Simulation / replay, not driven.</b> Each variant drives its own simulated car inside the sim window (first-order
delay model); the lead, radar and camera are the logged ones and do not react to the sim car. Route {html.escape(str(meta.get("route_dir")))},
build {html.escape(str(meta.get("git_commit")))}, {html.escape(str(meta.get("fingerprint")))}. Verdicts: nocaps smoother? <b>{html.escape(smooth)}</b>;
nocaps closer / later brake? <b>{html.escape(closer)}</b>.</div>
{"".join(f'<div class="warn">{html.escape(f)}</div>' for f in flags)}
<ul>{note_same}<li>orange: {bind_txt}</li>
<li>grey: logged car stopped and held by its brakes (residual &gt; {RESID_HOLD}); a sim car still moving there is pushed by that hold.
Trusted min gap stops at the first such push or at {DRIFT_M:g} m of drift, whichever comes first.</li></ul>
<p>Scores {scored};
min gap (all) is the whole window and is not trusted past that point.</p>
<table><tr><th>variant</th><th>peak cmd</th><th>min gap m (trusted)</th><th>min gap m (all)</th><th>jrms m/s³</th>
<th>sign flips (±0.08)</th><th>s below {BRAKE_TIME}</th>
<th>first ≤-0.5</th><th>first ≤-1.5</th><th>min sim aEgo</th><th>v end</th></tr>{"".join(rows)}</table>
<div id="wrap"><div id="plots">{"".join(p.svg(lg) for p, lg in panels)}</div>
<div id="side"><canvas id="bev" width="300" height="640" style="border:1px solid #ccc"></canvas><br>
<input id="sl" type="range" min="0" max="{len(idx) - 1}" value="0" style="width:300px"><br>
<button id="play">play</button> <select id="spd"><option>0.5</option><option selected>1</option><option>2</option><option>4</option></select>x
<table id="read"></table><pre id="tr" style="max-width:300px;white-space:pre-wrap;font-size:11px"></pre></div></div>
<script>
const D={json.dumps(js, separators=(",", ":"))};
const sl=document.getElementById('sl'),cv=document.getElementById('bev'),cx=cv.getContext('2d');
const svgs=[...document.querySelectorAll('#plots svg')];
function f(x,n=2){{return x==null?'-':x.toFixed(n)}}
function mmss(t){{return Math.floor(t/60)+':'+(t%60).toFixed(1).padStart(4,'0')}}
function draw(i){{
  const t=D.t[i];
  for(const s of svgs){{const t0=+s.dataset.t0,t1=+s.dataset.t1,x={ML}+(t-t0)/(t1-t0)*({PW - ML - MR});
    const c=s.querySelector('.cur');c.setAttribute('x1',x);c.setAttribute('x2',x);}}
  const W=cv.width,H=cv.height;let far=20;
  for(let j=0;j<D.t.length;j++){{if(D.d[j]!=null)far=Math.max(far,D.d[j]);if(D.visx[j]!=null)far=Math.max(far,D.visx[j]);}}
  let back=10;for(const v of D.var)for(const g of v.gs)if(g!=null)back=Math.max(back,g);
  const s=(H-30)/(far+back+10),Y=m=>H-15-(m+back+5)*s;
  cx.fillStyle='#f4f4f4';cx.fillRect(0,0,W,H);cx.fillStyle='#ddd';cx.fillRect(W/2-45,0,90,H);
  cx.strokeStyle='#fff';cx.setLineDash([12,12]);cx.beginPath();
  cx.moveTo(W/2-45,0);cx.lineTo(W/2-45,H);cx.moveTo(W/2+45,0);cx.lineTo(W/2+45,H);cx.stroke();cx.setLineDash([]);
  cx.fillStyle='#888';cx.font='10px sans-serif';for(let m=-10*Math.floor(back/10);m<=far+5;m+=10){{cx.fillText(m+' m',4,Y(m)+3);}}
  function car(yc,col,fill,lbl,x){{cx.strokeStyle=col;cx.lineWidth=2;cx.fillStyle=fill;const h=Math.max(4.5*s,6);
    cx.fillRect(x-9,yc-h,18,h);cx.strokeRect(x-9,yc-h,18,h);if(lbl){{cx.fillStyle=col;cx.fillText(lbl,x+13,yc-h/2);}}}}
  if(D.visx[i]!=null)car(Y(D.visx[i]),'#48a','rgba(72,136,170,0.15)','cam '+f(D.visx[i],1),W/2);
  if(D.d[i]!=null)car(Y(D.d[i]),'#333','rgba(0,0,0,0.25)',
    'radar '+f(D.d[i],1)+(D.track[i]!=null?' #'+D.track[i]:''),W/2);
  car(Y(0)+4.5*s,'#aaa','rgba(0,0,0,0.05)','logged',W/2);
  D.var.forEach((v,j)=>{{const g=v.gs[i];if(g==null)return;const x=W/2-30+j*20;car(Y(-g)+4.5*s,v.c,v.c+'33','',x);}});
  let r='<tr><th>'+mmss(t)+'</th><th>cmd</th><th>a</th><th>v</th><th>gap</th></tr>';
  D.var.forEach(v=>{{
    r+='<tr><td style="color:'+v.c+'">'+v.name+'</td>'
      +'<td>'+f(v.out[i])+'</td><td>'+f(v.sa[i])+'</td><td>'+f(v.sv[i],1)+'</td><td>'+f(v.gap[i],1)+'</td></tr>'}});
  r+='<tr><td>logged</td><td>'+f(D.cmdlog[i])+'</td><td></td><td>'+f(D.v[i],1)+'</td><td>'+f(D.d[i],1)+'</td></tr>';
  r+='<tr><td>lead</td><td></td><td></td><td>'+f(D.vlead[i],1)+'</td><td>cam '+f(D.visx[i],1)+'</td></tr>';
  document.getElementById('read').innerHTML=r;
  if(D.trace){{const e=D.trace[i]||[];
    document.getElementById('tr').textContent=D.tracekey+' lpx.py lines that moved the target:\\n'
      +e.map(q=>'L'+q[0]+': '+(q[1]==null?'start':q[1])+' -> '+q[2]).join('\\n');}}
}}
sl.oninput=()=>draw(+sl.value);
for(const s of svgs)s.addEventListener('click',ev=>{{const b=s.getBoundingClientRect(),t0=+s.dataset.t0,t1=+s.dataset.t1;
  const t=t0+(ev.clientX-b.left-{ML})/({PW - ML - MR})*(t1-t0);let k=0;while(k<D.t.length-1&&D.t[k]<t)k++;sl.value=k;draw(k);}});
let timer=null;document.getElementById('play').onclick=()=>{{if(timer){{clearInterval(timer);timer=null;return;}}
  timer=setInterval(()=>{{const n=+document.getElementById('spd').value;let k=+sl.value;
    const t=D.t[k]+0.05*n;while(k<D.t.length-1&&D.t[k]<t)k++;if(k>=D.t.length-1){{clearInterval(timer);timer=null;}}sl.value=k;draw(k);}},50);}};
let k0=0;while(k0<D.t.length-1&&D.t[k0]<{sw[0]})k0++;sl.value=k0;draw(k0);
</script></body></html>"""
  summ = {"name": name, "file": str(W["path"]), "sim_window": sw, "base": base, "cmp": cmp, "smoother": smooth, "closer_later": closer,
          "bind": C["bind"], "bind_s": round(C["bind_s"], 2), "diverge_t": C["diverge_t"], "flags": flags, "same": same,
          "per": {k: {q: (fnum(v) if not isinstance(v, dict) else {str(a): fnum(b) for a, b in v.items()}) for q, v in m.items()}
                  for k, m in M.items()}}
  return doc, summ


def index(S: list[dict], base: str, cmp: str) -> str:
  keys = []
  for s in S:
    for k in s["per"]:
      if k not in keys and k not in s["same"]:
        keys.append(k)
  head = "".join(f"<th>{html.escape(label(k))}<br>peak / gap / jrms</th>" for k in keys)
  rows = []
  for s in S:
    cells = []
    for k in keys:
      m = s["per"].get(k)
      if not m or m.get("n", 0) < 3:
        cells.append("<td>-</td>")
        continue
      g = m.get("trusted_gap")
      bad = ' style="background:#fdd"' if (g is not None and g < 0) else ""
      art = " *" if m.get("push_t") is not None else ""
      cells.append(f'<td{bad}>{m["peak_cmd"]:.2f} / {"-" if g is None else format(g, ".1f")}{art} / {m["jrms"]:.2f}</td>')
    fl = "<br>".join(html.escape(f.split(" — ")[0].split(":")[0] + ": " + f.split(":", 1)[1].split("(")[0].strip()) for f in s["flags"])
    rows.append(f'<tr><td><a href="{html.escape(s["name"])}.html">{html.escape(s["name"])}</a></td>'
                + f'<td>{mmss(s["sim_window"][0])}–{mmss(s["sim_window"][1])}</td>{"".join(cells)}'
                + f'<td>{html.escape(s["smoother"])}</td><td>{html.escape(s["closer_later"])}</td><td>{s["bind_s"]:.1f}</td>'
                + f'<td>{"-" if s["diverge_t"] is None else mmss(s["diverge_t"])}</td><td style="text-align:left;font-size:11px">{fl}</td></tr>')
  return f"""<!doctype html><html><head><meta charset="utf-8"><title>planner variants — replay</title><style>
body{{font:13px system-ui,sans-serif;margin:14px}} table{{border-collapse:collapse}} td,th{{border:1px solid #ccc;padding:3px 8px;text-align:right}}
td:first-child{{text-align:left}} .warn{{background:#fff4d6;border:1px solid #e0b000;padding:6px 10px;margin:6px 0}}</style></head><body>
<h2>Planner variants: {html.escape(label(base))} vs {html.escape(label(cmp))} — simulation / replay, not driven</h2>
<div class="warn">Closed-loop replay: each variant drives its own simulated car against the logged lead, which does not react to it.
peak = most negative planner command, gap = trusted min sim gap to the lead (m, red when below 0; up to the first standstill-hold push or
{DRIFT_M:g} m of drift; * = this car was pushed by the logged car's brake hold, a sim artefact, later in the window),
jrms = RMS d(cmd)/dt (m/s³), all inside the sim window.
"smoother?": jrms below/above {label(base)} by more than {SMOOTH_FRAC:.0%}. "closer / later brake?": trusted min gap
{CLOSER_M:g} m smaller, or the first ≤-0.5 / ≤-1.5 command more than {LATER_S:g} s later or never.
binding s: time where |{label(base)} − {label(cmp)}| &gt; {BIND_DIFF}.</div>
<table><tr><th>window</th><th>sim</th>{head}<th>{html.escape(label(cmp))} smoother?</th><th>{html.escape(label(cmp))} closer / later brake?</th>
<th>binding s</th><th>sim cars diverge</th><th>flags</th></tr>{"".join(rows)}</table></body></html>"""


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("frames", nargs="+", type=Path, help="alpha_closed_loop_replay.py --frames-json outputs")
  ap.add_argument("--out", type=Path, required=True, help="directory for <window>.html, index.html, summary.json")
  ap.add_argument("--base", default="b0.075", help="reference variant (default the repo planner, b0.075)")
  ap.add_argument("--cmp", default="x_nocap", help="variant judged against --base (default x_nocap)")
  ap.add_argument("--label", action="append", default=[], metavar="KEY=NAME", help="display name for a variant key")
  a = ap.parse_args()
  for kv in a.label:
    k, v = kv.split("=", 1)
    LABELS[k] = v
  a.out.mkdir(parents=True, exist_ok=True)
  S = []
  for fp in sorted(a.frames):
    if fp.name.endswith(".trace.json") or not fp.stat().st_size:
      continue
    W = load(fp)
    if not W["sim_keys"]:
      print(f"{fp}: no sim frames, skipped")
      continue
    name = fp.stem.split("_", 1)[1] if "_" in fp.stem else fp.stem
    doc, s = page(W, name, a.base, a.cmp)
    (a.out / f"{name}.html").write_text(doc)
    S.append(s)
    print(f"{name}: smoother? {s['smoother']}; closer/later? {s['closer_later']}; binding {s['bind_s']:.1f} s"
          + "".join(f"\n  ! {f}" for f in s["flags"]))
  (a.out / "index.html").write_text(index(S, a.base, a.cmp))
  (a.out / "summary.json").write_text(json.dumps(S, indent=1, default=str))
  print(f"wrote {len(S)} pages + index.html to {a.out}")


if __name__ == "__main__":
  main()
