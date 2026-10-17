import pickle, sys, os, numpy as np
O = os.path.expanduser("~/longsim_frames/sgsp/" + sys.argv[1]); pre = sys.argv[2]; cand = sys.argv[3]
for e in sys.argv[4].split(","):
  D = {f: pickle.load(open(f"{O}/{pre}_{f}_{e}.pkl", "rb"))[e]["rows"] for f in ("car", "tree", "sgsp")}
  def ser(f):
    r = [x for x in D[f] if x["out"].get(cand)]
    return np.array([x["t"] for x in r]), np.array([x["out"][cand][0] for x in r]), [x["out"][cand][5] for x in r], r
  t, u, src, r = ser("tree"); t0 = t[0]
  ju = np.abs(np.diff(u)) / np.maximum(np.diff(t), 1e-3)
  S = {f: ser(f) for f in ("car", "sgsp")}
  print(f"== {e}  tree {cand} jerkU rms {np.sqrt(np.mean(ju**2)):.2f}; car {np.sqrt(np.mean((np.diff(S['car'][1])/0.05)**2)):.2f}; sgsp {np.sqrt(np.mean((np.diff(S['sgsp'][1])/0.05)**2)):.2f}")
  # 1-s windows by summed jerk^2
  sec = ((t[1:] - t0)).astype(int); E = np.bincount(sec, ju**2)
  for s in np.argsort(E)[::-1][:5]:
    m = (t - t0 >= s - 0.5) & (t - t0 < s + 1.5)
    idx = np.where(m)[0][::4]
    print(f" t={s}s share {100*E[s]/E.sum():.0f}%")
    for i in idx:
      x = r[i]; L = x["L"]; ts = t[i]
      su = {f: float(np.interp(ts, S[f][0], S[f][1])) for f in S}
      print(f"   {ts-t0:6.2f} v={x['v']:5.2f} lead={'%5.1f/%5.2f'%(L[2],L[4]) if L[0] else '   --     '} tree u={u[i]:+.2f} {src[i]:22s} car={su['car']:+.2f} sgsp={su['sgsp']:+.2f} logcmd={x['cmd']:+.2f}")
