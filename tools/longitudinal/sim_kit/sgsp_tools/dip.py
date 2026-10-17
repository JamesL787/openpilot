import os
import pickle, sys
for e in sys.argv[1:]:
  L = pickle.load(open(os.path.expanduser(f"~/longsim_frames/sgsp/tr_{e}.pkl.trace"), "rb"))
  R = [x for x in pickle.load(open(os.path.expanduser(f"~/longsim_frames/sgsp/tr_{e}.pkl"), "rb"))[e]["rows"] if x["out"].get("OLBASE")]
  off = len(L) - len(R); print("==", e, "frames", len(L), "rows", len(R))
  fin = [x[1] for x in L]
  for i in range(1, len(L) - 1):
    d = fin[i] - fin[i - 1]
    if abs(d) > 0.35 and R[i - off]["v"] < 8 if i - off >= 0 else False:
      x = R[i - off]; Lr = x["L"]
      print(f"\n i={i} t={x['t']-R[0]['t']:.2f} v={x['v']:.2f} lead d={Lr[2]:.1f} vL={Lr[4]:.2f} aL={Lr[5]:.2f}  {fin[i-1]:+.2f} -> {fin[i]:+.2f} -> {fin[i+1]:+.2f}")
      for tag, j in (("prev", i - 1), ("this", i)):
        print("  ", tag, " ".join(f"{n}:{ln}={v:+.2f}" for n, ln, o, v in L[j][2] if o is None or abs(v - o) > 0.02))
