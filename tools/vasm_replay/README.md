# V-ASM driver-camera replay (D-118 evidence)

Replays the V-ASM model on every driver-camera frame of a route and compares it with radar adjacent leads.
Route data is never committed. Put it in a scratch dir `S` as `S/dm/<route>/<seg>/{rlog.zst,dcamera.hevc}`:

    python3 tools/konik_fetch.py --route 'DONGLE|ROUTE' --out $S/dm --segments 30,31
    python3 tools/konik_fetch.py --route 'DONGLE|ROUTE' --out $S/dm --segments 30,31 --dcameras

Run each script in the arm64 test image with the scratch dir mounted at /work (Colima cannot see the Mac's /tmp):

    docker run --rm --platform linux/arm64 -v "$PWD":/src/openpilot:ro -v $S:/work -e PYTHONPATH=/src:/src/openpilot \
      oprad-test:py312 bash -lc 'export PATH=/opt/venv/bin:$PATH; pip install -q av opencv-python-headless; cd /src/openpilot/tools/vasm_replay;
      python rlog_extract.py && python conf_replay.py && python events.py && python daemon_sim.py && python hold_eval.py'

| script | output |
|---|---|
| `rlog_extract.py` | `ex_<route>_<seg>.json`: V-ASM params from initData, driver frame times, radar adjacent leads, ego state |
| `conf_replay.py` | `conf_<route>_<seg>.npy`: raw model confidence, both image sides, every frame (~3 min/segment) |
| `events.py` | per pass event: where radar lost the car, and camera confidence per second around it |
| `daemon_sim.py` | the daemon's 1 s side alternation vs per-frame camera truth, with and without D-118 focus |
| `hold_eval.py` | the real `PassHold` on rlog radar, with each hold checked against the camera |
| `overtaken.py` | vehicles overtaking us: where radar first sees them, and camera confidence before that |
| `zoom.py NAME IMGSIDE T0 T1 STEP` | contact sheet of crops with confidence, plus radar on that side |

The driver camera is mirrored, so image left is car right.
