#!/usr/bin/env python3
"""Replay-only prototype for D-107: when the nav says "off ramp" and the lane guidance already puts the active lane on the
exit side (slightRight / slightLeft on the edge lane), would an automatic keep-to-exit trigger have fired, and when?

READ-ONLY. It reads rlog segments and prints the first tick each gate passes. It does not touch desire_helper.py and
changes no control behaviour. Params (NavLanePositioningAllowed, NavDesiresAllowed) are not in the rlog, so the shipped
Path B gate cannot be replayed here; this only evaluates the proposed trigger.

Usage: python3 tools/replay/nav_exit_autotake_proto.py RLOG.zst [RLOG.zst ...]   (segments in order)
"""
import sys
import zstandard
from cereal import log as L

# Same window as DesireHelper._nav_keep_is_imminent: np.interp(v_ego, [0, 15, 30], [25, 90, 160]) metres.
IMMINENT_M = ((0.0, 25.0), (15.0, 90.0), (30.0, 160.0))
MIN_SPEED = 8.0  # m/s, proposal (below this the keep is not worth a lateral action)


def imminent(v):
  pts = IMMINENT_M
  if v <= pts[0][0]:
    return pts[0][1]
  for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
    if v <= x1:
      return y0 + (y1 - y0) * (v - x0) / (x1 - x0)
  return pts[-1][1]


def main(paths):
  evs = []
  for p in paths:
    d = zstandard.ZstdDecompressor().stream_reader(open(p, 'rb')).read()
    evs += [(e.logMonoTime, e.which(), e) for e in L.Event.read_multiple_bytes(d)]
  evs.sort(key=lambda x: x[0])
  t0 = min(t for t, w, _ in evs if w == 'carState')
  cs = None
  first = {}
  for t, w, e in evs:
    if w == 'carState':
      cs = e.carState
      continue
    if w != 'navInstruction' or cs is None or t < t0:
      continue
    n = e.navInstruction
    rt = (t - t0) / 1e9
    if n.maneuverType != 'off ramp' or n.maneuverDistance <= 0:
      continue
    side = n.maneuverModifier
    act = [l for l in n.lanes if l.active]
    ad = str(act[0].activeDirection) if act else 'none'
    edge_lane = ad in ('slightRight', 'slightLeft') and ad.lower().endswith(side.replace('slight', '').lower())
    v = cs.vEgo
    gates = {
      'edge_lane': edge_lane,
      'window': n.maneuverDistance <= imminent(v),
      'speed': v >= MIN_SPEED,
      'no_blinker': not (cs.leftBlinker or cs.rightBlinker),
      'bsm_clear': not (cs.rightBlindspot if side.endswith('ight') else cs.leftBlindspot),
    }
    ok = all(gates.values())
    key = (int(n.maneuverDistance // 1), ok)
    if ok and 'fire' not in first:
      first['fire'] = rt
      print(f'FIRE t={rt:7.1f}s dist={n.maneuverDistance:5.0f} m v={v:5.1f} m/s lane={ad} side={side}')
    elif not ok and int(rt) % 5 == 0 and key not in first:
      first[key] = 1
      print(f'  t={rt:7.1f}s dist={n.maneuverDistance:5.0f} m v={v:5.1f} blocked by {[k for k, g in gates.items() if not g]}')
  if 'fire' not in first:
    print('never fired')


if __name__ == '__main__':
  main(sys.argv[1:])
