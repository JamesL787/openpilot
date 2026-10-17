import glob,os,pickle,sys,numpy as np
O=os.path.expanduser("~/longsim_frames/sgsp")
for f in sys.argv[1].split(","):
  out=[]
  for p in sorted(glob.glob(f"{O}/r_{f}_*.pkl")):
    for k,d in pickle.load(open(p,"rb")).items():
      r=[x for x in d["rows"] if x["out"].get("OLBASE")]
      t=np.array([x["t"] for x in r]); u=np.array([x["out"]["OLBASE"][0] for x in r])
      tt=np.arange(t[0],t[-1],0.05); U=np.interp(tt,t,u); j=np.diff(U)/0.05
      out.append((k[-2:],np.sqrt(np.mean(j**2)),np.percentile(np.abs(j),99),U.min()))
  print(f"{f:5}"," ".join(f"{k}:{a:.2f}/{b:.1f}/{m:.2f}" for k,a,b,m in out),"med",f"{np.median([o[1] for o in out]):.2f}")
