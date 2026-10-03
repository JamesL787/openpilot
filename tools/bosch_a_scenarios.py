#!/usr/bin/env python3
"""Generate Bosch-A radar scenarios by running the REAL parser, and emit JSON for the viewer.

This is not a simulator and it does not model anything. It synthesizes Bosch-A CAN frames,
feeds them through `CarInterface.RadarInterface` exactly as the car would, and records what
the parser actually decided on each sweep. Every number in the output came out of
opendbc/car/honda/radar_interface.py, so the viewer shows parser behaviour rather than an
illustration of it.

The scenarios are chosen to exercise the gates that DECISIONS.md says were expensive to get
wrong, so a change that quietly breaks one of them shows up as a visible difference:

  closing_lead     healthy U11, every gate passes -- the baseline
  saturation_rail  stopped car approached above 12.0 m/s (D-041). U11 rails on every sweep.
                   The point MUST still be published; discarding it deleted stopped cars on
                   route 000001f9 and the driver had to intervene.
  high_u10_decel   u10 above the validated 511 threshold during a real hard decel (D-042).
                   Lowering that threshold on offline statistics caused a measured regression.
  vrel_contradiction  U11 claims closing while the range opens (D-043). The one-sided
                   multi-sweep check rejects this; it must NOT reject the mirror case.
  no_targets       firmware no-target sentinels -- what every clean replay so far has
                   actually contained (STATUS.md). The honest baseline.

Frame builders are imported from the Bosch-A test module rather than copied. A second copy
of the inverse-byte formulas is exactly the divergence AGENTS.md §6 warns about, and the
drift would be silent.

Usage:
    python tools/bosch_a_scenarios.py                    # all scenarios to stdout
    python tools/bosch_a_scenarios.py -o data.json       # write a file
    python tools/bosch_a_scenarios.py --scenario closing_lead
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Importing the test module sets the BoschARadar param at import time (the parser is gated on
# it) and builds CP once. That side effect is intentional and required for the parser to run.
from opendbc.car.honda.tests.test_bosch_a_radar import (
  make_radar_interface,
  sweep,
)
from opendbc.car.honda.radar_interface import (
  BOSCH_A_AZIMUTH_CENTER,
  BOSCH_A_AZIMUTH_SCALE_RAD,
  BOSCH_A_DIRECT_VREL_CENTER_RAW,
  BOSCH_A_DIRECT_VREL_INVALID,
  BOSCH_A_DIRECT_VREL_MAX_RAW,
  BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW,
  BOSCH_A_DIRECT_VREL_MIN_RAW,
  BOSCH_A_DIRECT_VREL_SCALE_MPS,
  BOSCH_A_FREQ_HZ,
  BOSCH_A_RANGE_OFFSET_M,
  BOSCH_A_RANGE_SCALE_M,
  BOSCH_A_STATUS_INVALID,
  BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS,
)

PLACEHOLDER = "__SCENARIO_DATA__"

DT = 1.0 / BOSCH_A_FREQ_HZ
SLOT = 0
TRACK_ID = 1


def range_to_raw(range_m: float) -> int:
  """Invert the firmware-exact range mapping (D-040): range_m = raw/16 + offset."""
  return max(0, min(0xFFE, int(round((range_m - BOSCH_A_RANGE_OFFSET_M) / BOSCH_A_RANGE_SCALE_M))))


def raw_to_range(raw: int) -> float:
  return raw * BOSCH_A_RANGE_SCALE_M + BOSCH_A_RANGE_OFFSET_M


def azimuth_to_raw(rad: float) -> int:
  return max(0, min(0x7FE, int(round(rad / BOSCH_A_AZIMUTH_SCALE_RAD)) + BOSCH_A_AZIMUTH_CENTER))


def vrel_to_raw(vrel_mps: float) -> int:
  """Encode a relative velocity, clamping to the saturation rails rather than wrapping.

  Encodes at 1/72 (BOSCH_A_DIRECT_VREL_SCALE_MPS), the only U11 decode (D-074)."""
  raw = int(round(vrel_mps / BOSCH_A_DIRECT_VREL_SCALE_MPS)) + BOSCH_A_DIRECT_VREL_CENTER_RAW
  return max(BOSCH_A_DIRECT_VREL_MIN_RAW, min(BOSCH_A_DIRECT_VREL_MAX_RAW, raw))


def _run(frames_per_sweep, n_sweeps, describe):
  """Drive the real RadarInterface and capture what it published on each sweep."""
  ri = make_radar_interface()
  out = []
  for i in range(n_sweeps):
    t_nanos = int(i * DT * 1e9)
    spec = describe(i)
    can = frames_per_sweep(i, t_nanos, spec)
    rr = ri.update(can)
    points = []
    if rr is not None:
      for pt in rr.points:
        points.append({
          "trackId": pt.trackId,
          "dRel": round(pt.dRel, 3),
          "yRel": round(pt.yRel, 3),
          "vRel": round(pt.vRel, 3),
          "measured": bool(pt.measured),
        })
    out.append({
      "sweep": i,
      "t": round(i * DT, 4),
      "published": points,
      **spec,
    })
  return out


def scenario_closing_lead(n=60):
  """A lead at 40 m closing at -8 m/s. Healthy U11, low u10: every gate should pass."""
  d0, vrel = 40.0, -8.0

  def describe(i):
    d = d0 + vrel * i * DT
    return {"true_dRel": round(d, 3), "true_vRel": vrel, "u10": 40,
            "u11_raw": vrel_to_raw(vrel), "railed": False, "note": ""}

  def frames(i, t_nanos, spec):
    return sweep(SLOT, i % 16, 0x7, range_to_raw(spec["true_dRel"]), azimuth_to_raw(0.0),
                 life=1 + 2 * i, t_nanos=t_nanos, with_aux=True, track_id=TRACK_ID,
                 direct_vrel_raw=spec["u11_raw"], direct_vrel_uncertainty_raw=spec["u10"])

  return _run(frames, n, describe)


def scenario_saturation_rail(n=60):
  """D-041. Stopped car, ego at ~19.4 m/s. |vRel| far past the 12.0 m/s rail on every sweep.

  The published vRel understates closing -- that is expected and acceptable. What must NOT
  happen is the point disappearing: on route 000001f9 discarding the rail coasted until the
  point was deleted, radard fell back to a weaker vision lead, and the planner commanded 0.00
  into stopped traffic.
  """
  d0, vrel = 76.0, -19.4

  def describe(i):
    d = max(2.0, d0 + vrel * i * DT)
    raw = vrel_to_raw(vrel)
    return {"true_dRel": round(d, 3), "true_vRel": vrel, "u10": 86, "u11_raw": raw,
            "railed": raw in (BOSCH_A_DIRECT_VREL_MIN_RAW, BOSCH_A_DIRECT_VREL_MAX_RAW),
            "note": "u11 on the low rail; |vRel| >= 12.0 m/s, exact value unrecoverable"}

  def frames(i, t_nanos, spec):
    return sweep(SLOT, i % 16, 0x7, range_to_raw(spec["true_dRel"]), azimuth_to_raw(0.0),
                 life=1 + 2 * i, t_nanos=t_nanos, with_aux=True, track_id=TRACK_ID,
                 direct_vrel_raw=spec["u11_raw"], direct_vrel_uncertainty_raw=spec["u10"])

  return _run(frames, n, describe)


def scenario_high_u10_decel(n=60):
  """D-042. A genuine ~8 m/s^2 lead decel drives u10 above the validated 511 threshold.

  u10 is confounded with dynamics, so this is what a REAL manoeuvre looks like, not a fault.
  The parser must not let the resulting coast outlive BOSCH_A_STALE_S and delete the lead.
  """
  d, v = 45.0, -2.0

  def describe(i):
    nonlocal d, v
    # Hard decel between sweeps 15 and 40; u10 climbs with |a_rel| exactly as measured.
    a = -8.0 if 15 <= i < 40 else 0.0
    v += a * DT
    d += v * DT
    u10 = 620 if 15 <= i < 40 else 60
    return {"true_dRel": round(max(2.0, d), 3), "true_vRel": round(v, 3), "u10": u10,
            "u11_raw": vrel_to_raw(v), "railed": False,
            "note": "u10 above threshold during real decel" if u10 > BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW else ""}

  def frames(i, t_nanos, spec):
    return sweep(SLOT, i % 16, 0x7, range_to_raw(spec["true_dRel"]), azimuth_to_raw(0.0),
                 life=1 + 2 * i, t_nanos=t_nanos, with_aux=True, track_id=TRACK_ID,
                 direct_vrel_raw=spec["u11_raw"], direct_vrel_uncertainty_raw=spec["u10"])

  return _run(frames, n, describe)


def scenario_vrel_contradiction(n=60):
  """D-043. U11 reports -10.58 m/s closing while the range actually OPENS at +0.46 m/s.

  Modelled on route 000001eb at 6:59, an 11 m/s contradiction across a track-identity change.
  The one-sided check must reject this direction and only this direction.
  """
  d0, true_v, claimed_v = 30.0, 0.46, -10.58

  def describe(i):
    d = d0 + true_v * i * DT
    lying = i >= 20
    return {"true_dRel": round(d, 3), "true_vRel": true_v, "u10": 50,
            "u11_raw": vrel_to_raw(claimed_v if lying else true_v), "railed": False,
            "claimed_vRel": claimed_v if lying else true_v,
            "note": (f"U11 claims {claimed_v} while range opens at +{true_v}; "
                     + f"disagreement > {BOSCH_A_VREL_RATE_CHECK_MAX_DISAGREEMENT_MPS} m/s")
                    if lying else ""}

  def frames(i, t_nanos, spec):
    return sweep(SLOT, i % 16, 0x7, range_to_raw(spec["true_dRel"]), azimuth_to_raw(0.0),
                 life=1 + 2 * i, t_nanos=t_nanos, with_aux=True, track_id=TRACK_ID,
                 direct_vrel_raw=spec["u11_raw"], direct_vrel_uncertainty_raw=spec["u10"])

  return _run(frames, n, describe)


def scenario_no_targets(n=40):
  """Firmware no-target sentinels. This is what every clean Bosch-A replay so far contained.

  It is here as the honest baseline: a scenario that renders empty is the correct rendering
  of the data this project actually has, and the reason 'parser replay completed cleanly'
  has never meant 'the radar tracked a car'.
  """
  def describe(i):
    return {"true_dRel": None, "true_vRel": None, "u10": None, "u11_raw": None,
            "railed": False, "note": "status = no-target sentinel"}

  def frames(i, t_nanos, spec):
    return sweep(SLOT, i % 16, BOSCH_A_STATUS_INVALID, 0xFFF, 0x7FF, life=0xFFF,
                 t_nanos=t_nanos, with_aux=True, track_id=0xFF,
                 direct_vrel_raw=BOSCH_A_DIRECT_VREL_INVALID, direct_vrel_uncertainty_raw=0x3FF)

  return _run(frames, n, describe)


SCENARIOS = {
  "closing_lead": (scenario_closing_lead, "Healthy lead closing at -8 m/s; every gate passes."),
  "saturation_rail": (scenario_saturation_rail, "D-041 - stopped car past the 12.0 m/s rail. The point must survive."),
  "high_u10_decel": (scenario_high_u10_decel, "D-042 - real ~8 m/s2 decel pushes u10 past 511."),
  "vrel_contradiction": (scenario_vrel_contradiction, "D-043 - U11 claims closing while the range opens."),
  "no_targets": (scenario_no_targets, "No-target sentinels - what every clean replay has actually held."),
}


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--scenario", choices=sorted(SCENARIOS), help="only this one (default: all)")
  ap.add_argument("-o", "--out", help="write JSON here instead of stdout")
  ap.add_argument("--indent", type=int, default=None)
  ap.add_argument("--html", metavar="OUT",
                  help="render tools/bosch_a_viewer.html with this data embedded, to OUT")
  args = ap.parse_args()

  names = [args.scenario] if args.scenario else sorted(SCENARIOS)
  result = {
    "generator": "tools/bosch_a_scenarios.py",
    "source": "real opendbc RadarInterface, synthetic Bosch-A CAN frames",
    "sweep_hz": BOSCH_A_FREQ_HZ,
    "u10_threshold": BOSCH_A_DIRECT_VREL_MAX_UNCERTAINTY_RAW,
    "rail_mps": round(BOSCH_A_DIRECT_VREL_MAX_RAW / 2 * BOSCH_A_DIRECT_VREL_SCALE_MPS, 3),
    "scenarios": {},
  }
  for name in names:
    fn, blurb = SCENARIOS[name]
    sweeps = fn()
    published = sum(1 for s in sweeps if s["published"])
    result["scenarios"][name] = {
      "description": blurb,
      "n_sweeps": len(sweeps),
      "n_sweeps_with_point": published,
      "sweeps": sweeps,
    }
    print(f"{name}: {len(sweeps)} sweeps, {published} published a point", file=sys.stderr)

  text = json.dumps(result, indent=args.indent)

  if args.html:
    # The viewer is committed as a template with a single placeholder, so the generated data is
    # never checked in and can never drift from the parser that produced it (D-010, AGENTS §3).
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bosch_a_viewer.html")
    with open(template_path) as f:
      template = f.read()
    if PLACEHOLDER not in template:
      print(f"error: {template_path} has no {PLACEHOLDER} placeholder", file=sys.stderr)
      return 2
    # json.dumps cannot emit "</script"; guard anyway so data can never close the script tag.
    safe = text.replace("</", "<\\/")
    with open(args.html, "w") as f:
      f.write(template.replace(PLACEHOLDER, safe))
    print(f"wrote {args.html} ({os.path.getsize(args.html)/1024:.1f} KB)", file=sys.stderr)

  if args.out:
    with open(args.out, "w") as f:
      f.write(text)
    print(f"wrote {args.out} ({len(text)/1024:.1f} KB)", file=sys.stderr)
  elif not args.html:
    print(text)
  return 0


if __name__ == "__main__":
  sys.exit(main())
