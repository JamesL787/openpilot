# sim_kit: Bob's closed-loop longitudinal replay, packaged to run on another machine

Replay only. Nothing here is road evidence. Report results as "replay" (AGENTS.md).

## What is here
- `closed_loop.py`: the replay harness. For each event window, every candidate planner drives its own fitted car plant from T0,
  fed by the logged radar and model. It writes a pickle of per-frame rows.
- `car/longitudinal_planner.py` (+ `longitudinal_lead.py`, `blotv3.py`): the planner that was in the car for 2a6/2a4
  (build 87505f426). This is the default `CAR_LP`.
- `car/longitudinal_planner_d073.py`: the same planner plus D-073 (`EXP_CLOSE_RATE` env, default 1.5). Set `CAR_LP=` to this path.
- `plant/`:
  - `plant.py` + `plant_params.json` (table plant; the default, and the one used for stop work).
  - `plant_bp.py` + `plant_params_bpos.json` (Steve's brake-overshoot plant, used for jab work).
  - `plant_params_bpos2.json` (harsh-side bracket only).
  - Select the bp plant with `PLANT_MODULE=plant_bp PLANT_PARAMS=<kit>/plant/plant_params_bpos.json`.
- `events/`:
  - `ev_2a6.json`, `ev_2a4.json`: the 14 jab and real-brake windows.
  - `ev_need.json`: 12 windows on 283/2a4/280/278/293/2a6/297.
  - Route paths inside are resolved as `$ROUTES/<route-name>`.
- `open_loop_fleet.py`: open-loop fleet sweep. `VARIANTS=name=planner.py,...`, args `ROUTE_DIR OUT.npz`.
- `score.py`: metrics per event; `--ref reference/expected.json KEY` diffs against Bob's results.
- `reference/expected.json`: Bob's numbers. Keys are `<events>/<plant>/<candidate>`. D073 means `CAR_LP=car/longitudinal_planner_d073.py`, CANDS=BASE.

## Not in git (delivered separately once Peter approves a transfer method)
- Route logs: 000002a6--f5f92c6f78, 000002a4--4736f8e372, 00000283--fe4e75f88b, 00000280--d02d9c2f8e, 00000278--8f101d683e,
  00000293--9d152a3cdc, 00000297--f971b5896f. Point `ROUTES` at their parent directory.
- Params snapshots: `params_2a6`, `params_2a4` (the car's params at those drives) and `params_car` (2026-09-30). These hold device
  identity and API keys, so they never go in git. Set `PARAMS_ROOT=` to the snapshot dir.

## Run (from the repo root)
    K=tools/longitudinal/sim_kit
    export PYTHONPATH=.:opendbc_repo:tools ROUTES=/path/to/routes
    # today's planner + chill reference, table plant
    CANDS=BASE,ACC PARAMS_ROOT=/path/params_2a6 python $K/closed_loop.py $K/events/ev_2a6.json out/x_2a6.pkl
    # D-073 planner
    CAR_LP=$K/car/longitudinal_planner_d073.py CANDS=BASE PARAMS_ROOT=/path/params_2a6 python $K/closed_loop.py $K/events/ev_2a6.json out/v3_2a6.pkl
    python $K/score.py out/x_2a6.pkl BASE --ref $K/reference/expected.json ev_2a6/plant/BASE
- `ev_need.json` uses `PARAMS_ROOT=params_car`.
- The first line of the harness output starts with `CHECK planner ...`. It must name the kit's planner file.

## Validation before real work
Reproduce `ev_2a6/plant/BASE`, `ev_2a6/plant/D073`, `ev_2a4/plant/BASE`, `ev_2a4/plant/D073`, then `ev_need/plant/BASE`.
WORST diff should be < 0.05 (Bob's own kit run reproduces 0.000). If it is larger, report it before anything else:
- x86 vs aarch64 acados differences
- params mismatch
- a different repo head for `tools/longitudinal/alpha_*_replay.py`

## SGSP (starpilot/SecretGoodStarPilot) planner, closed loop (2026-10-17)
- `closed_loop_sgsp.py EVENTS.json OUT.pkl [ev,ev]`: the SGSP longitudinal planner on the logged radarState (our radar parser) and
  modelV2, on the same plant and stopping model as `closed_loop.py`. Same rows, so `score.py` and `sgsp_tools/compare.py` read both.
  SGSP runs out of the box: every `update()` kwarg at its default, personality and Experimental Mode from the logged selfdriveState.
- `sgsp_loader.py`: loads `openpilot.*` from `sgsp/openpilot` (extract, `sgsp_tools/closure.py`; missing modules are fetched on first
  use with `git show`) and `opendbc` from `sgsp/opendbc_extra` (`git archive starpilot/SecretGoodStarPilot opendbc_repo/opendbc`,
  with `car/structs.py` patched to `from cereal import car` to avoid a duplicate capnp ID).
- Needs `git fetch starpilot SecretGoodStarPilot` and the x86_64 MPC build: `sgsp_tools/build_mpc.sh` (the .so files are gitignored).
- Run: `LD_LIBRARY_PATH=$PWD/third_party/acados/x86_64/lib PYTHONPATH=.:tools:third_party/acados .venv/bin/python
  tools/longitudinal/sim_kit/closed_loop_sgsp.py <events> <out.pkl>` (no `opendbc_repo` on PYTHONPATH; one process per family).
- `events/ev_332_sgsp.json`: 8 windows on 00000332--e7efb3fe17 (car build dc8a4215 = `car/longitudinal_planner_dc8a4215.py`; run it
  with `CAR_LIBS= MPC_QP_CAP_RESOLVE=0`).
- `STOP_SNAP` (default 1, both harnesses): below 0.05 m/s the plant holds a = 0, so the sim v froze at ~0.048 m/s and crept into the
  lead. It now snaps to 0. Set `STOP_SNAP=0` to reproduce numbers from before 2026-10-17.
- Known limit: in Experimental Mode the model plan comes from the log and is not recomputed for the sim car. When the sim drifts from
  the drive, a planner that follows the model follows the logged decel (332_07, 49-55 s).
