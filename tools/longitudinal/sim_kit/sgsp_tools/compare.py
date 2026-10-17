"""compare.py: smoothness + replay fidelity for r_{fam}_{ev}.pkl (replay only)."""
import glob, os, pickle, sys
import numpy as np
O = os.path.expanduser("~/longsim_frames/sgsp")
FAMS = ("car", "tree", "sgsp")
ma = lambda y, n: np.convolve(np.pad(y, (n // 2, n - 1 - n // 2), mode="edge"), np.ones(n) / n, "valid")
bp = lambda y: ma(y, 7) - ma(y, 100)  # ~0.2-3 Hz band at 20 Hz

def rs(t, y):  # resample to 20 Hz
  tt = np.arange(t[0], t[-1], 0.05); return tt, np.interp(tt, t, y)

def ev_metrics(rows):
  r = [x for x in rows if x["out"].get("BASE") and x["out"]["BASE"][6] is not None]
  t = np.array([x["t"] for x in r]); ol = [x for x in rows if x["out"].get("OLBASE")]
  v, a, u, sh = (np.array([x["out"]["BASE"][6][i] for x in r]) for i in range(4))
  vl = np.array([x["v"] for x in r]); al = np.array([x["a"] for x in r]); cl = np.array([x["cmd"] for x in r])
  tt, A = rs(t, a); _, U = rs(t, u); _, AL = rs(t, al); _, VL = rs(t, vl); _, V = rs(t, v)
  jA = np.diff(A) / 0.05; jU = np.diff(U) / 0.05
  mv = V[1:] > 0.5  # leave out the plant's hard stop at v=0 (a snaps to 0)
  jAm = jA[mv] if mv.any() else jA[:1] * 0
  g = [x["L"][2] + x["out"]["BASE"][6][3] for x in r if x["L"][0]]
  ttc = [(x["L"][2] + x["out"]["BASE"][6][3]) / (x["out"]["BASE"][6][0] - x["L"][4]) for x in r if x["L"][0] and x["out"]["BASE"][6][0] - x["L"][4] > 0.1]
  to = np.array([x["t"] for x in ol]); uo = np.array([x["out"]["OLBASE"][0] for x in ol]); co = np.array([x["cmd"] for x in ol])
  _, UO = rs(to, uo); _, CO = rs(to, co)
  err = np.abs(V - VL); win = int(5 / 0.05)
  wv = np.convolve(err, np.ones(win) / win, "valid") if len(err) > win else err
  return dict(jerkAm=np.sqrt(np.mean(jAm**2)), jA95m=np.percentile(np.abs(jAm), 95), jerkA=np.sqrt(np.mean(jA**2)), jerkU=np.sqrt(np.mean(jU**2)), jA95=np.percentile(np.abs(jA), 95),
              swing=np.std(bp(A)), swing_log=np.std(bp(AL)), corr_a=np.corrcoef(bp(A), bp(AL))[0, 1],
              corr_ol=np.corrcoef(bp(UO), bp(CO))[0, 1], swing_ol=np.std(bp(UO)), swing_cmd=np.std(bp(CO)),
              vrmse=np.sqrt(np.mean((V - VL)**2)), worst=(float(wv.max()), float(tt[int(wv.argmax())] - tt[0])),
              umin=U.min(), amin=A.min(), gap=min(g) if g else np.nan, ttc=min(ttc) if ttc else np.nan,
              gap_end=g[-1] if g else np.nan, vend=v[-1])

res = {}
for f in FAMS:
  for p in sorted(glob.glob(f"{O}/r_{f}_*.pkl")):
    for k, d in pickle.load(open(p, "rb")).items():
      res[(f, k)] = ev_metrics(d["rows"])
evs = sorted({k for _, k in res})
cols = ("jerkAm", "jA95m", "jerkA", "jerkU", "jA95", "swing", "umin", "amin", "gap", "ttc", "corr_a", "corr_ol", "vrmse")
for e in evs:
  print(e)
  for f in FAMS:
    m = res.get((f, e))
    if m: print(f"  {f:5}" + " ".join(f"{c}={m[c]:.2f}" for c in cols) + f" worst5s={m['worst'][0]:.2f}@{m['worst'][1]:.0f}s swing_log={m['swing_log']:.2f}")
print("\nSUMMARY (median over events)")
for f in FAMS:
  ms = [res[(f, e)] for e in evs if (f, e) in res]
  if ms:
    print(f"  {f:5} n={len(ms)} " + " ".join(f"{c}={np.nanmedian([m[c] for m in ms]):.2f}" for c in cols)
          + f" vrmse_p90={np.percentile([m['vrmse'] for m in ms], 90):.2f}")
